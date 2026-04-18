# Agent Write Scope

## Global Rule
Workers write only to owned proposal/view folders. Canonical writes are orchestrator-only.

| Agent / Skill | Allowed Writes | Forbidden Writes |
| --- | --- | --- |
| `bsa-orchestrator` | `analysis/runtime/*`, `analysis/canonical/*`, `analysis/handoff/*`, `analysis/discovery/runtime/*`, `analysis/discovery/canonical/*`, `analysis/discovery/handoff/*` | none in contract |
| `d0-problem-framer` | `analysis/discovery/proposals/d1/` | canonical/handoff |
| `d0-context-researcher` | `analysis/discovery/proposals/d2/` | canonical/handoff |
| `d0-hypothesis-prioritizer` | `analysis/discovery/proposals/d3/` | canonical/handoff |
| `d0-feasibility-assessor` | `analysis/discovery/proposals/d4/` | canonical/handoff |
| `d0-synthesis-gatekeeper` | `analysis/discovery/proposals/d5/` | canonical/handoff |
| `bsa-evidence-intake` | `analysis/proposals/stage1/` | canonical/handoff |
| `bsa-claim-binder` | `analysis/proposals/stage1/` | canonical/handoff |
| `stage2` (runtime-native) | `analysis/proposals/stage2/` (runtime executor output) | canonical/handoff direct writes outside orchestrator promotion |
| `bsa-semantic-extractor` | `analysis/proposals/stage3/` | canonical/handoff |
| `bsa-domain-modeler` | `analysis/proposals/stage4/` | canonical/handoff |
| `bsa-backbone-builder` | `analysis/proposals/stage5/` | canonical/handoff |
| `bsa-anchor-auditor` | `analysis/proposals/stage5/`, `analysis/proposals/stage6/` | canonical/handoff |
| `bsa-contract-builder` | `analysis/proposals/stage6/` | canonical/handoff |
| `bsa-citation-auditor` | `analysis/proposals/stage7_8/stage7/`, `analysis/discovery/proposals/d5/` | canonical/handoff |
| `bsa-consistency-auditor` | `analysis/proposals/stage7_8/stage7/`, `analysis/discovery/proposals/d5/` | canonical/handoff |
| `bsa-skeptical-reviewer` | `analysis/proposals/stage7_8/stage7/`, `analysis/discovery/proposals/d5/` | canonical/handoff |
| `bsa-no-new-facts-auditor` | `analysis/proposals/stage7_8/stage8/`, `analysis/proposals/stage7_8/handoff/`, `analysis/discovery/proposals/d5/` | canonical/handoff |
| `bsa-validation-readiness` | `analysis/proposals/stage7_8/stage7/`, `analysis/proposals/stage7_8/stage8/` | canonical/handoff |
| `bsa-handoff-packager` | `analysis/proposals/stage7_8/handoff/` | canonical/handoff |
| sidecars | `analysis/views/*` | canonical/handoff direct promotion |

## Violation Handling
- reject write
- append violation event
- route governance item via shared `A51`
