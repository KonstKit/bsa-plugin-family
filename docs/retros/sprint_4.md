# Sprint 4 Retrospective — Plugin MVP Core

**Window:** Sprint 4 (weeks 10-11 of the 12-week Phase 0-2 roadmap).
**Tag target:** `v1.0.0-rc2` (created on HEAD once this retro commit is codex-approved). Sprint 4 is packaging work; canon policy files did not change in this sprint, so hash stays at `cbba8e53` (carried from v1.0.0-rc1 close + the Sprint-3-retroactive governance sweep that landed at Sprint 4 kickoff).
**Canon policy version:** `1.0.0-rc2+hash:cbba8e53`.

## What was delivered

| User story | Status | Commit(s) | Review rounds |
|---|---|---|---|
| US-S4-01 AC-0 — plugin API spike (`docs/plugin_api_spike.md`) | done | `06d5b2f` | 0 (spike-only, no AC review) |
| US-S4-01 AC-1..AC-4 — plugin manifest + release workflow | done | `10cb3f1` + `4c1a50b` | 2 |
| US-S4-02 — slash commands (bsa-start/status/stage/promote/audit/handoff) | done | `709e27e` + `a6687c8` (shared fix) | 2 |
| US-S4-03 — plugin hooks (SessionStart + PreToolUse:Write + PreToolUse:Bash) | done | `0828e9e` + `a6687c8` (shared fix) | 1 (approved round 1) + policy-alignment fix folded into US-S4-02/04 round-2 commit |
| US-S4-04 — install/uninstall flow + `INSTALL.md` | done | `0828e9e` + `a6687c8` (shared fix) | 2 |
| Sprint-3 retroactive — `governance/immutable_invariants.md` fact→claim sweep | done | `fcde0dc` + `fc8616b` | 0 (auto-applied from Sprint-3 spawn_task; self-contained) |

Plus: `docs/retros/sprint_4.md` (this file) + `v1.0.0-rc2` git tag (pending).

## Acceptance criteria coverage

**US-S4-01 (4 ACs + AC-0 spike):**
- AC-0: PASS — `docs/plugin_api_spike.md` documents 7 authoritative answers from `code.claude.com/docs/en/plugins-reference` (schema fields, custom-field permissiveness, skill/command/hook layout, install flow, reference plugins). Drove 6 concrete design decisions recorded in the spike's "Decisions captured" table.
- AC-1: PASS — `.claude-plugin/plugin.json` with required `name=bsa-full`, semver `version=1.0.0-rc1`, author/license/keywords/homepage/repository, plus custom `canonPolicyVersion` block (semver + hash_prefix + hash_full + compute metadata).
- AC-2: PASS — default `./skills/` discovery covers all 23 committed skill directories; no restructuring needed.
- AC-3: PASS — manifest conforms to Claude Code plugin schema (verified via spike + tests). Custom fields preserved per the spike finding.
- AC-4: PASS — `.github/workflows/release.yml` triggered on `v*` tag push. Seven hard gates: canon-hash match, version↔tag match, pytest, fixture runner, marker chain, tracked-only archive (resilient to pre-US-S4-{02,03,04} content), sha256 checksum. Release body auto-assembled from CHANGELOG tag section + canon hash block + install one-liner. Round-1 REJECT was on the archive step hard-requiring `commands/`/`hooks/`/`INSTALL.md` paths; round-2 rewrite made it tracked-only via `git ls-files --error-unmatch`.

**US-S4-02 (10 ACs):**
- AC-1..AC-2: PASS — `/bsa-start --mode=direct` and `--mode=discovery_then_bsa` documented in `commands/bsa-start.md`; runtime layout spec matches `skills/bsa-orchestrator/references/workflow-contract.md`.
- AC-3: PASS — `/bsa-status` in `commands/bsa-status.md`; includes compact + verbose modes, invokes `validate_marker_chain.py` and `compute_canon_hash.py` for chain/drift detection.
- AC-4: PASS — `/bsa-stage <n> run` accepts both `stage1..stage8` and `d1..d5`; documents per-stage worker chain.
- AC-5 + AC-9: PASS — `/bsa-promote` with `--dry-run` non-mutating preview. The hook (`pre_bash_promote.sh`) verifies markers at the event layer before the command runs.
- AC-6: PASS — `/bsa-audit citation|consistency|skeptical|no-new-claims|anchor` (five kinds, plus three short aliases `cit`/`skp`/`nnc`).
- AC-7: PASS — `/bsa-handoff` invokes `bsa-handoff-packager`, runs no-new-claims, emits manifest with canon hash + sha256.
- AC-8: PASS — `--verbose` universal flag documented in all six command files (36 parametrized tests).
- AC-10: PASS — graceful-degradation language for `plantuml`/`xmllint` in `bsa-start`, `bsa-status`, `bsa-stage`; Failure modes section in every command.
- Round-1 REJECT was on a broken cross-ref (`.claude-plugin/hooks/hooks.json` — actual path `hooks/hooks.json`) + trailing-underscore typo. Round-2 resolved both.

**US-S4-03 (4 ACs):**
- AC-1: PASS — `SessionStart` hook (`hooks/session_start.sh`) detects BSA workspace via `analysis/canonical/core_controls/` presence; suggests `/bsa-status` + surfaces RunID + Mode from A48 when available. Exit 0 always (informational).
- AC-2: PASS — `PreToolUse:Write` hook on `analysis/canonical/**` matcher enforces INV-02 via `BSA_WRITER=bsa-orchestrator` env check.
- AC-3: PASS — `PreToolUse:Bash` hook on `bsa[- ]promote` command pattern verifies per-stage required markers before the command runs. Per-stage marker map kept in sync with `merge-and-reentry-policy.md` + `run-profile-gates.md`.
- AC-4: PASS — every hook failure mode emits a clear user-visible explanation on stderr + exits non-zero. Informational hook (SessionStart) uses stdout.
- Approved round 1; a minor stage4/handoff marker-set inconsistency between the hook script and the policy doc was folded into the US-S4-02/04 round-2 fix.

**US-S4-04 (4 ACs):**
- AC-1: PASS — `INSTALL.md` documents the `/plugin marketplace add <url>` + `/plugin install bsa-full` flow per spike finding.
- AC-2: PASS — `/plugin list` verification step included.
- AC-3: PASS — `/plugin uninstall bsa-full` documented; explicit contract that `analysis/` workspace is PRESERVED (never touched by uninstall).
- AC-4: PASS — Troubleshooting section covers 7 common scenarios. Round-1 REJECT was on a broken `semantic_validate_bpmn.py` path + too-casual BSA_WRITER override guidance. Round-2 rewrote to cite the correct skill-scoped path (`skills/camunda-bpmn-from-context/scripts/semantic_validate_bpmn.py`) + replaced the casual guidance with a 6-step formal maintenance procedure (prefer scripted migration → open A51 decision_needed → attach sponsor sign-off → create migration log → perform edit → run /bsa-status to verify). Framed as TECHNICAL gate (`BSA_WRITER`) + PROCEDURAL gate (`A51` + log) with both required.

## Metrics

- **Tests:** 730 total (was 671 at Sprint 3 close). +59 in Sprint 4 across: plugin manifest shape (+9), slash command shape (+36), plugin hooks (+14). Runtime: ~100s on Python 3.9.6.
- **Commits:** 8 approved in Sprint 4 (2 chore + 6 feat/fix), across 4 user stories + AC-0 spike + 2 Sprint-3-retroactive cleanups (governance sweep + sem_audit follow-up that auto-applied from the Sprint-3 spawn_task chip). Plus this retro.
- **Review rounds:** 5 total across the 6 feature commits. US-S4-01 took 2 rounds (archive resilience + CHANGELOG embedding). US-S4-03 passed round 1. US-S4-02 + US-S4-04 batch-reviewed together, round-1 REJECT + round-2 APPROVE for both.
- **Lines of committed changes:** ~2100 (plugin.json + release workflow + 6 command files + hooks.json + 3 shell scripts + INSTALL.md + tests + retros + CHANGELOG).

## What went well

- **Spike-first paid for itself.** Two days of plugin-format research before any code meant zero rework on `plugin.json` shape, the skills/commands/hooks directory layout, or the hook matcher syntax. The spike's "Decisions captured" table became the canonical reference every downstream story cited.
- **Batch review for US-S4-02 + US-S4-03 + US-S4-04.** Reviewing three tightly-coupled stories in one codex pass caught a cross-cutting finding (hook-script stage4/handoff markers didn't match the policy doc) that would have been invisible to per-story reviews. Downside: one story (US-S4-03) approved round 1 but had a finding folded into the round-2 fix commit for the other two — slightly muddies the per-story audit trail, but the retro documents the split.
- **Hook-layer enforcement vs command-layer enforcement.** Shipping both was the right call. The hook-layer checks (SessionStart / PreToolUse:Write / PreToolUse:Bash) catch the most common mistakes at the earliest event layer; the command-layer checks in `bsa-promote.md` + skill invariants are the belt-and-suspenders fallback. Either on its own would have been porous.
- **Test-locks on plugin shape.** `tests/test_plugin_manifest.py` + `tests/test_plugin_commands.py` + `tests/test_plugin_hooks.py` together ship 59 new tests that lock every plugin-MVP contract (manifest shape, command shape, hook behavior) against drift. Future refactors that touch these surfaces fail loudly.

## What was harder than expected

- **Release-workflow resilience.** The round-1 `git archive` step required `commands/`, `hooks/`, and `INSTALL.md` paths that didn't exist yet at US-S4-01 tag time (US-S4-02/03/04 hadn't landed). The workflow would have hard-failed on a v1.0.0-rc1 re-tag. Round-2 fix: build a tracked-only path list via `git ls-files --error-unmatch`, skip untracked candidates with a `::notice::`. The pattern generalizes: any release workflow that archives selected paths should skip-missing rather than hard-require.
- **Canon hash instability between tag and first plugin work.** The `v1.0.0-rc1` tag captured hash `ac039430`, but the Sprint-3 spawn-task chip auto-applied a retroactive governance sweep between tag-push and Sprint 4 US-S4-01, moving the hash to `cbba8e53`. The plugin.json manifest declares `cbba8e53`, which disagrees with the fixture markers' `ac039430` short prefix. Not a blocker — the policy-drift warning advisory mode from US-S3-04 explicitly handles this case — but it's a reminder that `spawn_task` chips can introduce policy-state drift that needs a conscious bump decision. Sprint 5+ should treat any auto-applied governance edit as a forcing-function for a fresh canon recomputation + plugin.json update.
- **Cross-ref path discipline.** Three of the four round-1 rejects were broken relative paths (`.claude-plugin/hooks/hooks.json`, `scripts/semantic_validate_bpmn.py`, `stage1..stage8_/`). All preventable via a pre-commit grep. Worth adding: a simple `scripts/validate_crossrefs.py` that follows every markdown link + file-path reference in committed skill/command/hook/doc files and fails on unresolved targets. Sprint 4.5 or later.

## Carry-over into Sprint 4.5

Sprint 4.5 is the release sprint per the plan — not a new feature story set but a polish + fixture pass:

- **US-S45-01** — full expected_outputs for `project_0002` (Sprint 2 US-S2-03 landed the prep shell); author `project_0003` from scratch (process path + discovery mode + multi-stakeholder conflict).
- **US-S45-02** — user-facing documentation: README polish, getting-started guide, troubleshooting expansion beyond INSTALL.md.
- **US-S45-03** — cut `v1.0.0` final tag (strip the `-rc` suffix). Release workflow (ready since Sprint 4 US-S4-01) publishes the GitHub Release.

Per plan Phase 2.5 gate: after v1.0.0 cut, shakedown on 2-3 non-self-owned projects before Phase 3 kickoff.

## Canon hash stability note

Sprint 4 did NOT change any POLICY_GLOBS file. Canon hash is the same at Sprint 4 close as at Sprint 4 open (`cbba8e53...`). Category breakdown confirms: all 5 bucket hashes match the Sprint 3 exit state. Only `hash_full` in `plugin.json.canonPolicyVersion` updated (from the Sprint-3 `ac039430` to the post-retroactive-sweep `cbba8e53`).

## Sprint 4 exit criteria

- [x] AC-0 plugin API spike complete.
- [x] `.claude-plugin/plugin.json` manifest installable per spike findings.
- [x] 6 slash command files (bsa-start/status/stage/promote/audit/handoff) with --verbose + --dry-run + graceful-degradation language.
- [x] 3 plugin hooks (SessionStart + PreToolUse:Write + PreToolUse:Bash) with shell scripts + 14 unit tests covering every branch.
- [x] `INSTALL.md` with install/uninstall/upgrade + 7 troubleshooting scenarios + formal BSA_WRITER maintenance procedure.
- [x] Release workflow tag-triggered; archive resilient to pre-story paths; release body embeds CHANGELOG + canon hash + install one-liner + sha256.
- [x] Plugin semver 1.0.0-rc1 → 1.0.0-rc2 (packaging refinements since the Sprint 3 tag; no canon hash change).
- [ ] `v1.0.0-rc2` tag — to be created on the approved HEAD of this retro commit.
