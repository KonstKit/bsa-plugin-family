---
name: proto-from-context
description: Generate Protocol Buffers (proto3) skeleton .proto files from Stage 6 contract-layer artifacts (interface_contract_model.md + A61 anchor map). Use when an analyst needs to ship the BSA contract layer as a machine-readable gRPC service definition for downstream tooling (codegen for Go/Java/Python/etc. service stubs, contract testing, schema registries). Status, scope, and v1.3.2 boundary documented in references/integration-contract.md.
---

# Proto From Context

Bridge between the BSA contract layer (Stage 6) and the Protocol Buffers proto3 specification format (https://protobuf.dev/programming-guides/proto3/). The exporter takes an A61 anchor map plus the contract-layer artifacts the operator chose to publish and emits a proto3 skeleton at `<output_dir>/services.proto` (default `analysis/handoff/contracts/proto/`) plus an anchor manifest at `<output_dir>/anchor_manifest.json`.

Third and final Stage 6 contract exporter in the v1.3.x line: OpenAPI (v1.3.0, shipped), AsyncAPI (v1.3.1, shipped), proto (v1.3.2, this skill — completes the exporter family).

## Operating mode

**Operator-runner only.** Pattern mirrors v1.3.0 OpenAPI + v1.3.1 AsyncAPI exporters + the broader operator-runner family (v1.2.4 telemetry collector, v1.2.16 freshness, v1.2.17 triangulation, v1.2.18 miner, v1.2.19 patcher): stdlib-only (no pyyaml — proto syntax is text, rendered directly), defensive reads, atomic writes via tempfile + os.replace, `--print-only` / `--quiet` / `--workspace` / `--input` / `--output-dir` / `--package` CLI surface. Exit codes: 0 on completion, 2 on invocation error. Not wired into CI, not part of any mandatory marker family.

## Scope (v1.3.2 — skeleton)

**In scope:**
- Read `analysis/canonical/stage6/A61_anchor_map.csv` (canonical, post-promotion).
- Read optional `analysis/canonical/stage6/interface_contract_model.md` (descriptive, free-form; v1.3.2 does not parse it).
- Emit minimal-valid proto3 file at `<output_dir>/services.proto`:
  - `syntax = "proto3";` declaration (mandatory per proto3 spec — must be the first non-comment statement).
  - `package <name>;` (default `bsa.contracts`; overridable via `--package`).
  - For each A61 anchor with `AnchorClass=contract` AND a path-shaped `ElementID` (same channel-shape regex as v1.3.0/v1.3.1) AND a template-name charset matching the **proto3 field-name grammar** `^[A-Za-z_][A-Za-z0-9_]*$` (tightened from v1.3.1's permissive `^[A-Za-z0-9_-]+$` — see below), synthesize a `service.method` pair from the path: first non-template segment → service name (PascalCase), remaining non-template segments → method name (PascalCase concat); template segments (`{order_id}`) become `string <name> = <N>;` fields in the generated request message. Multiple anchors targeting the same service share one `service { ... }` block.
  - Per rpc: `rpc <Method>(<Service><Method>Request) returns (<Service><Method>Response);` plus a `// bsa-anchor: <ClaimID>` comment for traceability (mirror of v1.3.0 OpenAPI tag and v1.3.1 AsyncAPI tag).
  - Per rpc: two top-level `message <Service><Method>Request { ... }` and `message <Service><Method>Response {}` placeholders. Request includes one `string <param_name> = <tag>;` field per template parameter (sequential tag numbers starting at 1). Response is empty by default; operator enriches.
  - All rpcs default to **unary** (`rpc M(Req) returns (Resp);`); operator changes to streaming (`rpc M(stream Req) returns (stream Resp);`) post-export. The skeleton can't infer streaming intent from the A61 anchor alone (mirror of v1.3.1 AsyncAPI's default `send`/operator-may-switch-to-`receive` pattern).
- Emit `<output_dir>/anchor_manifest.json` per the schema at `references/anchor_manifest.schema.json`:
  - One `anchor_map` entry per A61 anchor materialized into the proto shell — Service entry (deduplicated per service across multiple rpcs) + Rpc entry (one per anchor).
  - `view_element_id` for Service: the service name (e.g., `Orders`); for Rpc: `<Service>.<Method>` (e.g., `Orders.Created`).
  - `view_element_kind` ∈ `{Service, Rpc, Message, Enum}` per the schema enum.

**Out of scope (v1.3.2 — explicit deferrals):**
- Parsing free-form prose in `interface_contract_model.md` to populate request/response message schemas. The skeleton emits empty placeholder messages; the operator enriches them in the .proto directly. A future v1.3.2.x can add markdown-driven message-field discovery once a structured authoring convention is established.
- **Dot-style ElementIDs** (`OrderService.CreateOrder`, `orders.created`). v1.3.2 supports only path-style (`/orders/{order_id}/created`) for symmetry with v1.3.0 + v1.3.1. Operators with dot-style ElementIDs in their A61 anchors will see them surface as `element_id_not_path_shaped` in `unmapped_anchors`. A future v1.3.2.x can add a second ElementID dialect once the operator base requests it.
- **Streaming intent inference.** All emitted rpcs are unary; operator manually adds `stream` to request and/or response sides post-export. The A61 anchor schema has no field describing client-stream / server-stream / bidi-stream intent.
- **Cross-file imports** (`import "google/protobuf/timestamp.proto";`, etc.). v1.3.2 emits a single self-contained `services.proto` with only string scalar fields. Operators using well-known types or splitting across files do so post-export.
- **Reserved-keyword / proto-identifier collision auto-renaming.** If a path segment PascalCases to a proto reserved keyword (e.g., path `/service/foo` → `Service.Foo` — the type-level `Service` is fine but the bare lowercase `service` is reserved) or to a name that collides with a primitive type (e.g., `/string/foo` → `String.Foo`), the exporter does NOT auto-rename. Operators are responsible for not using proto reserved words as path segments. If this becomes a recurring operator pain point, a v1.3.2.x can add a name-mangling pass.
- Full proto3 schema validation (e.g., `protoc --check` parse). The exporter does a minimal structural check (proto3 syntax declaration present, services + messages well-formed by construction); deeper validation is the operator's choice via `protoc` directly.
- Auto-merge with operator-edited overlays. The exporter overwrites `services.proto` on every run; operator may use `--output-dir` to write next to a hand-authored overlay and merge externally.
- Message + Enum entries in `view_element_kind`. The enum reserves them for future structured-input releases; v1.3.2 emits Service + Rpc only.
- **Percent-encoded characters in `ElementID`.** Same rule as v1.3.0/v1.3.1: any `%` in an A61 anchor's `ElementID` is rejected (`element_id_not_path_shaped`). Operators must use the decoded character directly. The trade-off is documented in `references/integration-contract.md` — atomic regex-level rejection eliminates the recursive-decode attack surface.
- **Hyphenated template names** (`{order-id}`, `{9id}`, etc.). v1.3.0 OpenAPI accepts hyphens (per OpenAPI/RFC 3986 path-template grammar); v1.3.1 AsyncAPI accepts hyphens (per AsyncAPI 3.0 Parameter Object spec); **v1.3.2 proto rejects them** because proto3 field names must match `^[A-Za-z_][A-Za-z0-9_]*$` (no hyphens, no leading digits). v1.3.2 R1 lesson: when a gate's accepted-token charset binds a downstream emission, the gate MUST match the downstream consumer's grammar — not a sibling exporter's grammar. Operators with hyphenated A61 ElementID templates have to rename them to underscore form (`{order_id}` not `{order-id}`) before the proto exporter will materialize them.

## Why an exporter, not a sidecar

Same architectural reasoning as v1.3.0 OpenAPI + v1.3.1 AsyncAPI exporters: proto3 .proto files are deliverables for downstream consumers (gRPC stub codegen across Go/Java/Python/Rust/etc., contract testing, schema registries), not navigation aids. Output therefore lives at `analysis/handoff/contracts/<format>/` (handoff-pack-style), not `analysis/views/`. Both surfaces remain operator-side and never write to `analysis/canonical/` (INV-02 stays intact).

The skill is NOT registered in `config/sidecar_registry.yaml` — it's an operator-driven exporter, not a sidecar.

## Workflow (operator)

1. Run the BSA pipeline through Stage 6 promotion. `analysis/canonical/stage6/A61_anchor_map.csv` should exist and have passed anchor audit.
2. Invoke the exporter:
   ```bash
   python3 skills/proto-from-context/scripts/generate_proto.py --workspace .
   ```
3. Inspect the emitted .proto at `<output_dir>/services.proto`. The skeleton has placeholder rpcs grouped by synthesized service name, with Request/Response message stubs. Enrich in place: add real fields with proto3 types (`int32`, `int64`, `bool`, nested messages, etc.), choose unary vs `stream` semantics, add `import` statements for well-known types if needed.
4. Inspect `anchor_manifest.json` to verify every emitted service/rpc traces back to a canonical A61 anchor.
5. Validate the enriched .proto with `protoc` (operator-side; exporter does not invoke protoc):
   ```bash
   protoc --proto_path=analysis/handoff/contracts/proto \
          --descriptor_set_out=/dev/null \
          analysis/handoff/contracts/proto/services.proto
   ```
6. Ship the enriched `services.proto` to downstream consumers per the operator's release process. The exporter does NOT run git, does NOT commit, does NOT push, does NOT invoke protoc (mirrors v1.3.0/v1.3.1 + v1.2.19 patcher's never-list).

## Cross-references

- `references/integration-contract.md` — full contract: input shape, output shape, validation rules, gate behavior, failure modes, CLI surface.
- `references/anchor_manifest.schema.json` — JSON Schema (Draft 2020-12) for the emitted manifest. Extends the common base at `governance/schemas/sidecar_anchor_manifest.base.schema.json` with proto-specific discriminators (sidecar literal `proto-from-context`, path extension `\.proto$`, view-element-kind enum `{Service, Rpc, Message, Enum}`, format const `proto3`).
- `skills/openapi-from-context/SKILL.md` — sibling exporter (v1.3.0). v1.3.2 mirrors its structure deliberately so the v1.3.x exporter family stays uniform for operators.
- `skills/asyncapi-from-context/SKILL.md` — sibling exporter (v1.3.1). v1.3.2 reuses the post-R2 channel-shape regex + brace-balance scan structure (lessons baked in pre-Codex), but **the parameter-name charset was re-derived for proto3** (proto3 field-name grammar `^[A-Za-z_][A-Za-z0-9_]*$`, NOT v1.3.1's permissive `^[A-Za-z0-9_-]+$` — see lesson #14: when porting a charset constant across exporters in a sibling family, do NOT reuse verbatim; re-derive from the new exporter's downstream consumer grammar).
- `skills/bsa-contract-builder/SKILL.md` — Stage 6 producer; the exporter consumes its outputs.
- `skills/bsa-handoff-packager/references/handoff-contract.md` — H1-H4 packets; the exporter's proto output sits alongside them under `analysis/handoff/contracts/proto/`.
