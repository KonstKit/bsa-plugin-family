# Changelog

All notable changes to the BSA Plugin Family. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + [Semantic Versioning](https://semver.org/spec/v2.0.0.html) for plugin versions.

Canon policy version (orthogonal measurement): `<semver>+hash:<sha256-prefix>`, computed from policy state (see [governance/immutable_invariants.md](governance/immutable_invariants.md) and Sprint 3 canon hash scheme).

## [Unreleased]

### Added
- Repository bootstrap: baseline structure, .gitignore, README, CHANGELOG, LICENSE, CONTRIBUTING (US-S0-01)
- Skills imported from `~/.codex/skills/` at canon v0.9 baseline (22 skills: bsa-*, d0-*, c4-plantuml-from-context, camunda-bpmn-from-context, inot-prompt-builder) (US-S0-01)
- `governance/immutable_invariants.md` — seven invariants anchoring governance: evidence-binding, single-writer canonical, no-new-claims, two-key promotion, A51 not a fact source, composition-via-orchestrator, ClaimType schema closed (US-S0-05)

## [0.9.0-foundation] — Pre-release, Phase 0 kickoff

Initial import. No behavioral changes from source Codex skills. Provides version-control baseline for subsequent Phase 1-2 stabilization.
