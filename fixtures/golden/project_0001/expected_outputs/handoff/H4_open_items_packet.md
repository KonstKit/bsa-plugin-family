# H4 Open Items Packet — Support Ticket Flow

## Open Items Digest (A51 filtered)

| A51Ref | IssueType | Severity | BlockingStatus | RaisedByStage | Age (days) | Summary | Related ClaimID |
|---|---|---|---|---|---|---|---|
| A51-002 | decision_needed | medium | soft | stage3 | 3 | Validate whether SLA windows need channel-specific variants | C-008 |
| A51-001 | uncertainty | low | informational | stage1 | 5 | Confirm the ~15% duplicate-rate estimate against a ticketing-system report | C-005 |

## Decisions Required (by severity)

**Medium**

1. Approve introduction of intake-side near-duplicate detection before evaluating channel-specific SLA variants. [AJ:C-008] supported by [C-005] and the PM-preference reference inside C-008's JustificationRationale [A51-002]
   - Rationale (reproduced from C-008 JustificationRationale): recommendation is derived from the duplicate-rate pain point [C-005] and the PM's explicit preference to keep the four-outcome model while adding duplicate detection; requires stakeholder validation on channel-specific SLA variants [A51-002].

**Low**

2. Accept residual uncertainty on the 15% duplicate-rate figure until ticketing-system telemetry confirms. [A51-001]
   - Rationale (reproduced from A51-001 NextAction): confirm the "fifteen percent" duplicate-rate estimate against a ticketing-system report before sizing downstream work.

## Suggested Owners

| A51Ref | Suggested owner role | Rationale | Backup role |
|---|---|---|---|
| A51-001 | support_ops_lead | A51.NextAction targets ticketing-system report review | product_analytics_lead |
| A51-002 | product_owner | A51.NextAction targets SLA policy validation | support_ops_lead |

## Target Resolution Windows

| A51Ref | Severity | Target resolution date | SLA source | Escalation trigger date |
|---|---|---|---|---|
| A51-002 | medium | 2026-05-03 | orchestrator default | 2026-05-05 |
| A51-001 | low | 2026-05-17 | orchestrator default | 2026-05-19 |

## Escalation Routes

| A51Ref | Owner role | Level-1 escalation | Level-2 escalation | Final escalation |
|---|---|---|---|---|
| A51-001 | support_ops_lead | support_ops_manager |  |  |
| A51-002 | product_owner | product_director | steering_committee | sponsor |
