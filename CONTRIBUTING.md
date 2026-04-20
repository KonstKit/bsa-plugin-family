# Contributing

## Workflow

Solo + AI-assist, local-only repo (no public remote). All changes land on `main` directly after local self-review + a `codex exec` review round — there is no PR surface because there is no other reviewer.

### Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):
- `feat(sprint-N): <description>`
- `fix(skill-name): <description>`
- `docs: <description>`
- `refactor(component): <description>`
- `test: <description>`
- `chore(release): <version>`

### Branches

- `main` — the only long-lived branch.
- `release/1.0.x` — created ONLY during a Phase 2.5 hotfix window, from the `v1.0.0` tag. Deleted after cherry-pick back to `main` (see [docs/phase_2_5_shakedown.md](docs/phase_2_5_shakedown.md) §Blocker → hotfix → re-release procedure).

### Pre-commit checklist

- `pytest tests/` — 302 tests must pass.
- `python3 scripts/fixture_runner.py --all` — 4 fixtures must pass.
- `python3 scripts/privacy_scan.py` — 0 blockers.
- `python3 scripts/compute_canon_hash.py` — output must match `.claude-plugin/plugin.json` `canonPolicyVersion.hash_full` (the `test_manifest_canon_hash_matches_current_script_output` pytest case also enforces this).
- Every commit references the relevant US-ID from the sprint plan (or `phase-2.5`, `chore`, etc. for post-release work).
- If the commit touches any invariant in [governance/immutable_invariants.md](governance/immutable_invariants.md) — commit message MUST include explicit reference + justification + major CanonPolicyVersion bump.
- CHANGELOG updated in the same commit (or the immediately adjacent chore commit).

## Validation before commit

Validator scripts are introduced across Sprint 0-0.5. Current availability:

| Validator | Status | Introduced in |
|---|---|---|
| `scripts/bootstrap_repo.sh` | available | Sprint 0, US-S0-01 |
| `scripts/validate_skill_structure.py` | Sprint 0 (US-S0-02) | pending |
| `scripts/inventory_audit.py` | Sprint 0 (US-S0-04) | pending |
| `scripts/privacy_scan.py` | Sprint 0 (US-S0-04) | pending |
| `scripts/validate_request_skill_routing.py` | Sprint 0.5 (US-S05-02) | pending |
| `scripts/fixture_runner.py` | Sprint 0.5 (US-S05-01) | pending |
| `scripts/compute_canon_hash.py` | Sprint 3 (US-S3-04) | pending |
| `scripts/migrate_v0.9_to_v1.0.py` | Sprint 2 (US-S2-02) | pending |

Every validator is a mandatory pre-commit check; they all run locally as part of the checklist above. There is no CI — the repo is local-only.

## Governance invariants

Core invariants in [governance/immutable_invariants.md](governance/immutable_invariants.md) are **not subject to automatic tuning** or self-improvement. Any change requires:
1. Major CanonPolicyVersion bump
2. Explicit reference to the invariant in PR description
3. Migration guide entry in `migrations/`
4. Manual maintainer approval (not AI auto-merge)

## Privacy

- No client data, PII, secrets, or internal URLs in commits
- Privacy scanner (Sprint 0 US-S0-04) runs as part of every pre-commit checklist and MUST return 0 blockers
- Fixtures must be sanitized before commit. Per-fixture sanitization notes live in `fixtures/golden/<project_id>/README.md` — these README files are created alongside each fixture starting with `project_0001` in Sprint 0.5 (US-S05-01)
