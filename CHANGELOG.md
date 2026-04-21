# Changelog

All notable changes to the BSA Plugin Family. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + [Semantic Versioning](https://semver.org/spec/v2.0.0.html) for plugin versions.

Canon policy version (orthogonal measurement): `<semver>+hash:<sha256-prefix>`, computed from policy state (see [governance/immutable_invariants.md](governance/immutable_invariants.md) and Sprint 3 canon hash scheme).

## [v1.0.3] — 2026-04-22

**Polish release** — closes the Sprint-6+7 retroactive-review HIGH findings that were deferred past v1.0.2 scope, plus four external-review P2/P3 doc-drift findings. Applies the v1.0.2 C2 enforcement pattern to A62 + A70 extension rules, so Phase-3 artifacts (NFR register + story register) have the same mechanical cross-field enforcement as A59.

**Tag target**: commit `5309481` (last of the v1.0.3 commits).
**Canon policy version**: `1.0.3+hash:0d4d1de4` — unchanged from v1.0.2 cherry-pick state. No POLICY_GLOBS file was touched.

### Fixed (schema-exec polish)

- **A62 `x-bsa-measurability-rules` executable** (`ef4d23b`) — Pre-fix, the extension declared INV-09 (performance/availability/scalability NFRs require Metric+Target OR A51Ref) in plain text, but `_make_csv_validator()` ignored it. New helper `_apply_measurability_rules()` reads the extension and applies per-row after JSON Schema. Qualitative NFR categories (usability/compliance/security/maintainability/observability/portability) unaffected.

- **A70 `x-bsa-provenance-rules` executable** (`ef4d23b`) — INV-08 seed: story rows must have at least one of SourceClaimIDs / RelatedNFRIDs non-empty. Pre-fix, both-empty rows passed F5 silently. New helper `_apply_provenance_rules()` generalizes to any schema declaring the `at_least_one_of_non_empty` extension.

- **A70 `x-bsa-invest-rules` executable** (`ef4d23b`) — INVEST-A51 coupling: INVESTStatus != 'pass' requires non-empty A51Ref. Pre-fix, deferred-INVEST rows without A51Ref passed silently. New helper `_apply_invest_rules()` enforces.

- **Extension-handler wiring** — all four extension handlers (including existing C2 `_apply_claim_type_rules`) invoked in `_make_csv_validator` per row. Schema-agnostic — schemas without a given extension no-op cleanly. Same pattern A71/A72 schemas (Sprint 8) can adopt.

### Fixed (external-review doc drift)

- **`config/request_skill_routes.json`** (`5309481`) — P2. `canon_policy_version` bumped from `"0.9"` (pre-Sprint-1 value) to `"1.0.0"`.
- **`CONTRIBUTING.md`** (`5309481`) — P2. Pre-commit checklist's "302 tests must pass" replaced with the current count (991) and a rule-based framing ("all pass", not a hardcoded number) so future sprint test growth doesn't re-stale the doc.
- **`README.md`** (`5309481`) — P3. Status line refreshed: 28 skills (was 23), ~991 tests (was 302), v1.0.0 → v1.0.3 patch-line history replaces the Sprint-4.5-snapshot freeze. Repo-layout block updated in lockstep.
- **`docs/architecture_overview.md`** (`5309481`) — P3. Canon-version example `1.0.0-rc2+hash:cbba8e53` replaced with live `1.0.0+hash:0d4d1de4` + a v1.0.x patch-line convention note (semver stays at 1.0.0 across patches; hash moves with POLICY_GLOBS edits).

### Added (tests only)

13 new regression tests (Group 9 in `tests/test_schemas_write_validator.py`): 9 A62 measurability (3 required categories × missing Metric+Target, 1 valid, 1 A51-alternative, 6 qualitative-unaffected), 3 A70 provenance (orphan / claim-only / NFR-only), 8 A70 INVEST (5 deferred-no-A51 / 3 deferred-with-A51 / 1 pass-no-A51), 1 multi-rule interaction test.

### Deferred (carried beyond v1.0.3)

- **H5 — no-new-stories tokenization** heuristic too strict on paraphrase + too loose on numeric/unit/acronym tokens. Needs stemming + unit-preserving tokenizer. Scheduled for v1.1.0 (Sprint 8 or 9 when test-scenario-builder surfaces real-engagement token diversity).
- **LOW — malformed extension-shape guard** (Codex noted in v1.0.3 review) — handlers assume extension is absent or dict; a truthy-non-dict value would `AttributeError`. Defensive isinstance checks → v1.0.4 or Sprint-8 polish.
- **LOW — A62/A70 extension shape-pin tests** analogous to the existing A59 one.

### Canon policy

- **Unchanged** at `0d4d1de4e425773461afe3ff3d10d41e68e25eb2a45e4697beec78c7a2c675b3`. v1.0.3 touches only non-POLICY_GLOBS files (hook validators, tests, CHANGELOG, README, CONTRIBUTING, architecture_overview, routing manifest).

### Verification

- `python3 -m pytest -q`: 991 passed.
- Schema-polish commit: Codex code-review APPROVE (`CODEX_ID 1776798093_v103_cr`). Confirmed all three deferred HIGH findings closed; whitespace handling consistent with C2; test coverage adequate.
- Doc-drift commit: no Codex round (zero semantic behavior; external reviewer's findings serve as the verification gate). Each finding factually validated against HEAD content pre-fix.

### Bookkeeping

- Manifest `version` stays at `1.0.0` through v1.0.3 — bump to `1.1.0` accompanies the Phase-3 feature release at Sprint 9 close.
- Sprint 5 retro trilogy now complete: `sprint_5.md` (v1.0.1 scope), `sprint_5_v1_0_2_hotfix.md` (v1.0.2 must-fix), `sprint_5_v1_0_3_polish.md` (this release).
- Next step: Phase-2.5 pilot on v1.0.3 on the Sysco Order & Deliver materials, now with A59 + A62 + A70 all mechanically enforced. If clean, proceed to Sprint 8 (bsa-test-scenario-builder, US-S8-01).

## [v1.0.2] — 2026-04-21

**Security hotfix** — retroactive Codex review of the Sprint-5 F5 work surfaced three CRITICAL findings + one HIGH that rendered the v1.0.1 "contract-enforcement hardening" claim misleading in production. All four now closed. v1.0.1 users should upgrade.

**Tag target**: commit `8d3c7e7` (last of the four must-fix commits).
**Canon policy version**: `1.0.2+hash:65a577fd...` — unchanged from v1.0.1 because no POLICY_GLOBS file was touched.

### Why this hotfix exists

Sprint 5 shipped F5 without the code-review / security-analyst rounds every prior sprint had used (2-3 rounds per US was the established pattern). Retroactive review, run after Sprint 6+7 had already built on top of F5, produced:

- Sprint 5 code review: REQUEST CHANGES + 2 high-risk findings.
- F5 security review: CRITICAL + 3 critical-severity findings.
- Sprint 6+7 code review: REQUEST CHANGES + 3 high-risk findings.

The three CRITICALs plus the most-exploitable HIGH became the v1.0.2 must-fix set. Sprint 6-7 commits were rolled back to `archive/sprint-6-7-pre-f5-fix` pending re-base on a clean v1.0.2 foundation.

### Fixed

- **C1 — hooks.json matcher coverage** (`743a496`) — Pre-fix, the PreToolUse:Write matcher covered only `analysis/canonical/**`. Marker writes to `analysis/runtime/ready/**` and `analysis/discovery/runtime/ready/**`, plus `analysis/discovery/canonical/**` writes, bypassed F5 entirely. The entire Sysco-engagement marker-drift class (camelCase marker_id, legacy `no_new_facts` filename) landed unmolested on v1.0.1. Matcher list now covers all four protected-path classes; stderr diagnostics generalized accordingly. 2 new data-level assertion tests would have caught the original miss.

- **C2 — A59 cross-field rules executable** (`e5418f4`) — Pre-fix, `x-bsa-claim-type-rules` in `a59.schema.json` declared INV-01 + INV-07 rules in plain text, but `_make_csv_validator()` ignored the extension. Bypasses: `ClaimType=direct` with empty `ExcerptID` + empty `A51Ref` passed (INV-01); `analyst_judgment` with empty `JustificationRationale` passed (INV-07). New helper `_apply_claim_type_rules()` reads the extension and applies per-row cross-field checks after JSON Schema. 9 regression tests.

- **C3 — `BSA_PLUGIN_REPO` env-injection lockdown** (`ab6a8f8`) — Pre-fix, both hooks resolved `PLUGIN_REPO` from `${BSA_PLUGIN_REPO:-${CLAUDE_PLUGIN_ROOT:-<script-derived>}}`. Attacker-controlled `BSA_PLUGIN_REPO=/evil` pointed at a permissive `governance.schemas.write_validator`; all hook subprocess validation redirected. Round-1 attempt gated the override on a paired flag (`BSA_PLUGIN_REPO_ALLOW_TEST_OVERRIDE=1`); Codex correctly rejected — any attacker injecting one env var can inject two. Round-2 removed the override entirely. Priority now: script realpath → `CLAUDE_PLUGIN_ROOT` fallback. 2 paired-injection regression tests.

- **H-sec-4 — marker filename↔marker_id + FormatChecker + path normalization** (`8d3c7e7`) — Pre-fix, marker validation was syntactic only. `timestamp: "not-a-date"` passed (FormatChecker not enabled); filename↔payload binding unenforced (file named `stage8.no_new_claims.pass.json` could carry `marker_id=stage1.ready` and still satisfy `pre_bash_promote.sh`'s filename-presence check); marker_id↔stage/verdict bindings unenforced. All three closed. Round-2 Codex review caught a residual `..`-traversal bypass of the dispatcher regex itself; fixed with `posixpath.normpath()` in `_dispatch()` + `validate_canonical_write()`. 14 regression tests across two rounds.

### Added (tests only)

27 regression tests total — each is a direct replay of a Codex-flagged attack path:
  - 2 data-level hook-config assertions (C1 protected-path coverage).
  - 9 A59 cross-field coverage tests (C2).
  - 2 env-injection attack replays (C3).
  - 14 marker-binding tests (H-sec-4: timestamp, filename binding, stage/verdict binding, traversal normalization, Sysco attack replay).

### Deferred

The following findings from the same review cycle are acknowledged but not fixed in v1.0.2:

- **H-sec-1** — `BSA_WRITER` forgeable via ambient env (architectural; v2.0 signed-token work).
- **H-sec-2** — Case-insensitive FS dispatch bypass + discovery-path dispatch gaps (separate hardening pass).
- **H-sec-3** — Fail-open extraction on empty stdin / parse errors (backward-compat with tests; tighten in v1.1.0).
- **Sprint-6+7 high findings** on Phase-3 artifacts (INVEST-A51 executable, NFR measurability executable, no-new-stories tokenization). Applied to artifacts rolled back to `archive/sprint-6-7-pre-f5-fix`; re-evaluated when Sprint 6-7 is cherry-picked on top of v1.0.2.
- Medium / low findings (CSV header order, Edit-`replace_all` integration test, doc inconsistencies) — polish pass in v1.0.3 / v1.1.0.

### Canon policy

- **Unchanged** at `65a577fd6dea35474d349e312d6890690625aff11414b3e19848dfbdfc00a93b`. None of the v1.0.2 fixes touched a POLICY_GLOBS file — schema files (`governance/schemas/*.json`) are outside POLICY_GLOBS; hooks / validators / tests are too. Only `runtime-marker-schema.md` would have shifted the hash, and that doc was already correct at v1.0.1.

### Verification

- `python3 -m pytest -q`: 912 passed.
- Each must-fix commit passed an independent Codex code-review or security-analyst review. Two commits required a second round after the first surfaced an escape hatch (C3 paired-flag → removed; H-sec-4 `..`-traversal → `posixpath.normpath` in dispatcher).
- Codex review outputs retained in the session transcript as `/tmp/codex_out_*_{c1_cr,c2_cr,c3_sec,c3b_sec,hs4_sec,hs4b_sec}.txt`.

### Bookkeeping

- v1.0.1 tag remains at `8d4692a` (not re-tagged). Users installed from v1.0.1 should upgrade.
- Manifest `version` field stays at `1.0.0` through v1.0.2 — SemVer bump to `1.1.0` accompanies the Phase-3 feature release at Sprint 9 close.
- Sprint 5 retro (`docs/retros/sprint_5.md`) describes what v1.0.1 shipped. Hotfix retro (`docs/retros/sprint_5_v1_0_2_hotfix.md`) describes what v1.0.2 added on top.
- Sprint 6-7 commits are preserved in branch `archive/sprint-6-7-pre-f5-fix` (commits `f8d508b..a4e7682`). Cherry-pick on top of v1.0.2 is the next release-bookkeeping step before Sprint 8 work resumes.

## [v1.0.1] — 2026-04-21

Sprint 5 close — **contract-enforcement hardening release**. Schema-as-source-of-truth for canonical artifacts, plus write-time mechanical enforcement via the PreToolUse:Write hook. Closes three reviewer P-level findings (P1 marker-validator alphabet drift, P1 promote-hook A48 parse failure, P2 privacy-scan letter-only secrets). Also closes the entire Sysco-engagement drift class identified during the Phase 2.5 trial run.

**Tag target**: commit `8d4692a` (last Sprint-5-work commit, before Sprint-6 Phase-3 kick-off scaffolding).
**Canon policy version at v1.0.1**: `1.0.1+hash:65a577fd6dea35474d349e312d6890690625aff11414b3e19848dfbdfc00a93b`. Hash advanced from `cbba8e53…` (v1.0.0) because `runtime-marker-schema.md` gained the previously-undocumented `stage1.ready`, `discovery.d{2,3,4,5}.ready`, and verdict `MERGED` — filling documentation gaps surfaced by the schema-conformance tests.

### Added
- **F4a** (`034ddb3`) — `governance/schemas/marker.schema.json` + `governance/schemas/loader.py` + 18 schema-conformance tests. Closed marker-ID alphabet (36 IDs); `verdict` enum extended with `MERGED` for composite-promotion markers. Alphabet-sync test prevents future doc-vs-schema drift.
- **F4b + F2** (`dd5efe8`) — `governance/schemas/a48.schema.json` + three-format A48 parser (`parse_a48`: table / bullet-backtick / bullet-bold). `python3 -m governance.schemas.loader a48-field` CLI. `hooks/pre_bash_promote.sh` delegates parsing to the CLI instead of an in-bash grep that silently failed on table-format A48.
- **F1** (`c7dd646`) — `scripts/validate_marker_chain.py` reads alphabet + audit-pass sequences from the schema. Private `MAIN_CYCLE_SEQUENCE` / `DISCOVERY_SEQUENCE` tuples removed. Stage-ready / end-state / bridge / non-go-decision markers no longer rejected as `chain-unknown-marker`. `bsa.stage1.entry.enabled` no longer double-rejected.
- **F3** (`e648401`) — `scripts/privacy_scan._is_likely_natural_prose` rewritten: known-token-prefix gate (21 real secret prefixes: ghp_, sk_live_, xoxb-, AKIA, eyJ, glpat-, shpat_, etc.) + vowel-ratio heuristic (0.30..0.50 prose band). The `QwErTyUiOpAsDfGhJkLzXcVbNm` false-negative reproducer now surfaces as `api_key_token`.
- **F7** (`9495c2b`) — `commands/bsa-status.md` emits three state-aware notices: `discovery-deliverable-only`, `pre-stage-ready`, `handoff-ready-not-emitted`. Direct UX fix for the Sysco engagement operator-confusion at discovery-exit + bridge state.
- **F4c + F4d** (`12ec5e9`) — CSV row schemas for A50/A51/A58/A59/A60 + `iter_a50_rows`..`iter_a60_rows` loader helpers + `tier_to_claim_strength()` + 45 schema-conformance tests. `A59.ClaimType` pins the closed INV-07 enum (`direct | inference | analyst_judgment`); legacy values (`policy_statement` / `factual_state` / `process_step` / `decision_pending`) explicitly listed in the `x-bsa-banned-claim-type-values` extension as documentation.
- **F5** (`5025b2a`) — `governance/schemas/write_validator.py` with path-to-schema dispatcher for all 7 canonical artifacts. `hooks/pre_write_canonical.sh` now runs content validation after the INV-02 identity check. 35 tests including direct Sysco-regression replays (camelCase marker, legacy no_new_facts filename, legacy ClaimType in A59, drift tier label in A50) — all blocked at the hook with structured stderr.
- **F6** (`d699565`) — `scripts/validate_a51_reconciliation.py` + 9 tests. Detects `A51_RECONCILE_GAP` when marker payloads / handoff packets declare an A51Ref remediated while the canonical register holds it open; `A51_RECONCILE_GHOST` for refs that don't exist in the register at all. Handles operator-shorthand `A51-MISS-010/011` correctly.
- **F5 extension** (`8d4692a`) — Edit-tool support in the write hook. `apply_edit()` mirrors Claude Code Edit semantics (uniqueness required unless `replace_all=True`). Hook reads existing file, applies edit, validates the post-image. 9 new tests.

### Changed
- `skills/bsa-orchestrator/references/runtime-marker-schema.md` — added `stage1.ready.json`, `discovery.d{2,3,4,5}.ready.json` bullets; `verdict` column enumerates `MERGED`. These markers were already emitted by `/bsa-start` and discovery D2-D5 stages but were absent from the schema doc.
- `fixtures/golden/*/expected_markers/stage1.excerpts.merged.json` (4 fixtures) — `verdict: "merged"` → `"MERGED"` normalization for consistency with other ALL-CAPS verdict values.
- `fixtures/golden/project_0002/expected_outputs/canonical/core_controls/A60_negative_evidence_register.csv` + `project_0003/.../A60_...csv` + `adversarial_prompt_injection_001/.../A60_...csv` — migrated from the 3-column minimal form (NegEvID + RelatedClaimID + Notes) to the canonical 7-column form (adds SourceID + ExcerptRef + NegativeFinding + A51Ref). Finding prose moved from Notes into NegativeFinding where present.
- `scripts/privacy_whitelist.json` — `.claude-plugin/plugin.json` added to path-globs whitelist (hash hex substring phone-heuristic false-positive, same class as CHANGELOG + handoff manifests).

### Canon policy version
- **Advanced** from `cbba8e53...` (v1.0.0) → `65a577fd...` (v1.0.1) via the `runtime-marker-schema.md` documentation fill-in. No invariant semantics changed; the hash bump reflects documentation catching up to implementation behavior. The manifest at the v1.0.1 tag point still declares `version: "1.0.0"` — `version` field bump was intentionally deferred to the next feature release (v1.1.0, Sprint 9 close) rather than churning the v1.0.x line for a patch release.

### What's explicitly NOT in v1.0.1 (deferred to v1.1.0 / Sprint 9 close)
- Phase 3 skills proper (bsa-nfr-collector runtime behavior, bsa-story-writer, bsa-test-scenario-builder, bsa-traceability-matrix, bsa-backlog-bridge).
- `commands/bsa-dev-handoff.md` composite command.
- A62/A70/A71/A72 canonical artifacts with live data.
- Invariants INV-08 / INV-09 / INV-10 in `governance/immutable_invariants.md`.
- Manifest `version` bump from `1.0.0` to `1.1.0`.

### Verification
- `python3 -m pytest -q`: 885 passed at v1.0.1 tag point (730 baseline at sprint start + 155 new).
- Manual replay of every Sysco-engagement drift shape → each blocked at the write hook with structured stderr.
- All three reviewer P-level findings: reproduced pre-fix, verified fixed post-fix.

## [v1.0.0] — 2026-04-20

Sprint 4.5 close — **first public release** of `bsa-full`. Phase 0-2 MVP ships on-budget across the 12-week roadmap: 23 skills, 6 slash-commands, 3 safety hooks, 3 golden fixtures + 1 adversarial, 302 unit tests, 7 immutable invariants under canon hash `cbba8e53…`.

### Added
- **US-S45-01 Part A** (`b7438aa`) — `fixtures/golden/project_0002/`: prep-shell (Sprint 2 US-S2-03) upgraded to full passing fixture. 5 canonical core_controls + 5 stage2 artifacts + 7 main-cycle markers + H1-H4 handoff pack with manifest digest `556138828a314c47bf91a89033e7985a38147405582f2e62488ab9323df8e9d2`. Exercises structural path + discovery mode + mixed-tier evidence.
- **US-S45-01 Part B** (`d147236` + `92cccae`) — `fixtures/golden/project_0003/`: authored from scratch. Process path + discovery mode + multi-stakeholder conflict (procurement approval workflow). Two T4 sources contradict at tier-delta 0 → both inference claims (C-005, C-006) contested with `ClaimStrength=0.0`, routed to `A51-002` with `BlockingStatus=hard`. Analyst_judgment row (C-007) threads all 5 upstream ClaimIDs per INV-07. Handoff manifest digest `ac61192fdffee7e53a47804e4be841dd22b71e7422734860abb55702c0f86bcb`. Demonstrates the hard-blocker handoff policy (contested `A51` hard blocks downstream execution, not handoff emission).
- **US-S45-02** (`5294651` + `d815649`) — 6 user-facing docs + README polish: `docs/getting_started.md` (install + 30-sec tour + walkthrough), `docs/workflow.md` (stage-by-stage main + discovery, 7 invariants, tier-delta rule), `docs/commands_reference.md` (every slash-command with flags, preconditions, failure modes), `docs/troubleshooting.md` (10 failure modes), `docs/architecture_overview.md` (23 skills across 6 roles, three-layer governance, runtime layout), `docs/faq.md` (12 entries). README.md polished with 30-sec tour, docs index, Phase 2.5 shakedown gate note.
- **US-S45-03** (this commit) — version bump `1.0.0-rc2` → `1.0.0` in `.claude-plugin/plugin.json` (both `version` and `canonPolicyVersion.semver`). Sprint 4.5 retrospective finalized in `docs/retros/sprint_4_5.md`. CHANGELOG `[v1.0.0]` entry (this).

### Changed
- `CHANGELOG.md` — new `[v1.0.0]` section above `[v1.0.0-rc2]`.
- `README.md` — status line now reads `v1.0.0` (was `v1.0.0-rc2` / `v0.9.0-foundation` before).

### Canon policy version
- **Unchanged** at `cbba8e53b0312aeec2744e17d018583fcd96bba613a6b39be58ab702cb44fcb0` between `v1.0.0-rc2` and `v1.0.0`. Sprint 4.5 is fixture + documentation work; no POLICY_GLOBS file changed, so the hash is stable. `canonPolicyVersion.semver` bumped `1.0.0-rc2` → `1.0.0` in lockstep with `version`. Full CanonPolicyVersion string: `1.0.0+hash:cbba8e53b0312aeec2744e17d018583fcd96bba613a6b39be58ab702cb44fcb0`. Release workflow's hash-match gate recomputes and confirms equality at tag time.

### Phase 2.5 external shakedown gate
- `v1.0.0` triggers the Phase 2.5 external shakedown gate. 2-4 weeks of real-project usage by non-self-owned analysts is required before Phase 3 dev-handoff extension begins. Blocker-findings → v1.0.x hotfix, not Phase 3 kickoff.

### Out of scope for v1.0.0
- Dev-handoff extension (bsa-nfr-collector, bsa-story-writer, bsa-test-scenario-builder, bsa-traceability-matrix, bsa-backlog-bridge) — Phase 3.
- Machine-readable Stage 6 (OpenAPI / AsyncAPI / proto generation) — Phase 3.
- Plugin decomposition (bsa-core / bsa-discovery / bsa-sidecars split) — Phase 4.
- Domain/stack packs (fintech, healthcare, regulated) — Phase 5.
- Reality-probe layer — Phase 6.
- Self-improvement telemetry + evolution-miner — Phase 7.
- Marketplace + certification framework — Phase 8.

## [v1.0.0-rc2] — 2026-04-20

Sprint 4 plugin MVP close. All four US-S4-* stories delivered; Sprint 4.5 (fixture/docs pass + v1.0.0 final tag) remains.

### Added
- **US-S4-01 AC-0** — `docs/plugin_api_spike.md`: 7-question authoritative spike against `code.claude.com/docs/en/plugins-reference`. 6 concrete design decisions recorded up front.
- **US-S4-01 AC-1..AC-4** — `.claude-plugin/plugin.json` (version `1.0.0-rc2`, custom `canonPolicyVersion` block with hash `cbba8e53…`). `.github/workflows/release.yml` with 7 hard gates (canon-hash + version↔tag + pytest + fixtures + marker chain + tracked-only archive + sha256 checksum + CHANGELOG-driven release body). `tests/test_plugin_manifest.py` (9 cases).
- **US-S4-02** — six slash commands under `commands/` (`bsa-start`, `bsa-status`, `bsa-stage`, `bsa-promote`, `bsa-audit`, `bsa-handoff`). Each documents `--verbose`; `/bsa-promote` supports `--dry-run`; `/bsa-start` supports `--mode=direct` and `--mode=discovery_then_bsa`. `tests/test_plugin_commands.py` (36 parametrized cases).
- **US-S4-03** — three plugin hooks (SessionStart informational nudge; PreToolUse:Write enforcing INV-02 single-writer on `analysis/canonical/**`; PreToolUse:Bash enforcing marker-gate preconditions on `/bsa-promote`). Shell scripts + `hooks.json` + `tests/test_plugin_hooks.py` (14 cases covering every failure branch + `--dry-run` bypass + discovery-stage markers).
- **US-S4-04** — `INSTALL.md`: install/uninstall/upgrade flow + 7 troubleshooting scenarios + formal 6-step `BSA_WRITER` maintenance procedure (scripted-migration-first; open A51 decision_needed; sponsor sign-off; migration log; BSA_WRITER override; `/bsa-status` verification).

### Changed
- `CHANGELOG.md` — new `[v1.0.0-rc2]` section above `[v1.0.0-rc1]`.

### Fixed
- Round-1 review defects: `commands/bsa-promote.md` hook-path cross-ref (`.claude-plugin/hooks/hooks.json` → `hooks/hooks.json`), `commands/bsa-start.md` trailing-underscore typo, `INSTALL.md` `semantic_validate_bpmn.py` path (now cites `skills/camunda-bpmn-from-context/scripts/semantic_validate_bpmn.py`), `hooks/pre_bash_promote.sh` stage4 + handoff marker set reconciled with `merge-and-reentry-policy.md`.

### Canon policy version
- Stays at `cbba8e53b0312aeec2744e17d018583fcd96bba613a6b39be58ab702cb44fcb0` at Sprint 4 close — no POLICY_GLOBS file changed between `v1.0.0-rc1` and `v1.0.0-rc2`. The Sprint-3-retroactive `governance/immutable_invariants.md` sweep that moved the hash from `ac039430` to `cbba8e53` landed at Sprint 4 kickoff (`fcde0dc` + `fc8616b`); everything else in Sprint 4 was packaging work outside POLICY_GLOBS.

## [v1.0.0-rc1] — 2026-04-20

Sprint 3 close + Sprint 4 plugin-manifest kickoff. First release candidate carrying the `canonPolicyVersion` hash form (semver + SHA-256 prefix) per US-S3-04.

### Added
- **US-S3-01** — sidecar self-description. Integration Contract sections in `skills/c4-plantuml-from-context/SKILL.md` and `skills/camunda-bpmn-from-context/SKILL.md`; `references/integration-contract.md` + `references/anchor_manifest.schema.json` (JSON Schema 2020-12, full macro taxonomy) on both sidecars. Doc-driven superset tests guarantee future reference-doc additions don't escape schema coverage.
- **US-S3-02** — discovery → main merge/dedup contract. `skills/bsa-orchestrator/references/discovery_to_main_merge.md` with disjoint ClaimID namespaces (`D-C-*` vs `C-*`), source identity-tuple dedup, excerpt `(SourceID, Locator)` dedup, A58 carry-forward with `Provenance=discovery-promoted` column, A59 `DiscoveryLineage` column, 8-event merge log. `merge_log.schema.json` enforces event-specific required fields via `allOf`/`if`/`then`. Four new `SCN-ORCH-001-C-MERGE-A..D` scenarios.
- **US-S3-03** — ReliabilityTier operationalization. `skills/bsa-evidence-intake/references/reliability_tier_spec.md` with 5 tiers (T1 empirical 1.00 / T2 authored-primary 0.85 / T3 authored-secondary 0.65 / T4 attestation 0.45 / T5 reported 0.20), 2-of-4 independence rule, tier-delta conflict resolution (≥ 2 higher-wins + `SupersededBy` / ≤ 1 contested + auto-A51 `cross_tier_contradiction` / anecdotal never overrides), `ClaimStrength` formula with optional decay schedule. KPI-001 rewritten as weighted coverage (target bumped from 0.90 unweighted to 0.75 weighted). `bsa-citation-auditor` gets four `EpistemicInsufficiency` sub-types. Reference implementation in `tests/test_tier_conflict_scenarios.py` (12 cases).
- **US-S3-04** — drift detection + CanonPolicyVersion hash. `skills/bsa-anchor-auditor/references/anchor-audit-contract.md` gains three drift sub-types (`semantic_rename_no_pivot`, `semantic_change_no_claim`, `class_change_no_pivot`) with detection heuristics + report JSON + A51 hard-block gate. `scripts/compute_canon_hash.py` outputs SHA-256 over 59 policy files with `--full` per-file breakdown and `--diff-breakdown` 5-category breakdown. `contract-versioning.md` documents `<semver>+hash:<sha256>` form + bump rules + drift-detection semantics. Every fixture marker carries `canon_policy_version_hash`.
- **US-S3-05** — marker chain validator. `scripts/validate_marker_chain.py` enforces prefix/gap/duplicate/timestamp-monotonicity/version-hash-consistency across main-cycle and discovery chains. Three previously-missing project_0001 middle-stage markers (stage5/6/7) added. CI wires it as a blocking step.
- **US-S3-06** — prompt-injection adversarial fixture. `fixtures/golden/adversarial_prompt_injection_001/` with three injection vectors (ignore-previous-instructions, delimiter-escape, tool-use injection), full canonical A50/A58/A59/A60/A51 showing T5 + `anecdotal=true` sources + CLASSIFY claims + A51 `boundary_risk` routes + hand-authored `prompt_injection_audit_report.md`.
- **US-S4-01** — plugin manifest + release workflow. `.claude-plugin/plugin.json` (name=`bsa-full`, version=`1.0.0-rc1`, MIT, author block, 10 keywords, custom `canonPolicyVersion` with semver+hash_prefix+hash_full+compute metadata). `.github/workflows/release.yml` with 7 hard gates (canon-hash match, version-tag match, pytest, fixture runner, marker chain, resilient archive, checksum). `tests/test_plugin_manifest.py` (9 cases) locks manifest shape + drift guard.

### Changed
- KPI-001 formula and target (US-S3-03). Fixture `project_0001` source S-001 promoted T3 → T2; A59 direct claims `ClaimStrength` 0.65 → 0.85; H3 scorecard updated to 0.85 with new per-tier breakdown section.
- Orchestrator promotion sequence now has 9 steps (was 8) with explicit merge-step insertion; pre-merge checklist renamed from "Merge Checklist" to "Pre-merge Preconditions".
- `scripts/privacy_whitelist.json` — 2 new entries for the plugin author email (intentional public contact) and `docs/retros/*.md` (hash-digest false positives from the phone heuristic).

### Fixed
- `governance/immutable_invariants.md` — Sprint 3 retroactive wording cleanup. INV-01 statement, INV-03 override policy, INV-05 heading, INV-05 body now use claim-semantics vocabulary instead of legacy `fact`/`factual` phrasing. No semantic change; vocabulary alignment only.
- `skills/bsa-citation-auditor/SKILL.md` + `skills/bsa-claim-binder/SKILL.md` — corrected relative cross-ref paths to `reliability_tier_spec.md` (was `../../bsa-evidence-intake/...` which resolved one directory too high; now `../bsa-evidence-intake/...`).

### Canon policy version
- `1.0.0-rc1+hash:cbba8e53b0312aeec2744e17d018583fcd96bba613a6b39be58ab702cb44fcb0` at Sprint 4 US-S4-01 commit point. The `ac039430` prefix recorded in Sprint 3 retro + fixture markers reflects the Sprint 3 exit state; the move to `cbba8e53` captures the retroactive `governance/` sweep that landed as chore follow-ups between Sprint 3 close and Sprint 4 US-S4-01.

## [Unreleased]

### Added
- `skills/bsa-context-framer/` — new worker skill closing the Stage 2 runtime-native gap (Sprint 1 US-S1-01). Produces `context_state_frame.md`, `stakeholder_authority_map.md`, `system_context_seed.md`, `constraints_dependencies_route.md`, `stage2_summary.json` under `analysis/proposals/stage2/`. Three references: `context-state-contract.md` (artifact shape), `stakeholder-authority-rules.md` (authority taxonomy + contestation flow), `system-context-seed-template.md` (system-context structure + sidecar hook). Validation bindings `SCN-STAGE2-001-A..C`. Invariants: INV-01 evidence-binding per row; INV-07 analyst_judgment rows require JustificationRationale with upstream ClaimID references; Stage 2 may not introduce net-new actors/entities/events/statuses/rules.

### Changed
- `skills/bsa-orchestrator/SKILL.md`: Stage 2 description updated from "intentionally runtime-native" to "worker-owned by bsa-context-framer"; worker set for `bsa_pack_direct_mixed_sources` now includes bsa-context-framer between claim-binder and semantic-extractor (Sprint 1 US-S1-01 AC-6, AC-7).
- `skills/bsa-orchestrator/references/stage2-runtime-contract.md`: gained an Owner section pointing at bsa-context-framer; marked the "runtime-native" label as deprecated; authoritative artifact-shape reference now lives in bsa-context-framer's `context-state-contract.md` with lockstep-change commitment.
- `skills/bsa-orchestrator/references/validation-scenario-manifest.csv`: added three rows `SCN-STAGE2-001-A/B/C` covering artifact presence, required headers/columns, and summary-fields + analyst_judgment discipline.
- `skills/bsa-claim-binder/SKILL.md`: invariants expanded to close the ClaimType enum (INV-07), clarify evidence-binding for direct/inference rows, and explicitly state that claim-binder itself does NOT author analyst_judgment rows during Stage 1 intake.
- `config/request_skill_routes.json`: direct-pack worker_set extended with bsa-context-framer; runtime_notes on the direct route updated to describe the new Stage 2 ownership and the stage2.context_state.pass gate.
- `tests/test_validate_request_skill_routing.py`: expected direct-pack worker_set assertion updated from 14 to 15 skills (rationale in docstring).
- `fixtures/golden/project_0001/expected_outputs/canonical/stage2/`: new directory with 5 Stage 2 artifacts (context_state_frame, stakeholder_authority_map, system_context_seed, constraints_dependencies_route, stage2_summary.json) demonstrating the expected shape that `bsa-context-framer` produces; Stage 2 artifacts reference upstream ClaimIDs (C-001..C-007) and route authority contention through A51 (Sprint 1 US-S1-02).
- `fixtures/golden/project_0001/expected_markers/stage2.context_state.pass.json`: new marker capturing Stage 2 promotion verdict, SCN coverage, and stakeholder/constraint counts.
- `fixtures/golden/project_0001/audit_expectations.json`: expected_verdicts extended with `stage2.context_state.pass: PASS`.
- `scripts/fixture_runner.py`: Stage 2 shape validator added — checks required headers in context_state_frame + system_context_seed, required columns in stakeholder_authority_map + constraints_dependencies_route, required fields in stage2_summary.json, plus stage_id='stage2' and context_mode in {direct, discovery_then_bsa}.
- `tests/test_fixture_runner.py`: 8 new regression tests covering Stage 2 baseline pass + adversarial mutations (missing header, missing column, missing summary field, wrong stage_id, bad context_mode, deleted artifact) + presence-gate test ensuring fixtures without `canonical/stage2/` still validate cleanly (prevents accidental mandatory-gating).
- `docs/retros/sprint_1.md` — Sprint 1 retrospective documenting 4 approved commits, 6 review rounds total, delivery of bsa-context-framer skill closing the Stage 2 ownership gap, fixture extension, and the lesson-carryover from Sprint 0.5's defensive-validator pattern.

### Pre-Sprint-1 entries (preserved for reference)
- Repository bootstrap: baseline structure, .gitignore, README, CHANGELOG, LICENSE, CONTRIBUTING (US-S0-01)
- Skills imported from `~/.codex/skills/` at canon v0.9 baseline (22 skills: bsa-*, d0-*, c4-plantuml-from-context, camunda-bpmn-from-context, inot-prompt-builder) (US-S0-01)
- `governance/immutable_invariants.md` — seven invariants anchoring governance: evidence-binding, single-writer canonical, no-new-claims, two-key promotion, A51 not a fact source, composition-via-orchestrator, ClaimType schema closed (US-S0-05)
- `scripts/validate_skill_structure.py` + `tests/test_validate_skill_structure.py` — structural linter for SKILL.md frontmatter (name/description required), directory-name match, and relative-link resolution (references/, scripts/, assets/, tests/, evals/). 21 unit tests cover AC-1..AC-4 plus CRLF, single-quoted scalars, title variants, balanced parens in paths, symlink loops. Baseline health: 22/22 skills pass (US-S0-02).
- `scripts/inventory_audit.py` + `docs/inventory_audit.md` — classifies each skill as stable/flaky/orphan/broken, counts references/scripts/tests/fixtures, extracts SCN/CHK/ART-VAL validation bindings from SKILL.md. Baseline: 22 stable / 0 flaky / 0 orphan / 0 broken (US-S0-04).
- `scripts/privacy_scan.py` + `scripts/privacy_whitelist.json` + `tests/test_privacy_scan.py` + `docs/privacy_audit.md` — scanner for email / phone / credit-card (Luhn, both unseparated and formatted) / api-key (entropy + digit presence) / internal-URL patterns with severity-tiered verdicts (blocker/warning/info). Blocker findings fail CI. Whitelist requires `{match, reason}` and `{glob, reason}` object entries (bare strings rejected with exit 2). Skips NPM integrity hashes, sequential digit sequences, and binaries. 29 unit tests. Baseline: 0 blockers / 0 warnings / 0 info across 152 scanned files (US-S0-04).
- `.github/workflows/ci.yml` — CI pipeline on push/PR to main. Two jobs: `project-validators` (Python 3.11 + 3.12 matrix) runs structural lint, routing manifest validator, inventory audit (with idempotency check), privacy scan (with idempotency check), and pytest unit suite; `sidecar-validators` runs c4-plantuml validator + self-tests, BPMN XML lint via xmllint, and INoT smoke evals (non-blocking in Phase 0). Concurrency guarded per-ref to avoid duplicate spend on force-pushes. Timeout 5 min per job (US-S0-03).
- `config/request_skill_routes.json` + `config/request_skill_routes.schema.json` + `scripts/validate_request_skill_routing.py` + `tests/test_validate_request_skill_routing.py` — routing manifest declaring worker sets for `bsa_pack_direct_mixed_sources` (14 skills) and `discovery_pack_mixed_sources` (9 skills) per bsa-orchestrator/SKILL.md:38-63, plus sidecar policy. Validator checks schema conformance, orchestrator presence, referenced-skill existence, uniqueness, type discipline (bool-reject, regex on canon_policy_version), and additionalProperties closure at top-level + conditional_workers + sidecars. 25 unit tests, wired into CI as blocking check (US-S05-02).
- `fixtures/golden/project_0001/` + `scripts/fixture_runner.py` + `tests/test_fixture_runner.py` — first golden fixture (synthetic Support-Ticket Triage, direct mode, process path) exercising all three ClaimType values (direct, inference, analyst_judgment). Hand-authored representative shape with A48/A50/A51/A58/A59/A60 canonical artifacts + markers + `audit_expectations.json` + `fixture_metadata.json`. Runner has two modes: `validate` (checks INV-01 evidence-binding, INV-07 ClaimType enum closure, analyst_judgment JustificationRationale upstream-ClaimID requirement, marker/metadata field integrity) and `compare` (hash-based drift check). 15 unit tests, wired into CI (US-S05-01).

## [0.9.0-foundation] — Pre-release, Phase 0 kickoff

Initial import. No behavioral changes from source Codex skills. Provides version-control baseline for subsequent Phase 1-2 stabilization.
