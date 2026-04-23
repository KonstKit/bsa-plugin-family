# Contributing

## Workflow

Solo + AI-assist, local-only repo (no public remote). All changes land on `main` directly after local self-review + a `codex exec` review round (often multiple rounds for substantial patches — 15 rounds total across the v1.1.x line). There is no PR surface because there is no other reviewer.

### Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):
- `feat(component): <description>`
- `fix(skill-name): <description>`
- `release(vX.Y.Z): <one-line summary>` (used for tagged releases)
- `docs: <description>`
- `refactor(component): <description>`
- `test: <description>`
- `chore(release): <version>`

### Branches

- `main` — the only long-lived branch.
- `release/X.Y.x` — created ONLY during a hotfix window from a release tag. Deleted after cherry-pick back to `main`.

### Pre-commit checklist

- `pytest tests/` — full test suite must pass (1412 tests as of v1.1.7; the exact count grows with each release — the invariant is "all pass", not a hardcoded number).
- `python3 scripts/fixture_runner.py --all` — all 8 fixtures (3 happy-path: `project_0001`/`0002`/`0003` + 5 adversarial: `prompt_injection`, `nfr_claim_contradiction`, `multi_way_contradiction`, `tier_delta_auto_resolution`, `block_on_contradiction` — last one is `spec_only=true`) must validate.
- `python3 scripts/privacy_scan.py` — 0 blockers.
- `python3 scripts/compute_canon_hash.py` — output must match `.claude-plugin/plugin.json` `canonPolicyVersion.hash_full` (the `test_manifest_canon_hash_matches_current_script_output` pytest case also enforces this).
- Manifest test (`test_manifest_version_and_canon_semver_agree`) — `version` MUST equal `canonPolicyVersion.semver`.
- Every commit references the relevant US-ID from the sprint plan (or the section letter — `A2`, `B1`, `C`, etc. — for v1.1.x patch-line work).
- If the commit touches any invariant in [governance/immutable_invariants.md](governance/immutable_invariants.md) — commit message MUST include explicit reference + justification + major CanonPolicyVersion bump.
- CHANGELOG updated in the same commit (or the immediately adjacent chore commit).

## Release discipline

The v1.1.x patch line uses two separate semver dimensions:

- **`.claude-plugin/plugin.json` `version`** — the plugin manifest version. Bumps only when the canon-policy state changes (i.e., a POLICY_GLOBS file edited).
- **Git tag `vX.Y.Z`** — operator-facing release marker. May advance independently of the manifest version when the patch is operator-tooling-only (e.g., new scripts, new tests, new docs, fixtures, anonymization).

Examples:
- v1.1.0 → v1.1.1: schema enum extension → both bump.
- v1.1.1 → v1.1.2: new migration script → tag bumps, manifest stays at 1.1.1 (script not in POLICY_GLOBS).
- v1.1.2 → v1.1.3: cross-artifact validator → both bump.
- v1.1.4 → v1.1.5: new fixtures → tag bumps, manifest stays at 1.1.4.
- v1.1.6 → v1.1.7: anonymization (text-only) → tag bumps, manifest stays at 1.1.6.

This matches the v1.0.x precedent (manifest stayed at 1.0.0 through v1.0.4 tags).

## Validation tooling (all available)

| Validator | Purpose |
|---|---|
| `scripts/bootstrap_repo.sh` | One-shot repo state-check (legacy; superseded by individual validators) |
| `scripts/validate_skill_structure.py` | Per-skill SKILL.md frontmatter + references presence |
| `scripts/inventory_audit.py` | Plugin manifest + skills directory inventory |
| `scripts/privacy_scan.py` | PII / credential / secret blocker scan |
| `scripts/validate_request_skill_routing.py` | Orchestrator routing manifest sanity |
| `scripts/fixture_runner.py` | Per-fixture validation (column sets, schema, marker chain) |
| `scripts/validate_marker_chain.py` | Per-workspace marker chain (gapless, monotonic, hash-consistent) |
| `scripts/validate_a51_reconciliation.py` | A51 ResolutionStatus vs marker/handoff payload reconciliation |
| `scripts/compute_canon_hash.py` | Canon-policy hash from POLICY_GLOBS files |
| `scripts/migrate_v0.9_to_v1.0.py` | v0.9 → v1.0 workspace migration (filename rename) |
| `scripts/migrate_v1.0_to_v1.1.py` | v1.0 → v1.1 workspace migration (4 mechanical fixes + 4 report kinds) |
| `scripts/backlog_live_apply.py` | Phase-3 live API client (Jira REST + Linear GraphQL + GitHub REST) |
| `scripts/bsa_cli.py` | Operator-facing read-only workspace status / next-step / doctor / materials-staging CLI |

Every validator is a mandatory pre-commit check; they all run locally as part of the checklist above. There is no CI — the repo is local-only.

## Codex review discipline

Every substantial patch goes through `codex exec -s read-only` review (operator-supplied advisory mode). For multi-file/multi-component patches (cross-artifact validator, live-API integration, anonymization sweep), expect 2-5 rounds:

- Round 1: identify must / should / nice-to-have issues.
- Round 2+: re-review after fixes; either APPROVE or surface new findings.

Final commit happens only after the latest Codex review returns APPROVE. Per-round findings are documented in the commit message.

## Governance invariants

Core invariants in [governance/immutable_invariants.md](governance/immutable_invariants.md) are **not subject to automatic tuning** or self-improvement. Any change requires:
1. Major CanonPolicyVersion bump
2. Explicit reference to the invariant in commit message
3. Migration guide entry in `migrations/`
4. Manual maintainer approval (not AI auto-merge)

INV-01..INV-10 are the current set. Most recent additions: INV-08 (story-claim provenance), INV-09 (NFR measurability), INV-10 (test-scenario provenance) in v1.1.0.

## Privacy + anonymization

- No client data, PII, secrets, or internal URLs in commits.
- Privacy scanner runs as part of every pre-commit checklist and MUST return 0 blockers.
- Fixtures must be sanitized before commit. Per-fixture sanitization notes live in `fixtures/golden/<project_id>/README.md`.
- Active surface (schemas / scripts / docs / tests / hooks) MUST NOT reference real client names. Use the universal alias `Pilot-1` for the first external pilot, `Pilot-2` for the second, etc. Historical sprint retrospectives (`docs/retros/sprint_*.md`) and git commit messages are exempt — they are development-history records (analogous to commit messages) and retain the original engagement names. See v1.1.7 anonymization patch for the contract.
