#!/usr/bin/env bash
# scripts/bootstrap_repo.sh
#
# US-S0-01 AC-1..AC-4: Reproducible bootstrap of BSA plugin family repo.
# Creates directory skeleton, copies 22 target skills from ~/.codex/skills/,
# initializes git, and prepares for initial commit.
#
# IMPORTANT — post-Phase-0 usage note:
# This script was Phase 0's Sprint 0 import tool. For NEW installations
# post-v0.95.0, prefer `git clone` of the plugin-family repo rather than
# re-running bootstrap against the upstream `.codex/skills/` source: post-
# Sprint-1+ the target carries semantic edits (skill renames, invariant
# additions, evidence-binding clarifications) that are NOT present in the
# upstream source. Re-running bootstrap will produce a pre-Sprint-1 target
# state, not the canonical post-rename state.
#
# The script is preserved as:
#   1. A historical record of the Sprint 0 import process (AC-4 commit).
#   2. An advisory integrity check on existing bootstrapped repos.
#
# Usage:
#   scripts/bootstrap_repo.sh [--source=<path>] [--target=<path>] [--dry-run]
#
# Defaults:
#   --source=${HOME}/.codex/skills
#   --target=${HOME}/projects/bsa-plugin-family
#
# Idempotent: safe to re-run. Skips skills already copied.
# Copies ONLY the 22 BSA target skills (explicit whitelist). Non-BSA skills
# in source (e.g., playwright, screenshot, macos-*) are intentionally excluded.
#
# Exits non-zero if:
#   - source directory missing (exit 1)
#   - any whitelisted skill not found in source (exit 3)
#   - integrity verification detects drift AND this is a fresh bootstrap
#     (no git commits yet in target) — exit 4
#   Post-bootstrap re-runs treat drift as advisory (exit 0) because post-
#   Sprint-1+ the target legitimately diverges from upstream source.
#
# Bash compatibility: runs on macOS default Bash 3.2 (no associative
# arrays; uses a case-based legacy-source-name resolver instead).

set -euo pipefail

SOURCE="${HOME}/.codex/skills"
TARGET="${HOME}/projects/bsa-plugin-family"
DRY_RUN=0

TARGET_SKILLS=(
  # Main-cycle workers + orchestrator (14)
  bsa-orchestrator
  bsa-evidence-intake
  bsa-claim-binder
  bsa-semantic-extractor
  bsa-domain-modeler
  bsa-backbone-builder
  bsa-contract-builder
  bsa-anchor-auditor
  bsa-citation-auditor
  bsa-consistency-auditor
  bsa-skeptical-reviewer
  bsa-no-new-claims-auditor
  bsa-validation-readiness
  bsa-handoff-packager
  # Discovery branch (5)
  d0-problem-framer
  d0-context-researcher
  d0-hypothesis-prioritizer
  d0-feasibility-assessor
  d0-synthesis-gatekeeper
  # Sidecars (3)
  c4-plantuml-from-context
  camunda-bpmn-from-context
  inot-prompt-builder
)

# Legacy source directory names that map to current canonical target names.
# Sprint 2 US-S2-02 renamed bsa-no-new-facts-auditor -> bsa-no-new-claims-auditor.
# The upstream `.codex/skills/` source may still use the legacy directory
# name; this function lets bootstrap find it under either name without
# requiring the source workspace to be renamed in lockstep.
#
# Bash-3.2-compatible (macOS default): uses a case statement instead of
# `declare -A` so the script runs on the OS-bundled bash without Homebrew
# upgrade.
legacy_source_for() {
  case "$1" in
    bsa-no-new-claims-auditor) echo "bsa-no-new-facts-auditor" ;;
    *) echo "" ;;
  esac
}

for arg in "$@"; do
  case "$arg" in
    --source=*) SOURCE="${arg#*=}" ;;
    --target=*) TARGET="${arg#*=}" ;;
    --dry-run)  DRY_RUN=1 ;;
    -h|--help)
      grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# Execute command given as argv array. No shell interpretation of arguments.
# Safe against injection via user-controlled --source / --target paths.
run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run]'
    for a in "$@"; do printf ' %q' "$a"; done
    printf '\n'
  else
    printf '[run]'
    for a in "$@"; do printf ' %q' "$a"; done
    printf '\n'
    "$@"
  fi
}

if [[ ! -d "$SOURCE" ]]; then
  echo "ERROR: source directory does not exist: $SOURCE" >&2
  exit 1
fi

# ensure_baseline_file <dest_path> — writes a starter file if not present.
# Content comes from heredoc via stdin. Idempotent: never overwrites an
# existing regular file, and never follows a pre-existing symlink (dangling
# or live) — such entries are rejected to prevent write-through-symlink
# attacks on rerun. Heredoc input is always consumed so caller control flow
# stays predictable whether or not the target is created.
ensure_baseline_file() {
  local dest="$1"
  # -L catches any symlink (including dangling); -e catches regular files,
  # dirs, etc. Reject if either is present.
  if [[ -L "$dest" || -e "$dest" ]]; then
    if [[ -L "$dest" ]]; then
      echo "  [skip-symlink] $dest (pre-existing symlink — refuse to write through)"
    else
      echo "  [exists] $dest"
    fi
    cat >/dev/null
    return 0
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] would create $dest"
    cat >/dev/null
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  # noclobber-like guard: if something raced in between the check and
  # the write, fail loudly rather than silently overwrite.
  ( set -o noclobber; cat >"$dest" ) || {
    echo "ERROR: ensure_baseline_file refused to overwrite $dest (race or TOCTOU)" >&2
    return 5
  }
  echo "  [create] $dest"
}

echo "Bootstrap BSA Plugin Family"
echo "  source: $SOURCE"
echo "  target: $TARGET"
echo "  skills: ${#TARGET_SKILLS[@]} (whitelist)"
echo "  dry-run: $DRY_RUN"
echo

# 1. Directory skeleton (idempotent)
run mkdir -p \
  "$TARGET/skills" \
  "$TARGET/scripts" \
  "$TARGET/tests" \
  "$TARGET/fixtures/golden" \
  "$TARGET/config" \
  "$TARGET/governance" \
  "$TARGET/docs" \
  "$TARGET/migrations" \
  "$TARGET/.github/workflows"

# 2. Ensure baseline documentation / control files (idempotent starter stubs).
# Full content is maintained via normal edits after first commit; these stubs
# guarantee US-S0-01 AC-1 is satisfied when running bootstrap on a fresh
# target (the repo boots with the required files present).
echo "Ensuring baseline control files..."

ensure_baseline_file "$TARGET/.gitignore" <<'GITIGNORE_EOF'
# Runtime state — never committed
analysis/
**/analysis/

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
*.egg-info/
dist/
build/
.tox/
.venv/
venv/
env/

# OS
.DS_Store
Thumbs.db
._*
__MACOSX

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# Logs / temp
*.log
*.tmp
*.bak
/tmp/
GITIGNORE_EOF

ensure_baseline_file "$TARGET/README.md" <<'README_EOF'
# BSA Plugin Family

Starter stub created by `scripts/bootstrap_repo.sh`. Replace with project README before first commit if running on a fresh target.

Evidence-first BA/SA analytical pipeline packaged as a Claude Code plugin family.
README_EOF

ensure_baseline_file "$TARGET/CHANGELOG.md" <<'CHANGELOG_EOF'
# Changelog

Starter stub. Replace with project CHANGELOG before first commit.

## [Unreleased]
CHANGELOG_EOF

ensure_baseline_file "$TARGET/LICENSE" <<'LICENSE_EOF'
Copyright (c) 2026 BSA Plugin Family contributors. All rights reserved. License terms TBD — private during Phase 0-2 development.
LICENSE_EOF

ensure_baseline_file "$TARGET/CONTRIBUTING.md" <<'CONTRIBUTING_EOF'
# Contributing

Starter stub. Replace with project contribution guidelines before first commit.
CONTRIBUTING_EOF

# 3. Copy skills from whitelist only (integrity verified in step 5)
missing_sources=()
for skill_name in "${TARGET_SKILLS[@]}"; do
  src="$SOURCE/$skill_name"
  dest="$TARGET/skills/$skill_name"
  # Fallback: if the canonical source directory is missing but a legacy
  # alias is registered, use the alias as the source. Target directory
  # name is always the canonical one, so renaming happens at copy time.
  legacy_name="$(legacy_source_for "$skill_name")"
  if [[ ! -d "$src" && -n "$legacy_name" ]]; then
    legacy_src="$SOURCE/$legacy_name"
    if [[ -d "$legacy_src" ]]; then
      echo "  [legacy-alias] $skill_name <- $legacy_name (US-S2-02 rename)"
      src="$legacy_src"
    fi
  fi
  if [[ ! -d "$src" ]]; then
    missing_sources+=("$skill_name")
    echo "  [missing] $skill_name (NOT in source — will fail integrity check)"
    continue
  fi
  if [[ ! -f "$src/SKILL.md" ]]; then
    echo "  [skip] $skill_name (no SKILL.md in source)"
    continue
  fi
  if [[ -d "$dest" ]]; then
    echo "  [exists] $skill_name"
  else
    echo "  [copy] $skill_name"
    run cp -R "$src" "$dest"
  fi
done

if [[ ${#missing_sources[@]} -gt 0 ]]; then
  echo
  echo "ERROR: ${#missing_sources[@]} whitelisted skills not found in source:" >&2
  for s in "${missing_sources[@]}"; do
    echo "  - $s" >&2
  done
  exit 3
fi

# 4. Git init (if not already)
if [[ ! -d "$TARGET/.git" ]]; then
  ( cd "$TARGET" && run git init -b main )
  ( cd "$TARGET" && run git config user.name 'BSA Maintainer' )
  ( cd "$TARGET" && run git config user.email 'maintainer@bsa-plugin-family.local' )
else
  echo "[exists] git repo already initialized"
fi

# 5. Verify per-skill integrity (AC-3): diff each whitelisted skill.
# Behaviour depends on whether this is a fresh bootstrap or a re-run:
# - Fresh bootstrap (target has no git commits yet): hard-fail on any
#   drift; this preserves AC-3 for the initial copy guarantee.
# - Re-run (target has at least one git commit): integrity drift is
#   expected (post-bootstrap sprints edit skills semantically), so the
#   script reports drift as advisory and exits 0.
# Skills with a legacy source alias carry an intentional *narrow* rename
# surface (SKILL.md + renamed reference contract file); drift outside
# that surface still fails on fresh bootstraps.
post_bootstrap=0
if [[ -d "$TARGET/.git" ]]; then
  if git -C "$TARGET" rev-parse --verify HEAD >/dev/null 2>&1; then
    post_bootstrap=1
  fi
fi
echo
if [[ "$post_bootstrap" -eq 1 ]]; then
  echo "Verifying copy integrity (advisory — post-bootstrap re-run mode)..."
else
  echo "Verifying copy integrity (strict — fresh bootstrap)..."
fi
drift=0
expected_drift=0
if [[ "$DRY_RUN" -eq 0 ]]; then
  for skill_name in "${TARGET_SKILLS[@]}"; do
    src="$SOURCE/$skill_name"
    legacy_name="$(legacy_source_for "$skill_name")"
    if [[ ! -d "$src" && -n "$legacy_name" ]]; then
      legacy_src="$SOURCE/$legacy_name"
      [[ -d "$legacy_src" ]] && src="$legacy_src"
    fi
    dest="$TARGET/skills/$skill_name"
    diff_file="/tmp/bsa_bootstrap_diff_${skill_name}.txt"
    if diff -rq "$src" "$dest" > "$diff_file" 2>&1; then
      continue  # identical — nothing to report
    fi
    if [[ -z "$legacy_name" ]]; then
      echo "  [drift] $skill_name — see $diff_file"
      drift=$((drift + 1))
      continue
    fi
    # Legacy-aliased skill: classify per-file diffs. The ONLY tolerated
    # rename surface is:
    #   1. SKILL.md (frontmatter name field + body rename edits)
    #   2. renamed reference contract (no-new-facts-contract.md gone from
    #      source, no-new-claims-contract.md present in target, or vice
    #      versa)
    # Any diff entry outside this surface is unexpected.
    unexpected=$(
      grep -Ev \
        -e "SKILL\.md(\s|$)" \
        -e "no-new-facts-contract\.md(\s|$)" \
        -e "no-new-claims-contract\.md(\s|$)" \
        "$diff_file" || true
    )
    if [[ -n "$unexpected" ]]; then
      echo "  [drift] $skill_name (unexpected diff beyond known rename surface; see $diff_file)"
      drift=$((drift + 1))
    else
      echo "  [expected-drift] $skill_name (known rename surface only; see $diff_file)"
      expected_drift=$((expected_drift + 1))
    fi
  done
  if [[ $drift -eq 0 ]]; then
    if [[ $expected_drift -eq 0 ]]; then
      echo "  [ok] all ${#TARGET_SKILLS[@]} skills verified clean"
    else
      echo "  [ok] ${#TARGET_SKILLS[@]} skills verified; $expected_drift expected-drift (legacy-alias renames)"
    fi
  else
    echo
    if [[ "$post_bootstrap" -eq 1 ]]; then
      echo "NOTICE: $drift skill(s) drift from source (advisory — post-bootstrap re-run)." >&2
      echo "This is expected: post-bootstrap sprints edit skills semantically." >&2
      echo "Inspect /tmp/bsa_bootstrap_diff_*.txt if investigating a specific skill." >&2
    else
      echo "ERROR: integrity verification FAILED — $drift skill(s) unexpected drift from source." >&2
      echo "AC-3 is not met. Inspect /tmp/bsa_bootstrap_diff_*.txt and reconcile." >&2
      exit 4
    fi
  fi
fi

echo
echo "Bootstrap complete."
if [[ "$DRY_RUN" -eq 0 ]]; then
  echo "Next steps:"
  echo "  cd $TARGET"
  echo "  git status"
  echo "  git add -A"
  echo "  git commit -m 'Initial import of 22 skills from .codex/skills/ (canon v0.9)'"
fi
