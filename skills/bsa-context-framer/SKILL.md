---
name: bsa-context-framer
description: Build Stage 2 context and system-framing artifacts from promoted Stage 1 claim-layer outputs, producing context_state_frame, stakeholder_authority_map, system_context_seed, constraints_dependencies_route, and stage2_summary with evidence-binding and analyst_judgment discipline.
---

# BSA Context Framer

Run this skill for Stage 2 context and system framing.

## Scope
- Build context/state frame from promoted Stage 1 claim-layer (`A58/A59`).
- Build stakeholder authority map tied to `A51` routing where authority is contested or unclear.
- Seed system context boundary, neighboring systems, interface obligations, and context triggers.
- Route constraints and dependencies through shared `A51`.
- Emit `stage2_summary.json` as the machine-readable digest gating Stage 3 start.
- Surface analyst recommendations explicitly as `ClaimType=analyst_judgment` rows in A59 with justification rationale referencing upstream claims (INV-07).

## Mandatory Reference Load
- Read [references/context-state-contract.md](references/context-state-contract.md) before writing Stage 2 artifacts.
- Read [references/stakeholder-authority-rules.md](references/stakeholder-authority-rules.md) when building `stakeholder_authority_map.md`.
- Read [references/system-context-seed-template.md](references/system-context-seed-template.md) when building `system_context_seed.md`.

## Inputs
- Canonical `analysis/canonical/core_controls/A58_evidence_excerpts.csv`
- Canonical `analysis/canonical/core_controls/A59_claim_register.csv`
- Canonical `analysis/canonical/core_controls/A60_negative_evidence_register.csv`
- Canonical `analysis/canonical/core_controls/A51_issue_route_register.csv`
- Canonical `analysis/canonical/core_controls/A48_run_context_card.md`
- Optional `analysis/discovery/canonical/d5/stage2_seed_bundle.md` when arriving from discovery path.

## Outputs
- `analysis/proposals/stage2/context_state_frame.md`
- `analysis/proposals/stage2/stakeholder_authority_map.md`
- `analysis/proposals/stage2/system_context_seed.md`
- `analysis/proposals/stage2/constraints_dependencies_route.md`
- `analysis/proposals/stage2/stage2_summary.json`

## Workflow
1. Read promoted Stage 1 claim-layer and shared `A48/A50/A51`.
2. If `A48.Mode == discovery_then_bsa`, read `stage2_seed_bundle.md` as seed material (wording aid only, never as claim source).
3. Extract context frame content under required section headers per `context-state-contract.md`.
4. Build stakeholder authority map rows linked to `A51Ref` where authority is contested.
5. Seed system context (boundary + neighbors + interface obligations + triggers) from framed claims.
6. Route constraints and dependencies through `A51` with `source_ref` and `escalation_target`.
7. Emit `stage2_summary.json` with required fields and digests.
8. Surface analyst recommendations as `ClaimType=analyst_judgment` additions to A59 proposal layer when downstream context reasoning requires non-evidence-backed statements; each such row must carry non-empty `JustificationRationale` referencing at least one upstream `ClaimID` from A59 (INV-07).

## Invariants
- Every row, section, or bullet containing a positive factual claim must trace to `ClaimID` (with `SourceID+ExcerptID`) or explicit `A51Ref` (INV-01).
- `ClaimType=analyst_judgment` rows may be authored by this skill but MUST carry `JustificationRationale` referencing at least one upstream ClaimID different from the row's own ClaimID (INV-07).
- Stage 2 artifacts cannot introduce actors, entities, events, statuses, or rules that are not already present in promoted Stage 1 claim-layer — catalog stabilization is Stage 4 work.
- `stage2_summary.json` digests are computed from promoted canonical inputs; re-running this skill must produce stable digests when inputs have not changed.
- Canonical writes are forbidden for this worker; outputs live in `analysis/proposals/stage2/` until orchestrator two-key promotion (evidence-binding + `stage2.context_state.pass` marker).

## On Audit Failure
1. Read Stage 2 audit findings and missing-section/digest diagnostics.
2. Correct only Stage 2 proposal artifacts owned by this skill.
3. Route unresolved context ambiguity or authority conflicts to `A51Ref` rather than inventing structure.
4. Regenerate `stage2_summary.json` so digests match the revised proposal state.
5. Re-submit for Stage 2 quality flow before `stage2.context_state.pass` promotion.

## Validation Binding
- `SCN-STAGE2-001-A`: required artifact set present and shape-valid.
- `SCN-STAGE2-001-B`: context_state_frame has all required headers; stakeholder_authority_map + constraints_dependencies_route have required columns.
- `SCN-STAGE2-001-C`: stage2_summary.json fields and digests present; analyst_judgment claims, if authored, have JustificationRationale referencing upstream ClaimIDs.

## References
- [references/context-state-contract.md](references/context-state-contract.md)
- [references/stakeholder-authority-rules.md](references/stakeholder-authority-rules.md)
- [references/system-context-seed-template.md](references/system-context-seed-template.md)
