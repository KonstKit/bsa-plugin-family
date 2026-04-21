---
name: bsa-story-writer
description: Author user stories in A70_story_register.csv from promoted A59 claims and A62 NFRs. Each story MUST trace to >= 1 ClaimID or >= 1 NFRID (INV-08). INVESTStatus enforced; deferred checks co-populate A51Ref. Phase 3 skill — runs after phase3.nfr.pass and before phase3.test_scenario.
---

# BSA Story Writer

Run this skill after `bsa-nfr-collector` has promoted `A62_nfr_register.csv`. Produces user stories that downstream skills (`bsa-test-scenario-builder`, `bsa-traceability-matrix`, `bsa-backlog-bridge`) consume.

## Scope

- Read promoted A59 (claims) + A62 (NFRs) + relevant handoff packets (H2).
- Author user stories in `A70_story_register.csv` per the canonical "As a `<persona>`, I want `<goal>`, so that `<benefit>`" shape.
- Apply INVEST acceptance criteria (Independent, Negotiable, Valuable, Estimable, Small, Testable); mark `INVESTStatus` accordingly. Any non-`pass` value MUST co-populate `A51Ref` so the decision / action is tracked.
- Never introduce net-new subjects, verbs, or conditions absent from the upstream claim/NFR set — stories are reshape operations, not authoring.

Out of scope:
- Estimation in story points — consuming team owns that. `EstimationHint` is a T-shirt-size producer hint only.
- Sprint / epic grouping — bsa-backlog-bridge (Sprint 9) handles that at export time.
- Approval / PO sign-off — the skill authors proposals; promotion through `/bsa-promote` + downstream PO review is the human gate.

## Inputs

- Promoted `analysis/canonical/core_controls/A59_claim_register.csv`
- Promoted `analysis/canonical/core_controls/A62_nfr_register.csv`
- Promoted `analysis/canonical/core_controls/A50_source_register.csv` (for actor/persona grounding)
- Promoted `analysis/handoff/H2_delivery_packet.md`
- Shared `analysis/canonical/core_controls/A51_issue_route_register.csv`

## Outputs

- `analysis/proposals/phase3/A70_story_register.csv`
- `analysis/proposals/phase3/story_authoring_report.md`

Both land under `analysis/proposals/phase3/`. Promotion to canonical goes through `/bsa-promote` with the two-key gate (evidence-binding on SourceClaimIDs/RelatedNFRIDs + `phase3.story.pass` marker).

## Workflow

1. **Load inputs.** Read A59, A62, A50, A51 canonical + H2 handoff packet. Fail fast if A59 or A62 is not promoted (story authoring requires both).

2. **Identify candidate groupings.** For each distinct subject (actor / system component / process step) mentioned across A59 + A62, collect the claims and NFRs that touch it. A story typically corresponds to one subject-verb pair at one point in a workflow.

3. **Choose personas.** The story's `Persona` field MUST name an actor identified in upstream material — an A50 source attribution, an A59 claim subject, or an A62 NFR subject. Inventing personas ("As a stakeholder...") is banned (see `x-bsa-banned-story-patterns` in the schema).

4. **Author the story text.** Canonical form: `As a <persona>, I want <goal>, so that <benefit>`. The `<benefit>` clause is strongly recommended; omit only when truly redundant with `<goal>`. Stay within the semantic territory of the source claims/NFRs — do not invent new conditions.

5. **Derive acceptance criteria.** Each criterion MUST be observable. When an NFR is linked via `RelatedNFRIDs`, embed the NFR's Metric+Target (if quantitative) as an acceptance line. When only A59 claims link, ground acceptance in the claim text. Multi-criterion rows use `;` or newline separation.

6. **Run the INVEST check.** Mark `INVESTStatus`:
   - `pass` — all six criteria met.
   - `needs-splitting` — the story is too large (touches multiple personas or workflow steps). Split and raise an A51 `decision_needed` for the split plan.
   - `needs-estimation` — team input required on sizing. Raise an A51 `decision_needed`.
   - `needs-testable-acceptance` — acceptance criteria are not concretely observable. Raise an A51 `missing_source` or `decision_needed` depending on gap type.
   - `needs-negotiation` — story is a mandate disguised as a story (likely reflects an INV-03 leak: the upstream claim is itself a prescription). Route to PO via A51 `decision_needed`.
   - `escalate` — multiple INVEST criteria failed; PO triage required. A51 `decision_needed` with severity=high.

7. **Populate cross-reference fields.** `SourceClaimIDs` — semicolon-joined A59 ClaimIDs; `RelatedNFRIDs` — semicolon-joined A62 NFRIDs. At least one of the two MUST be non-empty (INV-08). Priority inherits from highest source-claim Criticality.

8. **Emit artifact + report.** Write `A70_story_register.csv` and `story_authoring_report.md`. Report includes: total claims + NFRs scanned, stories authored, INVESTStatus distribution, A51 routes raised, coverage gaps (claims with no resulting story, NFRs with no linking story).

## Invariants

- **INV-08 (Phase 3)** — `SourceClaimIDs` OR `RelatedNFRIDs` non-empty on every row. Enforced by schema + this skill's own output check.
- **INV-03 (main cycle)** — stories MUST NOT introduce subjects / verbs / conditions absent from upstream claims. This is the no-new-claims discipline applied to stories. A no-new-stories auditor (US-S7-03) will run against A70 before promotion as a downstream gate.
- **INVEST-A51 coupling** — `INVESTStatus != 'pass'` requires non-empty `A51Ref`. Stories with deferred INVEST checks are only useful if the decision path is recorded.

## Failure modes

- **A62 not promoted** — skill exits with error pointing to `bsa-nfr-collector` / `phase3.nfr.pass`.
- **No candidate claims / NFRs** — report records `stories authored: 0` with a reason; not an error. Some engagements produce only architectural observations without user-facing stories.
- **INV-08 violation on any row** — F5 write-validator blocks the write; skill retries with correction (either add provenance, escalate via A51, or drop the row).
- **INVEST all-deferred on too many rows** — skill emits a summary line in the report (`>50% of stories are INVEST-deferred — upstream claim quality is the likely cause; review A59 for prescriptive claims that belong in a different artifact`).

## Composition

Invoked by `/bsa-dev-handoff` (Phase-3 composite command) as the second stage: `phase3.nfr → phase3.story → phase3.test_scenario → phase3.traceability → phase3.backlog_exported`.

May also be invoked directly via `/bsa-dev-handoff --only=story` for debugging / partial re-runs; prerequisites (phase3.nfr.pass + promoted A62) must be satisfied.

Downstream consumers read the promoted A70; they do not invoke this skill directly (INV-06 composition-via-orchestrator).

## Cross-refs

- `governance/schemas/a70.schema.json` — row schema + INVEST + provenance extensions.
- `skills/bsa-nfr-collector/SKILL.md` — upstream NFR authoring contract.
- `skills/bsa-nfr-collector/references/nfr-extraction-contract.md` — NFR derivation rules (useful for understanding how RelatedNFRIDs are shaped).
- `skills/bsa-no-new-claims-auditor/SKILL.md` — the main-cycle equivalent of the no-new-stories discipline that applies here.
- `docs/phase_3_plan.md` — Phase-3 sequencing + Sprint 7-9 scope.
- `commands/bsa-dev-handoff.md` — composite command that invokes this skill.
