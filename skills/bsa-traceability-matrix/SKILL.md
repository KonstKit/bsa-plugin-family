---
name: bsa-traceability-matrix
description: SCAFFOLD (Sprint 8 US-S8-02). Build A72_traceability_matrix.csv linking A70 stories to A59 claims to A50 sources. Three-way join with row-per-link granularity for orphan / coverage queries. Phase 3 skill.
---

# BSA Traceability Matrix (SCAFFOLD)

> **Status:** scaffold only. Implementation lands in Sprint 8 (US-S8-02).
>
> **TODO anchors:**
> - `[TODO-S8-02-A72-SCHEMA]` — schema with at minimum (StoryID, NFRID, ClaimID, SourceID, LinkType, LinkStrength).
> - `[TODO-S8-02-ORPHAN-DETECTION]` — output also includes orphan reports: stories without claims, claims without stories, NFRs without scenarios.
> - `[TODO-S8-02-COVERAGE-METRICS]` — KPI-006 (Phase-3) — story-to-claim coverage ratio.

## Scope (planned)

- Walk A70 stories → resolve A70.SourceClaimIDs → A59 claims → A59.SourceID → A50 sources.
- Walk A70 stories → A70.RelatedNFRIDs → A62 NFRs → A62.SourceClaimIDs → ... (same expansion).
- Emit one row per Story↔ClaimID↔SourceID triple in `A72_traceability_matrix.csv`.

## Output reports (planned)

- `traceability_orphans.md` — items at any layer without uplink.
- `traceability_coverage.md` — KPI scorecard.

## Invariants (planned)

- Pure derivation skill — never authors net-new claim/story content. Output is exclusively the join.
- Every A72 row resolves to existing A70 + A59 + A50 IDs (foreign-key validity check).

## TODO

- `[TODO-S8-02-LINK-TYPE-ENUM]` — direct / inferred / nfr-mediated / a51-routed.
