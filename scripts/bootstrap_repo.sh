#!/usr/bin/env bash
# scripts/bootstrap_repo.sh
#
# US-S0-01 AC-1..AC-4: Reproducible bootstrap of BSA plugin family repo.
# Creates directory skeleton, copies 22 target skills from ~/.codex/skills/,
# initializes git, and prepares for initial commit.
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
#   - integrity verification detects drift between source and target (exit 4)

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
  bsa-no-new-facts-auditor
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

# 5. Verify per-skill integrity (AC-3): diff each whitelisted skill. Hard-fail on drift.
echo
echo "Verifying copy integrity (whitelist skills only)..."
drift=0
if [[ "$DRY_RUN" -eq 0 ]]; then
  for skill_name in "${TARGET_SKILLS[@]}"; do
    src="$SOURCE/$skill_name"
    dest="$TARGET/skills/$skill_name"
    diff_file="/tmp/bsa_bootstrap_diff_${skill_name}.txt"
    if ! diff -rq "$src" "$dest" > "$diff_file" 2>&1; then
      echo "  [drift] $skill_name — see $diff_file"
      drift=$((drift + 1))
    fi
  done
  if [[ $drift -eq 0 ]]; then
    echo "  [ok] all ${#TARGET_SKILLS[@]} skills verified clean"
  else
    echo
    echo "ERROR: integrity verification FAILED — $drift skill(s) drift from source." >&2
    echo "AC-3 is not met. Inspect /tmp/bsa_bootstrap_diff_*.txt and reconcile." >&2
    exit 4
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
