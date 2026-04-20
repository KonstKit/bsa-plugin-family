# H2 Delivery Packet — Analytics Platform Ownership Audit

## Delivery Manifest (what's included)

| Artifact | Role | Canonical path | Version |
|---|---|---|---|
| A48 run context card | run metadata | `analysis/canonical/core_controls/A48_run_context_card.md` | 1.0.0-rc2 |
| A50 source register | source ledger | `analysis/canonical/core_controls/A50_source_register.csv` | 1.0.0-rc2 |
| A51 issue route register | unresolved items | `analysis/canonical/core_controls/A51_issue_route_register.csv` | 1.0.0-rc2 |
| A58 evidence excerpts | evidence layer | `analysis/canonical/core_controls/A58_evidence_excerpts.csv` | 1.0.0-rc2 |
| A59 claim register | claim layer | `analysis/canonical/core_controls/A59_claim_register.csv` | 1.0.0-rc2 |
| A60 negative evidence | counter-evidence | `analysis/canonical/core_controls/A60_negative_evidence_register.csv` | 1.0.0-rc2 |
| Stage 2 context state | context frame | `analysis/canonical/stage2/context_state_frame.md` | 1.0.0-rc2 |

## Requirements Summary (references fr_register/nfr_register)

Functional Requirements:

| FR-ID | Title | Priority | Owner role | ClaimID refs |
|---|---|---|---|---|
| FR-001 | Staging-schema models carry explicit owner tags (`data_eng_owned`) | must | data_engineering_lead | [C-001] |
| FR-002 | Marts-schema models carry explicit owner tags (`ae_owned`) | must | analytics_engineering_lead | [C-002] |
| FR-003 | Reference-data seeds carry an explicit custodian tag | should | data_governance_sponsor | [AJ:C-007] [C-003] |

Non-Functional Requirements:

| NFR-ID | Category | Target | Measurement | ClaimID refs |
|---|---|---|---|---|
| NFR-001 | observability | Upstream (`stg.*`) change notifications reach downstream (`mart.*`) before the next dashboard incident | incident-tracker root-cause tagging | [C-005] [A51-001] |
| NFR-002 | governance | BI consumers have either an owner-tag or a documented consumer catalog | single pointer-of-truth audit | [C-004] [A51-002] |

## Contracts & Interfaces (references A61)

| AnchorID | Contract name | Consumer | Producer | Contract kind | Reference |
|---|---|---|---|---|---|
| ANC-SCHEMA-001 | stg schema ownership boundary | mart layer | data engineering | data | `analysis/canonical/stage6/contracts/stg_boundary.md` |
| ANC-SCHEMA-002 | mart schema ownership boundary | BI consumers | analytics engineering | data | `analysis/canonical/stage6/contracts/mart_boundary.md` |
| ANC-SCHEMA-003 | ref schema custodianship (pending) | any seed consumer | unassigned | data | deferred pending A51-003 |

## Data & State (references entity/status catalogs)

Entities:

| Entity | Owner | Lifecycle | Canonical ref |
|---|---|---|---|
| stg.* models | data_engineering_lead | continuous-dbt-build | `analysis/canonical/stage4/domain_model/stg_entities.md` |
| mart.* models | analytics_engineering_lead | continuous-dbt-build | `analysis/canonical/stage4/domain_model/mart_entities.md` |
| ref.* seeds | unassigned | on-manual-update | `analysis/canonical/stage4/domain_model/ref_seeds.md` |

State machines:

| Entity | States | Transitions | Terminal states | Canonical ref |
|---|---|---|---|---|
| incident (lineage-drift scope) | detected, triaged, attributed, resolved | detected→triaged→attributed→resolved | resolved | `analysis/canonical/stage5/backbone/incident_states.md` |

## Processes (references backbone)

| Process | Trigger | Steps (summary) | Stakeholder | Canonical ref | Sidecar (if any) |
|---|---|---|---|---|---|
| Upstream schema change propagation | stg.* model shape changes | detect → notify downstream → update mart → verify | data_engineering_lead, analytics_engineering_lead | `analysis/canonical/stage5/backbone/schema_change_propagation.md` | none |
| Reference-data update (interim) | ref.* seed change proposed | (no owner gate today — routed via A51-003) | unassigned (pending decision) | `analysis/canonical/stage5/backbone/refdata_update_interim.md` | none |

## Assumptions & A51 Routes

| A51Ref | IssueType | Severity | BlockingStatus | Owner role | Next action |
|---|---|---|---|---|---|
| A51-001 | uncertainty | medium | informational | analytics_engineering_lead | Validate 30% figure against incident-tracker export (90-day window) |
| A51-002 | missing_source | medium | soft | bi_consumer_lead | Add a BI-team-side attestation or a BI-maintained consumer catalog |
| A51-003 | decision_needed | high | soft | data_governance_sponsor | Approve reference-data custodian assignment (AE + DE quarterly rotation per AJ:C-007) |

## Next Gate Preconditions

- [ ] A51-003 closed or explicitly waived by sponsor [A51-003]
- [ ] A51-002 closed with at least one non-AE attestation [A51-002]
- [ ] A51-001 closed with 90-day incident data or explicitly waived [A51-001]
- [ ] Stage 8 readiness_assessment = PASS at handoff emission time
- [ ] H1 sponsor sign-off recorded
