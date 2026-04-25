---
name: asyncapi-from-context
description: Generate AsyncAPI 3.0 specification skeletons from Stage 6 contract-layer artifacts (interface_contract_model.md + A61 anchor map). Use when an analyst needs to ship the BSA contract layer as a machine-readable event-driven API specification for downstream messaging tooling (codegen for producer/consumer SDKs, broker schema registries, contract testing). Status, scope, and v1.3.1 boundary documented in references/integration-contract.md.
---

# AsyncAPI From Context

Bridge between the BSA contract layer (Stage 6) and the AsyncAPI 3.0 specification format (https://www.asyncapi.com/docs/reference/specification/v3.0.0). The exporter takes an A61 anchor map plus the contract-layer artifacts the operator chose to publish and emits an AsyncAPI YAML skeleton at `<output_dir>/asyncapi.yaml` (default `analysis/handoff/contracts/asyncapi/`) plus an anchor manifest at `<output_dir>/anchor_manifest.json`.

Second of three Stage 6 contract exporters in the v1.3.x line: OpenAPI (v1.3.0, shipped), AsyncAPI (v1.3.1, this skill), proto (v1.3.2, future).

## Operating mode

**Operator-runner only.** Pattern mirrors v1.3.0 OpenAPI exporter + the broader operator-runner family (v1.2.4 telemetry collector, v1.2.16 freshness, v1.2.17 triangulation, v1.2.18 miner, v1.2.19 patcher): stdlib + pyyaml only, defensive reads, atomic writes via tempfile + os.replace, `--print-only` / `--quiet` / `--workspace` / `--input` / `--output-dir` / `--title` / `--version` CLI surface. Exit codes: 0 on completion, 2 on invocation error. Not wired into CI, not part of any mandatory marker family.

## Scope (v1.3.1 — skeleton)

**In scope:**
- Read `analysis/canonical/stage6/A61_anchor_map.csv` (canonical, post-promotion).
- Read optional `analysis/canonical/stage6/interface_contract_model.md` (descriptive, free-form; v1.3.1 does not parse it).
- Emit minimal-valid AsyncAPI 3.0 YAML at `<output_dir>/asyncapi.yaml`:
  - Top-level: `asyncapi: "3.0.0"`, `info` block (title + version), `channels: {}`, `operations: {}`.
  - For each A61 anchor with `AnchorClass=contract` AND a path-shaped `ElementID` (same character class as v1.3.0 OpenAPI exporter; see "Out of scope" for dot-style addresses), add a placeholder `channels/<sanitized_id>` entry with `address: <ElementID>` AND `messages: {}`. When the address contains Channel Address Expressions (`/orders/{order_id}/created`), emit `parameters: {<name>: {description: "..."}}` per the AsyncAPI 3.0 Channel Object spec. Parameter names must match `^[A-Za-z0-9_-]+$` (hyphens allowed; dots and other punctuation rejected at the shape gate as `element_id_not_channel_shaped`). Plus a placeholder `operations/<sanitized_id>` with `action: send`, channel ref, and a tag for traceability.
- Emit `<output_dir>/anchor_manifest.json` per the schema at `references/anchor_manifest.schema.json`:
  - One `anchor_map` entry per A61 anchor materialized into the AsyncAPI shell (Channel + Operation entries — 2 per anchor).
  - `view_element_id` for Channel: the channel key (e.g., `channel_anc_user_signedup_001`); for Operation: `<action> <channel-key>` (e.g., `send channel_anc_user_signedup_001`).
  - `view_element_kind` ∈ `{Channel, Operation, Message, Server}` per the schema enum.

**Out of scope (v1.3.1 — explicit deferrals):**
- Parsing free-form prose in `interface_contract_model.md` to populate message payload schemas. The skeleton emits stubs; the operator enriches them in YAML directly. A future v1.3.1.x can add markdown-driven channel discovery once a structured authoring convention is established.
- **Dot-style channel addresses** (`user.signed_up`, `orders.created.{order_id}`). v1.3.1 supports only path-style (`/user/signedup`, `/orders/{order_id}/created`) for symmetry with the v1.3.0 OpenAPI exporter. Operators with dot-style channels in their A61 anchors will see them surface as `element_id_not_channel_shaped` in `unmapped_anchors`. A future v1.3.1.x can add a second channel-shape regex once the operator base requests it.
- Full AsyncAPI 3.0 schema validation. The exporter does a minimal structural check (top-level required fields present); deeper validation is the operator's choice via the AsyncAPI parser CLI (`@asyncapi/parser`) or equivalent (NOT a Python dep — operators run the JS-side validator on the emitted YAML).
- Auto-merge with operator-edited overlays. The exporter overwrites `asyncapi.yaml` on every run; operator may use `--output-dir` to write next to a hand-authored overlay and merge externally.
- Server / Message / Tag entries in `view_element_kind`. The enum reserves them for future structured-input releases; v1.3.1 emits Channel + Operation only.
- **Percent-encoded characters in `ElementID`.** Same rule as v1.3.0 OpenAPI exporter: any `%` in an A61 anchor's `ElementID` is rejected (`element_id_not_channel_shaped`). Operators must use the decoded character directly (`/user/foo` not `/user/%66oo`). The trade-off is documented in `references/integration-contract.md` — atomic regex-level rejection eliminates the recursive-decode attack surface.

## Why an exporter, not a sidecar

Same architectural reasoning as v1.3.0 OpenAPI exporter: AsyncAPI specs are deliverables for downstream consumers (producer/consumer SDK codegen, broker schema registries), not navigation aids. Output therefore lives at `analysis/handoff/contracts/<format>/` (handoff-pack-style), not `analysis/views/`. Both surfaces remain operator-side and never write to `analysis/canonical/` (INV-02 stays intact).

The skill is NOT registered in `config/sidecar_registry.yaml` — it's an operator-driven exporter, not a sidecar.

## Workflow (operator)

1. Run the BSA pipeline through Stage 6 promotion. `analysis/canonical/stage6/A61_anchor_map.csv` should exist and have passed anchor audit.
2. Invoke the exporter:
   ```bash
   python3 skills/asyncapi-from-context/scripts/generate_asyncapi.py --workspace .
   ```
3. Inspect the emitted YAML at `<output_dir>/asyncapi.yaml`. The skeleton has placeholder channels + operations for every contract-class anchor with a path-shaped ElementID; enrich in place with real message payload schemas + per-operation action (`send`/`receive`) decisions + server bindings.
4. Inspect `anchor_manifest.json` to verify every emitted channel/operation traces back to a canonical A61 anchor.
5. Ship the enriched `asyncapi.yaml` to downstream consumers per the operator's release process. The exporter does NOT run git, does NOT commit, does NOT push (mirrors v1.3.0 OpenAPI + v1.2.19 patcher's never-list).

## Cross-references

- `references/integration-contract.md` — full contract: input shape, output shape, validation rules, gate behavior, failure modes, CLI surface.
- `references/anchor_manifest.schema.json` — JSON Schema (Draft 2020-12) for the emitted manifest. Extends the common base at `governance/schemas/sidecar_anchor_manifest.base.schema.json` with AsyncAPI-specific discriminators (sidecar literal `asyncapi-from-context`, path extension `\.(yaml|yml|json)$`, view-element-kind enum `{Channel, Operation, Message, Server}`, format const `asyncapi-3.0`).
- `skills/openapi-from-context/SKILL.md` — sibling exporter (v1.3.0). v1.3.1 mirrors its structure deliberately so the v1.3.x exporter family stays uniform for operators.
- `skills/bsa-contract-builder/SKILL.md` — Stage 6 producer; the exporter consumes its outputs.
- `skills/bsa-handoff-packager/references/handoff-contract.md` — H1-H4 packets; the exporter's AsyncAPI output sits alongside them under `analysis/handoff/contracts/asyncapi/`.
- Future peer: `skills/proto-from-context/` (v1.3.2).
