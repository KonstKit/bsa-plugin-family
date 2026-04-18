---
name: d0-context-researcher
description: Execute D2 discovery research design, build path artifacts, create pain/gap register, and route evidence into A58/A59/A60 plus A51.
---

# D0 Context Researcher

Use this skill for D2 discovery research and evidence packaging.

## Scope
- Define research design and method mix with explicit quality checks.
- Build path-specific discovery artifacts.
- Produce `Pain/Gap Register` and contradiction routing.
- Build discovery claim-layer proposals `A58/A59/A60`.

## Inputs
- `analysis/discovery/canonical/d1/problem_statement_card.md`
- `analysis/discovery/canonical/d1/stakeholder_map.md`
- `analysis/discovery/canonical/d1/discovery_scope_card.md`
- Available research corpus/interview notes/transcripts/tickets/docs.
- Shared `analysis/canonical/core_controls/A51_issue_route_register.csv`.

## Outputs
- `analysis/discovery/proposals/d2/research_design.md`
- `analysis/discovery/proposals/d2/path_artifact_contract.md`
- `analysis/discovery/proposals/d2/pain_gap_register.md`
- `analysis/discovery/proposals/d2/contradiction_route.md`
- `analysis/discovery/proposals/d2/research_quality_report.md`
- `analysis/discovery/proposals/d2/A58_evidence_excerpts.csv`
- `analysis/discovery/proposals/d2/A59_claim_register.csv`
- `analysis/discovery/proposals/d2/A60_negative_evidence_register.csv`

## Invariants
- Discovery artifacts are AS-IS, not TO-BE design.
- Existing interview transcripts, notes, and call records count as interview evidence when present.
- If no interview evidence exists and cannot be collected autonomously, use an explicit corpus-only exception and route the gap through `A51`.
- External evidence must route through `A58/A59`; never direct canonical write.
- No second uncertainty ledger outside shared `A51`.

## On Audit Failure
1. Keep D2 findings in proposal layer.
2. Add missing evidence routes to `A51Ref`.
3. Regenerate research quality report and affected D2 artifacts.
4. Re-run D2 quality gate before D3.

## Validation Binding
- `SCN-DISC13-001-A` through `SCN-DISC13-001-E`.

## References
- [references/research-design-and-paths.md](references/research-design-and-paths.md)
- [references/path-artifact-contracts.md](references/path-artifact-contracts.md)
