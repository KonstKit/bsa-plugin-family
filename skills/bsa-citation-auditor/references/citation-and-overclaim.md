# Citation and Overclaim Contract

## Output
- `analysis/proposals/stage7_8/stage7/citation_audit_report.md`
- `analysis/proposals/stage7_8/stage7/citation_audit_report.json`

## Required Sections
- total statements audited
- statements with `ClaimID`
- statements with `A51Ref`
- unsupported critical claims count
- unsupported non-critical claims count
- audit verdict (`pass`/`fail`)

## Marker Link
- `stage7.citation_audit.pass.json` requires `critical unsupported claims = 0`
- `discovery.d5.citation_audit.pass.json` requires the same rule for D5 reuse

## KPI Binding
- `KPI-003`: `critical unsupported claims = 0`
