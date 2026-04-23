# Immutable Invariants Registry

**Status:** Authoritative. This document defines BSA pipeline invariants that are NOT subject to automatic tuning, self-improvement auto-merge, or quiet skill evolution. Changes to any invariant here require explicit major `CanonPolicyVersion` bump + explicit maintainer approval + migration guide entry.

Last reviewed: 2026-04-19 (Sprint 0, US-S0-05).
Governance anchor for future Phase 7 self-improvement loop.

## Invariants

### INV-01: Evidence-binding
**Statement:** Every positive `direct` or `inference` claim promoted into canonical surfaces (`A59_claim_register.csv` and derivatives) MUST carry `SourceID + ExcerptID` linking to an entry in `A58_evidence_excerpts.csv`, OR an explicit `A51Ref` routing the claim through the shared uncertainty ledger.

**Rationale:** Anti-hallucination guarantee. Claims without traceable evidence are fabrications or uncontrolled inference. This is the foundational property of the entire BSA pipeline — weakening it collapses the system's value proposition.

**Enforcement:**
- `bsa-claim-binder` invariants
- `bsa-citation-auditor` (KPI-003: critical unsupported claims = 0)
- `bsa-consistency-auditor` (broken claim-binding count = 0)
- Runtime two-key promotion gate

**Override policy:** `none` — cannot be overridden. Changing this invariant is equivalent to redefining the system.

---

### INV-02: Single-writer canonical
**Statement:** Only `bsa-orchestrator` may write to `analysis/canonical/` and `analysis/discovery/canonical/`. Worker skills write exclusively to `analysis/proposals/*/` and `analysis/discovery/proposals/*/`. Sidecars write only to `analysis/views/*/`. No parallel canonical ledgers permitted.

**Rationale:** Promotion discipline. Prevents concurrent/overlapping writes that would create inconsistent canonical state. Enables audit-gated two-key promotion — orchestrator verifies all preconditions before atomic promote.

**Enforcement:**
- `bsa-orchestrator/references/ownership-and-lifecycle.md`
- Sprint 4 hook `PreToolUse:Write` on `analysis/canonical/`
- `CHK-GOV-001-08` validation scenario

**Override policy:** `requires_major_bump_and_explicit_approval` — only permissible if architecture fundamentally changes (e.g., distributed multi-writer model with conflict resolution). Out of scope for v1.x.

---

### INV-03: No new claims in Stage 8 and handoff
**Statement:** Stage 8 readiness artifacts and H1-H4 handoff packages MUST NOT introduce statement-level or element-level claims that cannot be traced to canonical upstream artifacts. `bsa-no-new-claims-auditor` verdict: leakage count = 0 (KPI-005).

**Rationale:** Output fidelity. Handoff must represent analyzed content, not re-author it. Prevents LLM drift during compression/paraphrase.

**Enforcement:**
- `bsa-no-new-claims-auditor` (main cycle + handoff + D5 discovery modes)
- Runtime marker: `stage8.no_new_claims.pass.json`
- Handoff no-new-claims gate before package promotion

**Override policy:** `none` for positive `direct`/`inference` claims. `ClaimType=analyst_judgment` with `justification_rationale` (see INV-07) is the legitimate channel for recommendations/judgments in H1/H4 — NOT an override of INV-03, but a distinct allowed category.

---

### INV-04: Two-key promotion
**Statement:** Canonical promotion requires both keys simultaneously:
1. **Evidence-binding key** — every promoted claim/anchor/element has `ClaimID (SourceID+ExcerptID)` or explicit `A51Ref`.
2. **Audit-pass key** — the stage-specific mandatory marker set is present and valid (per `bsa-orchestrator/references/run-profile-gates.md`).

**Rationale:** Dual gate prevents single-point-of-failure. Evidence-binding without audit = unverified quality; audit-pass without evidence = unsupported content.

**Enforcement:**
- `bsa-orchestrator/references/workflow-contract.md` promotion sequence
- Orchestrator pre-merge verification
- Sprint 4 hook `PreToolUse:Bash` on `/bsa promote`

**Override policy:** `none` — both keys are required. Skipping either key invalidates canonical state.

---

### INV-05: A51 is not a claim source
**Statement:** The shared `A51_issue_route_register.csv` tracks unresolved items, contradictions, decisions needed, and boundary risks. It MUST NOT be used as a source of positive claims. A claim with `A51Ref` but no upstream `ClaimID` is a guarded hypothesis, not a canonical claim.

**Rationale:** Prevents A51 from becoming a backdoor for hallucinated content. A51 is negative space (what we don't know), not a container for unsupported assertions.

**Enforcement:**
- `bsa-claim-binder` invariants
- `bsa-citation-auditor` critical unsupported claims check
- Downstream consumers must distinguish `ClaimID`-backed vs `A51Ref`-guarded

**Override policy:** `none`.

---

### INV-06: Composition via orchestrator
**Statement:** Worker skills MUST NOT invoke other worker skills directly. All inter-skill composition and routing happens through `bsa-orchestrator`. The orchestrator is the only entity authorized to sequence Stage N → Stage N+1 transitions, trigger auditors, and merge proposals.

**Rationale:** Centralizes state-machine logic and marker emission. Prevents circular dependencies, uncoordinated concurrent runs, and skill-level assumptions about pipeline ordering. Keeps individual skills independently testable.

**Enforcement:**
- Skill SKILL.md reviews (no `Invoke` or `Call` of other skills)
- Routing manifest `config/request_skill_routes.json` as single source of truth
- Sprint 0.5 `validate_request_skill_routing.py`

**Override policy:** `requires_major_bump_and_explicit_approval` — only permissible if multi-agent architecture fundamentally changes. Sidecars are an exception: they may be invoked by orchestrator as derived-only views, but sidecars do not invoke workers.

---

### INV-07: ClaimType schema closed
**Statement:** The `ClaimType` enum on `A59_claim_register.csv` is closed to exactly three values: `direct | inference | analyst_judgment`. Semantics:
- **direct** — claim reproduces or directly quotes source content
- **inference** — claim is derived from source content via explicit, recorded reasoning chain
- **analyst_judgment** — claim is a recommendation, risk assessment, or architectural preference authored by the analyst; MUST carry `justification_rationale` field referencing ≥ 1 upstream `ClaimID`

**Rationale:** Distinct epistemic categories. Conflating direct/inference erases provenance; omitting analyst_judgment forces recommendations into illegitimate channels (A51 or hallucination).

**Enforcement:**
- `bsa-claim-binder` schema validator
- `bsa-citation-auditor` treats each type with category-specific rules
- `bsa-no-new-claims-auditor` recognizes analyst_judgment as allowed in H1/H4 (with justification requirement), not as leakage

**Override policy:** `requires_major_bump_and_explicit_approval` — new categories require major `CanonPolicyVersion` bump and migration path. Adding a 4th type without migration breaks all downstream consumers.

---

### INV-08: Story-claim provenance (Phase 3)
**Statement:** Every `A70_story_register.csv` row MUST carry non-empty `SourceClaimIDs` (≥ 1 A59 ClaimID) OR non-empty `RelatedNFRIDs` (≥ 1 A62 NFRID). Stories authored from thin air — both provenance fields empty — are rejected at the F5 hook layer.

**Rationale:** Mirrors INV-03 (no new claims in Stage 8 / handoff) but applied to user stories. A story without claim or NFR provenance is the Phase-3 equivalent of a hallucinated handoff — drift the operator can't trace back to source content.

**Enforcement:**
- `governance/schemas/a70.schema.json` — `x-bsa-provenance-rules.at_least_one_of_non_empty: ["SourceClaimIDs", "RelatedNFRIDs"]`
- `governance/schemas/write_validator.py::_apply_provenance_rules` — F5 hook-time enforcement
- The same `x-bsa-provenance-rules` extension carries through to backlog exports (`backlog_export_linear.schema.json`, `backlog_export_generic.schema.json`) + Jira export `bsa_provenance.anyOf` constraint — INV-08 propagates end-to-end through the bridge.

**Override policy:** `requires_explicit_a51_route` — operators who genuinely want a story without claim/NFR provenance MUST raise an A51 `decision_needed` route documenting the rationale. The hook still rejects; the override is a workflow signal, not a schema bypass.

---

### INV-09: NFR measurability (Phase 3)
**Statement:** Every `A62_nfr_register.csv` row of category `performance | availability | scalability` MUST carry non-empty `Metric` AND non-empty `Target` OR non-empty `A51Ref`. Qualitative categories (`usability | compliance | security | maintainability | observability | portability`) MAY omit `Metric+Target` BUT MUST populate `TestabilityNotes`.

**Rationale:** Quantitative NFRs without measurable targets are aspirational, not requirements — they create the LLM-drift class where "Fast please." silently ships as a performance NFR. The Metric+Target pair (or A51 deferral) forces the authoring skill to either commit to a number OR record the open decision explicitly.

**Enforcement:**
- `governance/schemas/a62.schema.json` — `x-bsa-measurability-rules.quantitative_categories_requiring_metric_and_target: ["performance", "availability", "scalability"]`
- `governance/schemas/write_validator.py::_apply_measurability_rules` — F5 hook-time enforcement

**Override policy:** `requires_explicit_a51_route` — same pattern as INV-08. Measurability-deferred NFRs surface the gap via A51 instead of bypassing the schema.

---

### INV-10: Test-scenario provenance (Phase 3)
**Statement:** Every `A71_test_scenario_register.csv` row MUST carry non-empty `SourceStoryID` resolving to an existing A70 row. Composite scenarios (multiple StoryIDs in one row) are forbidden — the SourceStoryID column is singular.

**Rationale:** Test scenarios without story drivers are dead test code — they verify behavior nobody asked for. The 1:1 (or 1:N from one story to multiple scenarios) shape forces every test to trace back to a user-facing decision.

**Enforcement:**
- `governance/schemas/a71.schema.json` — `SourceStoryID` is in `required` AND has the singular pattern `^STORY-(?:[A-Z]{2,5}-)?[0-9]{3,4}$` (no semicolon-list).
- F5 hook-time enforcement at write.

**Override policy:** `none` — INV-10 is unconditional. A test scenario without a story driver is always wrong; the fix is to author the missing story first.

---

## Scope of self-improvement (Phase 7 L1/L2)

**See [`docs/phase_7_design.md`](../docs/phase_7_design.md)** for the v1.1.14 foundation: formal `config/tunables.yaml` inventory + `scripts/phase_7_lint.py` IMMUTABLE_CONFLICT detector + safety contract.

The future Phase 7 self-improvement loop may tune:
- Severity thresholds (e.g., `EpistemicInsufficiency` trigger bounds)
- KPI targets within adjustable bounds (e.g., KPI-001 target 0.70..0.95)
- Scoring weights in references (e.g., prioritization matrix axis weights)
- Validator tolerance for warnings (not for blockers)

The self-improvement loop MUST NOT tune:
- Any invariant in this registry
- Core enum schemas (`ClaimType`, `IssueType`, `AnchorClass`)
- Ownership assignments (which skill owns which surface)
- Promotion sequence ordering
- Marker gate requirements (which markers are mandatory)

Attempted L1 auto-patch that touches a derived rule whose upstream is an invariant MUST be flagged `IMMUTABLE_CONFLICT` and rejected automatically.

---

## Change log

### 2026-04-20 — Sprint 3 retroactive semantic-rename sweep
Wording-only cleanup. The Sprint 2 US-S2-02 part 3/3 audit (`docs/sem_audit_rename.md`) was scoped to `skills/` only; this file retained legacy "fact"/"factual" phrasing that contradicts the canonical claim-semantics vocabulary. Applied:
- INV-01 statement: "Every positive factual claim" → "Every positive `direct` or `inference` claim" (explicit ClaimType replaces narrow disambiguator on the foundational evidence-binding rule).
- INV-03 override policy: "`none` for positive factual claims" → "`none` for positive `direct`/`inference` claims" (parallel with INV-01; preserves the explicit contrast against `ClaimType=analyst_judgment` in the next sentence).
- INV-05 heading: "A51 is not a fact source" → "A51 is not a claim source" (matches the Sprint 2 phrasing already in `skills/bsa-orchestrator/references/shared-control-surface-contracts.md`).
- INV-05 body: "source of positive factual claims" → "source of positive claims"; "guarded hypothesis, not a fact" → "guarded hypothesis, not a canonical claim".

No semantic change; no `CanonPolicyVersion` bump. See `docs/sem_audit_rename.md` Sprint 3 retroactive findings table.

### 2026-04-19 — Initial version (US-S0-05)
Seven invariants defined. INV-07 (ClaimType enum with `analyst_judgment`) added based on plan rev2 critical review — blocks Phase 3 story-writer hallucination risk without explicit judgment category. Sprint 1 US-S1-01 AC-8/AC-9 operationalize this invariant in A59 schema.
