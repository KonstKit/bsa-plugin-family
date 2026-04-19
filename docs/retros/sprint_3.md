# Sprint 3 Retrospective — P0 Stabilization Close

**Window:** Sprint 3 (weeks 8-9 of the 12-week Phase 0-2 roadmap).
**Tag target:** `v1.0.0-rc1` (created on HEAD once this retro commit is codex-approved — Sprint 3 closes the last batch of Phase-1 P0 blockers: sidecar self-description, discovery→main merge/dedup, ReliabilityTier operationalization, drift detection + CanonPolicyVersion hash, marker-chain validator, prompt-injection regression baseline).
**Canon policy version:** `1.0.0-rc1+hash:ac039430` — the `ac039430...` prefix is the SHA-256 digest computed by `scripts/compute_canon_hash.py` over all policy files at retro time. First Sprint to ship the hash form alongside the semver.

## What was delivered

| User story | Status | Commit(s) | Review rounds |
|---|---|---|---|
| US-S3-01 — sidecar self-description (C4 + BPMN Integration Contract sections + anchor_manifest JSON Schemas) | done | `1472ef5` + `67f9b3e` + `0d7ee11` | 3 |
| US-S3-02 — discovery→main merge/dedup contract + merge_log JSON Schema | done | `c89496d` + `1f7858d` | 2 |
| US-S3-03 — ReliabilityTier operationalization (5 tiers + independence + conflict resolution + weighted KPI-001 + EpistemicInsufficiency) | done | `f2ecdad` + `f5ceabe` | 2 |
| US-S3-04 — drift detection rules + CanonPolicyVersion hash + `compute_canon_hash.py` + marker schema extension | done | `19962f4` + `675def2` | 2 |
| US-S3-05 — marker chain validator + CI wiring | done | `7c60093` | 1 |
| US-S3-06 — prompt-injection adversarial fixture (`adversarial_prompt_injection_001`) | done | `a0646a0` | 1 |

Plus: `docs/retros/sprint_3.md` (this file) + `v1.0.0-rc1` git tag (pending).

## Acceptance criteria coverage

**US-S3-01 (4 ACs):**
- AC-1..AC-4: PASS — Integration Contract sections in both sidecar SKILL.md files; `references/integration-contract.md` with operating modes (orchestrated vs standalone) + anchor manifest schema + failure mode matrix; `references/anchor_manifest.schema.json` (JSON Schema 2020-12) with full enums covering every documented macro/element kind; doc-driven superset tests ensure future reference-doc additions don't silently escape schema coverage.

**US-S3-02 (5 ACs):**
- AC-1..AC-5: PASS — `discovery_to_main_merge.md` defines disjoint namespaces (D-C-* vs C-*), source dedup by identity tuple, excerpt dedup by (SourceID, Locator), A58 carry-forward with `Provenance=discovery-promoted` column, A59 claim lineage with `DiscoveryLineage` column, 8-event merge_log with conditional required fields via JSON Schema `allOf`/`if`/`then`. Four new SCN-ORCH-001-C-MERGE-A..D scenarios added. Schema round-trip test exercises line-by-line JSONL validation.

**US-S3-03 (8 ACs):**
- AC-1..AC-6: PASS in spec + skill updates — 5-tier model (T1=1.00 / T2=0.85 / T3=0.65 / T4=0.45 / T5=0.20) with NIST SP 800-53 + CMMI-style rationale, 2-of-4 independence definition, conflict resolution (tier-delta ≥ 2 higher-wins + SupersededBy / ≤ 1 contested + auto-A51 cross_tier_contradiction / anecdotal never overrides), ClaimStrength formula with decay hook, KPI-001 rewritten as weighted coverage (target bumped from 0.90 unweighted to 0.75 weighted), citation auditor gets 4 EpistemicInsufficiency sub-types (low_tier_only, not_independent, anecdotal_only, judgment_on_low_tier).
- AC-7 / AC-8: PASS via executable fixture-as-test. `tests/test_tier_conflict_scenarios.py` ships a 12-case reference implementation of conflict resolution and epistemic sufficiency rules — the future orchestrator runtime is expected to produce identical outcomes on identical inputs. Full-pipeline adversarial fixtures are scoped to Sprint 4.5 per commit-message acknowledgement.
- Fixture `project_0001` updated: S-001 promoted T3 → T2 with credible rationale; direct-claim ClaimStrength 0.65 → 0.85; H3 KPI scorecard updated (0.82 unweighted → 0.85 weighted) with new per-tier breakdown section.

**US-S3-04 (7 ACs):**
- AC-1..AC-4: PASS — anchor-audit-contract.md defines three drift sub-types (`semantic_rename_no_pivot`, `semantic_change_no_claim`, `class_change_no_pivot`) with detection heuristics, report JSON shape, and A51 `boundary_risk` + hard BlockingStatus gate. Adversarial fixture (full drift detection run) is Sprint-4+ scope per plan.
- AC-5: PASS — `CanonPolicyVersion` accepts both bare semver (pre-Sprint-3) and `<semver>+hash:<sha256>` form (Sprint-3+). Bump rules explicitly documented.
- AC-6: PASS — all 4 fixture markers now carry `canon_policy_version_hash=ac039430` (8-char prefix); marker-schema reference doc defines the field as required for Sprint-3+ markers, optional for pre-v1.0 workspaces.
- AC-7: PASS — `scripts/compute_canon_hash.py` outputs aggregate hash + per-file breakdown (`--full`) + category-level breakdown (`--diff-breakdown`) covering 5 policy-file buckets. POLICY_GLOBS spans all 23 committed SKILL.md + every orchestrator reference + per-skill policy references + both sidecar contracts + governance + sem_audit_rename (59 entries).

**US-S3-05 (6 ACs):**
- AC-1..AC-6: PASS — `scripts/validate_marker_chain.py` enforces prefix/gap/duplicate/timestamp-monotonicity/version-hash-consistency across main-cycle and discovery chains. 14 tests cover baseline pass, every failure mode, and edge cases (empty workspace, pre-hash markers, discovery-only chain). CI wires it as a blocking step. Three previously-missing project_0001 middle-stage markers (stage5/6/7) added to close the chain.

**US-S3-06 (5 ACs):**
- AC-1..AC-5: PASS — `adversarial_prompt_injection_001` fixture with 3 injection vectors (ignore-previous-instructions, delimiter-escape with fake YAML frontmatter, tool-use injection in transcript), full canonical A50/A58/A59/A60/A51 showing T5 + anecdotal=true sources + CLASSIFY claims (no verbatim injection content as system claim) + A51 boundary_risk routes. Hand-authored `prompt_injection_audit_report.md` records the mapping. README covers what each injection attempts, expected pipeline handling, synthetic-vs-live-run contrast, Phase 3 hook.

## Metrics

- **Tests:** 671 total (was 557 at Sprint 2 close). +114 in Sprint 3 across: sidecar anchor manifest schemas (+26 after round-2 doc-driven parsing), merge log schema (+22), ReliabilityTier propagation (+5) + tier conflict scenarios (+12), canon hash (+12 after round-1 category breakdown), marker chain validator (+14). Runtime: ~100s on Python 3.9.6.
- **Commits:** 11 approved in Sprint 3 (6 feat + 5 fix). Plus this retro commit.
- **Review rounds:** 11 total across the 6 stories. US-S3-01 needed 3 rounds (enum completeness under escalating pressure); US-S3-02 through US-S3-04 needed 2 rounds each; US-S3-05 and US-S3-06 passed on round 1.
- **Lines of committed changes:** ~4200 (3 new reference docs, 2 new JSON Schemas, 3 new scripts, 7 new test files, fixture updates, sprint retro).

## What went well

- **Doc-driven superset tests as a pattern.** The round-2 finding on US-S3-01 — that hardcoded `documented = {...}` constants in tests don't catch doc-to-schema drift — crystallized a pattern now replicated across the sprint. `test_sidecar_anchor_manifest_schema.py` parses `c4-plantuml-syntax.md` and `support-matrix.md` at test time; `test_reliability_tier_propagation.py` parses `reliability_tier_spec.md` for tier weights; `test_every_skill_md_is_in_policy_globs` enumerates the `skills/` directory. Each test closes the "contract says X, code says Y" gap that hardcoded constants can't.
- **Executable fixture-as-test.** For US-S3-03 AC-7/AC-8, rather than author a full Sprint-4.5-scale pipeline fixture for conflict resolution and epistemic sufficiency, `test_tier_conflict_scenarios.py` ships a 12-case reference implementation of the rules. Future orchestrator runtime is required to produce identical outcomes. This is testable contract — cheaper than a pipeline fixture and more rigorous than markdown-only specs.
- **CanonPolicyVersion hash as a drift forcing-function.** US-S3-04's `compute_canon_hash.py` turns "did this commit touch policy?" from a human judgment call into a deterministic SHA-256 comparison. The per-category breakdown (`--diff-breakdown`) narrows where a bump originated (was it governance? orchestrator? per-skill refs?), which will be valuable during Sprint 4+ deprecation windows.
- **Marker chain validator as a separate gate.** US-S3-05's `validate_marker_chain.py` decouples chain integrity from per-stage auditors. Adding it as a CI blocker caught an existing fixture gap (project_0001 missed stage5/6/7 markers) that none of the stage-level auditors had flagged. Separation-of-concerns paying dividends.

## What was harder than expected

- **Policy-scope definition is a judgment call.** US-S3-04 round 1 rejected the canon-hash script because POLICY_GLOBS didn't include every SKILL.md — the docstring promised completeness, the list delivered a subset. The resolution was "enumerate explicitly, doc-drive the test" (see `test_every_skill_md_is_in_policy_globs`). Lesson: any "policy file list" must be auto-validated by a doc-driven test the moment it's authored, never relied on via code review alone.
- **Contract layer vs runtime layer lines.** US-S3-03 review round 1 flagged AC-7/AC-8 fixtures as not delivered even though the commit had the spec text and rules. The distinction I missed: AC-7/AC-8 literally say "fixture demonstrates" — markdown alone doesn't demonstrate, it describes. Executable tests (or real pipeline outputs) are the only things that demonstrate. Fixed by the reference-implementation test file, but next sprint I should check AC text for "demonstrate / produce / generate" phrases up front and plan executable coverage.
- **Timestamp monotonicity cascading into fixture edits.** Adding stage5/6/7 markers to project_0001 required timestamps between stage3 (Feb 21 09:00) and stage8 (Feb 22 15:00). Narrow window; I had to pick plausible times (Feb 21 14:00, Feb 22 09:00, Feb 22 13:30) that preserve ordering. A more realistic fixture would run across multiple days — revisit in Sprint 4.5 when live-run fixtures land.

## Carry-over into Sprint 4

Sprint 4 pivots from contract work (Phase 1) to packaging (Phase 2 MVP):

- **US-S4-01 (plugin MVP core):** plugin.json manifest + `.claude-plugin/` structure. Plugin-API spike at AC-0 is mandatory prerequisite — answer whether custom fields like `canonPolicyVersion` are allowed or must live in a separate config.
- **US-S4-02..US-S4-04:** slash commands (`/bsa start`, `/bsa status`, etc.), hooks (SessionStart + PreToolUse), install/uninstall flow.
- Sprint 4.5 fills expected_outputs on `project_0002`, authors `project_0003`, writes user-facing docs, cuts v1.0.0.

## Canon hash breakdown at Sprint 3 close

```
aggregate:                ac039430bdffdaf66c75107c1792aa71f8bd077c8f1da4f76844cc6b50a4a6f1
governance:               2086a86d27bf01b0935a61504dbd928c0aa5443b67fa3548008763ee01033597  (n=1)
skills_skill_md:          80698e867fd48feee9bc62ec75e1dda200074a13ae743a7acf840770809fed31  (n=23)
orchestrator_references:  12262c7fb8522746d38aff8d94a87132c45429fbd68cd4c765813dc943ac11a2  (n=15)
per_skill_references:     5d08c9bf3504c9bb3e667f63c30da0ab313cfc193059dd721a21853eb3bd57fb  (n=19)
docs:                     eca939c115a76b5aad424ecf1b24a776cb8ceae68179f5fd2aa9c8c38198a280  (n=1)
```

## Phase 1 retrospective

Sprint 3 closes Phase 1 (P0 Stabilization). The original Phase-0 analysis identified 7 P0 blockers:

1. ~~Stage 2 runtime-native without worker-skill~~ — closed in Sprint 1 (US-S1-01 `bsa-context-framer`).
2. ~~H1-H4 packages undocumented~~ — closed in Sprint 2 (US-S2-01 H1-H4 specs + manifest schema).
3. ~~Naming debt (`no-new-facts` → `no-new-claims`)~~ — closed in Sprint 2 (US-S2-02 three-part rename + semantic audit).
4. ~~Sidecars not self-describing~~ — closed in Sprint 3 (US-S3-01 Integration Contracts).
5. ~~Discovery↔main merge/dedup contract not formalized~~ — closed in Sprint 3 (US-S3-02).
6. ~~`ReliabilityTier` declared-but-not-operationalized~~ — closed in Sprint 3 (US-S3-03).
7. ~~Drift detection in anchor auditor declared-but-not-specified~~ — closed in Sprint 3 (US-S3-04 drift rules + canon hash).

Plus two Sprint-3 additions during rev3 planning: US-S3-05 marker chain validator (covering a gap nobody had flagged as P0 but which surfaced fixture gaps once added), and US-S3-06 prompt-injection baseline (deferred from "Phase 3 security workstream" to "give future Phase 3 a positive control").

All 7 P0 blockers + 2 rev3 adds closed. Phase 2 (plugin MVP) can begin.

## Sprint 3 exit criteria

- [x] All 6 US-S3-* stories delivered with codex approval
- [x] Sidecars self-describing (AC-1..AC-4 of US-S3-01)
- [x] Discovery→main merge contract + schema + SCN scenarios
- [x] ReliabilityTier operationalized end-to-end (tier spec + claim-binder + citation auditor + weighted KPI-001 + fixture)
- [x] CanonPolicyVersion hash computable + carried in markers
- [x] Marker chain validator in CI as a blocking step
- [x] Prompt-injection regression fixture with Phase-3 hook
- [x] CanonPolicyVersion bump to `1.0.0-rc1+hash:ac039430`
- [ ] `v1.0.0-rc1` tag — to be created on the approved HEAD of this retro commit
