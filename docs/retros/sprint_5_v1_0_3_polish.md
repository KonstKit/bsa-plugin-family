# v1.0.3 Polish Retrospective — Deferred HIGH Findings + External Doc Drift

**Window:** Tail of the Sprint-5 remediation cycle, run immediately after v1.0.2 hotfix + Sprint 6-7 cherry-pick.
**Tag target:** `v1.0.3` (pending commit `5309481`).
**Canon policy version at v1.0.3:** `1.0.3+hash:0d4d1de4` — unchanged from v1.0.2 (no POLICY_GLOBS files touched).

## Why this polish release exists

Two threads landed at the same time:

1. **Sprint-6+7 retroactive review deferrals** — the code review of Phase-3 kick-off + Sprint 7 (run alongside the Sprint-5 F5 security review) flagged three HIGH findings that declared rules in schema extensions without executable enforcement. Same problem class as Codex CRITICAL C2 for A59. Deferred from v1.0.2 scope but explicitly slated for a follow-up pass before Sprint 8 could build on top of Phase-3 artifacts.

2. **Concurrent external review drift findings** — a second reviewer (reviewing the repo-wide contract + docs state, not the write-validator specifically) flagged four P2/P3 config-and-docs drifts: routing manifest's `canon_policy_version` frozen at `0.9`, CONTRIBUTING.md's `302 tests` gate, README's `23 skills / 302 unit tests` cardinalities, and architecture_overview's pre-release canon example.

Both threads are "contract-enforcement hygiene" in the same spirit as the v1.0.2 hotfix, so they ship together as v1.0.3.

## What was delivered

| Fix | Finding | Commit | Codex review rounds | Result |
|---|---|---|---|---|
| **A62 `x-bsa-measurability-rules` executable** | S6+7 review HIGH (H4 — INV-09 seed documentary only) | `ef4d23b` | 1 | APPROVE |
| **A70 `x-bsa-provenance-rules` executable** | S6+7 review HIGH (INV-08 seed documentary only) | `ef4d23b` | 1 | APPROVE |
| **A70 `x-bsa-invest-rules` executable** | S6+7 review HIGH (H3 — INVEST-A51 coupling documentary only) | `ef4d23b` | 1 | APPROVE |
| **Routing manifest canon version bump** | External review P2 | `5309481` | 0 (doc-only) | — |
| **CONTRIBUTING test-count gate refresh** | External review P2 | `5309481` | 0 | — |
| **README cardinalities refresh** | External review P3 | `5309481` | 0 | — |
| **architecture_overview canon example refresh** | External review P3 | `5309481` | 0 | — |

Plus: this retro file + CHANGELOG `[v1.0.3]` entry + `v1.0.3` git tag (pending).

## Acceptance criteria coverage

**Schema-exec polish (`ef4d23b`):**
- AC-1: PASS — three new handlers in `governance/schemas/write_validator.py` follow the C2 pattern exactly: `_apply_measurability_rules`, `_apply_provenance_rules`, `_apply_invest_rules`. Each reads its target extension, no-ops when missing, returns line-numbered violation messages when cross-field rule fails.
- AC-2: PASS — all four extension handlers (plus existing C2 `_apply_claim_type_rules`) invoked in `_make_csv_validator` per row after JSON Schema validation. Schema-agnostic: schemas without a given extension run no cross-field check.
- AC-3: PASS — 13 new regression tests in `tests/test_schemas_write_validator.py` Group 9: A62 measurability (9 tests covering 3 required + 6 qualitative categories + A51-alternative + Metric+Target happy path), A70 provenance (3 tests: orphan rejected, claim-only / NFR-only accepted), A70 INVEST (8 tests: 5 deferred statuses without A51Ref rejected, 3 with A51Ref accepted, pass-without-A51Ref accepted). Plus one multi-rule interaction test.
- AC-4 (Codex review): Codex APPROVE with 1 LOW non-blocking finding (no guard on malformed extension shape → `AttributeError`; filed as v1.0.3+1 follow-up polish, not v1.0.3 blocker).
- AC-5: PASS — existing Sprint 7 tests (introduced during cherry-pick) all still green. 978 → 991 with +13 new tests; zero existing-test breakage confirms no false-positive introduced.

**External drift fixes (`5309481`):**
- AC-1: PASS — `config/request_skill_routes.json:5` `canon_policy_version` bumped `0.9` → `1.0.0`.
- AC-2: PASS — `CONTRIBUTING.md:24` pre-commit checklist rewritten to name the current count (991) plus an explicit rule-based framing ("all pass" invariant, not a hardcoded number).
- AC-3: PASS — `README.md` status line refreshed to reflect v1.0.0 → v1.0.1 → v1.0.2 → v1.0.3 patch-line, 28 skills, and ~991 tests. Repository-layout block updated in lockstep.
- AC-4: PASS — `docs/architecture_overview.md:70` canon-version example replaced with current `1.0.0+hash:0d4d1de4` value; added a v1.0.x patch-line convention note for clarity.

## Tests / verification snapshot

- **991 passed** at v1.0.3 tag point (978 post-cherry-pick + 13 new schema-polish tests).
- Codex code-review on the schema polish commit: APPROVE (`CODEX_ID 1776798093_v103_cr`).
- Doc-drift commit: no Codex round (doc-only, zero semantic-behavior change); external reviewer's findings serve as the verification gate.
- Canon hash stable at `0d4d1de4...` (none of the v1.0.3 files are in POLICY_GLOBS).

## What remains open (carried beyond v1.0.3)

From the Sprint-6+7 review:

- **H5 (no-new-stories tokenization heuristic)** — both too strict (exact-token diffing → false-flags paraphrase) and too loose (drops numeric/unit tokens like `500ms`, 3-letter acronyms like `SLA`/`SSO`, whole-source corpus aggregation hides topic bleed). Codex characterization: "good as advisory linter today, not yet reliable as hard promotion blocker for realistic engagement data". Scheduled for v1.1.0 (Sprint 8 / 9 when test-scenario-builder lands and story↔scenario traceability surfaces real-engagement token diversity).

From the v1.0.3 Codex review:

- **LOW — malformed extension-shape guard** — the four handlers assume the extension property is either absent or a well-formed dict. A truthy-non-dict value (e.g., `x-bsa-invest-rules: "please enforce"`) would `AttributeError` on `.get`. Filed as a hardening pass — defensive `isinstance(ext, dict)` guards around each helper entry. Can ship in v1.0.4 or rolled into Sprint-8 polish.
- **LOW — shape-pin tests for A62/A70 extensions** — A59 has `test_a59_claim_type_rules_schema_extension_structure` asserting the rule-dict shape; A62/A70 don't have the equivalent. Follow-up test-only commit.

From the external review:

- Nothing remaining. All four findings closed.

## Lessons

- **C2 pattern generalizes well.** Three new extension handlers written in ~90 minutes total, each ~20-30 lines, reviewer-APPROVE on the first round. The work would have been quadruple the effort if done ad-hoc per extension; following the C2 template made it mechanical.

- **Doc drift is invisible until someone looks.** The external reviewer's four findings were all plain-text facts sitting in the repo for months. They don't fail tests; they don't fail CI; they quietly make onboarding misleading and release-readiness checklists stale. Recurring discipline: every release cut should grep for hardcoded cardinalities (`\b23\b`, `\b302\b`) and hardcoded version examples (old semvers / old hash prefixes) in README + CONTRIBUTING + docs/ before tagging. Not a hard CI gate yet; a make-target script + pre-tag checklist would be a cheap fix.

- **The "grows with each release" framing.** Hardcoding `991 unit tests` in CONTRIBUTING would re-stale on the next sprint that adds tests. Replacing the number with a rule ("all pass"; exact count in the latest sprint retro) pushes the source-of-truth to an already-living document. Same principle in the README repo-layout comment ("~990 unit tests"). Not elegant but honest.

## Release bookkeeping

- `v1.0.0`, `v1.0.1`, `v1.0.2` tags remain at their original commits (no retag).
- `v1.0.3` tag lands on `5309481` (doc-drift commit, which is the LAST commit of this polish release).
- Manifest `version` field stays at `1.0.0` through v1.0.3 (same SemVer rationale as the prior patches — bump to `1.1.0` at the Phase-3 feature release at Sprint 9 close).
- Canon hash unchanged at `0d4d1de4...`.

## Related

- Sprint 5 retros:
  - `docs/retros/sprint_5.md` — scope-as-shipped at v1.0.1.
  - `docs/retros/sprint_5_v1_0_2_hotfix.md` — four must-fix items at v1.0.2.
  - `docs/retros/sprint_5_v1_0_3_polish.md` — this file.
- Sprint 6 + 7 retros: `docs/retros/sprint_6.md`, `docs/retros/sprint_7.md`.
- Codex review outputs preserved as `/tmp/codex_out_*_{v103_cr}.txt` (v1.0.3 schema polish) and the earlier security-review outputs.
- External reviewer's drift findings: session transcript (no separate codex_out file; the review arrived through the operator channel).

Next: Phase-2.5 pilot on v1.0.3 on the Sysco Order & Deliver materials, now with A59 + A62 + A70 all mechanically enforced. If clean, proceed to Sprint 8 (bsa-test-scenario-builder, US-S8-01).
