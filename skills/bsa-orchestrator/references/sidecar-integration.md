# Sidecar Integration Contract

## Non-Ownership Rule
Sidecars are non-canonical contributors. Outputs are derived-only and cannot be directly promoted.

## Trigger Matrix

| Sidecar | Trigger | Output Surface | Rule |
| --- | --- | --- | --- |
| `tavily-web-search` | external evidence gap | `analysis/views/evidence/` | route through `A58/A59`, no direct promotion |
| `camunda-bpmn-from-context` | process-path context is stable | `analysis/views/bpmn/` | derived-only + anchor manifest |
| `c4-plantuml-from-context` | boundary/architecture question + stable context | `analysis/views/c4/` | derived-only + anchor manifest |
| `inot-prompt-builder` | adjudication ambiguity | `analysis/views/adjudication/` | advisory |
| `introspection-dialog-starter` | human checkpoint | `analysis/views/checkpoints/` | advisory |

## Implementation Status
- Sidecars are optional integrations, not mandatory BSA core stages.
- Expected sidecars are external skills/tools that may or may not be installed in a given Codex environment.
- If a sidecar is unavailable, continue the core pipeline without blocking canonical promotion.

## Discovery-Triggered Views
Discovery artifacts (journey/process/context maps) may trigger BPMN/C4 generation only as derived aids.
They cannot redefine canonical discovery or main-cycle structure.

## Mandatory Anchor Mapping
Every generated BPMN/C4 view must have `view element -> canonical anchor` mapping in:
- `analysis/views/bpmn/anchor_manifest.json`
- `analysis/views/c4/anchor_manifest.json`

## ART-VAL Binding
- `ART-VAL-001-06`: no direct sidecar promotion.
- `ART-VAL-001-07`: anchor manifest required.
- `ART-VAL-001-09`: discovery-triggered sidecars remain derived-only.
