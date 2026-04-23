# Sidecar Inventory

Operator-facing summary of the two diagram sidecars shipped with the BSA plugin family. Both are **derived-only, non-canonical**: their output never feeds back into the claim layer, and sidecar failures don't block pipeline promotion. v1.1.12 (Section I) — codifies the inventory + adds F5-boundary regression tests pinning the non-canonical-path discipline.

## At a glance

| Sidecar | Output format | Status | F5 boundary | Tests |
|---|---|---|---|---|
| `c4-plantuml-from-context` | PlantUML `.puml` (C4 model) | Stable | `analysis/views/c4/` (NON-canonical) | 1 validator + ~70 unit tests |
| `camunda-bpmn-from-context` | BPMN 2.0 XML `.bpmn` | Stable + Camunda-aware | `analysis/views/bpmn/` (NON-canonical) | 14 test modules + 12 production scripts, layout policy + engine smoke |

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

## F5 boundary

Both sidecars write to `analysis/views/<sidecar>/` paths, which are **explicitly outside the F5 single-writer canonical-path set**:

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
- **End-to-end test fixture** that exercises an orchestrated sidecar invocation against a `project_NNNN/` happy-path fixture. Today the sidecars are tested in isolation; a full-pipeline-with-sidecar test would catch orchestrator integration drift.
- **DBML / sequence-diagram sidecars** — third / fourth sidecars to round out the diagram coverage.
