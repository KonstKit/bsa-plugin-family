---
name: bsa-test-scenario-builder
description: Build Gherkin-style Given/When/Then test scenarios in A71_test_scenario_register.csv from promoted A70 stories and measurable A62 NFRs. Every scenario MUST trace to exactly one A70 story (INV-10). NFR-bound scenarios MUST reference the NFR's Metric (paraphrase OK) and contain the literal Target string from A62 (whatever shape A62 stored — comparator+number, value+unit, etc.) in the Then-clause. AutomationStatus=deferred rows co-populate A51Ref. Phase 3 skill — runs after phase3.story.pass, before phase3.traceability.
---

# BSA Test Scenario Builder

Run this skill after `bsa-story-writer` has promoted `A70_story_register.csv`. Produces test scenarios that downstream skills (`bsa-traceability-matrix`, `bsa-backlog-bridge`) consume.

## Scope

- Read promoted A70 (stories) + A62 (NFRs) + A59 (claims, for Given-clause grounding) + A51 (route open deferrals).
- Author Gherkin-style Given / When / Then scenarios in `A71_test_scenario_register.csv`. Each scenario keys to exactly one story (`SourceStoryID`); composite scenarios must split.
- For each acceptance criterion in a story, generate at least one scenario covering the happy path. Add scenarios for boundary conditions / negative paths when the criterion implies them (e.g., a "within 60s" criterion implies both an "exactly at SLA" scenario and a "past SLA" rollover scenario).
- For each measurable NFR (`Metric` + `Target` populated), produce at least one verification scenario whose Then-clause references the NFR's Metric (paraphrase OK — humans don't write snake_case identifiers in Gherkin) AND contains the NFR's literal Target string (whatever shape A62 stored for that row — `< 500`, `>= 99.9`, `500 ms`, etc.). The metric NAME may be paraphrased; the Target string must appear literally because that's what becomes a runnable test threshold. NFR-only scenarios (no functional story driver) are NOT supported by A71 — instead, route via the NFR's home story (A70 row that links the NFR via `RelatedNFRIDs`).

Out of scope:
- Runnable test code (Cucumber, pytest-bdd, Jest, etc.) — the register is intent-level; runnable export is a separate skill (open question for v1.2 polish).
- Test-data generation — scenarios reference data shapes by name, not by literal content.
- Test orchestration / suite layout — that's a CI concern; the register is a flat list of scenarios with Tags for grouping.

## Inputs

- Promoted `analysis/canonical/core_controls/A70_story_register.csv`
- Promoted `analysis/canonical/core_controls/A62_nfr_register.csv` (for NFR Metric+Target lookup)
- Promoted `analysis/canonical/core_controls/A59_claim_register.csv` (for Given-clause grounding evidence)
- Shared `analysis/canonical/core_controls/A51_issue_route_register.csv` (for raised deferral routes)

## Outputs

- `analysis/proposals/phase3/A71_test_scenario_register.csv`
- `analysis/proposals/phase3/test_scenario_authoring_report.md`

Both land under `analysis/proposals/phase3/`. Promotion to canonical goes through `/bsa-promote` with the two-key gate (provenance check on `SourceStoryID` + `phase3.test_scenario.pass` marker).

## Workflow

1. **Load inputs.** Read promoted A70, A62, A59, A51. Fail fast if A70 is not promoted (`phase3.story.pass` marker absent — point at `bsa-story-writer`).

2. **Iterate stories.** For each row in A70, walk its `AcceptanceCriteria` field (semicolon / newline separated). Each criterion is a candidate scenario seed.

3. **Author Given clause.** Ground in the story's `Persona` + the upstream A59 claim's setting (look up `SourceClaimIDs[0]` in A59 for the claim's subject + scenario context). Multi-clause Given: join with ` AND `. Avoid implementation detail — describe observable system / workspace state.

4. **Author When clause.** Single trigger event per scenario. If the criterion implies multiple actions, split into multiple scenarios. Use present-tense verbs; no "and then" chains.

5. **Author Then clause.** Observable, testable outcome.
   - **Functional scenario** (no `RelatedNFRID`): describe the observable state change (e.g., "the ticket transitions to `acknowledged`").
   - **NFR-bound scenario** (`RelatedNFRID` populated): MUST reference the linked A62 row's `Metric` (a clear paraphrase of the metric name is acceptable) AND contain the linked NFR's literal `Target` string (whatever A62 stored for that row — comparator+number like `< 500`, value+unit like `500 ms`, etc.). Example: NFR-PERF-001 with `Metric='p95 latency ms'`, `Target='< 500'`. The Then-clause must contain a recognizable reference to the metric AND the literal Target string (e.g., "the page-latency p95 is `< 500` ms over a 10-minute window" — `latency p95` paraphrases the metric name; `< 500` is the literal Target). Documentary-only at the schema layer (`x-bsa-nfr-coverage-rules`); the skill MUST self-validate before write.

6. **Set Tags.** `@smoke` for must-run-on-every-build scenarios (typically Priority=level-1 + AutomationStatus in {automated, partial}). `@perf`, `@critical`, `@regression` etc. as natural categories. Tag vocabulary is open but lowercase + hyphen/underscore + `@` prefix.

7. **Set Priority.** Inherits from `SourceStoryID`'s Priority by default. May be raised (never lowered) with A51 rationale (e.g., scenario authoring surfaces a regression risk the story didn't see).

8. **Set AutomationStatus.**
   - `automated` — runnable test exists in CI today.
   - `partial` — automation exists but covers a subset of the assertion (e.g., the 60s SLA is checked but only on synthetic traffic, not production-like).
   - `manual` — scripted manual test, not automated.
   - `not-automated` — explicitly chosen manual-forever (compliance scenarios, exploratory checks).
   - `deferred` — automation blocked on something external (test environment, data, tooling). MUST co-populate `A51Ref` with a `decision_needed` route. Enforced by `x-bsa-deferral-rules` at hook time.

9. **Populate `SourceStoryID`.** Single STORY-NNN id from A70. Composite scenarios are forbidden — split into multiple A71 rows, each keyed to its primary story.

10. **Emit artifact + report.** Write `A71_test_scenario_register.csv` and `test_scenario_authoring_report.md`. Report sections:
    - Stories scanned + scenarios authored.
    - AutomationStatus distribution.
    - NFR coverage report: which A62 measurable NFRs got at least one verification scenario; which were missed.
    - Story coverage report: which A70 stories got at least one scenario; which were missed.
    - A51 routes raised (deferred scenarios + raised regression risks).

## Invariants

- **INV-10 (Phase 3, NEW in Sprint 8)** — `SourceStoryID` non-empty on every row. Enforced by schema (pattern + required) + write-validator at hook time.
- **NFR-coverage rule** — when `RelatedNFRID` is non-empty, the Then-clause MUST reference the linked A62 row's `Metric` (paraphrase OK) AND contain its literal `Target` string (whatever shape A62 stored for that row). Documented in `x-bsa-nfr-coverage-rules`; enforced by this skill's own output validator (cross-artifact lookup outside F5 path-bound dispatch). Future hook-layer enforcement is filed as `[TODO-S8-01-X-ARTIFACT-NFR-COVERAGE]`.
- **Deferral coupling** — `AutomationStatus == 'deferred'` requires non-empty `A51Ref`. Generalized version of A70's INVEST-A51 coupling; enforced by `write_validator._apply_deferral_rules`.
- **No net-new claims** — scenarios reshape acceptance criteria into Gherkin form; they MUST NOT introduce subjects / verbs / conditions absent from upstream claims. Mirrors INV-03; checked at promotion via the no-new-stories auditor pattern.

## Failure modes

- **A70 not promoted** — skill exits with error pointing to `bsa-story-writer` / `phase3.story.pass`.
- **Story has no acceptance criteria** — should not happen (A70 schema enforces non-empty `AcceptanceCriteria`); if it does, skill raises an A51 `missing_source` route against the story and skips.
- **Measurable NFR with no story driver** — skill cannot author an A71 row for an unbound NFR. Flag in the report under "NFR coverage gaps"; the upstream `bsa-story-writer` must add a story that links the NFR (or operator must create one manually + promote).
- **NFR-bound scenario where the Then-clause does not embed Metric+Target** — skill self-rejects + retries with corrected Then-text; if still failing after 2 retries, raises an A51 `missing_source` against the NFR.
- **Composite scenario candidate** — split into multiple rows; never emit a scenario with multiple When-actions or with `SourceStoryID` listing more than one id.

## Composition

Invoked by `/bsa-dev-handoff` (Phase-3 composite command) as the third stage: `phase3.nfr → phase3.story → phase3.test_scenario → phase3.traceability → phase3.backlog_exported`.

May also be invoked directly via `/bsa-dev-handoff --only=test-scenario` for debugging / partial re-runs; prerequisites (phase3.story.pass + promoted A70) must be satisfied.

Downstream consumers (`bsa-traceability-matrix`, `bsa-backlog-bridge`) read the promoted A71; they do not invoke this skill directly (INV-06 composition-via-orchestrator).

## Cross-refs

- `governance/schemas/a71.schema.json` — row schema + deferral + NFR-coverage extensions.
- `skills/bsa-story-writer/SKILL.md` — upstream story authoring contract.
- `skills/bsa-nfr-collector/SKILL.md` — upstream NFR authoring contract.
- `skills/bsa-no-new-claims-auditor/SKILL.md` — the main-cycle equivalent of the no-new-claims discipline applied to scenarios at promotion gate.
- `docs/phase_3_plan.md` — Phase-3 sequencing + Sprint 8-9 scope.
- `commands/bsa-dev-handoff.md` — composite command that invokes this skill.

## Open follow-ups

- `[TODO-S8-01-X-ARTIFACT-NFR-COVERAGE]` — hook-layer enforcement of NFR Metric+Target embedded in Then-clause requires a cross-artifact validator (read A62 at hook time when validating A71). Currently rule is documentary at the schema layer + skill-self-validated. Land in a follow-up sprint when a cross-artifact validator pattern is established (US-S8-02 or later).
- `[TODO-S8-01-RUNNABLE-EXPORT]` — runnable test export (Cucumber `.feature` files, pytest-bdd, Jest) is a v1.2 candidate. Schema is already runnable-friendly (Gherkin shape); the export step is a small generator skill.
- `[TODO-S8-01-NEGATIVE-PATH-HEURISTICS]` — heuristics for auto-suggesting boundary / negative scenarios when the acceptance criterion uses temporal ("within X seconds"), boundary ("at least N"), or comparison ("more than M") language.
