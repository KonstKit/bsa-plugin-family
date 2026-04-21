# Phase 3 Plan — Dev-Handoff Extension (Sprint 6+)

Phase 3 extends the BSA pipeline from "evidence-bound analysis artifact" (H1-H4) into "dev-handoff input" (user stories + NFRs + test scenarios + traceability + backlog-bridge).

## Status (Sprint 5 baseline)

Phase 2.5 gate unblocked by Sprint 5 (schema enforcement + reconciliation auditor). Phase 3 kick-off starts in Sprint 6 with `bsa-nfr-collector` as the first skill delivered end-to-end; the other four skills are scaffolded in the same sprint but built out in Sprints 7-9.

## New skills (5)

| Skill | Input | Output artifact | Dependencies |
|---|---|---|---|
| **bsa-nfr-collector** | A59 claims (`analyst_judgment` + select `inference`) + H2 delivery packet | `A62_nfr_register.csv` | A59 + A51 |
| **bsa-story-writer** | A59 claims + A62 NFRs + H2 delivery packet | `A70_story_register.csv` | A59 + A62 |
| **bsa-test-scenario-builder** | A70 stories + A59 claims + A62 NFRs | `A71_test_scenario_register.csv` | A70 + A62 |
| **bsa-traceability-matrix** | A70 + A59 + A50 | `A72_traceability_matrix.csv` | A70 + A59 + A50 |
| **bsa-backlog-bridge** | A70 + A71 + A72 + H1-H4 | `handoff/backlog_export.{json,csv}` + platform-specific files | all of A70-A72 |

## New canonical artifacts (4 CSVs)

Schema-first per Sprint-5 discipline — every new artifact gets a JSON Schema in `governance/schemas/` + loader helper + write-validator dispatch entry + schema-conformance tests. F5's `pre_write_canonical.sh` automatically enforces them.

- `A62_nfr_register.csv` — Non-functional requirements extracted from claims.
- `A70_story_register.csv` — User stories derived from claims + NFRs.
- `A71_test_scenario_register.csv` — Test scenarios keyed to stories.
- `A72_traceability_matrix.csv` — Story ↔ claim ↔ source three-way links.

## User-story breakdown (Sprints 6-9)

### Sprint 6 — Foundation

- **US-S6-01** — A62 schema + bsa-nfr-collector skill (SKILL.md + references + tests + golden-fixture updates). Proof-of-pattern for Phase 3 skills. **[Kick-off: implemented end-to-end in Sprint-5 scaffolding commit for review, promoted to Sprint 6 ACs.]**
- **US-S6-02** — Scaffold commits for the other 4 Phase-3 skills (SKILL.md + TODO anchors + reference skeletons). No tests yet — just the directory layout + interface documentation.
- **US-S6-03** — `commands/bsa-dev-handoff.md` new slash-command that sequences the 5 Phase-3 skills as a composition.
- **US-S6-04** — Update `skills/bsa-orchestrator/references/workflow-contract.md` to include the Phase-3 stages (informational — actual promotion routing in Sprint 7).

### Sprint 7 — bsa-story-writer

- **US-S7-01** — A70 schema.
- **US-S7-02** — bsa-story-writer SKILL.md + references. Input: A59 + A62. Output: A70.
  Acceptance: INVEST criteria enforcement (Independent / Negotiable / Valuable / Estimable / Small / Testable — at least documented, ideally validated).
- **US-S7-03** — Tests including: every story traces to ≥ 1 ClaimID or ≥ 1 NFRID (no net-new claims in stories → reuse no-new-claims-auditor pattern).

### Sprint 8 — bsa-test-scenario-builder + bsa-traceability-matrix

- **US-S8-01** — A71 schema + bsa-test-scenario-builder.
- **US-S8-02** — A72 schema + bsa-traceability-matrix.
- **US-S8-03** — Integration test: run full D→Stage1..8→NFR→Story→TestScenario→TraceabilityMatrix on project_0001 fixture; assert every test scenario links back to claim + source through the matrix.

### Sprint 9 — bsa-backlog-bridge + Phase-3 release

- **US-S9-01** — bsa-backlog-bridge skill with Jira JSON exporter (most-requested format).
- **US-S9-02** — Linear CSV exporter.
- **US-S9-03** — Generic CSV exporter (for "paste into our home-grown tool" case).
- **US-S9-04** — Phase 3 acceptance fixture: adversarial case where claim evidence contradicts NFR, ensure story-writer surfaces as A51.
- **US-S9-05** — `v1.1.0` release cut with Phase-3 closed.

## Cross-cutting invariants (Phase 3 adds)

- **INV-08 (NEW): Story-claim provenance.** Every A70 story row MUST carry a non-empty `SourceClaimIDs` list referencing ≥ 1 A59 ClaimID. Stories authored from thin air are rejected. Mirrors INV-03 (no new claims in handoff) but applied to stories.

- **INV-09 (NEW): NFR measurability.** Every A62 NFR of category `performance | availability | scalability` MUST have non-empty `Metric` + `Target`. Qualitative categories (`usability | compliance`) MAY omit but MUST populate `TestabilityNotes`.

- **INV-10 (NEW): Test-scenario provenance.** Every A71 scenario row MUST carry `SourceStoryID` (linking to A70). Scenarios without stories are rejected.

These land in `governance/immutable_invariants.md` as part of US-S9-05.

## Integration points

**Discovery → Stage1..8 → Phase-3:** Phase-3 skills run AFTER Stage 8 / handoff promotion. Prerequisites:
- `stage8.no_new_claims.pass.json` marker present.
- `handoff.ready.json` marker present.
- H2_delivery_packet.md promoted to `analysis/handoff/`.

**Orchestration:** `bsa-orchestrator` composes the 5 Phase-3 skills. New markers:
- `phase3.nfr.pass.json`
- `phase3.story.pass.json`
- `phase3.test_scenario.pass.json`
- `phase3.traceability.pass.json`
- `phase3.backlog_exported.json`
- `pipeline.phase3.complete.json`

All new markers go into `marker.schema.json`'s `marker_id` enum + main audit-pass sequence. Same alphabet-sync test catches drift.

## Enforcement layer (reuse of Sprint 5 F5)

Because F5 dispatches by path, the new schemas (A62 / A70 / A71 / A72) get write-time schema enforcement automatically as soon as:
1. Their `governance/schemas/a62.schema.json` et al. exist.
2. The `_DISPATCHER` table in `governance/schemas/write_validator.py` gains the new path patterns.

No hook-level changes needed. This is the direct payoff of doing F5 before Phase 3 — every new Phase-3 artifact gets mechanical schema enforcement from day one, and the LLM-drift class that bit the Sysco engagement cannot recur for the new surfaces.

## Risks

| Risk | Mitigation |
|---|---|
| Story-writer produces "stories" that are thinly-restated claims (no real decomposition) | INV-08 + story-specific no-new-claims auditor recognizes this; adversarial fixture in US-S9-04 pins the regression. |
| NFR over-collection — picking up every adjective as an NFR | NFRCategory enum + Measurability rules; small-scope fixtures. |
| Backlog-bridge brittleness across platforms | Generic-CSV path as fallback; JSON+Jira as primary; defer Linear/GitHub Projects to v1.2. |
| Phase-3 output schema-drift (the Sysco-class problem) | Already mitigated by F5 — new schemas get enforcement on day one. |

## Release target

`v1.1.0` at the end of Sprint 9. Semver bump because Phase 3 adds capability (backward-compatible: Phase 0-2 workspaces keep working; Phase 3 is opt-in via `/bsa-dev-handoff`).

## Related

- Sprint 5 summary: commits `034ddb3..8d4692a`.
- Phase 2.5 shakedown: `docs/phase_2_5_shakedown.md`.
- Existing immutable invariants (INV-01..INV-07): `governance/immutable_invariants.md`.
