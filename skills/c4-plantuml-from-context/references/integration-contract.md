# C4 PlantUML — BSA Integration Contract

Self-describing integration surface for the `c4-plantuml-from-context` sidecar when it participates in a BSA pipeline run. Peer document: `skills/camunda-bpmn-from-context/references/integration-contract.md`. Orchestrator-owned parent rules: `skills/bsa-orchestrator/references/sidecar-integration.md`.

## Status

- **Sidecar role:** derived-only, non-canonical.
- **Ownership:** generated views cannot be promoted into `analysis/canonical/`. They serve as navigation aids that trace back to canonical anchors, never as the anchors themselves.
- **Validation binding (orchestrator):** `ART-VAL-001-06` (no direct sidecar promotion), `ART-VAL-001-07` (anchor manifest required), `ART-VAL-001-09` (discovery-triggered sidecars remain derived-only).

## Operating modes

### Orchestrated mode

Entered when the skill is invoked by `bsa-orchestrator` as part of a BSA run, or when the user explicitly targets `analysis/views/c4/`.

Detection heuristic:
- The output directory is under `analysis/views/c4/` OR
- The current working tree contains `analysis/canonical/core_controls/A61*` (anchor map) AND the user did not pass `--standalone`.

In orchestrated mode:
- **`anchor_manifest.json` MUST be produced** alongside every emitted `.puml` file and placed at `analysis/views/c4/anchor_manifest.json`.
- **Every `view_element_id`** used in the PlantUML source (C4 `Person`, `System`, `Container`, `Component`, `Rel`, `Deployment_Node`, `System_Boundary`, etc.) MUST appear as an entry in the manifest, mapping to a canonical `A61.AnchorID`.
- **Orphan view elements** (present in `.puml` but absent from manifest) fail `ART-VAL-001-07` and must be either (a) mapped to a new A61 row raised through `bsa-orchestrator`, or (b) removed from the diagram, or (c) routed via `A51` as an unresolved-structure item.
- **Unmapped AnchorIDs** (manifest entries pointing to A61 rows that don't exist) also fail `ART-VAL-001-07`.

### Standalone mode

Entered when the skill is invoked directly by a user outside any BSA workspace, or explicitly via `--standalone`.

Detection heuristic:
- No `analysis/canonical/` anywhere in the working tree ancestry, AND
- User did not explicitly target `analysis/views/c4/`.

In standalone mode:
- **`anchor_manifest.json` is NOT emitted.** The generated `.puml` carries no BSA governance weight.
- The output is informational / review / teaching material only.
- If the user later promotes this diagram into a BSA workspace, they must author the anchor manifest manually or re-run the skill in orchestrated mode.

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

`analysis/views/c4/anchor_manifest.json` is a JSON object with the following shape:

```json
{
  "manifest_version": "1.0",
  "generated_at": "2026-04-19T17:00:00Z",
  "sidecar": "c4-plantuml-from-context",
  "sidecar_version": "1.0.0",
  "canon_policy_version": "0.95.0",
  "view_files": [
    {
      "path": "analysis/views/c4/system_context.puml",
      "diagram_type": "System Context",
      "anchor_map": [
        {
          "view_element_id": "support_desk",
          "view_element_kind": "System",
          "a61_anchor_id": "ANC-SYS-001",
          "notes": "Support desk system in scope; maps to stage4 domain model entry"
        },
        {
          "view_element_id": "agent",
          "view_element_kind": "Person",
          "a61_anchor_id": "ANC-ACTOR-001"
        }
      ]
    }
  ]
}
```

Required fields:
- `manifest_version` — schema version string. `1.0` as of Sprint 3.
- `generated_at` — ISO-8601 UTC timestamp.
- `sidecar` — exact literal `"c4-plantuml-from-context"`.
- `canon_policy_version` — the version active at emission time.
- `view_files` — non-empty array; each entry lists all view elements in one `.puml`.

Per-element required fields:
- `view_element_id` — PlantUML alias / identifier used inside the `.puml`.
- `view_element_kind` — one of the C4-PlantUML macro names documented in `references/c4-plantuml-syntax.md`. Full enum is enforced by `anchor_manifest.schema.json` and covers: people (`Person`, `Person_Ext`), systems (`System`, `System_Ext`, `SystemDb`, `SystemDb_Ext`, `SystemQueue`, `SystemQueue_Ext`), containers (`Container`, `Container_Ext`, `ContainerDb`, `ContainerDb_Ext`, `ContainerQueue`, `ContainerQueue_Ext`), components (`Component`, `Component_Ext`, `ComponentDb`, `ComponentDb_Ext`, `ComponentQueue`, `ComponentQueue_Ext`), boundaries (`Boundary`, `Enterprise_Boundary`, `System_Boundary`, `Container_Boundary`), deployment (`Deployment_Node`, `Deployment_Node_L`, `Deployment_Node_R`, `Node`, `Node_L`, `Node_R`), and relationships (`Rel`, `BiRel`, `RelIndex`). Directional relationship variants (`Rel_U`, `BiRel_Left`, etc.) collapse to their base kind for anchor-mapping purposes.
- `a61_anchor_id` — canonical anchor ID; MUST exist in `analysis/canonical/core_controls/A61*`.

Optional fields:
- `notes` — free-text annotation (one line).

## Relationship to canonical claim-layer

A C4 diagram element is a **view projection** of one or more canonical claims, not a claim itself. The trace chain is:

```
canonical A59 claim  →  A61 anchor row  →  anchor_manifest.json entry  →  .puml view_element_id
```

If a diagram surfaces a boundary, component, or relationship that has no A61 anchor:
- It is NOT license to author a new canonical claim inline in the `.puml`.
- It IS a signal that either (a) the canonical claim-layer is incomplete (route via `A51`, `IssueType=missing_source` or `boundary_risk`), or (b) the diagram is over-reaching (compress or split).

## Failure modes

| Failure | Orchestrated mode | Standalone mode |
|---|---|---|
| Missing `anchor_manifest.json` | Hard fail (ART-VAL-001-07) | N/A |
| Orphan `view_element_id` (in `.puml`, absent from manifest) | Hard fail (ART-VAL-001-07) | N/A |
| Unmapped `a61_anchor_id` (manifest references a non-existent A61 row) | Hard fail (ART-VAL-001-07) | N/A |
| `canon_policy_version` mismatch with current workspace | Soft warning, surface in run log | N/A |
| Skill invoked with ambiguous mode | Hard fail: refuse to emit until user confirms | Hard fail: same |
| Standalone diagram later moved under `analysis/views/c4/` without manifest | Hard fail at next orchestrator run | N/A (pre-move) |

## Cross-references

- Parent contract: `skills/bsa-orchestrator/references/sidecar-integration.md`
- Governance: `governance/immutable_invariants.md` — INV-02 (single-writer canonical: sidecars never write to `analysis/canonical/`) + INV-06 (composition via orchestrator: sidecars are invoked by the orchestrator, they do not invoke workers).
- Peer sidecar: `skills/camunda-bpmn-from-context/references/integration-contract.md`
- Validation scenario: `ART-VAL-001` family in `skills/bsa-orchestrator/references/validation-scenario-manifest.csv`
