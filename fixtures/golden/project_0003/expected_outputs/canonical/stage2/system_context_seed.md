# System-Context Seed — fixture-project-0003

## System Boundary

The procurement approval workflow encompasses approval decisions for vendor purchases above the line-manager threshold. In-boundary: dollar-bracket routing, finance authority rules, legal review on non-standard clauses, ops-consult role (currently absent from policy). Out-of-boundary: vendor negotiation, procure-to-pay mechanics after approval, post-decision audit trail [C-001] [C-002] [C-004].

## Neighboring Systems

- **Vendor management / procurement platform** (orthogonal): the system of record for purchase requests; approvals are emitted back to it.
- **Contract-management system** (downstream of legal review): executes signed contracts after approval; carries the non-standard-clause flags cited in C-003.
- **Accounts-payable / ERP** (downstream of approval): processes payment after approval; out of scope.
- **Board governance** (upstream for > 500k purchases per C-001): required escalation for the top bracket only.

## Interface Obligations

- Finance VP MUST sign off on any purchase ≥ 50k per policy [C-002].
- Legal MUST review any non-standard-clause contract; gating-vs-advisory status CONTESTED [C-003] [A51-002].
- Ops-consult on operational-impact purchases is structurally undefined [C-004] [A51-001].
- Board escalation MUST happen on > 500k per policy bracket [C-001].

## Context Triggers

A canonical approval-workflow promotion cycle is triggered when:
- A new vendor purchase exceeds the line-manager threshold (dollar bracket routing).
- A contract carries a non-standard indemnity/liability/IP clause (legal-review required; A51-002 resolution determines whether review is gating or advisory).
- A purchase impacts operational capacity (ops-consult role to be defined after A51-001 resolution).
- A50-level rollback incident occurs (currently undocumented per A51-003; triggers policy-text review if confirmed).
