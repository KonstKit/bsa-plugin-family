# v1.0.4 UX Pass Retrospective — `bsa` Shell CLI

**Window:** Tail of the Sprint-5 remediation cycle, run after v1.0.3 polish.
**Tag target:** `v1.0.4` (pending commit `9d3c99b`).
**Canon policy version at v1.0.4:** `1.0.3+hash:0d4d1de4` — unchanged from v1.0.3 (no POLICY_GLOBS files touched).

## Why this UX-pass release exists

After v1.0.3 the plugin's safety surface was solid (F1–F7 enforcement + retroactive Codex sweeps + A59/A62/A70 cross-field rules), but the operator surface was still LLM-only. State sat across five subdirectories (`runtime/ready/`, `canonical/`, `proposals/`, `handoff/`, `views/`); recovering from a hook-blocked write meant reading stderr, re-checking markers, and replaying slash-commands; onboarding a new engagement meant remembering "what's the next command given this state?".

The user pushback after the Phase-2.5 pilot was direct: *"слишком сложно использовать плагин сейчас"* — the safety net works, but the day-to-day UX is hostile to anything other than "the LLM does everything". v1.0.4 is the answer: a shell-friendly `bsa` CLI that READS the workspace state and tells you where you are + what to do next, plus stages external materials into the canonical inputs surface.

The CLI does NOT replace slash-commands. All canonical state mutation still goes through the orchestrator skill (`/bsa-start`, `/bsa-stage`, `/bsa-promote`, `/bsa-audit`, `/bsa-handoff`). The CLI is read-only on the canonical state for `status`/`next`/`doctor`; `materials` writes only to `analysis/proposals/stage1/inputs/` (outside the F5 dispatcher regex, gated by `--commit`).

## What was delivered

| Subcommand | Surface | Commit | Codex rounds | Result |
|---|---|---|---|---|
| `bsa status` | A48 fields + markers (both zones) + A51 open counts + audit outputs | `895581f` | 2-3 | APPROVE |
| `bsa next` | State machine over A48 stage + marker presence → next slash-command suggestion | `c9013e8` | 3 | APPROVE |
| `bsa doctor` | Orchestrates 4 validators (marker_chain × 2 zones, A51-reconciliation, no-new-stories, privacy-scan) + walks every canonical file through the F5 write-validator. Single green/red signal | `77d305d` | 6 | APPROVE |
| `bsa materials <src-dir>` | Convert PDF/DOCX/MD/TXT → MD staged under `analysis/proposals/stage1/inputs/source_NNN_<slug>.md` + draft `source_manifest.csv` (T5 default) | `9d3c99b` | 7 | APPROVE |

Plus: this retro file + CHANGELOG `[v1.0.4]` entry + `v1.0.4` git tag (pending).

Cumulative size: **~2700 lines added** to `scripts/bsa_cli.py` + **~1700 lines added** to `tests/test_bsa_cli.py` across 4 commits. Zero changes to canonical schemas, hooks, or orchestrator routing.

## Acceptance criteria coverage

**Chunk 1 — `bsa status` (`895581f`):**
- AC-1: PASS — `WorkspaceState` reader (analysis/, A48 fields, both marker zones, A51 counts, audit outputs); CLI prints Stage / RunID / Mode / CanonPolicyVersion + last marker per zone + open A51 counts split by BlockingStatus.
- AC-2: PASS — graceful degradation: uninitialized workspace exits 2 with "not a BSA workspace" message; malformed marker JSON skipped silently; Sysco-drifted camelCase markers (`marker`/`emittedAt` instead of `marker_id`/`timestamp`) still parse via fallback keys.
- AC-3: PASS — bash wrapper at `scripts/bsa` with realpath-on-`$0` so the documented `ln -s ~/bin/bsa` install mode works.
- AC-4 (Codex review): APPROVE after 2-3 rounds (1 HIGH each: realpath bug, audit-output filename, emittedAt fallback).
- AC-5: PASS — 13 regression tests added (978 → 991, of which 13 in chunk 1).

**Chunk 2 — `bsa next` (`c9013e8`):**
- AC-1: PASS — `_STAGE_REQUIRED_MARKERS` table mirrors `hooks/pre_bash_promote.sh` exactly; drift-check test parses the hook's case-pattern block and asserts sorted-equality.
- AC-2: PASS — zone-aware presence checks (`_zone_filenames_for_stage`); main vs discovery zones never cross-contaminate suggestion logic.
- AC-3: PASS — d1 init state (where `/bsa-start` emits `discovery.d1.ready` BEFORE the worker runs) detected via `_d1_has_proposal_output` check; `/bsa-stage d1 run` suggested instead of bogus `/bsa-promote`.
- AC-4 (Codex review): APPROVE after 3 rounds (HIGH-1: d1 init false-positive promote; HIGH-2: payload-vs-filename presence mismatch; MEDIUM: handoff branch + discovery.complete branches).
- AC-5: PASS — 19 regression tests added (991 → 1022).

**Chunk 3 — `bsa doctor` (`77d305d`):**
- AC-1: PASS — orchestrates 4 validators in subprocess (concat stdout+stderr); content walk through `python3 -m governance.schemas.write_validator` per canonical file.
- AC-2: PASS — exit-code contract `0/1/2`: ALL CLEAN / workspace dirty / doctor-environment broken. CI can distinguish "workspace has issues" from "doctor itself is broken".
- AC-3: PASS — privacy-scan trap (`DEFAULT_SKIP_DIR_NAMES` includes "analysis" → `--root <ws>` silently scans nothing) closed by passing `--root <ws>/analysis`. Plugin's own `docs/privacy_audit.md` not corrupted by external-workspace runs (`--output <tempfile>`).
- AC-4 (Codex review): APPROVE after 6 rounds. Per-round narrowing: HIGH (privacy-scan analysis-skip) → MEDIUM (rc=2 collapse, stdout drop) → LOW (TOCTOU race on content walk → `_iter_workspace_canonical_files(strict=True)` + post-enumeration is_dir() check brackets the entire enumeration window).
- AC-5: PASS — 11 regression tests added (1022 → 1033).

**Chunk 4 — `bsa materials` (`9d3c99b`):**
- AC-1: PASS — converts PDF (pypdf), DOCX (python-docx), MD/TXT (verbatim with encoding fallback). Optional deps imported lazily; missing deps surface a clear `pip install ...` hint in summary.
- AC-2: PASS — staged inputs land under `analysis/proposals/stage1/inputs/source_NNN_<slug>.md` with a provenance header `<!-- bsa materials: staged from <Origin> ... -->`. Draft `source_manifest.csv` matches A50 column order EXACTLY (pinned by `test_materials_install_hint_no_canonical_header_safety` + `test_materials_draft_manifest_validates_against_a50_schema`).
- AC-3: PASS — 3-layered idempotency: Origin in manifest (primary) → slug-on-disk + provenance match (manifest-deletion recovery) → exact target collision (final backstop). Slug collisions across distinct sources allocate alt-slugs (`<base>_<sha1[:6]>`) instead of false-skipping.
- AC-4: PASS — write-side safety:
  - `--commit` gated; default is dry-run preview.
  - Refuses if any of `analysis/`, `proposals/`, `stage1/`, `inputs/` is a symlink, OR if `manifest_path`/planned target is a symlink.
  - Refuses if existing manifest header doesn't match `_A50_HEADER` (would silently misalign appended rows).
  - Refuses if existing manifest is read-only (`os.access(W_OK)` check, since `os.replace` would otherwise bypass mode bits).
  - Atomic write via `_atomic_write_text` (tempfile + os.replace, with mode preservation) so mid-write failure leaves manifest unchanged.
  - Recursive walk (`--recursive`) skips symlinked DIRECTORIES (would loop forever) but honors symlinked FILES (legit cloud-folder use case).
- AC-5 (Codex review): APPROVE after 7 rounds. Each round narrowed the threat surface:
  - Round 1: 3 HIGH (symlink containment, target-existence idempotency, manifest header drift) + 2 MEDIUM (recursive symlink loops, ConversionUnavailable contract).
  - Round 2: 1 HIGH (leaf-symlink obхода containment) + 2 MEDIUM (slug-collision false-positive, header-drift non-atomic).
  - Round 3: 2 MEDIUM (provenance basename vs origin_rel, manifest-write non-atomic on non-header failures).
  - Round 4: 1 MEDIUM (orphan-recovery guidance broken) + 1 LOW (regression test didn't reproduce bug).
  - Round 5: 1 MEDIUM (`write_text` non-atomic → corrupted manifest possible).
  - Round 6: 1 MEDIUM (`os.replace` lost mode + bypassed W_OK).
  - Round 7: APPROVE, no findings.
- AC-6: PASS — 28 regression tests added (1033 → 1061).

## Tests / verification snapshot

- **1061 passed** at v1.0.4 tag point (978 baseline + 13 v1.0.3 + 31 chunks 1+2 + 11 chunk 3 + 28 chunk 4 = 1061).
- **18 Codex review rounds** total across 4 chunks (2 + 3 + 6 + 7), all reaching APPROVE.
- Smoke against `/tmp/sysco-pilot-v103` (Sysco engagement workspace): `bsa doctor` produces 4 FAIL sections + exit 1 + readable per-validator detail; plugin's own `docs/privacy_audit.md` byte-equal after.
- Smoke against synthetic workspaces: `bsa materials` dry-run + commit + idempotent re-run + `--force` + `--recursive` + symlinked-workspace refusal + drifted-header refusal + read-only manifest refusal — all behave as documented.
- Canon hash stable at `0d4d1de4...` (none of the v1.0.4 files are in POLICY_GLOBS).

## What remains open (carried beyond v1.0.4)

From the v1.0.3 retro:

- **LOW — malformed extension-shape guard** — A59/A62/A70 handlers assume the extension property is either absent or a well-formed dict. A truthy-non-dict value (e.g., `x-bsa-invest-rules: "please enforce"`) would `AttributeError` on `.get`. Filed as v1.0.4+1 polish (next item to land after this tag).
- **LOW — shape-pin tests for A62/A70 extensions** — A59 has `test_a59_claim_type_rules_schema_extension_structure`; A62/A70 don't. Filed as v1.0.4+1 polish.

From the Phase-2.5 pilot:

- **A51 RaisedByStage enum extension** — Sysco engagement uses `discovery.d1`, `discovery.d2`, ..., `discovery.d5`, `discovery.complete` as RaisedByStage values, but the A51 schema enum currently only documents `stage1`-`stage8` + `handoff`. Filed as v1.0.4+1 polish (pilot blocker — without this the discovery-zone A51 issues fail F5 validation).

From the chunk-4 review:

- **Per-target leaf-symlink check is defense-in-depth but unreachable** with current planning logic (monotonic `_next_source_id` + slug-routing always allocate around pre-existing symlinks). Documented in the test file with a comment; if planner internals change in the future, the per-target check becomes a meaningful guard.
- **Orphan-input recovery is manual** — if the manifest write fails after some inputs are already staged, the user must delete the orphans + re-run from scratch. A `--recreate-manifest` flag that walks `inputs/` and rebuilds `source_manifest.csv` from provenance comments is filed as a future enhancement (v1.1.0 polish, not v1.0.x scope).

## Lessons

- **Read-only chunks are cheap; write-side chunks are expensive.** Chunks 1+2 (status, next) closed in 2-3 Codex rounds. Chunk 3 (doctor) needed 6 because subprocess orchestration + privacy-scan traps + TOCTOU races against the workspace tree. Chunk 4 (materials) needed 7 because we crossed the canonical-state boundary for the first time — every threat class (symlinks, idempotency, atomicity, mode preservation) had to be addressed individually. Pattern for future write-side commands: budget 5-7 review rounds, not 1-2.

- **Codex disambiguates HIGH-vs-LOW well; trust the verdict.** Across 18 rounds, every HIGH finding pointed at a real exploitable defect (write redirect, false-clean exit, mid-write corruption). Every LOW was advisory polish (missing test, missing comment, marginal race). The MEDIUM tier was where most narrowing happened — Codex would catch the LITERAL bug, then a round later catch the SUBTLER bug behind it. The "TOCTOU race" thread in chunk 3 is the canonical example: round 3 caught the obvious case, round 4 caught the post-check window, round 5 caught the during-enumeration window, round 6 (APPROVE) confirmed the pre+post bracketing closed everything.

- **Atomic-write primitive belongs in a shared helper.** `_atomic_write_text` (tempfile + os.replace + chmod-preserve) was hand-written in chunk 4 round 5 + 6. The next write-side command (sprint 8 likely) should reuse it; keep it as a top-level helper, not a closure. Bonus: the chmod-preserve detail is non-obvious — `os.replace` swaps the inode, so the mode bits live on the tempfile, not the destination. Without `os.chmod(tempfile, orig_mode)` before `os.replace`, every atomic write resets mode to mkstemp's 0600 default.

- **Provenance comments enable manifest-deletion recovery without a separate index file.** Chunk 4's slug-collision disambiguation reads each staged file's `<!-- bsa materials: staged from <Origin> ... -->` header to decide whether a slug collision is "same source, truly already staged" vs "different source, allocate alt slug". This means the manifest is recoverable from the input files alone — useful for the eventual `--recreate-manifest` flow, and useful right now for recovery from accidental `rm source_manifest.csv`.

- **Optional deps via lazy import + clear hint scales better than vendoring.** `pypdf` + `python-docx` are imported INSIDE the converter functions. Missing → ConversionUnavailable with a one-line `pip install ...` hint surfaced in the summary. The plugin core stays stdlib-only (the 1000-line CLI has zero pip deps); users opt in to PDF/DOCX support. Pattern generalizes to future format converters (PowerPoint, RTF, XLS) without bloating the install footprint.

## Release bookkeeping

- `v1.0.0`, `v1.0.1`, `v1.0.2`, `v1.0.3` tags remain at their original commits (no retag).
- `v1.0.4` tag lands on `9d3c99b` (chunk-4 commit, last of the v1.0.4 commits).
- Manifest `version` field stays at `1.0.0` through v1.0.4 (same SemVer rationale as the prior patches — bump to `1.1.0` at the Phase-3 feature release at Sprint 9 close).
- Canon hash unchanged at `0d4d1de4...`.
- Manifest `description` was NOT updated — the `bsa` CLI is operator UX, not a new plugin surface. Same rationale as why we didn't change the marketplace listing for v1.0.2 / v1.0.3.

## Related

- Sprint 5 retros:
  - `docs/retros/sprint_5.md` — scope-as-shipped at v1.0.1.
  - `docs/retros/sprint_5_v1_0_2_hotfix.md` — four must-fix items at v1.0.2.
  - `docs/retros/sprint_5_v1_0_3_polish.md` — three deferred HIGH + four doc-drift findings at v1.0.3.
  - `docs/retros/sprint_5_v1_0_4_ux_pass.md` — this file.
- Codex review outputs preserved as `/tmp/codex_out_*_chunk{1,2,3,4}_cr*.txt`.
- Chunk-by-chunk commit messages at `895581f`, `c9013e8`, `77d305d`, `9d3c99b` carry the per-round finding tables and fix descriptions.

Next: v1.0.4+1 polish — A51 RaisedByStage enum extension (pilot blocker), malformed-extension-shape isinstance guards, A62/A70 extension shape-pin tests. Then Sprint 8 (`bsa-test-scenario-builder`, US-S8-01).
