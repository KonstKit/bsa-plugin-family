#!/usr/bin/env bash
# pre_write_canonical.sh — PreToolUse:Write hook for bsa-full plugin.
#
# Enforces TWO things on every Write/Edit targeting analysis/canonical/*:
#
#   1. INV-02 single-writer (always): caller MUST identify as
#      bsa-orchestrator via BSA_WRITER env var.
#   2. Schema conformance (Sprint 5 F5): for canonical artifacts whose
#      shape is governed by a schema in governance/schemas/ (markers,
#      A48, A50, A51, A58, A59, A60), the proposed content is
#      validated against that schema. Schema mismatch → BLOCKED with
#      structured stderr listing the violations.
#
# The matcher in hooks.json narrows to analysis/canonical/** paths, so
# if this script runs, the write is against a protected path by
# definition. The script does identity check first (cheaper, narrower)
# then content check (catches the Sysco-engagement schema-drift class
# that the previous identity-only hook waved through).
#
# Claude Code passes the tool input as JSON on stdin. Expected payload
# shape:
#   {"tool_input": {"file_path": "...", "content": "..."}}
# For Edit tool the relevant fields are slightly different
# (old_string/new_string) — the F5 helper handles edits by reading the
# existing file and applying the edit before validating; for now this
# hook validates Write content only and leaves Edit to be tightened in
# a later iteration.
#
# If stdin is empty (interactive use, test contexts that don't pipe
# JSON), content validation is skipped and only the identity check
# applies — this preserves behavioral compatibility with the pre-F5
# hook for test fixtures that exercise the identity gate alone.
#
# Exit 0 = allow. Exit 1 = block (stderr surfaced to Claude).

set -euo pipefail

WRITER="${BSA_WRITER:-}"

# ---- Identity check (INV-02) ------------------------------------------
if [ "${WRITER}" != "bsa-orchestrator" ]; then
  cat >&2 <<EOF
[bsa-full / pre_write_canonical] BLOCKED: write to analysis/canonical/* by non-orchestrator caller.

Single-writer invariant (governance/immutable_invariants.md INV-02):
- Only bsa-orchestrator may write into analysis/canonical/.
- Worker skills + human edits MUST go through analysis/proposals/<stage>/
  and be promoted via /bsa-promote (two-key promotion).

BSA_WRITER env var (current value: "${WRITER}") must equal
"bsa-orchestrator" for the write to succeed.

If you are editing canonical by hand as part of maintenance (e.g., a
migration), temporarily export BSA_WRITER=bsa-orchestrator before the
edit — and DOCUMENT the reason in a migration log at
migrations/<version>/manual_canonical_edits_log.md.
EOF
  exit 1
fi

# ---- Schema-conformance check (Sprint 5 F5) --------------------------
# Locate the plugin repo for the python -m governance.schemas.* CLIs.
PLUGIN_REPO="${BSA_PLUGIN_REPO:-${CLAUDE_PLUGIN_ROOT:-}}"
if [ -z "${PLUGIN_REPO}" ]; then
  PLUGIN_REPO="$(cd "$(dirname "$0")/.." && pwd)"
fi

# Read tool-input JSON from stdin if available. If stdin is a TTY or
# empty, we have no content to validate — skip the schema check (the
# identity gate already passed).
if [ -t 0 ]; then
  exit 0
fi

TOOL_INPUT_JSON="$(cat)"
if [ -z "${TOOL_INPUT_JSON}" ]; then
  exit 0
fi

# Extract target file_path from the tool-input JSON via Python.
# (Plugin already requires Python 3.9+ as documented prereq, so adding
# this dependency is no-op cost; jq is intentionally avoided.)
TARGET_PATH="$(printf '%s' "${TOOL_INPUT_JSON}" | (cd "${PLUGIN_REPO}" && python3 -c '
import json, sys
try:
    payload = json.loads(sys.stdin.read())
except json.JSONDecodeError:
    print("__SKIP__"); sys.exit(0)
ti = payload.get("tool_input") if isinstance(payload, dict) else None
if not isinstance(ti, dict):
    print("__SKIP__"); sys.exit(0)
path = ti.get("file_path") or ti.get("path") or ""
content = ti.get("content")
if not path or content is None:
    # Edit tool (old_string/new_string) is out of scope for this
    # iteration — skip rather than block to avoid false positives.
    print("__SKIP__"); sys.exit(0)
print(path)
') || true)"

if [ "${TARGET_PATH}" = "__SKIP__" ] || [ -z "${TARGET_PATH}" ]; then
  exit 0
fi

# Pipe the EXTRACTED content (not the wrapping JSON) into the
# validator. The validator reads stdin as the proposed file content.
set +e
printf '%s' "${TOOL_INPUT_JSON}" | (cd "${PLUGIN_REPO}" && python3 -c '
import json, sys
payload = json.loads(sys.stdin.read())
sys.stdout.write(payload["tool_input"]["content"])
') | (cd "${PLUGIN_REPO}" && python3 -m governance.schemas.write_validator "${TARGET_PATH}")
VALIDATOR_RC=$?
set -e

if [ ${VALIDATOR_RC} -ne 0 ]; then
  exit ${VALIDATOR_RC}
fi

exit 0
