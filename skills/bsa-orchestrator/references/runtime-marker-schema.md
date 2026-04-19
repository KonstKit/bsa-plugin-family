# Runtime Marker Schema

## Marker Zones
- Main: `analysis/runtime/ready/*.json`
- Discovery: `analysis/discovery/runtime/ready/*.json`
- Bridge: `analysis/runtime/ready/bsa.stage1.entry.enabled.json`

## Main Control + Audit Markers
- `stage1.excerpts.merged.json`
- `stage2.ready.json`
- `stage2.context_state.pass.json`
- `stage3.ready.json`
- `stage3.citation_audit.pass.json`
- `stage4.ready.json`
- `stage5.ready.json`
- `stage5.anchor_audit.pass.json`
- `stage6.ready.json`
- `stage6.anchor_audit.pass.json`
- `stage7.ready.json`
- `stage7.skeptical_review.pass.json`
- `stage8.ready.json`
- `stage8.no_new_claims.pass.json`
- `handoff.ready.json`
- `pipeline.complete.json`

## Discovery Markers
- `discovery.d1.ready.json`
- `discovery.d2.claims.merged.json`
- `discovery.d2.research_quality.pass.json`
- `discovery.d3.prioritization.pass.json`
- `discovery.d4.constraint_audit.pass.json`
- `discovery.d5.citation_audit.pass.json`
- `discovery.d5.no_solution_leakage.pass.json`
- optional (strict profile):
  - `discovery.d5.skeptical_review.pass.json`
  - `discovery.d5.no_new_claims.pass.json` (legacy: `discovery.d5.no_new_facts.pass.json` accepted read-only in pre-v1.0 workspaces)
- `discovery.exit.pass.json`
- `discovery.go.json`
- `discovery.pivot.json`
- `discovery.more_research.json`
- `discovery.no_go.json`

## Bridge Rule
`stage1` may start from discovery only when both markers exist:
- `discovery.go.json`
- `bsa.stage1.entry.enabled.json`
