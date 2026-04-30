#!/usr/bin/env bash
# scripts/github_import_from_export.sh — shell driver for GitHub Issues +
# GitHub Projects v2 import from
# `analysis/handoff/backlog_export_github.csv` (v1.1.17, Sprint 1 / T5).
#
# Uses `gh` CLI natively (already installed in most developer /
# CI environments; `gh` handles auth via `gh auth login` OR
# GH_TOKEN env var). `gh` is the canonical GitHub client and
# wraps both the REST (issues) AND GraphQL v4 (Projects v2) APIs,
# so this driver handles both halves that the Python impl splits
# (issues-only in backlog_live_apply.py, Projects v2 manual).
#
# Dependencies:
#   bash 3.2+ (macOS default works), gh (1.14+ for Projects v2),
#   Python 3 (for CSV parsing). gh handles JSON serialization itself;
#   no jq required in happy path.
#
# Auth: `gh auth status` must show a logged-in account OR
# GH_TOKEN / GITHUB_TOKEN must be set with the required scopes
# (`repo`, `project`).
#
# Exit codes:
#   0 — all rows OK.
#   1 — partial failure.
#   2 — invocation error.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: github_import_from_export.sh [--workspace DIR] [--export PATH]
                                    [--apply] [--repo OWNER/NAME]
                                    [--canon-hash HEX]
                                    [--project-owner OWNER]
                                    [--project-number N]
                                    [-h|--help]

Required for --apply:
  Either `gh auth status` shows a logged-in account, OR
  $GH_TOKEN / $GITHUB_TOKEN is set.

  --repo OWNER/NAME       — Target repo for `gh issue create`.

Optional (for Projects v2 attachment):
  --project-owner OWNER   — Org / user that owns the Project.
  --project-number N      — Numeric Project ID (see `gh project list`).

Other:
  --workspace DIR         — BSA workspace root. Default: $PWD.
  --export PATH           — Default:
                            <workspace>/analysis/handoff/backlog_export_github.csv
  --apply                 — Default: dry-run.
  --canon-hash HEX        — v1.4.9 (rec #5): 8 lowercase hex chars
                            matching .claude-plugin/canon_policy.json
                            hash_prefix. REQUIRED when --apply (matches
                            Python contract). Auto-detected from
                            `<workspace>/.claude-plugin/canon_policy.json`
                            when --apply set without --canon-hash.

Example:
  export GH_TOKEN=ghp_...
  bash scripts/github_import_from_export.sh \\
    --workspace /path/to/ws \\
    --repo acme/backlog \\
    --project-owner acme \\
    --project-number 42 \\
    --apply
EOF
}

WORKSPACE="${PWD}"
EXPORT_PATH=""
REPO=""
PROJECT_OWNER=""
PROJECT_NUMBER=""
APPLY=0
CANON_HASH=""  # v1.4.9 rec #5: unified idempotency key format.

while [ $# -gt 0 ]; do
  case "$1" in
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --export) EXPORT_PATH="$2"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    --repo) REPO="$2"; shift 2 ;;
    --canon-hash) CANON_HASH="$2"; shift 2 ;;
    --project-owner) PROJECT_OWNER="$2"; shift 2 ;;
    --project-number) PROJECT_NUMBER="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[github_import] unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for cmd in gh python3; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "[github_import] missing dependency: ${cmd}" >&2
    exit 2
  fi
done

if [ -z "${EXPORT_PATH}" ]; then
  EXPORT_PATH="${WORKSPACE}/analysis/handoff/backlog_export_github.csv"
fi
if [ ! -f "${EXPORT_PATH}" ]; then
  echo "[github_import] export file not found: ${EXPORT_PATH}" >&2
  exit 2
fi
# v1.1.17 round-3 (Codex HIGH): SEPARATE state file from Python impl
# (see jira_import_from_export.sh for full rationale).
STATE_PATH="${WORKSPACE}/analysis/handoff/live_api_response_github_shell.json"

if [ "${APPLY}" = "1" ]; then
  if [ -z "${REPO}" ]; then
    echo "[github_import] --apply requires --repo OWNER/NAME" >&2
    exit 2
  fi
  # Verify gh is authenticated (either gh auth OR GH_TOKEN env).
  if ! gh auth status >/dev/null 2>&1 && [ -z "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]; then
    echo "[github_import] gh is not authenticated; run 'gh auth login' or set GH_TOKEN." >&2
    exit 2
  fi
fi

# v1.4.9 rec #5: resolve canon-hash. Operator may pass --canon-hash
# explicitly (matches Python contract); fallback auto-detects from
# `<workspace>/.claude-plugin/canon_policy.json`.
if [ -z "${CANON_HASH}" ]; then
  CANON_POLICY_PATH="${WORKSPACE}/.claude-plugin/canon_policy.json"
  if [ -f "${CANON_POLICY_PATH}" ] && command -v jq >/dev/null 2>&1; then
    CANON_HASH=$(jq -r '.hash_prefix // empty' "${CANON_POLICY_PATH}" 2>/dev/null || true)
  fi
fi
if [ "${APPLY}" = "1" ]; then
  # v1.4.9 R1 MAJOR #1 fix: see jira_import_from_export.sh.
  if [ "${#CANON_HASH}" -ne 8 ]; then
    echo "[github_import] --apply requires --canon-hash with EXACTLY 8 lowercase hex chars (got len ${#CANON_HASH}: '${CANON_HASH}'). Pass it explicitly OR ensure ${WORKSPACE}/.claude-plugin/canon_policy.json carries hash_prefix." >&2
    exit 2
  fi
  case "${CANON_HASH}" in
    [a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9]) ;;
    *)
      echo "[github_import] --apply requires --canon-hash with 8 lowercase hex chars (got: '${CANON_HASH}'). Allowed: 0-9 a-f only." >&2
      exit 2
      ;;
  esac
fi

# --- CSV parse helper (same shape as linear driver) ---
# v1.1.17 round-2 (Codex SHOULD #2): sanitize tabs/newlines in
# StoryID/Title before emitting TSV (see linear driver comment).
parse_csv_rows() {
  python3 - "$1" <<'PY'
import csv, json, sys, re
path = sys.argv[1]
SANITIZE_RE = re.compile(r"[\t\r\n]+")
def sanitize(s: str) -> str:
    return SANITIZE_RE.sub(" ", s).strip()
with open(path, newline='', encoding='utf-8') as fh:
    reader = csv.DictReader(fh)
    for row in reader:
        story = sanitize(row.get("StoryID", ""))
        title = sanitize(row.get("Title", ""))
        print(f"{story}\t{title}\t{json.dumps(row)}")
PY
}

ROW_COUNT=$(parse_csv_rows "${EXPORT_PATH}" | wc -l | tr -d ' ')
echo "[github_import] export: ${EXPORT_PATH}"
echo "[github_import] rows: ${ROW_COUNT}"
echo "[github_import] mode: $([ "${APPLY}" = "1" ] && echo APPLY || echo DRY-RUN)"
echo "[github_import] state: ${STATE_PATH}"

# macOS bash 3.2 lacks `declare -A`; use a tmpfile + grep instead.
# v1.1.17 round-3 (Codex HIGH): state lives at the shell-only
# *_shell.json path (separate from Python's F5-validated canonical
# `live_api_response_<plat>.json`). Accept BOTH `.results[]/.status`
# AND legacy `.rows[]/.outcome` on read; always WRITE current shape.
DONE_KEYS_FILE="$(mktemp -t bsa_github_done.XXXXXX)"
done_count=0
# v1.4.9 rec #5: cross-read both state files (shell + Python). With
# the unified key format `bsa-{StoryID}-{canon_hash_prefix}`, prior
# runs from EITHER driver are recognized.
PYTHON_STATE_PATH="${WORKSPACE}/analysis/handoff/live_api_response_github.json"
for read_path in "${STATE_PATH}" "${PYTHON_STATE_PATH}"; do
  if [ -f "${read_path}" ]; then
    python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    # v1.4.9 R1 MAJOR #3 fix: prefilter by .platform field. A
    # misplaced state file (e.g. linear renamed to *_github*) must
    # not poison this run. Files without .platform accepted (legacy).
    plat = d.get('platform')
    if plat is not None and plat != 'github':
        sys.exit(0)
    keys = set()
    for row in d.get('results', []):
        if isinstance(row, dict) and row.get('status') in ('created', 'skipped'):
            k = row.get('idempotency_key')
            if k:
                keys.add(k)
    for row in d.get('rows', []):  # legacy round-1 shape
        if isinstance(row, dict) and row.get('outcome') in ('created', 'already_exists'):
            k = row.get('idempotency_key')
            if k:
                keys.add(k)
    for k in sorted(keys):
        print(k)
except Exception:
    pass
" "${read_path}" 2>/dev/null >> "${DONE_KEYS_FILE}" || true
  fi
done
if [ -s "${DONE_KEYS_FILE}" ]; then
  sort -u "${DONE_KEYS_FILE}" -o "${DONE_KEYS_FILE}"
  done_count=$(wc -l < "${DONE_KEYS_FILE}" | tr -d ' ')
  echo "[github_import] prior state: ${done_count} already-succeeded row(s) will be skipped (read from shell + python state files)."
fi

is_already_done() {
  grep -Fxq "$1" "${DONE_KEYS_FILE}" 2>/dev/null
}

SUCCEEDED=0
SKIPPED=0
FAILED=0
FAILED_KEYS=()
OUTCOMES=()

# v1.1.17 round-1 (Codex P1): extend EXIT trap to cover per-row
# error tmpfile. `gh` does NOT leak auth via argv (reads from
# env/keychain/config) so no separate AUTH_TMP needed.
cleanup_all() {
  rm -f "${DONE_KEYS_FILE}" /tmp/gh_err_$$.txt 2>/dev/null || true
}
# v1.1.17 round-2 (Codex MEDIUM): trap signals so tmpfiles are
# cleaned even on Ctrl-C / kill (bash 3.2 doesn't run EXIT then).
trap cleanup_all EXIT INT TERM

while IFS=$'\t' read -r story_id title row_json; do
  [ -z "${story_id}" ] && continue
  # v1.4.9 rec #5: unified key format (see jira / linear drivers).
  if [ -n "${CANON_HASH}" ]; then
    idem_key="bsa-${story_id}-${CANON_HASH}"
  else
    idem_key="bsa-${story_id}-dryrun"
  fi

  if is_already_done "${idem_key}"; then
    echo "  [SKIP] ${story_id}: already-created"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  if [ "${APPLY}" = "0" ]; then
    echo "  [DRY-RUN] would gh-issue-create: ${story_id} — ${title:0:60}..."
    SUCCEEDED=$((SUCCEEDED + 1))
    continue
  fi

  # Extract body + labels via python3 (avoid jq dep).
  body=$(printf '%s' "${row_json}" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('Body', ''))")
  labels=$(printf '%s' "${row_json}" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('Labels', ''))")

  issue_url=$(gh issue create \
    --repo "${REPO}" \
    --title "${title}" \
    --body "${body}" \
    --label "${labels}" 2>/tmp/gh_err_$$.txt || true)
  if [ -z "${issue_url}" ]; then
    echo "  [FAIL] ${story_id}: gh issue create failed" >&2
    cat /tmp/gh_err_$$.txt >&2
    rm -f /tmp/gh_err_$$.txt
    FAILED=$((FAILED + 1))
    FAILED_KEYS+=("${idem_key}")
    continue
  fi
  rm -f /tmp/gh_err_$$.txt

  # Optional: attach to Projects v2 board.
  if [ -n "${PROJECT_OWNER}" ] && [ -n "${PROJECT_NUMBER}" ]; then
    if gh project item-add "${PROJECT_NUMBER}" --owner "${PROJECT_OWNER}" --url "${issue_url}" >/dev/null 2>&1; then
      echo "  [OK] ${story_id} → ${issue_url} + Project #${PROJECT_NUMBER}"
    else
      echo "  [OK] ${story_id} → ${issue_url} (Project attach failed; attach manually)"
    fi
  else
    echo "  [OK] ${story_id} → ${issue_url}"
  fi
  SUCCEEDED=$((SUCCEEDED + 1))
  OUTCOMES+=("${idem_key}|created|${story_id}|1")
done < <(parse_csv_rows "${EXPORT_PATH}")

# State writeback — `.results[]/.status` shape (v1.1.17 round-3:
# shell-only state at *_shell.json path, separate from Python's
# F5-validated canonical path); tmpfile in same FS as STATE_PATH
# (round-2 MEDIUM: atomic mv guarantee).
if [ "${APPLY}" = "1" ] && [ ${#OUTCOMES[@]} -gt 0 ]; then
  state_dir="$(dirname "${STATE_PATH}")"
  mkdir -p "${state_dir}"
  state_new="$(mktemp "${state_dir}/.bsa_github_state.XXXXXX")"
  python3 - "${STATE_PATH}" "${state_new}" "github" "${OUTCOMES[@]}" <<'PY'
import json, sys, os, time
prior_path, new_path, platform, *outcomes = sys.argv[1:]
prior = {"platform": platform, "results": []}
if os.path.isfile(prior_path):
    try:
        with open(prior_path) as fh:
            prior = json.load(fh)
    except Exception:
        pass
if not isinstance(prior, dict):
    prior = {"platform": platform, "results": []}
# v1.4.9 R2 NEW MAJOR fix: discard prior rows when platform mismatches
# (misplaced/poisoned file); force-set platform on writeback.
prior_platform = prior.get("platform")
if prior_platform is not None and prior_platform != platform:
    prior = {"platform": platform, "results": []}
else:
    prior["platform"] = platform
existing = prior.get("results")
if not isinstance(existing, list):
    existing = []
legacy_rows = prior.get("rows")
if isinstance(legacy_rows, list):
    for r in legacy_rows:
        if not isinstance(r, dict):
            continue
        existing.append({
            "story_id": r.get("story_id", ""),
            "idempotency_key": r.get("idempotency_key", ""),
            "status": r.get("outcome", ""),
        })
prior["results"] = existing
prior.pop("rows", None)
by_key = {
    r.get("idempotency_key"): r
    for r in prior["results"] if isinstance(r, dict) and r.get("idempotency_key")
}
now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
for spec in outcomes:
    parts = spec.split("|")
    idem, status, story = parts[0], parts[1], parts[2]
    attempts = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
    by_key[idem] = {
        "story_id": story, "idempotency_key": idem, "status": status,
        "attempts": attempts, "updated_at": now, "driver": "shell",
    }
prior["results"] = sorted(by_key.values(), key=lambda r: r["idempotency_key"])
with open(new_path, "w") as fh:
    json.dump(prior, fh, indent=2)
PY
  mv "${state_new}" "${STATE_PATH}"
fi

echo ""
echo "[github_import] summary: ${SUCCEEDED} ok, ${SKIPPED} skipped, ${FAILED} failed (total ${ROW_COUNT})"
if [ ${FAILED} -gt 0 ]; then
  printf '%s\n' "${FAILED_KEYS[@]}" >&2
  exit 1
fi
exit 0
