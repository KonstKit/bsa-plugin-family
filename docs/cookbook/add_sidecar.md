# Cookbook: Add a New Sidecar

Step-by-step recipe for shipping a new diagram sidecar (mirrors v1.0 c4-plantuml / v1.0 camunda-bpmn / v1.2.11 dbml). Use this when adding a new derived-view format that consumes A61 anchors and emits diagram source under `analysis/views/<format>/`.

**Estimated effort:** 1-2 weeks + 2-4 Codex review rounds.

**Prerequisites:** read `docs/sidecar_inventory.md` and `docs/CONTRIBUTING.md` (esp. lessons #1, #4-5).

## Sidecar vs exporter — pick the right shape

| Aspect | Sidecar (this cookbook) | Stage 6 contract exporter (`add_contract_exporter.md`) |
|---|---|---|
| Output location | `analysis/views/<format>/` (NON-canonical, NON-handoff) | `analysis/handoff/contracts/<format>/` (operator deliverable) |
| Audience | Analyst navigation aid | Downstream consumers (codegen, schema registries) |
| Validation | F5-boundary discipline (anchor manifest required when adjacent to `analysis/`) | Operator-side via spec-tool CLI (e.g., `protoc`) |
| Registered in | `config/sidecar_registry.yaml` (with status = `experimental` / `stable`) | NOT registered (operator-driven exporter) |
| Detection mode | Orchestrated (anchor manifest required) OR standalone (`--standalone` flag) | Standalone only (no orchestrator dispatch) |

**Pick sidecar when:** the format is a navigation aid for analysts (visual diagram during review).
**Pick exporter when:** the format is a deliverable for downstream tooling (gRPC stubs, REST clients, event-broker registries).

## Decision matrix (lock before writing code)

| Decision | Default | Notes |
|---|---|---|
| Skill (canon-bumping) or script? | **Skill** with full SKILL.md + integration-contract.md + anchor_manifest.schema.json | All 3 sidecars are skills. Scripts inside `skills/<format>-from-context/scripts/` may exist for validation/rendering. |
| Status at ship | `experimental` (mirror v1.2.11 dbml) | Promote to `stable` after 1-2 cycles of operator use. |
| Validator? | **Yes**, even minimal — validate F5-boundary discipline (manifest adjacency check) | Mirror `skills/c4-plantuml-from-context/scripts/validate_<format>.py`. |
| Anchor manifest schema | Draft 2020-12, extends `governance/schemas/sidecar_anchor_manifest.base.schema.json` | Same as exporters. |
| `view_element_kind` enum | Per-format kinds (e.g., for sequence diagram: `Lifeline`, `Message`, `Fragment`, `Note`) | Document reserved-for-future kinds explicitly. |

## File scaffold

```
skills/<format>-from-context/
├── SKILL.md                              # Sidecar description + operating modes
├── references/
│   ├── integration-contract.md           # Full input/output/F5-boundary contract
│   ├── anchor_manifest.schema.json       # Draft 2020-12 manifest schema
│   └── <format>-syntax.md                # Brief syntax reference for the format (helpful)
└── scripts/
    ├── validate_<format>.py              # Minimal validator (F5-boundary check at minimum)
    └── test_validate_<format>.py         # Validator tests
config/
└── sidecar_registry.yaml                 # +1 entry: status=experimental, integration-contract path
fixtures/golden/project_0004_sidecar_e2e/
└── expected_outputs/views/<format>/      # Sample output for fixture e2e
    ├── <sample>.<ext>                    # Diagram source
    └── anchor_manifest.json              # With anchor_map entries
```

## Step-by-step

### 1. Pre-flight (~30 min)

```bash
# Read all 3 existing sidecars + inventory:
cat docs/sidecar_inventory.md
cat skills/c4-plantuml-from-context/SKILL.md
cat skills/camunda-bpmn-from-context/SKILL.md
cat skills/dbml-from-context/SKILL.md  # Most recent (v1.2.11), cleanest reference

# Read the format spec to understand element types you'll declare in view_element_kind enum.
```

### 2. Write SKILL.md (~30 min)

Mirror `skills/dbml-from-context/SKILL.md`. Sections:
- Frontmatter
- One-paragraph what-the-sidecar-renders intro
- "Operating modes" — Orchestrated + Standalone (with detection heuristic)
- "Detection heuristic" — when the skill refuses to emit (the F5-boundary rule)
- "Validator" — pointer to scripts/validate_<format>.py
- "Optional dependencies" — external tools the operator may need (e.g., `plantuml` CLI, `bpmn-js`, `dbdiagram.io`)

### 3. Write `references/integration-contract.md` (~30 min)

Mirror `skills/dbml-from-context/references/integration-contract.md`. Sections:
- "Status" — experimental / stable
- "Inputs" — A61 anchor map + format-specific narrative input (if any)
- "Outputs" — adjacent files (`<sample>.<ext>` + `anchor_manifest.json`)
- "Detection heuristic" — exact path-substring rule (e.g., "any path containing `analysis/` requires adjacent anchor_manifest.json")
- "Anchor manifest mapping" — convention for `view_element_id` per element kind
- "F5 boundary" — non-canonical, derived-only, sidecar failure does NOT block pipeline promotion
- "Cross-references"

### 4. Write `references/anchor_manifest.schema.json` (~20 min)

Same shape as exporter manifest schemas. Per-format discriminators:
- `sidecar` const: `<format>-from-context`
- `path` pattern: `\.<ext>$` (e.g., `\.puml$`, `\.bpmn$`, `\.dbml$`)
- `format` const: `<format>` (e.g., `c4-plantuml`, `bpmn-2.0`, `dbml`)
- `view_element_kind` enum: per-format kinds
- Minimal `unmapped_anchors` (sidecars typically don't have it — anchor mapping is operator-curated)

### 5. Write `scripts/validate_<format>.py` (~3-5 hours)

Minimal validator (mirror v1.2.11 dbml validator's first iteration):
- Validate the format's syntax (parse-level check)
- Validate the F5-boundary discipline (manifest adjacency check)
- Optional: deeper validation (type correctness, FK target resolution — added in v1.2.15 for dbml)

CLI:
```python
parser.add_argument("input", type=Path, help="Path to <ext> file")
parser.add_argument("--lenient-types", action="store_true", help="Skip type-correctness check (preserve pre-deep-validator behavior)")
parser.add_argument("--quiet", action="store_true")
```

Apply self-review lessons:
- **Lesson #1** (impact analysis): if you're parsing a format with a long history (proto, BPMN), check what real-world variants exist
- **Lesson #4** (layer overlap): your validator should NOT duplicate F5 hook logic; the F5 hook handles canonical writes, your validator handles the sidecar's own non-canonical output
- **Lesson #5** (reach equality): if your validator's regex/check mirrors a schema or spec doc, verify them character-by-character

### 6. Write `scripts/test_validate_<format>.py` (~3-5 hours)

Test buckets (target 30-60 tests):
- **Parser** (10-15 tests): valid syntax variants + invalid syntax variants per element kind
- **F5-boundary detection** (3-5 tests): adjacent manifest required when in `analysis/`; standalone mode bypasses
- **Type correctness** (10-20 tests if applicable): per-type valid/invalid
- **CLI** (5-7 tests): standard surface

### 7. Update `config/sidecar_registry.yaml` (~5 min)

The registry has a 7-check lint contract (`scripts/sidecar_registry_lint.py`) — read the file's own header for the full schema. Required fields per entry: `name`, `output_format`, `f5_path_prefix`, `integration_contract`, `anchor_manifest_schema`, `status`, `added_in`, `summary` (plus optional `optional_dependencies`).

Add an entry mirroring the existing dbml entry:
```yaml
- name: <format>-from-context              # MUST match skills/<name>/ dir (C1)
  output_format: "<Human-readable, e.g., 'PlantUML .puml'>"
  f5_path_prefix: analysis/views/<format>/  # MUST NOT overlap any POLICY_GLOBS path (C4)
  integration_contract: skills/<format>-from-context/references/integration-contract.md  # MUST exist (C2)
  anchor_manifest_schema: skills/<format>-from-context/references/anchor_manifest.schema.json  # MUST exist + match base shape (C3)
  optional_dependencies: ["<external CLI / lib that operator may install>"]  # OPTIONAL list
  status: experimental                      # MUST be one of {stable, beta, experimental} (C7)
  added_in: vX.Y.Z                          # The plugin version where this sidecar first ships
  summary: "One-line operator-facing description."
```

Run `python3 -m pytest tests/test_sidecar_registry.py` to verify all 7 checks pass.

### 8. Extend fixture `project_0004_sidecar_e2e` (~1-2 hours)

Add sample diagrams + anchor manifest for the new format under `fixtures/golden/project_0004_sidecar_e2e/expected_outputs/views/<format>/`.

The `tests/test_sidecar_e2e_fixture.py` test suite picks up new sidecars automatically if you follow the directory convention.

### 9. Update `scripts/compute_canon_hash.py` POLICY_GLOBS (~5 min)

Add 3 entries alphabetically:
```python
"skills/<format>-from-context/SKILL.md",
"skills/<format>-from-context/references/integration-contract.md",
"skills/<format>-from-context/references/anchor_manifest.schema.json",
```

### 10. Recompute canon hash + bump manifest + 5 fixture metadata files (~10 min)

Same as exporter cookbook step 8.

### 11. Update CHANGELOG + RELEASING + sidecar_inventory.md (~30 min)

CHANGELOG: mirror v1.2.11 dbml entry shape. Emphasize derived-only, F5-boundary discipline, status (experimental).
RELEASING: one new table row.
sidecar_inventory.md: add row to the "At a glance" table + new section per the existing pattern.

### 12. Pre-Codex self-review + Codex loop (~2-4 rounds)

Sidecar reviews typically need 2-3 rounds. Common findings:
- Validator strictness mismatch (overly permissive accepts invalid format syntax)
- F5-boundary detection regex covers wrong path patterns
- Manifest schema misses an element kind the format actually has

### 13. Final commit + tag (~5 min)

```bash
git add -A
git commit -F /tmp/release_msg.txt
git tag -a vX.Y.Z -F /tmp/tag_msg.txt
```

## Common pitfalls

- **Forgetting that integration-contract.md is in POLICY_GLOBS.** Editing it is canon-bumping; you MUST bump the manifest. Caught v1.2.11 (turned an expected canon-neutral release into a canon-bump).
- **Validator parsing in multiple passes.** v1.2.15 lesson: prefer one parser call returning a tuple `(elements, refs, warnings)` over re-scanning. Closes a class of false-positives.
- **Quote-blind depth tracker.** Triple-quoted strings or escape-aware quoting needs a manual scanner that strips quoted regions BEFORE the depth check. v1.2.15 dbml caught this.
- **F5-boundary regex too narrow or too broad.** Test with paths inside `analysis/`, paths inside `analysis/canonical/`, paths outside `analysis/` entirely, paths with `--standalone` flag.
- **Sidecar registry entry forgotten.** Without `config/sidecar_registry.yaml` entry, orchestrator won't dispatch to the sidecar.

## Cross-references

- `skills/c4-plantuml-from-context/` — v1.0 (oldest reference, includes Rel-relationship convention)
- `skills/camunda-bpmn-from-context/` — v1.0 (most extensive — 14 test modules + 12 production scripts; Camunda 7/8 extensions)
- `skills/dbml-from-context/` — v1.2.11 (cleanest recent reference; v1.2.15 added deep validator)
- `docs/sidecar_inventory.md` — At-a-glance comparison table
- `governance/schemas/sidecar_anchor_manifest.base.schema.json` — Manifest base schema
- `config/sidecar_registry.yaml` — Sidecar status registry
- `docs/CONTRIBUTING.md` — 15 self-review lessons
