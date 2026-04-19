# Sprint 0 Retrospective — Foundation

**Window:** Sprint 0 (weeks 1-2 of the 12-week Phase 0-2 roadmap, executed in a single day of focused solo+AI work).
**Tag target:** `v0.9.0-foundation` (created on HEAD once this finalization commit is codex-approved — tagging is a post-commit git-ref operation, not commit content).
**Canon policy version:** 0.9 (pre-stabilization baseline).

## What was delivered

| User story | Status | Commit(s) |
|---|---|---|
| US-S0-01 — Git repo + copy 22 skills + initial commit | done | `cd893c8` (approved after 4 codex review rounds) |
| US-S0-05 — `governance/immutable_invariants.md` registry | done | merged into `cd893c8` |
| US-S0-02 — `validate_skill_structure.py` + 21 unit tests | done | `3f24cc2` (approved after 2 codex rounds) |
| US-S0-04 — inventory audit + privacy scanner + reports | done | `efed5a8` (approved after 5 codex rounds) |
| US-S0-03 — CI pipeline (GitHub Actions) | done | `c200d49` (approved round 1) + minor hardening follow-up |

Plus: `docs/retros/sprint_0.md` (this file) + `requirements-dev.txt` + CI read-only permissions. `v0.9.0-foundation` git tag is created immediately after this commit is approved.

## Acceptance criteria coverage

- US-S0-01 AC-1..AC-4: all met. Bootstrap on fresh target creates baseline docs, skeleton, copies 22 skills, initializes git, verifies integrity with hard-fail on drift.
- US-S0-02 AC-1..AC-4: all met. 22/22 baseline skills pass structural lint.
- US-S0-03 AC-1..AC-4: all met. CI matrix (Python 3.11+3.12), 5-min cap, sidecar validators wired, INoT smoke runs unconditionally (non-blocking in Phase 0).
- US-S0-04 AC-1..AC-4: all met. 22 stable / 0 broken inventory; 0 blockers / 0 warnings / 0 info privacy. Both reports committed and validated for idempotency in CI.
- US-S0-05 AC-1..AC-4: all met. 7 invariants enumerated with `id`, `statement`, `rationale`, `enforcement_mechanism`, `override_policy`. IMMUTABLE_CONFLICT policy documented for future Phase 7.

## Metrics

- **Test count:** 50 unit tests across `tests/` (21 for validator, 29 for privacy scan).
- **Scripts added:** 6 (`bootstrap_repo.sh`, `validate_skill_structure.py`, `inventory_audit.py`, `privacy_scan.py`, `privacy_whitelist.json` config, plus `.github/workflows/ci.yml`).
- **Docs added:** 8 (`README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `LICENSE`, `docs/inventory_audit.md`, `docs/privacy_audit.md`, `governance/immutable_invariants.md`, this retro).
- **Codex review rounds per commit:** 4 (bootstrap), 2 (validator), 5 (inventory+privacy), 1 (CI), plus this finalization commit. Total: 12 review rounds across 4 approved commits.
- **Tests pass:** 50/50 in ~1.6s on Python 3.9.6 (runtime Python not required to match CI matrix for local dev).

## What went well

- **Dog-fooding US-format paid off early.** Each user story's AC list was a concrete, testable checklist. `validate_skill_structure.py` literally encodes US-S0-02 ACs as assertions in `tests/test_validate_skill_structure.py`.
- **Codex review gate caught real defects.** Of 12 review rounds, 11 returned REQUEST_CHANGES — each with at least one genuine correctness or security finding that would have landed in production. Highlights:
  * `eval`-based command execution in bootstrap (shell injection)
  * integrity drift being warning-only (AC-3 not actually enforced)
  * `ensure_baseline_file` writing through dangling symlinks
  * `_has_word_like_content` suppressing real prefixed API keys with `_` / `-` separators
  * formatted credit card numbers with space/hyphen grouping evading the unseparated-digit Luhn detector
  * `Whitelist.load()` leaking uncaught `TypeError` on non-dict roots / non-string values
  * `SCN_PATTERN` capturing trailing-dash wildcards as concrete bindings
- **Stdlib-only discipline.** No third-party runtime dependencies. Only dev dep is `pytest` (pinned in `requirements-dev.txt`).
- **Deterministic report idempotency check.** Encoding `git diff --exit-code docs/*.md` in CI catches non-determinism in report generators at PR time.

## What was harder than expected

- **Review latency per commit.** 4 rounds on the bootstrap commit alone added ~20 minutes of wall-clock per round. For future sprints, front-loading defensive checks (symlink handling, type validation, regex edge cases) saves at least one review round.
- **Regex-based parsing is brittle.** The original Markdown link regex missed balanced parens and single-quoted titles. The replacement hand-written scanner is more code but handles CommonMark's edge cases correctly. Trade-off worth making even at Phase 0.
- **Whitelist schema drift.** The original `path_globs: [string]` form was ungoverned — no reason field, no type check. Converting to `{glob, reason}` objects + full type validation took three review rounds (4 → 5 on US-S0-04). Lesson for Phase 1: any user-facing config structure gets a schema + type guard on day 1.

## Carry-over into Sprint 0.5

- **US-S05-01:** First golden fixture + `fixture_runner.py` + `fixture_metadata.json` (model hash capture).
- **US-S05-02:** `config/request_skill_routes.json` + schema + validator. Wire into CI.
- **CI hardening recs not yet applied:**
  * Badge placeholder in `README.md` still reads `OWNER/bsa-plugin-family` — update on first push to remote.

## Phase 0 exit criteria (from plan)

- [x] All 5 US-S0-* AC passed
- [x] CI workflow authored and all steps pass local dry-runs (validators, pytest, c4 fixtures, bpmn xmllint, inot smoke). Remote GitHub Actions run will be verified on the first push.
- [x] Inventory + privacy reports reviewed
- [ ] Tag `v0.9.0-foundation` — to be created on the approved HEAD of this commit

Sprint 0.5 begins immediately after this tag.
