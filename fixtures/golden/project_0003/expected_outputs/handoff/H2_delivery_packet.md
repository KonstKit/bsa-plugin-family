# H2 Delivery Packet — Procurement Approval Workflow Audit

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
| FR-001 | Vendor purchases route through the dollar-bracket approval tree | must | finance_vp | [C-001] [C-002] |
| FR-002 | Non-standard-clause contracts receive legal review before execution | must | legal_pm | [C-003] |
| FR-003 | Operational-impact purchases carry an explicit ops-consult step | should | procurement_sponsor | [AJ:C-007] [C-004] |

Non-Functional Requirements:

| NFR-ID | Category | Target | Measurement | ClaimID refs |
|---|---|---|---|---|
| NFR-001 | governance | Legal review has a written, non-ambiguous gating status | policy-text audit | [C-003] [C-005] [C-006] [A51-002] |
| NFR-002 | auditability | Approval decisions carry a resolved A51-002 verdict before execution | A51 resolution audit trail | [A51-002] |

## Contracts & Interfaces (references A61)

| AnchorID | Contract name | Consumer | Producer | Contract kind | Reference |
|---|---|---|---|---|---|
| ANC-AUTH-001 | Dollar-bracket approval authority | procurement platform | finance org | policy | `analysis/canonical/stage6/contracts/dollar_bracket_auth.md` |
| ANC-AUTH-002 | Non-standard-clause legal review (gating status CONTESTED) | contract management system | legal org | policy | `analysis/canonical/stage6/contracts/legal_review_clause.md` |
| ANC-AUTH-003 | Operational-impact ops-consult (pending) | procurement platform | unassigned (pending A51-001) | policy | deferred pending A51-001 |

## Data & State (references entity/status catalogs)

Entities:

| Entity | Owner | Lifecycle | Canonical ref |
|---|---|---|---|
| vendor purchase request | procurement platform | request -> review -> approve/reject | `analysis/canonical/stage4/domain_model/purchase_request.md` |
| non-standard-clause contract | contract management system | draft -> legal review -> signed | `analysis/canonical/stage4/domain_model/non_standard_contract.md` |
| operational-impact purchase | unassigned (pending A51-001) | request -> ??? -> approve/reject | `analysis/canonical/stage4/domain_model/ops_impact_purchase.md` |

State machines:

| Entity | States | Transitions | Terminal states | Canonical ref |
|---|---|---|---|---|
| vendor purchase request | submitted, under_review, approved, rejected | submitted -> under_review -> (approved OR rejected) | approved, rejected | `analysis/canonical/stage5/backbone/purchase_request_states.md` |
| non-standard-clause contract | draft, legal_flagged, legal_cleared, signed, blocked | draft -> legal_flagged -> (legal_cleared -> signed) OR (blocked <- legal_flagged) | signed, blocked | `analysis/canonical/stage5/backbone/non_standard_contract_states.md` |

## Processes (references backbone)

| Process | Trigger | Steps (summary) | Stakeholder | Canonical ref | Sidecar (if any) |
|---|---|---|---|---|---|
| Dollar-bracket approval routing | new vendor purchase request | classify bracket -> route to finance approver -> emit decision | finance_vp, procurement_sponsor | `analysis/canonical/stage5/backbone/dollar_bracket_routing.md` | none |
| Non-standard-clause legal review (CONTESTED flow) | contract flagged non-standard | legal PM review -> (per A51-002 resolution: gate or advise) -> back to finance | finance_pm, legal_pm | `analysis/canonical/stage5/backbone/non_standard_legal_review.md` | none |
| Ops-consult on operational-impact (interim) | operational-impact purchase proposed | (no owner gate today — routed via A51-001) | unassigned (pending decision) | `analysis/canonical/stage5/backbone/ops_consult_interim.md` | none |

## Assumptions & A51 Routes

| A51Ref | IssueType | Severity | BlockingStatus | Owner role | Next action |
|---|---|---|---|---|---|
| A51-001 | missing_source | medium | soft | ops_lead (once engaged) | Add ops-team attestation or artifact formalizing ops-consult role (per A51.NextAction) |
| A51-002 | contradiction | high | hard | procurement_sponsor | Sponsor decision on canonical legal-review interpretation + policy-text update to S-001 + re-promote A59 unmarking contested claim |
| A51-003 | uncertainty | low | informational | legal_general_counsel | Confirm 2023 GC-rollback incident via HR / legal-ops records before formalizing C-007 judgment |

## Next Gate Preconditions

- [ ] A51-002 closed by sponsor with a canonical legal-review interpretation [A51-002]
- [ ] A51-001 closed with an ops-team attestation or explicit waiver [A51-001]
- [ ] A51-003 closed with documentary confirmation of the 2023 incident OR the C-007 recommendation is accepted without citing the incident [A51-003]
- [ ] Stage 8 readiness_assessment = PASS at handoff emission time
- [ ] H1 sponsor sign-off recorded
