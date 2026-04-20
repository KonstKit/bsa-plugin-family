# H4 Open Items Packet — Procurement Approval Workflow Audit

## Open Items Digest (A51 filtered)

| A51Ref | IssueType | Severity | BlockingStatus | RaisedByStage | Age (days) | Summary | Related ClaimID |
|---|---|---|---|---|---|---|---|
| A51-002 | contradiction | high | hard | stage1 | 1 | CONTESTED: two T4 sources (finance PM S-002 vs legal PM S-003) make incompatible claims about whether legal review is advisory or a blocking gate | C-005;C-006 |
| A51-001 | missing_source | medium | soft | stage1 | 1 | Ops-consult role on operational-impact purchases is undefined in policy; ops-side attestation missing | C-004 |
| A51-003 | uncertainty | low | informational | stage1 | 1 | 2023 GC-rollback incident cited as informal precedent is undocumented; requires HR / legal-ops confirmation | C-006 |

## Decisions Required (by severity)

**High (hard blocker)**

1. Decide canonical legal-review interpretation on non-standard-clause contracts: **blocking gate** (per C-006 current practice) or **advisory** (per C-005 policy reading). [AJ:C-007] supported by [C-003] (policy-acknowledged ambiguity), [C-005] (finance PM attestation), [C-006] (legal PM attestation + 2023 precedent) [A51-002]
   - Rationale (reproduced from C-007 JustificationRationale): Analyst-judgment derived from the structural contradiction between C-005 and C-006 plus the policy-acknowledged ambiguity in C-003 and the ops-gap in C-004. Recommendation picks the legal-as-gate interpretation (C-006) on the grounds that it reflects current practice; requires sponsor sign-off to rewrite the policy text. A51-002 must be closed via sponsor decision before any downstream promotion cites this judgment as resolved.

**Medium**

2. Decide whether to add an ops-consult role to the procurement policy for operational-impact purchases, or to formally acknowledge that ops has no consulting authority. [C-004] [A51-001]
   - Rationale (reproduced from A51-001 NextAction): Add an ops-team attestation or ops-maintained artifact describing the ops-consult role on operational-impact purchases. Policy gap (C-004) leaves the ops role structurally undefined.

**Informational**

3. Accept residual uncertainty on the 2023 GC-rollback incident until HR / legal-ops records confirm the event. [A51-003]
   - Rationale (reproduced from A51-003 NextAction): The 2023 GC-rollback incident cited by the legal PM (E-007) as informal precedent is undocumented. Before the analyst_judgment (C-007) can be formalized into policy, confirm the 2023 incident via HR / legal-ops records.

## Suggested Owners

| A51Ref | Suggested owner role | Rationale | Backup role |
|---|---|---|---|
| A51-001 | ops_lead | A51.NextAction requires ops-side attestation; ops lead is the only stakeholder who can author it | procurement_sponsor (as interim co-signer) |
| A51-002 | procurement_sponsor | A51.NextAction requires sponsor sign-off on which legal-review interpretation is canonical + policy-text update | finance_vp (co-signer on authority rules) + legal_general_counsel (co-signer on legal-side interpretation) |
| A51-003 | legal_general_counsel | A51.NextAction requires documentary confirmation of a 2023 incident within legal-ops recordkeeping | legal_pm (as proposer of the precedent) |

## Target Resolution Windows

| A51Ref | Severity | Target resolution date | SLA source | Escalation trigger date |
|---|---|---|---|---|
| A51-002 | high | 2026-05-04 | orchestrator default (hard blockers: 14 days) | 2026-05-06 |
| A51-001 | medium | 2026-05-04 | orchestrator default (soft: 14 days) | 2026-05-06 |
| A51-003 | low | 2026-05-18 | orchestrator default (informational: 28 days) | 2026-05-20 |

## Escalation Routes

| A51Ref | Owner role | Level-1 escalation | Level-2 escalation | Final escalation |
|---|---|---|---|---|
| A51-001 | ops_lead | ops_manager | procurement_sponsor | steering_committee |
| A51-002 | procurement_sponsor | steering_committee | sponsor | sponsor |
| A51-003 | legal_general_counsel | legal_manager |  |  |
