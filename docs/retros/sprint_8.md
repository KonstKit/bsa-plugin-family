# Sprint 8 Retrospective — bsa-test-scenario-builder + bsa-traceability-matrix + Phase-3 integration

**Window:** Single sprint, three user stories landed in sequence after v1.0.4+1 polish closed.
**Tag target:** `sprint-8-close` on commit `2eeafed`.
**Canon policy version at Sprint 8 close:** `1.0.3+hash:3c32c861` (was `0d4d1de4` at v1.0.3 / Sprint 7 close; bumped twice during US-S8-01 + US-S8-02 from POLICY_GLOBS edits to two SKILL.md files + runtime-marker-schema.md + the manifest's recorded hash).

## Why this sprint

Sprint 6 + 7 delivered the first two real Phase-3 skills (`bsa-nfr-collector`, `bsa-story-writer`). Sprint 8 was the closing pair on the canonical-artifact side of Phase-3: `bsa-test-scenario-builder` + `bsa-traceability-matrix`, plus the integration test that proves the whole D→Stage1..8→Phase-3 chain hangs together end-to-end on the project_0001 golden fixture.

After Sprint 8, only `bsa-backlog-bridge` (Sprint 9) remains scaffold; Phase-3 schema infrastructure + cross-artifact discipline is fully in place.

## What was delivered

| US | Surface | Commit | Codex rounds | Result |
|---|---|---|---|---|
| US-S8-01 | A71 schema + bsa-test-scenario-builder + cross-field handler `_apply_deferral_rules` (generalized status+A51 coupling) + marker `phase3.test_scenario.pass` + H-sec-4 patterned-match for `phase3.<sub>.pass` (closes pre-existing gap for nfr.pass + story.pass too) | `e533475` | 8 | APPROVE |
| US-S8-02 | A72 schema + bsa-traceability-matrix + REUSED `_apply_deferral_rules` with `status_field='LinkType'` override + marker `phase3.traceability.pass` (auto-bound via existing patterned-match) | `87007a0` | 4 | APPROVE |
| US-S8-03 | project_0001 fixture extended with A62/A70/A71/A72 + 4 phase3 markers + 29-test integration suite mechanically pinning the cross-artifact join | `2eeafed` | 4 | APPROVE |

Plus: this retro file + `sprint-8-close` tag (pending).

Cumulative: **+109 tests** across the sprint (1057 → 1167); zero regressions.

## Acceptance criteria coverage

**US-S8-01 (`e533475`):**
- AC-1: PASS — `governance/schemas/a71.schema.json` (12 columns; INV-10 SourceStoryID required-singular pattern; LinkType-style enums; `x-bsa-deferral-rules` + `x-bsa-nfr-coverage-rules` extensions).
- AC-2: PASS — `_apply_deferral_rules` generic handler in `governance/schemas/write_validator.py` (configurable `status_field` + `requires_a51_when_status`); wired into `_make_csv_validator` per-row loop alongside the four pre-existing handlers.
- AC-3: PASS — `phase3.test_scenario.pass` added to `marker_id` + `phase3.test_scenario` to `stage` enums in `marker.schema.json`; H-sec-4 patterned-match `^phase3\.([a-z_]+)\.pass$` added to `_expected_stage_verdict` (incidentally also closes the pre-existing binding gap for `phase3.nfr.pass` + `phase3.story.pass` from Sprints 6-7).
- AC-4 (Codex review): APPROVE after 8 rounds. Findings narrowed: HIGH `_comment` lying about non-existent handler → MEDIUM literal-vs-paraphrase Target wording → MEDIUM H-sec-4 binding hole + A71/A62 contract mismatch → MEDIUM orphan-recovery guidance + missing positive-assertion → MINOR doc staleness / underscore-vs-hyphen / marker-block staleness → APPROVE.
- AC-5: PASS — 33 new tests in `tests/test_schemas_a71.py` + 3 shape-pin tests in `tests/test_schemas_write_validator.py` (1070 → 1106).

**US-S8-02 (`87007a0`):**
- AC-1: PASS — `governance/schemas/a72.schema.json` (8 columns; all ID fields singular; LinkType enum narrowed to 3 values after round-2 dropped `inferred` to enforce row-identity uniqueness; `x-bsa-deferral-rules` REUSES the generalized handler with `status_field='LinkType'` override).
- AC-2: PASS — Foreign-key + claim-source-consistency invariants pinned via `x-bsa-foreign-key-rules.applies_to_all_rows: true` (round-2 explicit pin against re-introducing LinkType-class exemptions).
- AC-3: PASS — `phase3.traceability.pass` marker added; H-sec-4 binding works automatically through the US-S8-01 patterned-match (no code change).
- AC-4 (Codex review): APPROVE after 4 rounds. Findings: MEDIUM internal contradiction (placeholder rows for unresolved IDs vs schema requiring resolved) → MEDIUM duplicate-row drift via `inferred` LinkType + a51-routed exemption from FK/consistency → MEDIUM standalone `--only=traceability` prereqs missing A62 → APPROVE + LOW (closed inline) on stale A71-facing docs claiming bsa-traceability-matrix consumes A71.
- AC-5: PASS — 30 new tests in `tests/test_schemas_a72.py` + 2 shape-pin tests in `tests/test_schemas_write_validator.py` (1106 → 1138).

**US-S8-03 (`2eeafed`):**
- AC-1: PASS — `fixtures/golden/project_0001/expected_outputs/canonical/core_controls/` extended with A62 (2 rows), A70 (3 rows), A71 (3 rows), A72 (4 rows). All evidence-grounded in the existing main-cycle A50/A59 content (round-1 fix forced by Codex).
- AC-2: PASS — Four `expected_markers/phase3.{nfr,story,test_scenario,traceability}.pass.json` markers, all passing F5 + H-sec-4.
- AC-3: PASS — `audit_expectations.json` extended with phase3 verdicts, KPI-006 bound (story-to-claim coverage = 1.00), expected_phase3_counts, expected_orphans (4 A59 claims without A72 row including C-008 by-design), 4 new INV invariants.
- AC-4: PASS — `tests/test_integration_phase3_project_0001.py` (29 tests) covers F5 schema validation for every Phase-3 artifact + marker, cross-artifact FK resolution, claim-source consistency, row-identity uniqueness, audit-expectations-vs-fixture drift, INV-09/10/KPI-006 spot pins, AND the headline US-S8-03 acceptance: every A71 scenario links back to claim+source through A72.
- AC-5: PASS — 3 anti-drift tests catch invented numerics + invented mechanism keywords (round-1 + round-2 + round-3 fixes) using a shared `_ungrounded_numeric_tokens` helper that the regression pin exercises directly (round-3 fix).
- AC-6 (Codex review): APPROVE after 4 rounds. Findings: MAJOR fixture drift (net-new conditions like "60 seconds" / "non-empty repro-steps field" / "threshold X" violating reshape contracts) → MEDIUM substring-vs-token bug in drift test → MEDIUM regression pin doesn't exercise production code path → APPROVE.

## Tests / verification snapshot

- **1167 passed** at Sprint 8 close (was 1057 at v1.0.4 / Sprint 7 close; +110 = 33 + 30 + 29 integration + 18 mixed write-validator pins / regression pins added across the three USes plus 0 regressions).
- **16 Codex review rounds** total across the three commits (8 + 4 + 4); all reaching APPROVE.
- Canon hash advanced through several intermediate values during the sprint (the manifest tracks the most recent: `3c32c861` after the US-S8-02 round-4 LOW closed inline; US-S8-03 added no POLICY_GLOBS edits so hash stayed put through that commit).
- `bsa doctor` against the project_0001 fixture (symlinked into a tmp workspace) is now expected to surface the full Phase-3 chain as clean — first end-to-end fixture that validates the F5 + cross-artifact + marker discipline together.

## Patterns that proved out

- **Generalized cross-field handler reuse.** US-S8-01 added `_apply_deferral_rules` with a configurable `status_field` (defaulting to AutomationStatus for A71). US-S8-02 just declared `"status_field": "LinkType"` in the A72 schema — zero new handler code, zero new tests for the handler itself, just shape pins for the configuration. The **5 cross-field handlers now in `write_validator.py`** (claim-type / measurability / provenance / invest / deferral) are the foundation for any future Phase-3+ schema; new schemas adopting an existing pattern get enforcement for free.

- **Patterned H-sec-4 matches generalize.** US-S8-01 round-3 added `^phase3\.([a-z_]+)\.pass$` → ("phase3.<sub>", "PASS"). US-S8-02 added `phase3.traceability.pass` to the marker enum and the binding worked automatically — no code change to `_expected_stage_verdict`. The pattern also retroactively closed the same-class binding gaps for `phase3.nfr.pass` + `phase3.story.pass` from Sprints 6-7 (regression tests added incidentally).

- **Documentary cross-artifact extensions + skill self-validation.** Two cross-artifact rules landed as DOCUMENTARY at the schema layer: `x-bsa-nfr-coverage-rules` (A71 Then-clause references NFR Metric+Target) and `x-bsa-foreign-key-rules` (A72 IDs resolve in A70/A59/A50; claim-source consistency). Both deferred to skill self-validation because F5's path-bound dispatch can't reach sibling artifacts at write time. This is fine for now (the skills self-validate before write; the integration test US-S8-03 mechanically pins the rules at fixture-promotion time), but it points at a future cross-artifact validator pattern that would let F5 enforce these rules at hook time. Filed as `[TODO-S8-01-X-ARTIFACT-NFR-COVERAGE]` + `[TODO-S8-02-X-ARTIFACT-FK]` for v1.2 polish.

## Lessons

- **Fixture authoring is harder than schema authoring.** US-S8-03 needed 4 Codex rounds because the FIRST draft of the Phase-3 fixture rows silently violated the "no net-new subjects/verbs/conditions" reshape contract — exactly the discipline the bsa-story-writer + bsa-test-scenario-builder skills are supposed to enforce. The schema + skill spec pass review fine, but writing CONTENT that respects them requires extra scrutiny. Two complementary anti-drift mechanisms ended up landing in this sprint: the **numeric-token grounding test** (every numeric in A70/A71 must come from upstream A59/A62/A51) and the **banned-phrase lexical pin** (curated list of LLM-elaboration phrases). Future Phase-3 fixture additions get both guards for free.

- **Token-set vs substring is a recurring bug.** Codex round-2 caught my "every numeric token in downstream MUST appear in upstream corpus" check using `assert token in corpus_string` — substring semantics let `"24"` falsely pass when corpus contained only `"240"`. Round-3 caught my regression pin against this check that didn't actually exercise the production code path. The fix was to extract a `_ungrounded_numeric_tokens(downstream_text, upstream_tokens) -> list[str]` helper that BOTH the production checks AND the synthetic pin call — single source of truth, future revert to substring matching fails both. Pattern generalizes: any "X must appear in Y" assertion is suspicious; check whether you mean substring or token-set; pick a primitive that makes the distinction explicit.

- **Each Codex round narrows.** US-S8-01 needed 8 rounds (the most so far), but each round caught a strictly more subtle defect than the previous: Round 1 was a flat-out lying comment; round 8 was an underscore-vs-hyphen typo in a usage example. By round 4-5 we were polishing doc consistency, not finding correctness bugs. This is the right shape — the high-impact defects surface early, and the long tail is hygiene. Budget guidance for future write-side / cross-artifact USes: **5-8 rounds**.

- **The integration test substitutes for a real cross-artifact validator.** US-S8-03's `tests/test_integration_phase3_project_0001.py` doesn't run at hook time — it runs in CI / `pytest`. So the cross-artifact integrity rules (FK resolution, claim-source consistency, NFR-coverage) are enforced on the FIXTURE but not on a live workspace. That's an acceptable trade for now (skills self-validate; pilot engagements would catch via `bsa doctor` walks) but the eventual cross-artifact validator pattern should reuse the same logic.

## What remains open (carried beyond Sprint 8)

- **`[TODO-S8-01-X-ARTIFACT-NFR-COVERAGE]`** — hook-layer enforcement of A71 Then-clause referencing A62 Metric + literal Target. Documentary today; skill-self-validates; integration test pins on fixture. Future cross-artifact validator pattern needed.

- **`[TODO-S8-02-X-ARTIFACT-FK]`** — hook-layer enforcement of A72 foreign-key resolution + claim-source consistency. Same deferral pattern; same future home.

- **`[TODO-S8-02-INCREMENTAL-MATRIX]`** — incremental A72 update (vs full re-build) for engagements with thousands of triples. v1.2 polish.

- **`[TODO-S8-02-LINK-STRENGTH-OVERRIDE]`** — A51 IssueType for explicit operator override of LinkStrength. v1.2 polish.

- **`[TODO-S8-01-RUNNABLE-EXPORT]`** — A71 → Cucumber `.feature` / pytest-bdd / Jest exporter. v1.2 candidate (separate generator skill).

- **`[TODO-S8-01-NEGATIVE-PATH-HEURISTICS]`** — auto-suggest boundary / negative scenarios from temporal/comparison phrasings in A70 acceptance criteria. v1.2 polish.

- **Sysco pilot follow-up** — IssueType `inventory_gap` + Severity `critical` enum drifts (separate from the v1.0.4+1 RaisedByStage extension that closed the discovery.dN drift). Pilot blockers triaged with operator: either accept as enum extensions or remap to existing values.

## Release bookkeeping

- Sprint 6, 7 retros remain at their original commits.
- `sprint-8-close` tag lands on `2eeafed` (US-S8-03 commit, last of the Sprint 8 commits).
- Manifest `version` field stays at `1.0.0` through Sprint 8 — bumped to `1.1.0` at Sprint 9 close (Phase-3 release).
- Canon hash at Sprint 8 close: `3c32c861`.
- 4 of 5 Phase-3 skills are now real implementations (`bsa-nfr-collector` Sprint 6, `bsa-story-writer` Sprint 7, `bsa-test-scenario-builder` Sprint 8 US-S8-01, `bsa-traceability-matrix` Sprint 8 US-S8-02). Only `bsa-backlog-bridge` remains as scaffold (Sprint 9).

## Related

- Sprint 6, 7 retros: `docs/retros/sprint_6.md`, `docs/retros/sprint_7.md`.
- v1.0.x tail: `docs/retros/sprint_5_v1_0_2_hotfix.md`, `_v1_0_3_polish.md`, `_v1_0_4_ux_pass.md`.
- Phase-3 plan: `docs/phase_3_plan.md` (US-S8-01/02/03 scope — all three closed).
- Codex review outputs preserved as `/tmp/codex_out_*_us8_0{1,2,3}_cr*.txt` (16 review files across the sprint).

Next: Sprint 9 — `bsa-backlog-bridge` (Jira/Linear/generic exporters) + `v1.1.0` release cut with Phase-3 closed. Per `docs/phase_3_plan.md` US-S9-01..05.
