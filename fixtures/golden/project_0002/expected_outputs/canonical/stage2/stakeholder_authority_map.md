# Stakeholder Authority Map — fixture-project-0002

| stakeholder_id | stakeholder_name | authority_level | decision_scope | linked_a51_refs |
|---|---|---|---|---|
| STK-001 | data_engineering_lead | owner | Staging-schema models (`stg.*`) including `stg_events`, `stg_users`. Upstream-change notification obligations [C-001]. |  |
| STK-002 | analytics_engineering_lead | owner | Marts-schema models (`mart.*`) including `fct_user_activity`, `dim_user` [C-002]. |  |
| STK-003 | bi_consumer_lead | consumer | Consumes `mart.*` but is NOT assigned ownership of any dbt-tracked model; contested via single-source attestation pending BI-side triangulation [C-004]. | A51-002 |
| STK-004 | data_governance_sponsor | decision_authority | Cross-cutting custodianship decisions; currently pending on reference-data (`ref.*`) assignment per A51-003. | A51-003 |
| STK-005 | reference_data_custodian | unassigned | `ref.*` seed tables (lookup tables, taxonomies). Currently no team is formally assigned; multiple teams update without attribution [C-006]. | A51-003 |
