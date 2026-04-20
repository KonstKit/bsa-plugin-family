#!/usr/bin/env bash
# session_start.sh — SessionStart hook for bsa-full plugin.
#
# When Claude Code opens a session in a directory that already contains
# a BSA-initialized workspace (detected by presence of
# analysis/canonical/core_controls/), suggest the user run /bsa-status to
# see current state. If no BSA workspace is detected, exit quietly.
#
# This hook is informational only — it never blocks. Exit 0 always.
#
# Stdout is surfaced to Claude as user-visible context (per Claude Code
# plugin hook conventions); keep it short.

set -euo pipefail

CWD="$(pwd)"
CANONICAL_DIR="${CWD}/analysis/canonical/core_controls"
A48_PATH="${CANONICAL_DIR}/A48_run_context_card.md"

if [ ! -d "${CANONICAL_DIR}" ]; then
  # No BSA workspace here; exit quietly.
  exit 0
fi

# Workspace detected — emit a short suggestion.
if [ -f "${A48_PATH}" ]; then
  # Extract a few fields from A48 for a more-informed nudge.
  run_id="$(grep -E '^-\s+`?RunID`?:' "${A48_PATH}" 2>/dev/null | head -1 | sed 's/.*`RunID`: *//; s/.*RunID: *//' || true)"
  mode="$(grep -E '^-\s+`?Mode`?:' "${A48_PATH}" 2>/dev/null | head -1 | sed 's/.*`Mode`: *//; s/.*Mode: *//' || true)"
  printf 'BSA workspace detected in %s' "${CWD}"
  if [ -n "${run_id}" ]; then
    printf ' (RunID: %s' "${run_id}"
    if [ -n "${mode}" ]; then
      printf ', mode: %s' "${mode}"
    fi
    printf ')'
  fi
  printf '.\nRun `/bsa-status` to see current stage, pending markers, and open A51 items.\n'
else
  # Canonical dir exists but A48 missing — partially bootstrapped.
  printf 'BSA workspace partially initialized in %s (A48 missing).\n' "${CWD}"
  printf 'Run `/bsa-start` to re-seed or `/bsa-status` if A48 is present under an unexpected path.\n'
fi

exit 0
