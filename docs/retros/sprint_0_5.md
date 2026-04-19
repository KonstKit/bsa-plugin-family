# Sprint 0.5 Retrospective — Foundation Completion

**Window:** Sprint 0.5 (week 3 of the 12-week Phase 0-2 roadmap).
**Tag target:** `v0.9.1-foundation-complete` (created on HEAD once this retro commit is codex-approved).
**Canon policy version:** 0.9 (unchanged from Sprint 0; will bump at Sprint 1 with bsa-context-framer).

## What was delivered

| User story | Status | Commit(s) | Review rounds |
|---|---|---|---|
| US-S05-02 — routing manifest + schema + validator + CI wire | done | `5fe37d6` | 4 |
| US-S05-01 — golden fixture #1 + fixture_runner.py + metadata | done | `72ce283` | 3 |

Plus: `docs/retros/sprint_0_5.md` (this file). `v0.9.1-foundation-complete` git tag is created immediately after this retro commit is codex-approved (tagging is a post-commit git-ref operation; see exit-criteria checklist below).

## Acceptance criteria coverage

- **US-S05-02 AC-1..AC-4:** all met.
  * AC-1: manifest has both `bsa_pack_direct_mixed_sources` (14-skill worker_set) and `discovery_pack_mixed_sources` (9-skill worker_set), exactly matching `bsa-orchestrator/SKILL.md:38-63`.
  * AC-2: `request_skill_routes.schema.json` is Draft 2020-12; stdlib validator enforces shape, type, patterns, ident forms, and `additionalProperties: false` at every nesting level (top-level, routes, conditional_workers, sidecars).
  * AC-3: validator checks schema conformance, per-route completeness, cross-reference to `skills/<name>/SKILL.md`, orchestrator presence, request_type uniqueness, sidecar uniqueness.
  * AC-4: CI step `Routing manifest validator (US-S05-02)` in `project-validators` job; any invalid routing (missing skill, missing orchestrator, malformed JSON, type violation) fails CI.
- **US-S05-01 AC-1..AC-5:** met within Phase-0 honesty re-scope.
  * AC-1 re-scoped: fixture is hand-authored shape-level-representative, not a live pipeline run. Re-scope documented in `fixtures/golden/project_0001/README.md` with plan to capture live-run fixtures in Sprint 4.5. Codex review approved this scope explicitly.
  * AC-2: fixture contains `inputs/`, `expected_outputs/canonical/`, `expected_markers/`, `audit_expectations.json`, `fixture_metadata.json` and `README.md`.
  * AC-3: `scripts/fixture_runner.py --mode=compare` passes on committed baseline.
  * AC-4: every A59 row has `SourceID+ExcerptID` OR `A51Ref` (INV-01); runner enforces this for every `ClaimType` including `analyst_judgment`.
  * AC-5: `fixture_metadata.json` carries `model_used`, `model_version_hash`, `canon_policy_version`, `plugin_version`, `captured_at`; runner requires all fields.

## Metrics

- **Test count:** 98 tests total (21 skill-lint + 29 privacy + 25 routing + 23 fixture). Growth path across the sprint: started at 15 fixture tests (US-S05-01 first commit), grew to 22 during the round-2 hardening pass, then to 23 when the retro round added the `captured_at` regression.
- **Actual latest total:** 98 tests pass in ~3s on Python 3.9.6.
- **Scripts added Sprint 0.5:** 2 (`validate_request_skill_routing.py`, `fixture_runner.py`).
- **Config + schema + fixture files added:** 10+ (routing manifest, schema, per-fixture canonical artifacts, markers, metadata).
- **Codex review rounds per commit:** 4 (routing), 3 (fixture). Total: 7 rounds across 2 approved commits.

## What went well

- **Routing manifest turned out well-shaped.** The stdlib-only validator grew from a simple shape check to a full nested-property enforcer across 4 review rounds, closing every corner case codex identified (bool-subclass trap, `TypeError` on non-string workers, unknown-key bypass at conditional_workers/sidecars levels, schema parity for `$schema`/`_description`/`runtime_notes`).
- **Fixture-runner invariants are not lip service.** Adversarial mutation tests (missing evidence binding, analyst_judgment without justification, ClaimType outside the enum, ExcerptID not in A58, A51Ref not in A51, locator out of range, locator escaping inputs/) each produce a specific finding code. Future contributors cannot accidentally drop an invariant without CI noticing.
- **Honesty note worked.** The Sprint-0 plan rev2 called out that Phase 0 lacks a live orchestrator harness and re-scoped AC-1 to "shape-level representative". Codex explicitly accepted the re-scope on first read rather than pushing back — the plan rev2 language prepared the ground correctly.
- **Locator containment caught a real security-shaped bug.** Path traversal via `../fixture_metadata.json:L1` would have silently passed the is_file() check before round 3. Adding the `resolve() + relative_to()` pattern closed it with a small diff.

## What was harder than expected

- **Each validator hardening step uncovered the next.** Round 1 of routing fixed 4 issues; round 2 then surfaced 1 sibling issue; round 3 surfaced the next parity gap; round 4 surfaced the nested-additionalProperties hole. Not a process failure — codex is doing exactly what a strict reviewer should — but worth noting that stdlib-only schema enforcement is verbose enough that it pays to write it defensively from the start next time (e.g., via a generic `_require_keys_subset` helper instead of per-site loops).
- **Self-reference filter on analyst_judgment.** The `upstream_refs` check originally allowed `C-008` to reference itself as its own upstream — codex caught it on fixture round 1. Fix is one line (`[r for r in refs if r != own_id]`), but it is the kind of edge that only shows up when you try to break the fixture on purpose.
- **Fixture locator accuracy.** My first fixture had three locators pointing at wrong line ranges (E-002 L10-L12 vs real L10, E-003 L14-L18 vs real L12-L16, E-004 L20 vs real L18). The fix was trivial once the runner enforced range validation — which itself was a round-2 addition. Lesson: when crafting a synthetic fixture, validate locators against the real files *as you write them*, not at the end.

## Carry-over into Sprint 1

- **bsa-context-framer skill** (US-S1-01): close the Stage 2 runtime-native gap. Routing manifest already has a runtime_notes entry flagging the upcoming addition of this worker to `bsa_pack_direct_mixed_sources`.
- **Fixture update on Sprint 1 merge:** once Stage 2 worker lands, `project_0001` needs Stage 2 expected_outputs (context_state_frame, stakeholder_authority_map, system_context_seed, constraints_dependencies_route, stage2_summary.json) and a `stage2.context_state.pass.json` marker. Routing manifest needs `bsa-context-framer` in the direct-mode worker_set.
- **CI runtime so far:** ~3s worth of tests + validators. Still well under the 5-min per-job timeout.

## Phase 0 exit criteria (combined Sprint 0 + Sprint 0.5)

- [x] All US-S0-* + US-S05-* AC passed
- [x] CI workflow authored; all steps pass local dry-runs (validators, pytest, c4 fixtures, bpmn xmllint, inot smoke, routing, fixture runner). Remote GitHub Actions run pending first push.
- [x] Inventory + privacy reports reviewed
- [x] Golden fixture #1 runnable + comparable
- [x] Routing manifest validator in CI
- [x] `v0.9.0-foundation` tag (Sprint 0 exit)
- [ ] `v0.9.1-foundation-complete` tag — to be created on approved HEAD of this retro commit

Phase 0 complete after `v0.9.1-foundation-complete` is pushed. Sprint 1 begins immediately after: new skill `bsa-context-framer` closing the Stage 2 gap, with its own dedicated SKILL.md, references, and validation bindings `SCN-STAGE2-001-A..C`.
