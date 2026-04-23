# Fixture `adversarial_multi_way_contradiction_001` — Multi-Way (3-Source) Contradiction Regression Baseline

Synthetic adversarial fixture for v1.1.5 (B3). Establishes a regression baseline for the multi-way contradiction case: when **three or more** upstream sources at the same tier disagree on a single measurable target, the chain MUST capture all three contradictory ClaimIDs in ONE A51 contradiction route (semicolon-joined `RelatedClaimID` cell) — not three separate pairwise A51 rows.

## Why this fixture exists

The existing `adversarial_nfr_claim_contradiction_001` fixture covers the binary case (2 sources). Real-world engagements often have 3+ sources disagreeing (e.g., ops runbook says X, PM email says Y, customer SLA contract says Z). A naive contradiction-detector would emit 3 pairwise A51 rows (X⊥Y, X⊥Z, Y⊥Z) — bloating the issue register and making the resolution path unclear. The contract-correct behavior: ONE A51 row with `RelatedClaimID = C-001;C-002;C-003`, ONE resolution decision needed, the operator sees one thing to fix.

## Multi-way contradiction covered

Three synthetic input files asserting different SLA windows for the same severity tier. ALL THREE are T2 (authored-primary) — the contradiction is intentionally same-tier so no auto-resolution applies (per `skills/bsa-evidence-intake/references/reliability_tier_spec.md`):

| Input file | Tier | What it claims |
|---|---|---|
| `inputs/source_001_ops_runbook.md` | T2 (authored-primary, ops runbook) | "P0 incident response begins within 15 minutes." |
| `inputs/source_002_sre_handbook.md` | T2 (authored-primary, SRE on-call handbook) | "P0 incident response begins within 5 minutes." |
| `inputs/source_003_customer_sla_contract.md` | T2 (authored-primary, customer-facing SLA contract) | "P0 incident acknowledgement within 60 seconds." |

All three sources DISAGREE on the P0 incident response window (15 min vs 5 min vs 60 sec). All T2 so tier hierarchy doesn't pick a winner.

## Expected pipeline handling

A well-behaved chain must:

1. **Intake captures all three claims** — A59 has 3 direct claims (one from each source). All carry `ClaimStrength=0.0` per the a59 schema's contradiction-routed value; `A51Ref=A51-CONFL-002` propagates the routing on each.
2. **A60 negative-evidence register** captures the cross-links (each claim is negative evidence for the other two — 3 × 2 = 6 cross-link rows total).
3. **A51 contradiction route raised**: ONE `A51-CONFL-002` row with:
   - `IssueType=contradiction`
   - `BlockingStatus=hard`
   - `RaisedByStage=stage1`
   - `RelatedSourceID=S-001;S-002;S-003` (semicolon-joined, all three sources)
   - `RelatedClaimID=C-001;C-002;C-003` (semicolon-joined, all three claims)
   - `NextAction` enumerates the three contradictory values + asks for stakeholder resolution
   - `Severity=critical` (because customer-facing SLA contract is among the contradicted sources — meets the v1.1.1 `critical` semantics: "contractual / customer-facing / regulatory issues")
4. **Single resolution decision needed** — the operator sees ONE A51 row with three options. The fixture's audit_expectations.json explicitly forbids 3 pairwise A51 rows.

Cross-check: zero rows in the fixture silently pick one side; the multi-way contradiction is captured atomically.

## Multi-way contradiction-detector contract

When `bsa-claim-binder` (or any chain step) detects ≥ 2 same-tier claims contradicting on the same measurable target, it MUST emit ONE A51 row with all contradicted `(SourceID, ClaimID)` joined by `;` in the `RelatedSourceID` / `RelatedClaimID` cells. The pattern lets the schema's existing pattern (`^(?:C-...(?:[;/]C-...)*)?$`) handle N-way contradictions without enum-extension or schema change.

The semicolon-joined shape is the v1.1.x convention (`A51_RELATED_CLAIM_DELIMITER = ';'`). Slash (`/`) is also accepted by the schema regex but `;` is preferred for predictable diffs.

## Files

- `inputs/source_001_ops_runbook.md` — first source (T2, claims 15-min response).
- `inputs/source_002_sre_handbook.md` — second source (T2, claims 5-min response).
- `inputs/source_003_customer_sla_contract.md` — third source (T2 customer SLA contract, claims 60-second ack).
- `expected_outputs/canonical/core_controls/A50_source_register.csv` — 3 sources.
- `expected_outputs/canonical/core_controls/A51_issue_route_register.csv` — 1 multi-way contradiction route.
- `expected_outputs/canonical/core_controls/A58_evidence_excerpts.csv` — 3 excerpts (one per claim).
- `expected_outputs/canonical/core_controls/A59_claim_register.csv` — 3 contradicted claims.
- `expected_outputs/canonical/core_controls/A60_negative_evidence_register.csv` — 6 cross-link rows.
- `audit_expectations.json` — declarative regression baseline.
- `fixture_metadata.json` — provenance + authoring mode.

## What this fixture does NOT cover

- Phase-3 propagation (A62/A70/A71/A72) — covered by the binary-contradiction fixture; the multi-way semantics propagate identically (every Phase-3 row touching any of the 3 contradicted claims carries the same A51-CONFL-002 ref).
- Cross-tier contradictions — see `adversarial_tier_delta_auto_resolution_001` for tier-delta ≥ 2 auto-resolution.
- Block-on-contradiction failure mode — see `adversarial_block_on_contradiction_001`.

## Synthetic vs live-run

`authoring_mode = synthetic_adversarial`. Hand-authored canonical state pinning the multi-way contradiction shape. Re-run by `tests/test_adversarial_b3_fixtures.py::TestMultiWayContradiction`.
