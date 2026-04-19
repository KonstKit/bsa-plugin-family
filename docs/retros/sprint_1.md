# Sprint 1 Retrospective — Stage 2 Gap Closure

**Window:** Sprint 1 (weeks 4-5 of the 12-week Phase 0-2 roadmap).
**Tag target:** `v0.95.0` (created on HEAD once this retro commit is codex-approved — Sprint 1 bumps canon policy from 0.9 to 0.95, reflecting the new worker skill and the extended ClaimType enum).
**Canon policy version:** 0.95.

## What was delivered

| User story | Status | Commit(s) | Review rounds |
|---|---|---|---|
| US-S1-01 part 1/2 — bsa-context-framer skill package | done | `97ed306` | 2 |
| US-S1-01 part 2/2 — orchestrator + claim-binder wiring | done | `a6a1ea4` | 2 |
| US-S1-02 — fixture Stage 2 expected_outputs + runner checks | done | `1215d08` | 1 |
| chore — gitignore personal Claude Code settings overrides | done | `b7589e1` | 1 |

Plus: `docs/retros/sprint_1.md` (this file) + `v0.95.0` git tag (pending).

## Acceptance criteria coverage

US-S1-01 (9 ACs per plan rev2):
- AC-1 through AC-5: PASS — bsa-context-framer produces the five Stage 2 proposal artifacts with required section headers, table columns, summary fields, and evidence citations per the lockstep contract pair (context-state-contract.md + stage2-runtime-contract.md).
- AC-6 text rewrite: PASS — every active "runtime-native" Stage 2 claim across the orchestrator surface (SKILL.md lines 14/31/107, workflow-contract.md, agent-write-scope.md, ownership-and-lifecycle.md, pilot-runbook.md) replaced with the bsa-context-framer-owned model. The only surviving occurrence is the explicit "deprecated" note in stage2-runtime-contract.md.
- AC-7 routing: PASS — config/request_skill_routes.json worker_set for bsa_pack_direct_mixed_sources grew from 14 to 15, placing bsa-context-framer between bsa-claim-binder and bsa-semantic-extractor.
- AC-8 claim-binder: PASS — invariants expanded with INV-07 enum closure reference; analyst_judgment rows are explicitly authored ONLY downstream (Stage 2 framer, H1/H4 packager), never during Stage 1 intake.
- AC-9 governance anchor: PASS via Sprint 0 US-S0-05 (INV-07 already in governance/immutable_invariants.md).

US-S1-02 (3 ACs):
- AC-1: PASS — fixture project_0001 now carries all 5 Stage 2 artifacts with shape matching the contract exactly.
- AC-2: PASS — fixture_runner --mode=compare (and --mode=both) clean on baseline.
- AC-3: PASS — 8 Stage 2 regression cases in total: 1 baseline pass, 6 adversarial mutations (missing required header, missing required column, missing summary field, wrong stage_id, bad context_mode, deleted artifact), and 1 presence-gate regression proving that a fixture WITHOUT canonical/stage2/ still validates cleanly (added as codex round-1 minor recommendation on commit 1215d08).

## Metrics

- **Tests:** 106 total (21 skill-lint + 29 privacy + 25 routing + 31 fixture). Growth +8 from Sprint 0.5 (98 -> 106). Runtime: ~3.6s on Python 3.9.6.
- **Commits:** 4 approved in Sprint 1 (1 chore + 3 feat: US-S1-01 part 1, part 2, US-S1-02). Plus this finalization commit.
- **Review rounds:** 6 total across the 4 commits (chore 1, part 1 round 2, part 2 round 2, US-S1-02 round 1).
- **Lines of committed changes:** ~1200 (bsa-context-framer skill + 3 references + Stage 2 fixture + runner extensions + test expansions + documentation updates).

## What went well

- **Lockstep contract pair worked.** bsa-context-framer's context-state-contract.md and bsa-orchestrator/references/stage2-runtime-contract.md were kept aligned from the start (required headers, columns, and fields are defined once and referenced from two points). The runner's STAGE2_*_REQUIRED_* constants mirror the contract data, giving us a machine-checked guarantee.
- **The lesson from Sprint 0.5 landed.** Writing validators defensively from the first draft ("write regex/checks with every edge case already in mind") cut Sprint 1's review-round count vs Sprint 0.5 (6 vs 7 rounds across approved commits of comparable scope).
- **Presence-gated Stage 2 validation** kept backward compatibility for fixtures that don't carry Stage 2 data (not a concern today, but matters as fixture library grows past the single project_0001 baseline). The dedicated `test_stage2_block_skipped_when_directory_absent` makes this a permanent invariant.
- **Residual-claim sweep via grep.** After codex flagged that AC-6 was incomplete at SKILL.md:14 only, I switched to `grep -rn "runtime-native"` across the whole orchestrator directory and caught 5 more locations I would otherwise have missed. This pattern is worth adopting as standard practice in subsequent sprints: every contract term rename runs through a repo-wide grep before first review request.

## What was harder than expected

- **Contract-term rename has wider surface than expected.** A simple "stage2 is runtime-native" -> "stage2 is worker-owned by bsa-context-framer" rewrite touched 6 distinct files across the orchestrator contract surface. Lesson for future renames: start with grep, enumerate every hit, then draft the rewrite once per location.
- **ClaimType field-name consistency.** Round-1 codex review on part 1/2 caught that I mixed `justification_rationale` (snake_case) and `JustificationRationale` (PascalCase) in the new skill package, even though the existing A59 schema was unambiguous. Added a habit-note: any new skill that references an existing canonical surface MUST grep the existing surface for field names before first draft.
- **Citation form drift.** Same round caught `[Cxxx]` vs `[C-xxx]` drift across the new Stage 2 references. The repo-wide convention is `C-xxx` (dashed); should ship a citation-style quick-ref to go with governance/immutable_invariants.md in a future sprint.

## Carry-over into Sprint 2

- **US-S2-01** — specify internal structure of H1-H4 handoff packages (currently "undocumented" per Phase 0 analysis). Re-surface of analyst_judgment ClaimType through H1 Executive Brief recommendations is the main behavioural extension.
- **US-S2-02** — `no-new-facts` -> `no-new-claims` naming unification with backward-compat marker aliases + partial-state migration fixture.
- **Future hardening** (from codex minor rec on US-S1-02): extend the Stage 2 shape validator from presence checks to full schema semantics — header ordering, seed_source / summary_version / required_headers_present value rules. Sprint 2 or later.

## Phase 1 progress

Sprint 1 closes the largest Phase-1 blocker (Stage 2 gap). Remaining P0 stabilization items are naming debt (Sprint 2), H1-H4 content contracts (Sprint 2), sidecar self-description (Sprint 3), discovery-to-main merge contract (Sprint 3), ReliabilityTier operationalization (Sprint 3), drift detection specification (Sprint 3).

## Sprint 1 exit criteria

- [x] All US-S1-* AC passed (US-S1-01 AC-1..9, US-S1-02 AC-1..3)
- [x] bsa-context-framer passes all 9 ACs of US-S1-01
- [x] Fixture regression green on baseline; 8 Stage 2 regression cases total (1 baseline pass + 6 adversarial mutations + 1 presence-gate regression) — each mutation produces a specific finding code
- [x] CI remains green (local dry-run all steps pass)
- [x] CanonPolicyVersion bump to 0.95 documented in fixture summary, marker, and contract_version field
- [ ] `v0.95.0` tag — to be created on the approved HEAD of this retro commit
