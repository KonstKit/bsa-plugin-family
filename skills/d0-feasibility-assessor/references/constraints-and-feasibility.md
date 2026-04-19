# D4 Constraints and Feasibility

## Required Outputs
- `feasibility_assessment.md`
- `constraint_audit_report.md` with `Status: PASS`
- optional context seed for derived sidecars

## D4-lite vs D4-deep Triggers
Use `D4-deep` when any of the following are true:
- regulated or compliance-sensitive domain
- irreversible cost or migration risk
- cross-team/external dependency count > 1
- unresolved hard constraint in `A51`
- security, privacy, or data-boundary implications

Otherwise use `D4-lite`.

## Sidecar Rule
- BPMN/C4 may be triggered only as derived discovery aids.
- Generated views cannot become canonical discovery claims.
