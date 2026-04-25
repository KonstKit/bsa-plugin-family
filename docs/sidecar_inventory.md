# Sidecar Inventory

Operator-facing summary of the diagram sidecars shipped with the BSA plugin family. All are **derived-only, non-canonical**: their output never feeds back into the claim layer, and sidecar failures don't block pipeline promotion. v1.1.12 (Section I) — codifies the inventory + adds F5-boundary regression tests pinning the non-canonical-path discipline. v1.2.11 adds the third sidecar (`dbml-from-context`, status=experimental).

## At a glance

| Sidecar | Output format | Status | F5 boundary | Tests |
|---|---|---|---|---|
| `c4-plantuml-from-context` | PlantUML `.puml` (C4 model) | Stable | `analysis/views/c4/` (NON-canonical) | 1 validator + ~70 unit tests |
| `camunda-bpmn-from-context` | BPMN 2.0 XML `.bpmn` | Stable + Camunda-aware | `analysis/views/bpmn/` (NON-canonical) | 14 test modules + 12 production scripts, layout policy + engine smoke |
| `dbml-from-context` | DBML `.dbml` (relational-schema text) | Experimental (v1.2.11) | `analysis/views/dbml/` (NON-canonical) | 1 minimal validator + 17 unit tests |

## c4-plantuml-from-context

**Skill:** `skills/c4-plantuml-from-context/SKILL.md`.
**What it does:** generates C4 model diagrams (system context / container / component / dynamic / deployment / system landscape) as PlantUML/C4-PlantUML source from architecture notes, ADRs, codebase context, screenshots, whiteboards.

**Operating modes (per `references/integration-contract.md`):**

- **Orchestrated** — invoked by `bsa-orchestrator` as a derived view aid. Every emitted `.puml` MUST have an adjacent `analysis/views/c4/anchor_manifest.json` mapping each `view_element_id` to a canonical `A61.AnchorID`. Unmapped view elements are treated as fabrications (route via `A51` rather than editing the diagram).
- **Standalone** — invoked directly outside a BSA pipeline. No anchor manifest required; the emitted `.puml` is informational only and carries no BSA governance weight.

**Detection heuristic:** if a `.puml` file is generated under any path containing `analysis/` but no `anchor_manifest.json` is adjacent, the skill refuses to emit — it either asks for the missing manifest (orchestrated intent) or requires explicit `--standalone` confirmation.

**Validator:** `skills/c4-plantuml-from-context/scripts/validate_c4_plantuml.py` — checks the C4-PlantUML include matrix, macro syntax, and layout rules. Optional `--plantuml on` mode adds a syntax-check pass via the `plantuml` CLI when installed. Anchor-manifest mapping is enforced by the orchestrator's promotion contract (per `references/integration-contract.md`), not by this validator. Run via `python3 skills/c4-plantuml-from-context/scripts/validate_c4_plantuml.py <file.puml>`.

**Optional dependencies:** `plantuml` CLI for `--plantuml on` mode (renders + lints). Skill prints a graceful-degradation message and skips the render step when missing.

## camunda-bpmn-from-context

**Skill:** `skills/camunda-bpmn-from-context/SKILL.md`.
**What it does:** generates BPMN 2.0 XML (with documented Camunda 7/8 extension support) from process notes, transcripts, workshop output. Supports greenfield generation, review/fix workflows, and preserve-only constructs per the support matrix.

**Operating modes:** mirror the c4 sidecar (orchestrated vs standalone). Anchor manifest path: `analysis/views/bpmn/anchor_manifest.json`.

**Bundled tooling (14 test modules + 12 production scripts under `skills/camunda-bpmn-from-context/scripts/`):**

- `validate_governance_docs.py` — governance-doc compliance check.
- `validate_run_manifest.py` — per-run manifest validation.
- `semantic_validate_bpmn.py` — semantic-level BPMN check (structural + Camunda extension fidelity).
- `apply_bpmn_layout_policy.py` — auto-layout post-processing.
- `engine_smoke_bpmn.py` + `engine_smoke_matrix.py` — engine-level import smoke (Camunda 7 / 8).
- `simple_mode_bridge.py` — simple-mode entry / fallback.
- `backend_selector.py` — deterministic backend selection per `references/selector_decision_table.md`.
- `claim_guardrail.py` — preserve-only construct guardrail.
- `make_stripped_fixture.py` — fixture preparation helper.
- `build_preview_artifacts.py` — operator-side preview helper.
- `run_bpmn_pipeline.py` — end-to-end pipeline runner.

**Reference doc set (21 references under `skills/camunda-bpmn-from-context/references/`):** integration contract, intake & questions, modeling conventions, support matrix, traceability contract + table template, review mode, layout policy, simple mode, selector decision table, selector reason codes, acceptance fixtures, release phases, FR coverage map, engine smoke hooks, deployment readiness, plus operator-facing supplements. Run `ls skills/camunda-bpmn-from-context/references/` for the full set.

**Optional dependencies:**
- `xmllint` for BPMN syntax validation (graceful degradation when missing).
- `playwright` (under `skills/camunda-bpmn-from-context/node_tooling/`) for preview rendering — operator-installed.

## dbml-from-context

**Skill:** `skills/dbml-from-context/SKILL.md` (added in v1.2.11; status: experimental).
**What it does:** generates DBML (Database Markup Language — a compact textual format for relational schemas) from data-model notes, existing SQL DDL, ORM model files, stakeholder interviews about entity semantics. Sits at the data-persistence layer, orthogonal to the c4-plantuml-from-context architectural sidecar and the camunda-bpmn-from-context process sidecar.

**Operating modes** (mirror c4 + bpmn): orchestrated mode emits `analysis/views/dbml/anchor_manifest.json` alongside every `.dbml` file, mapping tables / columns / refs / enums / table-groups to canonical `A61.AnchorID` rows. Standalone mode emits the `.dbml` with no manifest.

**`view_element_id` convention** (per `references/integration-contract.md`):
- Tables: bare name (`users`).
- Columns: `<table>.<column>` (`users.id`).
- Refs: `ref_<from_table>_<from_col>_to_<to_table>_<to_col>` (`ref_orders_user_id_to_users_id`).
- Enums + TableGroups: bare name.

**Validator:** `skills/dbml-from-context/scripts/validate_dbml.py` — v1.2.15 deep implementation. Checks balanced braces, non-empty block bodies, top-level Ref statement shape, inline `[ref: ...]` shape, AND (v1.2.15) type-catalog enforcement (DBML/SQL base types + parameterized forms + Enum-typed columns) AND FK target resolution (every Ref must point at an existing `<table>.<column>`). The `--lenient-types` flag preserves pre-v1.2.15 permissive type behavior for legacy `.dbml` using custom domain types; FK resolution is unconditional.

**Optional dependencies:** `@dbml/cli` for local rendering (`dbml2svg`). Graceful degradation when missing.

**Reference doc set** (3 references under `skills/dbml-from-context/references/`): integration contract, anchor manifest schema, DBML syntax pointer.

## F5 boundary

All three sidecars write to `analysis/views/<sidecar>/` paths, which are **explicitly outside the F5 single-writer canonical-path set**:

```
F5 canonical paths (single-writer enforced):       Sidecar paths (writer-agnostic):
  analysis/canonical/**                              analysis/views/c4/**
  analysis/discovery/canonical/**                    analysis/views/bpmn/**
  analysis/runtime/ready/**                          (sidecar output never under canonical/)
  analysis/discovery/runtime/ready/**
  analysis/handoff/backlog_export_*.{json,csv}       (since v1.1.4-v1.1.6 — backlog exports
  analysis/handoff/live_api_response_*.json            and live-API state)
```

This is by design: sidecars are derived-only, so their output should not require orchestrator-only write permissions. Operators (or any worker skill) can write to `analysis/views/`. The sidecars' anchor manifests carry the BSA-governance linkage instead of single-writer enforcement.

Regression tests: `tests/test_sidecar_f5_boundary.py` (added v1.1.12) pins this discipline by asserting the F5 dispatcher does NOT match `analysis/views/<sidecar>/...` paths.

## Operator-side usage examples

### c4-plantuml standalone
```bash
# Generate a C4 system-context diagram from a directory of source notes.
# (Sidecar reads context, asks clarifying questions, emits .puml.)
# In Claude Code, invoke the skill via the standard slash-command flow
# or cite it directly when chatting with Claude:
#   "Use the c4-plantuml-from-context skill to draw a C4 system context
#    for the order-deliver subsystem from these ADRs."
# After emission, validate:
python3 skills/c4-plantuml-from-context/scripts/validate_c4_plantuml.py path/to/system-context.puml
# Optional render (requires plantuml CLI):
plantuml -tsvg path/to/system-context.puml
```

### camunda-bpmn standalone
```bash
# Generate a BPMN process from workshop notes.
# Sidecar runs through intake → mode selection → emission → layout policy.
# After emission, validate:
python3 skills/camunda-bpmn-from-context/scripts/semantic_validate_bpmn.py path/to/process.bpmn
# Optional engine smoke (requires Camunda runtime):
python3 skills/camunda-bpmn-from-context/scripts/engine_smoke_bpmn.py path/to/process.bpmn
```

### Orchestrated mode (in a BSA pipeline run)
The orchestrator emits `analysis/views/<sidecar>/anchor_manifest.json` automatically when invoking a sidecar as part of `/bsa-stage 5` or `/bsa-stage 6` (anchor-binding stages). The sidecar then refuses to emit without the manifest, enforcing the orchestrated-mode contract.

## Open follow-ups (post-v1.1.x)

These are out of scope for v1.1.x but tracked here for future planning:

- ~~**Common SidecarConfig schema**~~ — **CLOSED in v1.1.18 (S1)**. Shared base schema lives at `governance/schemas/sidecar_anchor_manifest.base.schema.json`; per-sidecar schemas extend it (verified by `scripts/sidecar_registry_lint.py` C3 check).
- ~~**Sidecar registry** in `config/`~~ — **CLOSED in v1.1.18 (S2)**. `config/sidecar_registry.yaml` lists per-sidecar metadata (name, output format, F5 path prefix, integration contract path, anchor schema path, optional deps, status, added_in version, summary). Lint at `scripts/sidecar_registry_lint.py` enforces 7 checks.
- ~~**End-to-end test fixture**~~ — **CLOSED in v1.2.6 (Sprint 3 / S3).** New fixture at `fixtures/golden/project_0004_sidecar_e2e/` walks the full A61-anchor → sidecar-manifest → view-file cross-product for both stable sidecars (`c4-plantuml-from-context` + `camunda-bpmn-from-context`). 5 C4 anchors + 5 BPMN anchors share a single A61 register; both sidecars' manifests cross-reference back. Companion test at `tests/test_sidecar_e2e_fixture.py` (16 tests) pins: schema validity per sidecar, every manifest a61_anchor_id resolves to A61, every view-element id in the .puml/.bpmn appears in the corresponding manifest's anchor_map, manifest view paths exist on disk, A61 partitions cleanly across sidecars, every A61 row is consumed by some manifest. Three negative-path regression tests pin the cross-ref + schema checks against silent-pass regressions (unmapped anchor / orphan view element / wrong sidecar literal). Live-run sidecar fixture remains a Sprint 4.5+ deliverable (this fixture is hand-authored).
- ~~**DBML sidecar**~~ — **CLOSED in v1.2.11 (status=experimental).** `skills/dbml-from-context/` ships the third sidecar: relational-schema text (tables, columns, refs, enums, table groups) as the data-persistence-layer peer to c4-plantuml-from-context (architecture) and camunda-bpmn-from-context (process). Registry entry at `config/sidecar_registry.yaml`; e2e fixture coverage under `fixtures/golden/project_0004_sidecar_e2e/expected_outputs/views/dbml/`. Status stays `experimental` until a real-pilot validation pass.
- **Sequence-diagram sidecar** — fourth sidecar; remains deferred. The c4-plantuml-from-context sidecar already covers `C4_Dynamic` diagrams for runtime scenarios, so a dedicated sequence-diagram sidecar is lower priority than DBML was; revisit once a real pilot surfaces a case where `C4_Dynamic` is insufficient.
