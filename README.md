# BSA Plugin Family

**Local-only, solo-maintainer tool.** Evidence-first BA/SA analytical pipeline packaged as a Claude Code plugin. Anti-hallucination gates, claim-binding traceability, two-key promotion, and artifact-first governance. Not published to any public marketplace; installed from a local checkout.

## Install

```
/plugin marketplace add /Users/kkitanin/projects/bsa-plugin-family
/plugin install bsa-full@bsa-marketplace
/plugin list       # expect bsa-full@1.2.9 (v1.2.x line; manifest may lag git tag during canon-neutral patch releases)
```

Full install / uninstall / upgrade (including session-only `claude --plugin-dir` path): [INSTALL.md](INSTALL.md).

## 30-second tour

```
cd /tmp/my-engagement
/bsa-start --mode=direct
# drop your sources under analysis/proposals/stage1/inputs/
/bsa-stage 1          # runs bsa-evidence-intake + bsa-claim-binder
/bsa-promote
/bsa-stage 2          # runs bsa-context-framer
/bsa-promote
# ... Stages 3-8 (each with its own worker chain + in-stage audits) ...
/bsa-handoff          # H1-H4 pack
/bsa-dev-handoff      # Phase 3: NFRs + stories + test scenarios + traceability + backlog export
```

Each `/bsa-stage N` invocation runs the stage's full worker chain (worker + any in-stage auditor) per the routing manifest. The standalone `/bsa-audit <kind>` command is only needed to re-run a specific audit against current proposals. Full walkthrough + discovery mode: [docs/getting_started.md](docs/getting_started.md).

## Status

**v1.2.9** — current release. v1.2.x line progression: v1.2.0 (first canon bump since v1.1.6 — one-line cross-ref), v1.2.1 (A51 `link_strength_override` enum, closes TODO-S8-02-LINK-STRENGTH-OVERRIDE), v1.2.2 (A72 incremental-diff helper, closes TODO-S8-02-INCREMENTAL-MATRIX), v1.2.3 (A71 runnable test export in Cucumber / pytest-bdd / jest, closes TODO-S8-01-RUNNABLE-EXPORT), v1.2.4 (Phase 7 telemetry foundation L1a — canon-neutral), v1.2.5 (A70 negative-path scenario suggestions, closes TODO-S8-01-NEGATIVE-PATH-HEURISTICS), v1.2.6 (end-to-end sidecar fixture), v1.2.7 (A61 schema formalization), v1.2.8 (A61 cross-row F5 enforcement — FK to A59 + AnchorID uniqueness), v1.2.9 (C4 relationship `view_element_id` convention — closes the v1.2.6 round-1 scope-down). v1.1.x background:

- **v1.1.0** (Phase-3 close) — full Phase-3 dev-handoff: 5 new skills (`bsa-nfr-collector`, `bsa-story-writer`, `bsa-test-scenario-builder`, `bsa-traceability-matrix`, `bsa-backlog-bridge`); 4 new canonical artifacts (A62 NFR register, A70 story register, A71 test scenarios, A72 traceability matrix); 3 new platform-specific export shapes (Jira REST v3 JSON, Linear CSV, generic CSV); 3 new immutable invariants (INV-08, INV-09, INV-10).
- **v1.1.1** — A51 enum extensions (`inventory_gap` + `cross_tier_contradiction` + `Severity=critical`) for the first external pilot drift bundle, plus internal contract alignment across 6 docs/SKILL.md files.
- **v1.1.2** — `scripts/migrate_v1.0_to_v1.1.py` mechanical migration tool (4 mechanical fixes + 4 manual-review report flags) for v1.0.x → v1.1.x workspace upgrade.
- **v1.1.3** — Cross-artifact validator at the F5 hook layer (closes `[TODO-S8-01-X-ARTIFACT-NFR-COVERAGE]` + `[TODO-S8-02-X-ARTIFACT-FK]`): A71 NFR-coverage rule + A72 foreign-key/claim-source-consistency rule are now executable (not just documentary), via a new `_SiblingArtifactCache` that lets per-row handlers reach sibling canonical CSVs.
- **v1.1.4** — Platform export polish: optional Jira `customfield_mapping` block, Linear `Project` + `Cycle` columns, brand-new GitHub Projects v2 export schema (`backlog_export_github.csv` + F5 dispatcher entry).
- **v1.1.5** — Three new adversarial fixtures: multi-way (3-source) contradiction (atomic A51), tier-delta auto-resolution (T1 vs T4 → no A51), block-on-contradiction (spec-only baseline for the proposed `--strict-on-hard-a51` opt-in mode).
- **v1.1.6** — Live API integration (`scripts/backlog_live_apply.py`): Jira REST + Linear GraphQL + GitHub REST clients with idempotency, exponential backoff, partial-failure tolerance, per-platform state files, fcntl-based concurrency lock, and defense-in-depth token-shape rejection in the F5-validated response file (closes `[TODO-S9-LIVE-API]`).
- **v1.1.7** — Pilot anonymization across the active surface (the original first-pilot client name was scrubbed from schemas/scripts/docs/tests/hooks; the universal alias `Pilot-1` is used throughout).
- **v1.1.8** — Documentation polish: refreshed README, getting_started, FAQ, CONTRIBUTING, INSTALL to reflect the v1.1.x reality after the rapid-fire v1.1.0..v1.1.7 release line.

28 skills (9 main-cycle workers + 5 discovery workers + 5 auditors + 5 Phase-3 workers + 2 sidecars + 1 orchestrator + 1 meta) • 6 slash-commands + 1 Phase-3 composite (`/bsa-dev-handoff`) • 3 safety hooks • 8 golden fixtures (3 happy-path: `project_0001`/`0002`/`0003` + 5 adversarial: `prompt_injection`, `nfr_claim_contradiction`, `multi_way_contradiction`, `tier_delta_auto_resolution`, `block_on_contradiction` — last one is `spec_only`, documenting an opt-in failure mode the v1.2 implementation will use as its regression baseline) • 1412 unit tests (the exact count grows with each release; the invariant is "all pass") • evidence-bound claim layer (INV-01) • closed `ClaimType` enum (INV-07) • tier-aware weighted coverage (KPI-001) • two-key promotion • no-new-claims gate • Phase-3 story-claim provenance (INV-08) + NFR measurability (INV-09) + test-scenario provenance (INV-10).

External pilot status: see [docs/pilot_validation.md](docs/pilot_validation.md). Phase 2.5 external shakedown (2-4 weeks of real-project usage) framing applies to v1.0.x; v1.1.x is post-shakedown — the v1.0.x → v1.1.x migration tool exists precisely to bring shakedown-era workspaces forward.

## Architecture

Two-phase pipeline:

- **Discovery (D1-D5, optional):** problem framing → context research → hypothesis prioritization → feasibility → synthesis.
- **Main cycle (Stage 1-8 + Handoff):** evidence intake → claim binding → context/state → semantic catalogs → backbone → contracts → skeptical review → no-new-claims gate → H1-H4 handoff pack.
- **Phase 3 dev-handoff (post-Handoff, optional):** NFR collection → story writing → test scenario building → traceability matrix → backlog export (Jira / Linear / generic / GitHub Projects v2). Live-API mode (v1.1.6) posts directly to the platform.

Governance invariants: evidence-binding, single-writer canonical, no-new-claims, two-key promotion, composition-via-orchestrator, `ClaimType` schema closed, story-claim provenance, NFR measurability, test-scenario provenance. Registry: [governance/immutable_invariants.md](governance/immutable_invariants.md). Full architecture: [docs/architecture_overview.md](docs/architecture_overview.md).

## Repository layout

```
.claude-plugin/         Plugin manifest (plugin.json with canonPolicyVersion)
commands/               6 slash commands (/bsa-start, /bsa-status, /bsa-stage, /bsa-promote, /bsa-audit, /bsa-handoff)
                          + 1 Phase-3 composite (/bsa-dev-handoff)
hooks/                  3 safety hooks (SessionStart, PreToolUse:Write, PreToolUse:Bash)
skills/                 28 worker/auditor/sidecar/orchestrator/Phase-3 skills (bsa-*, d0-*, sidecars, inot-*)
scripts/                Validators, fixture runners, canon-hash computer, migration tools, live-API client
tests/                  1412 unit tests (grows with each release; exact count in the latest CHANGELOG entry)
fixtures/golden/        8 fixture dirs: 3 happy-path (project_0001/2/3) + 5 adversarial (prompt_injection, nfr_claim_contradiction, multi_way_contradiction, tier_delta_auto_resolution, block_on_contradiction — last is spec_only)
config/                 Orchestrator routing manifest (request_skill_routes.json)
governance/             Immutable invariants registry + JSON schemas (markers, A48..A72, backlog exports, live API response)
migrations/             v0.9 → v1.0 + v1.0 → v1.1 migration packs
docs/                   User + maintainer documentation
```

## Documentation

- [docs/getting_started.md](docs/getting_started.md) — install + first run.
- [docs/workflow.md](docs/workflow.md) — stage-by-stage walkthrough (+ discovery mode).
- [docs/commands_reference.md](docs/commands_reference.md) — every slash command with flags.
- [docs/troubleshooting.md](docs/troubleshooting.md) — common failure modes.
- [docs/architecture_overview.md](docs/architecture_overview.md) — skill families + invariants + governance.
- [docs/pilot_validation.md](docs/pilot_validation.md) — Pilot-1 status + framework-level pilot validation invariants.
- [docs/pilot_2nd_pass_runbook.md](docs/pilot_2nd_pass_runbook.md) — operator runbook for the 2nd Pilot-1 doctor pass (manual-review decision trees + pre/post diff workflow). v1.1.15.
- [docs/sidecar_inventory.md](docs/sidecar_inventory.md) — c4-plantuml + camunda-bpmn sidecar inventory + F5-boundary contract. v1.1.18 added [`config/sidecar_registry.yaml`](config/sidecar_registry.yaml) machine-readable registry + [`governance/schemas/sidecar_anchor_manifest.base.schema.json`](governance/schemas/sidecar_anchor_manifest.base.schema.json) common base.
- [docs/perf_baseline.md](docs/perf_baseline.md) — hot-path latency baseline + regression policy (run `python3 scripts/perf_bench.py --check` to verify).
- [docs/phase_7_design.md](docs/phase_7_design.md) — Phase 7 self-improvement loop foundation (tunable inventory + IMMUTABLE_CONFLICT lint + safety contract). v1.1.14.
- [docs/strict_a51_mode.md](docs/strict_a51_mode.md) — `/bsa-promote --strict-on-hard-a51` opt-in failure-mode contract (block-on-hard-A51). v1.1.16.
- [docs/shell_import_drivers.md](docs/shell_import_drivers.md) — bash + jq + curl/gh alternatives to `scripts/backlog_live_apply.py` for Jira / Linear / GitHub imports. v1.1.17.
- [docs/faq.md](docs/faq.md) — FAQ.
- [migrations/v1.0_to_v1.1/README.md](migrations/v1.0_to_v1.1/README.md) — v1.0.x → v1.1.x workspace migration guide.
- [CHANGELOG.md](CHANGELOG.md) — full release notes.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Solo maintainer, AI-assisted workflow. All commits run `pytest` + `scripts/fixture_runner.py --all` + `scripts/privacy_scan.py` + `scripts/compute_canon_hash.py` locally, and land through a `codex exec` review round before commit (multiple rounds for substantial patches — 15 rounds total across the v1.1.x line).

Sprint history: [docs/retros/](docs/retros/) — sprints 0..9 + v1.0.x polish sprints. Note: retro docs retain the original first-pilot client name as a development-history record (analogous to commit messages); the active plugin surface uses the universal alias `Pilot-1` (see [v1.1.7 anonymization](CHANGELOG.md#v117--2026-04-23)).

## License

See [LICENSE](LICENSE).
