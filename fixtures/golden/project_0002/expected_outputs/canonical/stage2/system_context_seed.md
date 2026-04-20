# System-Context Seed — fixture-project-0002

## System Boundary

The `analytics_platform` dbt project encompasses three schema layers: `stg` (staging), `mart` (dimensional), and `ref` (reference-data seeds). The system boundary includes all dbt models under these schemas plus the ownership tags carried on each model block [C-001] [C-002] [C-003]. Out-of-boundary: dashboarding tools that consume the mart schema, raw event-producing systems upstream of staging.

## Neighboring Systems

- **Raw event producers** (upstream of `stg`): feed the typed views via ETL; not owned by any dbt-tracked team; lineage drift from upstream changes is the primary pain point documented in C-005.
- **BI/dashboarding layer** (downstream of `mart`): consumes dim/fct tables but is not assigned ownership of any dbt-tracked model [C-004].
- **Incident tracker** (orthogonal): cited as the evidence source for C-005 validation (A51-001).
- **Data governance function** (orthogonal): named as the decision-authority path for A51-003 custodianship assignment.

## Interface Obligations

- `stg.*` tables MUST emit change notifications to downstream consumers (including `mart.*`); lack of this notification is the root cause cited in C-005 lineage drift [C-005].
- `mart.*` tables MUST consume `stg.*` without adding raw-event logic; marts apply business rules on top of typed staging views [C-002].
- `ref.*` seeds have no documented update-notification protocol; updates currently occur without attribution [C-006].

## Context Triggers

A canonical promotion cycle is triggered when:
- A new dbt model is authored (requires owner-tag assignment per C-001/C-002 conventions).
- An existing model changes schema (requires downstream-consumer notification per C-005 gap).
- A new `ref` seed is introduced (requires custodian designation per A51-003 resolution).
- Any dashboard incident roots in an upstream `stg` change the downstream `mart` owner did not hear about (primary pain point per C-005).
