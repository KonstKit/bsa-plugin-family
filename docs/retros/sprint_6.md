# Sprint 6 Retrospective — Phase 3 Kick-off

**Window:** Sprint 6 (first sprint of Phase 3 dev-handoff extension; starts immediately after v1.0.1 tag).
**Tag target:** No sprint-end tag. Sprint 6 is kick-off work — plan doc + first real skill + four scaffolds + composite command + workflow-contract update. The next tag (`v1.1.0`) ships at Sprint 9 close when the remaining four Phase-3 skills implement for real.
**Canon policy version at Sprint 6 close:** `1.0.1+hash:76ef3c0a` — hash advanced twice during Sprint 6 (Phase-3 scaffolding added 5 new SKILL.md files to POLICY_GLOBS → `65a577fd` → `139a17e7`; workflow-contract.md edit with Phase-3 section → `76ef3c0a`). Semver unchanged (`1.0.1` — patch line — because no user-facing feature ships until Phase-3 skills implement). Full string: `1.0.1+hash:76ef3c0a7847284930d9bf215b6c54cf405d3385fb3ec6a399851d8fe8baa92d`.

## What was delivered

| User story | Status | Commit(s) | Review rounds |
|---|---|---|---|
| US-S6-01 — Phase-3 plan doc + A62 schema + `bsa-nfr-collector` full end-to-end | done | `f8d508b` | 0 (self-reviewed; Codex review scheduled before Sprint 7 work starts) |
| US-S6-02 — Scaffold commits for 4 Phase-3 skills (story-writer, test-scenario-builder, traceability-matrix, backlog-bridge) | done | `f8d508b` | 0 |
| US-S6-03 — `commands/bsa-dev-handoff.md` composite command | done | `b24791f` | 0 |
| US-S6-04 — `workflow-contract.md` Phase-3 Dev-Handoff Extension section | done | `b24791f` | 0 |

Plus: `docs/retros/sprint_6.md` (this file).

## Acceptance criteria coverage

**US-S6-01** (5 ACs):
- AC-1: PASS — `docs/phase_3_plan.md` authored with concrete US breakdown across Sprints 6-9, four new canonical artifacts (A62/A70/A71/A72), three new invariants (INV-08/INV-09/INV-10), dependencies, risks, release target.
- AC-2: PASS — `governance/schemas/a62.schema.json` authored. 9-value NFRCategory enum (ISO/IEC 25010-aligned). `x-bsa-measurability-rules` extension declares INV-09 (performance/availability/scalability require Metric+Target). Full row schema: 11 columns, required subset consistent with canonical column order.
- AC-3: PASS — `skills/bsa-nfr-collector/SKILL.md` authored end-to-end (scope, inputs, outputs, workflow, invariants, failure modes, cross-refs). `references/nfr-extraction-contract.md` authored with category taxonomy + 7 derivation rules + report shape + acceptance criteria.
- AC-4: PASS — `governance/schemas/loader.py` gains `iter_a62_rows(path)`. `governance/schemas/write_validator.py` `_DISPATCHER` table gains A62 entry. F5 hook mechanically enforces A62 schema from day one (direct payoff of doing F5 before Phase 3).
- AC-5: PASS — 27 new schema-conformance tests in `tests/test_schemas_a62.py`: meta-validity, all 9 categories accepted, category-prefixed NFRID accepted, multi-source claims accepted, qualitative with empty Metric/Target accepted, 8 negative cases including "missing SourceClaimIDs" (INV-08 guard), "drift category", "empty statement/testability", F5 dispatcher + valid/invalid content integration.

**US-S6-02** (4 ACs — one per scaffold skill):
- AC-1: PASS — `skills/bsa-story-writer/SKILL.md` + `references/` directory. Frontmatter compliant, skill-lint passes. TODO anchors: `[TODO-S7-02-A70-SCHEMA]`, `[TODO-S7-02-INVEST]`, `[TODO-S7-02-NO-NEW-STORIES-AUDITOR]`, plus workflow-step-level TODOs.
- AC-2: PASS — `skills/bsa-test-scenario-builder/SKILL.md` + `references/`. TODO anchors: `[TODO-S8-01-A71-SCHEMA]`, `[TODO-S8-01-GHERKIN]`, `[TODO-S8-01-NFR-COVERAGE]`, `[TODO-S8-01-RUNNABLE-EXPORT]`.
- AC-3: PASS — `skills/bsa-traceability-matrix/SKILL.md` + `references/`. TODO anchors: `[TODO-S8-02-A72-SCHEMA]`, `[TODO-S8-02-ORPHAN-DETECTION]`, `[TODO-S8-02-COVERAGE-METRICS]`, `[TODO-S8-02-LINK-TYPE-ENUM]`.
- AC-4: PASS — `skills/bsa-backlog-bridge/SKILL.md` + `references/`. TODO anchors: `[TODO-S9-01-JIRA-JSON]`, `[TODO-S9-02-LINEAR-CSV]`, `[TODO-S9-03-GENERIC-CSV]`, `[TODO-S9-04-IDEMPOTENCY]`, `[TODO-S9-RELEASE-NOTES]`.

All four scaffolds pass `scripts/validate_skill_structure.py` (28/28 skill-lint at Sprint 6 close, up from 23/23 before Phase 3).

**US-S6-03** (3 ACs):
- AC-1: PASS — `commands/bsa-dev-handoff.md` frontmatter + usage + prerequisites + full workflow description + per-skill marker documentation + failure-mode list.
- AC-2: PASS — partial-run support (`--only=<skill>`) with explicit prerequisite table per variant. Enables debugging / retry of individual Phase-3 skills without re-running upstream work.
- AC-3: PASS — platform-choice flag (`--platform=<jira|linear|generic|all>`) for backlog-bridge output. Default `all` emits all three formats.

**US-S6-04** (2 ACs):
- AC-1: PASS — `skills/bsa-orchestrator/references/workflow-contract.md` "Execution Paths" section gained step 10 (Phase 3 optional) in both with-discovery and without-discovery variants.
- AC-2: PASS — new "Phase 3 Dev-Handoff Extension (Sprint 6+)" section with a 5-row table (phase3.nfr → phase3.backlog_exported) listing owning skill + required marker + artifact promoted. Notes on future INV-08/09/10 landing at v1.1.0 + F5 automatic enforcement for Phase-3 artifacts as their schemas land.

## Tests / verification snapshot

- **912 passed** at Sprint-6 close (885 at Sprint 5 end + 27 new A62 tests in Sprint 6 US-S6-01).
- All 28 SKILL.md files pass skill-lint (23 baseline + 5 Phase-3 skills).
- Canon hash drift test green: plugin.json `hash_full` matches `compute_canon_hash.py` output.

## Scope decisions / what's intentionally deferred

- **Phase-3 marker alphabet in marker.schema.json** — `phase3.nfr.pass`, `phase3.story.pass`, `phase3.test_scenario.pass`, `phase3.traceability.pass`, `phase3.backlog_exported`, `pipeline.phase3.complete` — deferred. Each lands with its owning sprint's skill implementation. At Sprint 6 close, only bsa-nfr-collector would actually emit a marker (phase3.nfr.pass), but orchestrator emission path goes via proposals first, which F5 doesn't gate on — so the schema entry is a one-line change at the start of Sprint 7 when bsa-nfr-collector is exercised against a live workspace.

- **Manifest `version` field bump** — stays at `1.0.0` through Sprint 6. Bump to `1.1.0` lands at Sprint 9 close with the full Phase-3 feature release. Intermediate sprints carry the work under `canonPolicyVersion.semver` advancement but not SemVer bumps (standard "work in progress toward next minor" convention).

- **A70/A71/A72 schemas** — each schema lands at the start of its owning sprint (Sprint 7 for A70, Sprint 8 for A71/A72). Authoring them eagerly in Sprint 6 would be speculative — the skill workflow + consumer-skill dependencies shape the schema, and those aren't fully locked until the owning skill is implemented.

- **Test-scenario notation** — Gherkin Given-When-Then is the obvious default (per the scaffold) but the specific dialect (Cucumber? pytest-bdd?) is not yet chosen. `[TODO-S8-01-GHERKIN]` + `[TODO-S8-01-RUNNABLE-EXPORT]` in the test-scenario-builder scaffold flag this for Sprint 8 decision.

## Lessons

- **Scaffold-plus-one pattern works for Phase kick-offs.** Landing one skill end-to-end (`bsa-nfr-collector`) plus four well-anchored scaffolds gave a stable interface for the composite command (US-S6-03) to reference without committing to undelivered behavior. The four scaffold SKILL.md files pass skill-lint so they live alongside real skills without skill-set quality degradation.

- **F5 payoff realized immediately.** A62 schema-conformance was enforced at the hook layer the moment the schema landed + dispatcher entry was added — no new hook code needed. This is the direct Sprint-5 foundation dividend: every new Phase-3 schema gets mechanical enforcement for free. Story-writer (Sprint 7) + test-scenario-builder (Sprint 8) + traceability-matrix (Sprint 8) will each get the same treatment when their schemas land.

- **POLICY_GLOBS maintenance is cheap if tested.** The `test_every_skill_md_is_in_policy_globs` guard caught the 5 missing SKILL.md files on first run, forcing the additions into compute_canon_hash.py before commit. Without that test, canon hash would silently not have reflected the Phase-3 skill state — exactly the class of drift the hash is supposed to prevent.

## What's still open (carries into Sprint 7)

- US-S7-01 — `governance/schemas/a70.schema.json`.
- US-S7-02 — `bsa-story-writer` real implementation (replacing the scaffold).
- US-S7-03 — no-new-stories auditor pattern (mirror of no-new-claims).
- Phase-3 marker alphabet: add `phase3.nfr.pass` to marker.schema.json when bsa-nfr-collector runs end-to-end in a Sprint-7-era live test or first Phase-2.5 engagement.

## Related

- Sprint 5 close: `v1.0.1` tag on commit `8d4692a`, retro `docs/retros/sprint_5.md`.
- Sprint 6 commits: `f8d508b` (kick-off) + `b24791f` (command + workflow-contract).
- Phase 3 plan: `docs/phase_3_plan.md`.
- Target release: `v1.1.0` at Sprint 9 close.
