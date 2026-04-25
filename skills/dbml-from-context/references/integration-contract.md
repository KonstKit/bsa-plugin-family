# DBML From Context — BSA Integration Contract

Self-describing integration surface for the `dbml-from-context` sidecar when it participates in a BSA pipeline run. Peer documents: `skills/c4-plantuml-from-context/references/integration-contract.md` (architecture layer), `skills/camunda-bpmn-from-context/references/integration-contract.md` (process layer). Orchestrator-owned parent rules: `skills/bsa-orchestrator/references/sidecar-integration.md`.

Added in v1.2.11 as the third BSA sidecar. Status: experimental until a real-pilot pass validates the anchor-mapping convention.

## Status

- **Sidecar role:** derived-only, non-canonical. DBML sits at the data-persistence layer, orthogonal to the c4-plantuml-from-context architectural sidecar.
- **Ownership:** generated views cannot be promoted into `analysis/canonical/`. They serve as navigation aids that trace back to canonical anchors, never as the anchors themselves. The `.dbml` file's tables, columns, and refs are VIEW PROJECTIONS of A59 claims about the data model — they don't establish new canonical facts.
- **Validation binding (orchestrator):** `ART-VAL-001-06` (no direct sidecar promotion), `ART-VAL-001-07` (anchor manifest required), `ART-VAL-001-09` (discovery-triggered sidecars remain derived-only).

## Operating modes

### Orchestrated mode

Entered when the skill is invoked by `bsa-orchestrator` as part of a BSA run, or when the user explicitly targets `analysis/views/dbml/`.

Detection heuristic:
- The output directory is under `analysis/views/dbml/` OR
- The current working tree contains `analysis/canonical/core_controls/A61*` (anchor map) AND the user did not pass `--standalone`.

In orchestrated mode:
- **`anchor_manifest.json` MUST be produced** alongside every emitted `.dbml` file and placed at `analysis/views/dbml/anchor_manifest.json`.
- **Every view-element-id** used in the DBML source (tables, column-as-fk, refs, enums, table groups) MUST appear as an entry in the manifest, mapping to a canonical `A61.AnchorID`.
- **Orphan view elements** (present in `.dbml` but absent from manifest) fail `ART-VAL-001-07` and must be either (a) mapped to a new A61 row raised through `bsa-orchestrator`, or (b) removed from the schema, or (c) routed via `A51` as an unresolved-data-model item.
- **Unmapped AnchorIDs** (manifest entries pointing to A61 rows that don't exist) also fail `ART-VAL-001-07`.

### Standalone mode

Entered when the skill is invoked directly by a user outside any BSA workspace, or explicitly via `--standalone`.

Detection heuristic:
- No `analysis/canonical/` anywhere in the working tree ancestry, AND
- User did not explicitly target `analysis/views/dbml/`.

In standalone mode:
- `anchor_manifest.json` is NOT emitted.
- The generated `.dbml` carries no BSA governance weight — it's a starting point for a data-model discussion.

### Ambiguous context

If the detection heuristic is ambiguous (an `analysis/` directory but no `A61*` files yet, or the user targets a path that resembles BSA but isn't), the skill MUST ask the user to confirm intent before emitting:

```
Detected a path resembling a BSA workspace but no canonical A61 anchor map. Are you:
  (a) authoring inside an in-progress BSA workspace? → orchestrated mode, will emit anchor_manifest.json
  (b) running standalone? → standalone mode, no manifest
```

Silent emission without resolving this ambiguity is a contract violation.

## `view_element_id` convention

DBML elements have natural identifiers in the source — this is simpler than the C4 sidecar's relationship-derivation case. The conventions:

| DBML element | `view_element_id` | `view_element_kind` |
|---|---|---|
| `Table users { ... }` | `users` | `Table` |
| `id integer [primary key]` (column inside `Table users`) | `users.id` | `Column` |
| `Ref: orders.user_id > users.id` (explicit top-level Ref) | `ref_orders_user_id_to_users_id` | `Ref` |
| `user_id integer [ref: > users.id]` (inline column ref) | `ref_<table>_user_id_to_users_id` | `Ref` |
| `Enum user_role { admin member }` | `user_role` | `Enum` |
| `TableGroup tenancy { users roles }` | `tenancy` | `TableGroup` |

- **Tables** use their bare name (snake_case, per DBML convention).
- **Columns** use `<table>.<column>` — this distinguishes a column from a same-named table and keeps the reference unambiguous across the whole schema.
- **Refs** use `ref_<from_table>_<from_col>_to_<to_table>_<to_col>` — deterministic derivation parallel to the C4 relationship convention (`rel_<from>_<connector>_<to>`). Short and long arrow forms (`>`, `-`, `<`) all collapse to `to` at the bridge layer; cardinality / direction, if operators want to track it, rides in the manifest `notes` field.
- **Enums** + **TableGroups** use their bare name.

Multiple refs between the same `(from_table.col, to_table.col)` pair use `__N` suffixes starting at `__2`, matching the C4 convention.

## Anchor manifest schema

Authoritative JSON Schema: [anchor_manifest.schema.json](anchor_manifest.schema.json) (Draft 2020-12).

Example:

```json
{
  "manifest_version": "1.0",
  "generated_at": "2026-04-25T00:00:00Z",
  "sidecar": "dbml-from-context",
  "sidecar_version": "1.0.0",
  "canon_policy_version": "1.2.11+hash:<...>",
  "view_files": [
    {
      "path": "analysis/views/dbml/core_schema.dbml",
      "bounded_context": "user_management",
      "anchor_map": [
        {
          "view_element_id": "users",
          "view_element_kind": "Table",
          "a61_anchor_id": "ANC-TABLE-001",
          "notes": "Primary user identity"
        },
        {
          "view_element_id": "users.id",
          "view_element_kind": "Column",
          "a61_anchor_id": "ANC-COLUMN-001",
          "notes": "PK + FK target for orders.user_id"
        },
        {
          "view_element_id": "ref_orders_user_id_to_users_id",
          "view_element_kind": "Ref",
          "a61_anchor_id": "ANC-REF-001",
          "notes": "Orders belong to a user; cardinality many-to-one"
        }
      ]
    }
  ]
}
```

Required fields:
- `manifest_version` — `"1.0"` as of v1.2.11.
- `generated_at` — ISO-8601 UTC timestamp.
- `sidecar` — exact literal `"dbml-from-context"`.
- `canon_policy_version` — the version active at emission time.
- `view_files` — non-empty array; each entry lists all view elements in one `.dbml`.

Per-view-file required fields:
- `path` — MUST end in `.dbml` and MUST start with `analysis/views/dbml/` in orchestrated mode.
- `bounded_context` — a short identifier for the DB / service / bounded context this file models. Helps operators distinguish multi-context schemas when one workspace ships several `.dbml` files.
- `anchor_map` — non-empty array of `{view_element_id, view_element_kind, a61_anchor_id, notes?}` entries.

## Relationship to canonical claim-layer

A DBML element is a **view projection** of one or more canonical claims, not a claim itself. The trace chain mirrors the C4 sidecar's:

```
canonical A59 claim  →  A61 anchor row  →  anchor_manifest.json entry  →  .dbml view_element_id
```

Typical claim shapes that feed DBML anchors:
- "The system stores user records in a `users` table with primary key `id`" → ANC-TABLE-001 + ANC-COLUMN-001 (2 anchors from 1 claim).
- "Each order belongs to exactly one user" → ANC-REF-001 + cardinality note.

## Failure modes

| Failure | Orchestrated mode | Standalone mode |
|---|---|---|
| Missing `anchor_manifest.json` | Hard fail (ART-VAL-001-07) | N/A |
| Orphan `view_element_id` (in `.dbml`, absent from manifest) | Hard fail (ART-VAL-001-07) | N/A |
| Unmapped `a61_anchor_id` (manifest references a non-existent A61 row) | Hard fail (ART-VAL-001-07) | N/A |
| `.dbml` contains a CREATE TRIGGER or CHECK-beyond-bracket-syntax construct | Route through A51 (IssueType=missing_source, Severity=low) — out-of-scope by contract, not a silent omission | Soft warning in review output |
| Multiple bounded contexts in one `.dbml` | Hard fail at skill-level review — split required | Soft warning |
| `canon_policy_version` mismatch with current workspace | Soft warning, surface in run log | N/A |
| Skill invoked with ambiguous mode | Hard fail: refuse to emit until user confirms | Hard fail: same |

## Cross-references

- Parent contract: `skills/bsa-orchestrator/references/sidecar-integration.md`
- Governance: `governance/immutable_invariants.md` — INV-02 (single-writer canonical: sidecars never write to `analysis/canonical/`) + INV-06 (composition via orchestrator).
- Peer sidecars:
  - `skills/c4-plantuml-from-context/references/integration-contract.md` (architecture)
  - `skills/camunda-bpmn-from-context/references/integration-contract.md` (process)
- Validation scenario: `ART-VAL-001` family in `skills/bsa-orchestrator/references/validation-scenario-manifest.csv`.
- Base schema: `governance/schemas/sidecar_anchor_manifest.base.schema.json`.

## What ships in v1.2.11 / v1.2.15

- **Syntax validator** at `skills/dbml-from-context/scripts/validate_dbml.py` (stdlib-only). v1.2.11 covered: balanced braces, non-empty block bodies, top-level `Ref:` statement shape, inline `[ref: ...]` annotation shape. **v1.2.15 added**: type-catalog enforcement (DBML/SQL base types + parameterized forms; Enum-typed columns resolve against in-file Enum declarations) AND FK target resolution (every Ref must point at an existing `<table>.<column>` declared in this file). The `--lenient-types` CLI flag preserves pre-v1.2.15 permissive type behavior for legacy `.dbml` using custom domain types; FK resolution is unconditional.

## Deferrals

- **Cross-file references**: `[ref: > other_schema.users.id]` with a database-prefix is recognised by upstream DBML but the validator does not resolve targets across files. Single-file FK resolution covers the dominant case (one bounded context per `.dbml` per the BSA convention).
- **Enum-value-binding** (whether an inserted row's column value belongs to the named enum): out of scope; DBML doesn't model row data.
- **Index target resolution**: `indexes { (col1, col2) }` — column existence inside the indexes block is not yet verified by v1.2.15; future release may extend.
- **Automatic manifest emission from `.dbml` source**: the operator or future tooling authors the manifest. A deterministic `.dbml` → manifest derivation is tractable (DBML syntax is simpler than C4-PlantUML) but out of scope for v1.2.11.
- **Inline `[ref: ...]` view_element_id extraction**: v1.2.11's e2e test helper (`_load_dbml_view_elements`) extracts IDs for top-level `Ref:` statements only; inline column-level ref annotations don't currently surface a separate `view_element_id`. The integration-contract documents both forms as anchorable, but the v1.2.11 fixture uses only the top-level form to keep the extractor simple. A follow-up release can extend the helper + fixture together.
- **`sidecar_version` pin**: v1.2.11 uses `1.0.0` (first release). The registry's `added_in: v1.2.11` field is the canonical provenance.
