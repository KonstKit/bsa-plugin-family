# H4 Open Items Packet — Analytics Platform Ownership Audit

## Open Items Digest (A51 filtered)

| A51Ref | IssueType | Severity | BlockingStatus | RaisedByStage | Age (days) | Summary | Related ClaimID |
|---|---|---|---|---|---|---|---|
| A51-003 | decision_needed | high | soft | stage1 | 3 | Assign reference-data (`ref.*`) custodian; sponsor sign-off required on proposed AE+DE rotation | C-006 |
| A51-002 | missing_source | medium | soft | stage1 | 3 | Add BI-team attestation or consumer catalog; single-source AE attestation insufficient | C-004 |
| A51-001 | uncertainty | medium | informational | stage1 | 3 | Validate 30%-lineage-drift figure against 90-day incident-tracker export | C-005 |

## Decisions Required (by severity)

**High**

1. Approve establishing an explicit reference-data custodian role — proposed: analytics engineering with quarterly rotation to data engineering. [AJ:C-007] supported by [C-006] (custodian-gap pain point) and [C-003] (structural absence in dbt config) [A51-003]
   - Rationale (reproduced from C-007 JustificationRationale): recommendation is derived from the custodian-gap pain point [C-006] and the absence of an owner-tag convention in the existing dbt config for seeds [C-003]; requires stakeholder validation on proposed rotation cadence [A51-003].

**Medium**

2. Decide whether to promote C-004 (BI does not own marts) to non-contested status after a BI-side attestation lands, or to hold BI consumer relationship as an intentional open question. [A51-002]
   - Rationale (reproduced from A51-002 NextAction): add a BI-team stakeholder attestation or a BI-team-maintained artifact listing the models BI consumes.

**Informational**

3. Accept residual uncertainty on the 30% lineage-drift figure until incident-tracker telemetry confirms. [A51-001]
   - Rationale (reproduced from A51-001 NextAction): validate the 30%-of-dashboard-incidents estimate against an incident-tracker export of at least 90 days.

## Suggested Owners

| A51Ref | Suggested owner role | Rationale | Backup role |
|---|---|---|---|
| A51-001 | analytics_engineering_lead | A51.NextAction targets the incident tracker they use to close mart-incidents | data_engineering_lead |
| A51-002 | bi_consumer_lead | A51.NextAction requires a BI-side artifact; BI lead is the only stakeholder who can author it | analytics_engineering_lead (as interim co-signer) |
| A51-003 | data_governance_sponsor | A51.NextAction requires sponsor sign-off on custodian assignment | analytics_engineering_lead (as proposer per AJ:C-007) |

## Target Resolution Windows

| A51Ref | Severity | Target resolution date | SLA source | Escalation trigger date |
|---|---|---|---|---|
| A51-003 | high | 2026-05-04 | orchestrator default | 2026-05-06 |
| A51-002 | medium | 2026-05-04 | orchestrator default | 2026-05-06 |
| A51-001 | medium | 2026-05-18 | orchestrator default | 2026-05-20 |

## Escalation Routes

| A51Ref | Owner role | Level-1 escalation | Level-2 escalation | Final escalation |
|---|---|---|---|---|
| A51-001 | analytics_engineering_lead | analytics_engineering_manager |  |  |
| A51-002 | bi_consumer_lead | bi_manager | data_governance_sponsor | steering_committee |
| A51-003 | data_governance_sponsor | steering_committee | sponsor | sponsor |
