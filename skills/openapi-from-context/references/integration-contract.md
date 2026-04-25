# OpenAPI From Context — BSA Integration Contract

Self-describing integration surface for the `openapi-from-context` exporter. First of three Stage 6 contract exporters in the v1.3.x line (OpenAPI / AsyncAPI / proto). Status: experimental — the v1.3.0 ship is a skeleton that scaffolds the bundle shape so v1.3.0.x / v1.3.1+ can iterate against a stable contract.

## Status + Ownership

- **Skill role:** operator-driven exporter. NOT a sidecar — see SKILL.md §"Why an exporter, not a sidecar". NOT registered in `config/sidecar_registry.yaml`.
- **Output ownership:** generated artifacts live under `analysis/handoff/contracts/openapi/` and are **operator-shipped deliverables**, not derived navigation aids. They never enter `analysis/canonical/` (INV-02 stays intact). The exporter writes only inside its `output_dir` (default `analysis/handoff/contracts/openapi/`; CLI override `--output-dir`).
- **Validation binding:** the exporter is opt-in and does NOT contribute to a mandatory marker. Operators choosing to enforce OpenAPI shape compliance run `openapi-spec-validator` (or equivalent) themselves against the emitted YAML; the exporter's own checks are minimal-structural (top-level required fields).

## Inputs

Required:
- `analysis/canonical/stage6/A61_anchor_map.csv` — the post-audit, orchestrator-promoted anchor map. Source of every materialized OpenAPI path/operation. Without this file the exporter exits 2 with a clear "no canonical A61 found" message.

Optional (read when present, ignored when absent — never required):
- `analysis/canonical/stage6/interface_contract_model.md` — descriptive prose. v1.3.0 does NOT parse it (skeleton-only); future versions may extract path/method/parameter hints. Presence/absence does not affect output shape.
- `analysis/canonical/stage6/boundary_input_output_map.md` — same: documented as future input, not consumed in v1.3.0.

Out of scope:
- `analysis/proposals/stage6/*` — pre-promotion proposals. The exporter consumes only canonical (post-audit) anchors so that downstream API consumers receive the same anchor set the orchestrator endorsed.

## Outputs

Two files per run, both inside `output_dir` (default `analysis/handoff/contracts/openapi/`):

### `api.yaml`

Minimal-valid OpenAPI 3.1 spec. Top-level shape:

```yaml
openapi: "3.1.0"
info:
  title: "<workspace-derived or operator-supplied>"
  version: "1.0.0"
paths:
  /<anchor-derived-path>:
    get:
      operationId: "anc_<sanitized_anchor_id>_get"
      summary: "Placeholder operation for A61 anchor <AnchorID>"
      tags: ["bsa-anchor:<ClaimID-or-A51Ref>"]
      responses:
        "200":
          description: "Placeholder response — operator must enrich"
```

For each A61 anchor with `AnchorClass=contract` AND a path-shaped `ElementID` (matches `^/[A-Za-z0-9_/{}.~-]*$` AND has balanced, non-empty, non-nested `{...}` templates AND no literal `..`), one path entry is emitted with one `get` operation. Anchors that don't match this shape go into `anchor_manifest.json::unmapped_anchors` with a structured reason (`element_id_not_path_shaped`, `element_id_path_traversal`, etc.) instead of polluting the YAML.

**`%` is intentionally NOT in the path character class.** Operators authoring A61 anchors must use the decoded character directly (`/users/foo` not `/users/%66oo`). The trade-off is documented in the exporter's `_PATH_SHAPE` comment: legitimate OpenAPI path templates rarely need `%`-encoding (parameters carry encoded values, path literals stay decoded), and admitting `%` opens a recursive-decode attack surface that requires either iterative decode-until-stable + `%HH` validation OR atomic regex-level rejection — the latter is simpler and equally safe. Encoded traversal (`/foo/%2e%2e/bar` and depth variants) is rejected at the path-shape gate as `element_id_not_path_shaped`, not as `element_id_path_traversal` — both reject the input but the structured reason matches the actual gate that fired (reach-equality lesson from v1.2.16 R5 + v1.2.19 R5).

### `anchor_manifest.json`

Conforms to `skills/openapi-from-context/references/anchor_manifest.schema.json` (Draft 2020-12, extends `governance/schemas/sidecar_anchor_manifest.base.schema.json`).

Top-level: `manifest_version`, `generated_at`, `sidecar` (literal `"openapi-from-context"`), `canon_policy_version`, `view_files`.

Per `view_files[]` entry:
- `path` — repo-relative or absolute path to the emitted `api.yaml` (matches `\.(yaml|yml|json)$`).
- `format` — literal `"openapi-3.1"` (discriminator for future spec-version drift).
- `anchor_map` — array of `{view_element_id, view_element_kind, a61_anchor_id, notes?}`.
- `unmapped_anchors` — array of A61 anchor IDs that were considered but skipped (with structured reasons).

`view_element_kind` enum: `Operation` / `PathItem` / `Schema` / `Tag`. v1.3.0 emits only `Operation` + `PathItem`; `Schema` + `Tag` reserved for future structured-input releases.

`view_element_id` convention:
- `PathItem`: the path itself (e.g., `/users/{id}`).
- `Operation`: `<METHOD> <path>` (e.g., `GET /users/{id}`).

## Validation rules

Per emitted `api.yaml`:
1. **Top-level shape** — `openapi`, `info`, `paths` keys MUST be present (minimal OpenAPI 3.1).
2. **Version pin** — `openapi: "3.1.0"` literal. v1.3.0 doesn't support 3.0.x.
3. **No-crash invariant** — even with zero contract-class anchors, the exporter emits a valid `api.yaml` with `paths: {}` and a manifest with empty `anchor_map`.

Per emitted `anchor_manifest.json`:
1. **Schema conformance** — validates against `references/anchor_manifest.schema.json` (Draft 2020-12).
2. **Round-trip integrity** — every entry in `anchor_map` MUST resolve to an A61 row that was in the input CSV at exporter run time (drift detection between input + manifest catches the case where the canonical A61 changed mid-run).
3. **No orphans in YAML** — every path/operation key in `api.yaml` MUST have a matching `anchor_map` entry. The exporter constructs both from the same iteration, so this holds by construction; the schema test pins it.

## Gate behavior

**Non-blocking by default in v1.3.0.** The exporter:
- Always emits both files; an empty A61 input produces an empty-but-valid skeleton, not an error.
- Never modifies `analysis/canonical/`.
- Never invokes `git`, `git apply`, `git commit`, or `git push`.
- Never edits source files referenced by tunables or by Stage 6 artifacts.

Failure modes:
- Missing `analysis/canonical/stage6/A61_anchor_map.csv` → exit 2, clear "promote Stage 6 first" message.
- Malformed `A61_anchor_map.csv` (CSV parse error / missing required columns) → exit 2, line/column-localized error.
- Output directory not writable → exit 2, clear filesystem error.
- Operator passes `--output-dir` outside the workspace → permitted (mirrors v1.2.19 patcher's R1-FIX-2); paths in `_index.json` and the summary fall back to absolute strings.

## CLI

```
python3 skills/openapi-from-context/scripts/generate_openapi.py --workspace <path>
python3 skills/openapi-from-context/scripts/generate_openapi.py --workspace <path> --input <a61_csv>
python3 skills/openapi-from-context/scripts/generate_openapi.py --workspace <path> --output-dir <dir>
python3 skills/openapi-from-context/scripts/generate_openapi.py --workspace <path> --title "My API"
python3 skills/openapi-from-context/scripts/generate_openapi.py --workspace <path> --version "2.1.0"
python3 skills/openapi-from-context/scripts/generate_openapi.py --workspace <path> --print-only
python3 skills/openapi-from-context/scripts/generate_openapi.py --workspace <path> --quiet
```

`--input` overrides the canonical A61 path (useful for fixture-based runs without an initialized BSA workspace). `--output-dir` overrides where the two output files go (mirrors v1.2.19 patcher: implicit-missing path is permissive, explicit-missing is rejected). `--title` / `--version` populate the OpenAPI `info` block (defaults: workspace dir name + `1.0.0`).

## Failure modes summary

| Failure | Behavior |
|---|---|
| Missing canonical `A61_anchor_map.csv` (and `--input` not given) | Exit 2, message "Stage 6 not promoted" |
| Malformed A61 CSV | Exit 2, line/column-localized error |
| Anchor with non-path-shaped `ElementID` | Skipped from YAML; recorded in `unmapped_anchors` |
| Output dir explicit + missing | Exit 2 (mirrors v1.2.19 patcher R1-FIX-1) |
| Output dir implicit + missing | Permissive: created on demand |
| `--title` / `--version` containing shell metacharacters | Stored verbatim in YAML; no shell snippet emitted by this exporter (no operator-pasteable command surface) |
| `ElementID` containing literal `..` | Rejected by `_TRAVERSAL_HINT` regex; recorded in `unmapped_anchors` with reason `element_id_path_traversal` |
| `ElementID` containing percent-encoding (any depth: `%2e`, `%252e`, `%25252e`, etc.) | Rejected by the path-shape regex (`%` is not in the character class); recorded with reason `element_id_not_path_shaped`. R2 design: atomic regex-level reject closes the recursive-decode attack surface without iterative decode passes |
| `ElementID` with malformed OpenAPI template (`/users/{id`, `/users/{}`, `/users/}{`, `/users/{{id}}`) | Rejected by the brace-balance scan; recorded with reason `element_id_not_path_shaped` |

## Cross-references

- Sibling exporters (planned): `skills/asyncapi-from-context/` (v1.3.1), `skills/proto-from-context/` (v1.3.2).
- Producer: `skills/bsa-contract-builder/SKILL.md` (Stage 6 outputs).
- Adjacent: `skills/bsa-handoff-packager/references/handoff-contract.md` (H1-H4 packets sit alongside under `analysis/handoff/`).
- Governance: `governance/immutable_invariants.md` INV-02 (single-writer canonical — exporter never writes `analysis/canonical/`), INV-03 (no new claims — exporter only references existing A61 anchors).
- Base schema: `governance/schemas/sidecar_anchor_manifest.base.schema.json` (the OpenAPI manifest extends the same common base every sidecar manifest extends, even though OpenAPI itself is an exporter, not a sidecar — reusing the shape keeps downstream tooling uniform).
