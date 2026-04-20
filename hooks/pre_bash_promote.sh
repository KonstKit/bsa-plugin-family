#!/usr/bin/env bash
# pre_bash_promote.sh — PreToolUse:Bash hook for bsa-full plugin.
#
# Intercepts Bash tool calls whose command string invokes /bsa-promote
# (matcher in hooks.json). Verifies the REQUIRED audit markers for the
# current stage exist before the orchestrator's own precondition check
# runs. Belt-and-suspenders with the command-level check; catches the
# most common promote-without-audit mistake at the earliest layer.
#
# Exit 0 = allow. Exit 1 = block.
#
# The hook reads the current stage from A48_run_context_card.md in the
# cwd's analysis/canonical/core_controls/. For each stage, the required
# marker(s) are defined in
# skills/bsa-orchestrator/references/run-profile-gates.md.

set -euo pipefail

CWD="$(pwd)"
A48_PATH="${CWD}/analysis/canonical/core_controls/A48_run_context_card.md"
MARKERS_DIR="${CWD}/analysis/runtime/ready"
DISCOVERY_MARKERS_DIR="${CWD}/analysis/discovery/runtime/ready"

# --dry-run invocations skip the marker check — dry-run never mutates.
# The matcher fires on /bsa[- ]promote/, so the full invoked command is
# available to inspect via the script's argv (Claude Code passes it).
for arg in "$@"; do
  case "${arg}" in
    *--dry-run*) exit 0 ;;
  esac
done

if [ ! -f "${A48_PATH}" ]; then
  cat >&2 <<EOF
[bsa-full / pre_bash_promote] BLOCKED: no A48_run_context_card.md found in cwd.

Current directory: ${CWD}

Run /bsa-start to initialize a BSA workspace before attempting promote.
EOF
  exit 1
fi

# Extract current stage from A48 (CurrentStage field).
current_stage="$(grep -E '^-\s+`?CurrentStage`?:' "${A48_PATH}" | head -1 | sed 's/.*`CurrentStage`: *//; s/.*CurrentStage: *//' | tr -d '[:space:]')"

if [ -z "${current_stage}" ]; then
  cat >&2 <<EOF
[bsa-full / pre_bash_promote] BLOCKED: A48 does not declare CurrentStage.
Check the A48 file at: ${A48_PATH}
EOF
  exit 1
fi

# Per-stage required-marker map. Keep in sync with
# skills/bsa-orchestrator/references/run-profile-gates.md.
case "${current_stage}" in
  stage1)
    required=("stage1.excerpts.merged.json")
    ;;
  stage2)
    required=("stage2.context_state.pass.json")
    ;;
  stage3)
    required=("stage3.citation_audit.pass.json")
    ;;
  stage4)
    # Stage 4 has no explicit audit marker before promotion in Sprint-3
    # run profiles; stage4.ready is a presence-only signal that the
    # producer ran. Require it.
    required=("stage4.ready.json")
    ;;
  stage5)
    required=("stage5.anchor_audit.pass.json")
    ;;
  stage6)
    required=("stage6.anchor_audit.pass.json")
    ;;
  stage7)
    required=("stage7.skeptical_review.pass.json")
    ;;
  stage8)
    required=("stage8.no_new_claims.pass.json")
    ;;
  handoff)
    required=("stage8.no_new_claims.pass.json" "handoff.ready.json")
    ;;
  d1)
    required=("discovery.d1.ready.json")
    markers_dir="${DISCOVERY_MARKERS_DIR}"
    ;;
  d2)
    required=("discovery.d2.claims.merged.json" "discovery.d2.research_quality.pass.json")
    markers_dir="${DISCOVERY_MARKERS_DIR}"
    ;;
  d3)
    required=("discovery.d3.prioritization.pass.json")
    markers_dir="${DISCOVERY_MARKERS_DIR}"
    ;;
  d4)
    required=("discovery.d4.constraint_audit.pass.json")
    markers_dir="${DISCOVERY_MARKERS_DIR}"
    ;;
  d5)
    required=("discovery.d5.citation_audit.pass.json" "discovery.d5.no_solution_leakage.pass.json")
    markers_dir="${DISCOVERY_MARKERS_DIR}"
    ;;
  *)
    cat >&2 <<EOF
[bsa-full / pre_bash_promote] BLOCKED: unknown CurrentStage "${current_stage}" in A48.
Valid values: stage1..stage8, handoff, d1..d5.
EOF
    exit 1
    ;;
esac

markers_dir="${markers_dir:-${MARKERS_DIR}}"

missing=()
for m in "${required[@]}"; do
  if [ ! -f "${markers_dir}/${m}" ]; then
    missing+=("${m}")
  fi
done

if [ "${#missing[@]}" -gt 0 ]; then
  {
    printf '[bsa-full / pre_bash_promote] BLOCKED: missing required marker(s) for %s promotion.\n\n' "${current_stage}"
    printf 'Missing markers in %s:\n' "${markers_dir}"
    for m in "${missing[@]}"; do
      printf '  - %s\n' "${m}"
    done
    printf '\nRun the appropriate audit before promoting:\n'
    case "${current_stage}" in
      stage3) printf '  /bsa-audit citation\n' ;;
      stage5|stage6) printf '  /bsa-audit anchor\n' ;;
      stage7) printf '  /bsa-audit skeptical\n' ;;
      stage8) printf '  /bsa-audit no-new-claims\n' ;;
      *)      printf '  (see run-profile-gates.md for the full marker set)\n' ;;
    esac
    printf '\nUse /bsa-promote --dry-run to preview the planned promotion without mutation.\n'
  } >&2
  exit 1
fi

exit 0
