# H1 Executive Brief — Analytics Platform Ownership Audit

## Executive Summary

The dbt project config formally assigns ownership only for the staging and marts layers [C-001] [C-002], leaving reference-data custodianship and BI-consumer ownership structurally undefined [C-003] [C-004] [C-006]. Recommend establishing an explicit reference-data custodian before expanding the seed set further [AJ:C-007] supported by [C-003] and [C-006].

## Key Findings (≤5)

- Staging models (`stg.*`) are owned by the data-engineering team via explicit `data_eng_owned` tags in dbt. [C-001]
- Marts models (`mart.*`) are owned by the analytics-engineering team via explicit `ae_owned` tags in dbt. [C-002]
- Reference-data (`ref.*`) seeds carry no owner tag in the dbt config; multiple teams update without attribution. [C-003] [C-006]
- BI consumers use marts but are not assigned ownership — single-source attestation pending triangulation. [C-004] [A51-002]
- Approximately 30% of dashboard incidents trace to upstream changes the downstream team did not hear about; figure is an attested rough estimate pending validation. [C-005] [A51-001]

## Recommended Next Steps

1. Approve establishing an explicit reference-data custodian role (proposed: analytics engineering with quarterly rotation to data engineering). [AJ:C-007] supported by [C-003] [C-006] [A51-003]
2. Confirm the 30%-lineage-drift figure against a 90-day incident-tracker export before committing any SLA target. [A51-001]
3. Solicit a BI-team-side attestation or consumer catalog to triangulate BI ownership status. [A51-002]

## Risks & Blockers

| Risk | Severity | Impacted scope | Trace |
|---|---|---|---|
| Reference-data updates go unattributed | medium | ref schema + downstream marts | [C-006] [A51-003] |
| Lineage-drift incident rate unvalidated | medium | SLA commitments, detection latency targets | [C-005] [A51-001] |
| BI-consumer ownership status single-source | medium | consumer-interface handoffs | [C-004] [A51-002] |

## Confidence Assessment

Overall: medium. Ownership claims for `stg.*` and `mart.*` are direct quotes from T2 production config. Three residual uncertainties are routed through `A51` with explicit next-action plans; no hard blockers.

| KPI | Target | Actual | Verdict |
|---|---|---|---|
| KPI-001 | ≥ 0.75 | 0.85 | PASS |
| KPI-002 | 0 | 0 | PASS |
| KPI-003 | 0 critical | 0 | PASS |
| KPI-004 | 0 | 0 | PASS |
| KPI-005 | 0 leakage | 0 | PASS |
