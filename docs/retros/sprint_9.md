# Sprint 9 Retrospective — bsa-backlog-bridge + adversarial fixture + v1.1.0 release cut

**Window:** Closing sprint of the Phase-3 dev-handoff workstream. Picks up immediately after Sprint 8 close (sprint-8-close tag on `2eeafed`).
**Tag target:** `v1.1.0` (pending commit at the end of US-S9-05).
**Canon policy version at Sprint 9 close:** `1.1.0+hash:d449ae74` (was `1.0.3+hash:3c32c861` at Sprint 8 close; bumped through several intermediate values during US-S9-01..04, then again at US-S9-05 when INV-08/09/10 landed in `governance/immutable_invariants.md`).

## Why this sprint

Sprint 8 closed with 4 of 5 Phase-3 skills implemented + the project_0001 happy-path integration test. Sprint 9 closes the remaining slice:
- The **fifth and final** Phase-3 skill (`bsa-backlog-bridge`) — Jira REST v3 JSON + Linear CSV + generic CSV exporters under `analysis/handoff/`.
- The **adversarial regression baseline** (claim-contradiction → A51 propagation chain) — proves the Phase-3 contract works end-to-end for the contradicted-evidence case, not just the clean case.
- The **v1.1.0 release cut** — semver bump from 1.0.x to 1.1.0 (Phase-3 closed); INV-08/09/10 codified in `governance/immutable_invariants.md`; `pipeline.phase3.complete` in the marker alphabet.

After Sprint 9, Phase 3 is FEATURE-COMPLETE: every Phase-3 artifact has a schema, a producer skill, an integration-test regression baseline, and a backlog-export path to dev tooling.

## What was delivered

| US | Surface | Commit | Codex rounds | Result |
|---|---|---|---|---|
| US-S9-01..03 (combined) | bsa-backlog-bridge SKILL.md + 3 export schemas (Jira JSON, Linear CSV, generic CSV) + first F5 dispatcher entries under analysis/handoff/ + `_validate_jira_export_json` helper + 2 new terminal markers (phase3.backlog_exported + pipeline.phase3.complete) with EXACT H-sec-4 bindings + 45 schema-conformance tests | `01a5de9` | 6 | APPROVE |
| US-S9-04 | adversarial_nfr_claim_contradiction_001 fixture + 35 integration tests + headline `test_contradiction_propagates_to_every_phase3_artifact` mechanically pinning the 5-layer A59→A62→A70→A71→A72 propagation chain | `e209010` | 7 | APPROVE |
| US-S9-05 | INV-08/09/10 added to `governance/immutable_invariants.md` + manifest version + canonPolicyVersion bumped to 1.1.0 + Sprint 9 retro + CHANGELOG entry + v1.1.0 tag | (this commit) | 0 (bookkeeping) | — |

Plus: this retro file + `v1.1.0` git tag (pending).

Cumulative: **+81 tests** across the sprint (1167 → 1248); zero regressions.

## Acceptance criteria coverage

**US-S9-01..03 (`01a5de9`):**
- AC-1: PASS — `governance/schemas/backlog_export_jira.schema.json` (top-level discriminator + Jira REST v3 issue-create shape + bsa_provenance block); `backlog_export_linear.schema.json` (CSV with 9 required columns; Status/Priority/Estimate enums; Labels regex with positive + negative lookaheads for membership AND singularity); `backlog_export_generic.schema.json` (CSV with 9 columns including INVESTStatus + A51Ref).
- AC-2: PASS — F5 dispatcher gained 3 new entries under `analysis/handoff/backlog_export_*` (FIRST F5 dispatch on handoff/ paths). New `_validate_jira_export_json` helper for the JSON shape (CSV ones reuse `_make_csv_validator`).
- AC-3: PASS — INV-08 enforcement carries through to all 3 exports (Jira via `bsa_provenance.anyOf`; Linear/generic via `x-bsa-provenance-rules` + the existing `_apply_provenance_rules` handler). INVEST-A51 coupling carries through to generic export via `x-bsa-invest-rules`.
- AC-4: PASS — phase3.backlog_exported + pipeline.phase3.complete in marker alphabet + EXACT H-sec-4 bindings (neither ends in `.pass` so the patterned-match doesn't cover them; explicit entries needed).
- AC-5 (Codex review): APPROVE after 6 rounds. Findings narrowed: HIGH (INV-08 not enforced, INVEST coupling missing, A71 dependency incoherent, label vocabulary too loose, idempotency wording inconsistent) → MEDIUM (Linear duplicate tags pass; loader docstring stale; substring vs membership) → APPROVE.
- AC-6: PASS — 45 new tests in `tests/test_schemas_backlog_export.py` (1167 → 1212).

**US-S9-04 (`e209010`):**
- AC-1: PASS — adversarial_nfr_claim_contradiction_001/ ships 2 inputs (T2 ops runbook 4h SLA + T2 PM directive 30min SLA — same-tier so no auto-resolution per `reliability_tier_spec.md`). 9 expected_outputs CSVs + A48 + 4 phase3.*.pass markers + audit_expectations.json + fixture_metadata.json + README.md.
- AC-2: PASS — A51-CONFL-001 (IssueType=contradiction, BlockingStatus=hard, Severity=high) references both contradicted ClaimIDs. A60 cross-link rows for each direction. C-001 + C-002 ClaimStrength=0.0 (per a59 schema's contradiction-routed value — same-tier disagreement neutralizes the tier-derived 0.85). A62.NFR-PERF-001 with empty Target + non-empty Metric + A51Ref set (WHAT-vs-THRESHOLD asymmetry — only the THRESHOLD is contested). A70.STORY-001 with INVESTStatus=needs-negotiation + A51Ref. A71.TS-001 with AutomationStatus=deferred + A51Ref + Then-clause preserving BOTH literals ("4 hours" + "30 minutes"). A72: 2 a51-routed traces (one per contradicted claim).
- AC-3 (headline): PASS — `test_contradiction_propagates_to_every_phase3_artifact` mechanically pins the A59→A62→A70→A71→A72 propagation chain. A future regression where the chain silently picks one side of the contradiction fails this single test.
- AC-4 (anti-drift discipline): PASS — 4 anti-drift tests (numeric-token grounding for A70 + A71; banned-phrase pin for LLM-averaging compromises like "approximately 2 hours"; substring-vs-token regression pin via shared `_ungrounded_numeric_tokens` helper).
- AC-5 (Codex review): APPROVE after 7 rounds. Findings narrowed: 3 Must (A62 contract inconsistency; invented numerics; anti-drift discipline missing) → Must (stale text in 5 places after round-1 fix) → Must (NEW: tier policy violation T2 vs T4) → Must (ClaimStrength=0.0 for contested) → Should (1 README stale line) → APPROVE.
- AC-6: PASS — 35 new tests in `tests/test_integration_phase3_contradiction.py` (1212 → 1248).

**US-S9-05 (this commit):**
- AC-1: INV-08 / INV-09 / INV-10 added to `governance/immutable_invariants.md` per `docs/phase_3_plan.md` US-S9-05 statement.
- AC-2: Manifest `version` and `canonPolicyVersion.semver` both bumped to `1.1.0`. Manifest `description` updated to mention 28 skills + Phase-3 dev-handoff (NFRs / stories / test scenarios / traceability matrix / backlog-bridge).
- AC-3: Canon hash recomputed: `0d7654f6` → `d449ae74` (the immutable_invariants.md edit moved POLICY_GLOBS state).
- AC-4: Sprint 9 retro file (this) + `v1.1.0` CHANGELOG entry land. Tag `v1.1.0` placed on the bookkeeping commit.

## Tests / verification snapshot

- **1248 passed** at Sprint 9 close (was 1167 at Sprint 8 close; +81 across the sprint = 45 export tests + 35 contradiction tests + 1 incidental).
- **15 Codex review rounds** total across US-S9-01..03 + US-S9-04 (6 + 7 + 0 bookkeeping); both substantial USes reaching APPROVE.
- All 5 Phase-3 skills now real implementations (no scaffolds remain).
- Both happy-path (project_0001) AND adversarial (claim-contradiction) Phase-3 chains have committed regression baselines + integration tests.

## Patterns that proved out

- **Generalized cross-field handler reuse pays off across Phase 3.** The 5 cross-field handlers in `write_validator.py` (claim_type / measurability / provenance / invest / deferral) cover EVERY Phase-3 cross-field rule with zero new handler code in Sprint 9. The Linear export uses `_apply_provenance_rules` (INV-08 carry-through). The generic export uses both `_apply_provenance_rules` AND `_apply_invest_rules`. The Jira JSON export shape was the only place needing a new validator (`_validate_jira_export_json`) because it's structured JSON, not row-by-row CSV. Pattern generalizes to any future Phase-4+ schemas.

- **`x-bsa-deferral-rules` with configurable `status_field` works as designed.** A70 uses default (`AutomationStatus`); A72 overrides to `LinkType` via `status_field: "LinkType"`; both reuse the SAME `_apply_deferral_rules` handler. The next deferral-coupled schema gets enforcement for free.

- **Patterned H-sec-4 matches generalize.** `^phase3\.([a-z_]+)\.pass$` (added US-S8-01 round-3) covered phase3.test_scenario.pass + phase3.traceability.pass automatically. The two non-`.pass` terminal markers in Sprint 9 (`phase3.backlog_exported`, `pipeline.phase3.complete`) needed EXACT entries — same precedent as `pipeline.complete` etc. The pattern + EXACT-fallback mix is the right discipline.

- **Adversarial fixtures are MUCH harder than happy-path fixtures.** US-S9-04 needed 7 review rounds (vs US-S8-03's 4) because the adversarial surface includes:
  - Reliability-tier policy interactions (round 4 caught my T2/T4 fixture violating the `delta>=2 → auto-resolve` rule).
  - WHAT-vs-THRESHOLD asymmetry on A62 (round 1 caught my "Metric+Target both empty" claim that conflicted with the "only Target is contested" reality).
  - Contested-claim ClaimStrength rule (round 5 caught my retained 0.85 — should be 0.0 per the a59 schema's contradiction-routed value).
  - LLM-averaging banned phrases ("approximately 2 hours", "averaged SLA", "compromise window") — adversary surface that doesn't exist for happy-path fixtures.
  Lesson: budget **7-10 rounds** for any future adversarial fixture; the surface is genuinely larger.

- **First F5 dispatch on handoff/ went smoothly.** Pre-Sprint-9, F5 only gated `analysis/canonical/`. Adding 3 entries under `analysis/handoff/backlog_export_*` was a 6-line dispatcher change + 3 new schemas; zero changes to the dispatcher mechanics or hook script. Pattern: F5 generalizes to any path-pattern + schema pair.

## Lessons

- **Schema enforcement carries through end-to-end when extensions are explicit.** INV-08 is enforced at A70 (`x-bsa-provenance-rules`). It carries through to backlog exports because the export schemas DECLARE the same extension. The `_apply_provenance_rules` handler is schema-agnostic — it reads whatever extension the row's schema carries. Pattern: any contract that should propagate through a downstream artifact gets re-declared on that artifact, not passed implicitly.

- **"Surface as A51, don't block" is the right contract for Phase 3.** US-S9-04's PASS verdicts on the adversarial markers were initially counterintuitive — "isn't a contradiction supposed to FAIL?" — but the documented contract is that contradictions surface as A51 routes (route-able + reviewable + recoverable), not as pipeline failures (terminal + non-recoverable). The fixture verdicts reflect this. A future security workstream might add an opt-in "fail on hard A51" mode; that's a separate fixture.

- **Adversarial fixtures need their own anti-drift tests.** The happy-path project_0001 fixture has US-S8-03's no-new-numerics + banned-phrase guards. The contradiction fixture needed its own variant — same pattern but adversary-specific (e.g., banning "approximately 2 hours" because that's the LLM-averaged value of (4h + 30min)/2). Pattern: every fixture's anti-drift suite mirrors the happy-path discipline + adds drift classes specific to the fixture's adversary surface.

- **Each Codex round genuinely narrows the surface.** Across 15 rounds (US-S9-01..03 + US-S9-04), the average defect severity dropped monotonically — first review caught contract-level HIGH issues; last reviews polished doc consistency. By round 5 of either US, we were finding stale phrases in README files that contradicted the schema; by round 7 of US-S9-04, the only remaining defect was a single "non-zero ClaimStrength" line.

## What remains open (carried beyond Sprint 9)

From US-S9-01..03:
- `[TODO-S9-01-JIRA-CUSTOMFIELDS]` — explicit support for mapping A62 NFR IDs into Jira custom fields. v1.2 polish.
- `[TODO-S9-02-LINEAR-PROJECTS]` — Linear projects / cycles assignment. v1.2 polish.
- `[TODO-S9-03-GITHUB-PROJECTS]` — GitHub Projects v2 export format. v1.2 candidate.
- `[TODO-S9-LIVE-API]` — optional live-API mode. v1.3 candidate.

From US-S9-04:
- Block-on-contradiction failure mode (separate fixture, opt-in). v1.2.
- Multi-way contradictions (3+ sources). v1.2 extension fixture.
- Tier-delta auto-resolution case (T2 vs T4 → T2 wins silently, no A51 raised). v1.2 separate fixture.

From US-S8 carry-overs (still open):
- `[TODO-S8-01-X-ARTIFACT-NFR-COVERAGE]` — hook-layer enforcement of A71 Then-clause Metric/Target embedding via cross-artifact A62 lookup. Same pattern as `[TODO-S8-02-X-ARTIFACT-FK]`. Both deferred to a future cross-artifact validator pattern.
- `[TODO-S8-01-RUNNABLE-EXPORT]` — A71 → Cucumber/.feature exporter. v1.2.
- `[TODO-S8-02-INCREMENTAL-MATRIX]` — incremental A72 update for thousands-of-triples engagements. v1.2.

From the Sysco pilot (still open):
- IssueType `inventory_gap` + Severity `critical` enum extensions (separate from the v1.0.4+1 `RaisedByStage` extension that closed the discovery.dN drift). Pilot blockers — triage with operator on whether to extend the enums or remap.

## Release bookkeeping

- `sprint-8-close` tag remains at `2eeafed` (no retag).
- `v1.1.0` tag lands on the US-S9-05 bookkeeping commit (this commit + retro file + manifest bump + INV-08/09/10 codification).
- Manifest `version` field bumped to `1.1.0` (was `1.0.0` through all of v1.0.x).
- Canon policy version: `1.1.0+hash:d449ae74` (semver bump + hash recomputation).
- 28 skills total (was ~23 at v1.0.0 baseline; +5 Phase-3 skills implemented across Sprints 6-9: bsa-nfr-collector, bsa-story-writer, bsa-test-scenario-builder, bsa-traceability-matrix, bsa-backlog-bridge).
- 1248 tests total (was ~302 at v1.0.0 baseline; +946 across the v1.0.x patch line + Sprint 6-9 Phase-3 work).

## Related

- Sprint 6, 7, 8 retros: `docs/retros/sprint_6.md`, `sprint_7.md`, `sprint_8.md`.
- v1.0.x tail: `sprint_5_v1_0_2_hotfix.md`, `_v1_0_3_polish.md`, `_v1_0_4_ux_pass.md`.
- Phase-3 plan: `docs/phase_3_plan.md` (US-S9-01..05 scope — all five closed in this sprint).
- Codex review outputs preserved as `/tmp/codex_out_*_us9_0{1_03,4}_cr*.txt` (15 review files across the sprint).
- Adversarial fixture: `fixtures/golden/adversarial_nfr_claim_contradiction_001/`.
- Happy-path Phase-3 fixture: `fixtures/golden/project_0001/` (Sprint 8 US-S8-03).

Phase 3 is feature-complete. Next: pilot the v1.1.0 release on a real engagement (Sysco or new). Bug-fix work goes into v1.1.x; new feature work (e.g., Phase-4 if defined) goes into v1.2.0.
