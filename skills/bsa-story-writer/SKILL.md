---
name: bsa-story-writer
description: SCAFFOLD (Sprint 7 US-S7-02). Generate user stories in A70_story_register.csv from promoted A59 claims and A62 NFRs. Every story MUST trace to >= 1 ClaimID OR >= 1 NFRID per INV-08. Phase 3 skill — runs after phase3.nfr.pass.
---

# BSA Story Writer (SCAFFOLD)

> **Status:** scaffold only. Implementation lands in Sprint 7 (US-S7-02). This SKILL.md documents the intended interface so downstream skills (`bsa-test-scenario-builder`, `bsa-traceability-matrix`) can be designed against a stable contract.
>
> **TODO anchors:**
> - `[TODO-S7-02-A70-SCHEMA]` — author `governance/schemas/a70.schema.json` before this skill goes live.
> - `[TODO-S7-02-INVEST]` — encode INVEST acceptance criteria in the workflow.
> - `[TODO-S7-02-NO-NEW-STORIES-AUDITOR]` — pair with a no-new-stories auditor (mirrors no-new-claims).

## Scope (planned)

- Read promoted A59 claims + A62 NFRs.
- Author user stories in `A70_story_register.csv` per INVEST principles (Independent / Negotiable / Valuable / Estimable / Small / Testable).
- Every story carries `SourceClaimIDs` (≥ 1 from A59) and/or `RelatedNFRIDs` (≥ 1 from A62) — INV-08.

Out of scope:
- Estimating story points — that's owned by the team consuming the backlog.
- Sprint planning — out of plugin scope entirely.

## Inputs (planned)

- Promoted `analysis/canonical/core_controls/A59_claim_register.csv`
- Promoted `analysis/canonical/core_controls/A62_nfr_register.csv`
- Promoted `analysis/handoff/H2_delivery_packet.md`

## Outputs (planned)

- `analysis/proposals/phase3/A70_story_register.csv`
- `analysis/proposals/phase3/story_authoring_report.md`

## Workflow (skeleton)

1. `[TODO-S7-02-CANDIDATE-FILTER]` — decide which claims/NFRs map to which story granularity.
2. `[TODO-S7-02-INVEST-VALIDATION]` — author each story; verify INVEST criteria pre-emit.
3. `[TODO-S7-02-ACCEPTANCE-CRITERIA]` — derive acceptance criteria from NFR Metric+Target where present.
4. `[TODO-S7-02-A51-ROUTE]` — route stories that lack clear value or test path through A51.
5. Emit A70 + report.

## Invariants (planned)

- INV-08 (Phase 3): every A70 row has non-empty `SourceClaimIDs` OR `RelatedNFRIDs`.
- No new claim content in stories — story text MUST stay within the upstream claim/NFR semantics.

## Cross-refs

- `docs/phase_3_plan.md` — Phase-3 sequencing.
- `skills/bsa-nfr-collector/SKILL.md` — upstream contract.
- `governance/schemas/a70.schema.json` — TO BE WRITTEN in Sprint 7.
