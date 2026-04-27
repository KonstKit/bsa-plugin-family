#!/usr/bin/env bash
# pre_write_canonical.sh — PreToolUse:Write hook for bsa-full plugin.
#
# Enforces TWO things on every Write/Edit targeting a BSA-protected path:
#
#   1. INV-02 single-writer (always): caller MUST identify as
#      bsa-orchestrator via BSA_WRITER env var.
#   2. Schema conformance (Sprint 5 F5): for artifacts whose shape is
#      governed by a schema in governance/schemas/ (markers, A48, A50,
#      A51, A58, A59, A60), the proposed content is validated against
#      that schema. Schema mismatch → BLOCKED with structured stderr
#      listing the violations.
#
# The matcher in hooks.json narrows to the four protected-path classes:
#   - analysis/canonical/**
#   - analysis/discovery/canonical/**
#   - analysis/runtime/ready/**
#   - analysis/discovery/runtime/ready/**
# If this script runs, the write is against one of those paths by
# definition. The script does identity check first (cheaper, narrower)
# then content check (catches the Pilot-1-engagement schema-drift class
# that the pre-F5 identity-only hook waved through, AND the runtime/ready
# marker-drift class that the Sprint-5 matcher gap allowed past).
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
[bsa-full / pre_write_canonical] BLOCKED: write to a BSA protected path by non-orchestrator caller.

Single-writer invariant (governance/immutable_invariants.md INV-02):
- Only bsa-orchestrator may write into analysis/canonical/, analysis/discovery/canonical/,
  analysis/runtime/ready/, or analysis/discovery/runtime/ready/.
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
#
# v1.0.2 C3 hardening: the previous code accepted BSA_PLUGIN_REPO from
# the user's shell, which enabled a validator-redirection attack. The
# first C3 iteration guarded the override with a second env flag
# (BSA_PLUGIN_REPO_ALLOW_TEST_OVERRIDE=1), but Codex security review
# correctly pointed out that any attacker who can inject one env var
# can inject both — a paired-flag lock is not a lock at all. Final
# lockdown: NO env-variable override is honored. Priority:
#   1. Script realpath (always authoritative — the hook lives inside
#      the plugin, so the repo root is deterministic from `pwd -P` of
#      the hooks/ parent directory).
#   2. CLAUDE_PLUGIN_ROOT fallback — host-set by Claude Code itself at
#      hook invocation time; trusted by construction.
# Tests run the actual hook script via its real path, so realpath
# resolution already works without any override.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
PLUGIN_REPO="$(cd "${SCRIPT_DIR}/.." && pwd -P)"

# Sanity: the derived path MUST contain governance/schemas/. If the
# script was copied out of the plugin tree (unusual), fall back to
# CLAUDE_PLUGIN_ROOT.
if [ ! -d "${PLUGIN_REPO}/governance/schemas" ]; then
  if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -d "${CLAUDE_PLUGIN_ROOT}/governance/schemas" ]; then
    PLUGIN_REPO="${CLAUDE_PLUGIN_ROOT}"
  fi
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

# Extract (path, content) from the tool-input JSON via Python. Handles
# both Write (file_path + content) and Edit (file_path + old_string +
# new_string + replace_all) shapes:
#
#   Write → use content directly.
#   Edit  → read existing file, apply replacement, use the result.
#
# Two temp files come back: ${TMPDIR}/bsa-f5-<pid>.{path,content}.
# Exit 0 + empty files = "skip" (tool shape not recognized; let the
# actual tool run).
TMPBASE="${TMPDIR:-/tmp}/bsa-f5-$$"
trap 'rm -f "${TMPBASE}.path" "${TMPBASE}.content"' EXIT

# Capture the original user-shell CWD BEFORE entering the Python
# extraction block. Two consumers depend on it:
#
#   1. Edit-shape extraction (Python block below) needs it to resolve
#      a workspace-relative file_path (e.g., "analysis/canonical/.../A48.md")
#      back to an absolute path on disk before reading the existing file.
#      v1.3.7 fix: pre-v1.3.7 the Python ran inside `cd "${PLUGIN_REPO}"`,
#      so a relative file_path resolved against PLUGIN_REPO instead of
#      the workspace, the file was not found, and the hook silently
#      exited 0 — bypassing schema validation entirely for any caller
#      that passed a relative path. Now BSA_USER_CWD is forwarded into
#      the Python child env and used to anchor the path.
#
#   2. The validator invocation further down (BSA_WORKSPACE_CWD) — same
#      reason: validator's _resolve_sibling_dir uses it for FK / NFR
#      cross-artifact sibling lookups (Codex v1.1.3 round-1 finding).
USER_CWD="$(pwd)"

printf '%s' "${TOOL_INPUT_JSON}" | (cd "${PLUGIN_REPO}" && TMPBASE="${TMPBASE}" BSA_USER_CWD="${USER_CWD}" python3 -c '
import json, os, sys
tmpbase = os.environ["TMPBASE"]
user_cwd = os.environ.get("BSA_USER_CWD", "")
try:
    payload = json.loads(sys.stdin.read())
except json.JSONDecodeError:
    sys.exit(0)
ti = payload.get("tool_input") if isinstance(payload, dict) else None
if not isinstance(ti, dict):
    sys.exit(0)
path = ti.get("file_path") or ti.get("path") or ""
if not path:
    sys.exit(0)
# Write shape: content provided directly.
if "content" in ti and ti["content"] is not None:
    with open(tmpbase + ".path", "w", encoding="utf-8") as fh:
        fh.write(path)
    with open(tmpbase + ".content", "w", encoding="utf-8") as fh:
        fh.write(ti["content"])
    sys.exit(0)
# Edit shape: apply old_string → new_string against the existing file
# and validate the post-image.
if "old_string" in ti and "new_string" in ti:
    from pathlib import Path
    from governance.schemas.write_validator import apply_edit, EditError
    target = Path(path)
    # Anchor workspace-relative paths against the original user CWD,
    # not against PLUGIN_REPO (we are running inside `cd PLUGIN_REPO`
    # so a bare `Path(path).is_file()` would resolve against the wrong
    # root and silently skip validation — the v1.3.7 P0 fix).
    if not target.is_absolute() and user_cwd:
        target = Path(user_cwd) / target
    if not target.is_file():
        sys.exit(0)
    existing = target.read_text(encoding="utf-8")
    try:
        post = apply_edit(
            existing,
            ti["old_string"],
            ti["new_string"],
            bool(ti.get("replace_all", False)),
        )
    except EditError:
        sys.exit(0)
    with open(tmpbase + ".path", "w", encoding="utf-8") as fh:
        fh.write(path)
    with open(tmpbase + ".content", "w", encoding="utf-8") as fh:
        fh.write(post)
    sys.exit(0)
sys.exit(0)
') || true

# Skip validation if the extraction produced no files (unknown tool
# shape, parse failure, edit-inapplicable — all benign at this layer).
if [ ! -f "${TMPBASE}.path" ] || [ ! -f "${TMPBASE}.content" ]; then
  exit 0
fi

TARGET_PATH="$(cat "${TMPBASE}.path")"

# Pipe the post-image content into the validator. Validator reads
# stdin as the proposed file content; on violation it prints
# structured BLOCKED diagnostics on stderr and exits 1.
set +e
(cd "${PLUGIN_REPO}" && BSA_WORKSPACE_CWD="${USER_CWD}" python3 -m governance.schemas.write_validator "${TARGET_PATH}") < "${TMPBASE}.content"
VALIDATOR_RC=$?
set -e

if [ ${VALIDATOR_RC} -ne 0 ]; then
  exit ${VALIDATOR_RC}
fi

exit 0
