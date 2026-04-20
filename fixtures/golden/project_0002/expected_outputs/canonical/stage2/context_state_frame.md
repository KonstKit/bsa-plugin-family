# Context-State Frame — fixture-project-0002

## Problem Or Objective

Audit the analytics-platform dbt lineage and clarify cross-team ownership between data engineering, analytics engineering, BI consumers, and reference-data custodianship [C-001] [C-002] [C-003] [C-006].

## Scope Boundary

### In

- Staging-schema (`stg`) ownership — formally assigned to data engineering per dbt tags `data_eng_owned` [C-001].
- Marts-schema (`mart`) ownership — formally assigned to analytics engineering per dbt tags `ae_owned` [C-002].
- Reference-data (`ref` schema) custodianship gap — structurally visible in the dbt config and corroborated by attestation [C-003] [C-006].
- BI-consumer ownership position vs the marts layer [C-004] [A51-002].

### Out

- Individual dashboard rewrites (scope intersects only at the consumer interface, not the dashboard authoring).
- New dimensional-model design (scope is ownership, not model schema changes).
- Performance tuning of the dbt build graph.

## Context Mode

`discovery_then_bsa`. Scope was initially fuzzy ("clarify ownership") and multiple stakeholder teams disagreed on boundaries (see `stakeholder_authority_map.md` contestation rows). Discovery phase framed the ownership question; BSA main cycle promotes the canonical layer.

## Stakeholders

Authority and contestation detail live in `stakeholder_authority_map.md`. In-scope stakeholders: data-engineering team lead (stg owner), analytics-engineering team lead (mart owner), BI consumer lead (unowned consumer; contested), data governance sponsor (reference-data decision; pending per A51-003).

## Constraints

Constraint + dependency detail lives in `constraints_dependencies_route.md`. Key constraints:
- dbt project config must remain the source-of-truth for model ownership tags (not a separate artifact) [C-001] [C-002].
- Any custodianship assignment for `ref` schema seeds requires sponsor sign-off before downstream promotion [A51-003].
- The 30%-lineage-drift figure is an AE rough estimate pending T1-T3 triangulation — not a committed SLA target [C-005] [A51-001].

## Dependencies

- Incident-tracker export for A51-001 triangulation (external system; 90-day window requested).
- BI-team-maintained consumer catalog for A51-002 triangulation (artifact may not exist; stakeholder attestation acceptable fallback).
- Data governance sponsor availability for A51-003 custodianship sign-off.

## Open Uncertainties

Each uncertainty is routed to an A51 row with resolution plan. No uncertainty exceeds `BlockingStatus=soft` at Stage 2 promotion time.

- [A51-001] exact incident-rate figure (30%-is-attestation) — pending incident-tracker export.
- [A51-002] BI-consumer ownership status — pending BI-side attestation.
- [A51-003] reference-data custodian assignment — pending sponsor decision.
