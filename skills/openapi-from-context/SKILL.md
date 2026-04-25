---
name: openapi-from-context
description: Generate OpenAPI 3.1 specification skeletons from Stage 6 contract-layer artifacts (interface_contract_model.md + A61 anchor map). Use when an analyst needs to ship the BSA contract layer as a machine-readable API specification for downstream API tooling (codegen, mock servers, contract testing). Status, scope, and v1.3.0 boundary documented in references/integration-contract.md.
---

# OpenAPI From Context

Bridge between the BSA contract layer (Stage 6) and the OpenAPI 3.1 specification format (https://spec.openapis.org/oas/v3.1.0). The exporter takes an A61 anchor map plus the contract-layer artifacts the operator chose to publish and emits an OpenAPI YAML skeleton at `analysis/handoff/contracts/openapi/api.yaml` plus an anchor manifest at `analysis/handoff/contracts/openapi/anchor_manifest.json`.

First of three Stage 6 contract exporters in the v1.3.x line: OpenAPI (v1.3.0, this skill), AsyncAPI (v1.3.1, future), proto (v1.3.2, future).

## Operating mode

**Operator-runner only.** The exporter is invoked manually by an analyst, not auto-fired by the orchestrator. Pattern mirrors `scripts/freshness_audit.py` (v1.2.16), `scripts/triangulation_audit.py` (v1.2.17), `scripts/phase_7_miner.py` (v1.2.18), `scripts/phase_7_patcher.py` (v1.2.19): stdlib-only, defensive reads, atomic writes, `--print-only` / `--quiet` / `--workspace` / `--input` / `--output-dir` CLI surface, exit codes (0 on completion, 2 on invocation error). Not wired into CI; not part of any mandatory marker family.

## Scope (v1.3.0 — skeleton)

**In scope:**
- Read `analysis/canonical/stage6/A61_anchor_map.csv` (canonical, post-promotion).
- Read optional `analysis/canonical/stage6/interface_contract_model.md` (descriptive, free-form).
- Emit minimal-valid OpenAPI 3.1 YAML at `analysis/handoff/contracts/openapi/api.yaml`:
  - `openapi: "3.1.0"`, `info` block (title + version), `paths: {}` placeholder.
  - For each A61 anchor with `AnchorClass=contract` AND a path-shaped `ElementID`, add a placeholder `paths/<id>` entry with a single `get` operation tagged with the anchor's `ClaimID` for traceability.
- Emit `analysis/handoff/contracts/openapi/anchor_manifest.json` per the schema at `references/anchor_manifest.schema.json`:
  - One `anchor_map` entry per A61 anchor materialized into the OpenAPI shell.
  - `view_element_id` = the OpenAPI path or operation key (`<path>` for PathItem, `<METHOD> <path>` for Operation).
  - `view_element_kind` ∈ `{Operation, PathItem, Schema, Tag}` per the schema enum.

**Out of scope (v1.3.0 — explicit deferrals):**
- Parsing free-form prose in `interface_contract_model.md` to populate request/response schemas. The skeleton emits stubs; the operator enriches them in YAML directly. A future v1.3.0.x can add markdown-driven path discovery once a structured authoring convention is established.
- Full OpenAPI 3.1 schema validation. The exporter does a minimal structural check (top-level required fields present); deeper validation is the operator's choice via `openapi-spec-validator` or equivalent (test-only dep, not pinned at runtime).
- Auto-merge with operator-edited overlays. The exporter overwrites `api.yaml` on every run (per Phase 7 patcher's atomic-write semantics); operator may choose `--output-dir` to write next to a hand-authored overlay and merge externally.
- AsyncAPI / gRPC / proto export. Those are v1.3.1 / v1.3.2 follow-ups in this same `analysis/handoff/contracts/<format>/` family.
- **Percent-encoded characters in `ElementID`.** Any `%` in an A61 anchor's `ElementID` is rejected (`element_id_not_path_shaped`). Operators must use the decoded character directly: `/users/foo`, NOT `/users/%66oo`; `/items/{id}`, NOT `/items/%7Bid%7D`. The trade-off is documented in `references/integration-contract.md` §"Outputs" — atomic regex-level rejection eliminates the recursive-decode attack surface (encoded traversal like `%2e%2e`, double-encoded `%252e%252e`, triple-encoded `%25252e%25252e` are all rejected at the same gate) without requiring iterative decode + `%HH`-validity passes.

## Why an exporter, not a sidecar

DBML / C4 / BPMN sidecars sit at `analysis/views/<sidecar>/` and produce *navigation aids* — derived diagrams that trace back to canonical anchors but don't ship as deliverables themselves. OpenAPI / AsyncAPI / proto specs ARE deliverables — they're what downstream API teams consume. The output therefore lives at `analysis/handoff/contracts/<format>/` (handoff-pack-style), not `analysis/views/`. Both surfaces remain operator-side and never write to `analysis/canonical/` (INV-02 stays intact).

The skill is NOT registered in `config/sidecar_registry.yaml` — it's an operator-driven exporter, not a sidecar.

## Workflow (operator)

1. Run the BSA pipeline through Stage 6 promotion. `analysis/canonical/stage6/A61_anchor_map.csv` should exist and have passed anchor audit.
2. Invoke the exporter:
   ```bash
   python3 skills/openapi-from-context/scripts/generate_openapi.py --workspace .
   ```
3. Inspect the emitted YAML at `analysis/handoff/contracts/openapi/api.yaml`. The skeleton has placeholder paths for every contract-class anchor; enrich in place with real request/response schemas.
4. Inspect `anchor_manifest.json` to verify every emitted path/operation traces back to a canonical A61 anchor. Orphan paths (in YAML but absent from manifest) and unmapped anchors (manifest entry without an A61 row) are operator-fixable; the exporter never tries to "auto-fix" them.
5. Ship the enriched `api.yaml` to downstream consumers per the operator's release process. The exporter does NOT run git, does NOT commit, does NOT push (mirrors L2 patcher's never-list).

## Cross-references

- `references/integration-contract.md` — full contract: input shape, output shape, validation rules, gate behavior, failure modes.
- `references/anchor_manifest.schema.json` — JSON Schema (Draft 2020-12) for the emitted manifest. Extends the common base at `governance/schemas/sidecar_anchor_manifest.base.schema.json` with OpenAPI-specific discriminators (sidecar literal `openapi-from-context`, path extension `\.(yaml|yml|json)$`, view-element-kind enum `{Operation, PathItem, Schema, Tag}`).
- `skills/bsa-contract-builder/SKILL.md` — Stage 6 producer; the exporter consumes its outputs.
- `skills/bsa-handoff-packager/references/handoff-contract.md` — H1-H4 packets; the exporter's OpenAPI output sits alongside them under `analysis/handoff/contracts/openapi/` (handoff-pack-style location, but the exporter is independent of the packager — neither invokes the other).
- Future peers: `skills/asyncapi-from-context/` (v1.3.1), `skills/proto-from-context/` (v1.3.2).
