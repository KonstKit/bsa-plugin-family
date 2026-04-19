# Changelog

All notable changes to the BSA Plugin Family. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + [Semantic Versioning](https://semver.org/spec/v2.0.0.html) for plugin versions.

Canon policy version (orthogonal measurement): `<semver>+hash:<sha256-prefix>`, computed from policy state (see [governance/immutable_invariants.md](governance/immutable_invariants.md) and Sprint 3 canon hash scheme).

## [Unreleased]

### Added
- Repository bootstrap: baseline structure, .gitignore, README, CHANGELOG, LICENSE, CONTRIBUTING (US-S0-01)
- Skills imported from `~/.codex/skills/` at canon v0.9 baseline (22 skills: bsa-*, d0-*, c4-plantuml-from-context, camunda-bpmn-from-context, inot-prompt-builder) (US-S0-01)
- `governance/immutable_invariants.md` — seven invariants anchoring governance: evidence-binding, single-writer canonical, no-new-claims, two-key promotion, A51 not a fact source, composition-via-orchestrator, ClaimType schema closed (US-S0-05)
- `scripts/validate_skill_structure.py` + `tests/test_validate_skill_structure.py` — structural linter for SKILL.md frontmatter (name/description required), directory-name match, and relative-link resolution (references/, scripts/, assets/, tests/, evals/). 21 unit tests cover AC-1..AC-4 plus CRLF, single-quoted scalars, title variants, balanced parens in paths, symlink loops. Baseline health: 22/22 skills pass (US-S0-02).
- `scripts/inventory_audit.py` + `docs/inventory_audit.md` — classifies each skill as stable/flaky/orphan/broken, counts references/scripts/tests/fixtures, extracts SCN/CHK/ART-VAL validation bindings from SKILL.md. Baseline: 22 stable / 0 flaky / 0 orphan / 0 broken (US-S0-04).
- `scripts/privacy_scan.py` + `scripts/privacy_whitelist.json` + `tests/test_privacy_scan.py` + `docs/privacy_audit.md` — scanner for email / phone / credit-card (Luhn) / api-key (entropy) / internal-URL patterns with severity-tiered verdicts (blocker/warning/info). Blocker findings fail CI. Whitelist supports string matches and path globs. Skips NPM integrity hashes (sha256-/sha384-/sha512-), sequential digit sequences (placeholder data), and binaries. 18 unit tests. Baseline: 0 blockers / 0 warnings / 0 info across 152 scanned files (US-S0-04).

## [0.9.0-foundation] — Pre-release, Phase 0 kickoff

Initial import. No behavioral changes from source Codex skills. Provides version-control baseline for subsequent Phase 1-2 stabilization.
