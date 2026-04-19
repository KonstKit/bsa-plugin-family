# Golden Fixture `project_0001`

**Scenario:** minimal synthetic Support-Ticket Triage system analysis.
**Mode:** `direct` (no discovery branch exercised).
**Path:** `process` (Stage 5 backbone is process-oriented).
**ClaimType coverage:** `direct`, `inference`, `analyst_judgment` — all three.

## Honesty scope

This fixture is **shape-level representative**, not the literal output of a real end-to-end pipeline run. Phase 0 MVP does not yet include a live orchestrator harness that can drive all 22 skill prompts through real model inference; running such a harness is Phase 2+ work (plugin MVP in Sprint 4 wires slash-commands that invoke skills).

What the fixture IS:
- Synthetic inputs under `inputs/` — sanitized, domain-neutral narrative.
- Hand-authored `expected_outputs/canonical/` demonstrating the exact shape and invariants a real run is contracted to produce: evidence-binding, ClaimType enum closure, A51 routing, multi-stage anchor provenance.
- `expected_markers/` showing the runtime-marker schema at each pass gate.
- `audit_expectations.json` encoding which audit verdicts are expected.
- `fixture_metadata.json` pinning model/canon-policy/plugin versions.

What the fixture IS NOT:
- A record of a real model-driven run.
- A regression guarantee against semantic changes in individual skills (that gate is pytest + individual skill validators).

## Regression semantics

`scripts/fixture_runner.py`:
- `--mode=validate` — verifies fixture-internal invariants (every A59 row has ClaimID+SourceID+ExcerptID or A51Ref; analyst_judgment rows have justification_rationale referencing ≥1 upstream ClaimID; marker schemas conform).
- `--mode=compare` — regenerates nothing; verifies that committed `expected_outputs/**` match the on-disk state. Any diff surfaces as a finding, catching accidental fixture drift.

Combined, these two modes turn the fixture into a machine-checkable demonstration of the claim-binding discipline the pipeline enforces at runtime.

## Replacing this fixture with a real pipeline run

In Sprint 4.5 (plugin v1.0.0 release), a second fixture set will capture real orchestrator-driven runs on sanitized projects. At that point `project_0001` will be re-verified against the live pipeline and promoted to a regression anchor for every downstream skill change.
