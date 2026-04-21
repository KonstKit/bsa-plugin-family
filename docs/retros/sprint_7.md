# Sprint 7 Retrospective — bsa-story-writer End-to-End

**Window:** Sprint 7 (second substantive sprint of Phase 3; Sprint 6 delivered kick-off + nfr-collector, Sprint 7 delivers story-writer).
**Tag target:** No sprint-end tag. Sprint 7 is work-in-progress toward v1.1.0 at Sprint 9 close.
**Canon policy version at Sprint 7 close:** `1.0.1+hash:0d4d1de4` — hash advanced from `76ef3c0a` (Sprint 6 close) because `marker.schema.json` gained the two phase3.* markers + `runtime-marker-schema.md` documented them.

## What was delivered

| User story | Status | Commit(s) | Review rounds |
|---|---|---|---|
| US-S7-01 — A70 story schema | done | `d39a39c` | 0 |
| US-S7-02 — bsa-story-writer full implementation (replaces scaffold) | done | `d39a39c` | 0 |
| US-S7-03 — no-new-stories auditor + INV-08 enforcement tests | done | `d39a39c` | 0 |
| Incidental — phase3.nfr.pass + phase3.story.pass in marker schema | done | `d39a39c` | 0 |

Plus: `docs/retros/sprint_7.md` (this file).

## Acceptance criteria coverage

**US-S7-01** (4 ACs):
- AC-1: PASS — `governance/schemas/a70.schema.json` with 12 required columns; StoryText pattern enforces canonical "As a <persona>, I want <goal>..." shape; StoryID follows STORY-NNN / STORY-XXX-NNN pattern family.
- AC-2: PASS — INVESTStatus enum (6 values: pass / needs-splitting / needs-estimation / needs-testable-acceptance / needs-negotiation / escalate). EstimationHint enum (xs/s/m/l/xl/unknown).
- AC-3: PASS — extension properties document cross-field rules (`x-bsa-provenance-rules` for INV-08, `x-bsa-invest-rules` for INVEST-A51 coupling, `x-bsa-banned-story-patterns` for 6 anti-patterns).
- AC-4: PASS — loader `iter_a70_rows` + write-validator dispatcher A70 entry. F5 hook mechanically enforces from the moment of landing.

**US-S7-02** (3 ACs):
- AC-1: PASS — `skills/bsa-story-writer/SKILL.md` rewritten from Sprint-6 scaffold to production spec. 8-step workflow including INVEST handling + A51 routing for deferred criteria.
- AC-2: PASS — `skills/bsa-story-writer/references/story-authoring-contract.md` with 8 derivation rules, banned anti-patterns table, INVEST criterion-to-status mapping, report shape, acceptance criteria.
- AC-3: PASS — skill-lint 28/28 passes (bsa-story-writer still compliant after rewrite; no regressions across other skills).

**US-S7-03** (4 ACs):
- AC-1: PASS — `scripts/validate_no_new_stories.py` implements three finding classes: STORY_PROVENANCE, STORY_DANGLING_REF, STORY_LEAKAGE.
- AC-2: PASS — Leakage detection uses >= 4-char word tokens, curated stop-word list, and corpus = claim Statement + JustificationRationale + linked A58 ExcerptText + linked NFR Statement/Metric/Target/TestabilityNotes.
- AC-3: PASS — 10 regression tests in `tests/test_validate_no_new_stories.py` covering empty workspace, clean cases, all three finding classes, stop-word false-positive guard, NFR-corpus inclusion, multi-finding aggregation.
- AC-4: PASS — 29 schema-conformance tests in `tests/test_schemas_a70.py` pin every enum + pattern + F5-dispatch integration. Negative tests include explicit Sysco-class regression guards (banned anti-pattern StoryText "The system shall...").

## Tests / verification

- **951 passed** at Sprint 7 close (912 at Sprint 6 close + 39 new tests: 29 A70 schema + 10 no-new-stories).
- skill-lint: 28/28 (unchanged count; bsa-story-writer rewritten in-place).
- canon hash: matches compute_canon_hash.py output.

## Scope decisions / what's deferred

- **INV-08 cross-field at F5-hook layer** — per-row schema catches shape (pattern on SourceClaimIDs + RelatedNFRIDs), but "at-least-one non-empty" cross-field is not expressible cleanly in JSON Schema for CSV values. Enforced by the skill's own output validator + the no-new-stories auditor pre-promotion. Documented explicitly; future work could introduce a schema-extension directive (e.g., `x-bsa-oneof-nonempty`) that the F5 dispatcher reads.

- **No-new-stories as a skill wrapper** — Sprint 7 delivers it as a standalone script. A skill-wrapper emitting its own phase3 marker is Sprint 8 or pre-v1.1.0 polish work.

- **Multiple-story-tests for same claim** — when one A59 claim legitimately fans out into multiple stories, each A70 row references the same ClaimID in SourceClaimIDs. No special handling needed; the claim→stories coverage report in the authoring report surfaces the fan-out pattern.

## Lessons

- **Leakage detection precision needs test-fixture discipline.** First tests used loose corpus coverage (story tokens like "appears", "concurrent", "works" not explicitly in source) — the auditor correctly flagged them. Fix: test fixtures now use minimal-token stories that demonstrate provenance. Real engagements will face this genuinely; the tight-corpus lesson transfers.

- **JSON Schema `(?i)` regex flag is deprecated.** First A70 schema used `^(?i)As\\s+...` which triggered Python DeprecationWarning in the jsonschema validator. Switched to `^(?i:As)\\s+...` inline-group syntax. Future schemas should avoid the legacy flag form.

- **F5 + Phase-3 schemas are compound-interest.** A70 ships + F5 dispatcher entry ships → enforcement lands automatically. Zero hook code changes. Same pattern for A71/A72 in Sprint 8.

## Carries into Sprint 8

- US-S8-01 — A71 test-scenario schema + bsa-test-scenario-builder real implementation (replaces scaffold).
- US-S8-02 — A72 traceability matrix schema + bsa-traceability-matrix real implementation (replaces scaffold).
- US-S8-03 — Integration test on project_0001 fixture: full main cycle + Phase 3 (NFR + Story + TestScenario + Traceability) end-to-end, asserting every test scenario traces back to claim+source via matrix.
- Optional polish: wrap no-new-stories auditor as a skill that emits its own marker.

## Related

- Sprint 6 close: retro `docs/retros/sprint_6.md`.
- Sprint 7 commits: `d39a39c`.
- Phase 3 plan: `docs/phase_3_plan.md`.
- Target release: `v1.1.0` at Sprint 9 close.
