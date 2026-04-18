---
name: d0-synthesis-gatekeeper
description: Execute D5 synthesis, D-Exit decision, and Stage1 handoff with profile-governed citation, skeptical, no-new-facts, and no-solution-leakage controls.
---

# D0 Synthesis Gatekeeper

Use this skill for D5 and discovery exit.

## Scope
- Produce `Discovery Report` and `Discovery Brief`.
- Produce `stage1_seed_bundle.md` for D0 -> BSA bridge.
- Run mandatory D5 audits and set D-Exit decision.
- Ensure seed outputs contain only discovery-claim-linked facts or explicit `A51Ref`.

## Inputs
- `analysis/discovery/canonical/d4/feasibility_assessment.md`
- `analysis/discovery/canonical/d4/constraint_audit_report.md`
- `analysis/discovery/canonical/d2/A58_evidence_excerpts.csv`
- `analysis/discovery/canonical/d2/A59_claim_register.csv`
- `analysis/discovery/canonical/d2/A60_negative_evidence_register.csv`
- Shared `analysis/canonical/core_controls/A51_issue_route_register.csv`

## Outputs
- `analysis/discovery/proposals/d5/discovery_report.md`
- `analysis/discovery/proposals/d5/discovery_brief.md`
- `analysis/discovery/proposals/d5/d_exit_decision.md`
- `analysis/discovery/proposals/d5/stage1_seed_bundle.md`
- `analysis/discovery/proposals/d5/stage2_seed_bundle.md`
- `analysis/discovery/proposals/d5/discovery_citation_audit_report.md`
- `analysis/discovery/proposals/d5/no_solution_leakage_report.md`

## Mandatory Preconditions
Before `discovery.go`:
- `discovery.d5.citation_audit.pass.json`
- `discovery.d5.no_solution_leakage.pass.json`
- `discovery.exit.pass.json`

## Optional Extended Preconditions
- `discovery.d5.skeptical_review.pass.json` when skeptical profile is enabled.
- `discovery.d5.no_new_facts.pass.json` when no-new-facts profile is enabled.
- Profile gate sets are defined by orchestrator run-profile contract (`bsa-orchestrator/references/run-profile-gates.md`).

## Audit Reuse Rule
- Reuse existing citation/skeptical/no-new-facts principles for discovery outputs.
- Discovery audit outputs remain non-canonical and cannot bypass governance.

## On Audit Failure
1. Keep D-Exit at non-go (`pivot|more_research|no_go`).
2. Record blocker and route in shared `A51`.
3. Regenerate only D5 proposal artifacts after upstream correction.
4. Re-run D5 audit set and decision.

## Validation Binding
- `SCN-DISC15-001-*` and aggregate `SCN-DISC-001`.

## References
- [references/synthesis-and-d-exit.md](references/synthesis-and-d-exit.md)
- [references/discovery-to-bsa-handoff.md](references/discovery-to-bsa-handoff.md)
