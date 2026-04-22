# Workflow — end-to-end pipeline

Full stage-by-stage walkthrough of the BSA pipeline including discovery mode.

## Pipeline shape

```
  (optional) Discovery:  D1  →  D2  →  D3  →  D4  →  D5  →  discovery.go marker
                          ↓ (promotion: discovery seed → Stage 1)
   Main cycle:  Stage 1 → Stage 2 → Stage 3 → Stage 4 → Stage 5 → Stage 6 → Stage 7 → Stage 8 → Handoff
```

Every arrow is a **two-key promotion**: the orchestrator moves proposals into canonical only when evidence-binding (INV-01) AND the required audit markers both pass. Missing either is a blocker; the PreToolUse:Bash hook refuses `/bsa-promote` until both hold.

## Stage-by-stage

Worker chains below follow the authoritative stage map in [commands/bsa-stage.md](../commands/bsa-stage.md) §"What this command does".

### Stage 1 — Evidence intake + claim binding

- Inputs: raw source documents under `analysis/proposals/stage1/inputs/`.
- Workers: `bsa-evidence-intake` → `bsa-claim-binder`.
- Canonical artifacts: `A48`, `A50`, `A58`, `A59`, `A60`, `A51` (under `analysis/canonical/core_controls/`).
- Gate: `stage1.excerpts.merged.json` marker.
- Command: `/bsa-stage 1` then `/bsa-promote`.

Every positive `direct` or `inference` claim promoted into `A59` must carry `SourceID+ExcerptID` OR an explicit `A51Ref` (evidence-binding, INV-01). `analyst_judgment` claims are governed by INV-07: they must carry `JustificationRationale` referencing ≥ 1 upstream `ClaimID`.

`ReliabilityTier` (T1-T5) is set on every `A50` row and propagates into `A59.ClaimStrength` per [reliability_tier_spec.md](../skills/bsa-evidence-intake/references/reliability_tier_spec.md).

### Stage 2 — Context state frame

- Worker: `bsa-context-framer`.
- Canonical artifacts under `analysis/canonical/stage2/`: `context_state_frame.md`, `stakeholder_authority_map.md`, `constraints_dependencies_route.md`, `system_context_seed.md`, `stage2_summary.json`.
- Gate: `stage2.context_state.pass.json` marker.
- Command: `/bsa-stage 2` then `/bsa-promote`.

Stage 2 has an explicit worker (`bsa-context-framer`) — earlier drafts were runtime-native, which is documented as a resolved gap in [sprint 1 retro](retros/sprint_1.md).

### Stage 3 — Semantic extraction + citation/consistency audit

- Worker: `bsa-semantic-extractor` (runs first).
- Auditors (in-stage): `bsa-citation-auditor` + `bsa-consistency-auditor`.
- Audit reports: `citation_audit_report.md`, `consistency_audit_report.md`.
- KPI output: `KPI-001` (weighted coverage) + `KPI-003` (critical unsupported) + `KPI-004` (anchor integrity partial).
- Gate: `stage3.citation_audit.pass.json` marker.
- Command: `/bsa-stage 3` (runs worker + both audits); or `/bsa-audit citation` / `/bsa-audit consistency` to re-run an individual audit.

KPI-001 weighted coverage: `sum(ClaimStrength for direct claims with bound SourceID+ExcerptID) / count(all direct claims)`. Target ≥ 0.75. KPI-001 is **direct-claims-only**: inference claims (contested or otherwise) do not enter the formula — they are surfaced via `A51` when contested at tier-delta ≤ 1.

### Stage 4 — Domain model (entity + state catalogs)

- Worker: `bsa-domain-modeler`.
- Canonical: `analysis/canonical/stage4/domain_model/` entity + state-machine catalogs.
- Gate: `stage4.ready.json` marker (promotion gate; no dedicated audit).
- Command: `/bsa-stage 4` then `/bsa-promote`.

### Stage 5 — Backbone anchors

- Worker: `bsa-backbone-builder`.
- Auditor (in-stage): `bsa-anchor-auditor` (backbone mode).
- Canonical: `analysis/canonical/stage5/backbone/`, `A61` backbone anchors.
- Audit: anchor-drift detection + orphan/duplicate/class-mismatch + claim-binding.
- Gate: `stage5.anchor_audit.pass.json` marker.
- Command: `/bsa-stage 5` (runs builder + anchor audit); `/bsa-audit anchor` to re-run the audit.

### Stage 6 — Contract-layer anchors

- Worker: `bsa-contract-builder`.
- Auditor (in-stage): `bsa-anchor-auditor` (contract-layer mode).
- Canonical: `analysis/canonical/stage6/contracts/`, `A61` full contract layer.
- Audit: same anchor-audit contract as Stage 5; A61 promoted here.
- Gate: `stage6.anchor_audit.pass.json` marker.
- Command: `/bsa-stage 6` then `/bsa-promote`.

### Stage 7 — Skeptical review + citation-audit re-run

- Worker: `bsa-skeptical-reviewer`.
- Auditor (in-stage): `bsa-citation-auditor` re-run against the full promoted corpus.
- Audit reports: `skeptical_review_report.md` (+ updated `citation_audit_report.md`).
- Gate: `stage7.skeptical_review.pass.json` marker.
- Command: `/bsa-stage 7`; `/bsa-audit skeptical` to re-run skeptical review.

### Stage 8 — Validation readiness + no-new-claims gate

- Worker: `bsa-validation-readiness`.
- Auditor (in-stage): `bsa-no-new-claims-auditor`.
- Audit reports: `readiness_assessment.md`, `no_new_claims_report.md`.
- KPI output: `KPI-005` (new-claim leakage). Target = 0.
- Gate: `stage8.no_new_claims.pass.json` marker.
- Command: `/bsa-stage 8`; `/bsa-audit no-new-claims` to re-run.

### Handoff — H1-H4 pack

- Worker: `bsa-handoff-packager`.
- Output: `H1_exec_brief.md`, `H2_delivery_packet.md`, `H3_validation_packet.md`, `H4_open_items_packet.md`, plus `handoff_manifest.json`, `handoff_evidence_binding_map.csv`, `handoff_no_new_claims_report.md`.
- Second no-new-claims audit: the auditor runs again over H1-H4; its verdict lands in `handoff_no_new_claims_report.md` and gets attached to `handoff_manifest.json.no_new_claims_verdict`.
- Command: `/bsa-handoff`.

## Discovery mode

When scope is fuzzy, stakeholder accounts conflict, or the source set is itself in flux, use `--mode=discovery_then_bsa`. This runs five discovery sub-stages first:

| Stage | Worker | Output | Gate marker |
|---|---|---|---|
| D1 | `d0-problem-framer` | problem-frame note | `discovery.d1.ready` |
| D2 | `d0-context-researcher` | discovery A58/A59 prefixed `D-C-*` | `d2.claims.merged` + `d2.research_quality.pass` |
| D3 | `d0-hypothesis-prioritizer` | ranked hypothesis list | `d3.prioritization.pass` |
| D4 | `d0-feasibility-assessor` | constraint audit | `d4.constraint_audit.pass` |
| D5 | `d0-synthesis-gatekeeper` | discovery-seed bundle + citation + no-solution-leakage | `d5.citation_audit.pass` + `d5.no_solution_leakage.pass` |

After D5 passes the gatekeeper, the orchestrator promotes the discovery-seed bundle into Stage 1 according to the [discovery→main merge contract](../skills/bsa-orchestrator/references/discovery_to_main_merge.md). Discovery claim IDs (`D-C-*` namespace) and main claim IDs (`C-*` namespace) stay isolated; conflict detection raises an `A51` with `IssueType=contradiction` and `BlockingStatus=hard`.

## Two-key promotion in practice

```
/bsa-promote --dry-run
```

outputs the list of files that would move from `analysis/proposals/stage<n>/` to `analysis/canonical/stage<n>/`, the markers that would be emitted, and the evidence-binding check result.

A successful run:

```
/bsa-promote
```

acquires a file-lock, writes the canonical state, emits the next stage's `*.ready` marker, and releases the lock. Only `bsa-orchestrator` is permitted to write under `analysis/canonical/` (enforced by the PreToolUse:Write hook).

## Invariants summary (all 7)

- **INV-01** — evidence-binding: every positive `direct` or `inference` claim promoted into `A59` MUST carry `SourceID+ExcerptID` OR an explicit `A51Ref`. `analyst_judgment` claims are scoped to INV-07 below.
- **INV-02** — single-writer canonical: only `bsa-orchestrator` writes under `analysis/canonical/`.
- **INV-03** — no new claims introduced after Stage 7 (no-new-claims gate, KPI-005 = 0).
- **INV-04** — two-key promotion: audit markers + evidence-binding both required for every promotion.
- **INV-05** — `A51` is not a claim source (only uncertainty / contradiction / missing_source / decision_needed / boundary_risk / inventory_gap / cross_tier_contradiction routes).
- **INV-06** — composition via orchestrator: skills do not call each other directly.
- **INV-07** — `ClaimType` enum closed to `{direct, inference, analyst_judgment}`; `analyst_judgment` rows MUST carry `JustificationRationale` referencing ≥ 1 upstream `ClaimID`. Enum extension requires a major CanonPolicyVersion bump.

Plus the **tier-delta ≤ 1 contested rule** from the reliability tier spec: contradicting claims at tier-delta ≤ 1 route via `A51` with `IssueType=cross_tier_contradiction` (per [reliability_tier_spec.md](../skills/bsa-evidence-intake/references/reliability_tier_spec.md) §Conflict Resolution), `Severity=high`, `BlockingStatus=hard`, and both rows get `ClaimStrength=0.0`.

Full registry: [../governance/immutable_invariants.md](../governance/immutable_invariants.md).
