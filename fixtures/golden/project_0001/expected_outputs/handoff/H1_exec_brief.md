# H1 Executive Brief — Support Ticket Flow

## Executive Summary

Support-ticket intake and triage run on three channels with a four-outcome triage model [C-001] [C-004], but an estimated 15% of tickets are duplicates caught only after agent pickup [C-005], adding measurable drag to the engineering escalation path [C-006]. Recommend introducing near-duplicate detection at intake before extending any channel-specific SLA variants [AJ:C-008].

## Key Findings (≤5)

- Tickets arrive via three channels: support email, self-service portal, and billing-team escalation. [C-001]
- Severity is assigned within one hour; High/Critical page on-call, Low/Medium do not. [C-002] [C-003]
- Triage closes with one of four outcomes: resolved, escalated to engineering, marked duplicate, or routed to billing. [C-004]
- An estimated ~15% of tickets are duplicates detected only after agent pickup — inference pending validation against ticketing-system data. [C-005] [A51-001]
- SLA is 4 hours initial response on High/Critical and 1 business day on Low/Medium. [C-007]

## Recommended Next Steps

1. Approve introduction of intake-side near-duplicate detection before considering channel-specific SLA variants. [AJ:C-008] supported by [C-005] and the PM-preference reference in C-008's JustificationRationale
2. Confirm the ~15% duplicate-rate estimate against a ticketing-system report before sizing the detection effort. [A51-001]
3. Decide whether SLA windows need channel-specific variants after duplicate-detection change lands. [A51-002]

## Risks & Blockers

| Risk | Severity | Impacted scope | Trace |
|---|---|---|---|
| Duplicate-rate figure unvalidated against system data | medium | intake sizing, effort estimate | [C-005] [A51-001] |
| Channel-specific SLA decision unresolved | medium | SLA policy, customer commitments | [A51-002] |
| Engineering escalation slowed by missing repro steps | low | engineering throughput | [C-006] |

## Confidence Assessment

Overall: medium. Core flow claims (channels, triage, SLAs) are direct quotes; the duplicate-rate figure is a PM estimate and the primary recommendation rests on analyst judgment routed through A51.

| KPI | Target | Actual | Verdict |
|---|---|---|---|
| KPI-001 | ≥ 0.75 | 0.82 | PASS |
| KPI-002 | 0 | 0 | PASS |
| KPI-003 | 0 critical | 0 | PASS |
| KPI-004 | 0 | 0 | PASS |
| KPI-005 | 0 leakage | 0 | PASS |
