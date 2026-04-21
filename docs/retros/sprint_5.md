# Sprint 5 Retrospective — Contract-Enforcement Hardening

**Window:** Sprint 5 (post-v1.0.0 hardening pass; driven by Phase 2.5 engagement feedback and two external reviewer passes).
**Tag target:** `v1.0.1` (created on HEAD `8d4692a` once this retro commit is codex-approved). Sprint 5 is schema-enforcement work — canon policy files DID change (schema documents added, runtime-marker-schema.md extended with previously-missing markers), so hash moves from `cbba8e53` (v1.0.0) → `65a577fd` (Sprint 5 mid-sprint after F4a doc edit) and stays there through the end of Sprint 5 (Phase-3 scaffolding + POLICY_GLOBS additions happen AFTER v1.0.1 tag point, in Sprint 6 kick-off).
**Canon policy version:** `1.0.1+hash:65a577fd` — derived from the schema-integration edit to `runtime-marker-schema.md`.

## What was delivered

| User story | Status | Commit(s) | Review rounds |
|---|---|---|---|
| F4a — marker.schema.json foundation + loader + schema-conformance tests | done | `034ddb3` | 1 |
| F4b + F2 — A48 schema + parser (table/bullet/bold); promote-hook A48 extraction fix | done | `dd5efe8` | 1 |
| F1 — validate_marker_chain reads alphabet from schema (drops private hardcoded tuples) | done | `c7dd646` | 1 |
| F3 — privacy_scan no longer silently skips digit-free high-entropy secrets | done | `e648401` | 1 |
| F7 — /bsa-status state-aware transition notices (3 templates) | done | `9495c2b` | 0 (docs-only) |
| F4c + F4d — CSV schemas for A50/A51/A58/A59/A60 + fixture normalization | done | `12ec5e9` | 1 |
| F5 — pre_write_canonical.sh enforces schemas at write time (the Sysco-class fix) | done | `5025b2a` | 1 |
| F6 — A51 reconciliation auditor (validate_a51_reconciliation.py) | done | `d699565` | 1 |
| F5 extension — Edit-tool support in pre_write_canonical | done | `8d4692a` | 1 |

Plus: `docs/retros/sprint_5.md` (this file) + `v1.0.1` git tag (pending).

## Origin of the sprint

Two external reviewer passes landed between the v1.0.0 release and the first planned Phase 2.5 engagement:

1. **Code-review round** surfaced three P-level findings in the v1.0.0 codebase:
   - P1: `validate_marker_chain.py` rejected stage-ready / end-state / bridge markers (its private sequence set drifted from the documented alphabet).
   - P1: `hooks/pre_bash_promote.sh` silently exited code 1 on table-format A48 (grep matched only bullet-format, pipefail + set -e hid the diagnostic).
   - P2: `scripts/privacy_scan.py` had a guaranteed false-negative class — digit-free high-entropy secrets (BIP39 seed phrases, letter-only API tokens) skipped the entropy check via a mis-documented "natural prose" gate.

2. **Phase 2.5 trial engagement** (the Sysco Order&Deliver discovery-cycle run) produced `automated_results/` output that was content-rich but **schema-incompatible** at every contract surface: camelCase marker field names (`marker` / `emittedAt` / `canonPolicyVersion` instead of `marker_id` / `timestamp` / `canon_policy_version`), legacy `no_new_facts` filenames, ad-hoc ClaimType strings (`policy_statement` / `factual_state` / `process_step`), custom ReliabilityTier labels (`T1_multi_source_consistent` etc.), a 3-column A60 shape that disagreed with the documented 7-column contract. Root cause: the plugin enforced INV-02 (single-writer) mechanically via `pre_write_canonical.sh` but enforced INV-01 / INV-07 / marker-schema **rhetorically only** — skill SKILL.md files told the LLM "use these field names", the LLM drifted, no write-time gate caught it.

Both signals pointed to the same fix class: **schema-as-source-of-truth with write-time mechanical enforcement**. F4+F5 are the meat of that; F1/F2/F3 are the three reviewer-P-level follow-ons; F6 catches a related but distinct class (lifecycle-state drift between marker payloads and canonical A51); F7 is the UX papercut the engagement also surfaced.

## Acceptance criteria coverage

**F1 — validator reads alphabet from schema:**
- AC-1: PASS — `MAIN_CYCLE_SEQUENCE` + `DISCOVERY_SEQUENCE` no longer hardcoded; resolve through `governance.schemas.loader.audit_pass_sequence()` against `marker.schema.json` extension property.
- AC-2: PASS — alphabet-sync test (`test_schema_alphabet_matches_doc`) fails CI if `runtime-marker-schema.md` and `marker.schema.json` enum drift.
- AC-3: PASS — stage-ready markers (`stage1.ready` ... `stage8.ready`), end-state markers (`handoff.ready`, `pipeline.complete`), bridge marker (`bsa.stage1.entry.enabled`), and non-go discovery decisions (`discovery.pivot` / `.more_research` / `.no_go`) all pass validation as non-gating markers instead of being rejected as `chain-unknown-marker`.
- AC-4: PASS — `bsa.stage1.entry.enabled` no longer double-rejected (fix in `_split_chains` routing plus the two-tier alphabet-then-sequence check in `_validate_chain`).

**F2 — promote-hook A48 parser fix:**
- AC-1: PASS — hook no longer depends on in-bash grep for CurrentStage extraction. Delegates to `governance.schemas.loader a48-field` Python CLI.
- AC-2: PASS — all three A48 on-disk shapes parse (bullet-backtick, bullet-bold, markdown-table). Regression tests: `test_pre_bash_promote_handles_table_format_a48_*` + `test_pre_bash_promote_handles_bullet_bold_a48` + `test_pre_bash_promote_table_a48_with_real_fixture_path`.
- AC-3: PASS — hook emits structured BLOCKED stderr on any parse failure (vs pre-F2 silent exit-1).

**F3 — privacy_scan letter-only secrets:**
- AC-1: PASS — `_is_likely_natural_prose` rewritten from a digit-presence gate to a two-step decision (known-prefix gate + vowel-ratio heuristic).
- AC-2: PASS — the original P2 reproducer (`QwErTyUiOpAsDfGhJkLzXcVbNm`, H=4.70, 26 chars, letter-only) now surfaces as `api_key_token`.
- AC-3: PASS — 21 `KNOWN_TOKEN_PREFIXES` cover GitHub / Stripe / Slack / AWS / Google / JWT / GitLab / DigitalOcean / Shopify families.
- AC-4: PASS — false-positive guard: camelCase + snake_case identifiers + long English-like slugs not flagged (vowel ratio lands in 0.30..0.50 prose band).

**F4a..F4d — schema foundation:**
- AC-1: PASS — `governance/schemas/` holds 7 schemas at end-of-sprint (marker, a48, a50, a51, a58, a59, a60). Each is valid JSON Schema Draft 2020-12.
- AC-2: PASS — single loader module (`governance.schemas.loader`) with typed helpers (`iter_a50_rows` ... `iter_a60_rows`, `parse_a48`, `audit_pass_sequence`, etc.). Stdlib-only at import; `jsonschema` lazy-imported.
- AC-3: PASS — schema-conformance test suite (`tests/test_schemas_marker.py`, `test_schemas_a48.py`, `test_schemas_a51.py`, `test_schemas_csv_artifacts.py`) validates all golden fixtures against their schemas and includes negative regression guards.
- AC-4: PASS — fixture drifts surfaced during schema authoring were fixed in the same commit: verdict `"merged"` → `"MERGED"` normalization (4 fixtures), A60 3-column shape → 7-column shape (3 fixtures), runtime-marker-schema.md gained `stage1.ready` + `discovery.d{2,3,4,5}.ready` + verdict `MERGED`.
- AC-5: PASS — canon hash updated (`cbba8e53` → `65a577fd`) after the marker-schema doc edit; plugin manifest + `compute_canon_hash.py` drift test all in sync.

**F5 — pre_write_canonical schema enforcement (THE pivotal change):**
- AC-1: PASS — `governance/schemas/write_validator.py` dispatches writes to `analysis/(discovery/)?runtime/ready/*.json` and `analysis/(discovery/)?canonical/core_controls/A{48,50,51,58,59,60}_*` through the matching schema.
- AC-2: PASS — `hooks/pre_write_canonical.sh` calls the validator CLI on the proposed content after the existing INV-02 identity check. Backward compat: empty stdin → identity-only mode (pre-F5 behavior).
- AC-3: PASS — direct replays of the Sysco-engagement drift shapes are blocked: camelCase marker, legacy `discovery.d5.no_new_facts.pass.json` filename, legacy `policy_statement` ClaimType in A59, custom `T1_multi_source_consistent` tier in A50. All four bad shapes fail at the hook with structured BLOCKED stderr naming the violating field.
- AC-4: PASS — non-canonical paths (proposals, views, random files) pass unconditionally; F5 enforces only the canonical control surface, by design.
- AC-5: PASS — identity check fires BEFORE content validation. Wrong `BSA_WRITER` → INV-02 BLOCKED message; never leaks F5 schema details in that branch.
- AC-6 (F5 Edit extension): PASS — Edit-shape tool input (`old_string` / `new_string` / `replace_all`) handled. Hook reads the existing file, applies the edit via `apply_edit()`, validates the post-image. Edit-that-produces-invalid-content blocked; edit-that-produces-valid-content allowed; edit-that-is-unapplicable (old_string absent) skipped with exit 0 (letting the actual Edit tool report).

**F6 — A51 reconciliation auditor:**
- AC-1: PASS — `scripts/validate_a51_reconciliation.py` reads canonical A51 register plus marker payloads plus handoff packets; emits `A51_RECONCILE_GAP` when an A51Ref is declared remediated in markers/handoff while the register keeps `ResolutionStatus=open`.
- AC-2: PASS — `A51_RECONCILE_GHOST` finding for A51Refs claimed-resolved in markers that aren't in the register at all.
- AC-3: PASS — proximity window (200 chars) prevents false positives from unrelated "closed" mentions.
- AC-4: PASS — operator-shorthand `A51-MISS-010/011` correctly expands into both refs.
- AC-5: PASS — direct replay of the Sysco-engagement gap (discovery.go.json precondition reclassifies A51-MISS-010/011 but canonical register keeps them open) surfaces both findings.

**F7 — /bsa-status state-aware notices:**
- AC-1: PASS — three notice templates added to `commands/bsa-status.md`: `discovery-deliverable-only`, `pre-stage-ready`, `handoff-ready-not-emitted`. Each has an explicit marker-set + A48 trigger condition so the orchestrator emits deterministically.
- AC-2: PASS — the `discovery-deliverable-only` template directly addresses the Sysco UX papercut (operator reached D-Exit + bridge, no main cycle, unclear whether workspace was stuck or intentionally between cycles). Notice names both valid paths forward.

## Tests / verification snapshot

At Sprint-5 end, `python3 -m pytest -q` reports **885 passed** (730 baseline at sprint start + 155 new tests across F1/F2/F3/F4/F5/F6). Grep for Sprint-5 patterns:

- `tests/test_schemas_marker.py` — 18 tests (F4a).
- `tests/test_schemas_a48.py` — 18 tests (F4b).
- `tests/test_schemas_a51.py` — 18 tests (F4c).
- `tests/test_schemas_csv_artifacts.py` — 27 tests (F4d, parametrized over A50/A58/A59/A60).
- `tests/test_schemas_write_validator.py` — 41 tests (F5 + F5-Edit extension).
- `tests/test_validate_a51_reconciliation.py` — 9 tests (F6).
- `tests/test_validate_marker_chain.py` — +5 F1 regression tests.
- `tests/test_plugin_hooks.py` — +10 F2 regression tests + F5 integration tests.
- `tests/test_privacy_scan.py` — +6 F3 regression tests.

No pre-existing test had to be deleted or weakened. `test_scan_baseline_has_no_blockers` stayed green — privacy scan rewrite did not introduce new false positives across the live repo.

## What closed

The Sysco-engagement drift class is mechanically blocked:
- Marker field-name drift → schema enum on `marker_id` + per-field required snake_case fields; F5 hook blocks at write.
- Legacy `no_new_facts` → not in the `marker_id` enum; F5 blocks.
- Legacy `ClaimType` strings → not in the A59 enum (INV-07 closed); F5 blocks.
- Custom `ReliabilityTier` labels → not in the A50 enum; F5 blocks.
- A60 3-column shape → missing required columns; F5 blocks.
- A51 lifecycle-state divergence → detected by the F6 auditor, surfaced as findings.

Before Sprint 5, each of these was "rhetorically forbidden" via skill SKILL.md text; after Sprint 5, each is mechanically forbidden at the earliest layer. The plugin's own invariants (INV-01 evidence-binding, INV-07 ClaimType enum, marker schema) now have executable gates that match their rhetoric.

## What's still out of scope (deferred to Phase 3 / later)

1. **A61 contract-anchors schema.** No committed fixture exists for A61; without an empirical source of truth, the schema would be speculative. When the first A61 fixture lands (likely via bsa-contract-builder fixture updates in a future sprint), the schema gets authored + the F5 dispatcher entry + tests in one follow-up commit.

2. **Cross-artifact constraint enforcement at the hook layer.** INV-01 says "every positive direct/inference claim needs SourceID+ExcerptID". The per-row A59 schema catches most of that, but verifying that the referenced `S-NNN` / `E-NNN` actually exist in A50/A58 requires reading upstream files. That's the domain of `bsa-claim-binder` + `bsa-citation-auditor` (which do it today), not the write-hook.

3. **Schema-diff tooling for version upgrades.** When a schema evolves (e.g., v1 → v2 adding a new required column), workspaces produced under v1 need a migration path. Currently the migration script `scripts/migrate_v0.9_to_v1.0.py` handles one such bump manually; generalizing this is future platform work, not Sprint 5.

4. **Edit-tool's `replace_all` path in pre_write hook.** The hook's Python extraction passes `replace_all` through correctly, but the integration tests cover single-replacement only. Multi-occurrence Edit with `replace_all=True` is supported by `apply_edit()` (unit-tested) but not exercised end-to-end through the hook; extra integration test welcome in Sprint 6.

## Lessons

- **Schema-first before enforcement paid off.** F4 had to land before F5 could do anything useful. Sequencing the sprint as "all schemas first, then the hook that uses them" avoided scope thrash. The F4a → F4b → F4c+F4d → F5 order kept each commit narrow.

- **Golden fixtures need re-validation when schemas land.** Three separate fixture drifts surfaced only when `test_all_golden_fixture_rows_validate` ran for the first time: verdict case, A60 column count, A51 ID patterns. Worth keeping schema-conformance tests on golden fixtures from day one of any future schema work — they're cheap to run and catch real inconsistencies authors didn't notice.

- **Alphabet-sync tests prevent the drift recurring.** `test_schema_alphabet_matches_doc` in the marker-schema test file is the single-most-valuable pattern from this sprint: it makes a future author who adds a marker to `runtime-marker-schema.md` but forgets the schema enum fail CI instantly. The same pattern should be applied when A61 schema lands.

- **Review findings had high signal.** All three reviewer P-level issues were reproducible exactly as described (I re-ran each empirically in separate tmp workspaces before starting the fix). That's not always true; this sprint's reviewer was thorough.

- **Engagement-surfaced findings had highest signal.** The Sysco run exposed a class of problem (rhetorical-only enforcement) that neither internal review nor static analysis had flagged. Phase 2.5 pilot existing primarily as "run on real data" paid for itself on engagement #1. Future pilots likely surface similarly useful surprises.

## Policy version handling at v1.0.1

- **Semver**: `1.0.0` → `1.0.1`. Patch bump because no public API shape changed for users of v1.0.0 (same slash commands, same skill set, same canonical-artifact column headers for compliant outputs). What changed is internal discipline: the plugin now refuses to write non-conformant content that v1.0.0 would silently accept.
- **Canon hash**: `cbba8e53` (v1.0.0) → `65a577fd` (v1.0.1). The hash moves because `runtime-marker-schema.md` gained the previously-undocumented markers (`stage1.ready` + `discovery.d{2,3,4,5}.ready`) and verdict `MERGED`.
- **Backward-compat for existing workspaces**: v1.0.0-produced workspaces with the pre-hash canon version (`0.95` or `1.0.0+hash:cbba8e53`) stay valid under the chain validator's "pre-hash workspace" tolerance. Workspaces produced by Sysco-style drifting output — the thing Sprint 5 blocks — would fail at the write hook today; they'd already failed at the validators before, just silently and later.

## Related

- External reviewer transcript (code-review findings): see session notes.
- Phase 2.5 shakedown checklist: `docs/phase_2_5_shakedown.md`.
- Pre-Sprint-5 state (v1.0.0): tag `v1.0.0`.
- Post-Sprint-5 state (v1.0.1): HEAD `8d4692a` at retro emission.
- Phase 3 kick-off (Sprint 6): starts immediately after v1.0.1 tag, in commit `f8d508b` and beyond.
