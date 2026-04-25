# Releasing

Operator-facing release procedure for the BSA plugin family. v1.1.10 (Section J) — codifies the discipline that's been ad-hoc through v1.1.9 (15+ tagged releases) into a repeatable checklist.

## Two-semver convention recap

The repo uses two independent semver dimensions:

- **`.claude-plugin/plugin.json` `version`** — the plugin manifest version. Bumps ONLY when the canon-policy state changes (i.e., a file in `scripts/compute_canon_hash.py::POLICY_GLOBS` was edited). Enforced by `tests/test_plugin_manifest.py::test_manifest_version_and_canon_semver_agree` (`version` MUST equal `canonPolicyVersion.semver`).
- **Git tag `vX.Y.Z`** — operator-facing release marker. May advance independently of the manifest when the patch is operator-tooling-only (new scripts, new tests, new docs, new fixtures, anonymization, CI/CD scaffolding, packaging polish).

Examples from the v1.1.x line:

| Tag | Manifest at tag | Canon hash | Why this shape |
|---|---|---|---|
| v1.1.0 | 1.1.0 | `d449ae74` | New invariants (INV-08/09/10), SKILL.md edits → both move. |
| v1.1.1 | 1.1.1 | `a5b51af8` | A51 enum extension (`inventory_gap` + `cross_tier_contradiction` + `Severity=critical`) + cross-doc consistency edits → POLICY_GLOBS edited → both move. |
| v1.1.2 | 1.1.1 | `a5b51af8` | New `migrate_v1.0_to_v1.1.py` script → not in POLICY_GLOBS → tag bumps, manifest stays. |
| v1.1.3 | 1.1.3 | `78bac137` | Cross-artifact validator + SKILL.md TODO closures → POLICY_GLOBS edited. |
| v1.1.4 | 1.1.4 | `eefb7204` | Platform export polish + SKILL.md TODO closures → POLICY_GLOBS edited. |
| v1.1.5 | 1.1.4 | `eefb7204` | New adversarial fixtures only → not in POLICY_GLOBS. |
| v1.1.6 | 1.1.6 | `ac63a8c3` | Live API integration + SKILL.md TODO closure → POLICY_GLOBS edited. |
| v1.1.7 | 1.1.6 | `ac63a8c3` | Anonymization (text-only edits to non-POLICY_GLOBS files). |
| v1.1.8 | 1.1.6 | `ac63a8c3` | Documentation polish. |
| v1.1.9 | 1.1.6 | `ac63a8c3` | CI/CD scaffolding (`.github/`). |
| v1.1.10 | 1.1.6 | `ac63a8c3` | Distribution / packaging polish (LICENSE + manifest metadata + templates + RELEASING.md). |
| v1.1.11 | 1.1.6 | `ac63a8c3` | Security workstream (Section G) — threat model + security_audit.py + SECURITY.md. |
| v1.1.12 | 1.1.6 | `ac63a8c3` | Sidecar polish (Section I) — inventory doc + F5-boundary regression tests. |
| v1.1.13 | 1.1.6 | `ac63a8c3` | Performance / scale validation (Section F) — perf_bench.py + baseline + CI gate. |
| v1.1.14 | 1.1.6 | `ac63a8c3` | Phase 7 self-improvement loop foundation (Section D) — tunables.yaml + lint. |
| v1.1.15 | 1.1.6 | `ac63a8c3` | 2nd Pilot-1 pass operator runbook + diff helper (Section K prep). |
| v1.1.16 | 1.1.6 | `ac63a8c3` | `--strict-on-hard-a51` opt-in promote mode (Sprint 1 / T6). |
| v1.1.17 | 1.1.6 | `ac63a8c3` | Operator shell import drivers (Sprint 1 / T5) — Jira / Linear / GitHub. |
| v1.1.18 | 1.1.6 | `ac63a8c3` | Sidecar common config schema + registry (Sprint 1 / S1+S2). |
| v1.1.19 | 1.1.6 | `ac63a8c3` | Anonymization regression test (Sprint 1 / H4). |
| v1.2.0 | 1.2.0 | `5d8ae8b6` | First canon bump since v1.1.6 — added one-line cross-ref `governance/immutable_invariants.md` → `docs/phase_7_design.md` (H2). Establishes the v1.2.x line; manifest version + canon hash both move. |
| v1.2.1 | 1.2.1 | `6821009d` | A51 IssueType enum extension `link_strength_override` (T2; closes TODO-S8-02-LINK-STRENGTH-OVERRIDE). Schema + shared-control-surface-contracts.md + bsa-traceability-matrix SKILL.md updated in lockstep. |
| v1.2.2 | 1.2.2 | `66e2004f` | A72 incremental-diff helper (T1; closes TODO-S8-02-INCREMENTAL-MATRIX). New `scripts/a72_incremental_diff.py` + operator-side cache at `analysis/canonical/.a72_incremental_state.json` (non-canonical). bsa-traceability-matrix SKILL.md edited → canon hash bumps. |
| v1.2.3 | 1.2.3 | `f4ac1767` | A71 runnable test export (T3; closes TODO-S8-01-RUNNABLE-EXPORT). New `scripts/a71_runnable_export.py` emits Cucumber `.feature` / pytest-bdd / jest-cucumber artifacts. bsa-test-scenario-builder SKILL.md edited (round-1 closure + round-2 wording fix) → canon hash bumps. |
| v1.2.4 | 1.2.3 | `f4ac1767` | Phase 7 telemetry foundation L1a (P1+P2): `governance/schemas/telemetry_run.schema.json` + `scripts/phase_7_telemetry_collector.py` (KPI-001 + KPI-006 capture; null-on-missing-upstream). Schema + script + tests + design-doc edits all outside POLICY_GLOBS — canon-neutral, manifest stays at 1.2.3. |
| v1.2.5 | 1.2.5 | `0eb4093d` | A70 negative-path scenario suggestions (T4; closes TODO-S8-01-NEGATIVE-PATH-HEURISTICS). New `scripts/suggest_negative_path_scenarios.py` (stdlib-only) scans A70 AcceptanceCriteria for three measurable-language pattern classes (temporal / boundary / comparison) + emits per-story boundary + off-by-one suggestions to `analysis/handoff/negative_path_suggestions.md` (NOT canonical). bsa-test-scenario-builder SKILL.md TODO entry closed → canon hash bumps. |
| v1.2.6 | 1.2.5 | `0eb4093d` | End-to-end sidecar fixture (S3; closes the open follow-up at `docs/sidecar_inventory.md`). New `fixtures/golden/project_0004_sidecar_e2e/` (5 C4 anchors + 5 BPMN anchors sharing one A61 register) + `tests/test_sidecar_e2e_fixture.py` (16 tests: schema validity per sidecar + cross-ref to A61 + view-element-id-in-manifest checks + 3 negative-path pins). Fixture + test + sidecar-inventory doc edit all outside POLICY_GLOBS — canon-neutral, manifest stays at 1.2.5. |
| v1.2.7 | 1.2.5 | `0eb4093d` | A61 schema formalization (closes the v1.2.6 sidecar-e2e fixture's documented forward-looking gap). New `governance/schemas/a61.schema.json` (Draft 2020-12) + `iter_a61_rows()` in loader + dispatcher entry in write_validator + `tests/test_schemas_a61.py` (44 tests). Pre-v1.2.7 A61 writes were silently allowed at the F5 hook layer; post-v1.2.7 every A61 row is row-shape-validated. Schema + loader + dispatcher + tests all outside POLICY_GLOBS — canon-neutral, manifest stays at 1.2.5. |
| v1.2.8 | 1.2.5 | `0eb4093d` | A61 cross-row enforcement at F5 hook (closes the two v1.2.7 deferrals). New `x-bsa-anchor-binding-rules` extension on `a61.schema.json` (FK SourceClaimID → A59.ClaimID + AnchorID uniqueness across rows) + `_apply_anchor_binding_rules()` handler in write_validator (cross-row, runs once after the per-row loop) + 9 new tests. Schema + handler + tests all outside POLICY_GLOBS — canon-neutral, manifest stays at 1.2.5. |
| v1.2.9 | 1.2.9 | `4548551b` | C4 relationship `view_element_id` convention (closes the v1.2.6 round-1 scope-down). New §"Relationship view_element_id convention" in `skills/c4-plantuml-from-context/references/integration-contract.md` documents the deterministic `rel_<from>_<connector>_<to>` derivation (connectors: `to`/`bi`/`idx_to` for Rel/BiRel/RelIndex) + `__N` suffix for multi-occurrence same-pair. Fixture extended with 2 Rel anchors; e2e loader extended via `_derive_c4_relationship_ids`; 10 new convention tests. Integration contract is in POLICY_GLOBS → canon hash bumps (first canon-bumping release since v1.2.5). |
| v1.2.10 | 1.2.9 | `4548551b` | Generic cross-row uniqueness extension (extracts A61's logic). New `x-bsa-uniqueness-rules` schema extension + `_apply_uniqueness_rules` handler; `_check_unique_columns` shared helper. A61's `_apply_anchor_binding_rules` refactored to delegate uniqueness — byte-identical behavior preserved. 17 new tests in `tests/test_schemas_uniqueness_rules.py`. Unblocks v1.2.12 (implicit row-identifier FK + uniqueness backfill on A50/A58/A59/A60/A62/A70/A71/A72). Handler + tests outside POLICY_GLOBS — canon-neutral, manifest stays at 1.2.9. |
| v1.2.11 | 1.2.11 | `6d91f10e` | Third BSA sidecar: `dbml-from-context` (relational-schema text). New skill directory with SKILL.md + integration-contract.md + anchor_manifest.schema.json + dbml-syntax.md + minimal validator (validate_dbml.py, +17 tests) + registry entry (status=experimental). Fixture extended with 10 DBML anchors (2 tables + 6 cols + 1 ref + 1 enum) + DBML view + DBML manifest. 3-way cross-sidecar partition verified. Half-closes the pre-v1.2.11 open follow-up at `docs/sidecar_inventory.md` (sequence-diagram sidecar remains deferred). Canon-bumping via 3 new POLICY_GLOBS paths. |
| v1.2.12 | 1.2.11 | `6d91f10e` | Cross-row uniqueness backfill on all canonical CSV schemas. `x-bsa-uniqueness-rules` extension (v1.2.10) added to A50/A51/A58/A59/A60/A62/A70/A71/A72 pinning each row-identifier column (SourceID/A51Ref/ExcerptID/ClaimID/NegEvID/NFRID/StoryID/ScenarioID/TraceID). A61 intentionally retains `x-bsa-anchor-binding-rules` (FK + uniqueness bundled). 19 new tests (parameterized static + dispatcher-path pins). Schema edits outside POLICY_GLOBS — canon-neutral, manifest stays at 1.2.11. |
| v1.2.13 | 1.2.11 | `6d91f10e` | FK cross-artifact backfill on 6 canonical CSV schemas. New generic `x-bsa-foreign-key-refs` extension (schema-agnostic, parallel to A72's A72-specific `x-bsa-foreign-key-rules`) + `_apply_foreign_key_refs` handler. 15 FK references opted in across A58/A59/A60/A62/A70/A71 covering SourceID → A50, ExcerptID → A58, RelatedClaimID → A59, SourceClaimIDs (multi) → A59, RelatedNFRIDs (multi) → A62, SourceStoryID → A70, RelatedNFRID → A62, A51Ref → A51. A72 intentionally keeps its A72-specific extension (claim_source_consistency); A61 keeps anchor-binding. 23 new tests. Schema edits outside POLICY_GLOBS — canon-neutral, manifest stays at 1.2.11. |

## Pre-release checklist

Run BEFORE creating the release commit:

1. **Local validation gates** (same as the `pre-commit` checklist in [CONTRIBUTING.md](../CONTRIBUTING.md)):
   ```bash
   python3 -m pytest -q
   python3 scripts/fixture_runner.py --all --mode=validate
   python3 scripts/privacy_scan.py
   python3 scripts/compute_canon_hash.py
   ```
   The first three must exit 0; the fourth must match `.claude-plugin/plugin.json` `canonPolicyVersion.hash_full`.

2. **Decide the tag-vs-manifest pattern**. Use the table above as reference:
   - **Manifest moves** when ANY POLICY_GLOBS file changed (run `python3 scripts/compute_canon_hash.py --diff-against <prior_hash>` to confirm).
   - **Manifest stays** when only `scripts/`, `tests/`, `docs/`, `fixtures/`, `.github/`, `migrations/`, `CHANGELOG.md`, `CONTRIBUTING.md`, `INSTALL.md`, `LICENSE`, `README.md` were touched.

3. **Update `CHANGELOG.md`** with a new top-level entry of the form:
   ```markdown
   ## [vX.Y.Z] — YYYY-MM-DD

   **One-sentence summary.**

   **Tag target**: this commit (the vX.Y.Z <description>).
   **Canon policy version**: `<manifest-semver>+hash:<hash-prefix>` — <unchanged | moved from prior>.

   ### Added | Changed | Updated | Round-N Codex review hardening | Carried forward (deferred)
   ```

4. **Codex review**. Run `codex exec -s read-only` against the staged diff. For substantial patches, expect 2-5 rounds. Final commit happens only after the latest round returns APPROVE.

5. **Verify** the release workflow trigger pattern (`.github/workflows/release.yml`) would match the planned tag. The smoke test `tests/test_ci_workflows.py::test_release_yml_only_triggers_on_version_tags` enforces this with `fnmatch` against real tag shapes.

## Release commit + tag

```bash
# 1. Stage everything.
git add -A

# 2. Commit with a release(vX.Y.Z) prefix.
git commit -m "$(cat <<'EOF'
release(vX.Y.Z): <one-line summary>

<body — what changed, Codex review summary, manifest-vs-tag note,
   carried-forward items, test count delta>
EOF
)"

# 3. Tag the commit.
git tag -a vX.Y.Z -m "vX.Y.Z — <one-line summary>. <round count> Codex rounds. Canon hash <hash-prefix>."

# 4. Verify the tag list.
git tag -l "v1.1*"   # or whatever the current line is
```

## Post-release (when the repo is on a public remote)

`.github/workflows/release.yml` runs automatically on `vX.Y.Z` tag push:

1. Verifies `CHANGELOG.md` has a matching `## [vX.Y.Z]` entry (catches the case where the maintainer tags before updating CHANGELOG).
2. Re-runs pytest / privacy-scan / canon-hash / manifest-version-vs-semver gates.
3. Builds `dist/bsa-full-vX.Y.Z.tar.gz` (excludes `.git`, `.github`, `tests`, `requirements-dev.txt`, cache dirs) and uploads it as a 90-day-retention artifact.
4. The maintainer can then attach the tarball to a GitHub Release page if desired.

## Release tarball verification

Before publishing the tarball as a downloadable release artifact, verify it:

```bash
# (a) Tar contents — should include the installable plugin tree.
tar tzf dist/bsa-full-vX.Y.Z.tar.gz | head -30

# (b) MUST include:
#     .claude-plugin/plugin.json
#     commands/*.md (6 files + bsa-dev-handoff.md = 7)
#     hooks/{hooks.json, pre_write_canonical.sh}
#     skills/<28 dirs>/SKILL.md
#     scripts/*.py
#     fixtures/golden/<8 dirs>/
#     governance/{immutable_invariants.md, schemas/}
#     migrations/{v0.9_to_v1.0/, v1.0_to_v1.1/}
#     docs/*.md
#     CHANGELOG.md, CONTRIBUTING.md, INSTALL.md, LICENSE, README.md

# (c) MUST NOT include:
#     .git*
#     .github*
#     tests/
#     requirements-dev.txt
#     __pycache__, .pytest_cache, dist/

# (d) Privacy scan against the extracted tree (defense-in-depth — should
#     mirror the in-repo privacy_scan result).
mkdir -p /tmp/release-verify
tar xzf dist/bsa-full-vX.Y.Z.tar.gz -C /tmp/release-verify
cd /tmp/release-verify && python3 scripts/privacy_scan.py
```

## Rollback procedure

If a release ships with a defect found post-tag:

1. **Don't delete the bad tag.** Tags are immutable history. If something is broken, ship a hotfix patch on top.
2. **Hotfix branch from the bad tag** (only if the bad tag is in production use; otherwise just patch on `main`):
   ```bash
   git checkout -b release/X.Y.x vX.Y.Z
   # apply the fix
   git commit -m "fix(release-X.Y.x): <description>"
   git tag -a vX.Y.Z+1 -m "vX.Y.Z+1 — hotfix for vX.Y.Z (<description>)"
   git checkout main && git merge release/X.Y.x
   git branch -D release/X.Y.x   # delete after cherry-pick is complete
   ```
3. **Document the hotfix** in CHANGELOG.md with a new `## [vX.Y.Z+1]` entry referencing the bad tag and explaining the fix.

## Marketplace publication (future / Phase 8 candidate)

The plugin currently installs from a local checkout (`/plugin marketplace add /path/to/repo`). Marketplace publication (Anthropic's plugin marketplace, when public) is a Phase 8 deliverable per `docs/phase_3_plan.md`. Until then:

- Operators install from a local clone of the public GitHub repo (when the repo lands on GitHub).
- Tarball artifacts from `.github/workflows/release.yml` runs are downloadable from the GitHub Releases page (operator extracts then `claude --plugin-dir <extracted-path>`).
- No PyPI / npm / Homebrew shipping today; the plugin is Claude-Code-native and doesn't fit those distribution surfaces.
