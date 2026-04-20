#!/usr/bin/env bash
# pre_write_canonical.sh — PreToolUse:Write hook for bsa-full plugin.
#
# Enforces INV-02 (single-writer canonical): only bsa-orchestrator may
# write into analysis/canonical/*. The caller is identified via the
# BSA_WRITER environment variable that bsa-orchestrator sets before
# issuing its own writes.
#
# Claude Code passes the target path(s) to the hook. We block any write
# whose target is under analysis/canonical/ and BSA_WRITER is not set to
# "bsa-orchestrator".
#
# Exit 0 = allow. Exit 1 = block (stderr surfaced to Claude).
#
# The matcher in hooks.json already narrows to analysis/canonical/**
# paths, so if this script runs, the write is against a protected path
# by definition. The script only needs to check BSA_WRITER identity.

set -euo pipefail

WRITER="${BSA_WRITER:-}"

if [ "${WRITER}" = "bsa-orchestrator" ]; then
  exit 0
fi

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
