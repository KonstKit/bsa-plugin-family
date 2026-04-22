# Architecture Overview

High-level view of the BSA plugin family: what's in it, how the pieces fit together, and which invariants hold.

## 23 skills, six roles

| Role | Skill count | Members |
|---|---|---|
| **Main-cycle workers** (produce canonical content) | 9 | `bsa-evidence-intake`, `bsa-claim-binder`, `bsa-context-framer`, `bsa-semantic-extractor`, `bsa-domain-modeler`, `bsa-backbone-builder`, `bsa-contract-builder`, `bsa-handoff-packager`, `bsa-validation-readiness` |
| **Discovery workers** (D1-D5 pre-intake phase) | 5 | `d0-problem-framer`, `d0-context-researcher`, `d0-hypothesis-prioritizer`, `d0-feasibility-assessor`, `d0-synthesis-gatekeeper` |
| **Auditors** (verify + emit gate markers) | 5 | `bsa-citation-auditor`, `bsa-consistency-auditor`, `bsa-anchor-auditor`, `bsa-skeptical-reviewer`, `bsa-no-new-claims-auditor` |
| **Sidecars** (derived-only, non-canonical views) | 2 | `c4-plantuml-from-context`, `camunda-bpmn-from-context` |
| **Orchestrator** | 1 | `bsa-orchestrator` — routes requests, holds promotion lock, emits markers |
| **Meta** | 1 | `inot-prompt-builder` — prompt authoring helper (orthogonal to the main pipeline) |

Total: 9 + 5 + 5 + 2 + 1 + 1 = 23 skill directories under `skills/`.

## Data layers

The pipeline operates on three nested layers, each with strict invariants:

```
  Raw inputs (under analysis/proposals/stage1/inputs/)
      ↓  excerpted
  A58 evidence excerpts (source + locator + verbatim text)
      ↓  bound
  A59 claim register (ClaimType × SourceID+ExcerptID OR A51Ref)
      ↓  aggregated
  A60 negative-evidence register (counter-evidence pointers)
      ↓  contextualized
  A51 issue-route register (unresolved uncertainty / contradiction / missing_source)
      ↓  promoted
  Stage 2-8 derived artifacts (context frame, catalogs, backbone, contracts, audits)
      ↓  packaged
  H1-H4 handoff (exec brief / delivery packet / validation / open items)
```

Source metadata (A50 register) + run context (A48 card) provide cross-cutting provenance.

## Three layers of governance

### Layer 1 — runtime markers

Every pipeline transition emits a marker under `analysis/runtime/ready/` (main cycle) or `analysis/discovery/runtime/ready/` (discovery). File naming follows [runtime-marker-schema.md](../skills/bsa-orchestrator/references/runtime-marker-schema.md): `stage<N>.ready.json` for stage-entry, `stage<N>.<audit>.pass.json` for audit gates, `stage1.excerpts.merged.json` for the Stage 1 intake gate, `handoff.ready.json` and `pipeline.complete.json` at the end. Audit failures do not emit a dedicated `.fail.json` marker — they emit the audit report and halt promotion instead. Each marker carries:

- `marker_id`, `stage`, `verdict`, `timestamp`
- `canon_policy_version` + `canon_policy_version_hash`
- stage-specific fields (KPI values, counts, SCN identifiers)

`scripts/validate_marker_chain.py` confirms the chain is gapless, monotonic, and internally consistent.

### Layer 2 — immutable invariants registry

[governance/immutable_invariants.md](../governance/immutable_invariants.md) enumerates 7 invariants that cannot be relaxed without a **major** CanonPolicyVersion bump:

| ID | Invariant | Enforcement |
|---|---|---|
| INV-01 | Evidence-binding: every positive `direct`/`inference` claim in A59 has SourceID+ExcerptID OR A51Ref (analyst_judgment is scoped to INV-07) | `bsa-citation-auditor`, `fixture_runner.py`, PreToolUse:Bash hook |
| INV-02 | Single-writer canonical: only orchestrator writes under `analysis/canonical/` | PreToolUse:Write hook |
| INV-03 | No new claims in Stage 8 + handoff (KPI-005 = 0) | `bsa-no-new-claims-auditor` |
| INV-04 | Two-key promotion: audit markers + evidence-binding both required | orchestrator promotion routine + PreToolUse:Bash hook |
| INV-05 | A51 is not a claim source (only uncertainty/contradiction/missing_source/decision_needed/boundary_risk/inventory_gap/cross_tier_contradiction routes) | A51 schema + review |
| INV-06 | Composition via orchestrator (no direct skill-to-skill calls) | `bsa-orchestrator/SKILL.md` + review |
| INV-07 | ClaimType enum closed to `{direct, inference, analyst_judgment}` | `bsa-claim-binder/SKILL.md` + fixture_runner + pytest |

### Layer 3 — canon policy version hash

`scripts/compute_canon_hash.py` hashes a fixed set of governance-defining files (SKILL.md frontmatter, references with invariants, KPI definitions, reliability tier spec, validation scenario manifest, immutable invariants). The result lives in `.claude-plugin/plugin.json` `canonPolicyVersion.hash_full` and is attached to every runtime marker as `canon_policy_version_hash`.

`CanonPolicyVersion = <semver>+hash:<sha256-prefix>`, e.g., `1.0.0+hash:0d4d1de4` on the v1.0.3 HEAD (after the Phase-3 scaffolds landed POLICY_GLOBS adds). The manifest semver stays at `1.0.0` through the v1.0.x patch line; it bumps to `1.1.0` at the next feature release (Sprint 9 close). The hash moves whenever any file in `compute_canon_hash.py::POLICY_GLOBS` changes.

Bump rules:
- **Major** — immutable invariant touched (new invariant, weakening, or changed semantics).
- **Minor** — new validation scenario, new skill, new required field in a marker.
- **Patch** — docs-only, typo fixes, formatting.

The maintainer recomputes the hash manually via `python3 scripts/compute_canon_hash.py` after any POLICY_GLOBS edit and updates `.claude-plugin/plugin.json` `canonPolicyVersion.hash_full` in the same commit; the plugin-manifest pytest (`tests/test_plugin_manifest.py::test_manifest_canon_hash_matches_current_script_output`) catches drift on every local `pytest` run.

## Two promotion gates

### Stage 1 — evidence promotion

`/bsa-promote` on Stage 1 moves A48 / A50 / A58 / A59 / A60 / A51 from `analysis/proposals/stage1/` to `analysis/canonical/core_controls/`. Preconditions: INV-01 holds on every positive `direct`/`inference` row in A59 (analyst_judgment rows are governed by INV-07 instead), and `stage1.excerpts.merged.json` has been emitted.

### Stage N → N+1 — stage promotion (N ≥ 2)

`/bsa-promote` on a later stage checks its audit marker is present AND its proposal content satisfies INV-01 (on any new positive `direct`/`inference` rows the stage introduced into A59) + INV-07 (on any new `analyst_judgment` rows) AND any stage-specific preconditions (per `run_profile_gates.md`).

Between the two gates, the orchestrator holds a file-lock to prevent concurrent writes to canonical.

## Skill composition pattern

All skills are invoked **via** the orchestrator. A worker never calls another worker directly. This is INV-06 and is enforced by review:

```
   user → /bsa-stage 2 run
          ↓
   bsa-orchestrator reads config/request_skill_routes.json
          ↓
   routes to bsa-context-framer (Stage 2 worker)
          ↓
   bsa-context-framer reads canonical A48/A50/A58/A59/A60/A51
          ↓
   bsa-context-framer writes proposals/stage2/{5 files}
          ↓
   returns to orchestrator
          ↓
   orchestrator emits runtime marker, surfaces result to user
```

Same pattern for audits — the orchestrator invokes the auditor, collects the report + marker, and hands the verdict back.

## Sidecar model (integration contract)

C4-PlantUML and BPMN sidecars produce **derived** views from the canonical A61 anchor map. They are **non-canonical**: sidecar output never feeds back into claims, and sidecar failures don't block promotion.

Each sidecar carries an `integration-contract.md` describing:
- The `anchor_manifest.json` it consumes.
- The `view_element_id → A61.AnchorID` mapping rule.
- The "derived-only" status explicitly (sidecar output cannot become canonical).
- Standalone vs orchestrated-mode behavior.

## Runtime layout

Authoritative source: [skills/bsa-orchestrator/references/workflow-contract.md](../skills/bsa-orchestrator/references/workflow-contract.md) §"Runtime Layout".

```
analysis/
├── runtime/                   ← orchestrator + hooks writable
│   ├── ready/                   *.json markers (stage*.ready, *.pass, *.merged, handoff.ready, pipeline.complete)
│   ├── locks/                   file-locks during promotion
│   ├── reentry/                 re-entry bookkeeping
│   └── events/                  event log
├── canonical/                 ← single-writer (orchestrator-only)
│   ├── core_controls/           A48, A50, A51, A58, A59, A60, A61
│   ├── stage1/ ... stage8/      per-stage promoted content
├── proposals/                 ← worker-writable; promoted via /bsa-promote
│   ├── stage1/ ... stage6/
│   └── stage7_8/
│       ├── stage7/
│       ├── stage8/
│       └── handoff/            pre-promotion handoff pack
├── views/                     ← sidecar output (derived, non-canonical)
│   ├── evidence/, bpmn/, c4/, adjudication/, checkpoints/
├── handoff/                   ← promoted handoff pack (top-level, NOT under canonical/)
└── discovery/                 ← (if mode=discovery_then_bsa; parallel shape)
    ├── runtime/
    │   ├── ready/                d*.json markers
    │   ├── locks/                file-locks during discovery promotion
    │   ├── reentry/              re-entry bookkeeping
    │   └── events/               event log
    ├── canonical/
    │   ├── core_controls/        discovery-local A58/A59/A60 + refs to shared A48/A50/A51
    │   └── d1/ ... d5/           per-sub-stage promoted content
    ├── proposals/
    │   └── d1/ ... d5/           pre-promotion
    └── handoff/                  discovery handoff pack
```

## Plugin surface

```
.claude-plugin/plugin.json   ← discovery manifest
commands/bsa-*.md             ← 6 slash commands
hooks/hooks.json              ← 3 safety hooks (SessionStart, PreToolUse:Write, PreToolUse:Bash)
skills/                       ← 23 skill directories (each with SKILL.md + references/ + scripts/)
config/request_skill_routes.json  ← orchestrator routing table
scripts/                      ← validators, fixture runners, canon-hash computer
fixtures/golden/              ← 3 regression fixtures + 1 adversarial prompt-injection fixture
governance/                   ← immutable invariants registry
migrations/                   ← v0.9 → v1.0 migration pack
```

Further reading:

- [workflow.md](workflow.md) — stage-by-stage walkthrough.
- [../skills/bsa-orchestrator/SKILL.md](../skills/bsa-orchestrator/SKILL.md) — orchestrator contract.
- [../skills/bsa-orchestrator/references/contract-versioning.md](../skills/bsa-orchestrator/references/contract-versioning.md) — canon version hashing.
- [../governance/immutable_invariants.md](../governance/immutable_invariants.md) — invariants registry.
