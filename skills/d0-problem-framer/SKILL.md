---
name: d0-problem-framer
description: Initialize D1 discovery under shared A48/A50/A51 governance, produce problem framing artifacts, and enforce de-solutionization before D2.
---

# D0 Problem Framer

Use this skill for D1 of the optional discovery branch.

## Scope
- Initialize discovery entry under shared governance with main-cycle instruments `A48/A50/A51`.
- Produce `Problem Statement Card`, `Stakeholder Map`, and `Discovery Scope Card`.
- Route early constraints and uncertainties into shared `A51` (by reference), not parallel ledgers.
- Emit D1-ready outputs for orchestrator promotion.

## Inputs
- User request and source brief for discovery kickoff.
- Shared controls `analysis/canonical/core_controls/A48_run_context_card.md`, `A50_source_register.csv`, `A51_issue_route_register.csv` when present.

## Outputs
- `analysis/discovery/proposals/d1/problem_statement_card.md`
- `analysis/discovery/proposals/d1/stakeholder_map.md`
- `analysis/discovery/proposals/d1/discovery_scope_card.md`

## Invariants
- Discovery cannot create a second governance plane.
- D1 output cannot hard-code implementation design.
- Open items and constraints are routed to shared `A51Ref`.

## On Audit Failure
1. Keep D1 outputs proposal-layer only.
2. Add missing governance routes to shared `A51`.
3. Revise framing artifacts with explicit non-solution language.
4. Re-submit D1 package for readiness promotion.

## Validation Binding
- `SCN-DISC12-001-A` through `SCN-DISC12-001-E`.

## References
- [references/problem-framing.md](references/problem-framing.md)
- [references/discovery-governance.md](references/discovery-governance.md)
