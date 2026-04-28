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
#
# v1.3.7 P0 fix: boundary-aware match. Pre-v1.3.7 used `*--dry-run*`
# substring glob, which silently activated dry-run mode on misleading
# inputs like `--dry-run-disabled`, `foo=--dry-run-EXTRA`, or any token
# containing the substring. We mirror the existing --strict-on-hard-a51
# regex below: require word boundary on both sides (start-of-string OR
# whitespace before; end-of-string OR whitespace OR `=` after).
for arg in "$@"; do
  if [[ "${arg}" =~ (^|[[:space:]])--dry-run($|[[:space:]]|=) ]]; then
    exit 0
  fi
done

if [ ! -f "${A48_PATH}" ]; then
  cat >&2 <<EOF
[bsa-full / pre_bash_promote] BLOCKED: no A48_run_context_card.md found in cwd.

Current directory: ${CWD}

Run /bsa-start to initialize a BSA workspace before attempting promote.
EOF
  exit 1
fi

# Extract current stage from A48. Delegates to the schema-aware Python
# parser (governance/schemas/loader.py) which understands all three
# A48 markdown shapes (bullet-backtick, bullet-bold, table). The
# previous in-bash grep only matched bullet-backtick and silently
# failed under set -o pipefail on the table-format A48 used by the
# golden fixtures (Sprint 5 F2 fix; see tests/test_plugin_hooks.py
# round-2 cases).
# v1.0.2 C3 hardening: see hooks/pre_write_canonical.sh for rationale.
# No env-variable override is honored. Priority:
#   1. Script realpath — always authoritative.
#   2. CLAUDE_PLUGIN_ROOT — host-set fallback.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
PLUGIN_REPO="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
if [ ! -d "${PLUGIN_REPO}/governance/schemas" ]; then
  if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -d "${CLAUDE_PLUGIN_ROOT}/governance/schemas" ]; then
    PLUGIN_REPO="${CLAUDE_PLUGIN_ROOT}"
  fi
fi

# Disable pipefail just for the extraction so a clean missing-field
# diagnostic can be emitted instead of silent exit-1.
set +o pipefail
current_stage="$(cd "${PLUGIN_REPO}" && python3 -m governance.schemas.loader a48-field "${A48_PATH}" CurrentStage 2>/dev/null)"
extract_rc=$?
set -o pipefail

if [ ${extract_rc} -ne 0 ] || [ -z "${current_stage}" ]; then
  cat >&2 <<EOF
[bsa-full / pre_bash_promote] BLOCKED: A48 does not declare CurrentStage (or A48 is malformed).

A48 path: ${A48_PATH}

The schema-aware parser at \`governance/schemas/loader.py a48-field\`
could not extract a non-empty CurrentStage value. Supported A48
shapes: Markdown table (\`| Field | Value |\`), bullet with backticks
(\`- \\\`Field\\\`: value\`), or bullet with bold (\`- **Field**: value\`).

Run \`python3 -m governance.schemas.loader a48-field ${A48_PATH} CurrentStage\`
from ${PLUGIN_REPO} for the parser's own diagnostic.
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
    # Stage 4 has no explicit audit marker in the documented
    # run-profile-gates.md / merge-and-reentry-policy.md marker set.
    # The orchestrator's own precondition check still runs; this hook
    # just does not gate on a specific marker. Allow the Bash call
    # through.
    exit 0
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
    # merge-and-reentry-policy.md names stage8.no_new_claims.pass as the
    # only required marker for handoff (the stage8 gate IS the handoff
    # gate under single-writer single-marker semantics).
    required=("stage8.no_new_claims.pass.json")
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

# v1.1.16 (Sprint 1 / T6): --strict-on-hard-a51 opt-in pre-flight check.
# Two activation paths (CLI flag OR env-var); either triggers the
# scripts/promote_strict_preflight.py invocation. Default permissive
# mode skips this check entirely (zero overhead when not opted in).
#
# The preflight refuses canonical write when ANY A51 row has
# BlockingStatus=hard AND ResolutionStatus=open AND no H4 waiver in
# the `## Decisions Required` section. See
# fixtures/golden/adversarial_block_on_contradiction_001/ for the spec.
strict_mode=0
if [ "${BSA_STRICT_ON_HARD_A51:-0}" = "1" ]; then
  strict_mode=1
fi
# v1.1.16 round-1 (Codex): flag detection must be boundary-aware.
# Earlier substring match via `*--strict-on-hard-a51*` silently
# activated on e.g. `--strict-on-hard-a51-EXTRA` or `foo=--strict-
# on-hard-a51-disabled`. We now require a word boundary on BOTH
# sides: preceded by start-of-string OR whitespace, AND followed
# by end-of-string OR whitespace OR `=`. Claude Code passes the
# full command line as a single argv element, so we scan each
# arg with bash regex.
for arg in "$@"; do
  if [[ "${arg}" =~ (^|[[:space:]])--strict-on-hard-a51($|[[:space:]]|=) ]]; then
    strict_mode=1
  fi
done

if [ "${strict_mode}" = "1" ]; then
  if [ -x "${PLUGIN_REPO}/scripts/promote_strict_preflight.py" ]; then
    set +e
    python3 "${PLUGIN_REPO}/scripts/promote_strict_preflight.py" --workspace "${CWD}" >&2
    preflight_rc=$?
    set -e
    if [ ${preflight_rc} -ne 0 ]; then
      # The preflight already wrote a structured BLOCKED diagnostic to
      # stderr; we just propagate the exit code. exit 1 = real block;
      # exit 2 = invocation/parse error (operator misconfig).
      exit ${preflight_rc}
    fi
  else
    cat >&2 <<EOF
[bsa-full / pre_bash_promote] BLOCKED: --strict-on-hard-a51 requested but
the preflight script is missing or not executable:
  ${PLUGIN_REPO}/scripts/promote_strict_preflight.py

Either restore the script (this is part of the plugin distribution)
or drop --strict-on-hard-a51 to use default permissive mode.
EOF
    exit 2
  fi
fi

# v1.3.8 (output review #3.1): marker-freshness pre-flight. Refuses
# promote when any existing marker in analysis/runtime/ready/ or
# analysis/discovery/runtime/ready/ carries a stale canon-policy hash
# (canon was edited after the marker was emitted). Cascade-flags every
# downstream marker too. The freshness script exits:
#   0 = clean (or only PRE_HASH_TOLERATED)
#   1 = blocking (STALE_MARKER or DOWNSTREAM_OF_STALE)
#   2 = invocation error (workspace shape, canon_policy.json unreadable)
#
# Operator opt-out: BSA_SKIP_MARKER_FRESHNESS=1 disables the check.
# Use sparingly — typical reason is a manual canon-bump in progress
# where the operator KNOWS the markers are stale and is about to
# re-promote the chain end-to-end. Documenting the opt-out in the
# canon-bump workflow at docs/RELEASING.md is the right answer; the
# env var exists so an emergency unblock is possible.
if [ "${BSA_SKIP_MARKER_FRESHNESS:-0}" != "1" ]; then
  if [ -f "${PLUGIN_REPO}/scripts/validate_marker_freshness.py" ]; then
    set +e
    python3 "${PLUGIN_REPO}/scripts/validate_marker_freshness.py" "${CWD}" >&2
    fresh_rc=$?
    set -e
    # v1.3.8 R1 fix: explicit handling for ALL exit codes — fall-through
    # on unexpected non-zero would fail open and let promote proceed
    # against a possibly-stale chain. Mirror the strict-preflight
    # pattern: 0=allow, 1=blocked-with-recovery, anything else=
    # invocation/script-bug propagated as a block (exit 2 minimum so
    # the bash caller sees a non-zero result and stops).
    if [ ${fresh_rc} -eq 0 ]; then
      : # Clean — continue to the final exit 0 below.
    elif [ ${fresh_rc} -eq 1 ]; then
      cat >&2 <<EOF

[bsa-full / pre_bash_promote] BLOCKED: marker-freshness pre-flight
found stale or downstream-of-stale markers (see findings above).

Recovery options:
  1. Re-run the affected stages from the earliest STALE_MARKER point
     forward (typical case after a canon-policy edit that shifted the
     hash): /bsa-stage <N> followed by /bsa-promote per stage.
  2. If the canon edit was unintended, revert the canon_policy.json
     bump + recompute (scripts/compute_canon_hash.py) until the hash
     matches the existing marker chain.
  3. Emergency unblock (use rarely + document in your engagement log):
     BSA_SKIP_MARKER_FRESHNESS=1 /bsa-promote ...
EOF
      exit 1
    elif [ ${fresh_rc} -eq 2 ]; then
      # Invocation error already logged to stderr by the script.
      exit 2
    else
      # Unexpected non-zero (script bug, OOM, signal, etc.). Fail
      # CLOSED — silently allowing promote on an unverified-freshness
      # state would defeat the gate's purpose. v1.3.8 R1 (Codex
      # MAJOR): pre-fix this branch fell through to exit 0.
      cat >&2 <<EOF

[bsa-full / pre_bash_promote] BLOCKED: marker-freshness pre-flight
exited with an unexpected code (${fresh_rc}). This indicates a script
bug, runtime crash, or environment misconfig — investigate before
proceeding.

If you've verified the markers are actually fresh and need to
unblock, set BSA_SKIP_MARKER_FRESHNESS=1 in the environment.
EOF
      # Propagate the original exit code if it's a sensible error
      # range (>= 2); otherwise normalize to 2 so bash callers always
      # see a recognizable non-zero.
      if [ ${fresh_rc} -ge 2 ]; then
        exit ${fresh_rc}
      else
        exit 2
      fi
    fi
  fi
  # If the freshness script is missing entirely, fall through silently.
  # This preserves backward compatibility with pre-v1.3.8 installs that
  # might be running this hook against a workspace where the script
  # hasn't been deployed (extremely rare — script ships in the same
  # plugin distribution as the hook).
fi

exit 0
