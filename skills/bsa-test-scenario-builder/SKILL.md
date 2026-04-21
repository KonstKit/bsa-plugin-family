---
name: bsa-test-scenario-builder
description: SCAFFOLD (Sprint 8 US-S8-01). Build test scenarios in A71_test_scenario_register.csv from A70 stories and measurable A62 NFRs. Every scenario MUST trace to a SourceStoryID per INV-10. Phase 3 skill — runs after phase3.story.pass.
---

# BSA Test Scenario Builder (SCAFFOLD)

> **Status:** scaffold only. Implementation lands in Sprint 8 (US-S8-01).
>
> **TODO anchors:**
> - `[TODO-S8-01-A71-SCHEMA]` — `governance/schemas/a71.schema.json` with required SourceStoryID column.
> - `[TODO-S8-01-GHERKIN]` — choose scenario notation (Gherkin Given-When-Then is the obvious fit; pin the dialect).
> - `[TODO-S8-01-NFR-COVERAGE]` — every measurable A62 row should drive at least one scenario.

## Scope (planned)

- For each A70 story, derive 1+ test scenarios in Gherkin-style Given-When-Then.
- For each measurable A62 NFR (Metric+Target populated), derive a verification scenario keyed to NFR's TestabilityNotes.
- Output: `A71_test_scenario_register.csv` + `test_scenario_authoring_report.md`.

## Inputs (planned)

- Promoted `analysis/canonical/core_controls/A70_story_register.csv`
- Promoted `analysis/canonical/core_controls/A62_nfr_register.csv`
- Promoted `analysis/canonical/core_controls/A59_claim_register.csv` (for Given-clauses grounding)

## Invariants (planned)

- INV-10 (Phase 3): every A71 row has non-empty `SourceStoryID`. Scenarios without stories are rejected.
- Scenarios for measurable NFRs MUST embed the Metric+Target as the assertion (no aspirational scenarios).

## TODO

- `[TODO-S8-01-RUNNABLE-EXPORT]` — should A71 export to a runnable form (Cucumber / pytest-bdd)? Decide by Sprint 8.
