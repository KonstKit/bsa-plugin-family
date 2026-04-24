---
name: dbml-from-context
description: Generate DBML (Database Markup Language) schema diagrams from data-model notes, existing SQL DDL, ORM models, and stakeholder interviews. Use when Codex needs to document a relational data model, reverse-engineer a schema from ORM code, encode stakeholder data-model assumptions, or review/fix an existing `.dbml` file. Pairs with the c4-plantuml-from-context sidecar (system-level architecture) — DBML sits at the data-persistence layer below C4 Container/Component views. Status: experimental (added in v1.2.11 as the third BSA sidecar, per the v1.1.x open follow-up at docs/sidecar_inventory.md).
---

# DBML From Context

Model the data layer as DBML (https://dbml.dbdiagram.io/home/) — a human-readable textual format for describing relational schemas. This sidecar sits at the data-persistence layer, orthogonal to the c4-plantuml-from-context architectural sidecar and the camunda-bpmn-from-context process sidecar.

## Scope

- **In scope:** tables, columns + types, primary / foreign keys (`Ref` blocks), enums, table groups, simple indexes.
- **Out of scope:** CREATE TRIGGER / CREATE PROCEDURE (DBML doesn't model stored logic); column-level CHECK constraints beyond what DBML's bracket syntax supports; materialized views; storage-layer details (tablespaces, partitioning).

When the source material contains out-of-scope constructs, open an A51 route (`IssueType=missing_source` with `Severity=low`) rather than force-fitting them into DBML.

## Workflow

1. **Inventory the evidence.**
   - Read data-model docs, existing SQL DDL, ORM model files, schema diagrams, stakeholder interviews about entity semantics.
   - Build a working map of: entities (→ tables), attributes (→ columns), relationships (→ `Ref`s), lookup tables (→ enums), and namespace boundaries (→ table groups).
   - If an existing `.dbml` file is provided, treat its table aliases + column names as the baseline — changing them forces cross-artifact edits in A72 traceability, so keep them stable.

2. **Ask clarifying questions.**
   - Only the blocking ones: which schema / bounded context, entity ownership across services (data mesh vs monolithic DB), AS-IS vs TO-BE, whether lookup tables should be `Table` or `Enum`, cardinality ambiguities (one-to-one vs one-to-many).
   - Proceed with explicit assumptions when the source material is unambiguous.

3. **Emit DBML source.**
   - One `.dbml` file per bounded context. Don't cram multiple contexts into one file — splitting is the operator's signal that the underlying system has multiple DBs / services.
   - Every table has an explicit primary key (DBML supports `[primary key]` inline or `indexes { ... [pk] }`; prefer the inline form for single-column PKs).
   - Every non-nullable column is marked `[not null]`.
   - Every foreign-key column uses `Ref: <from>.<col> > <to>.<col>` (many-to-one) or `Ref: <from>.<col> - <to>.<col>` (one-to-one). Use the top-level `Ref:` statement OR the inline column-level `[ref: ...]` form; pick one style per file for consistency.
   - Name columns + tables in snake_case (DBML convention).

4. **Emit anchor manifest (orchestrated mode only).**
   - Every declared view element — `Table`, every `Column` inside a Table, every top-level `Ref`, every `Enum`, every `TableGroup` — MUST map to an A61 anchor row via `analysis/views/dbml/anchor_manifest.json`.
   - `view_element_id` convention: tables use their bare name (e.g., `users`); columns use `<table>.<column>` (e.g., `users.id`); refs use `ref_<from_table>_<from_col>_to_<to_table>_<to_col>` (e.g., `ref_orders_user_id_to_users_id`); enums + table groups use their bare name.
   - `view_element_kind`: one of `Table`, `Column`, `Ref`, `Enum`, `TableGroup` (per `references/anchor_manifest.schema.json` enum).

5. **Standalone mode** (no `analysis/canonical/` in scope): emit the `.dbml` file without a manifest; the output is informational / teaching material only.

See `references/integration-contract.md` for the full orchestrated-mode contract + `references/anchor_manifest.schema.json` for the manifest shape.

## What ships in v1.2.11

- **Minimal syntax validator** at `scripts/validate_dbml.py` — stdlib-only. Checks balanced braces, non-empty block bodies, top-level `Ref:` statement shape, inline `[ref: ...]` annotation shape. Run via `python3 skills/dbml-from-context/scripts/validate_dbml.py path/to/schema.dbml`.

## Out of scope for v1.2.11

- Automatic `.dbml` → `anchor_manifest.json` generation. The manifest is still hand-authored or emitted by the orchestrator. A future release can add lossless `.dbml`-parser-driven manifest synthesis.
- DBML-level type correctness (whether `varchar`/`integer`/etc. are valid DBML types) — DBML is liberal here, and v1.2.11's validator is deliberately structure-only.
- FK target resolution: a `Ref: orders.user_id > users.id` that points at a non-existent table is structurally valid in v1.2.11 but semantically broken. A future release can add cross-row FK resolution (likely using the `x-bsa-foreign-key-rules`-style extension pattern that A72 + the v1.2.10 generic uniqueness extension established).
- Enum-driven FK resolution: A61 anchors for `Enum`-kind columns exist today but aren't cross-ref-validated against the enum's value list at the F5 hook layer.
- Multi-schema files: each `.dbml` MUST declare exactly one bounded context. The `Project` header is optional.

## Cross-references

- `skills/c4-plantuml-from-context/SKILL.md` — peer sidecar (architecture layer).
- `skills/camunda-bpmn-from-context/SKILL.md` — peer sidecar (process layer).
- `config/sidecar_registry.yaml` — registry entry (added in v1.2.11).
- `docs/sidecar_inventory.md` — sidecar status table (DBML entry added in v1.2.11; marked `experimental` until a real-pilot pass validates the schema shape + the anchor convention).
- `governance/schemas/sidecar_anchor_manifest.base.schema.json` — base schema the DBML manifest extends.
