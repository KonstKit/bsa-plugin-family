---
name: bsa-dev-handoff
description: Phase 3 composite — run the dev-handoff extension after main-cycle handoff.ready is emitted. Sequences bsa-nfr-collector → bsa-story-writer → bsa-test-scenario-builder → bsa-traceability-matrix → bsa-backlog-bridge to produce A62 NFRs, A70 stories, A71 test scenarios, A72 traceability matrix, and platform-specific backlog exports. Phase-3 terminal command; handoff pack from /bsa-handoff is the input.
---

# `/bsa-dev-handoff`

Run the Phase-3 dev-handoff extension after a successful main-cycle handoff. Turns the canonical claim-layer + H1-H4 packets into user stories, NFRs, test scenarios, a traceability matrix, and backlog exports for Jira / Linear / generic CSV.

## Usage

```
/bsa-dev-handoff [--platform=<jira|linear|generic|all>] [--only=<skill>] [--verbose]
```

- `--platform=<...>` — which backlog-bridge output to emit. `all` (default) emits all three. Individual: `jira`, `linear`, `generic`.
- `--only=<skill>` — run a single Phase-3 skill in isolation (debugging / partial re-run). One of `nfr`, `story`, `test-scenario`, `traceability`, `backlog-bridge`. Default is the full chain.
- `--verbose` — per-skill trace: which claims were matched, how many NFRs / stories / scenarios emitted, any A51 routes raised.

## Prerequisites

- `handoff.ready.json` marker present (/bsa-handoff completed).
- `analysis/handoff/H1_exec_brief.md` + `H2_delivery_packet.md` + `H3_validation_packet.md` + `H4_open_items_packet.md` + `handoff_manifest.json` present.
- Canonical `A59_claim_register.csv` + `A50_source_register.csv` + `A51_issue_route_register.csv` promoted (these are the sources the Phase-3 skills read).
- Phase-3 skills installed: `bsa-nfr-collector`, `bsa-story-writer`, `bsa-test-scenario-builder`, `bsa-traceability-matrix`, `bsa-backlog-bridge`. At Sprint 6 kick-off, only `bsa-nfr-collector` is fully implemented; the other four are scaffolds — partial runs via `--only=nfr` are the supported path until Sprints 7-9 close.

## What this command does

Delegate to `bsa-orchestrator`, which composes the 5 Phase-3 skills:

1. **bsa-nfr-collector** reads A59 + H2, authors `analysis/proposals/phase3/A62_nfr_register.csv` + extraction report. Emits `phase3.nfr.pass.json` on success (INV-09 measurability rules satisfied OR measurability-gap A51 routes raised).
2. **bsa-story-writer** (Sprint 7 — scaffold at Sprint 6 kick-off) reads promoted A59 + A62, authors `A70_story_register.csv` per INVEST criteria. INV-08 enforced: every story carries SourceClaimIDs or RelatedNFRIDs. Emits `phase3.story.pass.json`.
3. **bsa-test-scenario-builder** (Sprint 8 — scaffold) reads A70 + A62 + A59, authors `A71_test_scenario_register.csv` in Gherkin Given-When-Then. INV-10 enforced: every scenario carries SourceStoryID. Measurable NFRs drive at least one scenario each. Emits `phase3.test_scenario.pass.json`.
4. **bsa-traceability-matrix** (Sprint 8 — scaffold) builds `A72_traceability_matrix.csv` linking A70 stories ↔ A59 claims ↔ A50 sources (three-way join, one row per Story↔ClaimID↔SourceID triple). Emits `phase3.traceability.pass.json`. Orphan report + coverage report are derived views.
5. **bsa-backlog-bridge** (Sprint 9 — scaffold) produces `analysis/handoff/backlog_export_{jira.json,linear.csv,generic.csv}` per the `--platform` flag. Strictly read-only on canonical state. Emits `phase3.backlog_exported.json` on success.
6. Orchestrator emits `pipeline.phase3.complete.json` after all five skills pass.

Each inter-skill transition uses the two-key promotion gate established in Sprint 3 (evidence-binding + audit-pass marker), reusing the main-cycle machinery.

## Prerequisites per --only invocation

| --only | Upstream requirement |
|---|---|
| `nfr` | handoff.ready + promoted A59 + H2 |
| `story` | phase3.nfr.pass + promoted A62 |
| `test-scenario` | phase3.story.pass + promoted A70 + promoted A62 |
| `traceability` | phase3.story.pass + promoted A70 + promoted A59 + promoted A50 |
| `backlog-bridge` | phase3.test_scenario.pass + phase3.traceability.pass + promoted A70 + A71 + A72 |

Partial runs are supported so a single Phase-3 skill can be debugged / retried without re-executing upstream work.

## Markers emitted

Under `analysis/runtime/ready/`:
- `phase3.nfr.pass.json`
- `phase3.story.pass.json`
- `phase3.test_scenario.pass.json`
- `phase3.traceability.pass.json`
- `phase3.backlog_exported.json`
- `pipeline.phase3.complete.json`

These marker IDs land in `governance/schemas/marker.schema.json` as each owning sprint ships the corresponding skill. At Sprint-6 kick-off only `phase3.nfr.pass` is in the schema; the others are added in Sprints 7-9.

## Output

- `analysis/proposals/phase3/` — per-skill proposal artifacts (A62 / A70 / A71 / A72 + report MDs). Promoted to `analysis/canonical/core_controls/` via `/bsa-promote` using the same two-key gate as main-cycle stages.
- `analysis/handoff/backlog_export_*` — terminal platform-specific files. These go directly to `handoff/` (not to a canonical/ path) because they're derived-only output for external consumption, not canonical state.

## Failure modes

- **Main-cycle handoff not ready**: refuse to start, direct to `/bsa-handoff`.
- **Phase-3 skill missing or scaffold-only**: when a full run is requested but a downstream skill is scaffold-only, the composite command completes the upstream skills and emits a notice describing which skills ran vs. skipped. `pipeline.phase3.complete.json` is NOT emitted until all five are real implementations (Sprint 9 close).
- **INV-08 / INV-09 / INV-10 violation at proposals stage**: the F5 write-validator blocks write; the skill retries with corrections or raises A51. Non-retryable violations surface as the command's own error with a pointer to the offending row.
- **Backlog-bridge platform target missing (e.g., `--platform=jira` but Jira is not configured)**: skill emits the file anyway (text format is spec'd; no live API call at the Phase-3 layer); operator copies the file into the target tool manually.

## Side effects

Writes under `analysis/proposals/phase3/` and `analysis/handoff/`. Does NOT modify `analysis/canonical/` directly — promotion is always through `/bsa-promote`. Pre-existing handoff pack (H1-H4 + manifest) is not touched.

## Next step

After `pipeline.phase3.complete.json`:
- Review `analysis/handoff/backlog_export_*` → paste into target backlog tool.
- Archive `analysis/proposals/phase3/*_report.md` as engagement artifacts.
- At this point the engagement is fully packaged for dev handoff.

## Cross-refs

- `docs/phase_3_plan.md` — Phase-3 sprint sequencing (Sprints 6-9) + artifact schemas.
- `skills/bsa-nfr-collector/SKILL.md` — first concrete Phase-3 skill (Sprint 6 US-S6-01).
- `skills/bsa-story-writer/SKILL.md` — scaffold (Sprint 7 US-S7-02).
- `skills/bsa-test-scenario-builder/SKILL.md` — scaffold (Sprint 8 US-S8-01).
- `skills/bsa-traceability-matrix/SKILL.md` — scaffold (Sprint 8 US-S8-02).
- `skills/bsa-backlog-bridge/SKILL.md` — scaffold (Sprint 9 US-S9-01..03).
- `commands/bsa-handoff.md` — upstream main-cycle handoff (prerequisite).
