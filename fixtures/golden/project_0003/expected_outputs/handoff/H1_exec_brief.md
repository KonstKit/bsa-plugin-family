# H1 Executive Brief — Procurement Approval Workflow Audit

## Executive Summary

The written procurement policy v4.2 defines a three-tier dollar-bracket approval structure with the finance VP holding sole authority on any purchase at or above 50k [C-001] [C-002], and mandates legal review on non-standard-clause contracts without specifying whether review is a blocking gate or an advisory function [C-003]. Two T4 attestations directly contradict each other at tier-delta 0 on exactly this ambiguity: the finance PM describes legal as advisory [C-005] while the legal PM describes legal as a blocking gate citing a 2023 rollback precedent [C-006] [A51-002]. An ops-consult role on operational-impact purchases is structurally undefined in policy [C-004] [A51-001]. Recommend codifying legal review as a blocking gate and adding an explicit ops-consult role in the next policy revision [AJ:C-007] supported by [C-002] [C-003] [C-004] [C-005] [C-006].

## Key Findings (≤5)

- Dollar-bracket approval thresholds are directly quoted from T2 policy (under 10k line manager / 10k-50k department head / 50k-and-above finance VP / board escalation above 500k). [C-001]
- Finance has sole authority on purchases at or above 50k per written policy; no other function may authorize without finance sign-off. [C-002]
- Policy mandates legal review on non-standard-clause contracts but explicitly declines to state whether review is a blocking gate — this ambiguity is flagged in the policy text itself. [C-003]
- Two same-tier (T4) attestations from finance PM and legal PM directly contradict each other on legal's gating authority; routed via A51-002 under tier-delta ≤ 1 contested rule. [C-005] [C-006] [A51-002]
- Ops-consult role on operational-impact purchases is a documented policy gap; no stakeholder attestation authored at pilot time. [C-004] [A51-001]

## Recommended Next Steps

1. Sponsor decision on canonical legal-review interpretation (blocking gate vs advisory). [AJ:C-007] supported by [C-003] [C-005] [C-006] [A51-002]
2. Add an ops-team attestation or ops-maintained artifact formalizing the ops-consult role on operational-impact purchases. [C-004] [A51-001]
3. Confirm the 2023 GC-rollback incident cited by legal PM via HR / legal-ops records before relying on it as policy precedent. [C-006] [A51-003]

## Risks & Blockers

| Risk | Severity | Impacted scope | Trace |
|---|---|---|---|
| Legal gating authority contested between two T4 sources at tier-delta 0 | high (hard blocker) | non-standard-clause contract approvals | [C-005] [C-006] [A51-002] |
| Ops-consult role structurally undefined in policy | medium | operational-impact purchases | [C-004] [A51-001] |
| 2023 GC-rollback incident unconfirmed by documentary evidence | low | policy precedent for legal-as-gate interpretation | [C-006] [A51-003] |

## Confidence Assessment

Overall: medium. Dollar-bracket and finance-authority claims are direct T2 policy quotes (high confidence). Legal-review and ops-consult claims are contested or structurally missing; all three residual uncertainties are routed via `A51` with explicit next-action plans. One hard blocker (A51-002) requires sponsor closure before any downstream artifact cites either side's interpretation as canonical.

| KPI | Target | Actual | Verdict |
|---|---|---|---|
| KPI-001 | ≥ 0.75 | 0.85 | PASS |
| KPI-002 | 0 | 0 | PASS |
| KPI-003 | 0 critical | 0 | PASS |
| KPI-004 | 0 | 0 | PASS |
| KPI-005 | 0 leakage | 0 | PASS |
