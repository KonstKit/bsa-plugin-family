# Context-State Frame — fixture-project-0003

## Problem Or Objective

Document the procurement approval workflow and surface cross-team ownership contestation between finance, legal, and ops [C-001] [C-002] [C-003] [C-004].

## Scope Boundary

### In

- Dollar-bracket approval thresholds (under 10k / 10k-50k / 50k and above) [C-001].
- Finance authority over 50k-and-above purchases [C-002].
- Legal review on non-standard-clause contracts (gating-vs-advisory status contested between T4 sources) [C-003] [C-005] [C-006] [A51-002].
- Ops-consult role on operational-impact purchases (policy-acknowledged gap) [C-004] [A51-001].

### Out

- Specific vendor negotiation tactics (outside the approval-workflow scope).
- Accounts-payable mechanics after approval.
- Audit/reporting downstream of the approval decision.

## Context Mode

`discovery_then_bsa`. Discovery was mandatory because scope was fuzzy ("document procurement approvals"), stakeholder accounts directly contradict each other on legal's authority, and the policy text itself explicitly acknowledges ambiguity on the legal-review gating status [C-003].

## Stakeholders

Authority detail in `stakeholder_authority_map.md`. Three functions with partially overlapping authority: finance (policy-granted dollar-bracket authority, C-002), legal (contested gating authority on non-standard clauses, C-005/C-006), ops (structurally absent from policy, C-004/A51-001).

## Constraints

Constraints + dependencies in `constraints_dependencies_route.md`. Key constraint: A51-002 is `BlockingStatus=hard` — no downstream Stage 3+ promotion that depends on a concrete legal-review interpretation can complete until the contradiction is resolved.

## Dependencies

- Sponsor decision on canonical legal-review interpretation (A51-002 closure).
- Policy-text update to S-001 once the sponsor decides (dependency on governance process).
- Ops-team attestation or artifact to close A51-001.
- Documentary confirmation of the 2023 GC-rollback incident for A51-003.

## Open Uncertainties

- [A51-001] ops-consult role undefined — missing ops-side attestation.
- [A51-002] **HARD BLOCKER** — two T4 sources contradict on legal's gating authority; contested per tier-delta ≤ 1 rule.
- [A51-003] 2023 GC-rollback incident undocumented; cited by legal PM but no corroborating record.
