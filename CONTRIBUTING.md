# Contributing

## Workflow

Solo + AI-assist. All changes on feature branches, self-reviewed, merged via PR with CI green.

### Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):
- `feat(sprint-N): <description>`
- `fix(skill-name): <description>`
- `docs: <description>`
- `refactor(component): <description>`
- `test: <description>`
- `chore(release): <version>`

### Branches

- `main` — protected, CI must pass, no force-push
- `feat/<sprint>-<short-slug>` — feature branches
- `fix/<issue-slug>` — bug fixes

### Pull Requests

- Every PR references relevant US-ID from sprint plan
- CI green required (CI pipeline introduced Sprint 0 US-S0-03 — until then, manual local validation)
- If PR touches any invariant in [governance/immutable_invariants.md](governance/immutable_invariants.md) — PR description MUST include explicit reference + justification + major CanonPolicyVersion bump
- Changelog updated in same PR

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

Once a validator is committed, it becomes a mandatory pre-PR check. CI (introduced Sprint 0 US-S0-03) will enforce the current set automatically once `.github/workflows/ci.yml` lands — until then, run validators locally.

## Governance invariants

Core invariants in [governance/immutable_invariants.md](governance/immutable_invariants.md) are **not subject to automatic tuning** or self-improvement. Any change requires:
1. Major CanonPolicyVersion bump
2. Explicit reference to the invariant in PR description
3. Migration guide entry in `migrations/`
4. Manual maintainer approval (not AI auto-merge)

## Privacy

- No client data, PII, secrets, or internal URLs in commits
- Privacy scanner (Sprint 0 US-S0-04) runs in CI as blocking check once landed
- Fixtures must be sanitized before commit. Per-fixture sanitization notes live in `fixtures/golden/<project_id>/README.md` — these README files are created alongside each fixture starting with `project_0001` in Sprint 0.5 (US-S05-01)
