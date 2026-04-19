# Run Profile Gates

## Purpose
Run profile defines which marker set is mandatory for promotion decisions in a given execution mode.

## Baseline Profile (runtime-default)

### Discovery mandatory markers
- `discovery.d1.ready.json`
- `discovery.d2.claims.merged.json`
- `discovery.d2.research_quality.pass.json`
- `discovery.d3.prioritization.pass.json`
- `discovery.d4.constraint_audit.pass.json`
- `discovery.d5.citation_audit.pass.json`
- `discovery.d5.no_solution_leakage.pass.json`
- `discovery.exit.pass.json`

### Main-cycle mandatory markers
- `stage1.excerpts.merged.json`
- `stage2.context_state.pass.json`
- `stage3.citation_audit.pass.json`
- `stage5.anchor_audit.pass.json`
- `stage6.anchor_audit.pass.json`
- `stage7.skeptical_review.pass.json`
- `stage8.no_new_claims.pass.json`

## Extended Discovery Profile (strict)
- Baseline plus:
  - `discovery.d5.skeptical_review.pass.json`
  - `discovery.d5.no_new_claims.pass.json` (legacy marker filename `discovery.d5.no_new_facts.pass.json` accepted for read-only consumption in pre-v1.0 workspaces; migrate via `scripts/migrate_v0.9_to_v1.0.py`)

## Profile Routing Rules
- Orchestrator chooses active profile.
- Workers must not self-select profile from chat.
- Profile changes require re-entry for affected downstream stages.

## Runtime Profile Linkage
- Environment-level runtime profile files live under `config/runtime_profiles/*.json`.
- Marker gate profile selection must remain compatible with active runtime profile metadata.
