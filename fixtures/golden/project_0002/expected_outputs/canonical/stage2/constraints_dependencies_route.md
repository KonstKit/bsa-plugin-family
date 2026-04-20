# Constraints and Dependencies Route — fixture-project-0002

| constraint_id | dependency_id | source_ref | escalation_target | linked_a51_refs |
|---|---|---|---|---|
| CONS-001 |  | C-001 + C-002 | data_engineering_lead / analytics_engineering_lead |  |
| CONS-002 | DEP-001 | C-003 + C-006 | data_governance_sponsor | A51-003 |
| CONS-003 | DEP-002 | C-005 | external incident-tracker system owner | A51-001 |
| CONS-004 | DEP-003 | C-004 | bi_consumer_lead | A51-002 |
| CONS-005 |  | CONS-001 (derived) | analytics_engineering_lead |  |

Constraint legend:
- **CONS-001** — dbt project config (`dbt_project.yml`) MUST remain the source-of-truth for model ownership tags. No parallel ownership ledger (e.g., a separate wiki) may override the tag-in-config rule.
- **CONS-002** — Any custodianship assignment for `ref.*` seeds requires data-governance-sponsor sign-off (A51-003) before the A59 row can be promoted beyond `analyst_judgment` → `direct` / `inference` status.
- **CONS-003** — The 30%-lineage-drift figure (C-005) is a rough attestation estimate and MUST NOT be cited as an SLA target or detection-latency commitment until triangulated against an incident-tracker export (A51-001).
- **CONS-004** — BI-consumer ownership status (C-004) is single-source (AE attestation only) and MUST NOT be promoted as a non-contested direct claim until BI-side attestation lands (A51-002).
- **CONS-005** — Derived: the ae-owned convention requires analytics engineering to emit consumer-facing notifications when any `mart.*` changes shape; lack of this notification breaks the reciprocal of CONS-001 (the staging-owner's notification obligation).
