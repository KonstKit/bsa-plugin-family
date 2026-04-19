# Pilot Runbook

## Modes
- Direct mode: start from materials -> composite Stage 1.
- Discovery mode: run D1-D5 first, then optional Stage 1 entry by discovery decision.

## Discovery Sequence (optional)
1. Run D1 and promote.
2. Run D2, emit `discovery.d2.claims.merged` + `discovery.d2.research_quality.pass`, then promote.
3. Run D3, emit `discovery.d3.prioritization.pass`, promote.
4. Run D4, emit `discovery.d4.constraint_audit.pass`, promote.
5. Run D5, emit `discovery.d5.citation_audit.pass` + `discovery.d5.no_solution_leakage.pass`, promote.
6. Emit `discovery.exit.pass` and one decision marker (`go/pivot/more_research/no_go`).
7. If `go`, ensure `bsa.stage1.entry.enabled` exists, then continue main cycle.

## Main Sequence
1. Stage1 (`bsa-evidence-intake` -> `bsa-claim-binder`) -> `stage1.excerpts.merged`.
2. Stage2 via `bsa-context-framer` (context/state framing) -> `stage2.context_state.pass`.
3. Stage3 semantic extraction + stage audit -> `stage3.citation_audit.pass`.
4. Stage4 domain modeling.
5. Stage5 backbone construction + anchor audit -> `stage5.anchor_audit.pass`.
6. Stage6 contract construction + anchor audit -> `stage6.anchor_audit.pass`.
7. Stage7 skeptical gate -> `stage7.skeptical_review.pass`.
8. Stage8 no-new-claims gate -> `stage8.no_new_claims.pass`.
9. Handoff packaging (shares Stage 8 no-new-claims gate contract).

## Final Checks
- quote-fidelity and no-new-claims checks pass for Stage 8 and handoff.
- discovery outputs are audited with reused citation/skeptical/no-new-facts principles before `discovery.go`.
- `ART-VAL-001-09` is satisfied when discovery-triggered BPMN/C4 remain derived-only.
