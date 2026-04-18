---
name: d0-hypothesis-prioritizer
description: Execute D3 opportunity/response modeling with prioritization and contradiction routing while keeping discovery pre-solution.
---

# D0 Hypothesis Prioritizer

Use this skill for D3 discovery prioritization.

## Scope
- Build opportunity map or response-option map (path-sensitive).
- Maintain hypothesis/response backlog with explicit statuses.
- Produce prioritization matrix with consistent scoring axes.

## Mandatory Reference Load
- Read [references/opportunity-response-modeling.md](references/opportunity-response-modeling.md) before producing D3 scoring outputs.

## Inputs
- `analysis/discovery/canonical/d2/research_design.md`
- `analysis/discovery/canonical/d2/path_artifact_contract.md`
- `analysis/discovery/canonical/d2/pain_gap_register.md`
- `analysis/discovery/canonical/d2/A58_evidence_excerpts.csv`
- `analysis/discovery/canonical/d2/A59_claim_register.csv`
- `analysis/canonical/core_controls/A51_issue_route_register.csv`

## Outputs
- `analysis/discovery/proposals/d3/opportunity_or_response_map.md`
- `analysis/discovery/proposals/d3/hypothesis_response_backlog.md`
- `analysis/discovery/proposals/d3/prioritization_matrix.md`
- `analysis/discovery/proposals/d3/prioritization_report.md` (`Status: PASS` required for gate)

## Invariants
- Discovery does not become implementation design.
- Contradictions and unresolved choices route via shared `A51Ref`.

## On Audit Failure
1. Read D3 prioritization findings.
2. Correct D3 scoring/rationale artifacts in proposal layer.
3. Route unresolved contradictions via `A51Ref`.
4. Re-submit D3 outputs and request re-validation.

## Validation Binding
- `SCN-DISC14-001-A` to `SCN-DISC14-001-C`.

## Reference
- [references/opportunity-response-modeling.md](references/opportunity-response-modeling.md)
