#!/usr/bin/env bash
# scripts/linear_import_from_export.sh — shell driver for Linear GraphQL
# import from `analysis/handoff/backlog_export_linear.csv`
# (v1.1.17, Sprint 1 / T5).
#
# Mirrors scripts/jira_import_from_export.sh but for Linear's GraphQL
# API + CSV export format.
#
# Dependencies:
#   bash 3.2+ (macOS default works), jq, curl, Python 3 (for robust
#   CSV parsing — Linear's Description column contains markdown with
#   embedded commas + is RFC-4180 quoted; pure bash parsing is too
#   fragile).
#
# Auth: Linear API key via `--token-env=BSA_LINEAR_TOKEN`; sent as
# `Authorization: <token>` header (Linear convention; NOT Bearer).
#
# Exit codes:
#   0 — all rows OK (or dry-run).
#   1 — partial failure.
#   2 — invocation error.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: linear_import_from_export.sh [--workspace DIR] [--export PATH]
                                    [--apply] [--team-id ID]
                                    [--canon-hash HEX] [--token-env VAR]
                                    [--timeout SEC] [--max-retries N]
                                    [-h|--help]

Required env vars:
  $BSA_LINEAR_TOKEN  — Linear API key (starts with "lin_api_...").

Optional:
  --workspace DIR    — BSA workspace root. Default: $PWD.
  --export PATH      — Default:
                       <workspace>/analysis/handoff/backlog_export_linear.csv
  --apply            — Actually POST. Default: dry-run.
  --team-id ID       — Linear team UUID. Required for --apply.
  --canon-hash HEX   — v1.4.9 (rec #5 unified idempotency): 8 lowercase
                       hex chars matching .claude-plugin/canon_policy.json
                       hash_prefix. REQUIRED when --apply (matches
                       Python backlog_live_apply.py contract).
                       Idempotency key format becomes
                       `bsa-{StoryID}-{HEX}` — same as Python — so the
                       two drivers no longer collide on the same key
                       space. Auto-detected from
                       `<workspace>/.claude-plugin/canon_policy.json`
                       when --apply set without --canon-hash.
  --token-env VAR    — Env var with API key. Default: BSA_LINEAR_TOKEN.
  --timeout SEC      — Default: 30.
  --max-retries N    — Default: 5.

Example:
  export BSA_LINEAR_TOKEN='lin_api_...'
  bash scripts/linear_import_from_export.sh \\
    --workspace /path/to/ws \\
    --team-id <linear-team-uuid> \\
    --apply
EOF
}

# --- defaults ---
WORKSPACE="${PWD}"
EXPORT_PATH=""
TEAM_ID=""
APPLY=0
TIMEOUT=30
MAX_RETRIES=5
TOKEN_ENV="BSA_LINEAR_TOKEN"
CANON_HASH=""  # v1.4.9 rec #5: unified idempotency key format.

while [ $# -gt 0 ]; do
  case "$1" in
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --export) EXPORT_PATH="$2"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    --team-id) TEAM_ID="$2"; shift 2 ;;
    --canon-hash) CANON_HASH="$2"; shift 2 ;;
    --token-env) TOKEN_ENV="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --max-retries) MAX_RETRIES="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[linear_import] unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for cmd in jq curl python3; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "[linear_import] missing dependency: ${cmd}" >&2
    exit 2
  fi
done

if [ -z "${EXPORT_PATH}" ]; then
  EXPORT_PATH="${WORKSPACE}/analysis/handoff/backlog_export_linear.csv"
fi
if [ ! -f "${EXPORT_PATH}" ]; then
  echo "[linear_import] export file not found: ${EXPORT_PATH}" >&2
  exit 2
fi
# v1.1.17 round-3 (Codex HIGH): SEPARATE state file from Python impl
# (see jira_import_from_export.sh for full rationale).
STATE_PATH="${WORKSPACE}/analysis/handoff/live_api_response_linear_shell.json"

if [ "${APPLY}" = "1" ]; then
  if [ -z "${TEAM_ID}" ]; then
    echo "[linear_import] --apply requires --team-id" >&2
    exit 2
  fi
  if [ -z "${!TOKEN_ENV:-}" ]; then
    echo "[linear_import] env var ${TOKEN_ENV} is empty" >&2
    exit 2
  fi
fi

# v1.4.9 rec #5: resolve canon-hash. Operator may pass --canon-hash
# explicitly (matches Python contract); fallback auto-detects from
# `<workspace>/.claude-plugin/canon_policy.json` so an operator who
# already configured the workspace doesn't have to repeat the value.
if [ -z "${CANON_HASH}" ]; then
  CANON_POLICY_PATH="${WORKSPACE}/.claude-plugin/canon_policy.json"
  if [ -f "${CANON_POLICY_PATH}" ]; then
    CANON_HASH=$(jq -r '.hash_prefix // empty' "${CANON_POLICY_PATH}" 2>/dev/null || true)
  fi
fi
# Validate when --apply (idempotency keys MUST be present in real
# runs; dry-run can skip the check since we won't write state).
if [ "${APPLY}" = "1" ]; then
  # v1.4.9 R1 MAJOR #1 fix: see jira_import_from_export.sh.
  if [ "${#CANON_HASH}" -ne 8 ]; then
    echo "[linear_import] --apply requires --canon-hash with EXACTLY 8 lowercase hex chars (got len ${#CANON_HASH}: '${CANON_HASH}'). Pass it explicitly OR ensure ${WORKSPACE}/.claude-plugin/canon_policy.json carries hash_prefix." >&2
    exit 2
  fi
  case "${CANON_HASH}" in
    [a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9]) ;;
    *)
      echo "[linear_import] --apply requires --canon-hash with 8 lowercase hex chars (got: '${CANON_HASH}'). Allowed: 0-9 a-f only." >&2
      exit 2
      ;;
  esac
fi

scrub() {
  sed -E 's/lin_api_[A-Za-z0-9+/=_-]+/[REDACTED]/g; s/[A-Za-z0-9+/=_-]{40,}/[REDACTED]/g'
}

# --- parse CSV via python3 (-c inline — keeps the shell driver simple
# but avoids CSV-quoting bugs bash 'while read' is notorious for) ---
#
# v1.1.17 round-2 (Codex SHOULD #2): sanitize tabs/newlines in StoryID
# and Title before emitting to the TSV stream. The schemas don't
# explicitly forbid these chars in title fields; rather than rely on
# upstream validation, we collapse \t/\r/\n → space here so the bash
# `read -r` loop cannot desync. row_json uses json.dumps which already
# escapes tabs/newlines as \t/\n inside the string, so the third
# field is always single-line.
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
echo "[linear_import] export: ${EXPORT_PATH}"
echo "[linear_import] rows: ${ROW_COUNT}"
echo "[linear_import] mode: $([ "${APPLY}" = "1" ] && echo APPLY || echo DRY-RUN)"
echo "[linear_import] state: ${STATE_PATH}"

# macOS bash 3.2 lacks `declare -A`; use a tmpfile + grep instead.
# v1.1.17 round-3 (Codex HIGH): accept BOTH `.results[]/.status` (current
# shell shape) AND legacy round-1 `.rows[]/.outcome` on read; always
# WRITE the current shape. NOTE: this state file is at the shell-only
# `*_shell.json` path (separate from Python's F5-validated canonical
# `live_api_response_<plat>.json`). See file-header comment.
DONE_KEYS_FILE="$(mktemp -t bsa_linear_done.XXXXXX)"
done_count=0
# v1.4.9 rec #5: cross-read both state files. Accept idempotency
# keys from EITHER the shell driver's own state (this file) OR the
# Python driver's canonical state at `live_api_response_<plat>.json`
# (no F5 schema check on the foreign read; we just extract keys).
# Together with the unified key format, this lets operators switch
# drivers mid-engagement without re-creating issues.
PYTHON_STATE_PATH="${WORKSPACE}/analysis/handoff/live_api_response_linear.json"
for read_path in "${STATE_PATH}" "${PYTHON_STATE_PATH}"; do
  if [ -f "${read_path}" ]; then
    # v1.4.9 R1 MAJOR #3 + R2 NEW MAJOR fix: see jira driver. Use
    # explicit null check (jq's `//` also defaults on `false`).
    jq -r '
      if (.platform == null or .platform == "linear") then
        (.results[]? | select(.status=="created" or .status=="skipped") | .idempotency_key),
        (.rows[]? | select(.outcome=="created" or .outcome=="already_exists") | .idempotency_key)
      else
        empty
      end
    ' "${read_path}" 2>/dev/null >> "${DONE_KEYS_FILE}" || true
  fi
done
# Dedupe across both state files.
if [ -s "${DONE_KEYS_FILE}" ]; then
  sort -u "${DONE_KEYS_FILE}" -o "${DONE_KEYS_FILE}"
  done_count=$(wc -l < "${DONE_KEYS_FILE}" | tr -d ' ')
  echo "[linear_import] prior state: ${done_count} already-succeeded row(s) will be skipped (read from shell + python state files)."
fi

is_already_done() {
  grep -Fxq "$1" "${DONE_KEYS_FILE}" 2>/dev/null
}

SUCCEEDED=0
SKIPPED=0
FAILED=0
FAILED_KEYS=()
OUTCOMES=()

# v1.1.17 round-1 (Codex CRITICAL): pass Authorization header via
# curl -K configfile (not via -H on the argv) to avoid leaking the
# token via `ps`/`/proc`.
#
# v1.1.17 round-3 (Codex MEDIUM): trap registered BEFORE AUTH_TMP
# population to close the small pre-trap leak window.
AUTH_TMP=""
cleanup_all() {
  rm -f "${DONE_KEYS_FILE}" "${AUTH_TMP:-}" /tmp/linear_resp_$$.json 2>/dev/null || true
}
trap cleanup_all EXIT INT TERM
if [ "${APPLY}" = "1" ]; then
  AUTH_TMP="$(mktemp -t bsa_linear_auth.XXXXXX)"
  chmod 600 "${AUTH_TMP}"
  printf 'header = "Authorization: %s"\n' "${!TOKEN_ENV}" > "${AUTH_TMP}"
fi

while IFS=$'\t' read -r story_id title row_json; do
  [ -z "${story_id}" ] && continue
  # v1.4.9 rec #5: unified key format `bsa-{StoryID}-{canon_hash}`
  # — same as Python backlog_live_apply.py:_make_idempotency_key.
  # Removes the `-sh-{sha256-of-story-summary}` divergence so a
  # workspace can switch between Python and shell drivers without
  # re-creating issues.
  if [ -n "${CANON_HASH}" ]; then
    idem_key="bsa-${story_id}-${CANON_HASH}"
  else
    # Dry-run without canon-hash: build a placeholder key (won't be
    # written anywhere; only used in [DRY-RUN] log).
    idem_key="bsa-${story_id}-dryrun"
  fi

  if is_already_done "${idem_key}"; then
    echo "  [SKIP] ${story_id}: already-created (idem=${idem_key})"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  if [ "${APPLY}" = "0" ]; then
    echo "  [DRY-RUN] would issueCreate: ${story_id} — ${title:0:60}..."
    SUCCEEDED=$((SUCCEEDED + 1))
    continue
  fi

  # Build Linear GraphQL mutation with the row fields.
  description=$(echo "${row_json}" | jq -r '.Description')
  gql_payload=$(jq -n \
    --arg teamId "${TEAM_ID}" \
    --arg title "${title}" \
    --arg description "${description}" \
    '{
      query: "mutation CreateIssue($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { id identifier } } }",
      variables: {
        input: {
          teamId: $teamId,
          title: $title,
          description: $description
        }
      }
    }')

  attempt=1
  rc=1
  while [ ${attempt} -le ${MAX_RETRIES} ]; do
    http_status=$(
      printf '%s' "${gql_payload}" | \
      curl -sS -o /tmp/linear_resp_$$.json -w "%{http_code}" \
        -X POST "https://api.linear.app/graphql" \
        -K "${AUTH_TMP}" \
        -H "Content-Type: application/json" \
        --max-time "${TIMEOUT}" \
        -d @- 2>/dev/null || echo "000"
    )
    case "${http_status}" in
      200)
        # Linear always returns 200 — check GraphQL success AND no errors.
        success=$(jq -r '.data.issueCreate.success // false' /tmp/linear_resp_$$.json 2>/dev/null)
        has_errors=$(jq -r '.errors | length > 0' /tmp/linear_resp_$$.json 2>/dev/null)
        if [ "${success}" = "true" ] && [ "${has_errors}" != "true" ]; then
          rc=0
          break
        fi
        err_body=$(cat /tmp/linear_resp_$$.json | scrub)
        echo "  [FAIL] ${story_id}: GraphQL returned success=${success}, errors=${has_errors}" >&2
        echo "    ${err_body}" >&2
        rc=1
        break
        ;;
      429|500|502|503|504)
        sleep_s=$(awk "BEGIN{print 2^${attempt}}")
        echo "  [RETRY] ${story_id}: status=${http_status}, attempt ${attempt}/${MAX_RETRIES}, sleep ${sleep_s}s"
        sleep "${sleep_s}"
        attempt=$((attempt + 1))
        ;;
      *)
        echo "  [FAIL] ${story_id}: status=${http_status}" >&2
        rc=1
        break
        ;;
    esac
  done
  rm -f /tmp/linear_resp_$$.json || true
  if [ ${rc} -eq 0 ]; then
    echo "  [OK] ${story_id}"
    SUCCEEDED=$((SUCCEEDED + 1))
    OUTCOMES+=("${idem_key}|created|${story_id}|${attempt}")
  else
    FAILED=$((FAILED + 1))
    FAILED_KEYS+=("${idem_key}")
    OUTCOMES+=("${idem_key}|failed|${story_id}|${attempt}")
  fi
done < <(parse_csv_rows "${EXPORT_PATH}")

# State writeback — `.results[]/.status` shape (v1.1.17 round-3:
# shell-only state at *_shell.json path, not Python's F5-validated
# canonical path); tmpfile in same FS as STATE_PATH (round-2 Codex
# MEDIUM: atomic mv guarantee).
if [ "${APPLY}" = "1" ] && [ ${#OUTCOMES[@]} -gt 0 ]; then
  state_dir="$(dirname "${STATE_PATH}")"
  mkdir -p "${state_dir}"
  state_new="$(mktemp "${state_dir}/.bsa_linear_state.XXXXXX")"
  python3 - "${STATE_PATH}" "${state_new}" "linear" "${OUTCOMES[@]}" <<'PY'
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
# (misplaced/poisoned file); force-set platform on writeback so
# future runs trust their own state.
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
echo "[linear_import] summary: ${SUCCEEDED} ok, ${SKIPPED} skipped, ${FAILED} failed (total ${ROW_COUNT})"
if [ ${FAILED} -gt 0 ]; then
  echo "[linear_import] failed keys:" >&2
  printf '  %s\n' "${FAILED_KEYS[@]}" >&2
  exit 1
fi
exit 0
