# Constraints and Dependencies Route — fixture-project-0003

| constraint_id | dependency_id | source_ref | escalation_target | linked_a51_refs |
|---|---|---|---|---|
| CONS-001 |  | C-001 + C-002 | finance_vp |  |
| CONS-002 | DEP-001 | C-003 + C-005 + C-006 | procurement_sponsor | A51-002 |
| CONS-003 | DEP-002 | C-004 | procurement_sponsor | A51-001 |
| CONS-004 | DEP-003 | C-006 | legal_general_counsel | A51-003 |
| CONS-005 |  | CONS-002 (derived) | procurement_sponsor | A51-002 |

Constraint legend:
- **CONS-001** — The dollar-bracket approval structure (under 10k line-manager / 10k-50k department-head / 50k-and-above finance-VP / over 500k board-escalation) is the canonical routing rule for vendor purchases, sourced from policy v4.2 [C-001] [C-002]. No ad-hoc bracket override is admissible.
- **CONS-002** — Any non-standard-clause contract MUST receive legal review per written policy [C-003]. Whether that review is a blocking gate (C-006) or an advisory input (C-005) is **contested** (A51-002). Until sponsor resolution, downstream Stage 3+ artifacts MUST NOT cite either interpretation as canonical.
- **CONS-003** — Purchases affecting operational capacity are structurally undefined in policy [C-004]. An ops-consult role MUST be added to the policy text before ops authority can be referenced as a routing rule (A51-001 resolution prerequisite).
- **CONS-004** — The 2023 GC-rollback precedent cited by the legal PM (E-007) is the sole attestation supporting C-006. Any policy change formalizing legal-as-gate MUST cite a corroborating record (A51-003) and not the undocumented incident alone.
- **CONS-005** — Derived: because CONS-002 is hard-blocked, any analyst_judgment row (e.g., C-007) that recommends a specific reconciliation MUST carry `A51Ref=A51-002` and remain **unresolved** in handoff until the sponsor decides. Re-promotion is required after sponsor sign-off.

Dependency legend:
- **DEP-001** — Sponsor decision on canonical legal-review interpretation (blocking vs advisory). Input to CONS-002. Owner: procurement_sponsor (STK-006). Target resolution window: before any Stage 3 citation audit cites C-005 / C-006 as settled.
- **DEP-002** — Ops-team attestation or ops-maintained artifact formalizing the ops-consult role on operational-impact purchases. Input to CONS-003. Owner: ops_lead (STK-005) once engaged; no owner currently assigned.
- **DEP-003** — Documentary confirmation of the 2023 GC-rollback incident (HR / legal-ops records, board minutes, or contract-cancellation record). Input to CONS-004. Owner: legal_general_counsel (STK-004).
