#!/usr/bin/env bash
# scripts/jira_import_from_export.sh — shell driver for Jira REST v3 import
# from `analysis/handoff/backlog_export_jira.json` (v1.1.17, Sprint 1 / T5).
#
# Purpose: provide a bash+jq+curl alternative to the Python
# `scripts/backlog_live_apply.py` for operators whose CI / environment
# doesn't have full Python available (or who just prefer shell).
#
# Contract surface:
#   * Reads the F5-validated Jira export from the default workspace
#     path, OR from --export <path>.
#   * Dry-run by default; --apply required for real POSTs.
#   * Token via env var only (BSA_JIRA_TOKEN + BSA_JIRA_EMAIL);
#     NEVER via CLI arg. Scrubbed from error output.
#   * Idempotent: re-reading a prior live_api_response_jira_shell.json
#     (separate from Python impl path; see v1.1.17 round-3) skips
#     rows whose idempotency key already succeeded.
#   * Partial-failure tolerant: continues after per-row failure,
#     exits 1 at the end if any row failed.
#
# Dependencies:
#   bash 3.2+ (macOS default works), jq (1.6+), curl, coreutils.
#   Python 3 for CSV (not used here — Jira is JSON-only).
#
# Exit codes:
#   0 — all rows OK (or dry-run clean).
#   1 — partial failure: ≥1 row failed post-retry; rest completed.
#   2 — invocation error (missing export, missing env var, jq/curl absent).
#
# Compare: scripts/backlog_live_apply.py (Python impl with fcntl lock,
# exponential backoff, idempotency key derived from canon hash). This
# shell driver is a LIGHTER alternative — no fcntl lock (operator
# responsibility), no F5 validation of the response output (rely on
# Jira-side validation), simpler retry policy.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: jira_import_from_export.sh [--workspace DIR] [--export PATH]
                                  [--apply] [--base-url URL]
                                  [--canon-hash HEX]
                                  [--email-env VAR] [--token-env VAR]
                                  [--timeout SEC] [--max-retries N]
                                  [-h|--help]

Required env vars:
  $BSA_JIRA_EMAIL    — Atlassian account email (basic-auth username).
  $BSA_JIRA_TOKEN    — Atlassian API token (basic-auth password).

Optional:
  --workspace DIR    — BSA workspace root. Default: $PWD.
  --export PATH      — Explicit export path. Default:
                       <workspace>/analysis/handoff/backlog_export_jira.json
  --apply            — Actually POST. Default: dry-run (print plan only).
  --base-url URL     — Jira Cloud base URL, e.g. https://acme.atlassian.net
                       Required for --apply.
  --canon-hash HEX   — v1.4.9 (rec #5): 8 lowercase hex chars matching
                       .claude-plugin/canon_policy.json hash_prefix.
                       REQUIRED when --apply (matches Python contract).
                       Auto-detected from
                       `<workspace>/.claude-plugin/canon_policy.json`
                       when --apply set without --canon-hash.
  --timeout SEC      — Per-request timeout. Default: 30.
  --max-retries N    — Max retry budget per row. Default: 5.
  --email-env VAR    — Env var containing email. Default: BSA_JIRA_EMAIL.
  --token-env VAR    — Env var containing token. Default: BSA_JIRA_TOKEN.

Example:
  export BSA_JIRA_EMAIL='user@example.invalid'
  export BSA_JIRA_TOKEN='ATATT3...'
  bash scripts/jira_import_from_export.sh \\
    --workspace /path/to/bsa/workspace \\
    --base-url https://acme.atlassian.net \\
    --apply
EOF
}

# --- defaults ----------------------------------------------------------

WORKSPACE="${PWD}"
EXPORT_PATH=""
BASE_URL=""
APPLY=0
TIMEOUT=30
MAX_RETRIES=5
EMAIL_ENV="BSA_JIRA_EMAIL"
TOKEN_ENV="BSA_JIRA_TOKEN"
CANON_HASH=""  # v1.4.9 rec #5: unified idempotency key format.

# --- arg parsing -------------------------------------------------------

while [ $# -gt 0 ]; do
  case "$1" in
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --export) EXPORT_PATH="$2"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    --canon-hash) CANON_HASH="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --max-retries) MAX_RETRIES="$2"; shift 2 ;;
    --email-env) EMAIL_ENV="$2"; shift 2 ;;
    --token-env) TOKEN_ENV="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[jira_import] unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# --- dependency check --------------------------------------------------

for cmd in jq curl; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "[jira_import] missing dependency: ${cmd}. Install and retry." >&2
    exit 2
  fi
done

# --- resolve paths -----------------------------------------------------

if [ -z "${EXPORT_PATH}" ]; then
  EXPORT_PATH="${WORKSPACE}/analysis/handoff/backlog_export_jira.json"
fi

if [ ! -f "${EXPORT_PATH}" ]; then
  echo "[jira_import] export file not found: ${EXPORT_PATH}" >&2
  exit 2
fi

# v1.1.17 round-3 (Codex HIGH): shell drivers write to a SEPARATE
# state file from the Python impl (`scripts/backlog_live_apply.py`).
# Reasons:
#   1. Python's state file at live_api_response_jira.json is F5-
#      validated against governance/schemas/live_api_response.schema.json
#      — that schema requires fields shell can't easily produce
#      (operator_run_id pattern, platform_base_url URI, summary block,
#      idempotency_key with the canon-hash-prefix format) AND has
#      `additionalProperties: false` so any shell-emitted extras
#      would be rejected.
#   2. The shell idempotency-key format intentionally differs (`-sh-`
#      infix) so the two tracks cannot collide on the same key space.
# These two facts make true Python↔shell interop infeasible without
# reimplementing the full Python contract in bash. Instead we accept
# the design: SEPARATE state files, operators pick ONE driver per
# workspace, no cross-tool prior-state inheritance.
# See `docs/shell_import_drivers.md` §"State files".
STATE_PATH="${WORKSPACE}/analysis/handoff/live_api_response_jira_shell.json"
LOG_PATH="${WORKSPACE}/analysis/handoff/live_api_log.jsonl"

# --- auth env check (only when --apply) --------------------------------

if [ "${APPLY}" = "1" ]; then
  if [ -z "${BASE_URL}" ]; then
    echo "[jira_import] --apply requires --base-url" >&2
    exit 2
  fi
  if [ -z "${!EMAIL_ENV:-}" ]; then
    echo "[jira_import] env var ${EMAIL_ENV} is empty; set it to the Atlassian account email." >&2
    exit 2
  fi
  if [ -z "${!TOKEN_ENV:-}" ]; then
    echo "[jira_import] env var ${TOKEN_ENV} is empty; set it to an Atlassian API token." >&2
    exit 2
  fi
fi

# v1.4.9 rec #5: resolve canon-hash. Operator may pass --canon-hash
# explicitly (matches Python contract); fallback auto-detects from
# `<workspace>/.claude-plugin/canon_policy.json`.
if [ -z "${CANON_HASH}" ]; then
  CANON_POLICY_PATH="${WORKSPACE}/.claude-plugin/canon_policy.json"
  if [ -f "${CANON_POLICY_PATH}" ]; then
    CANON_HASH=$(jq -r '.hash_prefix // empty' "${CANON_POLICY_PATH}" 2>/dev/null || true)
  fi
fi
if [ "${APPLY}" = "1" ]; then
  # v1.4.9 R1 MAJOR #1 fix: validate the WHOLE variable as a single
  # 8-char lowercase-hex string. Earlier `grep -Eq '^...$'` was line-
  # based and would accept a multiline jq-emitted value whose first
  # line happened to match. Length-check + POSIX case-glob is
  # unambiguous (no regex engine, no multi-line ambiguity).
  if [ "${#CANON_HASH}" -ne 8 ]; then
    echo "[jira_import] --apply requires --canon-hash with EXACTLY 8 lowercase hex chars (got len ${#CANON_HASH}: '${CANON_HASH}'). Pass it explicitly OR ensure ${WORKSPACE}/.claude-plugin/canon_policy.json carries hash_prefix." >&2
    exit 2
  fi
  case "${CANON_HASH}" in
    [a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9]) ;;
    *)
      echo "[jira_import] --apply requires --canon-hash with 8 lowercase hex chars (got: '${CANON_HASH}'). Allowed: 0-9 a-f only." >&2
      exit 2
      ;;
  esac
fi

# --- scrub helper ------------------------------------------------------
# Scrub any token-shape leak from a string (defense-in-depth; curl
# -sS already hides auth headers, but we also scrub our own error
# output just in case a future edit introduces a leak).
scrub() {
  # Replace any base64-looking >=20-char string with [REDACTED].
  # Matches ATATT3* + generic basic-auth base64 payloads.
  sed -E 's/[A-Za-z0-9+/=_-]{20,}/[REDACTED]/g'
}

# --- row count + dry-run output ---------------------------------------

ROW_COUNT=$(jq '.issues | length' "${EXPORT_PATH}")
echo "[jira_import] export: ${EXPORT_PATH}"
echo "[jira_import] rows: ${ROW_COUNT}"
echo "[jira_import] target: ${BASE_URL:-<dry-run>}"
echo "[jira_import] mode: $([ "${APPLY}" = "1" ] && echo APPLY || echo DRY-RUN)"
echo "[jira_import] state: ${STATE_PATH}"
echo "[jira_import] log: ${LOG_PATH}"

# --- load prior state for idempotency ----------------------------------
#
# macOS's default bash is 3.2, which lacks `declare -A` (associative
# arrays). We use a tmpfile + grep instead so the driver stays portable
# across dev laptops + CI runners without requiring a Homebrew bash.
#
# v1.1.17 round-3 (Codex HIGH): shell drivers use a SEPARATE state
# file (`live_api_response_<plat>_shell.json`) from Python. The shell
# state shape is intentionally simpler than the Python F5-validated
# shape — top-level `.results[]` with per-row `.idempotency_key` +
# `.status` (created|skipped|failed). No schema enforcement; this
# file is operator-tooling output, not canonical state.
#
# We accept TWO read shapes for in-place upgrade:
#   * canonical (current): `.results[].status`
#   * legacy round-1:      `.rows[].outcome`
DONE_KEYS_FILE="$(mktemp -t bsa_jira_done.XXXXXX)"
done_count=0
# v1.4.9 rec #5: cross-read both state files. Accept idempotency keys
# from EITHER the shell driver's own state OR the Python driver's
# canonical state at `live_api_response_<plat>.json`. Together with
# the unified key format (bsa-{StoryID}-{canon_hash_prefix}, no more
# `-sh-` infix), this lets operators switch drivers mid-engagement
# without re-creating issues.
PYTHON_STATE_PATH="${WORKSPACE}/analysis/handoff/live_api_response_jira.json"
for read_path in "${STATE_PATH}" "${PYTHON_STATE_PATH}"; do
  if [ -f "${read_path}" ]; then
    # v1.4.9 R1 MAJOR #3 fix: prefilter by `.platform` field to
    # defend against a misplaced/poisoned state file (e.g. a Linear
    # state renamed to *_jira_shell.json) silently suppressing
    # creates for matching StoryIDs across platforms. Files WITHOUT
    # a `platform` field are accepted (legacy v1.1.17 shell state
    # didn't emit it).
    # v1.4.9 R2 NEW MAJOR fix: explicit null check (was `// "jira"`)
    # because jq's `//` operator also defaults on `false`. A
    # poisoned file with `"platform": false` would otherwise pass.
    jq -r '
      if (.platform == null or .platform == "jira") then
        (.results[]? | select(.status=="created" or .status=="skipped") | .idempotency_key),
        (.rows[]? | select(.outcome=="created" or .outcome=="already_exists") | .idempotency_key)
      else
        empty
      end
    ' "${read_path}" 2>/dev/null >> "${DONE_KEYS_FILE}" || true
  fi
done
if [ -s "${DONE_KEYS_FILE}" ]; then
  sort -u "${DONE_KEYS_FILE}" -o "${DONE_KEYS_FILE}"
  done_count=$(wc -l < "${DONE_KEYS_FILE}" | tr -d ' ')
  echo "[jira_import] prior state: ${done_count} already-succeeded row(s) will be skipped (read from shell + python state files)."
fi

is_already_done() {
  # Exact-line match in DONE_KEYS_FILE. Returns 0 (match) or 1 (absent).
  grep -Fxq "$1" "${DONE_KEYS_FILE}" 2>/dev/null
}

# --- process rows ------------------------------------------------------

SUCCEEDED=0
SKIPPED=0
FAILED=0
FAILED_KEYS=()
# Array of "idem_key|outcome" tuples for writeback at the end.
OUTCOMES=()

# v1.1.17 round-1 (Codex CRITICAL): DO NOT pass credentials via curl
# `-u email:token` — argv leaks via `ps`/`/proc` while curl is
# executing. Instead write a 0600-perm curl config file containing
# `user = "email:token"` and pass via `-K`. File is cleaned on EXIT
# trap (defense-in-depth) and per-row after curl returns.
#
# v1.1.17 round-3 (Codex MEDIUM): the trap MUST be registered BEFORE
# AUTH_TMP is populated — earlier ordering had a small leak window
# between mktemp+chmod+write and the trap install.
AUTH_TMP=""
cleanup_all() {
  rm -f "${DONE_KEYS_FILE}" "${AUTH_TMP:-}" \
        /tmp/jira_resp_$$.json /tmp/jira_err_$$.txt 2>/dev/null || true
}
trap cleanup_all EXIT INT TERM
if [ "${APPLY}" = "1" ]; then
  AUTH_TMP="$(mktemp -t bsa_jira_auth.XXXXXX)"
  chmod 600 "${AUTH_TMP}"
  # Embed email + token inside the config; curl reads this instead of
  # taking creds on the command line. Lines must match curl's
  # `--config` syntax (see `man curl` §FILES).
  printf 'user = "%s:%s"\n' "${!EMAIL_ENV}" "${!TOKEN_ENV}" > "${AUTH_TMP}"
fi

# stream each issue + its idempotency key.
# v1.4.9 rec #5: unified key format `bsa-{StoryID}-{canon_hash}` —
# same as Python backlog_live_apply.py:_make_idempotency_key. The
# previous `-sh-{sha256-of-story-summary}` divergence forced operators
# to pick ONE driver per workspace; cross-tool re-runs caused
# duplicate issue creation. Now both drivers share one key space.
while IFS=$'\t' read -r story_id summary raw_issue; do
  if [ -n "${CANON_HASH}" ]; then
    idem_key="bsa-${story_id}-${CANON_HASH}"
  else
    # Dry-run without canon-hash: build a placeholder key (only used
    # in [DRY-RUN] log; never written to state).
    idem_key="bsa-${story_id}-dryrun"
  fi

  if is_already_done "${idem_key}"; then
    echo "  [SKIP] ${story_id} (idem=${idem_key}): prior state shows already-created."
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  if [ "${APPLY}" = "0" ]; then
    echo "  [DRY-RUN] would POST: ${story_id} — ${summary:0:60}..."
    SUCCEEDED=$((SUCCEEDED + 1))
    continue
  fi

  # --- actual POST ---
  attempt=1
  rc=1
  # v1.1.17 round-1 (Codex CRITICAL): Jira POST body is the ENTIRE
  # issue JSON (`{"fields": {...}}`), NOT just `.fields`. The jq
  # emitter below pre-wraps; verify we have the right shape before
  # sending.
  while [ ${attempt} -le ${MAX_RETRIES} ]; do
    http_status=$(
      printf '%s' "${raw_issue}" | \
      curl -sS -o /tmp/jira_resp_$$.json -w "%{http_code}" \
        -X POST "${BASE_URL}/rest/api/3/issue" \
        -K "${AUTH_TMP}" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json" \
        --max-time "${TIMEOUT}" \
        -d @- 2>/tmp/jira_err_$$.txt \
      || echo "000"
    )
    case "${http_status}" in
      201|200)
        rc=0
        break
        ;;
      429|500|502|503|504)
        sleep_s=$(awk "BEGIN{print 2^${attempt}}")
        echo "  [RETRY] ${story_id}: status=${http_status}, attempt ${attempt}/${MAX_RETRIES}, sleep ${sleep_s}s"
        sleep "${sleep_s}"
        attempt=$((attempt + 1))
        ;;
      *)
        err_body=$(cat /tmp/jira_resp_$$.json 2>/dev/null | scrub || true)
        echo "  [FAIL] ${story_id}: status=${http_status}" >&2
        echo "    ${err_body}" >&2
        rc=1
        break
        ;;
    esac
  done
  rm -f /tmp/jira_resp_$$.json /tmp/jira_err_$$.txt || true
  if [ ${rc} -eq 0 ]; then
    echo "  [OK] ${story_id} (idem=${idem_key})"
    SUCCEEDED=$((SUCCEEDED + 1))
    OUTCOMES+=("${idem_key}|created|${story_id}|${attempt}")
  else
    echo "  [FAIL] ${story_id} — retry budget exhausted or non-retryable status" >&2
    FAILED=$((FAILED + 1))
    FAILED_KEYS+=("${idem_key}")
    OUTCOMES+=("${idem_key}|failed|${story_id}|${attempt}")
  fi
done < <(jq -r '.issues[] | [(.bsa_provenance.story_id // (.fields.labels[]? | select(test("^STORY-")))) // "UNKNOWN", .fields.summary, ({fields: .fields} | tojson)] | @tsv' "${EXPORT_PATH}")
# NOTE on the jq filter above:
#   * Extracts StoryID from bsa_provenance.story_id (canonical field
#     per backlog_export_jira.schema.json), falls back to labels for
#     legacy exports, uses "UNKNOWN" if neither.
#   * @tsv escapes embedded tabs/newlines in field values so the
#     while-read loop cannot desync.
#   * v1.1.17 round-1 (Codex CRITICAL): we emit `{fields: .fields}`
#     (not just `.fields`) so `raw_issue` is the full Jira REST v3
#     request body `{"fields": {...}}`. Kept on a single line to
#     avoid bash 3.2 process-substitution parsing quirks with
#     embedded comments + multi-line quoted jq.

# --- state writeback (idempotency completeness) ------------------------
#
# v1.1.17 round-1 (Codex HIGH): earlier version only READ prior state,
# never wrote back, so re-running the shell driver would re-create
# every row. Now we merge new outcomes into prior state and write
# atomically via tmp + mv.
#
# v1.1.17 round-3 (Codex HIGH): the shell state shape is `.results[]`
# with per-row `.status` ∈ {created, skipped, failed}. This is a
# SIMPLER variant of (not interop-compatible with) the F5-validated
# Python shape — see file-header comment + docs/shell_import_drivers.md
# §"State files" for why we deliberately picked separate paths. We
# still ACCEPT round-1 `.rows[]/.outcome` on read for in-place upgrade.
#
# v1.1.17 round-2 (Codex MEDIUM): tmpfile MUST live in the same
# filesystem as STATE_PATH so `mv` is atomic. /tmp may be on a
# different FS (e.g., tmpfs). We mktemp inside dirname(STATE_PATH).
if [ "${APPLY}" = "1" ] && [ ${#OUTCOMES[@]} -gt 0 ]; then
  state_dir="$(dirname "${STATE_PATH}")"
  mkdir -p "${state_dir}"
  state_new="$(mktemp "${state_dir}/.bsa_jira_state.XXXXXX")"
  python3 - "${STATE_PATH}" "${state_new}" "jira" "${OUTCOMES[@]}" <<'PY'
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
# v1.4.9 R2 NEW MAJOR fix: if prior file's `platform` is present
# but mismatches our run's platform, the prior file is misplaced/
# poisoned (e.g. linear state at jira path). Discarding only the
# rows + force-overwriting `platform` ensures THIS run's writeback
# carries the correct discriminator and future runs trust it.
prior_platform = prior.get("platform")
if prior_platform is not None and prior_platform != platform:
    prior = {"platform": platform, "results": []}
else:
    prior["platform"] = platform  # force-set (covers None / absent)
# Accept BOTH the canonical Python `results[]` shape AND the round-1
# shell `rows[]` shape on read; ALWAYS emit canonical on write.
existing = prior.get("results")
if not isinstance(existing, list):
    existing = []
legacy_rows = prior.get("rows")
if isinstance(legacy_rows, list):
    for r in legacy_rows:
        if not isinstance(r, dict):
            continue
        # Translate round-1 shape → canonical: `outcome` → `status`.
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
        "story_id": story,
        "idempotency_key": idem,
        "status": status,
        "attempts": attempts,
        "updated_at": now,
        "driver": "shell",
    }
prior["results"] = sorted(by_key.values(), key=lambda r: r["idempotency_key"])
with open(new_path, "w") as fh:
    json.dump(prior, fh, indent=2)
PY
  mv "${state_new}" "${STATE_PATH}"
fi

# --- summary -----------------------------------------------------------

echo ""
echo "[jira_import] summary: ${SUCCEEDED} ok, ${SKIPPED} skipped, ${FAILED} failed (total ${ROW_COUNT})"
if [ ${FAILED} -gt 0 ]; then
  echo "[jira_import] failed keys:" >&2
  printf '  %s\n' "${FAILED_KEYS[@]}" >&2
  exit 1
fi
exit 0
