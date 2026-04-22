---
name: bsa-traceability-matrix
description: Build A72_traceability_matrix.csv — three-way join of A70 stories ↔ A59 claims ↔ A50 sources, one row per traceable Story↔ClaimID↔SourceID triple. Pure derivation skill — never authors net-new content; rejects rows whose IDs don't resolve in upstream artifacts. Phase 3 skill — runs after phase3.test_scenario.pass, before phase3.backlog_exported.
---

# BSA Traceability Matrix

Run this skill after `bsa-test-scenario-builder` has promoted `A71_test_scenario_register.csv` (or after `bsa-story-writer` if running stand-alone). Produces the explicit Story↔Claim↔Source mapping that downstream consumers (`bsa-backlog-bridge`, audit tooling, human reviewers) use to query orphans + coverage gaps.

## Scope

- Walk A70 stories → resolve `A70.SourceClaimIDs` → A59 claims → A59.SourceID → A50 sources. Emit one A72 row per Story↔ClaimID↔SourceID triple (LinkType=`direct`).
- Walk A70 stories → `A70.RelatedNFRIDs` → A62 NFRs → `A62.SourceClaimIDs` → A59 claims → A59.SourceID → A50 sources. For each resulting triple: if the EXACT (Story, ClaimID, SourceID) was already emitted as a `direct` row in step 2, do NOT emit a duplicate (the row identity is the triple; multi-route reachability is annotated in `traceability_coverage.md`). If the triple is reachable ONLY via NFR-mediation, emit one row with LinkType=`nfr-mediated`.
- For stories where all three IDs (Story, Claim, Source) are KNOWN but the trace is provisional (e.g., the link strength is contested, or the operator wants to defer acceptance pending review), emit a row with LinkType=`a51-routed` + non-empty A51Ref so the deferral is tracked rather than silently accepted as a clean trace. NB: `a51-routed` is for KNOWN-BUT-DEFERRED links; rows with unresolved IDs are never emitted (schema requires non-empty StoryID/ClaimID/SourceID). Unresolved cases go to `traceability_orphans.md` + an A51 `missing_source` route, NOT to A72.
- Pure derivation: NEVER authors stories, claims, or sources. NEVER infers a triple that A70/A59/A50 don't already establish via explicit ID references.

Out of scope:
- Authoring net-new claims, stories, or sources.
- Resolving A51 routes — this skill records that a route is open; resolution is the operator's job.
- Backlog export — that's `bsa-backlog-bridge`. This skill produces the JOIN; bridge layers platform-specific shape on top.
- Test-scenario coverage matrix — A71 is keyed off A70 stories; A72 doesn't include scenarios as a fourth dimension. Scenario coverage lives in `test_scenario_authoring_report.md` (US-S8-01 output).

## Inputs

- Promoted `analysis/canonical/core_controls/A70_story_register.csv`
- Promoted `analysis/canonical/core_controls/A59_claim_register.csv`
- Promoted `analysis/canonical/core_controls/A50_source_register.csv`
- Promoted `analysis/canonical/core_controls/A62_nfr_register.csv` (for nfr-mediated traces)
- Shared `analysis/canonical/core_controls/A51_issue_route_register.csv` (for a51-routed traces)

## Outputs

- `analysis/proposals/phase3/A72_traceability_matrix.csv`
- `analysis/proposals/phase3/traceability_orphans.md`
- `analysis/proposals/phase3/traceability_coverage.md`

All three land under `analysis/proposals/phase3/`. Promotion to canonical goes through `/bsa-promote` with the two-key gate (foreign-key resolution check + `phase3.traceability.pass` marker).

## Workflow

1. **Load inputs.** Read promoted A70, A59, A50, A62, A51. Build in-memory indices: `story_by_id`, `claim_by_id`, `source_by_id`, `nfr_by_id`. Fail fast if any of A70/A59/A50 is not promoted (foreign-key resolution requires all three).

2. **Walk direct links.** For each A70 story, parse `SourceClaimIDs` (semicolon/slash-separated). For each ClaimID:
   - Look up the claim in A59. If absent: raise an A51 `missing_source` route AND record the unresolved (StoryID, ClaimID) pair in `traceability_orphans.md`. Do NOT emit an A72 row (schema requires non-empty resolved IDs).
   - Look up the claim's `SourceID` in A50. If absent: same A51 + orphan-report treatment for the (StoryID, ClaimID, SourceID) chain. Do NOT emit a row.
   - If both resolve cleanly: emit one A72 row with LinkType=`direct`, LinkStrength derived from claim's ClaimStrength + source's ReliabilityTier (T1/T2 → high; T3 → medium; T4/T5 → low).

3. **Walk NFR-mediated links.** For each A70 story, parse `RelatedNFRIDs`. For each NFRID:
   - Look up the NFR in A62. If absent: A51 `missing_source` + orphan report; do NOT emit a row.
   - For each `SourceClaimIDs` of the NFR, recurse claim+source resolution as in step 2. The row identity is the (Story, ClaimID, SourceID) triple — NOT (Story, ClaimID, SourceID, LinkType). So:
     * If the EXACT triple was already emitted as `direct` in step 2: do NOT emit a duplicate row. Track the multi-route reachability in `traceability_coverage.md` (the operator reads "this trace is reachable via direct link AND via NFR-mediation through NFR-XXX-NNN").
     * Otherwise: emit ONE row with LinkType=`nfr-mediated`.

4. **Mark deferred-but-resolved traces.** For any otherwise-clean trace (all three IDs resolved) that the operator has flagged as provisional via an existing A51 route (e.g., link strength contested, claim still under review), emit the row with LinkType=`a51-routed` + the route's A51Ref non-empty. The schema requires LinkType=`a51-routed` rows to co-populate A51Ref (`x-bsa-deferral-rules`). NB: `a51-routed` is reserved for KNOWN links that are deferred — never for unresolved IDs (those go to the orphan report only).

5. **Self-validate the matrix.** Before write, walk every emitted row and re-check (these checks apply to ALL LinkTypes including `a51-routed` — `a51-routed` defers ACCEPTANCE, not ID resolution or claim-source consistency):
   - StoryID resolves in A70.
   - ClaimID resolves in A59.
   - SourceID resolves in A50.
   - A59[ClaimID].SourceID equals this row's SourceID. A mismatch is a SKILL bug; halt and emit a diagnostic. (NB: this check applies to a51-routed rows too — there is no exemption.)
   - LinkType=`a51-routed` rows have non-empty A51Ref.
   - No duplicate (StoryID, ClaimID, SourceID) triples (one row per triple, regardless of LinkType).

6. **Emit reports.**
   - `traceability_orphans.md` — items at any layer without uplink:
     - A70 stories with no A72 row (story has no resolvable claim/NFR).
     - A59 claims with no A72 row (no story references this claim).
     - A50 sources with no A72 row (no claim references this source — possibly indicates source was loaded but never excerpted).
     - A62 NFRs with no A72 row (NFR has no story driver and no claim provenance).
   - `traceability_coverage.md` — KPI scorecard:
     - **KPI-006 (Phase-3) — story-to-claim coverage ratio**: `|A70 stories with at least one direct A72 row| / |A70 stories|`. Target: ≥ 0.90 for production-ready handoff; lower indicates story-writer authored stories without claim grounding (which INV-08 should have caught — investigate).
     - Source coverage: `|A50 sources with at least one A72 row| / |A50 sources where AccessStatus=readable|`. Target ≥ 0.80; lower indicates loaded-but-unused sources.
     - NFR coverage: `|A62 NFRs with at least one A72 row| / |A62 NFRs|`.

7. **Emit A72 + reports + marker.** Write `A72_traceability_matrix.csv` and the two report MDs to `analysis/proposals/phase3/`. After `/bsa-promote` lands them in `analysis/canonical/core_controls/`, emit `phase3.traceability.pass.json`.

## Invariants

- **Foreign-key integrity** — every A72 row's StoryID, ClaimID, SourceID MUST resolve to an existing row in A70, A59, A50 respectively. Applies to ALL rows including `a51-routed` (deferral is about acceptance, not ID resolution). Documented in `x-bsa-foreign-key-rules.applies_to_all_rows=true`; enforced by this skill's own self-validation (cross-artifact lookup outside F5 path-bound dispatch). Future hook-layer enforcement filed as `[TODO-S8-02-X-ARTIFACT-FK]`.
- **Claim-source consistency** — for ALL rows (including `a51-routed`), `A59[ClaimID].SourceID` MUST equal this row's SourceID. The matrix is a JOIN; an internally inconsistent join defeats traceability. There is no LinkType exemption for this rule.
- **Pure derivation** — NEVER author net-new claims, stories, NFRs, or sources. Every triple resolves to existing IDs in A70/A59/A50. (Mirrors INV-03 / INV-08 in spirit: derived artifacts cannot introduce content.) Unresolved IDs go to `traceability_orphans.md` + an A51 `missing_source` route, NEVER to A72 rows.
- **Row-identity uniqueness** — one row per (StoryID, ClaimID, SourceID) triple. Never emit duplicate rows differing only in LinkType (multi-route reachability is annotated in `traceability_coverage.md`, not duplicated in A72).
- **Deferral coupling** — `LinkType == 'a51-routed'` requires non-empty `A51Ref`. Generalized version of A70 INVEST-A51 + A71 deferred-A51 patterns; enforced by `write_validator._apply_deferral_rules` with `status_field='LinkType'` override.
- **Singularity** — every A72 row is exactly one Story↔Claim↔Source triple. No semicolon-list IDs. Composite traces split into multiple rows.

## Failure modes

- **A70/A59/A50 not all promoted** — skill exits with error pointing to the missing artifact's source skill.
- **A70 story references a ClaimID that doesn't exist in A59** — emit an A51 `missing_source` route + flag the unresolved (StoryID, ClaimID) pair in `traceability_orphans.md`. Do NOT emit an A72 row for the unresolved trace (schema requires non-empty resolved IDs); the orphan report is the way the operator finds out.
- **A59 claim's SourceID doesn't exist in A50** — same A51 + orphan-report treatment for the (StoryID, ClaimID, SourceID) chain. Do NOT emit a row.
- **Claim-source mismatch detected during self-validate (step 5)** — skill bug. Halt + emit diagnostic + do NOT promote. Operator inspects the offending claim's SourceID vs the matrix row's SourceID.
- **KPI-006 below 0.90** — emit a warning section in `traceability_coverage.md` with the offending stories listed; do NOT fail the skill (some engagements legitimately have story-only NFR-mediated traces). Operator decides whether to accept.

## Composition

Invoked by `/bsa-dev-handoff` (Phase-3 composite command) as the fourth stage: `phase3.nfr → phase3.story → phase3.test_scenario → phase3.traceability → phase3.backlog_exported`.

May also be invoked directly via `/bsa-dev-handoff --only=traceability` for debugging / partial re-runs; prerequisites (`phase3.story.pass` + promoted A70 + A59 + A50 + A62) must be satisfied. A62 is required because NFR-mediated traces (LinkType=`nfr-mediated`) recurse through A62.SourceClaimIDs; without A62 promoted, the skill emits an A72 with no nfr-mediated rows even when stories carry RelatedNFRIDs — incomplete output. `phase3.nfr.pass` is recommended for marker-level parity. (NB: `phase3.test_scenario.pass` is NOT a strict prerequisite — A72 doesn't read A71 directly; the matrix is keyed off stories, not scenarios.)

Downstream consumers:
- `bsa-backlog-bridge` reads A72 to attach claim/source provenance to exported stories.
- Human reviewers query A72 for orphans + coverage gaps directly via the two report MDs.

## Cross-refs

- `governance/schemas/a72.schema.json` — row schema + deferral + foreign-key extensions.
- `skills/bsa-story-writer/SKILL.md` — upstream story authoring (A70).
- `skills/bsa-evidence-intake/SKILL.md` — upstream source/claim authoring (A50/A59).
- `skills/bsa-nfr-collector/SKILL.md` — upstream NFR authoring (A62; consumed for nfr-mediated traces).
- `docs/phase_3_plan.md` — Phase-3 sequencing + Sprint 8-9 scope.
- `commands/bsa-dev-handoff.md` — composite command that invokes this skill.

## Open follow-ups

- `[TODO-S8-02-X-ARTIFACT-FK]` — hook-layer enforcement of foreign-key resolution (StoryID in A70, ClaimID in A59, SourceID in A50, claim-source consistency) requires a cross-artifact validator pattern. Currently rule is documentary at the schema layer + skill-self-validated. Same deferral as A71's `[TODO-S8-01-X-ARTIFACT-NFR-COVERAGE]`; both can land together when the cross-artifact validator pattern is established (Sprint 9 or v1.2).
- `[TODO-S8-02-INCREMENTAL-MATRIX]` — for engagements with thousands of triples, a full re-build on every `bsa-dev-handoff` invocation is wasteful. Incremental update (compare promoted A70/A59/A50 hashes to last-known) is filed as a v1.2 polish.
- `[TODO-S8-02-LINK-STRENGTH-OVERRIDE]` — operator override of LinkStrength (default is derived from tier × claim-strength) needs a designated A51 IssueType; pick / extend in v1.2.
