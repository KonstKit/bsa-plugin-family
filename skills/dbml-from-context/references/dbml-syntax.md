# DBML Syntax — Pointer Document

DBML (Database Markup Language) is a small textual format for describing relational schemas. Upstream spec: https://dbml.dbdiagram.io/docs. This document is a pointer + a per-BSA scoping note; it does NOT duplicate the upstream spec.

## What DBML covers (v1.2.11 scope)

| Construct | BSA view-element-kind | Example |
|---|---|---|
| Table | `Table` | `Table users { id integer [pk] }` |
| Column | `Column` | `username varchar [not null]` |
| Ref (top-level) | `Ref` | `Ref: orders.user_id > users.id` |
| Ref (inline) | `Ref` | `user_id integer [ref: > users.id]` |
| Enum | `Enum` | `Enum user_role { admin member }` |
| TableGroup | `TableGroup` | `TableGroup tenancy { users roles }` |

## BSA-specific conventions

1. **One bounded context per `.dbml`**. Don't cram multiple DBs / services into one file. The anchor manifest's `bounded_context` field names this.
2. **snake_case** for table + column names. Matches DBML idiom.
3. **Every table has an explicit PK**. Use the inline `[pk]` / `[primary key]` form for single-column PKs; `indexes { (col1, col2) [pk] }` for composites.
4. **Every FK uses a `Ref`**. Don't leave foreign-key columns implicit — even when the naming convention (`user_id` pointing at `users.id`) is obvious, author the Ref so the anchor manifest has something to reference.
5. **`view_element_id` derivation** is deterministic — see `integration-contract.md` §"view_element_id convention".

## Out of scope (v1.2.11)

DBML supports a few constructs this sidecar doesn't map:
- Triggers / stored procedures (DBML has no native syntax for these anyway).
- CHECK constraints beyond what the bracket-annotation syntax supports.
- Materialized views.
- Storage-layer concerns (tablespaces, partitioning).

When the source material contains these, open an A51 route (`IssueType=missing_source`, `Severity=low`) rather than force-fitting them into DBML.

## Tooling

- **Rendering**: https://dbdiagram.io/ (online) or `@dbml/cli` (local, Node.js). The sidecar does NOT depend on either — `.dbml` is a text artifact consumed by operators + downstream tooling at their discretion.
- **Parsing + validation**: `scripts/validate_dbml.py` ships a MINIMAL stdlib-only syntax check in v1.2.11 (balanced braces, non-empty block bodies, top-level Ref + inline `[ref: ...]` annotation shape). Richer validation (DBML type correctness, FK target resolution) is deferred.

## Cross-references

- Upstream spec: https://dbml.dbdiagram.io/docs
- Integration contract: `skills/dbml-from-context/references/integration-contract.md`
- Anchor manifest schema: `skills/dbml-from-context/references/anchor_manifest.schema.json`
- Peer sidecar syntax docs:
  - `skills/c4-plantuml-from-context/references/c4-plantuml-syntax.md`
  - `skills/camunda-bpmn-from-context/references/support-matrix.md`
