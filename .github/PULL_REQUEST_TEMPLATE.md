<!-- v1.1.10 (Section J): PR template. The repo is solo-maintained today;
this template will activate when a future contributor opens a PR. -->

## Summary

<!-- 1-3 bullets describing what this PR changes and why. -->

## Pre-merge checklist

- [ ] `pytest tests/` — all 1425+ tests pass.
- [ ] `python3 scripts/fixture_runner.py --all --mode=validate` — all 8 golden fixtures clean.
- [ ] `python3 scripts/privacy_scan.py` — 0 blockers.
- [ ] `python3 scripts/compute_canon_hash.py` — output matches `.claude-plugin/plugin.json` `canonPolicyVersion.hash_full` (CI's `canon-hash` job also enforces this; if you edited any POLICY_GLOBS file, update the manifest in the same PR).
- [ ] `CHANGELOG.md` updated with an entry describing the change.
- [ ] If touching any invariant in `governance/immutable_invariants.md` — explicit reference + rationale + major CanonPolicyVersion bump.
- [ ] If touching the active surface (schemas/scripts/docs/tests/hooks), no real client names — use the universal `Pilot-1` / `Pilot-N` alias (per v1.1.7 anonymization contract).
- [ ] If adding a new platform export or live-API client — token-handling regression tests + schema-level token-shape rejection (per v1.1.6 security pattern).

## Codex review status

<!-- Solo maintainer typically runs `codex exec -s read-only` review locally
before opening a PR. Note the round count and verdict here. -->

- Round count:
- Final verdict (APPROVE / REJECT):
- Findings addressed:

## Type of change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Schema enum extension (additive — backward-compatible)
- [ ] Breaking change (would require major CanonPolicyVersion bump)
- [ ] Documentation polish
- [ ] CI/CD / tooling
- [ ] Test coverage extension
- [ ] Other (specify):

## Linked context

<!-- Reference the relevant section letter (A-K), TODO marker
([TODO-S9-XXX]), or fixture / SKILL.md the change belongs to. -->
