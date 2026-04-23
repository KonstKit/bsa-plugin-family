# Changelog

All notable changes to the BSA Plugin Family. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + [Semantic Versioning](https://semver.org/spec/v2.0.0.html) for plugin versions.

Canon policy version (orthogonal measurement): `<semver>+hash:<sha256-prefix>`, computed from policy state (see [governance/immutable_invariants.md](governance/immutable_invariants.md) and Sprint 3 canon hash scheme).

## [v1.2.1] — 2026-04-23

**A72 LinkStrength override via A51 IssueType (Sprint 2 / T2).** Closes `TODO-S8-02-LINK-STRENGTH-OVERRIDE` from `skills/bsa-traceability-matrix/SKILL.md`. Adds the missing piece of the A72 LinkStrength contract: the operator-override path. Pre-v1.2.1 the SKILL.md said "operator may explicitly override (raise OR lower) with A51 rationale" but no specific `IssueType` existed for that purpose — operators had to reuse `decision_needed` or `uncertainty`, both of which downstream KPI tooling treats as different signals. v1.2.1 introduces a dedicated `link_strength_override` enum value so override annotations are filterable separately.

**Tag target**: this commit. **Canon policy version**: `1.2.1+hash:6821009d` — **bumps from 1.2.0+hash:5d8ae8b6** (A51 schema + shared-control-surface-contracts.md + bsa-traceability-matrix SKILL.md all in POLICY_GLOBS; canon hash necessarily moves).

### Updated

- **`governance/schemas/a51.schema.json`** — `IssueType` enum extended with `link_strength_override` (now 8 values, was 7). Description block expanded with operator workflow + distinction from generic `decision_needed`.
- **`skills/bsa-orchestrator/references/shared-control-surface-contracts.md`** — A51 minimal-columns reference updated to list the new enum value (in lockstep per the schema's own description requirement).
- **`skills/bsa-traceability-matrix/SKILL.md`** — `[TODO-S8-02-LINK-STRENGTH-OVERRIDE]` marked CLOSED with the operator workflow + cross-ref.
- **`tests/test_schemas_a51.py`** (+1 representative-row test) — pins a v1.2.1 row with `IssueType=link_strength_override` + `BlockingStatus=informational` (the recommended posture; override is annotation, not gate).
- **`.claude-plugin/plugin.json`** — version 1.2.0 → 1.2.1; canonPolicyVersion fields updated to 6821009d.
- **`docs/RELEASING.md`** — table entry added.
- **`README.md`, `INSTALL.md`, `docs/getting_started.md`, `docs/faq.md`** — current-release lines refreshed to 1.2.1.

### Operator workflow

When emitting an A72 row whose `LinkStrength` differs from the default formula (T1/T2 → high; T3 → medium; T4/T5 → low):

1. Create an A51 row with `IssueType=link_strength_override`. Recommended `BlockingStatus=informational` (override is annotation, not a promotion gate).
2. The A51 row's `NextAction` carries the rationale (e.g., `"LinkStrength manually raised from 'low' (T4 default) to 'medium' — independent observation by ops lead corroborates the source despite tier"` or `"LinkStrength lowered from 'high' (T2 default) to 'medium' — source applies only partially to this story scope"`).
3. Populate the A72 row's `A51Ref` with the new A51's ref. Schema enforcement at hook time (existing A51-ref validity check) catches typos.

### Codex review trail

Review pending — will run + append round findings when complete.

### Result

- 1635 → 1636 tests passing (+1 representative-row test for the new enum value).
- A72 LinkStrength override now has a first-class A51 IssueType. Downstream KPI / H4 packet / orphan-report tooling can filter overrides separately to detect a class of fixture-shape drift.

## [v1.2.0] — 2026-04-23

**First canon-bump since v1.1.6 (Sprint 2 / H2 — reverse cross-ref to Phase 7 design).** Establishes the v1.2.x line. Single deliberate edit: `governance/immutable_invariants.md` §"Scope of self-improvement" now opens with a `**See `docs/phase_7_design.md`**` cross-ref to the v1.1.14 foundation. v1.1.14 deferred this edit explicitly because invariants.md is in POLICY_GLOBS — touching it bumps the canon hash and breaks the v1.1.x manifest-stable discipline. v1.2.0 is the right release to land it: the canon bump is intended (this is the first of the v1.2.x line) and minimal (one line).

**Tag target**: this commit. **Canon policy version**: `1.2.0+hash:5d8ae8b6` — **bumps from 1.1.6+hash:ac63a8c3** (the first canon-state change since v1.1.6 went live in v1.1.6 release).

### Updated

- **`governance/immutable_invariants.md`** — §"Scope of self-improvement (Phase 7 L1/L2)" now opens with the cross-ref `**See [docs/phase_7_design.md](../docs/phase_7_design.md)**` pointing at the v1.1.14 foundation. The reverse cross-ref makes the relationship bidirectional (design doc already links to invariants.md as its source of truth).
- **`.claude-plugin/plugin.json`** — `version` 1.1.6 → 1.2.0; `canonPolicyVersion.semver` 1.1.6 → 1.2.0; `canonPolicyVersion.hash_prefix` ac63a8c3 → 5d8ae8b6; `canonPolicyVersion.hash_full` updated; `canonPolicyVersion.computed_at` updated.
- **`docs/RELEASING.md`** — release table back-filled with v1.1.11..v1.1.19 entries (all canon-neutral) + v1.2.0 entry (first canon-bump since v1.1.6).

### Why this is a deliberately small canon-bump release

v1.1.x established a discipline: never bump the canon hash unless you actually need to. v1.2.0 follows that discipline literally — the minimum viable change to legitimately move the canon hash is editing one file in POLICY_GLOBS. We picked the long-deferred H2 cross-ref because:
1. It's a real improvement (operators following the invariants link can now find the v1.1.14 foundation easily).
2. It's a one-line change with zero risk of breaking anything.
3. It opens the v1.2.x line cleanly without bundling unrelated work into the canon-bump release.

The next v1.2.x releases (T2 LinkStrength override, T1 incremental matrix, T3 runnable export) each get their own canon-bumping releases, following the same one-deliberate-change-per-release pattern.

### Codex review trail

- **Round 1**: REJECT — 1 MEDIUM. Bump itself sound (only invariants.md touched in POLICY_GLOBS; manifest fields consistent; canon-hash test passes); but several user-facing docs still pinned `1.1.6` / `v1.1.8` / "v1.1.x line" as current. **Fixed**: refreshed README.md (manifest expectation + current-release line), INSTALL.md (manifest expectation), docs/getting_started.md (manifest expectation), docs/faq.md (current-release section rewritten to reflect v1.2.0 + v1.1.x history).
- **Round 2**: REJECT (PARTIAL) — `(this release)` parenthetical at README.md:44 was correctly stale and removed. Other flagged references (README.md:42 + 44 historical bullets, INSTALL.md:51 caveat with v1.1.7..v1.1.19 history note, getting_started.md:97 `(v1.1.6)` annotation on `backlog_live_apply.py`, faq.md:136-138 "Closed in v1.1.x" feature-history bullets) are FACTUAL `shipped-in-vX` history — they say WHEN a feature first landed, not what's current. The CHANGELOG + docs/RELEASING.md table are the source of truth for "what's current"; per-feature historical annotations correctly carry their original release tag and should NOT be rewritten. Acceptance criterion explicitly narrowed: doc references that frame themselves as `current release` / `this release` MUST track the live manifest; doc references that frame themselves as historical `shipped-in-vX` / `closed-in-vX` are ALLOWED to keep their original version literal.

### Result

- 1635 tests passing (no test changes; only invariants doc + manifest fields + 4 user-facing doc refreshes).
- Canon hash: `ac63a8c3` → `5d8ae8b6` (first move since v1.1.6 went live in the v1.1.6 release).
- Manifest version: 1.1.6 → 1.2.0.
- v1.2.x line is now open. Subsequent releases (T2/T1/T3 from the Sprint-2 plan) will each be their own canon-bumping releases following the same minimal-change discipline.

## [v1.1.19] — 2026-04-23

**Anonymization regression test (Sprint 1 / H4).** Pins the v1.1.7 anonymization contract mechanically. Prior to this release, the scrub was a one-time commit verified by ad-hoc grep; any future maintainer who copy-pasted a retro mention into an active-surface file would silently re-introduce the client name. v1.1.19 closes that gap with a pytest regression scan.

**Tag target**: this commit. **Canon policy version**: `1.1.6+hash:ac63a8c3` — **unchanged**. Regression test + the two scrubbed doc lines all outside POLICY_GLOBS; manifest stays at 1.1.6.

### Added

- **`tests/test_anonymization_regression.py`** (+5 tests) — pins:
  * `test_no_forbidden_tokens_in_active_surface` — headline scan: walks the entire active surface (excluding `docs/retros/`, this test file itself, and tooling artifacts like `.pytest_cache`/`.git`/`node_modules`); fails with file:line for every leak. Uses word-boundary-anchored case-insensitive regex so `FORBIDDEN_TOKENS` additions are safe. Scans both file BODY and file PATH (filename-leak coverage from Codex round-1).
  * `test_forbidden_tokens_list_is_non_empty` — defensive pin that silently-cleared `FORBIDDEN_TOKENS` doesn't disable the regression.
  * `test_exempt_paths_match_documented_intent` — pins `docs/retros/` + this test file's exemption (the v1.1.7 contract surface).
  * `test_filename_leak_detected` — regression pin: synthesises a tmp repo with a file whose NAME contains the forbidden token (body is clean); asserts the scanner fires with a FILENAME-leak diagnostic + does NOT false-positive on an adjacent clean file. Synthetic-fixture-only — the literal token is NOT spelled out in this CHANGELOG entry to avoid the regression test self-flagging the changelog.
  * `test_pilot_1_alias_appears_in_active_surface` — defense-in-depth: if v1.1.7 got reverted (alias `Pilot-1` gone from the surface), this test fires independent of the forbidden-token scan.

### Updated

- **`docs/phase_3_plan.md`** — two leaked client-name mentions (lines 91 + 100 per v1.1.7 scrub catalogue) replaced with `Pilot-1`. The retros directory (`docs/retros/*.md`) remains intentionally untouched per the v1.1.7 "historical record" carve-out.

### Codex review trail

- **Round 1**: REJECT — 1 HIGH + 2 MEDIUM + 1 LOW.
  * **HIGH**: earlier impl scanned file BODIES only; a filename leak (token in path, not content) would pass. **Fixed**: added parallel filename / repo-relative path scan + `test_filename_leak_detected` regression.
  * **MEDIUM**: CHANGELOG said "one scrubbed doc line"; reality is 2 (lines 91 + 100 in `docs/phase_3_plan.md`). **Fixed**: wording corrected to "two scrubbed doc lines".
  * **MEDIUM**: CHANGELOG said scan walked "459 tracked files" but the walk is a filesystem walk (`os.walk`), not git-tracked. **Fixed**: wording corrected to "the active surface" (file-count omitted since it varies by working-tree state).
  * **LOW**: line-by-line scan could miss a token split across two lines. **Round-1 fix attempt**: switched to full-body finditer + re.DOTALL — but Codex round-2 caught that this STILL doesn't catch `sy\nsco` because the regex literal has no `\n`. **Round-2 fix**: added a parallel scan against a whitespace-stripped form of the body (no word boundaries, since stripping glues words together). New test `test_cross_line_split_detected` synthesises a file with `sy\nsco` body, asserts the scanner fires.
- **Round 2**: REJECT — HIGH/MEDIUM closed; LOW still OPEN per the round-1 attempt's incompleteness. **Fixed via stripped-body fallback** (see LOW notes above).
- **Round 3**: APPROVE with non-blocking LOW (false-positive surface on benign phrases that happen to combine into the forbidden token after whitespace stripping). Documented as deliberate v1.1.19 tradeoff via `test_stripped_scan_avoids_false_positive_on_split_words` regression that PINS the false-positive behavior — flipping the assertion in a future release signals the fallback got upgraded. (Concrete example omitted from this changelog text to avoid the regression test self-flagging the changelog — see the test docstring for the pinned scenario.)

### Result

- 1628 → 1635 tests passing (+7 anonymization regression tests).
- Anonymization is now executable contract, not just a one-time commit. Any future accidental re-introduction of the scrubbed name into the active surface (body OR filename OR cross-line-split) fires at CI, not at first external distribution.
- Active surface scan walked + reports zero violations.

## [v1.1.18] — 2026-04-23

**Sidecar common config schema + registry batch (Sprint 1 / S1+S2).** Closes the two open follow-ups from `docs/sidecar_inventory.md`. Sets up the foundation for adding 3rd / 4th sidecars (DBML, sequence-diagram, etc.) without re-defining the anchor manifest contract per sidecar.

**Tag target**: this commit. **Canon policy version**: `1.1.6+hash:ac63a8c3` — **unchanged**. Base schema + registry + lint live outside POLICY_GLOBS; manifest stays at 1.1.6.

### Added

- **`governance/schemas/sidecar_anchor_manifest.base.schema.json`** (S1) — shared base schema defining the 5 required top-level fields every sidecar's anchor manifest MUST carry: `manifest_version`, `generated_at`, `sidecar`, `canon_policy_version`, `view_files` (non-empty array). Per-sidecar schemas under `skills/<sidecar>/references/anchor_manifest.schema.json` extend this base with sidecar-specific discriminators (`diagram_type` for c4, `bpmn_profile` for bpmn). NOT directly F5-validated (per-sidecar schemas remain the F5 surface) — pinned by the registry lint + tests instead.
- **`config/sidecar_registry.yaml`** (S2) — operator-discoverable registry of all sidecars. Per-entry: `name`, `output_format`, `f5_path_prefix`, `integration_contract`, `anchor_manifest_schema`, `optional_dependencies`, `status` (stable / beta / experimental), `added_in` (plugin version), `summary`. Two entries today (c4-plantuml, camunda-bpmn).
- **`scripts/sidecar_registry_lint.py`** — stdlib + pyyaml lint with 7 checks:
  * **C1**: each entry's `name` matches a real `skills/<name>/` directory.
  * **C2**: `integration_contract` path exists.
  * **C3**: `anchor_manifest_schema` exists AND its `required` list includes ALL base-schema required fields (catches per-sidecar schema drift).
  * **C4**: `f5_path_prefix` does NOT contain any POLICY_GLOBS entry (sidecar paths must stay non-canonical — uses the AST-based POLICY_GLOBS reader from `phase_7_lint.py`).
  * **C5**: no two entries share the same `name`.
  * **C6**: required fields all present + non-empty.
  * **C7**: `status` ∈ {stable, beta, experimental}.
- **`tests/test_sidecar_registry.py`** (+14 tests) — pins committed registry passes lint; both shipping sidecars listed; per-sidecar schemas inherit base required fields (defense-in-depth check independent of lint); per-check unit triggers on synthetic broken inputs (C1–C7).

### Updated

- **`.github/workflows/ci.yml`** — added `sidecar-registry-lint` job (9th parallel job alongside pytest matrix, fixture-runner, privacy-scan, security-audit, canon-hash, marker-chain, perf-bench, phase-7-lint).
- **`tests/test_ci_workflows.py`** — required-jobs set bumped 8 → 9.
- **`docs/sidecar_inventory.md`** — both follow-ups (Common SidecarConfig schema, Sidecar registry) marked closed with cross-refs to v1.1.18 deliverables.
- **`README.md`** — Documentation section adds links to registry + base schema.

### Codex review trail

- **Round 1**: REJECT — 1 HIGH + 2 MEDIUM.
  * **HIGH**: C3 only compared top-level `required` keys; a per-sidecar schema could keep the 5 required fields but mutate `view_files` to a non-array OR drop `minItems`/`items.required` and silently pass. **Fixed**: C3 now also pins (a) `properties.view_files.type == "array"`, (b) `properties.view_files.minItems >= 1`, (c) each `view_files[]` item requires `path` + `anchor_map`. New error codes: `C3_ANCHOR_SCHEMA_VIEW_FILES_NOT_ARRAY`, `C3_ANCHOR_SCHEMA_VIEW_FILES_ALLOWS_EMPTY`, `C3_ANCHOR_SCHEMA_VIEW_FILES_ITEM_MISSING_REQUIRED`. Three new regression tests pin each.
  * **MEDIUM #1**: registry YAML header documented checks 1–5 while implementation has 7. **Fixed**: header now lists all 7 checks (C1-C7) with C3's full sub-conditions (a-d). Lint script header also updated.
  * **MEDIUM #2**: POLICY_GLOBS reader silently dropped non-string elements (unlike `phase_7_lint.py` which fails loudly). **Fixed**: now raises `RuntimeError` on any non-string element with message matching the phase_7_lint contract.

- **Round 2**: REJECT — HIGH still PARTIAL (C3 bypass when `properties.view_files` is absent entirely). MEDIUM #1 + MEDIUM #2 closed. **Fixed**: added `C3_ANCHOR_SCHEMA_VIEW_FILES_NOT_DEFINED` check that fires when `view_files` is in `required` but not declared under `properties`. Deeper structural checks now correctly short-circuit when view_files is missing (avoids noise; tested explicitly). New regression test `test_C3_view_files_not_defined`.

### Result

- 1610 → 1628 tests passing (+18 sidecar registry tests; 14 round-1 + 3 round-2 view_files conformance + 1 round-2 view_files NOT_DEFINED).
- The two open follow-ups from `docs/sidecar_inventory.md` are closed; remaining post-v1.1.x sidecar work (S3 e2e fixture, S4 DBML sidecar, S5 sequence-diagram sidecar) is now genuinely additive — adding a 3rd sidecar requires only a registry entry + skill directory + per-sidecar anchor schema (which the registry lint validates against the base shape via 5 sub-checks: required overlap + view_files defined + array + non-empty + items.required).

## [v1.1.17] — 2026-04-23

**Shell import drivers (Sprint 1 / T5).** Closes `TODO-S9-03-IMPORT-DRIVER` from `scripts/backlog_live_apply.py`. Three thin bash wrappers that consume `analysis/handoff/backlog_export_{jira,linear,github}.{json,csv}` and POST to the live platform — alternative to the Python impl for operators whose CI / environment doesn't have full Python, or who simply prefer shell.

**Tag target**: this commit. **Canon policy version**: `1.1.6+hash:ac63a8c3` — **unchanged**. Shell drivers + doc live outside POLICY_GLOBS; manifest stays at 1.1.6.

### Added

- **`scripts/jira_import_from_export.sh`** — Jira REST v3 driver. Uses `bash + jq + curl`. Auth via `$BSA_JIRA_EMAIL` + `$BSA_JIRA_TOKEN`. Basic-auth header. Retries on 429/5xx with exponential backoff, 5-attempt budget.
- **`scripts/linear_import_from_export.sh`** — Linear GraphQL driver. Uses `bash + jq + curl + python3` (for RFC-4180 CSV parsing). Auth via `$BSA_LINEAR_TOKEN`. Checks `data.issueCreate.success` + `errors[]` even on HTTP 200 (Linear always returns 200 regardless of GraphQL outcome).
- **`scripts/github_import_from_export.sh`** — GitHub Issues + Projects v2 driver. Uses `bash + gh CLI + python3` (for CSV parsing). Auth via `gh auth login` OR `$GH_TOKEN` / `$GITHUB_TOKEN`. Optional Projects v2 attach via `--project-owner` + `--project-number`.
- **`docs/shell_import_drivers.md`** — operator-facing contract: three drivers, common dry-run / idempotency / auth / exit-code contract, comparison with the Python impl.
- **`tests/test_shell_import_drivers.py`** (+22 tests) — pins:
  * All three scripts exist + executable + use `#!/usr/bin/env bash` shebang.
  * `--help` exits 0 + prints Usage.
  * No `declare -A` usage (macOS bash 3.2 compatibility — associative arrays are bash 4+).
  * Dry-run prints the plan against synthetic fixtures (no real API calls).
  * `--apply` refuses without required auth env var + target arg (`--base-url` for Jira, `--team-id` for Linear, `--repo` for GitHub).
  * Idempotency: a prior `live_api_response_jira_shell.json` (NOTE: separate path from Python's canonical `live_api_response_jira.json`; see Round 3 notes) with a matching idempotency key causes the row to be SKIPPED on the next run.
  * Dependencies (jq, curl, gh, python3) checked early; missing dep exits 2.

### Updated

- **`docs/faq.md`** — moved "Operator-side import drivers" from "Still deferred to Phase 5+ / future" to "CLOSED in v1.1.17" with cross-ref.
- **`README.md`** — Documentation section adds link to `docs/shell_import_drivers.md`.

### Design notes

- **Idempotency key format** — shell drivers use `bsa-{StoryID}-sh-{sha256(StoryID|Title)[:8]}` (the `sh-` infix distinguishes shell-driver keys from the Python impl's canon-hash-prefix keys). The two key spaces do NOT collide, so operators can switch between the two tracks without corrupting state.
- **CSV parsing** — pure bash `while IFS=, read` is too fragile for Linear's `Description` column (markdown with embedded commas + RFC-4180 quotes). The drivers inline a `python3 -c "import csv; ..."` snippet. This does mean shell drivers require Python3 for CSV platforms (Linear + GitHub); pure-shell CSV parsing was rejected as a correctness liability.
- **gh vs curl for GitHub** — the GitHub driver uses the `gh` CLI natively because (a) `gh` is universally available in GitHub-adjacent environments, (b) it handles both Issues (REST) AND Projects v2 (GraphQL) through one unified auth story, (c) the Python impl only handles Issues and defers Projects v2 to the operator — the shell driver closes that gap.
- **macOS bash 3.2 compatibility** — early iteration used `declare -A DONE_KEYS` for idempotency tracking; this broke on macOS's default bash 3.2 (Apple doesn't ship bash 4 due to GPLv3). Rewrote to use a tmpfile + `grep -Fxq` pattern. Pinned by `test_script_avoids_declare_dash_a`.

### Codex review trail

- **Round 1**: REJECT — 3 critical/high + 3 should-fix.
  * **CRITICAL #1 (CRITICAL)**: Jira `-u email:token` and Linear `-H "Authorization: $TOKEN"` leaked credentials into curl argv (visible via `ps`/`/proc`). **Fixed**: both drivers now write a 0600-perm curl config tmpfile (`user = "..."` for Jira basic-auth, `header = "Authorization: ..."` for Linear) and pass via `-K <tmpfile>`. Tmpfile cleaned on EXIT trap. New `test_jira_auth_not_in_argv` + `test_linear_auth_not_in_argv` regression tests (look for `-u`/`-H "Authorization:"` in non-comment script body).
  * **CRITICAL #2 (CRITICAL)**: Jira POST body shape was `.fields` directly; Jira REST v3 expects `{"fields": {...}}`. **Fixed**: jq emitter now produces `{fields: .fields}` so `raw_issue` is the full request body. New `test_jira_body_wraps_fields_correctly` pins the wrapping shape.
  * **HIGH #3 (HIGH)**: shell drivers READ prior `live_api_response_*.json` for idempotency but never WROTE new state, so re-running the shell driver itself would re-create every row. **Fixed**: each driver now appends `OUTCOMES+=("${idem_key}|${outcome}|${story}")` per row and writes the merged state via inline `python3 - <<'PY'` (atomic tmp + mv pattern). Prior entries from Python impl OR earlier shell runs are preserved (de-dup by idempotency_key). Dry-run does NOT write state. New `test_jira_apply_without_apply_flag_does_not_write_state` + `test_jira_prior_state_preserved_on_rerun` + `test_linear_prior_state_skips_already_created`.
  * **SHOULD #1 (MEDIUM)**: test coverage missing malformed-input + Linear/GitHub idempotency + Linear missing-auth + GitHub used Linear CSV shape. **Fixed**: added `_write_github_csv_export` with correct GitHub schema (Body/Size, not Description/Estimate); added `test_jira_malformed_json_does_not_crash`, `test_linear_malformed_csv_does_not_crash`, `test_linear_apply_refuses_without_token`.
  * **SHOULD #2 (MEDIUM)**: Python→bash TSV handoff fragile if Title contains tabs/newlines. **Fixed**: jq's `@tsv` operator escapes embedded tabs/newlines in field values automatically (Jira); for Linear/GitHub, the Python emitter uses `\t` as separator + the schemas constrain Title to `^[^\t\n]+` shape implicitly (the F5 schema validation catches violations before export hits the driver).
  * **SHOULD #3 (LOW)**: per-row tmpfiles only cleaned on happy path. **Fixed**: extended EXIT trap to include `/tmp/{jira,linear,github}_resp_$$.json` etc.

- **Bash 3.2 process-substitution quirk**: round-1 added multi-line comments inside `done < <(jq ...)` block; bash 3.2 on macOS choked on this (FD setup failed; `/dev/fd/62: No such file or directory`). Resolved by collapsing the jq filter to a single line + moving documentation comments OUTSIDE the process substitution. Pinned by the existing dry-run smoke tests.

- **Round 2**: REJECT — 3 PARTIAL (round-1 #3 state writeback, #1 test coverage, #2 TSV) + 3 NEW (HIGH cross-tool state shape mismatch, MEDIUM mktemp not in same FS, MEDIUM SIGTERM not trapped).
  * **HIGH (cross-tool state mismatch)**: round-1 wrote `.rows[]/.outcome` shape; the canonical Python impl uses `.results[]/.status`. Cross-tool runs would NOT interoperate. **Fixed**: all 3 drivers now ACCEPT both shapes on read (transparent in-place upgrade) and ALWAYS WRITE the canonical Python shape (`.results[].status`, with `attempts` + `updated_at` + `driver: "shell"` fields). New `test_drivers_accept_canonical_results_shape` + `test_drivers_accept_legacy_rows_shape` regression tests.
  * **MEDIUM (atomic mv)**: round-1 used `mktemp -t` which creates the tmpfile under `/tmp` — `mv` to `analysis/handoff/` may cross filesystems (non-atomic). **Fixed**: tmpfile now created in `dirname(STATE_PATH)` so `mv` is guaranteed-atomic on the same FS.
  * **MEDIUM (signal cleanup)**: bash 3.2 doesn't run EXIT trap on untrapped SIGTERM/SIGINT — a Ctrl-C during execution could leave AUTH_TMP behind. **Fixed**: `trap cleanup_all EXIT INT TERM` in all 3 drivers.
  * **PARTIAL (#1 test coverage)**: missing GitHub idempotency test. **Fixed**: added `test_github_prior_state_skips_already_created`.
  * **PARTIAL (#2 TSV robustness)**: round-1 emitted raw Title/StoryID through Python→bash TSV pipe; tabs/newlines in those fields would desync. **Fixed**: inline Python parser now sanitizes `[\t\r\n]+ → space` for both StoryID and Title before emit. (jq's `@tsv` already handled this for the Jira driver.)

- **Round 3**: REJECT — HIGH (cross-tool state shape) still OPEN despite round-2 attempt to mimic Python `.results[]/.status` shape. Codex correctly identified that the Python state file is F5-validated against `governance/schemas/live_api_response.schema.json` (additionalProperties:false + required `operator_run_id`/`platform_base_url`/`summary`/canon-hash-prefix idempotency keys) — shell drivers can't easily produce schema-conforming state without reimplementing the full Python contract. **Design pivot**: shell drivers now use a SEPARATE state path (`live_api_response_<platform>_shell.json`) with a simpler `.results[]/.status` shape, no F5 validation. Python and shell are independent tracks; mixing them in one workspace duplicates platform-side issues (idempotency-key formats also differ — `-sh-` infix). Documented as a deliberate design choice in `docs/shell_import_drivers.md` §"State files". New `test_drivers_use_separate_state_path_from_python` regression pins that the canonical Python state file is NEVER touched by shell-driver runs. ALSO: Codex round-3 NEW MEDIUM — trap registered AFTER AUTH_TMP creation left a small leak window. Fixed: trap now installed BEFORE AUTH_TMP population.

### Result

- 1575 → 1610 tests passing (+35 in test_shell_import_drivers.py: 22 round-1 + 9 round-2 + 3 round-2 cross-tool + 1 round-3 separate-state).
- Jira / Linear / GitHub imports now have a lightweight shell alternative to the Python heavy-weight. Operators can pick the tool that fits their environment, but **must pick ONE per workspace** (shell + Python state files are independent; mixing causes platform-side duplication).
- `TODO-S9-03-IMPORT-DRIVER` closed; the Phase-3 live-apply backlog is now down to zero open items.
- Credentials never appear in curl argv. Trap registered before any sensitive tmpfile creation (closes pre-trap leak window). State writeback uses simpler `.results[]/.status` shape at separate `*_shell.json` path; mv is atomic (same-FS tmpfile). SIGTERM/SIGINT also trigger cleanup. Jira POST body matches REST v3.

## [v1.1.16] — 2026-04-23

**`--strict-on-hard-a51` opt-in mode (Sprint 1 / T6).** Closes the v1.1.5 spec-as-fixture (`adversarial_block_on_contradiction_001`) by implementing the proposed opt-in failure mode. Default `/bsa-promote` posture is unchanged (permissive — surface contradictions as A51, do not block). When the operator opts in via `--strict-on-hard-a51` (or `BSA_STRICT_ON_HARD_A51=1`), the orchestrator hook runs a pre-flight check BEFORE acquiring the canonical merge lock and refuses the write if any A51 row has `BlockingStatus=hard` AND `ResolutionStatus=open` AND no H4 waiver in `## Decisions Required`.

**Tag target**: this commit. **Canon policy version**: `1.1.6+hash:ac63a8c3` — **unchanged**. New script + new hook branch + new doc all live outside POLICY_GLOBS; manifest stays at 1.1.6.

### Added

- **`scripts/promote_strict_preflight.py`** — stdlib-only preflight (~210 lines). Scans both main + discovery A51 registers for `BlockingStatus=hard + ResolutionStatus=open` rows; collects H4 waivers from `## Decisions Required` sections; emits structured BLOCKED message on stderr matching the format pinned by `tests/test_adversarial_b3_fixtures.py`. Exit codes: 0 (clean / waivered), 1 (block), 2 (invocation error).
- **`docs/strict_a51_mode.md`** — operator-facing contract: what it does, why opt-in, escape hatches, BLOCKED message shape, exit codes, when to use / not use.
- **`tests/test_promote_strict_preflight.py`** (+21 tests; 17 round-1 + 3 round-2 boundary + malformed-CSV + 1 round-3 overflow) — pins:
  * Classification logic (only `BlockingStatus=hard + ResolutionStatus=open` blocks; soft / informational / closed-status rows pass).
  * Discovery-zone A51 register also scanned.
  * H4 waiver detection: only `## Decisions Required` references count; mentions in `Open Items Digest` / `Suggested Owners` do NOT.
  * Partial waiver: 2 blockers + 1 waivered → still blocks on the other.
  * Edge cases: missing workspace → exit 2, no A51 file → exit 0, empty A51Ref → exit 2 (no silent block-bypass).
  * Spec-fixture end-to-end: synthetic workspace built from `adversarial_block_on_contradiction_001/` produces the exact BLOCKED message format.
  * `format_blocked_message()` truncates long NextAction to 80 chars + `...`.
  * Hook integration: both `--strict-on-hard-a51` flag AND `BSA_STRICT_ON_HARD_A51=1` env activate the preflight; default mode (no flag/env) skips the preflight entirely.

### Updated

- **`hooks/pre_bash_promote.sh`** — added strict-mode branch after the existing marker check. Detects flag OR env; invokes preflight script; propagates exit code. Default mode is zero-overhead.
- **`commands/bsa-promote.md`** — documented `--strict-on-hard-a51` flag with cross-ref to `docs/strict_a51_mode.md`.
- **`docs/faq.md`** — moved `--strict-on-hard-a51` from "Still deferred" to "Closed in v1.1.16" with cross-ref.
- **`fixtures/golden/adversarial_block_on_contradiction_001/`** — `spec_only` flipped from `true` → `false` (in both `fixture_metadata.json` + `audit_expectations.json`); README updated to reflect the v1.1.16 implementation; `_spec_only_history` field added documenting the transition.
- **`tests/test_adversarial_b3_fixtures.py`** — `test_metadata_marks_spec_only` renamed → `test_metadata_marks_spec_only_false_post_v1_1_16` and pin inverted (`is True` → `is False`); `test_proposed_strict_mode_preflight_blocks_on_open_hard_a51` switched from mock to real-script invocation against synthetic workspace.
- **`README.md`** — Documentation section adds link to `docs/strict_a51_mode.md`.

### Codex review trail

- **Round 1**: REJECT — 2 critical + 3 should-fix.
  * **CRITICAL #1 (HIGH)**: hook substring match `*--strict-on-hard-a51*` falsely activated on `--strict-on-hard-a51-EXTRA` / any arg containing the flag as a substring. Fixed: bash regex with word boundaries: preceded by start-of-string OR whitespace, followed by end-of-string OR whitespace OR `=`. New test `test_hook_boundary_aware_flag_does_not_activate_on_suffixed_token` pins the fix.
  * **CRITICAL #2 (HIGH)**: preflight fail-opened on malformed CSV — typoed `ResolutionStatus` header or truncated row silently classified every row as non-blocking (a real hard+open blocker would slip through strict mode). Fixed: pre-check that ALL required columns are present in the header AND no cell is None (csv.DictReader pads missing with None for short rows); any violation surfaces as exit-2 parse error (fail-CLOSED). New `REQUIRED_A51_COLUMNS` constant + 2 tests (`test_malformed_csv_missing_header_column_exits_2`, `test_malformed_csv_truncated_row_exits_2`).
  * **SHOULD #1 (MEDIUM)**: fixture README still said "proposed", "spec_only: true", "deferred to v1.2" in 5 places. Fixed: rewrote sections "Block-on-contradiction contract" (→ "live as of v1.1.16"), "Files" list (→ `spec_only: false` note), "What this fixture does NOT cover" (→ cross-refs to test file), "Synthetic vs live-run" (→ direct-invocation description).
  * **SHOULD #2 (MEDIUM)**: `commands/bsa-promote.md` listed "No unresolved hard-blocking A51 items" as a general precondition — contradicted the opt-in-only design. Fixed: annotated as "(opt-in only, v1.1.16)" with cross-ref to `docs/strict_a51_mode.md`.
  * **SHOULD #3 (LOW)**: CHANGELOG test-count math claimed "+19 new − 2 reorganised"; reality was 17 new + renames (not removals). Fixed with accurate math in the final Result section.

- **Round 3**: REJECT — 1 new HIGH (unflagged extra-field CSV overflow fail-open). Fixed: added `overflow = row.get(None)` check after the missing-cell check; any row with content past the last named column surfaces as exit-2 parse error with an RFC-4180 quoting hint. New test `test_malformed_csv_extra_field_overflow_exits_2` pins the fail-CLOSED path for unescaped commas in text fields.

### Result

- 1554 → 1575 tests passing (+17 round-1 + 3 round-2 + 1 round-3 = 21 new in test_promote_strict_preflight.py; test_adversarial_b3_fixtures.py had 2 renames/body rewrites for the spec_only flip, no net +/-).
- The v1.1.5 spec-as-fixture is now a live regression baseline. Any future drift in the BLOCKED message format or strict-mode contract will fail at CI.
- The `--strict-on-hard-a51` flag is operator-controllable and CI-controllable (`BSA_STRICT_ON_HARD_A51=1`) — engagements that want zero-open-blockers as a release gate can flip it without orchestrator-side changes.

## [v1.1.15] — 2026-04-23

**2nd Pilot-1 pass prep (Section K).** Closes Open Backlog #1 from `docs/pilot_validation.md` (operator runbook for manual-review steps). The actual 2nd Pilot-1 doctor pass remains operator-blocked — needs an operator with access to the real Pilot-1 workspace + signoff. v1.1.15 ships everything the framework can do without that operator action: the runbook + a pre/post doctor-output diff helper.

**Tag target**: this commit (the v1.1.15 Pilot-1 prep release).
**Canon policy version**: `1.1.6+hash:ac63a8c3` — **unchanged**. Runbook + helper live outside POLICY_GLOBS; canon hash unchanged. Manifest version stays at 1.1.6; v1.1.15 git tag marks the prep release.

### Added

- **`docs/pilot_2nd_pass_runbook.md`** — operator runbook (~200 lines) covering:
  * Pre-flight capture (`bsa doctor > pre.txt` + workspace snapshot).
  * Step 1: mechanical migration (`migrate_v1.0_to_v1.1.py --all-mechanical --apply`).
  * Step 2: manual reviews with decision trees for the 4 manual-review drift classes (B verdict caveats, E A50 AccessStatus partial, G A60 column-set, H A51 reconciliation).
  * Step 3: re-run doctor + interpret the section-by-section verdict.
  * Step 4: diff pre/post via `compare_doctor_outputs.py`.
  * Step 5: reporting template (what bundle to send back to the maintainer).
  * Common gotchas (idempotent re-runs, .pre-v1.1.bak handling, F5 hook rejections, gitignore).
- **`scripts/compare_doctor_outputs.py`** — stdlib-only diff helper that classifies each doctor section: CLOSED (FAIL→OK) / NEW (OK→FAIL — regression alert) / PERSISTED (no progress) / CHANGED (partial progress with detail change) / STILL_OK / DROPPED / ADDED. Exits 1 on any NEW section so CI / operators are alerted to regressions before declaring the migration successful. Tolerates trailing content on the status line ("(3 of 22 files)") so finding-count shifts surface as CHANGED, not PERSISTED.
- **`tests/test_compare_doctor_outputs.py`** (+24 tests) — pins:
  * Parser correctness on all 4 status types + multi-line detail bodies + trailing-content-on-status-line.
  * All 7 classification deltas (CLOSED / NEW / PERSISTED / CHANGED / STILL_OK / DROPPED / ADDED).
  * Exit code 1 fires on NEW (regression).
  * Text + JSON reporters produce non-empty output of the right shape.
  * CLI smoke tests against tiny captured outputs (file-missing, unrecognisable input, --json flag).

### Updated

- **`docs/pilot_validation.md`** — Open Backlog #1 (operator runbook) marked closed with cross-ref to the new runbook. Open Backlog item count drops 3 → 2 (renumbered): #1 = 2nd Pilot-1 doctor pass (operator-blocked), #2 = A60 schema-and-doc alignment (operator-blocked, depends on 2nd-pass outcome).
- **`README.md`** — Documentation section adds link to `docs/pilot_2nd_pass_runbook.md`.

### Codex review trail

- **Round 1**: REJECT — 6 critical + 2 should-fix.
  * **CRITICAL #1**: helper malformed-input check fired only when BOTH sides parsed empty. If exactly one side was malformed (e.g., truncated capture), the helper silently reported every section as DROPPED/ADDED — actively misleading the operator. Fixed: either-side-empty → exit 2.
  * **CRITICAL #2**: helper detail collector only handled the standard 6-space `_indent_detail()` form, but the `content validation` block uses 4-space + 8-space directly (per `scripts/bsa_cli.py:929-931`). Result: file-count shifts (21/22 → 3/22) misclassified as PERSISTED instead of CHANGED. Fixed: collect any line indented ≥3 spaces (catches 4 / 6 / 8) + strip leading whitespace uniformly. New test `test_content_validation_count_change_classifies_as_CHANGED` pins the round-1 bug.
  * **CRITICAL #3**: runbook Class E grounded on the wrong AccessStatus enum — said `partial → {full, restricted, none, unverified}` but the live v1.1 contract is `readable_partial → [readable, unreadable, denied, expired, missing]`. The original misleading mapping table would have actively corrupted operator decisions. Fixed: rewrote per `governance/schemas/a50.schema.json` + `migrations/v1.0_to_v1.1/README.md` Class E (2-row decision: `readable` + informational A51 OR `unreadable` + hard-block A51).
  * **CRITICAL #4**: runbook Class G told operators to populate a `SupersedingClaimID` column that doesn't exist in v1.1 A60 (`governance/schemas/a60.schema.json`). Fixed: rewrote with the real 7-column set (`NegEvID, SourceID, ExcerptRef, RelatedClaimID, NegativeFinding, A51Ref, Notes`); supersession is recorded in A59.Notes per `reliability_tier_spec.md`, not A60.
  * **CRITICAL #5**: runbook Class H used invalid `ResolutionStatus=remediated` (real enum is `[open, resolved, resolved_by_remediation, superseded, wontfix]`) AND referenced non-existent `IssueDescription` / `ResolutionNote` columns (real A51 columns are `A51Ref, IssueType, Severity, BlockingStatus, RaisedByStage, RelatedSourceID, RelatedClaimID, NextAction, ResolutionStatus`). Fixed: rewrote per the real schema + per-value semantics from the schema description.
  * **CRITICAL #6**: runbook pointed at wrong migration log path (`$WORKSPACE/migration_log.jsonl`) — actual is `$WORKSPACE/runtime/migration_log_v1.0_to_v1.1.jsonl` per `scripts/migrate_v1.0_to_v1.1.py:962-973`. Fixed all 4 occurrences (3 in the main flow + 1 in the gotchas section the round-2 cleanup initially missed).
  * **SHOULD #1**: missing tests for the 2 critical fixes (one-side-malformed + content-validation block format). Added.
  * **SHOULD #2**: Step 5 wording was implicit about helper buckets. Rewrote to explicitly explain `OK`/`SKIP` vs `FAIL`/`ERROR` bucketing + the cross-product → 7-classification map.

### Result (round-2 final)

- 1527 → 1554 tests passing (+27 compare_doctor_outputs tests, including the 3 round-2 regression tests for one-side-malformed + content-validation block format).
- The 2nd-pass operator workflow is now fully documented + tooled, AND the runbook decision trees are pinned to actual v1.1 schemas (round-1 Codex caught real schema-vs-doc drift that would have actively misled the operator). An operator can take the runbook + the migration script + the diff helper and execute the 2nd pass end-to-end without needing maintainer-side handholding.
- Section K is **as-closed-as-it-can-be** without operator action. The remaining work (running the 2nd pass against a real Pilot-1 workspace + reporting back) is a single bullet on the open backlog.

## [v1.1.14] — 2026-04-23

**Phase 7 self-improvement loop foundation (Section D).** Sets up the contract for the v1.2.x self-improvement loop without committing to a backend before there's real pilot data to drive it. Three layers:
* **L0 (foundation)** — formal tunable inventory + IMMUTABLE_CONFLICT lint + safety contract. **This release.**
* **L1 (telemetry + miner)** — v1.2.x candidate.
* **L2 (auto-patcher)** — v1.3+ candidate.

**Tag target**: this commit (the v1.1.14 Phase 7 foundation release).
**Canon policy version**: `1.1.6+hash:ac63a8c3` — **unchanged**. Tunable inventory + lint live outside POLICY_GLOBS; canon hash unchanged. Manifest version stays at 1.1.6; v1.1.14 git tag marks the foundation release.

### Added

- **`docs/phase_7_design.md`** — formal design doc for the self-improvement loop:
  * Three-layer architecture (L0 foundation / L1 miner / L2 auto-patcher) + which layer ships when.
  * Tunable inventory schema (id, current_value, allowed_range, owner_skill, source_file, source_line, linked_invariants, change_class, rationale).
  * 8-check lint contract (C1 source-line drift / C2 invariant validity / C3 owner_skill validity / C4 unique IDs / C5 IMMUTABLE_CONFLICT / C6 L1+POLICY_GLOBS forbidden / C7 change_class validity / C8 allowed_range sanity).
  * IMMUTABLE_CONFLICT detection algorithm + safety contract (no invariant edits / range-bounded / provenance / reversible / canon-hash neutral by construction for L1 / pilot-data-driven only).
  * Open questions deferred to v1.2.x design (telemetry storage shape, statistical significance gate, multi-pilot aggregation, auto-patch cadence, operator opt-out).
- **`config/tunables.yaml`** — single source of truth for which knobs Phase 7 may tune. v1.1.14 ships 12 entries:
  * 5 tier weights (T1..T5) — all `L2_proposal_only` (linked to INV-01).
  * 3 KPI targets (KPI-001 weighted, KPI-001 legacy, KPI-006) — all `L2_proposal_only` (KPI-001 legacy + KPI-006 also linked to invariants).
  * 1 decay cap (decay_factor_cap = 0.80) — `L2_proposal_only` (linked to INV-01).
  * 2 BPMN sidecar layout thresholds (max_shape_shift, max_label_shift) — `L1_auto_tunable` (no governance interaction; layout-quality tunables only).
  * 1 perf-bench regression threshold (2.0) — `L2_proposal_only`.
- **`scripts/phase_7_lint.py`** — stdlib + pyyaml lint with 8 per-entry / per-file checks (C1..C8). Uses `ast` to parse `POLICY_GLOBS` from `scripts/compute_canon_hash.py` (round-1 fix: regex-based reader was fooled by `(` in inline comments). CLI flags: `--quiet` for clean PASS output. Exit codes: 0 PASS / 1 lint findings / 2 invocation error.
- **`tests/test_phase_7_lint.py`** (+27 tests) — pins:
  * Committed tunables.yaml lints clean (C1 drift detector — catches if any tunable's source value changes without updating tunables.yaml).
  * Design doc exists + carries required section headers (catches accidental rename).
  * Inventory exercises BOTH change_classes (catches collapse to all-L2 = vacuous L1).
  * Inventory has at least one `linked_invariants` entry (catches cross-reference loss).
  * Each check rule (C1..C8) triggers on its synthetic broken-example.
  * `_read_policy_globs()` returns non-empty + includes `governance/immutable_invariants.md` (catches refactor of canon-hash script).
  * `_parse_numeric()` handles `>=`, `≥`, bare numbers, and returns None for enums.

### Updated

- **`.github/workflows/ci.yml`** — added `phase-7-lint` job (8th parallel job alongside pytest matrix, fixture-runner, privacy-scan, security-audit, canon-hash, marker-chain, perf-bench).
- **`tests/test_ci_workflows.py`** — required-jobs set bumped 7 → 8.
- **`docs/faq.md`** — Phase 7 line in "Still deferred to Phase 5+ / future" calls out v1.1.14 foundation vs v1.2.x telemetry backend.
- **`README.md`** — Documentation section adds link to `docs/phase_7_design.md`.

**Note**: `governance/immutable_invariants.md` is intentionally NOT touched in v1.1.14. That file is in POLICY_GLOBS — editing it would bump the canon hash and break the v1.1.x manifest-version-stable discipline. The `docs/phase_7_design.md` design doc cross-references invariants.md (one-way link) so the relationship is still discoverable; a reverse cross-reference in invariants.md can land in the next canon-bumping release.

### Codex review trail

- **Round 1**: REJECT — 2 critical + 4 should-fix.
  * **CRITICAL #1**: `docs/phase_7_design.md` L2 row in the layers table said "auto-merge proposals that pass governance gate (analyst review optional below threshold)" — contradicted the rest of the doc, which defines L2 as ALWAYS requiring analyst sign-off. Fixed: L2 row now says "auto-emit proposals (PRs) for tunables that need analyst sign-off (always reviewed before merge — the 'auto' is the proposal generation, not the apply)".
  * **CRITICAL #2**: `_read_invariant_ids()` regexed every `INV-XX` mention in invariants.md, so a prose reference like "Historical note: INV-09 was removed" would let C2 silently accept stale `linked_invariants` even after the actual declaration was gone. Fixed: now parses only `### INV-XX:` h3 headers (the authoritative declaration shape). New test `test_read_invariant_ids_only_counts_declarations` synthesises a doc with prose mentions of INV-09/INV-99 + h3 declarations of INV-01/INV-02 and pins that only the headers count.
  * **SHOULD #1**: `config/tunables.yaml` header comment said "no source_file may match POLICY_GLOBS" — contradicted the lint, which only blocks L1+POLICY_GLOBS (most committed entries are valid L2-in-POLICY_GLOBS). Fixed: comment now matches the lint's L1-only contract.
  * **SHOULD #2**: tests claimed "tolerates both tuple + list literal" but only smoke-tested the live (tuple) file. Added `test_read_policy_globs_handles_list_literal` + `test_read_policy_globs_handles_tuple_literal` synthetic-fixture tests that pin both forms with embedded `(` `)` `]` chars in comments (the round-1 regex bug surface).
  * **SHOULD #3**: `docs/phase_7_design.md` + `config/tunables.yaml` advertised enum-style tunables (`OR enum_values: [...]`) but the lint only supports numeric `allowed_range`. Fixed: doc + comment now say "v1.1.14 only supports numeric ranges; enum-style tunables are deferred until a use case appears".
  * **SHOULD #4**: CHANGELOG said 11 entries; reality is 12 (5 tier weights + 3 KPI targets + 1 decay cap + 2 BPMN + 1 perf-bench). Fixed.


### Result

- 1497 → 1527 tests passing (+30 phase_7_lint tests +1 ci_workflows update; round-1 had 27, round-2 added 3).
- Phase 7 contract is now executable, not just documented in immutable_invariants.md.
- Drift detection at lint time means any maintainer who edits a tunable value (e.g., bumps T2 from 0.85 to 0.87) without updating `config/tunables.yaml` gets caught at CI, not at the moment Phase 7 actually fires.
- IMMUTABLE_CONFLICT enforcement is mechanical — `L1_auto_tunable` with non-empty `linked_invariants` is a hard error.
- L1+POLICY_GLOBS coupling enforcement is mechanical — `L1_auto_tunable` whose source_file is canonical state is a hard error (would silently bump canon hash without a release marker).

## [v1.1.13] — 2026-04-23

**Performance / scale validation (Section F).** Establishes a hot-path latency baseline + automated regression detection. The plugin family was already fast (full pytest suite in ~115s; canon hash in ~25ms; F5 dispatcher per-call in single-digit microseconds), but had no codified baseline — so an O(n) → O(n²) regression on the F5 hot path could ship unnoticed. v1.1.13 closes that gap with a stdlib-only bench harness + committed baseline doc + CI regression check.

**Tag target**: this commit (the v1.1.13 perf release).
**Canon policy version**: `1.1.6+hash:ac63a8c3` — **unchanged**. Bench harness + baseline doc live outside POLICY_GLOBS; canon hash unchanged. Manifest version stays at 1.1.6; v1.1.13 git tag marks the perf-validation release (matches the v1.1.7..v1.1.12 cadence).

### Added

- **`scripts/perf_bench.py`** — stdlib-only benchmark harness (mirrors the structure of `scripts/security_audit.py` + `scripts/privacy_scan.py`). Five categories:
  * **F5 dispatcher** (`_dispatch()` per-call regex scan over the dispatcher table; matching + non-matching paths). Hot path: fires on every canonical write.
  * **validate_canonical_write** (full F5 pipeline on a representative A59 CSV, ~10 rows from project_0001).
  * **canon hash** (`compute_canon_hash.py` end-to-end — POLICY_GLOBS scan + sha256).
  * **fixture_runner** (`fixture_runner.py --all --mode=validate` over 8 fixtures).
  * **CI scan budget** (combined `privacy_scan.py` + `security_audit.py`, ~436 files each).
  * Records p50 / p95 / p99 / min / max / mean across N iterations (per-category default; configurable). Discards a warm-up iteration. CLI flags: `--report=<path>` (overwrite baseline), `--check` (compare current vs baseline + fail if any p95 ≥ 2.0× baseline), `--quiet` / `--json` / `--category` / `--iterations`.
- **`docs/perf_baseline.md`** — committed baseline. Maintainer's laptop (Apple Silicon, macOS) numbers; the 2× regression threshold accommodates GitHub Actions Linux runners (typically 1.5–3× slower).
- **`tests/test_perf_bench.py`** (+22 tests) — pins:
  * `_percentile()` math on edge cases: single sample, q=0, q out of [0,1], NIST nearest-rank on N=100 samples 1..100 (p95 → 95.0, p99 → 99.0, p50 → 50.0), empty raises.
  * `BenchResult` properties (p50/p95/p99/min/max/mean) compute via `_percentile` on recorded samples (catches drift if someone refactors to `statistics.quantiles` linear-interpolation).
  * `format_table` / `format_baseline_doc` round-trip cleanly through `parse_baseline_doc` (catches markdown-format drift between writer + reader).
  * Fast benches (`bench_dispatcher`, `bench_validate_canonical_write`) end-to-end runnable.
  * `_time_callable_ms()` discards warm-up + rejects iterations < 2.
  * `check_against_baseline()` PASS / FAIL on regression / FAIL on renamed bench / FAIL on removed bench / missing-doc paths.
  * Committed baseline doc exists, parses, and contains a row for every category (catches the case where someone bumps the bench list but forgets to re-record).

### Updated

- **`.github/workflows/ci.yml`** — added `perf-bench` job (7th parallel job alongside pytest matrix, fixture-runner, privacy-scan, security-audit, canon-hash, marker-chain). Runs `scripts/perf_bench.py --check --quiet`. Total wall time on GitHub Actions: ~12s (~6s on dev hardware).
- **`tests/test_ci_workflows.py`** — `test_ci_yml_has_required_jobs` updated for the 7-job set (was 6).
- **`README.md`** — Documentation section adds link to `docs/perf_baseline.md`.

### Codex review trail

- **Round 1**: REJECT — 1 critical + 3 should-fix.
  * **CRITICAL**: `_percentile()` was off-by-one. The earlier impl used `int(round(q*N + 0.5)) - 1` and Python's banker's rounding (`round(95.5) → 96` for N=100, q=0.95) returned index 95 → sample 96 instead of the NIST nearest-rank correct index 94 → sample 95. The all-same-value test fixture masked the bug. Fixed: now uses `math.ceil(q*N) - 1` (NIST §1.3.5.6 exactly) + a dedicated test pinning the result on samples 1..100.
  * **SHOULD #1**: `--check` passed when a current bench was missing from the baseline (renamed / added without re-recording). CI could go green while a bench was silently no longer compared. Fixed: now hard-fails on either side (current-not-in-baseline OR baseline-not-in-current). Operators must explicitly re-record via `--report=docs/perf_baseline.md` after a list change.
  * **SHOULD #2**: `tests/test_ci_workflows.py::test_ci_yml_has_required_jobs` still expected 6 jobs, would not catch a future removal of the v1.1.13 perf-bench job. Fixed: bumped to 7 jobs.
  * **SHOULD #3**: bench label said `--all --validate` (5 places) but the actual CLI is `--all --mode=validate`. Fixed all 5: `scripts/perf_bench.py` (×3), `docs/perf_baseline.md`, `CHANGELOG.md` (×2).

### Result

- 1474 → 1497 tests passing (+22 perf-bench tests +1 ci_workflows update).
- Hot-path latencies are now committed as a baseline (not just measured ad-hoc).
- CI catches any p95 regression ≥ 2× baseline automatically (the threshold that catches algorithmic regressions like O(n) → O(n²) without flagging single-digit-percent noise).
- F5 dispatcher per-call latency: p95 < 5µs (matching path) / p95 < 2µs (non-matching). Sub-microsecond margin even on the busiest write path.
- `validate_canonical_write` (full F5 pipeline on A59 CSV): p95 < 1ms.
- `compute_canon_hash.py` end-to-end: p95 < 30ms.
- `fixture_runner.py --all --mode=validate`: p95 < 50ms.
- `privacy_scan + security_audit` (CI scan budget): p95 < 1s.

## [v1.1.12] — 2026-04-23

**Sidecar polish (Section I).** Both diagram sidecars (`c4-plantuml-from-context` + `camunda-bpmn-from-context`) had zero open TODO markers and were already well-tested individually. v1.1.12 codifies the F5-boundary contract that's been implicit since v1.0.0 and adds an operator-facing inventory doc.

**Tag target**: this commit (the v1.1.12 sidecar release).
**Canon policy version**: `1.1.6+hash:ac63a8c3` — **unchanged**. Sidecar inventory + boundary tests live outside POLICY_GLOBS; canon hash unchanged. Manifest version stays at 1.1.6; v1.1.12 git tag marks the sidecar polish release.

### Added

- **`docs/sidecar_inventory.md`** — operator-facing summary: at-a-glance comparison table (c4 vs bpmn), per-sidecar status block (skill location, what it does, operating modes, validators, optional deps), F5-boundary explainer (why sidecar paths under `analysis/views/` are explicitly outside the canonical single-writer set), operator-side usage examples for both standalone and orchestrated modes, and post-v1.1.x open follow-ups (common SidecarConfig schema, sidecar registry, end-to-end orchestrator-with-sidecar fixture, future DBML / sequence-diagram sidecars).
- **`tests/test_sidecar_f5_boundary.py`** (+21 tests) — pins:
  * F5 dispatcher MUST NOT match any sidecar output path (`analysis/views/c4/*.puml`, `analysis/views/c4/anchor_manifest.json`, `analysis/views/bpmn/*.bpmn`, `analysis/views/bpmn/anchor_manifest.json`, `analysis/views/bpmn/preview.svg`). A drift here would silently break the sidecars' writer-agnostic discipline (only `bsa-orchestrator` could emit, breaking standalone mode).
  * `validate_canonical_write` returns `(True, [])` (pass-through) for sidecar anchor-manifest paths — the canonical contract.
  * Both sidecars have `SKILL.md` + `references/integration-contract.md` + `references/anchor_manifest.schema.json` (catches accidental rename/move).
  * Both sidecars have `scripts/test_*.py` files AND those tests appear in the global pytest collection (defense-in-depth: a future pytest config change excluding sidecar dirs would lose ~80 sidecar tests).
  * `docs/sidecar_inventory.md` exists and references both sidecars + the F5-boundary section (catches doc drift if a future commit touches the inventory).

### Updated

- **`README.md`** — Documentation section adds link to `docs/sidecar_inventory.md`.

### Codex review trail

- **Round 1**: REJECT — 1 critical (subprocess-based pytest collection test was brittle: shelled to nested `pytest --collect-only`, never checked returncode, treated collection failure as "tests missing", false-failed on no-tmp-dir env) + 3 should-fix (inventory drift: validator description claimed anchor-manifest mapping enforcement that doesn't exist; counts said 12 test modules + 11 production scripts but reality is 14 + 12; "15 references" but reality is 21) + 1 doc-drift (faq.md said standalone sidecars "still expect" anchor_manifest.json, contradicting both integration contracts).
- **Round 2 fixes**: replaced subprocess test with importlib-based discovery check (now also handles `unittest.TestCase` subclasses — sidecar style with names like `BackendSelectorTests` is not `Test*` prefixed, which the first round-2 draft missed); corrected the 4 inventory drift items; rewrote faq.md "Can I use a sidecar standalone?" answer to clarify standalone mode does NOT require anchor_manifest.json.
- **Round 2 follow-up**: APPROVE with 1 non-blocking SHOULD — the importlib smoke test only spot-checked the FIRST `test_*.py` per sidecar, making the docstring overclaim what the test catches. Final v1.1.12 iterates over ALL test files (~30 modules total, <1s on import) so a single broken module is caught — not just a sidecar-wide regression.

### Updated (round-2 doc fixes)

- **`docs/faq.md`** — "Can I use a sidecar standalone?" answer corrected: standalone mode does NOT require `anchor_manifest.json`; the heuristic for which mode is intended (path under `analysis/...` ⇒ orchestrated) is now spelled out.
- **`docs/sidecar_inventory.md`** — corrected BPMN counts (14 test modules + 12 production scripts; 21 references); removed false claim that `validate_c4_plantuml.py` enforces anchor-manifest mapping (that's the orchestrator's promotion contract, per integration-contract.md).

### Result

- 1453 → 1474 tests passing (+21 sidecar boundary regressions).
- Sidecar contract is now executable (not just documented in individual SKILL.md files).
- Operator-facing summary lets a new operator understand sidecar capabilities + boundaries without reading the full SKILL.md + references for each.

## [v1.1.11] — 2026-04-23

**Security workstream (Section G).** First explicit security posture for the repo. Adds threat model + automated security audit + CI integration + SECURITY.md disclosure flow. Especially valuable post-v1.1.6 (live API client introduced real token handling), now with multiple defense-in-depth layers documented and pinned by tests.

**Tag target**: this commit (the v1.1.11 security release).
**Canon policy version**: `1.1.6+hash:ac63a8c3` — **unchanged**. Security tooling lives outside POLICY_GLOBS; canon hash unchanged. Manifest version stays at 1.1.6; v1.1.11 git tag marks the security release.

### Added

- **`SECURITY.md`** — root-level security disclosure policy (GitHub-standard convention). Covers: vulnerability reporting flow, supported versions, threat-model summary, automated audit description, pre-merge security gates, anonymization policy, cryptographic implementation notes, supply-chain notes.
- **`docs/threat_model.md`** — explicit attack-surface inventory + per-vector mitigations + open risks. Sections: scope, threat actors, 7 attack-surface domains (token handling, INV-02 single-writer, cross-artifact validator, migration script, hook scripts, schema-drift bypass, privacy/PII leakage), defense-in-depth pattern, out-of-scope threats, mitigation drift detection.
- **`scripts/security_audit.py`** (450 LOC, stdlib-only) — automated drift detection complementing `privacy_scan.py`. Five scan categories:
  1. **Token-shape detection** — JWT, GitHub PAT, Atlassian API token, Bearer/Basic credentials, AWS access keys, Slack bot tokens. Catches hardcoded creds in committed files (CRITICAL severity).
  2. **Insecure subprocess** — `subprocess shell=True`, `os.system`, `subprocess.call shell=True` without `# nosec` justification. (HIGH).
  3. **Dangerous Python builtins** — bare `eval()`, `exec()`, `compile()` without attribute access (`re.compile`, `ast.literal_eval` correctly NOT flagged via `(?<![A-Za-z_.])` lookbehind). (HIGH).
  4. **Path-traversal heuristic** — `Path()` constructions from operator input without normalization. (MEDIUM).
  5. **Scrub-required check** — verifies `scripts/backlog_live_apply.py` actually carries the `_scrub_secrets` call (defense-in-depth pin against accidental scrub removal). (HIGH).
  Self-introspection skip + `tests/` skip prevent the audit from self-reporting on its own pattern definitions and on test data that intentionally contains sample patterns. `# nosec: <reason>` comment within ±2 lines suppresses individual findings with justification.
- **`tests/test_security_audit.py`** (+22 tests) — coverage for: live-repo regression baseline (zero CRITICAL+HIGH), CLI exit codes, `--quiet` mode, every detection category (positive sample fires), false-positive suppression (`re.compile`, `ast.literal_eval`, `# nosec` comment, exemption files), self-introspection (audit doesn't fire on its own docstring), scrub-required files exist + carry the call.
- **`.github/workflows/ci.yml`** — new `security-audit` job runs `python3 scripts/security_audit.py` on every push (must produce 0 CRITICAL + 0 HIGH).

### Updated

- **`CONTRIBUTING.md`** — pre-commit checklist gains `python3 scripts/security_audit.py` (0 CRITICAL + 0 HIGH); validation tooling table adds the new script.
- **`tests/test_ci_workflows.py::test_ci_yml_has_required_jobs`** — expected job set extends from 5 to 6 (adds `security-audit`).

### Round-1 Codex review hardening (round-2 fixes)

Codex round-1 review (REJECT) raised 2 critical bugs + 2 should-fix. All addressed before final commit:

- **Critical (closed)** — `PATH_TRAVERSAL_PATTERNS` was defined but **never invoked** by `run_audit()`. SECURITY.md + `docs/threat_model.md` advertised path-traversal scanning as one of the audit categories, but the function wasn't wired in. v1.1.11 final adds `_scan_path_traversal()` + invocation from `run_audit()`. Also tightened the regex to actually match the typical sink shape `(Path(base) / user_input).write_text(...)` (the earlier regex would have missed it even if invoked). Added 3 new regression tests pinning detection + suppression.
- **Critical (closed)** — Same regex was too narrow. v1.1.11 final uses two patterns: `Path() / identifier → .write_text/.write_bytes/.open/.read_text/.read_bytes/.mkdir/.touch/.rename/.symlink_to/.hardlink_to`, plus a literal `..` heuristic for `open("../...")` paste artifacts.
- **Should (closed)** — Bearer/Basic credential detector required 30+ chars; runtime quarantine in `backlog_live_apply.py::_TOKEN_SHAPE_RE` and the schema's `not.anyOf` clauses fire at 20+. v1.1.11 final aligns the audit threshold to 20+ chars so CI doesn't have a stricter-then-runtime gap.
- **Should (closed)** — `--repo-root` was only partially honored. `_scan_scrub_required` used the global `REPO_ROOT` (script-checkout-anchored), so a `--repo-root <other>` invocation would silently inherit the current checkout's allowlist. v1.1.11 final factors out `_scrub_required_for(repo_root)` and rebases all paths on the runtime root. Added regression test pinning the isolation.

### Result

- 1427 → 1453 tests passing (+26 security audit regressions including 4 round-1 hardening regressions + 1 CI workflow job-set update).
- Public-distribution security posture in place: explicit threat model, automated drift detection (5 scan categories all wired in), contributor-facing security policy.
- Zero outstanding CRITICAL or HIGH findings against the live repo HEAD.

## [v1.1.10] — 2026-04-23

**Distribution / packaging polish (Section J).** Brings the repo to public-remote / external-contributor readiness. Closes the longstanding LICENSE-vs-manifest contradiction (manifest declared `MIT` while the LICENSE file said "All rights reserved" / "TBD"); adds the packaging metadata (`homepage` / `repository` / `bugs`) that downstream tooling expects; ships the issue + PR templates that activate when contributors land; codifies the release procedure that's been ad-hoc through 9 prior tagged releases.

**Tag target**: this commit (the v1.1.10 packaging release).
**Canon policy version**: `1.1.6+hash:ac63a8c3` — **unchanged**. Packaging metadata + LICENSE + templates + release docs all live outside POLICY_GLOBS. Manifest version stays at 1.1.6; v1.1.10 git tag marks the packaging release.

### Changed

- **`LICENSE`** — was a 5-line "All rights reserved / TBD pending public release decision" placeholder. Now a full **MIT License** (matching what the manifest already declared as `"license": "MIT"`). Resolves the longstanding contradiction. Also adds a third-party-content notes section documenting upstream-derived skill provenance + test-only library licenses.
- **`.claude-plugin/plugin.json`** — added `homepage`, `repository` (`{type: "git", url: ...}`), and `bugs` (`{url: ...}`) slots with placeholder `<owner>` URLs (operator fills in at first public push). Description now mentions GitHub Projects v2 + live-API mode (was stuck at v1.1.0 wording). Keywords expanded with `phase-3`, `dev-handoff`, `jira`, `linear`, `github-projects-v2`.

### Added

- **`.github/PULL_REQUEST_TEMPLATE.md`** — template activates when a contributor opens a PR. Includes the pre-merge checklist (pytest, fixture-runner, privacy-scan, canon-hash, CHANGELOG, invariant-touch rules, anonymization compliance, token-handling regressions), Codex review status block, change-type classification, and linked-context section.
- **`.github/ISSUE_TEMPLATE/bug_report.md`** — bug template with plugin-version block, workspace-state block, repro steps, expected/actual behavior, affected-artifacts checklist (A48..A72 + marker chain + handoff + backlog export), privacy/anonymization checkbox.
- **`.github/ISSUE_TEMPLATE/feature_request.md`** — feature template with scope-classification checkboxes (additive enum extension / new SKILL / new invariant / new artifact / new platform export / operator tool / docs), acceptance-criteria template, carry-forward / TODO-marker reference.
- **`docs/RELEASING.md`** — operator-facing release procedure. Codifies the two-semver pattern (manifest version vs git tag) with a worked-example table for v1.1.0..v1.1.9; pre-release checklist; release commit + tag template; post-release CI behavior (release.yml triggers); release-tarball verification; rollback procedure; future marketplace-publication notes.

### Updated

- **`tests/test_plugin_manifest.py`** — 2 new tests:
  - `test_manifest_license_matches_license_file` — catches the LICENSE-vs-manifest drift that v1.1.10 closes (LICENSE must contain `MIT License` + the canonical permission grant clause when manifest declares `MIT`; rejects the legacy `All rights reserved` placeholder).
  - `test_manifest_distribution_metadata_present` — enforces `homepage` / `repository` / `bugs` slots are present and `repository.url` ends in `.git` (catches drift where a future maintainer might delete a slot).

### Result

- 1425 → 1427 tests passing (+2 manifest distribution tests).
- LICENSE / manifest / packaging metadata all internally consistent.
- Public-remote-ready: contributor templates + release procedure + signed MIT LICENSE in place.

## [v1.1.9] — 2026-04-23

**CI/CD infrastructure (Section H).** First GitHub Actions workflows for the repo. Brings the operator's pre-commit checklist into automated CI gating so that when the repo lands on a public remote, every push + PR + tag has the same validation discipline that's been local-only through v1.1.8.

**Tag target**: this commit (the v1.1.9 CI/CD scaffolding).
**Canon policy version**: `1.1.6+hash:ac63a8c3` — **unchanged**. CI workflows live outside POLICY_GLOBS; canon hash unchanged. Manifest version stays at 1.1.6; v1.1.9 git tag marks the CI/CD release. Matches v1.0.x precedent.

### Added

- **`.github/workflows/ci.yml`** — main CI workflow. Triggers on push to `main`, pull_request targeting `main`, and manual dispatch. Five parallel jobs:
  - **`pytest`** — three-Python-version matrix (3.9 / 3.11 / 3.12) running the full 1412-test suite with `-q -ra`.
  - **`fixture-runner`** — `python3 scripts/fixture_runner.py --all --mode=validate` against all 8 golden fixtures.
  - **`privacy-scan`** — `python3 scripts/privacy_scan.py` (must produce 0 blockers).
  - **`canon-hash`** — verifies `.claude-plugin/plugin.json` `canonPolicyVersion.hash_full` matches the live `compute_canon_hash.py` output.
  - **`marker-chain`** — per-fixture `validate_marker_chain.py` over every `expected_markers/` directory.
  - Concurrency group cancels in-progress runs of the same workflow + ref pair (saves runner minutes during rapid-fire patch lines).
- **`.github/workflows/release.yml`** — tag-triggered release validation. Triggers ONLY on `vX.Y.Z` and `vX.Y.Z-*` tag pushes. Runs:
  - The pytest + privacy-scan + canon-hash gates from CI.
  - Verifies the tag has a matching CHANGELOG entry (`## [vX.Y.Z] — DATE`).
  - Verifies manifest `version` == `canonPolicyVersion.semver`.
  - Builds a release tarball (excluding `.git`/`.github`/`tests`/`requirements-dev.txt`/cache dirs) and uploads it as a 90-day-retention artifact (operator can attach to a GitHub Release page).
- **`.github/dependabot.yml`** — weekly dependency updates for `pip` (requirements-dev.txt) + `github-actions` (workflow `uses:` versions). Minor + patch updates grouped into a single PR per ecosystem; major updates open separately.
- **`tests/test_ci_workflows.py`** (+12 tests) — smoke tests verifying the YAML files parse correctly and carry the expected jobs / triggers / steps. Catches drift if a maintainer edits `.github/` files without re-checking. Lazy-imports `pyyaml` via `pytest.importorskip` so the suite still runs in environments without it.

### Updated

- **`requirements-dev.txt`** — adds `PyYAML>=6.0,<7` (test-only dependency for `tests/test_ci_workflows.py`).

### Round-1 Codex review hardening

- **Critical (closed)** — `.github/workflows/release.yml` tag filters used regex-looking syntax (`v[0-9]+.[0-9]+.[0-9]+`), but GitHub Actions tag filters are **glob**, not regex. As-written, NO real version tag would have matched, so the release workflow would have silently never fired. v1.1.9 final uses correct glob (`v[0-9]*.[0-9]*.[0-9]*` + `v[0-9]*.[0-9]*.[0-9]*-*`).
- **Should (closed)** — workflow smoke tests in `tests/test_ci_workflows.py` only checked for pattern-string presence, not whether real tags would actually match. v1.1.9 final uses `fnmatch` (the same engine GitHub Actions uses internally) to verify: real released tags (v1.0.0, v1.0.4, v1.1.0..v1.1.9) MUST match; pre-release tags (v1.1.0-rc1) MUST match; non-version tags (`phase-3-baseline`, `snapshot`, `main`) MUST NOT match. Also added `test_release_yml_action_versions_current` guarding against drift onto deprecated `actions/checkout@v3` / `actions/setup-python@v4` / `actions/upload-artifact@v3`.

### Result

- 1412 → 1425 tests passing (+13 CI workflow regression tests including 1 round-1 hardening regression).
- First automated CI surface for the repo. Ready for public remote / external contributor PRs.
- Solo-maintainer + AI-assist workflow preserved: CI is gating, not blocking — the operator still reviews + commits via the local `pytest` + `codex exec` flow.

## [v1.1.8] — 2026-04-23

**Documentation polish (Section E).** Refreshes operator-facing docs that had drifted significantly during the v1.1.x feature line. README, getting_started, FAQ, CONTRIBUTING, and INSTALL all updated to reflect the current release shape.

**Tag target**: this commit (the v1.1.8 docs polish).
**Canon policy version**: `1.1.6+hash:ac63a8c3` — **unchanged** from v1.1.6/v1.1.7. Documentation lives outside POLICY_GLOBS; canon hash unchanged. Manifest version stays at 1.1.6; v1.1.8 git tag marks the docs-polish release. Matches v1.0.x precedent.

### Changed

- **README.md** — refreshed Status section: v1.0.3 era description replaced with a per-release v1.1.0..v1.1.7 summary line; install snippet shows `bsa-full@1.1.6`; skill count + invariant count updated; new section on Phase-3 dev-handoff in the Architecture overview; repository-layout block updated; Documentation section adds links to `pilot_validation.md`, `migrations/v1.0_to_v1.1/README.md`, and the CHANGELOG.
- **docs/getting_started.md** — version pin `@1.0.0` → `@1.1.6`; "23 skills" → "28 skills"; new "Phase 3 dev-handoff" section showing the `/bsa-dev-handoff` composite command and the four backlog export shapes; new "Migrating an older workspace" section pointing at the v1.0.x → v1.1.x migration tool.
- **docs/faq.md** — "Is this ready for production use?" rewritten for v1.1.x reality (Phase-3 closed, v1.0.x → v1.1.x migration tool exists, Pilot-1 framing); old "What isn't in v1.0.0?" section split into "What's in v1.1.x" (closed: Phase-3, enum extensions, migration tool, cross-artifact validator, platform export polish, adversarial fixtures, live API, anonymization) + "Still deferred to Phase 5+ / future" (machine-readable Stage 6, plugin decomposition, packs, Phase-7 self-improvement, marketplace, multi-session concurrency, GDPR controls, strict-on-hard-A51 mode, operator-side import drivers).
- **CONTRIBUTING.md** — pre-commit checklist test count `992 → 1412`; "Validation tooling" table replaced with the actual current state (12 validators, all available — was an aspirational table from Sprint 0); new "Release discipline" section explaining the two-semver-dimension pattern (manifest version vs git tag) with v1.0.x and v1.1.x examples; new "Codex review discipline" section formalizing the multi-round review pattern; new "Privacy + anonymization" section documenting the `Pilot-N` alias convention.
- **INSTALL.md** — version pin `@1.0.0` → `@1.1.6` with explanation of the manifest-vs-tag divergence.

### Result

- All operator-touch docs now read as v1.1.x reality.
- Zero behavior change; zero canon-state change.
- 1412 tests still passing.

## [v1.1.7] — 2026-04-23

**Pilot anonymization across the active surface.** The first external pilot engagement was previously referenced by its client name throughout the plugin's active surface — schemas, scripts, docs, tests, hooks. Even though the plugin is positioned as a universal Business/Systems Analysis framework, the client-name leak created a vendor-lock-in feel ("why is a specific company mentioned in our universal contract?") and broke the public-distribution use case. v1.1.7 scrubs all active-surface references to use the universal alias **`Pilot-1`**.

**Tag target**: this commit (the v1.1.7 anonymization patch).
**Canon policy version**: `1.1.6+hash:ac63a8c3` — **unchanged** from v1.1.6. Anonymization is text-only and touches only files outside POLICY_GLOBS (CHANGELOG, migrations README, pilot_validation.md, schemas, scripts, tests, hooks). Manifest version stays at 1.1.6; v1.1.7 git tag marks the anonymization release. Matches the v1.0.x precedent where v1.0.0 → v1.0.4 all kept the manifest at 1.0.0 (and v1.1.5 kept it at 1.1.4).

### Changed (active surface — operator-visible)

- **CHANGELOG.md** v1.1.1 – v1.1.6 entries — all client-name mentions rewritten to `Pilot-1`.
- **`migrations/v1.0_to_v1.1/README.md`** — title + scenario language now uses `Pilot-1 drift bundle` / `Pilot-1 workspace`.
- **`docs/pilot_validation.md`** — section heading + body anonymized; new top-of-file note explaining the `Pilot-1` alias convention and pointing at retros for historical client-name reference.
- **`governance/schemas/a51.schema.json`** — `IssueType.description`, `Severity.description`, `RaisedByStage.description` all rewritten.
- **`governance/schemas/a59.schema.json`** — schema `description` + `ClaimType.description` + drift-class `_comment` rewritten.
- **`scripts/migrate_v1.0_to_v1.1.py`** — module docstring + drift-bundle naming rewritten.
- **`scripts/bsa_cli.py`**, **`scripts/validate_a51_reconciliation.py`** — comments rewritten.
- **`hooks/hooks.json`**, **`hooks/pre_write_canonical.sh`** — comments rewritten.
- **`tests/test_*`** — function names + comments + sample data identifiers (`<client>-OD-DISC-...` → `PILOT1-OD-DISC-...`, `<client>_marker` → `pilot1_marker`, etc.) — all rewritten while preserving test semantics.

### Preserved (development history — analogous to commit messages)

- **`docs/retros/sprint_*.md`** (sprints 5, 7, 8, 9, 5_v1_0_2, 5_v1_0_3, 5_v1_0_4) — historical sprint retrospectives retain the original client name as a development-history record. Documenting WHY the framework evolved as it did is part of the project ledger and was deliberately not rewritten. Future contributors who want to know "where did `inventory_gap` come from?" can read those retros to see the real-world drift case study.
- **`docs/phase_3_plan.md`** — historical planning document.
- **Git commit messages + tag annotations v1.0.x..v1.1.6** — immutable; not touched. The original engagement name persists in the commit log as a development-history artifact.

### Result

- **136 → 0** mentions of the original client name in the active surface.
- **~53 mentions** retained in `docs/retros/sprint_*.md` + `docs/phase_3_plan.md` (historical record).
- 1412 tests still passing; no behavior change; no canon-state change.

## [v1.1.6] — 2026-04-23

**Live API integration (Section C).** Closes `[TODO-S9-LIVE-API]`. The `bsa-backlog-bridge` skill produced static export files since v1.1.0; v1.1.6 adds `scripts/backlog_live_apply.py` which POSTs each exported row to the live platform API (Jira REST, Linear GraphQL, GitHub REST). All three platforms ship in one patch.

**Tag target**: this commit (the v1.1.6 live-API integration).
**Canon policy version**: `1.1.6+hash:ac63a8c3` — patch-line bump from 1.1.4 (semver moves with manifest; hash advanced from `bsa-backlog-bridge/SKILL.md` edit closing the TODO).

### Added

- **`scripts/backlog_live_apply.py`** (730+ LOC, stdlib-only Python 3.9+) — three-platform live API client with idempotency + retry + partial-failure handling.
  - **Idempotency**: per-row key `bsa-{StoryID}-{canon_hash_prefix}`. Re-runs against an unchanged export read the prior `live_api_response.json` and skip already-created rows. Changing the canonical state (canon hash moves) yields a new key — operator must reconcile via platform-side dedup if needed.
  - **Dry-run by default**: `--apply` to actually POST. Dry-run prints the response document to stdout without writing the live state file.
  - **Stdlib-only HTTP**: `urllib.request` (no `requests`/`httpx` dependency). All three platforms use the same `_http_post_json` core.
  - **Exponential backoff**: 1s → 2s → 4s → 8s → 16s on 429 (rate-limited) + 5xx (server error) + network errors. Capped at 5 attempts per row; per-row deadline 30s.
  - **Partial-failure tolerant**: continues processing remaining rows after an individual failure. Exit code 1 only if at least one row failed; exit 0 on full success / dry-run; exit 2 on invocation error.
  - **Token security**: env-var indirection only (`--jira-token-env=BSA_JIRA_TOKEN` etc.); tokens NEVER appear in CLI args. Authorization-header values scrubbed (`<REDACTED>`) in error messages before persistence. Per-attempt JSONL log (`live_api_log.jsonl`) records request URL + status code + attempt number — NO bodies, NO headers.
  - **Per-platform clients**:
    - Jira: `POST /rest/api/3/issue` with the bridge-emitted issue payload. Basic auth (email + API token, Atlassian Cloud convention).
    - Linear: `POST /graphql` with `mutation issueCreate` (Linear has no REST surface). Bearer-style auth header. Requires `--linear-team-id`.
    - GitHub: `POST /repos/{owner}/{repo}/issues`. Bearer auth. Issue-only — Project v2 board assignment is operator-side via `gh` CLI (still TODO-S9-03-IMPORT-DRIVER).
- **`governance/schemas/live_api_response.schema.json`** — F5-validated structured response file at `analysis/handoff/live_api_response.json`. Schema enforces: platform enum (jira/linear/github), idempotency_key shape (`^bsa-STORY-...-[a-f0-9]{8}$`), summary cardinality (total = created + skipped + failed), and the cross-field invariants `status='created' MUST carry platform_id` + `status='failed' MUST carry last_error`. Tokens NEVER persisted here — only platform_base_url + operator_run_id + per-row idempotency state.
- **F5 dispatcher entry** for `analysis/handoff/live_api_response.json` (new `_validate_live_api_response_json` function in `write_validator.py`).
- **`governance.schemas.loader.load_live_api_response`** helper.
- **`tests/test_backlog_live_apply.py`** (+43 tests after round-1 hardening) — schema-level F5 dispatch + cross-field invariants; script-behavior with mocked HTTP (all 3 platforms × success/retry/failure paths, GraphQL strict-success branches, idempotency hit, idempotency key format); subprocess end-to-end (dry-run, run-id, missing args); v1.1.6 round-1 hardening (concurrency lock, validate-before-write, strict-deadline, token-shape rejection in platform_id/platform_url/last_error, platform-filter on prior state, GraphQL soft-failure no-retry, missing-team-id fast-fail).

### Round-1 Codex review hardening (round-2 fixes)

Codex round-1 review (REJECT) raised 2 critical bugs + 4 should-fix items. All addressed before final commit:

- **Critical (closed)** — Cross-platform state collision. Single shared `live_api_response.json` would let a sequential Jira→Linear→GitHub run skip the later platforms via stale cross-platform idempotency hits. v1.1.6 final uses **per-platform filenames** (`live_api_response_{jira,linear,github}.json`); F5 dispatcher regex narrowed to `live_api_response_(?:jira|linear|github)\.json`; `_load_prior_state_validated` hard-filters by top-level `platform` field even if the file got renamed.
- **Critical (closed)** — Linear GraphQL "soft failure" treated as success. Any HTTP 200 was marked `created` regardless of the GraphQL `errors[]` array, `data.issueCreate.success=false`, or missing `issue.identifier`. v1.1.6 final adds `_is_linear_success()` strict check (no errors AND success=true AND non-empty identifier). Also added upfront `--linear-team-id` validation in `_build_linear_config` so missing team_id fails FAST instead of burning the retry budget.
- **Should (closed)** — Response file written without `validate_canonical_write` pre-check. The advertised F5 guarantee was post-hoc only. v1.1.6 final calls the validator BEFORE `write_text` and exits 2 on violations.
- **Should (closed)** — Schema didn't reject token-shaped strings in `platform_id` / `platform_url` / `last_error`. Defense-in-depth fix: each field gets a `not.anyOf` JSON-Schema clause rejecting JWT, GitHub PAT (`ghp_/gho_/ghu_/ghs_/ghr_` prefix), Atlassian API token (`ATATT3...`), and Bearer/Basic-prefixed credentials. Loader's `_load_prior_state_validated` also calls `_looks_token_shaped()` to quarantine any prior-state row that slipped past schema validation.
- **Should (closed)** — Per-row deadline non-strict. Backoff sleep + request time could overshoot; `attempts` counter incremented even when the deadline-break path hit. v1.1.6 final tracks `sent_attempts` separately from the loop counter; caps both per-request timeout and backoff sleep by `remaining_budget`; aborts cleanly when remaining < 1s without incrementing `sent_attempts`.
- **Should (closed)** — Concurrent runs race condition. Two `--apply` runs against the same workspace+platform could both POST. v1.1.6 final adds `_acquire_platform_lock()` using `fcntl.flock` (Unix) / existence-check (Windows fallback) on a per-platform `live_api_response_{platform}.lock` file. Second concurrent run exits 2 with a clear "lock held" message.

### Updated

- **`skills/bsa-backlog-bridge/SKILL.md` Open follow-ups** — `[TODO-S9-LIVE-API]` struck through with closure note; documents the operator runbook (env-var indirection, idempotency convention, per-row deadline + backoff caps, partial-failure semantics).

### Carried forward (deferred to v1.2 / Section D-K)

- Operator-side import drivers (`scripts/jira_import_from_export.sh`, `scripts/linear_import_from_export.sh`, `scripts/github_import_from_export.sh`) — for operators who prefer shell over Python (or cannot install Python in their CI). v1.2 candidate (Section H/J).
- GitHub Project v2 board assignment automation (`gh project item-create` + `gh project item-edit` orchestration) — still TODO-S9-03-IMPORT-DRIVER. The live-apply script handles GitHub Issues only; Project v2 columns are set post-import by the operator's gh script.
- Live-API dry-run preview as a separate `--preview` flag (currently the dry-run print is the response document JSON, which is verbose). Cosmetic.

## [v1.1.5] — 2026-04-23

**Adversarial fixtures (B3).** Closes the three v1.2-candidate adversarial-fixture TODOs from the v1.1.0 carried-forward list — block-on-contradiction failure mode, multi-way contradictions, and tier-delta auto-resolution case. All three ship as fixture-data + integration tests; the block-on-contradiction fixture is **spec-only** (documents an unimplemented opt-in failure mode the v1.2 implementation will use as its regression baseline).

**Tag target**: this commit (the v1.1.5 adversarial-fixture batch).
**Canon policy version**: `1.1.4+hash:eefb7204` — **unchanged** from v1.1.4 (fixtures are not in POLICY_GLOBS; v1.1.5 is regression-baseline-only). Manifest version stays at 1.1.4 (matching v1.0.x patch-line precedent where v1.0.0 → v1.0.4 all kept manifest at 1.0.0; the v1.1.5 git tag marks the operator-facing fixture release, not a canon-state change).

### Added

- **`fixtures/golden/adversarial_multi_way_contradiction_001/`** — 3-source same-tier contradiction (P0 incident response: ops runbook 15min vs SRE handbook 5min vs customer SLA contract 60sec). Pins the contract that N-way contradictions are captured as ONE atomic A51 row (semicolon-joined `RelatedSourceID`/`RelatedClaimID`), NOT as N(N-1)/2 pairwise rows. Severity=critical because customer-contract is in the contradicted set. Full canonical state (A50/A58/A59/A60 with N×(N-1)=6 cross-link rows/A51) + `stage1.excerpts.merged` marker.
- **`fixtures/golden/adversarial_tier_delta_auto_resolution_001/`** — cross-tier (T1 vs T4 = delta 3) auto-resolution. T1 signed engineering spec (200ms target) wins over T4 marketing blog (under 1 sec). Pins the contract: higher-tier wins silently, lower-tier marked superseded via A59.Notes (`SupersededBy=C-001`), audit trail in A60, **NO A51 raised** (auto-resolution is the contract per `reliability_tier_spec.md` §By tier delta). Empty A51 register (header-only) explicitly tested.
- **`fixtures/golden/adversarial_block_on_contradiction_001/`** — spec-as-fixture for the proposed `--strict-on-hard-a51` opt-in failure mode (NOT implemented in v1.1.5 — v1.2 candidate). Documents the BLOCKED message shape so when the implementation lands, this fixture is the regression baseline. `fixture_metadata.json.spec_only = true` flags the fixture as documenting an unimplemented contract.
- **`tests/test_adversarial_b3_fixtures.py`** (+30 tests across 3 test classes) — covers the headline behavior unique to each fixture (atomic vs pairwise A51 cardinality; auto-resolution audit trail + no-A51 invariant; spec-only flag + mocked strict-mode pre-flight) plus cross-fixture invariants (required artifacts, A59/A51 schema validation, fixture_runner-required metadata fields).

### Carried forward (deferred to v1.2 / Section C)

- `--strict-on-hard-a51` opt-in failure mode in `/bsa-promote` orchestrator step + hook integration. Fixture `adversarial_block_on_contradiction_001` is the regression baseline waiting on this implementation.
- `SupersededBy` typed column in A59 schema (today encoded in Notes free-text). v1.2 candidate.
- Operator override of tier-delta auto-resolution via explicit A51 cross_tier_contradiction route. Documented in fixture README; no schema change needed.

## [v1.1.4] — 2026-04-23

**Platform export polish (B2).** Closes the three remaining v1.2-candidate TODOs from the v1.1.0 carried-forward list — `[TODO-S9-01-JIRA-CUSTOMFIELDS]`, `[TODO-S9-02-LINEAR-PROJECTS]`, `[TODO-S9-03-GITHUB-PROJECTS]` — by extending the existing Jira + Linear export schemas and adding a brand-new GitHub Projects v2 export schema. All three additions are backward-compatible (new fields/columns are optional or default to empty so pre-v1.1.4 exports still validate after operators add the new columns).

**Tag target**: this commit (the v1.1.4 platform-export polish).
**Canon policy version**: `1.1.4+hash:eefb7204` — patch-line bump from 1.1.3 (additive schema extensions; canon hash advanced from `bsa-backlog-bridge/SKILL.md` edits marking the three TODOs CLOSED).

### Added

- **Jira `customfield_mapping`** (`governance/schemas/backlog_export_jira.schema.json`) — OPTIONAL top-level object documenting four recognized BSA logical fields → Jira customfield IDs (`nfr_ids`, `source_claim_ids`, `story_id`, `a51_refs`). When present, the bridge populates the named customfields in each `issue.fields` with the corresponding `bsa_provenance` value (joined with `;` for arrays). When omitted, pre-v1.1.4 description-footer-only behavior preserved. `additionalProperties:false` on the mapping object catches typos at hook time (`nfr_id` vs `nfr_ids` rejected immediately). Customfield IDs validated against the canonical `^customfield_NNNNN$` shape (4-6 digits) so ad-hoc IDs (`cf_42`, `customfield_X`) fail.
- **Linear `Project` + `Cycle` columns** (`governance/schemas/backlog_export_linear.schema.json`) — TWO new required CSV columns (empty-string default preserves pre-v1.1.4 behavior of "team's default project, no cycle"). Project name pattern accepts Linear's character set (`[A-Za-z0-9 _-]{0,80}`); Cycle uses the same shape. Operators populate via `--linear-project` / `--linear-cycle` at bridge invocation OR per-story via A70 metadata.
- **GitHub Projects v2 export** (`governance/schemas/backlog_export_github.schema.json`) — brand-new CSV schema for `analysis/handoff/backlog_export_github.csv`. CSV-based because GitHub Projects v2 has no native bulk import; an operator-side `gh` script (or GitHub Actions workflow) consumes the rows to call `gh issue create` + `gh project item-create` + `gh project item-edit`. Columns: Title, Body, Status (Backlog/Todo/In Progress/Done), Priority (P0-P3), Size (XS-XL or empty), Labels (same regex as Linear: bsa-export + level-N + invest-N membership enforced via 3 positive + 3 negative lookaheads), StoryID, SourceClaimIDs, RelatedNFRIDs. F5 dispatcher entry registered at `/analysis/handoff/backlog_export_github.csv`. Loader gains `iter_backlog_export_github_rows`. Reuses the existing `_apply_provenance_rules` handler (INV-08 carries through identically to Linear/generic exports).
- **`tests/test_schemas_backlog_export.py`** (+17 tests, total 63) — covers Jira `customfield_mapping` (optional → pass; valid keys → pass; unknown key → block; bad ID format → block), Linear Project/Cycle (overlong name → block; bad chars → block; project + cycle populated → pass), and GitHub export end-to-end (baseline → pass; dispatcher routing; P0 round-trip; invalid Priority/Size → block; empty Size → pass; missing invest label → block; two-invest labels → block; provenance rule → block when both empty; loader iter function present; dispatcher path registered).

### Updated

- **`skills/bsa-backlog-bridge/SKILL.md` Outputs + Open follow-ups** — three TODO closure notes (struck through with closure detail); Outputs section adds `backlog_export_github.csv` next to existing three platforms; Jira + Linear entries note their v1.1.4 capability additions.

### Carried forward (deferred to v1.3 / Section C)

- `[TODO-S9-LIVE-API]` — optional live-API mode (POST to Jira / Linear / GitHub directly instead of static file output). Higher risk surface (auth, rate limits, partial failures); v1.3 candidate.

## [v1.1.3] — 2026-04-23

**Cross-artifact validator at the F5 hook layer (B1).** Closes the two declared v1.2-candidate TODOs from the v1.1.0 carried-forward list — `[TODO-S8-01-X-ARTIFACT-NFR-COVERAGE]` (A71 NFR-coverage rule) + `[TODO-S8-02-X-ARTIFACT-FK]` (A72 foreign-key + claim-source consistency). Both rules were documentary at the schema layer + skill-self-validated through v1.1.2; v1.1.3 makes them executable at the F5 hook layer so any writer (orchestrator, skill, operator manual edit) is gated.

**Tag target**: this commit (the v1.1.3 cross-artifact validator).
**Canon policy version**: `1.1.3+hash:78bac137` — patch-line bump from 1.1.1 (semver matches manifest version; hash advanced from SKILL.md edits in `bsa-test-scenario-builder` + `bsa-traceability-matrix` marking the TODOs CLOSED).

### Added

- **`_SiblingArtifactCache`** in `governance/schemas/write_validator.py` — per-validation-run memoized loader for sibling canonical artifacts. Keyed by `(filename, key_column)` so an A72 with N rows produces exactly one A50/A59/A70 read each, not N reads. Returns `None` for missing/unreadable siblings (handlers emit a clear violation, not a silent skip).
- **`_apply_foreign_key_rules`** — per-row handler for the `x-bsa-foreign-key-rules` schema extension. Applied to A72 today; the C2 pattern (read extension, apply per-row, emit line-numbered message) means any future schema declaring the same extension shape gets enforcement for free. Validates StoryID/ClaimID/SourceID resolution into A70/A59/A50 + the `claim_source_consistency` invariant (this row's ClaimID's A59 SourceID must equal this row's SourceID).
- **`_apply_nfr_coverage_rules`** — per-row handler for the `x-bsa-nfr-coverage-rules` schema extension. Applied to A71 today. Validates literal Target embed in Then-clause (mechanical, deterministic) + at least one significant Metric word in Then-clause (relaxed: stripped of stopwords; paraphrase OK per schema rationale). The relaxed Metric check is anti-aspiration ("agent gets paged" instead of an actual measurement), not anti-paraphrase.
- **`_resolve_sibling_dir`** — extracts the `analysis/canonical/core_controls/` parent dir from a write path. Returns `None` for paths outside the canonical layout AND for paths where the dir doesn't exist on disk (the latter keeps existing unit tests green; production hooks always have a real canonical dir).
- **`tests/test_cross_artifact_validator.py`** (+22 tests, including 5 added in round-2 hardening) — covers positive case, every FK violation kind (StoryID / ClaimID / SourceID unresolved + claim-source consistency mismatch + a51-routed row still subject to FK), every NFR-coverage violation kind (missing literal Target + no Metric reference + unresolved RelatedNFRID + blank RelatedNFRID exempt), sibling-cache memoization, missing-sibling-file diagnostics, graceful no-op when the path is outside the canonical layout, AND the four round-2 hardening regressions (`BSA_WORKSPACE_CWD` env-anchor, env-precedence over process CWD, blank A59.SourceID hard-fail, multi-source A59 membership check, word-boundary Metric match preventing `rate`-in-`iterate` false positives).

### Round-1 Codex review hardening (round-2 fixes)

Codex round-1 review (REJECT) raised 2 critical bugs + 1 should-fix. All addressed before final commit:

- **Must (closed)** — `_resolve_sibling_dir` made cross-artifact enforcement depend on the validator process CWD, but `pre_write_canonical.sh` invokes the validator from `PLUGIN_REPO`, NOT the user's workspace. Result: relative `file_path` writes silently no-op'd cross-artifact rules in production. Round-2 fix: hook script now exports `BSA_WORKSPACE_CWD="$(pwd)"` (the original user-shell CWD) before invoking the validator; `_resolve_sibling_dir` anchors relative paths there. Two regression tests pin the env-anchor (`test_workspace_cwd_env_anchors_relative_path` + `test_workspace_cwd_env_overrides_process_cwd`).
- **Must (closed)** — `claim_source_consistency` assumed `A59.SourceID` is a single non-empty scalar, but A59 explicitly allows blank (A51-routed claim) and multi-source (joined by `;`/`/`). Result: source-less claims silently passed; legitimate split-by-source matrix rows were falsely rejected. Round-2 fix: parse `A59.SourceID` on `;`/`/`/whitespace; blank → hard-fail when matrix promises a SourceID; multi-source → membership check (matrix row picks ONE of the claim's sources). Two regression tests pin the new semantics.
- **Should (closed)** — Metric word matching used raw substring search, so trivial overlaps (`rate` in `iterate`, `page` in `paged`) silently false-passed. Round-2 fix: switched to word-boundary regex (`\b<word>\b`); one regression test (`test_metric_match_uses_word_boundaries_not_substring`) pins the fix with the `rate`-vs-`iterate` adversarial case.

### Updated

- **`governance/schemas/a71.schema.json` `x-bsa-nfr-coverage-rules._comment`** — replaced "DOCUMENTARY at the F5/schema layer today" with "EXECUTABLE at the F5 hook layer as of v1.1.3"; documents the relaxed Metric match + the implementation pointer.
- **`governance/schemas/a72.schema.json` `x-bsa-foreign-key-rules._comment`** — same alignment; documents the implementation vehicle.
- **`skills/bsa-test-scenario-builder/SKILL.md` Invariants + Open follow-ups** — NFR-coverage rule now marked executable; `[TODO-S8-01-X-ARTIFACT-NFR-COVERAGE]` struck through with closure note.
- **`skills/bsa-traceability-matrix/SKILL.md` Invariants + Open follow-ups** — foreign-key + claim-source-consistency rules marked executable; `[TODO-S8-02-X-ARTIFACT-FK]` struck through with closure note.

### Carried forward (deferred to v1.2)

- `[TODO-S8-01-RUNNABLE-EXPORT]` — runnable test export (Cucumber `.feature`, pytest-bdd, Jest).
- `[TODO-S8-01-NEGATIVE-PATH-HEURISTICS]` — auto-suggest boundary / negative scenarios from temporal / boundary / comparison language in acceptance criteria.
- `[TODO-S8-02-INCREMENTAL-MATRIX]` — incremental A72 rebuild instead of full re-run on every `bsa-dev-handoff`.
- `[TODO-S8-02-LINK-STRENGTH-OVERRIDE]` — operator override of LinkStrength via designated A51 IssueType.
- Platform export polish (`[TODO-S9-01-JIRA-CUSTOMFIELDS]` / `[TODO-S9-02-LINEAR-PROJECTS]` / `[TODO-S9-03-GITHUB-PROJECTS]`) — Section B2.
- Adversarial fixtures (block-on-contradiction failure mode + multi-way contradictions + tier-delta auto-resolution case) — Section B3.

## [v1.1.2] — 2026-04-23

**Pilot-1 mechanical migration script.** Implements `scripts/migrate_v1.0_to_v1.1.py` per the spec authored in v1.1.1. Operators can now mechanically apply four classes of v1.0.x → v1.1.x drift fixes (marker payload field renames + A50 Priority/ReliabilityTier/SourceID-prefix cleanup) AND surface four classes of manual-review findings (verdict caveats / A50 AccessStatus partial / A60 header mismatch / A51 reconciliation) via `--report` flags.

**Tag target**: this commit (the v1.1.2 migration script implementation).
**Canon policy version**: `1.1.1+hash:a5b51af8` — **unchanged** from v1.1.1 (operator-tooling addition only; canon hash is unchanged because `scripts/` is not in POLICY_GLOBS, matching the v1.0.x patch-line precedent where v1.0.0 → v1.0.4 all kept the manifest at `1.0.0`). The v1.1.2 git tag marks the operator-tooling release; the policy state is identical to v1.1.1.

### Added

- **`scripts/migrate_v1.0_to_v1.1.py`** (350+ LOC, stdlib-only, Python 3.9+) — the mechanical migration tool spec'd in v1.1.1's `migrations/v1.0_to_v1.1/README.md`. Mirrors the structural template of `scripts/migrate_v0.9_to_v1.0.py`:
  - **Mechanical fixes** (apply with `--apply`):
    - `--markers-only` — marker payload field renames (`marker`→`marker_id`, `emittedAt`→`timestamp`, `canonPolicyVersion`→`canon_policy_version`); injects `<MIGRATION_TODO_VERDICT verdict_hint=<inferred>>` when verdict is missing so the operator sees it on next `bsa doctor`.
    - `--a50-priority` — strips Jira-style `P\d_` prefix from A50 Priority column (`P1_high`→`high`, `P2_medium`→`medium`, `P3_low`→`low`); inserts `<MIGRATION_TODO_PRIORITY_CRITICAL>` for legacy `P0_critical` (A50 Priority enum has no `critical` value — operator must escalate via A51).
    - `--a50-reliability-tier` — strips free-text suffix from A50 ReliabilityTier (`T2_primary_notes`→`T2`); appends descriptor to Notes column (creates Notes column if missing).
    - `--a50-source-id-prefix` — prepends canonical `S-` prefix to A50 SourceID matching `^[A-Z]{2,5}-\d{3,4}$`; rewrites every cross-reference in A58/A59/A60 SourceID columns to keep foreign keys consistent.
    - `--all-mechanical` — runs all four mechanical fixes in one invocation.
  - **Report-only checks** (always read-only):
    - `--report verdict-caveats` — lists every marker with verdict NOT in the closed enum (e.g., `PASS (with caveats)`).
    - `--report a50-access-status-partial` — lists every A50 row with AccessStatus NOT in the closed enum (e.g., `readable_partial`, `unreadable_binary`).
    - `--report a60-header-mismatch` — prints A60 header alongside the canonical header when columns differ.
    - `--report a51-reconciliation` — finds every A51 row with `ResolutionStatus=open` that a marker payload declares resolved/remediated (within ±80 char window of the A51Ref).
    - `--report all-reports` — aliases all four reports.
  - **Properties**: idempotent, non-destructive (`.pre-v1.1.bak` backups before every write), scoped to `analysis/`, JSONL log under `<workspace>/runtime/migration_log_v1.0_to_v1.1.jsonl`, dry-run by default.
  - **Smoke-tested against the Pilot-1 workspace** (`/private/tmp/pilot1-workspace-v1.0.x`): correctly classifies all 8 drift classes from the v1.0.x doctor output into mechanical-or-manual buckets, and matches the doctor's A51 reconciliation finding count (3 findings, not just 1) by delegating to the upstream auditor instead of duplicating it.
- **`tests/test_migrate_v1_0_to_v1_1.py`** (+29 tests) — covers preflight, all 4 mechanical fixes (dry-run + apply + idempotent), all 4 report kinds, JSONL log schema, the combined `--all-mechanical` + `--report all-reports` paths, headerless-CSV detection, write-error logging, parent-workspace mode, report-only immutability, and A51 synonym parity (fixed/completed/done).

### Codex review discipline

- **Round-1 review (REJECT)** raised 2 release-blocking issues + 2 should-fix issues, all addressed before commit:
  - **Must (closed)** — `report_a51_reconciliation` had hand-rolled scanning (only 5 resolution keywords, 80-char window, ignored H1-H4 handoff packets, didn't expand `A51-MISS-010/011` shorthand). v1.1.2 final delegates to `scripts/validate_a51_reconciliation.audit_workspace()` for full parity with `bsa doctor`. Verified by re-smoke on Pilot-1 workspace (1 → 3 findings; matches doctor).
  - **Must (closed)** — `report_a60_header_mismatch` hardcoded a stale 5-column canonical (real schema is 7: `NegEvID, SourceID, ExcerptRef, RelatedClaimID, NegativeFinding, A51Ref, Notes`). v1.1.2 final loads the canonical column set from `governance/schemas/a60.schema.json` at module-import time + uses exact-set semantics (missing OR extra columns both flagged). Stale test asserting 5-col file as canonical was rewritten.
  - **Should (closed)** — headerless CSV inputs were silently downgraded to "no column" skips (`csv.DictReader` promotes the first data row to a header). v1.1.2 final adds `_csv_read_validated()` that raises `HeaderValidationError` when none of the expected marker columns are present; surfaces as a real error record.
  - **Should (closed)** — SourceID-prefix phase-3 writes logged `applied` before the actual write succeeded. v1.1.2 final emits `planned` in phase 1+2 and `applied` (or `error`) per file after each phase-3 write.

### Updated

- **`migrations/v1.0_to_v1.1/README.md`** — marks the migration tool as IMPLEMENTED (was: spec'd, implementation pending). Recommended migration order section gains the actual command-line invocations.
- **`docs/pilot_validation.md`** —  Pilot-1 "Open backlog" item #1 (script implementation) marked DONE; backlog now leads with the operator runbook + second-round doctor pass.

### Carried forward (deferred to v1.2)

- Operator runbook for the manual-review steps (decision trees for verdict caveats, A50 AccessStatus partial, A60 column-set mapping, A51 reconciliation).
- Second-round  Pilot-1 doctor pass after operator applies the migration end-to-end.
- A60 schema-and-doc alignment (confirm the Pilot-1 A60 column drift is genuine misuse vs draft-schema artifact).

## [v1.1.1] — 2026-04-23

**Pilot-1 enum-extension patch + internal contract alignment.** Closes the schema-extendable subset of Pilot-1 drift via three additive A51 enum extensions, plus aligns existing internal documentation with the closed schema enums (no behavior change; doc drift had accumulated since v1.0.0).

**Tag target**: this commit (the v1.1.1 enum-extension patch).
**Canon policy version**: `1.1.1+hash:a5b51af8` — patch-line bump from 1.1.0 (additive enum extensions are backward-compatible). Hash advanced from edits to A51 schema, h1/h4 specs, shared-control-surface-contracts, reliability_tier_spec, discovery_to_main_merge.

### Added

- **A51 IssueType enum extension** — `inventory_gap` (Pilot-1, distinguishes a missing CATEGORY/SET of expected artifacts from a single `missing_source`) + `cross_tier_contradiction` (internal alignment — promotes the orchestrator-emitted variant for the reliability-tier-delta ≤ 1 contested rule from a doc-only convention to a first-class enum value matching `test_tier_conflict_scenarios` coverage). IssueType enum is now 7 values (was 5 in v1.1.0).
- **A51 Severity enum extension** — `critical` (Pilot-1, exceeds `high` for contract-binding SLA breach risk + customer-facing/regulatory issues). Severity enum is now 4 values (was 3 in v1.1.0).
- **`migrations/v1.0_to_v1.1/README.md`** — drift catalogue + per-class migration backlog for v1.0.x pilot workspaces (Pilot-1 baseline). Eight drift classes (marker payload schema, verdict enum, A50 Priority/ReliabilityTier/AccessStatus/SourceID format, A60 column set, A51 reconciliation) with `additive` / `mechanical` / `manual` verdicts each.
- **`docs/pilot_validation.md`** — Pilot-1 status + framework-level pilot-validation invariants. Pilot template for future engagements.

### Aligned (internal contract drift closed in this patch)

- **`shared-control-surface-contracts.md` A51 Minimal Columns** — published the new closed sets (IssueType + Severity).
- **`h1_spec.md` § Risks & Blockers** — Severity enum aligned to A51 actual enum (`critical → high → medium → low`); pre-v1.1.1 `blocker` synonym is now an explicit alignment note.
- **`h4_spec.md` § Open Items Digest + § Decisions Required + § Target Resolution Windows** — IssueType enum now publishes 7-value set; Severity grouping aligned to `critical → high → medium → low`; SLA fallback uses `critical = 2 business days` instead of legacy `blocker`.
- **`reliability_tier_spec.md` § Conflict Resolution** — tier-delta ≤ 1 row gains explicit `Severity=high` (was missing) alongside the existing `BlockingStatus=hard`.
- **`discovery_to_main_merge.md` § Excerpt dedup + § Conflict detection** — replaced legacy `Severity=hard` (typo of BlockingStatus into Severity) with `Severity=critical` + explicit `BlockingStatus=hard` on both A51 routing rules.
- **`docs/architecture_overview.md` INV-05 + `docs/workflow.md` INV-05** — INV-05 row now lists all 7 IssueType values.
- **`tests/test_schemas_a51.py`** — added 3 parametric cases covering `inventory_gap`, `Severity=critical`, and `cross_tier_contradiction` (negative tests preserved).

### Carried forward (deferred to v1.1.2 or v1.2)

-  Pilot-1 mechanical migration script (`scripts/migrate_v1.0_to_v1.1.py`) — spec'd in `migrations/v1.0_to_v1.1/README.md`, implementation pending. Operators currently apply the per-row mapping rules manually + use `bsa doctor` as a checklist.
-  Pilot-1 manual-review steps (verdict caveats, A50 AccessStatus partial, A60 column-set mapping, A51 reconciliation) — operator runbook pending.
- Second-round  Pilot-1 doctor pass after migration script lands.

## [v1.1.0] — 2026-04-22

**Phase-3 release** — closes the Phase-3 dev-handoff workstream (Sprints 6-9). All 5 Phase-3 skills are now real implementations: `bsa-nfr-collector` (Sprint 6), `bsa-story-writer` (Sprint 7), `bsa-test-scenario-builder` (Sprint 8 US-S8-01), `bsa-traceability-matrix` (Sprint 8 US-S8-02), `bsa-backlog-bridge` (Sprint 9 US-S9-01..03). 4 new canonical artifacts (A62 NFR register, A70 story register, A71 test scenario register, A72 traceability matrix). 3 new platform-specific export shapes (Jira REST v3 JSON, Linear CSV, generic CSV) under `analysis/handoff/` — first F5 dispatch on `analysis/handoff/` paths. 3 new immutable invariants (INV-08 story-claim provenance, INV-09 NFR measurability, INV-10 test-scenario provenance) codified in `governance/immutable_invariants.md`. Two committed Phase-3 regression baselines: happy-path (project_0001 fixture extension) + adversarial (claim-contradiction → A51 propagation chain).

**Tag target**: commit at the end of US-S9-05 (the bookkeeping commit that codifies INV-08/09/10 + bumps manifest to 1.1.0).
**Canon policy version**: `1.1.0+hash:d449ae74` — semver bump from 1.0.x (Phase-3 feature release per the v1.0.x patch-line convention); hash advanced from the immutable_invariants.md edit landing INV-08/09/10.
**Manifest description** updated: 28 skills (was 23) + Phase-3 dev-handoff explicitly mentioned.

### Added

- **`bsa-test-scenario-builder` real implementation** (Sprint 8 US-S8-01, commit `e533475`) — A71 test scenario register schema (12 columns; INV-10 SourceStoryID required + singular pattern; LinkType-style `x-bsa-deferral-rules` extension generalized to configurable `status_field`); F5 dispatcher entry; `_apply_deferral_rules` cross-field handler; `phase3.test_scenario.pass` marker + H-sec-4 patterned-match `^phase3\.([a-z_]+)\.pass$` (incidentally closed the same-class binding gap for `phase3.nfr.pass` + `phase3.story.pass` from Sprints 6-7); real SKILL.md spec replacing the v1.0.x scaffold.

- **`bsa-traceability-matrix` real implementation** (Sprint 8 US-S8-02, commit `87007a0`) — A72 traceability matrix schema (8 columns; all ID fields singular; LinkType enum narrowed to direct/nfr-mediated/a51-routed; reuses `_apply_deferral_rules` with `status_field='LinkType'` override); `x-bsa-foreign-key-rules` documentary extension with `applies_to_all_rows: true`; `phase3.traceability.pass` marker (auto-bound via the US-S8-01 patterned-match); real SKILL.md spec replacing the v1.0.x scaffold.

- **Project_0001 happy-path Phase-3 extension** (Sprint 8 US-S8-03, commit `2eeafed`) — extended the canonical regression fixture with A62 (2 NFRs) + A70 (3 stories) + A71 (3 scenarios) + A72 (4 traces) + 4 phase3.*.pass markers + `audit_expectations.json` Phase-3 declarations. 29 new integration tests in `tests/test_integration_phase3_project_0001.py` mechanically pinning the cross-artifact join + the headline US-S8-03 acceptance ("every test scenario links back to claim+source through the matrix").

- **`bsa-backlog-bridge` real implementation** (Sprint 9 US-S9-01..03, commit `01a5de9`) — three export schemas (Jira REST v3 JSON, Linear CSV, generic CSV) under `analysis/handoff/`; first F5 dispatcher entries on handoff/ paths; new `_validate_jira_export_json` helper for the JSON shape (CSVs reuse `_make_csv_validator`); two new terminal markers (`phase3.backlog_exported`, `pipeline.phase3.complete`) with EXACT H-sec-4 bindings (neither ends in `.pass` so the patterned-match doesn't cover them); INV-08 carry-through to all 3 exports (Jira via `bsa_provenance.anyOf`; Linear/generic via `x-bsa-provenance-rules`); INVEST-A51 coupling carry-through to generic export via `x-bsa-invest-rules`; Jira labels enforce membership (must include `bsa-export` + `level-N` + `invest-N`) AND singularity (`maxContains: 1`); Linear labels enforce same via positive + negative lookahead regex; real SKILL.md spec replacing the v1.0.x scaffold.

- **`adversarial_nfr_claim_contradiction_001` regression baseline** (Sprint 9 US-S9-04, commit `e209010`) — proves the Phase-3 chain handles contradictory evidence end-to-end. Two T2 sources (same-tier per `reliability_tier_spec.md` so no auto-resolution) disagree on a measurable target; the chain propagates the contradiction as A51-routed deferrals at every layer (A59 ClaimStrength=0.0; A62 Target empty + Metric non-empty + A51Ref set; A70 INVESTStatus=needs-negotiation + A51Ref; A71 AutomationStatus=deferred + A51Ref + Then-clause preserves both literals; A72 LinkType=a51-routed on every trace + A51Ref). 35 integration tests in `tests/test_integration_phase3_contradiction.py` including the headline `test_contradiction_propagates_to_every_phase3_artifact` mechanical pin.

- **3 new immutable invariants** codified in `governance/immutable_invariants.md` (Sprint 9 US-S9-05):
  - **INV-08 (Story-claim provenance)** — every A70 row carries non-empty `SourceClaimIDs` OR `RelatedNFRIDs`. Carries through to all 3 backlog export shapes via `x-bsa-provenance-rules` / Jira `bsa_provenance.anyOf`.
  - **INV-09 (NFR measurability)** — every quantitative-category A62 row carries non-empty `Metric+Target` OR non-empty `A51Ref`. Qualitative categories may omit Metric+Target but must populate `TestabilityNotes`.
  - **INV-10 (Test-scenario provenance)** — every A71 row carries non-empty singular `SourceStoryID` resolving in A70. Composite scenarios are forbidden.

### Tests

- **+946 tests** across the v1.0.x → v1.1.0 window (978 → 1248). Within Sprint 6-9 alone, +191 (1057 → 1248) covering: A62/A70/A71/A72/backlog-export schema conformance + extension shape pins + cross-field handler regressions; H-sec-4 binding for all 6 phase3.* markers; integration-level cross-artifact join validation across both happy-path + adversarial fixtures; anti-drift discipline (numeric-token grounding + banned-phrase pins) on every Phase-3 fixture.

### Codex review discipline

- **34 Codex review rounds** total across Sprint 8 + Sprint 9 USes (8 + 4 + 4 + 6 + 7 + 0 bookkeeping); every substantial US reaching APPROVE before commit. Each US's commit message carries the per-round finding tables. Adversarial-fixture authoring (US-S9-04) needed more rounds (7) than happy-path because the adversary surface (LLM averaging, tier-policy interactions, WHAT-vs-THRESHOLD asymmetry, contradiction-ClaimStrength rule) is genuinely larger.

### Carried forward (deferred to v1.1.x / v1.2 / v1.3)

- `[TODO-S8-01-X-ARTIFACT-NFR-COVERAGE]` + `[TODO-S8-02-X-ARTIFACT-FK]` — hook-layer enforcement of cross-artifact rules (A71 NFR-coverage; A72 FK + claim-source consistency). Currently documentary at the schema layer + skill-self-validated + integration-test-pinned. Future cross-artifact validator pattern (v1.2 candidate).
- `[TODO-S9-01-JIRA-CUSTOMFIELDS]` / `[TODO-S9-02-LINEAR-PROJECTS]` / `[TODO-S9-03-GITHUB-PROJECTS]` — additional platform-export polish. v1.2.
- `[TODO-S9-LIVE-API]` — optional live-API mode (POST to Jira/Linear directly). v1.3.
- Block-on-contradiction failure mode + multi-way contradictions + tier-delta auto-resolution case — separate adversarial fixtures for v1.2.
- Pilot-1 blockers: IssueType `inventory_gap` + Severity `critical` enum extensions (separate from the v1.0.4+1 `RaisedByStage` extension). Triage with operator.

## [v1.0.4] — 2026-04-22

**UX-pass release** — adds a shell-friendly `bsa` CLI that READS the workspace state and tells the operator where they are + what to do next, plus stages external materials (PDF/DOCX/MD/TXT) into the canonical Stage-1 inputs surface with a draft A50 source manifest. The CLI does NOT replace slash-commands; all canonical state mutation still goes through `/bsa-start`, `/bsa-stage`, `/bsa-promote`, `/bsa-audit`, `/bsa-handoff`. Read-only on canonical state for `status`/`next`/`doctor`; `materials` writes only to `analysis/proposals/stage1/inputs/` (gated by `--commit`, outside the F5 dispatcher regex).

**Tag target**: commit `9d3c99b` (last of the v1.0.4 commits).
**Canon policy version**: `1.0.3+hash:0d4d1de4` — unchanged from v1.0.3. No POLICY_GLOBS file was touched.

### Added

- **`scripts/bsa` (shell wrapper)** + **`scripts/bsa_cli.py` (Python CLI)** — locates the plugin repo from realpath-on-`$0` (same lockdown as `hooks/pre_write_canonical.sh` per v1.0.2 C3), so the documented `ln -s /path/to/bsa-plugin-family/scripts/bsa ~/.local/bin/bsa` install mode works. Stdlib at module level; PDF/DOCX libs imported lazily inside the materials subcommand.

- **`bsa status`** (`895581f`) — Reads A48 (RunID, Mode, CurrentStage, CanonPolicyVersion), markers in both zones (`analysis/runtime/ready/` + `analysis/discovery/runtime/ready/`), A51 open counts split by BlockingStatus, and audit outputs (no-new-claims report, citation/consistency reports). Tolerates Pilot-1-class camelCase markers (`marker`/`emittedAt` instead of `marker_id`/`timestamp`) via fallback keys; tolerates malformed marker JSON (skipped silently). Uninitialized workspace exits 2 with clear "not a BSA workspace" message.

- **`bsa next`** (`c9013e8`) — State machine over A48 stage + marker presence → next slash-command suggestion. `_STAGE_REQUIRED_MARKERS` table mirrors `hooks/pre_bash_promote.sh` exactly (drift-check test parses the hook's case-pattern block). Zone-aware presence checks (`_zone_filenames_for_stage`); main vs discovery zones never cross-contaminate. Distinguishes d1 init state (where `/bsa-start` emits `discovery.d1.ready` BEFORE the worker runs) via `_d1_has_proposal_output` check; suggests `/bsa-stage d1 run` instead of bogus `/bsa-promote`.

- **`bsa doctor`** (`77d305d`) — Composes 4 repo validators against the workspace (validate_marker_chain × 2 zones, validate_a51_reconciliation, validate_no_new_stories with SKIP when no A70, privacy_scan with `--root <ws>/analysis` to dodge the `DEFAULT_SKIP_DIR_NAMES` "analysis" entry) + walks every canonical artifact through `python3 -m governance.schemas.write_validator`. Single green/red signal before `/bsa-promote`. Exit-code contract `0/1/2`: ALL CLEAN / workspace dirty / doctor-environment broken — CI can distinguish "workspace has issues" from "doctor itself is broken". Privacy-scan output routed to a tempfile so the plugin's own `docs/privacy_audit.md` is not corrupted by external-workspace runs. Pre+post `is_dir(analysis/)` bracketing closes the TOCTOU false-clean race when the workspace tree is torn out mid-run.

- **`bsa materials <src-dir>`** (`9d3c99b`) — FIRST write-side CLI subcommand. Converts PDF (pypdf, optional), DOCX (python-docx, optional), MD/TXT (verbatim) into MD files staged under `analysis/proposals/stage1/inputs/source_NNN_<slug>.md`, plus a DRAFT `source_manifest.csv` matching the A50 column order EXACTLY (`ReliabilityTier=T5` default; user must re-tag during `/bsa-stage 1`). Default is dry-run preview; `--commit` required to write; `--force` overrides idempotency; `--recursive` walks subdirs. Three-layered idempotency (Origin in manifest → slug-on-disk + provenance match → exact target collision); slug collisions across distinct sources allocate `<base>_<sha1[:6]>` alt-slugs instead of false-skipping. Atomic writes via `_atomic_write_text` (tempfile + os.replace + chmod-preserve). Refuses if any of `analysis/`, `proposals/`, `stage1/`, `inputs/` is a symlink, OR if `manifest_path`/planned target is a symlink, OR if existing manifest header drifts from `_A50_HEADER`, OR if existing manifest is read-only (`os.access(W_OK)` check, since `os.replace` would otherwise bypass mode bits). Recursive walk skips symlinked DIRECTORIES (would loop forever) but honors symlinked FILES (legit cloud-folder use case).

### Tests

- 71 new regression tests added under `tests/test_bsa_cli.py` (978 → 1061 cumulative across the v1.0.3 → v1.0.4 window). Covers: graceful degradation on uninitialized / malformed / drifted workspaces; bash wrapper + symlink install path; state-machine drift-check against `pre_bash_promote.sh`; doctor exit-code contract + plugin-repo-untouched invariant; materials idempotency (3 layers); materials write-side safety (symlinks, header drift, atomic writes, mode preservation); optional-dep install-hint surfaces correctly; A50 schema compliance of the draft manifest.

### Codex review discipline

- 18 Codex review rounds total across 4 chunks (2 + 3 + 6 + 7), all reaching APPROVE. Each chunk's commit message carries the per-round finding tables. Pattern: read-only chunks (status, next) closed in 2-3 rounds; subprocess-orchestration chunk (doctor) needed 6 (multiple TOCTOU narrowings); first write-side chunk (materials) needed 7 (every threat class — symlinks, idempotency, atomicity, mode preservation — addressed individually). Future write-side commands should budget 5-7 review rounds.

### Deferred (carried into v1.0.4+1 polish)

- **A51 `RaisedByStage` enum extension** — Phase-2.5 pilot uses `discovery.d1`..`discovery.d5` + `discovery.complete` as RaisedByStage values, but A51 schema enum currently only documents `stage1`-`stage8` + `handoff`. Pilot blocker — without this the discovery-zone A51 issues fail F5 validation.
- **Malformed-extension-shape `isinstance` guards** — A59/A62/A70 cross-field rule handlers assume the extension property is either absent or a dict. A truthy-non-dict value would `AttributeError`.
- **A62/A70 shape-pin tests** — A59 has `test_a59_claim_type_rules_schema_extension_structure`; A62/A70 don't.

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
- Next step: Phase-2.5 pilot on v1.0.3 on the Pilot-1 Order & Deliver materials, now with A59 + A62 + A70 all mechanically enforced. If clean, proceed to Sprint 8 (bsa-test-scenario-builder, US-S8-01).

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

- **C1 — hooks.json matcher coverage** (`743a496`) — Pre-fix, the PreToolUse:Write matcher covered only `analysis/canonical/**`. Marker writes to `analysis/runtime/ready/**` and `analysis/discovery/runtime/ready/**`, plus `analysis/discovery/canonical/**` writes, bypassed F5 entirely. The entire Pilot-1 engagement marker-drift class (camelCase marker_id, legacy `no_new_facts` filename) landed unmolested on v1.0.1. Matcher list now covers all four protected-path classes; stderr diagnostics generalized accordingly. 2 new data-level assertion tests would have caught the original miss.

- **C2 — A59 cross-field rules executable** (`e5418f4`) — Pre-fix, `x-bsa-claim-type-rules` in `a59.schema.json` declared INV-01 + INV-07 rules in plain text, but `_make_csv_validator()` ignored the extension. Bypasses: `ClaimType=direct` with empty `ExcerptID` + empty `A51Ref` passed (INV-01); `analyst_judgment` with empty `JustificationRationale` passed (INV-07). New helper `_apply_claim_type_rules()` reads the extension and applies per-row cross-field checks after JSON Schema. 9 regression tests.

- **C3 — `BSA_PLUGIN_REPO` env-injection lockdown** (`ab6a8f8`) — Pre-fix, both hooks resolved `PLUGIN_REPO` from `${BSA_PLUGIN_REPO:-${CLAUDE_PLUGIN_ROOT:-<script-derived>}}`. Attacker-controlled `BSA_PLUGIN_REPO=/evil` pointed at a permissive `governance.schemas.write_validator`; all hook subprocess validation redirected. Round-1 attempt gated the override on a paired flag (`BSA_PLUGIN_REPO_ALLOW_TEST_OVERRIDE=1`); Codex correctly rejected — any attacker injecting one env var can inject two. Round-2 removed the override entirely. Priority now: script realpath → `CLAUDE_PLUGIN_ROOT` fallback. 2 paired-injection regression tests.

- **H-sec-4 — marker filename↔marker_id + FormatChecker + path normalization** (`8d3c7e7`) — Pre-fix, marker validation was syntactic only. `timestamp: "not-a-date"` passed (FormatChecker not enabled); filename↔payload binding unenforced (file named `stage8.no_new_claims.pass.json` could carry `marker_id=stage1.ready` and still satisfy `pre_bash_promote.sh`'s filename-presence check); marker_id↔stage/verdict bindings unenforced. All three closed. Round-2 Codex review caught a residual `..`-traversal bypass of the dispatcher regex itself; fixed with `posixpath.normpath()` in `_dispatch()` + `validate_canonical_write()`. 14 regression tests across two rounds.

### Added (tests only)

27 regression tests total — each is a direct replay of a Codex-flagged attack path:
  - 2 data-level hook-config assertions (C1 protected-path coverage).
  - 9 A59 cross-field coverage tests (C2).
  - 2 env-injection attack replays (C3).
  - 14 marker-binding tests (H-sec-4: timestamp, filename binding, stage/verdict binding, traversal normalization, Pilot-1 attack replay).

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

Sprint 5 close — **contract-enforcement hardening release**. Schema-as-source-of-truth for canonical artifacts, plus write-time mechanical enforcement via the PreToolUse:Write hook. Closes three reviewer P-level findings (P1 marker-validator alphabet drift, P1 promote-hook A48 parse failure, P2 privacy-scan letter-only secrets). Also closes the entire Pilot-1 engagement drift class identified during the Phase 2.5 trial run.

**Tag target**: commit `8d4692a` (last Sprint-5-work commit, before Sprint-6 Phase-3 kick-off scaffolding).
**Canon policy version at v1.0.1**: `1.0.1+hash:65a577fd6dea35474d349e312d6890690625aff11414b3e19848dfbdfc00a93b`. Hash advanced from `cbba8e53…` (v1.0.0) because `runtime-marker-schema.md` gained the previously-undocumented `stage1.ready`, `discovery.d{2,3,4,5}.ready`, and verdict `MERGED` — filling documentation gaps surfaced by the schema-conformance tests.

### Added
- **F4a** (`034ddb3`) — `governance/schemas/marker.schema.json` + `governance/schemas/loader.py` + 18 schema-conformance tests. Closed marker-ID alphabet (36 IDs); `verdict` enum extended with `MERGED` for composite-promotion markers. Alphabet-sync test prevents future doc-vs-schema drift.
- **F4b + F2** (`dd5efe8`) — `governance/schemas/a48.schema.json` + three-format A48 parser (`parse_a48`: table / bullet-backtick / bullet-bold). `python3 -m governance.schemas.loader a48-field` CLI. `hooks/pre_bash_promote.sh` delegates parsing to the CLI instead of an in-bash grep that silently failed on table-format A48.
- **F1** (`c7dd646`) — `scripts/validate_marker_chain.py` reads alphabet + audit-pass sequences from the schema. Private `MAIN_CYCLE_SEQUENCE` / `DISCOVERY_SEQUENCE` tuples removed. Stage-ready / end-state / bridge / non-go-decision markers no longer rejected as `chain-unknown-marker`. `bsa.stage1.entry.enabled` no longer double-rejected.
- **F3** (`e648401`) — `scripts/privacy_scan._is_likely_natural_prose` rewritten: known-token-prefix gate (21 real secret prefixes: ghp_, sk_live_, xoxb-, AKIA, eyJ, glpat-, shpat_, etc.) + vowel-ratio heuristic (0.30..0.50 prose band). The `QwErTyUiOpAsDfGhJkLzXcVbNm` false-negative reproducer now surfaces as `api_key_token`.
- **F7** (`9495c2b`) — `commands/bsa-status.md` emits three state-aware notices: `discovery-deliverable-only`, `pre-stage-ready`, `handoff-ready-not-emitted`. Direct UX fix for the Pilot-1 engagement operator-confusion at discovery-exit + bridge state.
- **F4c + F4d** (`12ec5e9`) — CSV row schemas for A50/A51/A58/A59/A60 + `iter_a50_rows`..`iter_a60_rows` loader helpers + `tier_to_claim_strength()` + 45 schema-conformance tests. `A59.ClaimType` pins the closed INV-07 enum (`direct | inference | analyst_judgment`); legacy values (`policy_statement` / `factual_state` / `process_step` / `decision_pending`) explicitly listed in the `x-bsa-banned-claim-type-values` extension as documentation.
- **F5** (`5025b2a`) — `governance/schemas/write_validator.py` with path-to-schema dispatcher for all 7 canonical artifacts. `hooks/pre_write_canonical.sh` now runs content validation after the INV-02 identity check. 35 tests including direct Pilot-1-regression replays (camelCase marker, legacy no_new_facts filename, legacy ClaimType in A59, drift tier label in A50) — all blocked at the hook with structured stderr.
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
- Manual replay of every Pilot-1 engagement drift shape → each blocked at the write hook with structured stderr.
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
