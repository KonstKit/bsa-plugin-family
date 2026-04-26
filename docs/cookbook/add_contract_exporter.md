# Cookbook: Add a New Contract Exporter

Step-by-step recipe for shipping a new Stage 6 contract exporter (mirrors v1.3.0 OpenAPI / v1.3.1 AsyncAPI / v1.3.2 proto). Use this when bridging the BSA Stage 6 contract layer (A61 anchor map) to a new specification format.

**Estimated effort:** 1-3 days (depending on spec complexity) + 2-5 Codex review rounds.

**Prerequisites:** read `docs/CONTRIBUTING.md` (esp. lessons #8, #11-15) and at least one existing exporter end-to-end (`skills/openapi-from-context/` is the cleanest reference).

## Decision matrix (lock before writing code)

| Decision | Default | Notes |
|---|---|---|
| Skill (canon-bumping) or script (canon-neutral)? | **Skill**, mirroring v1.3.0/1/2 | Stage 6 exporters live as skills with full SKILL.md + integration-contract.md + anchor_manifest.schema.json (all 3 in POLICY_GLOBS). Pure-script alternative is for operator-tooling without contract semantics. |
| Spec version | Latest stable major (e.g., proto3 not proto2) | Document deferral of older versions in SKILL "Out of scope". |
| Output filename | Single-file convention `<format-noun>.<ext>` (api.yaml / asyncapi.yaml / services.proto) | Symmetric with existing exporters. |
| Default rpc/operation direction | Per-format default (OpenAPI: GET; AsyncAPI: send; proto: unary) | Operator changes post-export. The skeleton can't infer from A61 alone. |
| ElementID dialect | path-style `^/[A-Za-z0-9_/{}.~-]*$` (mirror v1.3.0/1/2) | Dot-style addresses deferred to a later vN.x patch. |
| Parameter-name charset | **Re-derived from target spec's grammar** (lesson #14 — do NOT copy from sibling exporter) | OpenAPI: per RFC 3986. AsyncAPI: per AsyncAPI Parameter Object. proto3: per proto3 ident. |

## File scaffold

```
skills/<format>-from-context/
├── SKILL.md                              # Operator-driven exporter description
├── references/
│   ├── integration-contract.md           # Full input/output/CLI/failure-mode contract
│   └── anchor_manifest.schema.json       # Draft 2020-12 manifest schema
└── scripts/
    ├── generate_<format>.py              # CLI entry + render
    └── test_generate_<format>.py         # ~50-100 tests
```

All 5 files are required for canon-bumping discipline. Mirror exact layout of v1.3.2 proto exporter (most recent reference).

## Step-by-step

### 1. Pre-flight (~30 min)

```bash
# Confirm no existing skill with this name:
ls skills/ | grep -i <format>

# Read the canonical reference exporter end-to-end:
cat skills/openapi-from-context/SKILL.md
cat skills/openapi-from-context/references/integration-contract.md
cat skills/openapi-from-context/scripts/generate_openapi.py

# Read the target spec's reference page for the exact element being emitted.
# Lesson #12: identify ALL required sub-fields per element kind BEFORE writing code.
# Example for OpenAPI Path Item: paths/<path>/{get,post,...} needs `responses`.
# Example for AsyncAPI Channel: channels/<key> needs `parameters` for templates.
# Example for proto3 Service: needs `syntax = "proto3";` declaration first.
```

### 2. Write SKILL.md (~30 min)

Mirror `skills/openapi-from-context/SKILL.md`. Sections (in order):
- Frontmatter `name:` + `description:`
- One-paragraph what-it-bridges intro
- "Operating mode" — operator-runner only
- "Scope (vN.x — skeleton)" with **In scope** + **Out of scope** subsections
- "Why an exporter, not a sidecar" — paste from v1.3.0
- "Workflow (operator)" — 5-6 numbered steps
- "Cross-references" pointing at sibling exporters + producer + governance

### 3. Write `references/integration-contract.md` (~30 min)

Mirror `skills/openapi-from-context/references/integration-contract.md`. Sections:
- "Status + Ownership" — operator-driven, output ownership, validation binding
- "Inputs" — required + optional + out-of-scope
- "Outputs" — sample shape of the spec file + manifest
- "Validation rules" — top-level shape + version pin + no-crash invariant
- "Gate behavior" — non-blocking + never-list (no git, no canonical writes, no shell-out)
- "CLI" — full surface
- "Failure modes summary" — table of (failure → behavior)
- "Cross-references"

### 4. Write `references/anchor_manifest.schema.json` (~20 min)

Draft 2020-12. Extends `governance/schemas/sidecar_anchor_manifest.base.schema.json`. Per-format discriminators:
- `sidecar` const: `<format>-from-context`
- `path` pattern: `\.<ext>$`
- `format` const: spec-version-with-format (`openapi-3.1`, `asyncapi-3.0`, `proto3`)
- `view_element_kind` enum: per-spec elements (e.g., `Service`, `Rpc`, `Message`, `Enum` for proto)
- `unmapped_anchors[].reason` enum: `non_contract_anchor_class` + `element_id_not_path_shaped` + `element_id_path_traversal` + format-specific (e.g., `proto_identifier_synthesis_failed`, `duplicate_<unit>_collision`)
- `view_element_id` constraint: tight regex matching the actual emitted shape (lesson #15 — schema must enforce what code produces)

### 5. Write `scripts/generate_<format>.py` (~3-6 hours)

Module-level constants block (mirror v1.3.2):
```python
DEFAULT_INPUT_REL = "analysis/canonical/stage6/A61_anchor_map.csv"
DEFAULT_OUTPUT_REL = "analysis/handoff/contracts/<format>"
DEFAULT_<FORMAT>_FILENAME = "<spec-noun>.<ext>"
DEFAULT_MANIFEST_FILENAME = "anchor_manifest.json"

A61_REQUIRED_COLS = {"AnchorID", "AnchorClass", "ElementType", "ElementID", "ClaimID", "A51Ref"}

_PATH_SHAPE = re.compile(r"^/[A-Za-z0-9_/{}.~-]*$")  # identical to v1.3.0/1/2
_TRAVERSAL_HINT = re.compile(r"\.\.")
_ANCHOR_ID_PATTERN = re.compile(r"^ANC-[A-Z0-9_-]+$")
_PARAM_NAME_CHARSET = re.compile(<TARGET-SPEC GRAMMAR>)  # lesson #14 — re-derive!
```

Function structure (mirror v1.3.2):
- `_read_a61_rows(path)` — defensive CSV read
- `_classify_anchor(row)` — gates: bad_anchor_id / non_contract / traversal / shape (with brace-balance + charset check)
- `_synthesize_<unit>(...)` — format-specific synthesis from ElementID (if needed; e.g., proto's service+method synthesis)
- `_read_plugin_canon_version()` — for manifest's `canon_policy_version` field
- `build_bundle(rows, *, ...)` — main builder, returns (spec_doc, manifest_doc)
- `_render_<format>(doc)` — text serialization (yaml/json/text)
- `_atomic_write(path, body)` — tempfile + os.replace
- `_atomic_write_json(path, doc)` — same with json.dumps
- `_is_relative_to(path, base)` — Python <3.9 fallback
- `main(argv)` — CLI

CLI surface (mandatory):
```python
parser.add_argument("--workspace", type=Path, default=Path.cwd())
parser.add_argument("--input", type=Path, default=None)  # bypasses analysis/ guard
parser.add_argument("--output-dir", type=Path, default=None)  # implicit-permissive / explicit-rejected
parser.add_argument("--print-only", action="store_true")  # JSON manifest to stdout, NO writes
parser.add_argument("--quiet", action="store_true")
# Plus format-specific: --title, --version, --package, etc.
```

Apply ALL 15 self-review lessons (see `docs/CONTRIBUTING.md`):
- Lesson #8 (untrusted input as path component): validate AnchorID with `_ANCHOR_ID_PATTERN.fullmatch()` BEFORE filename construction
- Lesson #9 (exception after side-effect): `_is_relative_to` BEFORE the write loop
- Lesson #11 + #12 (shell-quote + leading-hyphen): N/A unless you render `git apply`-style commands
- Lesson #13 (atomic gate): `%` rejected at regex level, NOT via recursive unquote
- Lesson #14 (ASCII shape + structural validation): brace-balance scan after shape regex when admitting `{...}` templates
- Lesson #15 (untrusted-input-from-files): if you read JSON/YAML and use a value as path component, validate with explicit regex

### 6. Write `scripts/test_generate_<format>.py` (~3-5 hours)

Mirror `skills/openapi-from-context/scripts/test_generate_openapi.py`. Test buckets (target ~50-100 tests total):
- **Pure unit `_classify_anchor`** (10-15 tests): every gate's pass + reject paths
- **Pure unit synthesis** (8-12 tests, if applicable): every synthesis success + failure mode
- **`_read_a61_rows`** (3 tests): missing file / missing required columns / well-formed
- **`build_bundle`** (10-15 tests): empty / happy path / mixed skips routed to unmapped / dedup / silent-drop bad anchor IDs
- **Manifest schema conformance** (5-7 tests): validates well-formed + empty + pins all enum/literal/pattern constraints
- **Spec rendering** (4-7 tests): minimal-valid shape + per-element required fields present + deterministic ordering
- **Path-shape regex hardening** (8-10 tests, lessons #13+#14): URL-encoded traversal (lowercase / uppercase / double / triple) + truncated `%` + invalid hex + ANY `%` + null byte + Unicode digits
- **Brace-balance scan + charset** (6-9 tests, lesson #14 + #12): unbalanced / empty / misordered / nested / charset rejects
- **CLI** (8-12 tests): uninit workspace / missing A61 / --print-only no writes / writes both files / --input bypass / --output-dir variants / format-specific flags
- **Safety boundary** (3 tests): script source NEVER imports subprocess / no `.tmp` leftovers / canonical state unchanged
- **Idempotency** (1 test): same input → byte-identical output

### 7. Update `scripts/compute_canon_hash.py` POLICY_GLOBS (~5 min)

Add 3 entries alphabetically:
```python
POLICY_GLOBS: tuple[str, ...] = (
    ...
    "skills/<format>-from-context/SKILL.md",  # alphabetic position
    ...
    "skills/<format>-from-context/references/integration-contract.md",  # alphabetic
    "skills/<format>-from-context/references/anchor_manifest.schema.json",
    ...
)
```

### 8. Recompute canon hash + bump manifest (~10 min)

```bash
python3 scripts/compute_canon_hash.py
# Capture the new hex digest. Update .claude-plugin/plugin.json:
# - version: bump (1.3.X → 1.3.X+1 for sequential exporters)
# - canonPolicyVersion.semver: same as version
# - canonPolicyVersion.hash_prefix: first 8 chars of new digest
# - canonPolicyVersion.hash_full: full 64-char digest
# - canonPolicyVersion.computed_at: ISO 8601 UTC
```

Then bump 5 fixture metadata files in lockstep:
```bash
NEW_HASH=<8char>
NEW_VER=1.3.X
sed -i '' "s|\"<old_ver>+hash:<old_hash>\"|\"${NEW_VER}+hash:${NEW_HASH}\"|g" \
    fixtures/golden/project_0004_sidecar_e2e/fixture_metadata.json \
    fixtures/golden/project_0004_sidecar_e2e/expected_outputs/views/{bpmn,c4,dbml}/anchor_manifest.json
sed -i '' "s|\"canon_policy_version_hash\": \"<old_hash>\"|\"canon_policy_version_hash\": \"${NEW_HASH}\"|g" \
    fixtures/golden/project_0004_sidecar_e2e/expected_markers/stage1.excerpts.merged.json
sed -i '' "s|\"plugin_version\": \"<old_ver>\"|\"plugin_version\": \"${NEW_VER}\"|g" \
    fixtures/golden/project_0004_sidecar_e2e/fixture_metadata.json
```

Verify:
```bash
python3 -m pytest tests/test_plugin_manifest.py -x
```

### 9. Update CHANGELOG.md + docs/RELEASING.md (~30 min)

Mirror v1.3.2 entry shape:
- R0 narrative paragraph (what bridges, key design choices, never-list)
- "Tag target" + "Canon policy version" line
- "Added" subsection (5 new files + N tests bullet list)
- "Updated" subsection (POLICY_GLOBS + fixture metadata)
- "Result" subsection (test count delta + canon hash + privacy/lint/fixture pass)
- "Self-review applied" subsection (which lessons hit)
- "Codex review" subsection (placeholder for round entries)

RELEASING.md: one new table row in the historical examples list.

### 10. Pre-Codex self-review (~30 min)

Run the 15-lesson checklist explicitly (`docs/CONTRIBUTING.md`). Fix every gap BEFORE invoking Codex. Skipping this cost 5+ Codex round cascades historically.

Then run:
```bash
python3 -m pytest skills/<format>-from-context/scripts/test_generate_<format>.py -v
python3 -m pytest tests/test_plugin_manifest.py
python3 scripts/privacy_scan.py
python3 scripts/phase_7_lint.py
python3 scripts/fixture_runner.py
```

All must be green before Codex.

### 11. Codex review loop (~2-5 rounds)

Per `docs/CONTRIBUTING.md` "Codex review workflow" section. Use the 7-section prompt format. Expect:
- R1: 1-3 MAJOR + N MINOR findings (most-likely classes: spec-required-field misses, gate-vs-extractor charset mismatch, doc drift in CHANGELOG/RELEASING)
- R2: 0-1 MAJOR + N MINOR (post-fix doc drift)
- R3: APPROVE if discipline held

If R3 still REQUEST CHANGES: probably hit a domain gotcha not in the 15 lessons. Add it as lesson #16 to `feedback_self_review_before_codex.md`.

### 12. Final commit + tag (~5 min)

```bash
git add -A
git commit -F /tmp/release_msg.txt
git tag -a vX.Y.Z -F /tmp/tag_msg.txt
# NO PUSH (per release workflow — local-only repo).
```

## Common pitfalls (anti-patterns from v1.3.0-1.3.2 retros)

- **Copying parameter charset from sibling exporter** (lesson #14). Each format's grammar is different. v1.3.2 R1 caught this.
- **Missing `parameters` block for templated channel addresses** (lesson #12 / AsyncAPI Channel Object spec requirement). v1.3.1 R1 caught this.
- **Permissive shape regex without structural validation** (lesson #14). v1.3.0 R1 caught: `{` and `}` in regex character class without balanced-brace scan. Fix: add a brace-balance scan after the shape regex.
- **Recursive `urllib.parse.unquote` for traversal defense** (lesson #13). Pre-R2 v1.3.0 fix used 2-pass decode; triple-encoded survived. Atomic regex-level `%` rejection closes the entire encoding-depth attack class.
- **`view_element_id` schema only `minLength: 1`** (lesson #15-extension). Constraint should match the actual emitted identifier shape (e.g., `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$` for `Service` or `Service.Method`). v1.3.2 R1 caught this.
- **Forgetting to update CHANGELOG inventory list after replacing/inverting a test** (lesson #6). Post-refactor grep ALL release-narrative surfaces. v1.3.2 R2 hit this 3x.

## Cross-references

- `skills/openapi-from-context/` — v1.3.0 (cleanest reference; established the pattern)
- `skills/asyncapi-from-context/` — v1.3.1 (Channel Object `parameters` lesson)
- `skills/proto-from-context/` — v1.3.2 (synthesis pass + per-spec charset re-derivation)
- `docs/CONTRIBUTING.md` — 15 self-review lessons + Codex workflow
- `docs/RELEASING.md` — release procedure + canon-bump checklist
- `governance/schemas/sidecar_anchor_manifest.base.schema.json` — manifest base schema
