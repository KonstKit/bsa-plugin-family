# Fixture `adversarial_block_on_contradiction_001` — Block-on-Hard-A51 Failure-Mode Spec

Synthetic adversarial fixture authored in v1.1.5 (B3) as **spec-as-fixture** for an opt-in failure mode the chain did not implement at the time. **As of v1.1.16 (Sprint 1 / T6) the contract is live** — `scripts/promote_strict_preflight.py` + the `pre_bash_promote.sh` hook honor `--strict-on-hard-a51` (and the equivalent `BSA_STRICT_ON_HARD_A51=1` env). The orchestrator's `/bsa-promote` refuses canonical state if any A51 row has `BlockingStatus=hard` AND `ResolutionStatus=open` AND no H4 waiver in the `## Decisions Required` section. This fixture is now the canonical regression baseline for the BLOCKED message shape (see `docs/strict_a51_mode.md` for the operator-facing contract).

## Why this fixture exists

The default contract is "surface contradictions as A51, do not block the pipeline" — operators can ship a handoff with hard-blocking A51s open if they choose, knowing those items are flagged for the steering / sponsor track. Real-world engagements sometimes want the **opposite** posture: refuse to ship anything until all hard-blockers are closed. That's a valid but distinct contract — opt-in, not default.

This fixture documented the EXPECTED behavior of that opt-in mode so when it landed (v1.1.16, Sprint 1 / T6), the implementation had a regression baseline already in place. v1.1.5–v1.1.15: spec-only, integration test asserted the spec via mock. v1.1.16+: implementation lives at `scripts/promote_strict_preflight.py` + `hooks/pre_bash_promote.sh`; the integration test invokes the real script against a synthetic workspace built from this fixture.

## Block-on-contradiction contract (live as of v1.1.16)

When the operator runs `/bsa-promote --strict-on-hard-a51` (or `BSA_STRICT_ON_HARD_A51=1`), the orchestrator hook:

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

Per the v1.1.16 contract, `/bsa-promote --strict-on-hard-a51` against this fixture fails (exit 1, BLOCKED message naming A51-CONFL-003).

## Files

- `inputs/source_001_internal_runbook.md` — first source.
- `inputs/source_002_internal_policy.md` — second source.
- `expected_outputs/canonical/core_controls/A50_source_register.csv` — 2 sources.
- `expected_outputs/canonical/core_controls/A51_issue_route_register.csv` — 1 hard-blocking unresolved contradiction.
- `expected_outputs/canonical/core_controls/A58_evidence_excerpts.csv` — 2 excerpts.
- `expected_outputs/canonical/core_controls/A59_claim_register.csv` — 2 contradicted claims.
- `audit_expectations.json` — declarative spec including the `bsa_promote_strict` verdict.
- `fixture_metadata.json` — provenance + `spec_only: false` flag (v1.1.16+; was `true` in v1.1.5-v1.1.15).

## What this fixture does NOT cover

- Soft / informational A51 rows — those NEVER block, even in strict mode (covered by `tests/test_promote_strict_preflight.py::test_open_soft_row_does_not_block`).
- Multi-A51 blockers — the BLOCKED-message shape for N rows is documented in `docs/strict_a51_mode.md` and pinned by `tests/test_promote_strict_preflight.py::test_multiple_blockers_all_listed_in_message`, but not by fixture data.
- H4 waiver unblock path (covered by `tests/test_promote_strict_preflight.py::test_h4_waiver_in_decisions_required_unblocks`).

## Synthetic vs live-run

`authoring_mode = synthetic_adversarial`. `fixture_metadata.json.spec_only = false` since v1.1.16 — the orchestrator hook now honors `--strict-on-hard-a51` via `scripts/promote_strict_preflight.py`. The test (`tests/test_adversarial_b3_fixtures.py::TestBlockOnContradictionSpec::test_proposed_strict_mode_preflight_blocks_on_open_hard_a51`) invokes the real preflight script against a synthetic workspace built from this fixture's canonical state and asserts the BLOCKED-message shape + exit code.
