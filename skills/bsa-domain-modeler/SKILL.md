---
name: bsa-domain-modeler
description: Build Stage 4 domain and behavior model proposals from merged Stage 3 outputs, with anchor-ready provenance for critical entities.
---

# BSA Domain Modeler

Run this skill for Stage 4 stabilization.

## Scope
- Build actor/entity/event/status/rule catalogs.
- Build glossary and cross-catalog linkage.
- Prepare anchor-ready provenance for critical elements to support `A61`.

## Mandatory Reference Load
- Read [references/catalog-stabilization.md](references/catalog-stabilization.md) before writing Stage 4 catalogs.

## Inputs
- `analysis/canonical/stage3/semantic_core_rows.md`
- `analysis/canonical/stage3/semantic_traceability_report.md`
- `analysis/canonical/core_controls/A59_claim_register.csv`
- `analysis/canonical/core_controls/A51_issue_route_register.csv`

## Outputs
- `analysis/proposals/stage4/actor_catalog.md`
- `analysis/proposals/stage4/entity_catalog.md`
- `analysis/proposals/stage4/event_trigger_catalog.md`
- `analysis/proposals/stage4/status_lifecycle_catalog.md`
- `analysis/proposals/stage4/rule_catalog.md`
- `analysis/proposals/stage4/glossary_v2.md`
- `analysis/proposals/stage4/cross_catalog_linkage_matrix.md`
- `analysis/proposals/stage4/open_modeling_questions.md`
- `analysis/proposals/stage4/stage4_anchor_candidates.csv`
- `analysis/proposals/stage4/stage4_anchor_provenance.csv`

## Invariants
- Stage 4 may stabilize labels and groupings from Stage 3, but cannot add net-new actors, entities, events, statuses, or rules unless routed as unresolved `A51Ref` candidates.
- Critical catalog rows must remain traceable to canonical Stage 3 rows.

## On Audit Failure
1. Read downstream findings tied to Stage 4 artifacts.
2. Update only Stage 4 proposal outputs owned by this skill.
3. Preserve claim lineage and route unresolved contradictions to `A51Ref`.
4. Re-submit for downstream Stage 5/6 consumption.

## Validation Binding
- `SCN-STAGE46-001-A`: Stage 4 catalogs from merged Stage 3.
- `SCN-STAGE46-001-E`: critical Stage 4 anchors prepared for `A61`.

## Reference
- [references/catalog-stabilization.md](references/catalog-stabilization.md)
