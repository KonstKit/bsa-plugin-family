# H2 Delivery Packet — Support Ticket Flow

## Delivery Manifest (what's included)

| Artifact | Role | Canonical path | Version |
|---|---|---|---|
| A48 run context card | run metadata | `analysis/canonical/core_controls/A48_run_context_card.md` | 0.95.0 |
| A50 source register | source ledger | `analysis/canonical/core_controls/A50_source_register.csv` | 0.95.0 |
| A51 issue route register | unresolved items | `analysis/canonical/core_controls/A51_issue_route_register.csv` | 0.95.0 |
| A58 evidence excerpts | evidence layer | `analysis/canonical/core_controls/A58_evidence_excerpts.csv` | 0.95.0 |
| A59 claim register | claim layer | `analysis/canonical/core_controls/A59_claim_register.csv` | 0.95.0 |
| A60 negative evidence | counter-evidence | `analysis/canonical/core_controls/A60_negative_evidence_register.csv` | 0.95.0 |
| Stage 2 context state | context frame | `analysis/canonical/stage2/context_state_frame.md` | 0.95.0 |

## Requirements Summary (references fr_register/nfr_register)

Functional Requirements:

| FR-ID | Title | Priority | Owner role | ClaimID refs |
|---|---|---|---|---|
| FR-001 | Three-channel ticket intake (email, portal, billing escalation) | must | support_ops_lead | [C-001] |
| FR-002 | Severity assignment within 1 hour of arrival | must | support_ops_lead | [C-002] |
| FR-003 | Pager routing on High/Critical severity | must | on_call_rotation_lead | [C-003] |
| FR-004 | Four-outcome triage close (resolve, escalate, duplicate, billing) | must | support_ops_lead | [C-004] |
| FR-005 | Near-duplicate detection at intake | should | support_ops_lead | [AJ:C-008] |

Non-Functional Requirements:

| NFR-ID | Category | Target | Measurement | ClaimID refs |
|---|---|---|---|---|
| NFR-001 | performance | 4h first response High/Critical | ticketing-system SLA clock | [C-007] |
| NFR-002 | performance | 1 business day first response Low/Medium | ticketing-system SLA clock | [C-007] |
| NFR-003 | observability | Duplicate-rate telemetry available for audit | ticketing-system export | [C-005] [A51-001] |

## Contracts & Interfaces (references A61)

| AnchorID | Contract name | Consumer | Producer | Contract kind | Reference |
|---|---|---|---|---|---|
| ANC-INT-001 | Support email ingestion | ticketing-system | email-gateway | integration | `analysis/canonical/stage6/contracts/email_ingestion.md` |
| ANC-INT-002 | Self-service portal submission | ticketing-system | portal-frontend | api | `analysis/canonical/stage6/contracts/portal_submission.md` |
| ANC-INT-003 | Billing-team escalation handoff | ticketing-system | billing-system | integration | `analysis/canonical/stage6/contracts/billing_escalation.md` |

## Data & State (references entity/status catalogs)

Entities:

| Entity | Owner | Lifecycle | Canonical ref |
|---|---|---|---|
| Ticket | support_ops_lead | intake → triaged → closed | `analysis/canonical/stage4/domain_model/ticket.md` |
| Severity | support_ops_lead | assigned-at-triage | `analysis/canonical/stage4/domain_model/severity.md` |

State machines:

| Entity | States | Transitions | Terminal states | Canonical ref |
|---|---|---|---|---|
| Ticket | new, triaged, resolved, escalated, duplicate, billing-routed | new→triaged, triaged→{resolved, escalated, duplicate, billing-routed} | resolved, escalated, duplicate, billing-routed | `analysis/canonical/stage4/domain_model/ticket_states.md` |

## Processes (references backbone)

| Process | Trigger | Steps (summary) | Stakeholder | Canonical ref | Sidecar (if any) |
|---|---|---|---|---|---|
| Ticket intake | channel arrival | receive → log → route to triage | support_ops | `analysis/canonical/stage5/backbone/ticket_intake.md` | bpmn |
| Triage | new ticket logged | assign severity → select outcome | support_ops | `analysis/canonical/stage5/backbone/triage.md` | bpmn |
| Escalation to engineering | triage → escalate outcome | package repro → send to eng → await response | support_ops, engineering | `analysis/canonical/stage5/backbone/escalation.md` | none |

## Assumptions & A51 Routes

| A51Ref | IssueType | Severity | BlockingStatus | Owner role | Next action |
|---|---|---|---|---|---|
| A51-001 | uncertainty | low | informational | support_ops_lead | Confirm the ~15% duplicate-rate estimate against a ticketing-system report |
| A51-002 | decision_needed | medium | soft | product_owner | Validate whether SLA windows need channel-specific variants |

## Next Gate Preconditions

- [ ] A51-001 closed or explicitly waived by sponsor [A51-001]
- [ ] A51-002 decided (approve/reject channel-specific SLA variants) [A51-002]
- [ ] Stage 8 readiness_assessment = PASS at handoff emission time
- [ ] H1 sponsor sign-off recorded
