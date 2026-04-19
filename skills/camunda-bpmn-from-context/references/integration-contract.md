# Camunda BPMN — BSA Integration Contract

Self-describing integration surface for the `camunda-bpmn-from-context` sidecar when it participates in a BSA pipeline run. Peer document: `skills/c4-plantuml-from-context/references/integration-contract.md`. Orchestrator-owned parent rules: `skills/bsa-orchestrator/references/sidecar-integration.md`.

## Status

- **Sidecar role:** derived-only, non-canonical.
- **Ownership:** generated BPMN views cannot be promoted into `analysis/canonical/`. They serve as navigation aids that trace back to canonical anchors, never as the anchors themselves.
- **Validation binding (orchestrator):** `ART-VAL-001-06` (no direct sidecar promotion), `ART-VAL-001-07` (anchor manifest required), `ART-VAL-001-09` (discovery-triggered sidecars remain derived-only).

## Operating modes

### Orchestrated mode

Entered when the skill is invoked by `bsa-orchestrator` as part of a BSA run, or when the user explicitly targets `analysis/views/bpmn/`.

Detection heuristic:
- The output directory is under `analysis/views/bpmn/` OR
- The current working tree contains `analysis/canonical/core_controls/A61*` AND the user did not pass `--standalone`.

In orchestrated mode:
- **`anchor_manifest.json` MUST be produced** alongside every emitted `.bpmn` file and placed at `analysis/views/bpmn/anchor_manifest.json`.
- **Every BPMN flow element `id`** used in the `.bpmn` source MUST appear as an entry in the manifest, mapping to a canonical `A61.AnchorID`.
- **Orphan element IDs** (present in `.bpmn` but absent from manifest) fail `ART-VAL-001-07` and must be either (a) mapped to a new A61 row raised through `bsa-orchestrator`, or (b) removed from the diagram, or (c) routed via `A51` as an unresolved-process item.
- **Unmapped AnchorIDs** (manifest entries pointing to A61 rows that don't exist) also fail `ART-VAL-001-07`.

### Standalone mode

Entered when the skill is invoked directly by a user outside any BSA workspace, or explicitly via `--standalone`.

Detection heuristic:
- No `analysis/canonical/` anywhere in the working tree ancestry, AND
- User did not explicitly target `analysis/views/bpmn/`.

In standalone mode:
- **`anchor_manifest.json` is NOT emitted.** The generated `.bpmn` carries no BSA governance weight.
- The output is informational / review / teaching material only.
- If the user later promotes this BPMN into a BSA workspace, they must author the anchor manifest manually or re-run the skill in orchestrated mode.

### Ambiguous context

If the detection heuristic is ambiguous (e.g., there's an `analysis/` directory but no `A61*` files yet, or the user targets a path that resembles BSA but isn't), the skill MUST ask the user to confirm intent before emitting:

```
Detected a path resembling a BSA workspace but no canonical A61 anchor map. Are you:
  (a) authoring inside an in-progress BSA workspace? → orchestrated mode, will emit anchor_manifest.json
  (b) running standalone? → standalone mode, no manifest
```

Silent emission without resolving this ambiguity is a contract violation.

## Anchor manifest schema

Authoritative JSON Schema: [anchor_manifest.schema.json](anchor_manifest.schema.json) (Draft 2020-12). The example below is illustrative; the schema file is the source of truth and is what future sidecar validators will enforce.

`analysis/views/bpmn/anchor_manifest.json` is a JSON object with the following shape:

```json
{
  "manifest_version": "1.0",
  "generated_at": "2026-04-19T17:00:00Z",
  "sidecar": "camunda-bpmn-from-context",
  "sidecar_version": "1.0.0",
  "canon_policy_version": "0.95.0",
  "view_files": [
    {
      "path": "analysis/views/bpmn/ticket_intake.bpmn",
      "bpmn_profile": "documentation",
      "anchor_map": [
        {
          "element_id": "StartEvent_intake",
          "element_kind": "StartEvent",
          "a61_anchor_id": "ANC-EVT-001",
          "notes": "Triggered by any of the three intake channels (C-001 family)"
        },
        {
          "element_id": "Task_assign_severity",
          "element_kind": "Task",
          "a61_anchor_id": "ANC-TASK-002"
        },
        {
          "element_id": "Gateway_severity_branch",
          "element_kind": "ExclusiveGateway",
          "a61_anchor_id": "ANC-DEC-001"
        },
        {
          "element_id": "SequenceFlow_high_to_page",
          "element_kind": "SequenceFlow",
          "a61_anchor_id": "ANC-FLOW-003"
        }
      ]
    }
  ]
}
```

Required fields:
- `manifest_version` — schema version string. `1.0` as of Sprint 3.
- `generated_at` — ISO-8601 UTC timestamp.
- `sidecar` — exact literal `"camunda-bpmn-from-context"`.
- `canon_policy_version` — the version active at emission time.
- `view_files` — non-empty array; each entry lists all modeled element IDs in one `.bpmn`.
- `bpmn_profile` — one of `documentation`, `camunda-7`, `camunda-8`. Matches the runtime target chosen at generation time.

Per-element required fields:
- `element_id` — exact BPMN element `id` attribute as used inside the `.bpmn` XML.
- `element_kind` — one of the modeled BPMN 2.0 types: `StartEvent`, `Task`, `UserTask`, `ServiceTask`, `ReceiveTask`, `SendTask`, `ScriptTask`, `BusinessRuleTask`, `ManualTask`, `CallActivity`, `SubProcess`, `ExclusiveGateway`, `ParallelGateway`, `InclusiveGateway`, `EventBasedGateway`, `BoundaryEvent`, `IntermediateCatchEvent`, `IntermediateThrowEvent`, `EndEvent`, `SequenceFlow`, `MessageFlow`, `Participant`, `Lane`, `DataObject`.
- `a61_anchor_id` — canonical anchor ID; MUST exist in `analysis/canonical/core_controls/A61*`.

Optional fields:
- `notes` — free-text annotation (one line).

### BPMN-specific considerations

Unlike C4 (which models mostly static structure), BPMN heavily weights **flow semantics** — gateways, sequence flows, and decision points carry as much information as tasks do. All of them must be anchored:

- **Sequence flows** — one A61 anchor per sequence flow, because each flow encodes an ordering commitment (step X always precedes step Y). If a sequence flow is surfaced in BPMN but has no upstream claim evidence, it is a fabrication.
- **Gateway branches** — the condition expression on each outgoing flow of an exclusive/inclusive gateway is itself a claim about decision logic. If the condition is inferred rather than directly quoted, the supporting A59 row must use `ClaimType=inference` (not `direct`).
- **Boundary events** — exception paths are almost always under-specified in source material. Do not author BPMN boundary events without an upstream `A59` row or an explicit `A51` route surfacing the missing exception specification.
- **Participants / lanes** — must map to canonical actors in `analysis/canonical/stage2/stakeholder_authority_map.md`.

## Relationship to canonical claim-layer

A BPMN element is a **view projection** of one or more canonical claims, not a claim itself. The trace chain is:

```
canonical A59 claim  →  A61 anchor row  →  anchor_manifest.json entry  →  .bpmn element id
```

If a BPMN diagram surfaces a step, actor, branch, or exception with no A61 anchor:
- It is NOT license to author a new canonical claim inline in the `.bpmn`.
- It IS a signal that either (a) the canonical claim-layer is incomplete (route via `A51`, `IssueType=missing_source` or `boundary_risk`), or (b) the diagram is over-reaching (compress, split, or downgrade to documentation-only without exception branches).

## Failure modes

| Failure | Orchestrated mode | Standalone mode |
|---|---|---|
| Missing `anchor_manifest.json` | Hard fail (ART-VAL-001-07) | N/A |
| Orphan `element_id` (in `.bpmn`, absent from manifest) | Hard fail (ART-VAL-001-07) | N/A |
| Unmapped `a61_anchor_id` (manifest references a non-existent A61 row) | Hard fail (ART-VAL-001-07) | N/A |
| Sequence flow without anchor | Hard fail (ART-VAL-001-07) | N/A |
| Boundary event authored without upstream A59 or A51 route | Hard fail | Soft warning in standalone output |
| `canon_policy_version` mismatch with current workspace | Soft warning, surface in run log | N/A |
| Skill invoked with ambiguous mode | Hard fail: refuse to emit until user confirms | Hard fail: same |
| Standalone diagram later moved under `analysis/views/bpmn/` without manifest | Hard fail at next orchestrator run | N/A (pre-move) |

## Cross-references

- Parent contract: `skills/bsa-orchestrator/references/sidecar-integration.md`
- Governance: `governance/immutable_invariants.md` — INV-02 (single-writer canonical) + INV-06 (composition via orchestrator; sidecars invoked by orchestrator but do not invoke workers).
- Peer sidecar: `skills/c4-plantuml-from-context/references/integration-contract.md`
- Validation scenario: `ART-VAL-001` family in `skills/bsa-orchestrator/references/validation-scenario-manifest.csv`
- Existing BPMN traceability contract (generic, non-BSA): `skills/camunda-bpmn-from-context/references/traceability-contract.md` — complements this document for non-orchestrated workflows.
