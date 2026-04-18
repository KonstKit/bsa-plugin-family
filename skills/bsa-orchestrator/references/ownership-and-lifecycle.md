# Ownership and Lifecycle

## Ownership Matrix

| Surface | Writer | Allowed Content |
| --- | --- | --- |
| `analysis/canonical/` | `bsa-orchestrator` | authoritative main-cycle outputs |
| `analysis/discovery/canonical/` | `bsa-orchestrator` | authoritative discovery outputs |
| `analysis/canonical/core_controls/` | `bsa-orchestrator` | shared `A48/A50/A51` + main-cycle `A58/A59/A60/A61` |
| `analysis/discovery/canonical/core_controls/` | `bsa-orchestrator` | discovery-local `A58/A59/A60` plus references to shared `A48/A50/A51`; mirrored shared ledgers are forbidden |
| `analysis/proposals/` | stage workers | main-cycle proposals only |
| `analysis/discovery/proposals/` | discovery workers + approved reuse auditors | D1-D5 proposals only |
| `analysis/views/` | sidecars/workers | derived-only views |
| `analysis/handoff/` and `analysis/discovery/handoff/` | `bsa-orchestrator` | promoted package surfaces |

## Shared Governance Surfaces
- `A48`, `A50`, and `A51` remain shared instruments across discovery and main-cycle.
- One owner/finalization path only.
- Parallel ledgers are forbidden (`CHK-GOV-001-08`).

## Invariants
- Canonical surfaces are single-writer.
- Fact promotion requires evidence binding or explicit `A51Ref`.
- `A51` tracks uncertainty and unresolved contradictions; it is never a substitute evidence source for positive factual claims.
- Discovery outputs do not bypass main-cycle governance.
- `stage2` is runtime-native and remains governed by the same proposal->promotion ownership model.
