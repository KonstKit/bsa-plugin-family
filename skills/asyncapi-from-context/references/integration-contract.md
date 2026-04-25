# AsyncAPI From Context — BSA Integration Contract

Self-describing integration surface for the `asyncapi-from-context` exporter. Second of three Stage 6 contract exporters in the v1.3.x line (OpenAPI / AsyncAPI / proto). Status: experimental — the v1.3.1 ship is a skeleton that scaffolds the bundle shape so v1.3.1.x / v1.3.2+ can iterate against a stable contract.

## Status + Ownership

- **Skill role:** operator-driven exporter. NOT a sidecar — see SKILL.md §"Why an exporter, not a sidecar". NOT registered in `config/sidecar_registry.yaml`.
- **Output ownership:** generated artifacts live under `<output_dir>/` (default `analysis/handoff/contracts/asyncapi/`) and are **operator-shipped deliverables**. They never enter `analysis/canonical/` (INV-02 stays intact). The exporter writes only inside `output_dir`.
- **Validation binding:** opt-in; does NOT contribute to a mandatory marker. Operators choosing to enforce AsyncAPI conformance run the AsyncAPI parser CLI (`@asyncapi/parser`) themselves against the emitted YAML.

## Inputs

Required:
- `analysis/canonical/stage6/A61_anchor_map.csv` — the post-audit, orchestrator-promoted anchor map. Source of every materialized AsyncAPI channel + operation.

Optional:
- `analysis/canonical/stage6/interface_contract_model.md` — descriptive prose. v1.3.1 does NOT parse it.
- `analysis/canonical/stage6/boundary_input_output_map.md` — same: documented as future input, not consumed in v1.3.1.

Out of scope:
- `analysis/proposals/stage6/*` — pre-promotion proposals. Only canonical (post-audit) anchors are consumed.

## Outputs

Two files per run, both inside `output_dir`:

### `asyncapi.yaml`

Minimal-valid AsyncAPI 3.0 spec. Top-level shape:

```yaml
asyncapi: "3.0.0"
info:
  title: "<workspace-derived or operator-supplied>"
  version: "1.0.0"
channels:
  channel_anc_<sanitized>_001:
    address: "/orders/{order_id}/created"
    messages: {}
    parameters:
      order_id:
        description: "Placeholder parameter — operator must enrich with type/schema before shipping (extracted from `{order_id}` in address `/orders/{order_id}/created`)."
operations:
  channel_anc_<sanitized>_001:
    action: "send"
    channel:
      $ref: "#/channels/channel_anc_<sanitized>_001"
    tags:
      - name: "bsa-anchor:<ClaimID-or-A51Ref>"
```

For each A61 anchor with `AnchorClass=contract` AND a path-shaped `ElementID` (matches `^/[A-Za-z0-9_/{}.~-]*$` AND has balanced, non-empty, non-nested `{...}` templates whose contents match the AsyncAPI 3.0 Parameter Object name charset `^[A-Za-z0-9_-]+$` AND no literal `..`), one channel + one operation is emitted. When the address contains `{name}` Channel Address Expressions, the channel object also gets a `parameters` map per AsyncAPI 3.0 spec (one entry per distinct template name, with a placeholder `description` the operator enriches with `schema` / `location` after export). Anchors that don't match this shape go into `anchor_manifest.json::unmapped_anchors` with a structured reason — including templates with illegal parameter names like `{tenant.id}` (dot not allowed) or `{user id}` (space not allowed), which surface as `element_id_not_channel_shaped`.

**Channel-shape regex is identical to v1.3.0 OpenAPI exporter's path-shape regex.** Same `%`-rejection rationale (atomic regex-level reject closes the recursive-decode attack surface; encoded traversal at any depth surfaces as `element_id_not_channel_shaped`). Same balanced-brace template scan. Same reach-equality lesson (gate ID matches firing gate ID).

Default `action` is `send` (publisher view). Operator changes to `receive` after export when the operation is consumer-facing; the skeleton can't infer direction from the A61 anchor alone.

### `anchor_manifest.json`

Conforms to `skills/asyncapi-from-context/references/anchor_manifest.schema.json` (Draft 2020-12, extends `governance/schemas/sidecar_anchor_manifest.base.schema.json`).

Top-level: `manifest_version`, `generated_at`, `sidecar` (literal `"asyncapi-from-context"`), `canon_policy_version`, `view_files`.

Per `view_files[]` entry:
- `path` — repo-relative or absolute path to the emitted `asyncapi.yaml` (matches `\.(yaml|yml|json)$`).
- `format` — literal `"asyncapi-3.0"` (discriminator for future spec-version drift).
- `anchor_map` — array of `{view_element_id, view_element_kind, a61_anchor_id, notes?}`.
- `unmapped_anchors` — array of A61 anchor IDs that were skipped (with structured reasons).

`view_element_kind` enum: `Channel` / `Operation` / `Message` / `Server`. v1.3.1 emits Channel + Operation only; Message + Server reserved for future structured-input releases.

`view_element_id` convention:
- `Channel`: the channel key in the YAML (e.g., `channel_anc_user_signedup_001`).
- `Operation`: `<action> <channel-key>` (e.g., `send channel_anc_user_signedup_001`).

## Validation rules

Per emitted `asyncapi.yaml`:
1. **Top-level shape** — `asyncapi`, `info`, `channels`, `operations` keys MUST be present.
2. **Version pin** — `asyncapi: "3.0.0"` literal. v1.3.1 doesn't support 2.x or 3.1+.
3. **No-crash invariant** — even with zero contract-class anchors, the exporter emits a valid `asyncapi.yaml` with empty `channels: {}` + `operations: {}` and a manifest with empty `anchor_map`.

Per emitted `anchor_manifest.json`:
1. **Schema conformance** — validates against `references/anchor_manifest.schema.json` (Draft 2020-12).
2. **Channel/operation pairing** — every channel emitted has a matching operation referencing it (`#/channels/<key>`); both register in the manifest.
3. **No orphans in YAML** — every channel + operation key in `asyncapi.yaml` MUST have a matching `anchor_map` entry. Held by construction.

## Gate behavior

**Non-blocking by default in v1.3.1.** The exporter:
- Always emits both files; an empty A61 input produces an empty-but-valid skeleton.
- Never modifies `analysis/canonical/`.
- Never invokes git.
- Never edits source files referenced by Stage 6 artifacts.

## CLI

```
python3 skills/asyncapi-from-context/scripts/generate_asyncapi.py --workspace <path>
python3 skills/asyncapi-from-context/scripts/generate_asyncapi.py --workspace <path> --input <a61_csv>
python3 skills/asyncapi-from-context/scripts/generate_asyncapi.py --workspace <path> --output-dir <dir>
python3 skills/asyncapi-from-context/scripts/generate_asyncapi.py --workspace <path> --title "My Events" --version "2.0.0"
python3 skills/asyncapi-from-context/scripts/generate_asyncapi.py --workspace <path> --print-only
python3 skills/asyncapi-from-context/scripts/generate_asyncapi.py --workspace <path> --quiet
```

`--input` overrides the canonical A61 path AND bypasses the `analysis/`-init guard, mirroring v1.2.18 miner's `--telemetry-dir` semantic + v1.3.0 OpenAPI exporter's R1-FIX-1. `--output-dir` overrides where the two files go: implicit-missing path is permissive (created on demand), explicit-missing path is rejected (operator typo defense, mirrors v1.2.19 patcher R1-FIX-1). Outside-workspace `--output-dir` records absolute path in manifest (mirrors v1.2.19 patcher R1-FIX-2). `--title` / `--version` populate the AsyncAPI `info` block.

## Failure modes summary

| Failure | Behavior |
|---|---|
| Missing canonical `A61_anchor_map.csv` (and `--input` not given) | Exit 2, message "Stage 6 not promoted" |
| Malformed A61 CSV (parse / missing required columns) | Exit 2, structured error |
| `ElementID` containing literal `..` | Rejected by `_TRAVERSAL_HINT` regex; recorded in `unmapped_anchors` with reason `element_id_path_traversal` |
| `ElementID` containing percent-encoding (any depth: `%2e`, `%252e`, `%25252e`, etc.) | Rejected by the channel-shape regex (`%` is not in the character class); recorded with reason `element_id_not_channel_shaped`. Same R2 design as v1.3.0 OpenAPI exporter: atomic regex-level reject |
| `ElementID` with malformed OpenAPI-style template (`/users/{id`, `/users/{}`, `/users/}{`, `/users/{{id}}`) | Rejected by the brace-balance scan; recorded with reason `element_id_not_channel_shaped` |
| `ElementID` in dot-style (`user.signed_up`) | Rejected by the channel-shape regex (no leading `/`); recorded with reason `element_id_not_channel_shaped`. v1.3.1 only supports path-style — see SKILL "Out of scope" |
| Anchor with non-path-shaped `ElementID` | Rejected; recorded in `unmapped_anchors` |
| Output dir explicit + missing | Exit 2 (mirrors v1.2.19 patcher R1-FIX-1 + v1.3.0 OpenAPI exporter) |
| Output dir implicit + missing | Permissive: created on demand |
| Two anchors map to the same channel address | First wins, rest skipped with reason `duplicate_channel_collision` |
| Bad AnchorID (fails `^ANC-[A-Z0-9_-]+$`) | Silently dropped (would fail manifest schema if surfaced; mirrors v1.3.0 OpenAPI exporter approach) |

## Cross-references

- Sibling exporter (shipped): `skills/openapi-from-context/` (v1.3.0). v1.3.1 mirrors its structure + lessons (R1-R5 from v1.3.0 retro all baked in pre-Codex).
- Future peer (planned): `skills/proto-from-context/` (v1.3.2).
- Producer: `skills/bsa-contract-builder/SKILL.md` (Stage 6 outputs).
- Adjacent: `skills/bsa-handoff-packager/references/handoff-contract.md` (H1-H4 packets sit alongside under `analysis/handoff/`).
- Governance: `governance/immutable_invariants.md` INV-02 (single-writer canonical), INV-03 (no new claims).
- Base schema: `governance/schemas/sidecar_anchor_manifest.base.schema.json`.
