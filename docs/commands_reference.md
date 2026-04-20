# Commands Reference

Every slash command exposed by `bsa-full` with its flags, preconditions, postconditions, and failure modes.

All commands are thin wrappers; the actual work is delegated to one of 23 skills via the orchestrator. Full universal flags:

- `--verbose` — emit per-step trace (skill calls, file reads/writes, markers emitted). Without it, only a summary prints.
- `--dry-run` (where supported) — preview what the command would do without writing anything.

## `/bsa-start`

Initialize the `analysis/` runtime layout in the current working directory.

```
/bsa-start --mode=direct
/bsa-start --mode=discovery_then_bsa
```

- `--mode=direct` — start directly at Stage 1. Layout: `analysis/{runtime/{ready,locks,reentry,events},canonical,proposals,views,handoff}` (see [workflow-contract.md](../skills/bsa-orchestrator/references/workflow-contract.md) §Runtime Layout for the full shape).
- `--mode=discovery_then_bsa` — prepend D1-D5 discovery. Layout adds a parallel `analysis/discovery/{runtime,canonical,proposals,handoff}/`.

Writes: `analysis/canonical/core_controls/{A48,A50,A51}*` seeds, emits `analysis/runtime/ready/stage1.ready.json` (direct) or `analysis/discovery/runtime/ready/discovery.d1.ready.json` (discovery).

Failure modes: existing non-empty `analysis/` directory in CWD → refuses with message; user removes the directory or runs from a fresh directory.

## `/bsa-status`

Report current pipeline state.

```
/bsa-status
```

Output fields:
- Current stage.
- Pending markers (expected but not yet emitted).
- Open `A51` row count.
- Last audit verdict per stage.
- Canon policy version + hash on the most recent marker.

Failure modes: no `analysis/` directory → suggests running `/bsa-start`.

## `/bsa-stage <n>`

Run the worker chain for stage N. Valid N: `1`, `2`, `3`, `4`, `5`, `6`, `7`, `8`, plus discovery sub-stages `d1`..`d5`.

```
/bsa-stage 2
/bsa-stage d3
```

Routes via `config/request_skill_routes.json` and runs the full worker + in-stage auditor chain per [commands/bsa-stage.md](../commands/bsa-stage.md):

| Stage | Worker chain |
|---|---|
| stage1 | bsa-evidence-intake → bsa-claim-binder |
| stage2 | bsa-context-framer |
| stage3 | bsa-semantic-extractor → bsa-citation-auditor + bsa-consistency-auditor |
| stage4 | bsa-domain-modeler |
| stage5 | bsa-backbone-builder → bsa-anchor-auditor |
| stage6 | bsa-contract-builder → bsa-anchor-auditor |
| stage7 | bsa-skeptical-reviewer → bsa-citation-auditor (re-run) |
| stage8 | bsa-validation-readiness → bsa-no-new-claims-auditor |
| d1..d5 | corresponding d0-* discovery skills |

Emits proposal artifacts under `analysis/proposals/stage<n>/` (or `analysis/proposals/stage7_8/` for stages 7-8). Does **not** touch canonical until `/bsa-promote` runs.

## `/bsa-audit <kind>`

Re-run an individual auditor skill against the current stage's proposal output. In normal flow, audits run as part of `/bsa-stage N` — use `/bsa-audit <kind>` only when you want to re-run a specific audit without re-running the producing worker.

```
/bsa-audit citation
/bsa-audit consistency
/bsa-audit skeptical
/bsa-audit no-new-claims
/bsa-audit anchor
```

Maps to (markers live under `analysis/runtime/ready/`):

| `<kind>` | Auditor skill | Emits marker |
|---|---|---|
| `citation` | `bsa-citation-auditor` | `stage3.citation_audit.pass.json` |
| `consistency` | `bsa-consistency-auditor` | part of Stage 3 (no dedicated pass marker) |
| `skeptical` | `bsa-skeptical-reviewer` | `stage7.skeptical_review.pass.json` |
| `no-new-claims` | `bsa-no-new-claims-auditor` | `stage8.no_new_claims.pass.json` |
| `anchor` | `bsa-anchor-auditor` | `stage5.anchor_audit.pass.json` or `stage6.anchor_audit.pass.json` (stage-dependent) |

Output: human-readable `<kind>_audit_report.md` under `analysis/proposals/<stage>/` plus the marker under `analysis/runtime/ready/`. An audit that does NOT pass produces the report + blocks promotion; there is no dedicated `.fail.json` marker (see [runtime-marker-schema.md](../skills/bsa-orchestrator/references/runtime-marker-schema.md)).

## `/bsa-promote`

Two-key promotion: move a stage's proposal into canonical.

```
/bsa-promote
/bsa-promote --dry-run
```

Preconditions (both must hold):
1. Every positive `direct` or `inference` claim in the stage's proposal artifacts satisfies INV-01 evidence-binding (`SourceID+ExcerptID` OR `A51Ref`). `analyst_judgment` rows are validated against INV-07 (`JustificationRationale` referencing ≥ 1 upstream `ClaimID`).
2. All required audit markers for the stage are present and `verdict=PASS` (or `merged` for Stage 1).

The PreToolUse:Bash hook refuses execution if either precondition fails, and surfaces the exact missing marker or unbound row.

`--dry-run`: prints the full promotion plan (files to move, markers to emit) without touching `analysis/canonical/`.

## `/bsa-handoff`

Generate H1-H4 handoff pack, run the final no-new-claims gate, emit the manifest.

```
/bsa-handoff
```

Preconditions: Stage 8 `no_new_claims.pass` marker present; Stage 7 `skeptical_review.pass` present; all 5 core-control CSVs promoted.

Outputs under `analysis/proposals/stage7_8/handoff/`:

- `H1_exec_brief.md` — executive audience, ≤ 2 pages.
- `H2_delivery_packet.md` — delivery manifest + FR/NFR + A61 + entities + processes + A51 + next-gate preconditions.
- `H3_validation_packet.md` — KPI scorecard + per-tier breakdown + audit index + test-scenario seeds + outstanding findings.
- `H4_open_items_packet.md` — A51 digest + decisions required by severity + suggested owners + escalation routes.
- `handoff_manifest.json` — SHA-256 over H1-H4 + binding map + no-new-claims verdict.
- `handoff_evidence_binding_map.csv` — every `[Cxxx]` / `[AJ:Cxxx]` / `[A51-xxx]` citation mapped to canonical row.
- `handoff_no_new_claims_report.md` — the auditor's verdict over the handoff pack.

## Universal flags

### `--verbose`

Print per-step trace. Example:

```
/bsa-stage 2 run --verbose
```

emits:
```
[orchestrator] route: bsa_pack_direct_mixed_sources stage=2
[bsa-context-framer] reading canonical/core_controls/A48,A50,A58,A59,A60,A51
[bsa-context-framer] writing proposals/stage2/context_state_frame.md (142 lines)
[bsa-context-framer] writing proposals/stage2/stakeholder_authority_map.md
... (5 files)
[bsa-context-framer] writing proposals/stage2/stage2_summary.json
[orchestrator] stage 2 proposals ready for promotion
```

### `--dry-run` (supported on `/bsa-promote`)

Preview without side effects. Useful before committing a promotion.

## Graceful degradation

Commands that invoke sidecar skills (`c4-plantuml-from-context`, `camunda-bpmn-from-context`) check for optional tooling (`plantuml`, `xmllint`) at runtime. Missing tools trigger a degradation message like:

```
[c4-plantuml-from-context] plantuml not found; skipping render. Sidecar artifacts under analysis/views/c4/ will be .puml source only.
```

The pipeline continues without erroring.
