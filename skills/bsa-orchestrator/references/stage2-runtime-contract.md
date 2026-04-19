# Stage 2 Runtime Contract

## Purpose
Specify required Stage 2 outputs produced before Stage 3.

## Owner
Stage 2 is worker-owned by [`bsa-context-framer`](../../bsa-context-framer/SKILL.md) starting Sprint 1 (US-S1-01). The prior "runtime-native" label is deprecated. The skill's [`context-state-contract.md`](../../bsa-context-framer/references/context-state-contract.md) is the authoritative artifact-shape reference; this document stays in lockstep — any change to required headers, columns, or fields happens in both files in the same PR.

## Required Stage 2 Artifacts
- `analysis/proposals/stage2/context_state_frame.md`
- `analysis/proposals/stage2/stakeholder_authority_map.md`
- `analysis/proposals/stage2/system_context_seed.md`
- `analysis/proposals/stage2/constraints_dependencies_route.md`
- `analysis/proposals/stage2/stage2_summary.json`

## Required Sections

### `context_state_frame.md`
Must include:
- `## Problem Or Objective`
- `## Scope Boundary`
- `## Context Mode`
- `## Stakeholders`
- `## Constraints`
- `## Dependencies`
- `## Open Uncertainties`

### `system_context_seed.md`
Must include:
- `## System Boundary`
- `## Neighboring Systems`
- `## Interface Obligations`
- `## Context Triggers`

### `stakeholder_authority_map.md`
Must contain table columns:
- `stakeholder_id`
- `stakeholder_name`
- `authority_level`
- `decision_scope`
- `linked_a51_refs`

### `constraints_dependencies_route.md`
Must contain table columns:
- `constraint_id`
- `dependency_id`
- `source_ref`
- `escalation_target`
- `linked_a51_refs`

## `stage2_summary.json` Required Fields
- `stage_id = "stage2"`
- `summary_version`
- `context_mode`
- `stakeholder_count`
- `constraint_count`
- `dependency_count`
- `seed_source`
- `stage1_digest`
- `stage2_seed_digest`
- `methodology_digest`
- `contract_version`
- `stale_if`
- `linked_a51_count`
- `required_headers_present`

## Gate Link
- Stage 3 start is blocked until Stage 2 artifacts are promoted and `stage2.context_state.pass.json` is valid.
