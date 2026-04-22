# Fixture `adversarial_nfr_claim_contradiction_001` — Phase-3 Contradiction Regression Baseline

Synthetic adversarial fixture for Sprint 9 US-S9-04. Establishes a regression baseline for the Phase-3 contradictory-evidence case: when two upstream A59 claims contradict each other on a measurable target, the bsa-story-writer + bsa-test-scenario-builder + bsa-traceability-matrix chain must surface the contradiction as an A51 route (IssueType=contradiction) AND propagate the deferral down through INVESTStatus, AutomationStatus, and LinkType — never silently picking one side or averaging.

## Why this fixture exists

The Phase-3 plan's US-S9-04 acceptance: "adversarial case where claim evidence contradicts NFR, ensure story-writer surfaces as A51". Generalized: any case where two upstream sources support contradictory measurable targets must:

1. Be captured in A51 with `IssueType=contradiction`.
2. Make any A62 NFR derived from those claims defer the contested THRESHOLD: empty `Target` AND non-empty `A51Ref` pointing at the contradiction route AND non-empty `Metric` (the WHAT — `first response minutes` — is uncontested by the source disagreement; only the THRESHOLD value is). The asymmetry is the contract: emptying `Metric` would over-defer (claim the WHAT is also unknown, which it isn't); leaving `Target` non-empty would under-defer (silently picking one side). INV-09 is satisfied via the A51-route alternative (per measurability-rules: Metric+Target OR A51Ref non-empty). Pinned by `test_a62_quantitative_nfr_defers_target_via_a51`.
3. Make any A70 story whose acceptance depends on the contradicted target carry `INVESTStatus=needs-negotiation` + non-empty `A51Ref`.
4. Make any A71 scenario verifying the contradicted target carry `AutomationStatus=deferred` + non-empty `A51Ref`.
5. Make any A72 trace row touching the contradicted claim/source carry `LinkType=a51-routed` + non-empty `A51Ref`.

The integration test (tests/test_integration_phase3_contradiction.py) asserts the propagation chain mechanically — drift between the fixture state and the expected propagation fails the test.

## Contradiction covered

The fixture ships two synthetic input files asserting different SLA windows for the same severity tier. BOTH sources are T2 (authored-primary) — the contradiction is intentionally same-tier so no auto-resolution via tier hierarchy applies (per `skills/bsa-evidence-intake/references/reliability_tier_spec.md`, tier-delta `>= 2` resolves automatically; tier-delta `<= 1` does not):

| Input file | Tier | What it claims |
|---|---|---|
| `inputs/source_001_ops_runbook.md` | T2 (authored-primary, ops runbook) | "High-severity tickets receive initial response within 4 hours." |
| `inputs/source_002_pm_directive.md` | T2 (authored-primary, active PM policy directive) | "High-severity tickets MUST receive initial response within 30 minutes — anything slower is a customer-facing SLA breach." |

The two sources DISAGREE on the High-severity initial-response target (4h vs 30min). Both are T2 so tier hierarchy does NOT pick a winner. The contract-correct behavior: route to A51 contradiction (`A51-CONFL-001`) and defer the downstream chain.

## Expected pipeline handling

A well-behaved Phase-3 chain must:

1. **Intake captures both claims** — A59 has 2 direct claims (one from each source). Both carry `ClaimStrength=0.0` per the a59 schema's contradiction-routed value (the same-tier disagreement neutralizes the tier-derived 0.85 strength); `A51Ref=A51-CONFL-001` propagates the routing on each.
2. **A60 negative-evidence register** captures the cross-link (each claim is negative evidence for the other).
3. **A51 contradiction route** raised: `A51-CONFL-001` with IssueType=contradiction, BlockingStatus=hard, RaisedByStage=stage1, RelatedClaimIDs covering both contradicted ClaimIDs.
4. **A62 NFR with deferred Target**: NFR-PERF-001 captures the High-severity-SLA NFR with non-empty `Metric` (the WHAT — `first response minutes`) and EMPTY `Target` (the THRESHOLD — contested between 4h and 30min); `A51Ref=A51-CONFL-001` populated instead. INV-09's measurability rule is satisfied via the A51-route alternative — Metric+Target OR A51Ref non-empty per `x-bsa-measurability-rules`. The schema doesn't require Metric to be empty; only the contested Target value is deferred.
5. **A70 story with INVEST deferred**: STORY-001 depends on the SLA target; INVESTStatus=needs-negotiation; A51Ref=A51-CONFL-001.
6. **A71 scenario AutomationStatus=deferred**: TS-001 verifies the SLA target; can't author a literal Target since it's contested; AutomationStatus=deferred; A51Ref=A51-CONFL-001.
7. **A72 trace LinkType=a51-routed**: every trace row touching the contradicted claims carries LinkType=a51-routed; A51Ref=A51-CONFL-001.

Cross-check: zero rows in any Phase-3 artifact silently pick one side of the contradiction. Every artifact transparently defers via the A51 route.

## Files

- `inputs/source_001_ops_runbook.md` — first source (T2, claims 4h SLA).
- `inputs/source_002_pm_directive.md` — second source (T2 active PM policy directive, claims 30min SLA).
- `expected_outputs/canonical/core_controls/A50_source_register.csv` — 2 sources.
- `expected_outputs/canonical/core_controls/A51_issue_route_register.csv` — 1 contradiction route.
- `expected_outputs/canonical/core_controls/A58_evidence_excerpts.csv` — 2 excerpts (one per claim).
- `expected_outputs/canonical/core_controls/A59_claim_register.csv` — 2 contradicted claims.
- `expected_outputs/canonical/core_controls/A60_negative_evidence_register.csv` — cross-link rows.
- `expected_outputs/canonical/core_controls/A62_nfr_register.csv` — 1 NFR with deferred measurability.
- `expected_outputs/canonical/core_controls/A70_story_register.csv` — 1 INVEST-deferred story.
- `expected_outputs/canonical/core_controls/A71_test_scenario_register.csv` — 1 deferred scenario.
- `expected_outputs/canonical/core_controls/A72_traceability_matrix.csv` — 2 a51-routed traces (one per contradicted claim).
- `expected_markers/phase3.{nfr,story,test_scenario,traceability}.pass.json` — markers (PASS, since the contradiction is captured correctly per contract; the contract is "surface contradictions as A51", not "block on contradictions").
- `audit_expectations.json` — declarative regression baseline.

## What this fixture does NOT cover

- Block-on-contradiction behavior. The contract is "surface as A51", not "fail the pipeline". A future security workstream might add an opt-in "fail on hard-blocking A51" mode; that's a separate fixture.
- Multi-way contradictions (3+ sources disagreeing). This fixture is the binary case; multi-way is a v1.2 extension.
- Tier-delta contradictions (e.g., T2 vs T4) that would auto-resolve via tier hierarchy per `reliability_tier_spec.md`. This fixture intentionally uses same-tier (T2 vs T2) so no auto-resolution applies and the A51 route is the contract-correct outcome. A separate fixture covering the auto-resolution case (T2 wins over T4 silently — no A51 raised) is a v1.2 candidate.
