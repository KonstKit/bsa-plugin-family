---
name: d0-feasibility-assessor
description: Execute D4 feasibility assessment with D4-lite/D4-deep triggers, constraint audit, and optional derived sidecar triggers.
---

# D0 Feasibility Assessor

Use this skill for D4 feasibility and constraints.

## Scope
- Apply `D4-lite` vs `D4-deep` trigger rules.
- Produce feasibility and constraints package.
- Keep optional BPMN/C4 as derived aids only.

## Mandatory Reference Load
- Read [references/constraints-and-feasibility.md](references/constraints-and-feasibility.md) before scoring D4 depth and feasibility status.

## Inputs
- `analysis/discovery/canonical/d3/opportunity_or_response_map.md`
- `analysis/discovery/canonical/d3/hypothesis_response_backlog.md`
- `analysis/discovery/canonical/d3/prioritization_matrix.md`
- Shared governance controls `analysis/canonical/core_controls/A48_run_context_card.md` and `A51_issue_route_register.csv`

## Outputs
- `analysis/discovery/proposals/d4/feasibility_assessment.md`
- `analysis/discovery/proposals/d4/constraint_audit_report.md` (`Status: PASS` required for gate)
- Optional sidecar trigger context under `analysis/discovery/proposals/d4/`

## Invariants
- No detailed FR/NFR or implementation structure in discovery.
- Constraints and decisions are routed to shared `A51Ref`.

## On Audit Failure
1. Read D4 constraint findings.
2. Revise D4 feasibility outputs only.
3. Route unresolved blockers via `A51Ref`.
4. Re-emit D4 proposal package and request re-audit.

## Validation Binding
- `SCN-DISC14-001-D` and `SCN-DISC14-001-E`.

## Reference
- [references/constraints-and-feasibility.md](references/constraints-and-feasibility.md)
