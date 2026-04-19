# Stage 2 Context-State Contract

Authoritative shape for `analysis/proposals/stage2/` outputs. Aligned with `bsa-orchestrator/references/stage2-runtime-contract.md`; any change here MUST be mirrored there in the same PR.

## `context_state_frame.md`

Required section headers (exact strings, in any order; missing or renamed sections fail `SCN-STAGE2-001-B`):

- `## Problem Or Objective`
- `## Scope Boundary`
- `## Context Mode`
- `## Stakeholders`
- `## Constraints`
- `## Dependencies`
- `## Open Uncertainties`

Section body rules:

- Every positive factual claim cites `ClaimID` inline in `[C-xxx]` form or explicit `A51Ref` in `[A51-xxx]` form. Bullets without citations are rejected.
- `## Context Mode` must state exactly one of `direct` or `discovery_then_bsa`, matching `A48.Mode`.
- `## Scope Boundary` splits into `### In` and `### Out` subsections.
- `## Open Uncertainties` entries must point at `A51Ref` values and summarize blocking status.

## `stakeholder_authority_map.md`

Markdown table with exactly these columns in this order:

| Column | Meaning |
|---|---|
| `stakeholder_id` | Opaque ID (`ST-xxx`); unique in the file |
| `stakeholder_name` | Role or persona label, not a person's name unless architecturally relevant |
| `authority_level` | One of `decision`, `consultation`, `informational` |
| `decision_scope` | Bounded description of what this stakeholder decides or reviews |
| `linked_a51_refs` | Semicolon-separated `A51-xxx` IDs where this stakeholder is escalation target |

Rules:

- Every row must cite at least one `ClaimID` (in a trailing narrative line below the table) or carry `linked_a51_refs`.
- If the same authority level is contested between two stakeholders, raise an `A51` entry with `IssueType=decision_needed` and link both rows to its `A51Ref`.

## `system_context_seed.md`

Required section headers:

- `## System Boundary`
- `## Neighboring Systems`
- `## Interface Obligations`
- `## Context Triggers`

Rules:

- `## System Boundary` states the single in-scope system and a short rationale; cite `ClaimID` or `A51Ref`.
- `## Neighboring Systems` enumerates external actors/systems; one bullet per neighbor with evidence citation.
- `## Interface Obligations` enumerates inbound/outbound obligations as bullets, each carrying evidence citation. No invented integrations.
- `## Context Triggers` enumerates the events or signals that start a main-cycle instance.

## `constraints_dependencies_route.md`

Markdown table with exactly these columns:

| Column | Meaning |
|---|---|
| `constraint_id` | `CN-xxx` (constraint) OR left blank if row is a pure dependency |
| `dependency_id` | `DP-xxx` (dependency) OR left blank if row is a pure constraint |
| `source_ref` | `ClaimID` (with underlying `SourceID+ExcerptID`) OR `A51Ref` |
| `escalation_target` | `stakeholder_id` from `stakeholder_authority_map.md` or `none` |
| `linked_a51_refs` | Semicolon-separated `A51-xxx` IDs when status is contested |

Rules:

- Exactly one of `constraint_id` or `dependency_id` per row (never both, never neither).
- `source_ref` is non-empty — rows without evidence binding fail validation.
- `escalation_target`, if not `none`, must exist in `stakeholder_authority_map.md`.

## `stage2_summary.json`

Required top-level fields:

- `stage_id` — literal string `"stage2"`
- `summary_version` — integer, start at `1`
- `context_mode` — `"direct"` or `"discovery_then_bsa"`
- `stakeholder_count` — int
- `constraint_count` — int
- `dependency_count` — int
- `seed_source` — `"stage1_canonical"` or `"discovery_stage2_seed_plus_stage1_canonical"`
- `stage1_digest` — sha256 of canonical Stage 1 artifacts used as input (short prefix)
- `stage2_seed_digest` — sha256 of `stage2_seed_bundle.md` when present; empty string otherwise
- `methodology_digest` — sha256 of `context-state-contract.md` + `stakeholder-authority-rules.md` + `system-context-seed-template.md` (short prefix)
- `contract_version` — `CanonPolicyVersion` on promotion (e.g. `"0.95"` post-Sprint-1)
- `stale_if` — array of strings, each describing a condition that invalidates this summary
- `linked_a51_count` — int
- `required_headers_present` — boolean; `true` only when all mandatory sections exist across every `*.md` output

Rules:

- Re-running the skill on unchanged canonical inputs must produce identical digests (deterministic generation).
- On any mismatch between `required_headers_present=true` and actual section state, `SCN-STAGE2-001-B` fails.

## Evidence citation conventions

- Inline ClaimID reference: `[C-042]` (brackets around ClaimID only).
- Inline A51Ref reference: `[A51-003]`.
- Analyst-judgment inline marker: `[AJ:C-xxx]` on the judgment row; its `JustificationRationale` carries the upstream refs.

## Out of scope

- Stage 4 catalog stabilization (actor/entity/event/status/rule catalogs) — adding those here fails `SCN-STAGE2-001-A` structural check.
- Path selection (process vs structural) — decided in Stage 5 by `bsa-backbone-builder`, not here.
- Interface contract modeling — Stage 6 by `bsa-contract-builder`.
