# v1.0.2 Hotfix Retrospective — Sprint-5 F5 Security-Review Remediation

**Window:** Hotfix cycle between v1.0.1 (Sprint 5 close) and v1.1.0 (Phase-3 release). Driven by three retroactive Codex reviews of the Sprint-5 F5 work that the original sprint had skipped.
**Tag target:** `v1.0.2` (pending commit `8d3c7e7`).
**Canon policy version at v1.0.2:** `1.0.2+hash:65a577fd...` — canon hash unchanged from v1.0.1 because none of the fixes touched POLICY_GLOBS files.

## Why this hotfix exists

Sprint 5 delivered F5 — the PreToolUse:Write schema-enforcement hook — and the Sprint-5 retro claimed it mechanically blocked the Sysco-engagement drift class. The sprint shipped without the Codex code-review / security-analyst rounds that every prior sprint had used (2-3 rounds per US per the established pattern). When the review was finally run retroactively, it produced:

- **Sprint 5 code review** → REQUEST CHANGES + 2 high-risk findings.
- **F5 security review** → **CRITICAL** + 3 critical-severity findings.
- **Sprint 6+7 code review** → REQUEST CHANGES + 3 high-risk findings (applied to the work built on top of the broken foundation).

The three CRITICAL findings plus one HIGH that was the most exploitable became the v1.0.2 must-fix set.

## What was delivered

| Fix | Finding | Commit | Codex review rounds | Result |
|---|---|---|---|---|
| **C1** — Hook matcher coverage | Sec-review CRITICAL: `hooks.json` matcher covered only `analysis/canonical/**`. Marker writes (`analysis/runtime/ready/**` + discovery mirror) and `analysis/discovery/canonical/**` bypassed F5 entirely. | `743a496` | 1 | APPROVE |
| **C2** — A59 cross-field rules executable | Sec-review CRITICAL: `x-bsa-claim-type-rules` was documentary only. `ClaimType=direct` with empty `ExcerptID` + empty `A51Ref` passed (INV-01 bypass). `analyst_judgment` with empty `JustificationRationale` passed (INV-07 bypass). | `e5418f4` | 1 | APPROVE |
| **C3** — `BSA_PLUGIN_REPO` env-injection lockdown | Sec-review CRITICAL: attacker-controlled `BSA_PLUGIN_REPO=/evil` pointed at a permissive `governance.schemas.write_validator`, redirecting all hook subprocess validation. | `ab6a8f8` | 2 (round-1 paired-flag scheme → REJECT because attacker can inject both vars; round-2 no-override → APPROVE) | APPROVE |
| **H-sec-4** — Marker filename↔marker_id + FormatChecker + path normalization | Sec-review HIGH: marker validation syntactic only. No filename↔`marker_id` binding; no `marker_id`↔`(stage, verdict)` binding; `timestamp: "not-a-date"` passed. | `8d3c7e7` | 2 (round-1 → REQUEST CHANGES for `..`-traversal bypass; round-2 with `posixpath.normpath` → APPROVE) | APPROVE |

Plus: this retro file + `CHANGELOG.md` `[v1.0.2]` entry + `v1.0.2` git tag (pending).

## Acceptance criteria coverage

**C1 — hooks.json matcher coverage:**
- AC-1: PASS — `hooks/hooks.json` PreToolUse:Write matcher list extended from one path-pattern (`analysis/canonical/**`) to four (adds `analysis/discovery/canonical/**`, `analysis/runtime/ready/**`, `analysis/discovery/runtime/ready/**`).
- AC-2: PASS — `hooks/pre_write_canonical.sh` stderr wording generalized from "analysis/canonical/*" to "BSA protected path"; INV-02 rationale names all four path classes.
- AC-3: PASS — 2 new data-level assertion tests in `tests/test_plugin_hooks.py` pin the protected-path set (positive: required paths present; negative: no overly-broad globs). A future regression dropping a path fails CI at the hooks.json level, not at silent-bypass runtime.

**C2 — A59 cross-field rules executable:**
- AC-1: PASS — `_apply_claim_type_rules(row, schema, row_idx)` helper in `governance/schemas/write_validator.py` reads `x-bsa-claim-type-rules` from the schema.
- AC-2: PASS — `direct`/`inference` now require non-empty `ExcerptID` OR non-empty `A51Ref` (INV-01 enforcement). `analyst_judgment` requires non-empty `JustificationRationale` (INV-07 enforcement). Whitespace-only values treated as empty.
- AC-3: PASS — 9 regression tests covering direct/inference/analyst_judgment positive + negative paths, A51Ref-as-alternative behavior, multi-row line-numbered flagging, schema-extension-shape pin.

**C3 — `BSA_PLUGIN_REPO` env-injection lockdown:**
- AC-1: PASS — both hooks derive `PLUGIN_REPO` from script realpath (`pwd -P`) first, with `CLAUDE_PLUGIN_ROOT` fallback when the derived directory lacks `governance/schemas/`. No env override honored.
- AC-2: PASS — 2 paired-injection regression tests (`BSA_PLUGIN_REPO=/evil` + `BSA_PLUGIN_REPO_ALLOW_TEST_OVERRIDE=1`) confirm neither variable is trusted; real validator runs; attacker-planted validator not invoked.
- AC-3 (round-2 learning): Codex round-1 correctly identified that paired-flag locks provide no security — any attacker who can inject one env var can inject both. The round-2 fix removed the override branch entirely.

**H-sec-4 — marker filename↔marker_id + FormatChecker + path normalization:**
- AC-1: PASS — `governance/schemas/marker.schema.json` `timestamp` property gains regex pattern alongside `format: date-time`. Pattern enforcement works regardless of `jsonschema[format-nongpl]` optional-extras installation; FormatChecker enabled for defense-in-depth.
- AC-2: PASS — `_validate_marker_json(path, content)` enforces `PurePosixPath(path).stem == payload.marker_id` after schema validation. Emits `<filename-binding>: path stem 'X' does not match payload marker_id 'Y'` on mismatch.
- AC-3: PASS — `_expected_stage_verdict(marker_id)` helper derives expected `(stage, verdict)` pair for every marker_id in the schema enum (exact-match table + regex-pattern match for `stage<N>.ready`/`stage<N>.*.pass`/`discovery.d<N>.ready`/`discovery.d<N>.*.pass`). Mismatches flagged as dedicated violations.
- AC-4 (round-2): PASS — `_normalize_path(path)` via `posixpath.normpath()` after backslash→forward-slash conversion, used by `_dispatch()` and `validate_canonical_write()`. `..` / `.` / duplicate-slash segments collapse syntactically before dispatch — closes the Codex-flagged round-1 traversal bypass.
- AC-5: PASS — 14 regression tests total (9 primary + 5 traversal normalization), including direct replay of the Codex `..` reproducer.

## Tests / verification snapshot

- **912 passed** at v1.0.2 tag point (885 baseline at Sprint 5 end + 27 new regression tests).
- Each must-fix commit passed an independent Codex review.
- Two commits required a second Codex round when the first review found escape hatches:
  - C3: paired-flag override → removed entirely.
  - H-sec-4: raw-path `..` bypass → `posixpath.normpath()` in dispatcher.
- Canon hash stable at `65a577fd...` (v1.0.1 value) — no POLICY_GLOBS files touched by v1.0.2 fixes.

## What was deferred (acknowledged, not fixed in v1.0.2)

- **H-sec-1 (BSA_WRITER forgeability)** — ambient `BSA_WRITER=bsa-orchestrator` in the user shell still bypasses INV-02 identity check. Architectural fix requires signed tokens / runtime metadata; scoped to v2.0.
- **H-sec-2 (path canonicalization for case-sensitivity + discovery variants)** — on macOS default case-insensitive FS, `A59_claim_register.CSV` targets the real file but the dispatcher regex (case-sensitive) returns None. Separate hardening pass.
- **H-sec-3 (fail-open extraction)** — empty stdin / JSON parse errors / `EditError` all return allow. Acceptable for backward-compat with tests that don't pipe JSON; would tighten in v1.1.0 when the hook knows it's running under Claude Code proper.
- **S6+7 high findings** (INVEST-A51 coupling + NFR measurability executable; no-new-stories heuristic tokenization). These apply to Phase-3 artifacts (A62, A70) that were rolled back pre-v1.0.2. When Sprint 6-7 cherry-pick lands on top of v1.0.2, either the schema extensions get the same executable-enforcement treatment as A59 did in C2 (consistent discipline), or the gap is explicitly documented and deferred to v1.1.0.
- **Low / medium findings** from the three reviews (CSV header-order, Edit-replace_all integration test, doc inconsistencies) — standard cleanup, can go into v1.0.3 / v1.1.0 polish pass.

## Lessons

- **Review discipline is not optional.** The whole hotfix exists because Sprint 5 skipped what every prior sprint had enforced. The three retroactive reviews found 17 findings across three categories; the CRITICAL ones would have been caught in the sprint had the reviews run. Cost of skipping: roughly ~1.5-2 extra sprints of remediation + tag churn.

- **Paired-flag locks are not locks.** Round-1 C3 used a second env-var flag to guard the override branch. Codex correctly pointed out that any attacker who can inject one env var can inject two. The right fix was to remove the override surface entirely — trust narrowed from shell-controlled env input to on-disk hook location.

- **Syntactic path matching is not enough.** H-sec-4 round-1 was thorough on payload binding but missed the `..`-traversal bypass of the dispatcher regex itself. Path-string dispatch must normalize before matching. This kind of bypass is exactly what a second review round catches — the first review can confirm "the checks work on canonical paths"; the second round asks "what paths still reach canonical files without passing through the checks?".

- **Tests that call validators directly ≠ hook integration tests.** Every Sprint-5 test that called `validate_canonical_write()` directly passed on v1.0.1. What failed was the matcher wiring — the validator was never reached in production. Regression tests must include at least one data-level assertion that the hook config would actually route to the validator for every protected path class; direct-function unit tests don't establish that.

## Release bookkeeping

- `v1.0.1` remains tagged at commit `8d4692a`. It is NOT retagged — users who installed from that tag should upgrade to v1.0.2.
- CHANGELOG entry `[v1.0.2]` itemizes the four must-fix commits plus the retro ref.
- Manifest `version` field stays at `1.0.0` through v1.0.2 (same reasoning as v1.0.1 — `version` bumps accompany feature releases, not patch-line hotfixes). The proper SemVer bump is `1.1.0` at Sprint 9 close.

## Related

- Sprint 5 retro (original, scope-as-shipped): `docs/retros/sprint_5.md`.
- Sprint 5-7 rollback commits: HEAD reset to `8d4692a` + `archive/sprint-6-7-pre-f5-fix` branch preserves the original work; cherry-pick planned after v1.0.2 tag.
- Codex review outputs preserved in the session transcript (file paths under `/tmp/codex_out_*_{s5_cr,f5_sec,s67_cr,c1_cr,c2_cr,c3_sec,c3b_sec,hs4_sec,hs4b_sec}.txt`).
- Phase-3 plan (to be resumed after Sprint 6-7 cherry-pick): `docs/phase_3_plan.md` (on the archive branch).
