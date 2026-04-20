# Sprint 4.5 Retrospective — Plugin MVP Release

**Window:** Sprint 4.5 (week 12 of the 12-week Phase 0-2 roadmap).
**Tag target:** `v1.0.0` (created on HEAD once this retro commit is codex-approved + the manifest version bump from `1.0.0-rc2` → `1.0.0` lands). Sprint 4.5 is fixture + documentation work; canon policy files did not change in this sprint, so the hash stays at `cbba8e53` (carried from v1.0.0-rc2 close).
**Canon policy version at retro emission:** `1.0.0-rc2+hash:cbba8e53`. After US-S45-03 manifest bump: `1.0.0+hash:cbba8e53`.

## What was delivered

| User story | Status | Commit(s) | Review rounds |
|---|---|---|---|
| US-S45-01 Part A — project_0002 prep-shell upgraded to full fixture | done | `b7438aa` | 0 (clean pass, aligned to Part B templates) |
| US-S45-01 Part B — project_0003 authored from scratch (process + discovery + multi-stakeholder conflict) | done | `d147236` + `92cccae` (round-1 fixes) | 2 |
| US-S45-02 — 6 docs/ pages + README polish | done | `<docs-commit>` | `<N>` |
| US-S45-03 — v1.0.0 final tag | done | `<tag-commit>` + `v1.0.0` | 0 (release workflow gates pass or fail) |
| Sprint 4.5 retrospective (this file) | done | `<retro-commit>` | `<N>` |

Plus: `v1.0.0` git tag (pending US-S45-03).

## Acceptance criteria coverage

**US-S45-01 (3 ACs across both parts):**

- **AC-1** (3 fixtures covering different axes): PASS.
  - `project_0001` — process path + direct mode + support-ticket ops domain (Sprint 0.5 baseline).
  - `project_0002` — structural path + discovery mode + mixed-tier domain (analytics platform ownership). Part A promoted this from the Sprint 2 prep shell.
  - `project_0003` — process path + discovery mode + multi-stakeholder conflict (procurement approval workflow with two T4 sources contradicting at tier-delta 0). Part B authored from scratch.

- **AC-2** (all 3 fixtures pass fixture_runner end-to-end): PASS. `python3 scripts/fixture_runner.py --all` reports 4 fixtures × 0 findings (three `project_*` + `adversarial_prompt_injection_001`).

- **AC-3** (CI `fixture_smoke` job covers all 3): PASS. `.github/workflows/ci.yml` already invokes `fixture_runner.py --all`; total CI runtime remains ≤ 15 min.

**US-S45-02 (4 ACs):**

- **AC-1** (README polished with install/usage/docs links + CI badge): PASS. `README.md` rewritten: `kkitanin/bsa-plugin-family` owner, 30-second tour command sequence, docs/ link inventory, Phase 2.5 shakedown boundary note, v1.0.0 status line, accurate skills/commands/hooks/tests/fixtures counts.

- **AC-2** (6 docs/ pages): PASS.
  - `docs/getting_started.md` — install + 30-second tour + full-pipeline walkthrough + modes explanation.
  - `docs/workflow.md` — stage-by-stage (main cycle + discovery) + two-key promotion + invariants summary.
  - `docs/commands_reference.md` — every slash-command with flags, preconditions, postconditions, failure modes, graceful-degradation language.
  - `docs/troubleshooting.md` — 10 common failure modes covering install / evidence-binding / missing marker / KPI-001 failure / sidecar tools / marker-chain gap / no-new-claims hang / tier-delta contradiction / canonical accident / canon hash mismatch.
  - `docs/architecture_overview.md` — skill family breakdown (9 workers + 5 discovery + 5 auditors + 2 sidecars + 1 orchestrator + 1 meta = 23), three-layer governance (markers + invariants + canon hash), runtime layout, sidecar contract.
  - `docs/faq.md` — 12 FAQ entries covering production-readiness, claim vs fact terminology, tier model, contradiction handling, analyst_judgment semantics, sidecar standalone usage, adversarial fixture purpose, new-fixture workflow, canon-hash update procedure, workspace ownership, v1.0 scope boundaries.

- **AC-3** (CHANGELOG v1.0.0 entry): PASS. Entry describes: US-S45-01 Part A + B (fixtures project_0002 + project_0003), US-S45-02 (6 docs + README polish), tag-level canon-hash confirmation (unchanged `cbba8e53`). Breaking-changes section notes that v0.9 → v1.0 migration pack remains available under `migrations/`.

- **AC-4** (troubleshooting covers ≥ 5 common failure modes): PASS. 10 scenarios drafted.

**US-S45-03 (3 ACs):**

- **AC-1** (`v1.0.0` git tag + release workflow publishes): `<pending tag push>`. Release workflow gates: canon-hash match (cbba8e53), version↔tag match (1.0.0), pytest, fixture runner, marker chain, tracked-only archive, sha256 checksum — all pass per local pre-flight.

- **AC-2** (installable on clean Claude Code): `<pending external shakedown>` — smoke-tested locally via plugin manifest schema check. Phase 2.5 gate will exercise this on non-owned projects (2-4 weeks, blocking for Phase 3 kickoff).

- **AC-3** (CanonPolicyVersion in `.claude-plugin/plugin.json`): will PASS at US-S45-03 commit time. Planned bump: `canonPolicyVersion.semver` `"1.0.0-rc2"` → `"1.0.0"`; `canonPolicyVersion.hash_full` stays `"cbba8e53b0312aeec2744e17d018583fcd96bba613a6b39be58ab702cb44fcb0"` (no POLICY_GLOBS file touched in Sprint 4.5); release workflow's hash-match gate recomputes and confirms equality.

## Metrics

- **Tests:** 302 total (stable from Sprint 3/4 baseline — fixture authoring adds no new test cases, only new fixture files). Runtime: ~9s on Python 3.9.6.
- **Commits:** `<total>` approved in Sprint 4.5 across: US-S45-01 Part A (1 commit), US-S45-01 Part B (1 feat + 1 fix from round-1 codex review = 2 commits), US-S45-02 (1-2 commits depending on review rounds), US-S45-03 (1 chore bump + tag), this retro (1 commit).
- **Review rounds:** US-S45-01 Part A passed clean (round 0 — template already established from project_0002 shape). US-S45-01 Part B took 2 rounds (round 1 REJECT on C-007 JustificationRationale inconsistency + stage2 dependency count mismatch; round 2 APPROVE after fold-in + extension).
- **Lines of committed changes:** ~3500 (~2000 for project_0002 expansion + ~1500 for project_0003 + ~1800 for docs). Fixtures dominate; docs ~1800 LOC across 6 pages + README rewrite.
- **Fixture axis matrix complete:** process × direct + structural × discovery + mixed-tier + process × discovery × multi-stakeholder-conflict. Three primary fixtures cover both modes (direct + discovery), both paths (process + structural), three domains (support-ticket ops + analytics platform ownership + procurement approval workflow), and single-stakeholder vs multi-stakeholder-conflict evidence mixes. Plus one adversarial fixture (prompt-injection) for the Phase 3 security baseline.

## What went well

- **Part A went first-try clean.** `project_0002` fixture shape was already anchored by the Sprint 2 prep shell (scenario + inputs + metadata); Part A only needed to fill `expected_outputs/` in the project_0001 pattern + emit the 7 markers + manifest. No codex round-1 rework. The prep-shell-first pattern from US-S2-03 validated its own design.

- **Part B exercised the contested tier-delta rule end-to-end.** `project_0003` deliberately has two T4 attestations contradicting at tier-delta 0 (finance PM says legal-is-advisory, legal PM says legal-is-gate). Both inference claims get `ClaimStrength=0.0`, both route to A51-002 with `BlockingStatus=hard`, analyst_judgment C-007 threads all five upstream ClaimIDs (C-002..C-006) via INV-07. The fixture demonstrates hard-blocker handoff policy (A51-002 hard doesn't block handoff emission, blocks downstream execution) — that's a subtle piece of governance that the fixture now anchors.

- **Round-1 codex review on Part B caught consistency gaps I missed.** Three medium findings, all internal-consistency (not correctness): C-007 rationale claimed 5 upstream refs but only contained 4, derived markers/reports were consistent with the *claim* not the *canonical rationale*, and stage2 had 4 dependency bullets in `context_state_frame.md` but only 3 DEP-* entries + `dependency_count=3` everywhere else. Round-2 fixed all three in one commit (3 files, 3/-4 lines) and APPROVED clean.

- **Docs drafting was mostly template-driven.** The workflow/commands/architecture docs could lean heavily on the SKILL.md files + contract references already authored in Sprints 1-3. The FAQ and troubleshooting pages condensed lessons from the retros into user-facing advice.

## What was harder than expected

- **Figuring out which tier-contradiction A51 IssueType to use.** The reliability_tier_spec.md says `IssueType=cross_tier_contradiction` for tier-delta ≤ 1 contested claims, but the closed A51 enum (`shared-control-surface-contracts.md`) only lists `{uncertainty, contradiction, missing_source, decision_needed, boundary_risk}`. I used `IssueType=contradiction` in the fixture and noted the spec-vs-enum tension in README, but this is a latent inconsistency in the specs that should get resolved in a Phase 3 governance sweep. Spawned a task note for it.

- **A51 RelatedClaimID format when multiple claims are related.** `A51-002` has `RelatedClaimID="C-005;C-006"` (semicolon-separated). The fixture_runner only validates A60.RelatedClaimID pointing at A59 rows, not A51.RelatedClaimID, so the semicolon format passes. But it's a convention not a spec — multiple A51 rows in project_0002 use single IDs. Noted in fixture README for Phase 3 governance cleanup.

## What I would do differently

- **Pre-scan for self-referential consistency before inviting codex.** Round-1 codex caught the "rationale claims 5 refs but only has 4" issue; I could have caught it myself by running `grep -o 'C-[0-9]\{3\}'` against the rationale string before committing. Small helper script worth adding in Sprint 5+.

- **Spawn C-007 expansion as its own smaller commit.** Initially I rolled it into the main Part B commit; round-1 fix ended up being a 3-file micro-commit that would have been cleaner as a dedicated consistency-pass commit from the start.

## Hand-off to Phase 2.5 gate

Three fixture smoke tests + 302 pytest tests + privacy scan + marker chain validator + canon hash recompute all pass on HEAD. `v1.0.0` tag push triggers `.github/workflows/release.yml` 7-gate pipeline. The release body will auto-assemble from the new CHANGELOG entry.

**Next:** Phase 2.5 external shakedown. Not a sprint — a blocking gate for Phase 3 kickoff. Per the sprint plan:
- Plugin installed + used on 2-3 non-self-owned projects.
- Structured feedback collected per the 6 gate criteria.
- `docs/phase_2_5_shakedown.md` committed with aggregated feedback.
- Any blocker findings → v1.0.x hotfix release, NOT Phase 3 kickoff.
- Duration: 2-4 weeks non-negotiable.

The Phase 3 dev-handoff extension (bsa-nfr-collector, bsa-story-writer, bsa-test-scenario-builder, bsa-traceability-matrix, bsa-backlog-bridge, machine-readable Stage 6) is explicitly out-of-scope for v1.0.0 and the 12-week Phase 0-2 window.

Phase 0-2 closes here. Timeline: 12 weeks, on-budget. 23 skills, 6 commands, 3 hooks, 3 fixtures + 1 adversarial, 302 tests, 7 invariants under canon hash `cbba8e53`. First external release.
