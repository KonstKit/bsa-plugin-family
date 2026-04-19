# Merge and Re-entry Policy

## Merge Checklist
1. Stage-owned proposal path is valid.
2. Evidence-binding gate passes.
3. Required audit marker set exists.
4. Shared-governance policy is not violated (`A48/A50/A51` parallel ledger check).
5. No hard-blocking `A51` item remains unresolved for the promoted scope.
6. Merge lock is acquired.
7. Discovery → main merge step — when the current run is in `discovery_then_bsa` mode and `discovery.go` has fired, run the discovery→main merge per [discovery_to_main_merge.md](discovery_to_main_merge.md) before promoting Stage 1. Any `claim_conflict` or `excerpt_text_conflict` event halts the promotion via a hard-blocking `A51` contradiction row; `source_tier_mismatch` events are logged but non-blocking.

## Required Audit Markers
Discovery:
- d1 -> `discovery.d1.ready.json`
- d2 -> both `discovery.d2.claims.merged.json` and `discovery.d2.research_quality.pass.json`
- d3 -> `discovery.d3.prioritization.pass.json`
- d4 -> `discovery.d4.constraint_audit.pass.json`
- d5 -> `discovery.d5.citation_audit.pass.json` and `discovery.d5.no_solution_leakage.pass.json`
- Optional strict discovery profile adds:
  - `discovery.d5.skeptical_review.pass.json`
  - `discovery.d5.no_new_claims.pass.json` (legacy: `discovery.d5.no_new_facts.pass.json` — accepted for read-only in pre-v1.0 workspaces; migration via `scripts/migrate_v0.9_to_v1.0.py`)

Main cycle:
- stage1 -> `stage1.excerpts.merged.json`
- stage2 -> `stage2.context_state.pass.json`
- stage3 -> `stage3.citation_audit.pass.json`
- stage5 -> `stage5.anchor_audit.pass.json`
- stage6 -> `stage6.anchor_audit.pass.json`
- stage7 -> `stage7.skeptical_review.pass.json`
- stage8 -> `stage8.no_new_claims.pass.json`
- handoff -> `stage8.no_new_claims.pass.json`

## D0 -> BSA Entry Policy
- `discovery.go` enables Stage 1 only with `bsa.stage1.entry.enabled`.
- `discovery.pivot`, `discovery.more_research`, `discovery.no_go` block Stage 1.

## Re-entry Rule
Any invalidation opens explicit re-entry marker for affected stage family (discovery or main) and marks all downstream promoted surfaces as stale until revalidated.
