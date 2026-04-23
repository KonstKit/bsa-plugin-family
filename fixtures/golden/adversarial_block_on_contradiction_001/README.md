# Fixture `adversarial_block_on_contradiction_001` — Block-on-Hard-A51 Failure-Mode Spec

Synthetic adversarial fixture for v1.1.5 (B3). **Spec-as-fixture** for an opt-in failure mode the chain does not yet implement: when the operator passes `--strict-on-hard-a51` (or sets the equivalent env), the orchestrator's `/bsa-promote` MUST refuse to land canonical state if any A51 row with `BlockingStatus=hard` is unresolved (`ResolutionStatus=open` AND not waivered via H4 `## Decisions Required`).

## Why this fixture exists

The default contract is "surface contradictions as A51, do not block the pipeline" — operators can ship a handoff with hard-blocking A51s open if they choose, knowing those items are flagged for the steering / sponsor track. Real-world engagements sometimes want the **opposite** posture: refuse to ship anything until all hard-blockers are closed. That's a valid but distinct contract — opt-in, not default.

This fixture documents the EXPECTED behavior of that opt-in mode so when it lands (v1.2 candidate), the implementation has a regression baseline already in place. Today the fixture is **spec-only** (the orchestrator does not honor `--strict-on-hard-a51`) — the integration test for this fixture asserts the spec via mock, not against the live `/bsa-promote` invocation.

## Block-on-contradiction contract (proposed)

When the operator runs `/bsa-promote --strict-on-hard-a51` (or `BSA_STRICT_ON_HARD_A51=1`), the orchestrator MUST:

1. **Pre-flight check** — before acquiring the canonical write lock, scan `analysis/canonical/core_controls/A51_issue_route_register.csv` (or the equivalent under discovery) for any row matching:
   - `BlockingStatus = hard`
   - `ResolutionStatus = open`
   - NOT referenced by an H4 `## Decisions Required` waiver (when handoff has been emitted)
2. **Block on first match** — emit a structured BLOCKED message to stderr listing every blocking A51 row by `A51Ref + IssueType + Severity + NextAction`, then exit with code 1. Do NOT acquire the lock; do NOT write canonical.
3. **Pass when no blockers** — when zero A51 rows match the criteria above, proceed normally with the existing two-key promotion (audit-marker + evidence-binding).

Operator escape hatches:
- Drop `--strict-on-hard-a51` (back to default permissive mode).
- Resolve the A51 row in the canonical register (set `ResolutionStatus` to `resolved | resolved_by_remediation | superseded | wontfix`).
- Add an explicit waiver in H4 `## Decisions Required` referencing the A51 by `[A51-xxx]` — this records the sponsor's accept-and-proceed decision.

## Scenario captured by this fixture

Two T2 sources contradicting on a hard-blocking measurable target (same shape as `adversarial_nfr_claim_contradiction_001` — borrowed for spec-test stability). The fixture's canonical state has:

- Two contradicted T2 claims in A59.
- ONE A51 row: `A51-CONFL-003`, `IssueType=contradiction`, `Severity=critical`, `BlockingStatus=hard`, `ResolutionStatus=open`.
- NO H4 waiver covering A51-CONFL-003.

Per the proposed contract, `/bsa-promote --strict-on-hard-a51` against this fixture MUST fail (exit 1, BLOCKED message naming A51-CONFL-003).

## Files

- `inputs/source_001_internal_runbook.md` — first source.
- `inputs/source_002_internal_policy.md` — second source.
- `expected_outputs/canonical/core_controls/A50_source_register.csv` — 2 sources.
- `expected_outputs/canonical/core_controls/A51_issue_route_register.csv` — 1 hard-blocking unresolved contradiction.
- `expected_outputs/canonical/core_controls/A58_evidence_excerpts.csv` — 2 excerpts.
- `expected_outputs/canonical/core_controls/A59_claim_register.csv` — 2 contradicted claims.
- `audit_expectations.json` — declarative spec including the proposed `bsa_promote_strict` verdict.
- `fixture_metadata.json` — provenance + `spec_only: true` flag.

## What this fixture does NOT cover

- The actual orchestrator implementation of `--strict-on-hard-a51` (deferred to v1.2 — fixture exists to anchor the regression test once the implementation lands).
- Soft / informational A51 rows — those NEVER block, even in strict mode.
- Multi-A51 blockers — the message-format spec for "list all blockers" is documented in the README but not pinned in fixture data.

## Synthetic vs live-run + spec-only flag

`authoring_mode = synthetic_adversarial`. `fixture_metadata.json.spec_only = true` flags this fixture as documenting an unimplemented contract. The test (`tests/test_adversarial_b3_fixtures.py::TestBlockOnContradictionSpec`) asserts the canonical state matches the schema (so the fixture itself is consumable today) AND mocks the proposed orchestrator strict-mode pre-flight check to validate the BLOCKED message shape.

When `--strict-on-hard-a51` lands (v1.2), this fixture will be the regression baseline; the test will switch from mocked-pre-flight to direct-invocation assertions.
