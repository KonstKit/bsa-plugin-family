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
- `view_element_id` — for declaration-side macros (Person / System / Container / Component / Boundary / Deployment_Node / Node), the PlantUML alias used inside the `.puml`. For relationship macros (`Rel`, `BiRel`, `RelIndex` and their directional variants), the synthetic identifier derived per the convention in §"Relationship view_element_id convention" below — relationships have no native alias in C4-PlantUML.
- `view_element_kind` — one of the C4-PlantUML macro names documented in `references/c4-plantuml-syntax.md`. Full enum is enforced by `anchor_manifest.schema.json` and covers: people (`Person`, `Person_Ext`), systems (`System`, `System_Ext`, `SystemDb`, `SystemDb_Ext`, `SystemQueue`, `SystemQueue_Ext`), containers (`Container`, `Container_Ext`, `ContainerDb`, `ContainerDb_Ext`, `ContainerQueue`, `ContainerQueue_Ext`), components (`Component`, `Component_Ext`, `ComponentDb`, `ComponentDb_Ext`, `ComponentQueue`, `ComponentQueue_Ext`), boundaries (`Boundary`, `Enterprise_Boundary`, `System_Boundary`, `Container_Boundary`), deployment (`Deployment_Node`, `Deployment_Node_L`, `Deployment_Node_R`, `Node`, `Node_L`, `Node_R`), and relationships (`Rel`, `BiRel`, `RelIndex`). Directional relationship variants (`Rel_U`, `BiRel_Left`, etc.) collapse to their base kind for anchor-mapping purposes.
- `a61_anchor_id` — canonical anchor ID; MUST exist in `analysis/canonical/core_controls/A61*`.

Optional fields:
- `notes` — free-text annotation (one line).

## Relationship `view_element_id` convention

C4-PlantUML relationship macros (`Rel`, `BiRel`, `RelIndex` and their directional / layout variants) have no native identifier — the macro signature is positional (from, to, label, [tech], [sprite]) without an explicit ID parameter. Pre-v1.2.9 the integration contract listed relationships as anchorable per the `view_element_kind` enum but did not specify how the corresponding `view_element_id` should be derived; consequently fixtures + sidecar-driven anchor manifests had no mechanism to name relationships, and the v1.2.6 sidecar e2e fixture deliberately shipped without `Rel(...)` coverage to avoid the gap.

v1.2.9 closes this with a **deterministic derivation**: every relationship macro has exactly one `view_element_id` computable from its source-text arguments, with no per-engagement override (anything else would defeat the orchestrator's ability to mechanically cross-reference `.puml` source against the manifest's `anchor_map`).

**Formula:**

```
view_element_id  ::=  "rel_" <from_alias> "_" <connector> "_" <to_alias>  [ "__" <occurrence_index> ]

<connector>      ::=  "to"     for the Rel family:
                                 Rel,
                                 Rel_U / Rel_Up,
                                 Rel_D / Rel_Down,
                                 Rel_L / Rel_Left,
                                 Rel_R / Rel_Right,
                                 Rel_Back,
                                 Rel_Back_Neighbor,
                                 Rel_Neighbor
                 |    "bi"     for the BiRel family:
                                 BiRel,
                                 BiRel_U / BiRel_Up,
                                 BiRel_D / BiRel_Down,
                                 BiRel_L / BiRel_Left,
                                 BiRel_R / BiRel_Right,
                                 BiRel_Neighbor
                 |    "idx_to" for the RelIndex family:
                                 RelIndex,
                                 RelIndex_U / RelIndex_Up,
                                 RelIndex_D / RelIndex_Down,
                                 RelIndex_L / RelIndex_Left,
                                 RelIndex_R / RelIndex_Right,
                                 RelIndex_Back,
                                 RelIndex_Back_Neighbor,
                                 RelIndex_Neighbor
```

The full inventory above mirrors `STATIC_RELATIONSHIP_MACROS` + `DYNAMIC_RELATIONSHIP_MACROS` in `skills/c4-plantuml-from-context/scripts/validate_c4_plantuml.py:84` — that file is the source of truth; if a future C4-PlantUML upstream release adds a new relationship macro, it lands there first and this contract section follows in the same release.

The connector token is the *macro family*, not the direction qualifier. Direction qualifiers (`_U`/`_Up`/`_D`/`_Down`/`_L`/`_Left`/`_R`/`_Right`, plus `_Neighbor` and `_Back_Neighbor` forms) are render-only hints — the bridge layer (A61 anchors) does not partition on them, so the same logical relationship lives under one anchor regardless of layout-level direction tweaks.

**Where direction goes**: at the MANIFEST layer, direction is NOT preserved — `view_element_kind` MUST be the COLLAPSED base kind (`Rel`, `BiRel`, or `RelIndex`), matching the enum in `anchor_manifest.schema.json`. Operators who want to track the direction for diagram-review context SHOULD record it in the optional `notes` field (e.g., `"notes": "rendered as Rel_Up"`). Writing `Rel_Up` / `BiRel_Left` etc. directly into `view_element_kind` fails schema validation — the enum is intentionally the base-kind subset.

**Worked examples:**

| `.puml` source | `view_element_id` | `view_element_kind` | `notes` (optional) |
|---|---|---|---|
| `Rel(agent, web_ui, "Triages tickets via")` | `rel_agent_to_web_ui` | `Rel` | — |
| `Rel_Up(client, server, "queries")` | `rel_client_to_server` | `Rel` (collapsed) | `"rendered as Rel_Up"` |
| `Rel_Neighbor(a, b, "adjacent")` | `rel_a_to_b` | `Rel` (collapsed) | `"rendered as Rel_Neighbor"` |
| `Rel_Back_Neighbor(a, b, "reverse")` | `rel_a_to_b` | `Rel` (collapsed) | `"rendered as Rel_Back_Neighbor"` |
| `BiRel(svc_a, svc_b, "Exchanges health")` | `rel_svc_a_bi_svc_b` | `BiRel` | — |
| `BiRel_Left(svc_a, svc_b, "x")` | `rel_svc_a_bi_svc_b` | `BiRel` (collapsed) | `"rendered as BiRel_Left"` |
| `RelIndex(1, agent, ui, "step 1")` | `rel_agent_idx_to_ui` | `RelIndex` | — |
| `RelIndex_Right(1, agent, ui, "step 1")` | `rel_agent_idx_to_ui` | `RelIndex` (collapsed) | `"rendered as RelIndex_Right"` |

The `RelIndex` numeric index argument is intentionally NOT part of the ID. RelIndex's index is a render-order hint, not an identity discriminator — two distinct `RelIndex` calls between the same `(from, to)` pair are DIFFERENT relationships and use the occurrence-index suffix below.

**Multiple relationships between the same `(from, to, connector)` triple:**

When a `.puml` declares two or more relationships sharing the same `(from, to, connector)` triple (e.g., one `Rel(svc_a, svc_b, "RPC")` and a second `Rel(svc_a, svc_b, "Webhook")`), the first occurrence uses the unsuffixed form (`rel_svc_a_to_svc_b`) and each subsequent occurrence appends `__<N>` starting at `__2` (`rel_svc_a_to_svc_b__2`, `rel_svc_a_to_svc_b__3`, …). Occurrence order is the lexical order in the `.puml` source.

This is the only allowed source of `__N` suffixes; operators MUST NOT use them as a free-form discriminator (e.g., `rel_a_to_b__monitoring`) — anything else would defeat the deterministic-derivation promise. When a single pair has multiple semantically distinct relationships, opening A51 `boundary_risk` routes for each adjacent unresolved item is the right escape hatch.

**Rationale:**

- *Deterministic*: operators and future tooling can both compute the ID without ambiguity. The orchestrator's cross-reference check (every `view_element_id` in the `.puml` must appear in the manifest's `anchor_map`) needs a single canonical mapping; this convention provides one.
- *Readable*: human-meaningful (`rel_agent_to_web_ui` vs. opaque hashes).
- *Stable under label / tech edits*: the connector token + endpoints are the ID; changing the label or tech parameter does NOT churn the manifest.
- *Direction-agnostic*: `Rel(a, b, ...)` and `Rel_U(a, b, ...)` resolve to the same `view_element_id` — direction is a render-layer concern, not a bridge-layer one.

This convention is enforced by the v1.2.6 sidecar e2e test fixture (`tests/test_sidecar_e2e_fixture.py`) — relationship anchors in the v1.2.6 fixture's `.puml` follow this derivation and the test's `_load_c4_view_elements` helper extracts using the same formula.

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
