# Getting Started — bsa-full

Quickstart for installing `bsa-full` into Claude Code and running the evidence-first BA/SA pipeline end-to-end on your own project.

> **Who this is for:** a business or systems analyst (or team lead) who wants an auditable, anti-hallucination claim layer for a mid-size system-understanding or discovery engagement. 28 skills, 6 slash-commands + 1 Phase-3 composite, 3 safety hooks, 8 golden fixtures (3 happy-path: `project_0001`/`0002`/`0003` + 5 adversarial: `prompt_injection`, `nfr_claim_contradiction`, `multi_way_contradiction`, `tier_delta_auto_resolution`, `block_on_contradiction` — last one is `spec_only`) worth of regression coverage. v1.1.x adds Phase-3 dev-handoff (NFRs / stories / test scenarios / traceability matrix / backlog export with optional live-API mode).

## Prerequisites

- Claude Code (any version supporting the plugin system).
- Python 3.9+ (for the bundled validators and `compute_canon_hash.py`).
- **Optional:** `plantuml` (C4 rendering) and `xmllint` (BPMN validation). Either missing — the sidecar skill prints a graceful-degradation message and skips render/validate without failing the pipeline.

## Install

```
claude plugin marketplace add /Users/kkitanin/projects/bsa-plugin-family
claude plugin install bsa-full@bsa-marketplace
claude plugin list      # expect bsa-full@1.4.0 (manifest pinned at 1.4.0 across v1.4.x line; tag may be ahead — current tag is v1.4.11)
```

Full install + uninstall + upgrade notes (including the session-only `claude --plugin-dir` path for quick smoke-tests): [../INSTALL.md](../INSTALL.md).

## First run — 30-second tour

In a new project directory (`/tmp/my-engagement` will do), run:

```
/bsa-start --mode=direct
```

What it does:
1. Emits `analysis/runtime/ready/stage1.ready.json` (marker) and seeds `analysis/canonical/core_controls/{A48_run_context_card.md, A50_source_register.csv, A51_issue_route_register.csv}`.
2. Prints a summary of what's been created and what the next command is.

Check current state:

```
/bsa-status
```

Shows: current stage, pending markers, count of open A51 items, most recent audit verdict. Useful after returning to a workspace after a break.

## A full pipeline on the `project_0001` golden fixture

The simplest way to see the full flow is to copy one of the bundled fixtures and re-run it. Per the authoritative stage map in [commands/bsa-stage.md](../commands/bsa-stage.md):

```
cp -r /path/to/bsa-plugin-family/fixtures/golden/project_0001/inputs ./my-project-inputs
cd /tmp/my-project
/bsa-start --mode=direct
# drop your sources under analysis/proposals/stage1/inputs/
/bsa-stage 1             # bsa-evidence-intake -> bsa-claim-binder
/bsa-promote             # promotes Stage 1 into canonical; emits stage2.ready
/bsa-stage 2             # bsa-context-framer (emits stage2.context_state.pass)
/bsa-promote
/bsa-stage 3             # bsa-semantic-extractor + citation/consistency audits
/bsa-promote
/bsa-stage 4             # bsa-domain-modeler
/bsa-promote
/bsa-stage 5             # bsa-backbone-builder + anchor audit
/bsa-promote
/bsa-stage 6             # bsa-contract-builder + anchor audit
/bsa-promote
/bsa-stage 7             # bsa-skeptical-reviewer + citation audit re-run
/bsa-promote
/bsa-stage 8             # bsa-validation-readiness + no-new-claims audit
/bsa-promote
/bsa-handoff             # emit H1-H4 pack
```

Auditors run as part of each stage's worker chain; `/bsa-audit <kind>` is only needed to re-run a specific audit against current proposals without re-running the producing worker.

`/bsa-promote` is two-key: it verifies evidence-binding (INV-01 on promoted positive claims) **and** checks for the required audit markers before it moves anything from proposals to canonical. Use `/bsa-promote --dry-run` first if you want to see what would happen.

Each stage prints the artifacts it will write and what invariants must hold. The full command reference is in [commands_reference.md](commands_reference.md).

## Phase 3 dev-handoff (post-Handoff, optional)

Once `/bsa-handoff` has emitted H1-H4, the Phase-3 chain extends the engagement into dev-team-ready artifacts:

```
/bsa-dev-handoff                # composite: nfr-collector → story-writer →
                                  test-scenario-builder → traceability-matrix →
                                  backlog-bridge (jira / linear / generic / github)
```

Output lives at `analysis/handoff/`:

| File | Purpose |
|---|---|
| `backlog_export_jira.json` | Jira REST v3 issue-create JSON (consumable by `gh-style` Jira API loop) |
| `backlog_export_linear.csv` | Linear CSV import (Settings → Import) |
| `backlog_export_generic.csv` | Generic spreadsheet shape |
| `backlog_export_github.csv` | GitHub Projects v2 CSV (operator-side `gh` script consumes) |
| `phase3_dev_handoff_report.md` | Counts + flagged stories + INVEST-deferred backlog |

For real-time platform integration (POST directly to Jira / Linear / GitHub instead of static files), see `scripts/backlog_live_apply.py --help` (v1.1.6).

## Migrating an older workspace

If you have a workspace authored against v1.0.x schemas and want to bring it forward to v1.1.x:

```
scripts/migrate_v1.0_to_v1.1.py --workspace=path/to/analysis/ --all-mechanical
scripts/migrate_v1.0_to_v1.1.py --workspace=path/to/analysis/ --all-mechanical --apply
scripts/migrate_v1.0_to_v1.1.py --workspace=path/to/analysis/ --report all-reports
```

Full migration guide: [../migrations/v1.0_to_v1.1/README.md](../migrations/v1.0_to_v1.1/README.md).

## Modes

- `--mode=direct` — skips discovery, starts at Stage 1 with source inputs already known. Fastest path. Use when scope is already clear and source set is stable.
- `--mode=discovery_then_bsa` — runs D1-D5 (discovery) first, promotes a `discovery_seed_bundle` into Stage 1, then runs the main 1-8 cycle. Use when scope is fuzzy, stakeholders conflict, or the source set itself needs to be discovered.

Compare the three bundled fixtures to see both modes in action:

- `project_0001` — process + direct (support-ticket triage). Simplest, single-stakeholder.
- `project_0002` — structural + discovery + mixed-tier (analytics platform ownership).
- `project_0003` — process + discovery + multi-stakeholder-conflict (procurement approval workflow). Exercises the tier-delta ≤ 1 contested rule.

## What you get at `/bsa-handoff`

Five artifacts under `analysis/proposals/stage7_8/handoff/`, promoted to `analysis/handoff/` by `/bsa-promote` (the handoff pack lives at the top-level `analysis/handoff/`, not under `canonical/`; see [../skills/bsa-orchestrator/references/workflow-contract.md](../skills/bsa-orchestrator/references/workflow-contract.md) §Runtime Layout):

| File | Purpose |
|---|---|
| `H1_exec_brief.md` | Executive audience. ≤ 2 pages. Findings + Recommended Next Steps + KPI scorecard. |
| `H2_delivery_packet.md` | FR/NFR register, A61 contract anchors, entity/state catalogs, A51 routes, next-gate preconditions. |
| `H3_validation_packet.md` | KPI scorecard + per-tier breakdown + audit reports index + test-scenario seeds. |
| `H4_open_items_packet.md` | A51 digest, decisions required (by severity), suggested owners, escalation routes. |
| `handoff_manifest.json` | SHA-256 digest over H1-H4 + binding map + no-new-claims verdict. |

Plus `handoff_evidence_binding_map.csv` (every `[Cxxx]` / `[AJ:Cxxx]` / `[A51-xxx]` citation in H1-H4 mapped back to its canonical row) and `handoff_no_new_claims_report.md` (the no-new-claims auditor's verdict).

## Next

- [workflow.md](workflow.md) — full stage-by-stage walkthrough including discovery mode.
- [commands_reference.md](commands_reference.md) — every slash-command with flags.
- [architecture_overview.md](architecture_overview.md) — skill family, invariants, governance.
- [troubleshooting.md](troubleshooting.md) — common failure modes and fixes.
- [faq.md](faq.md) — FAQ.
