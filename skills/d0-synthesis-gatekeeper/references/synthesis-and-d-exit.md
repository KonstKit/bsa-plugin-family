# D5 Synthesis and D-Exit

## Required Outputs
- `discovery_report.md`
- `discovery_brief.md`
- `d_exit_decision.md`
- `stage1_seed_bundle.md`
- `stage2_seed_bundle.md`
- `discovery_citation_audit_report.md`
- `discovery_skeptical_review_report.md`
- `discovery_no_new_facts_report.md`
- `no_solution_leakage_report.md`

## D-Exit Contract (Base)
`D-Exit` base decisioning uses:
- citation status and critical unsupported claims,
- no-solution-leakage status,
- discovery no-new-facts leakage result.

## Run-Profile Extended Gates
- Some run profiles require additional pass markers before `discovery.go`.
- Typical extended markers:
  - `discovery.d5.skeptical_review.pass.json`
  - `discovery.d5.no_new_facts.pass.json`
- Marker requirements are profile-driven by orchestrator routing, not self-selected by this worker.

## Decision Space
- `Go`
- `Pivot`
- `More research`
- `No-go`
