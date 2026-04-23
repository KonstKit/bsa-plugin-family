---
name: bsa-backlog-bridge
description: Export A70 stories + A72 traceability into platform-specific backlog formats (Jira REST v3 JSON, Linear CSV, generic CSV) under analysis/handoff/. Pure derivation skill — never mutates upstream canonical state. Content-idempotent (same upstream → byte-identical body content; the Jira export's `generated_at` metadata field is the only across-run variation). INV-08 provenance preserved on every exported issue. Phase 3 terminal skill.
---

# BSA Backlog Bridge

Run this skill after `bsa-traceability-matrix` has promoted `A72_traceability_matrix.csv`. Produces platform-specific backlog files that downstream consumers (operator, dev team) import into their issue tracker. After successful emission of all requested platforms, emits `phase3.backlog_exported.json` and (when invoked as the terminal Phase-3 step) `pipeline.phase3.complete.json`.

## Scope

- Walk promoted A70 stories. For each story, compose a backlog item containing the story body + its acceptance criteria + INV-08 provenance (SourceClaimIDs / RelatedNFRIDs / StoryID).
- Cross-reference A72 to attach `trace_count` (number of A72 rows where StoryID matches) for downstream coverage queries.
- Emit one or more of three platform-specific files under `analysis/handoff/` per the `--platform` flag. Default: emit all three.
- Strictly read-only with respect to canonical state. Writes ONLY under `analysis/handoff/`. F5's dispatcher gates the export shapes (Sprint 9 added handoff/ paths to F5 for the first time — same write-time enforcement as canonical artifacts).

Out of scope:
- Mutating upstream A70/A71/A72/A50/A59/A62. Bridge is pure read.
- Live API calls to Jira/Linear/etc. — the bridge writes static export files; the operator imports them via the platform's CSV/JSON import UI or a custom POST script.
- Field-level customization (Jira customfields, Linear teams, etc.) beyond the minimum-viable shape — operators extend by post-processing the static files.
- A71 test scenarios in the export. Test scenarios are out-of-scope for backlog import (they live in QA tooling); A72 traceability + A70 story body together are sufficient for ticket-import purposes.

## Inputs

- Promoted `analysis/canonical/core_controls/A70_story_register.csv`
- Promoted `analysis/canonical/core_controls/A72_traceability_matrix.csv`
- Promoted `analysis/canonical/core_controls/A50_source_register.csv` (for source-name lookups in description footers)
- Promoted `analysis/handoff/H1_exec_brief.md` + `H2_delivery_packet.md` (for header context in the export report)
- CLI flag `--platform=<jira|linear|generic|all>` (default: `all`).
- CLI flag `--jira-project=<KEY>` (required when emitting Jira export — the project key the issues will be created under).

## Outputs

- `analysis/handoff/backlog_export_jira.json` (when --platform includes jira; v1.1.4 supports optional `customfield_mapping` block)
- `analysis/handoff/backlog_export_linear.csv` (when --platform includes linear; v1.1.4 added `Project` + `Cycle` columns)
- `analysis/handoff/backlog_export_generic.csv` (when --platform includes generic)
- `analysis/handoff/backlog_export_github.csv` (when --platform includes github; v1.1.4 — operator-side `gh` script consumes this for `gh issue create` + `gh project item-create` + `gh project item-edit`)
- `analysis/handoff/backlog_export_report.md` — counts, format choices, the `--jira-project` key used, A70 stories with INVESTStatus != 'pass' that surfaced as deferred backlog items.

After successful write of all requested platform files + report, emits:
- `analysis/runtime/ready/phase3.backlog_exported.json`
- `analysis/runtime/ready/pipeline.phase3.complete.json` (only when this skill is invoked as the terminal Phase-3 step — i.e., NOT under `--only=backlog-bridge` debugging mode).

## Workflow

1. **Load inputs.** Read promoted A70 + A72 + A50 + H1/H2. Build in-memory indices: `story_by_id`, `traces_by_story_id`, `source_by_id`. Fail fast if A70 or A72 is not promoted.

2. **Resolve --platform.** Default to `all`. Validate that `--jira-project` is set when jira is requested.

3. **Walk A70 stories in lexicographic StoryID order.** For each story:
   - Look up matching A72 rows; count → `trace_count`.
   - Compose the per-platform issue payload (see Format conventions below).

4. **Emit per-platform files** under `analysis/handoff/`:
   - **Jira**: single JSON object `{"export_format": "jira", "export_format_version": "1.0", "generated_at": <iso8601>, "source_artifacts": {…}, "issues": [<issue>, …]}` per `governance/schemas/backlog_export_jira.schema.json`.
   - **Linear**: CSV with columns Title, Description, Status, Priority, Labels, Estimate, StoryID, SourceClaimIDs, RelatedNFRIDs (canonical column order per `governance/schemas/backlog_export_linear.schema.json`).
   - **Generic**: CSV with columns Title, Description, AcceptanceCriteria, Priority, StoryID, SourceClaimIDs, RelatedNFRIDs, INVESTStatus, A51Ref (per `governance/schemas/backlog_export_generic.schema.json`).
   All three formats are byte-identical across re-runs against unchanged inputs (idempotency invariant — sorted issue order, deterministic field ordering, stable timestamp ONLY in `generated_at` which the bridge surfaces as a read-only metadata field, not as content).

5. **Write `backlog_export_report.md`** with:
   - Stories exported per platform (count + list of StoryIDs).
   - INVESTStatus distribution (pass / needs-* / escalate).
   - Deferred items list (INVESTStatus != 'pass' → "open issue in backlog; resolve via A51-NNN routes listed").
   - A72 trace-count distribution (stories with 0 traces flagged for operator attention).
   - Operator-facing import instructions (Jira: POST per-issue to /rest/api/3/issue; Linear: import CSV via Settings → Import; generic: paste into target tool).

6. **Emit markers** under `analysis/runtime/ready/`:
   - `phase3.backlog_exported.json` — verdict=PASS, stage=phase3.backlog. Always emitted on successful write.
   - `pipeline.phase3.complete.json` — verdict=PASS, stage=phase3.complete. Emitted ONLY when invoked as the terminal Phase-3 step (`/bsa-dev-handoff` full chain, not under `--only=backlog-bridge`).

## Format conventions

### Jira export (`backlog_export_jira.json`)

Per-issue shape:
```json
{
  "fields": {
    "project": {"key": "<--jira-project value>"},
    "issuetype": {"name": "Story"},
    "summary": "<A70.Title>",
    "description": "<A70.StoryText>\n\n## Acceptance criteria\n\n- <criterion 1>\n- <criterion 2>\n\n---\n*BSA provenance: STORY-NNN; claims: C-XXX, C-YYY; NFRs: NFR-ZZZ; trace count: N*",
    "labels": ["bsa-export", "level-1", "invest-pass"]
  },
  "bsa_provenance": {
    "story_id": "STORY-NNN",
    "source_claim_ids": ["C-XXX", "C-YYY"],
    "related_nfr_ids": ["NFR-ZZZ"],
    "trace_count": N
  }
}
```

INVESTStatus mapping:
- `pass` → `Story` issue type, label `invest-pass`.
- `needs-splitting`/`needs-estimation`/`needs-testable-acceptance`/`needs-negotiation` → `Story` (default) or `Task` (with `--jira-deferred-as-task`); label `invest-<status>`.
- `escalate` → `Story` + label `invest-escalate`. The escalate signal is preserved in the description footer so the receiving team triages on import.

### Linear export (`backlog_export_linear.csv`)

Per-row shape (CSV-quoted as needed):
```
Title,Description,Status,Priority,Labels,Estimate,StoryID,SourceClaimIDs,RelatedNFRIDs
"<title>","<markdown body>",Backlog,2,"bsa-export,invest-pass,level-1",3,STORY-001,C-042;C-045,NFR-PERF-001
```

INVESTStatus → Linear Status: `pass` → `Todo`; everything else → `Backlog` (lifecycle stays in the receiving team's hands; bridge doesn't presume on Linear states beyond the two pre-active ones).

EstimationHint → Linear Estimate (Fibonacci): xs→1, s→2, m→3, l→5, xl→8, unknown→empty.

### Generic export (`backlog_export_generic.csv`)

Per-row shape:
```
Title,Description,AcceptanceCriteria,Priority,StoryID,SourceClaimIDs,RelatedNFRIDs,INVESTStatus,A51Ref
"<title>","<As a... I want... so that...>","<criteria as authored>",level-1,STORY-001,C-042;C-045,NFR-PERF-001,pass,
```

No platform-specific translation — every column carries verbatim from A70 (and the schema enforces the expected enum + pattern shapes). Generic format is for "paste into our home-grown tool" workflows where the consuming team applies their own status/priority/label conventions.

## Invariants

- **Read-only with respect to canonical state.** Bridge NEVER writes under `analysis/canonical/`. The F5 hook would block such a write anyway (the dispatcher routes canonical paths through the schema validators, none of which match the bridge's output).
- **Schema-validated at write time.** All three export files dispatch through F5 to their respective schemas (US-S9-01..03 added handoff/ paths to the dispatcher for the first time). Malformed exports — wrong field names, missing provenance, broken Jira shape — fail the write rather than landing as silent half-exports.
- **Content-idempotent.** Re-running with unchanged A70/A72/A50 produces:
  - **Linear CSV + generic CSV**: byte-identical output (sorted StoryID order; canonical column order; no metadata fields).
  - **Jira JSON**: byte-identical EXCEPT for the top-level `generated_at` metadata field (which records the export wall-clock time). All `issues[]` content is byte-identical across runs; consumer-side diff tools that ignore `generated_at` see zero drift. Operators wanting strict full-byte idempotency for diff CI can post-process to strip `generated_at`.
- **INV-08 carries through.** Every exported issue / row carries a non-empty `StoryID` + (`SourceClaimIDs` non-empty OR `RelatedNFRIDs` non-empty). Provenance preserved end-to-end — a downstream consumer can trace a Jira ticket back to a BSA claim back to a source.

## Failure modes

- **A70 or A72 not promoted** — skill exits with error pointing to upstream skill (bsa-story-writer / bsa-traceability-matrix).
- **--platform=jira without --jira-project** — exits with usage error.
- **Schema validation failure on emitted file** — bridge re-attempts once (in case of transient field-naming bug); on second failure, exits with the F5 error message and a pointer to the failing schema. Does NOT emit `phase3.backlog_exported` marker.
- **Empty A70 (zero stories)** — bridge emits empty exports (e.g., Jira: `"issues": []`; CSV: header-only file) + a notice in the report. The export marker IS emitted (zero stories is a valid Phase-3 outcome — no actionable backlog items).
- **A70 story has no matching A72 rows** — emit warning in the report ("STORY-NNN has 0 traces in matrix — claim provenance may be unreliable"). Bridge continues; the trace_count=0 in the export payload makes the gap visible to consumers.

## Composition

Invoked by `/bsa-dev-handoff` (Phase-3 composite command) as the FIFTH and TERMINAL stage: `phase3.nfr → phase3.story → phase3.test_scenario → phase3.traceability → phase3.backlog_exported → pipeline.phase3.complete`.

Direct invocation: `/bsa-dev-handoff --only=backlog-bridge --platform=jira --jira-project=ACME` for debugging or partial re-runs. Prerequisites: phase3.story.pass + phase3.traceability.pass + promoted A70/A72/A50/H1/H2.

When invoked under `--only=backlog-bridge`, this skill emits `phase3.backlog_exported.json` ONLY (NOT `pipeline.phase3.complete.json` — the pipeline-complete marker is reserved for the full chain).

Downstream consumers:
- Operator imports `backlog_export_jira.json` via Jira REST POST loop.
- Operator imports `backlog_export_linear.csv` via Linear Settings → Import.
- Operator imports `backlog_export_generic.csv` via paste-into-tool.
- Audit tooling reads any of the three to verify provenance preservation against canonical state.

## Cross-refs

- `governance/schemas/backlog_export_jira.schema.json` — Jira export shape.
- `governance/schemas/backlog_export_linear.schema.json` — Linear export row shape.
- `governance/schemas/backlog_export_generic.schema.json` — generic CSV row shape.
- `skills/bsa-story-writer/SKILL.md` — upstream A70 authoring contract.
- `skills/bsa-traceability-matrix/SKILL.md` — upstream A72 authoring contract.
- `docs/phase_3_plan.md` — Phase-3 sequencing + Sprint 9 scope.
- `commands/bsa-dev-handoff.md` — composite command that invokes this skill.

## Open follow-ups

- ~~`[TODO-S9-01-JIRA-CUSTOMFIELDS]`~~ — **CLOSED in v1.1.4.** Jira export schema gains an OPTIONAL top-level `customfield_mapping` object documenting four recognized BSA logical fields → Jira customfield IDs (`nfr_ids`, `source_claim_ids`, `story_id`, `a51_refs`). When set, the bridge populates the named customfields in `issue.fields` per row; when omitted, pre-v1.1.4 description-footer-only behavior preserved. `additionalProperties:false` on the mapping object catches typos at hook time.
- ~~`[TODO-S9-02-LINEAR-PROJECTS]`~~ — **CLOSED in v1.1.4.** Linear export schema gains two required columns (`Project`, `Cycle`). Empty values preserve pre-v1.1.4 behavior (team default project, no cycle); non-empty values let the bridge associate stories with a named Linear project + cycle.
- ~~`[TODO-S9-03-GITHUB-PROJECTS]`~~ — **CLOSED in v1.1.4.** New `analysis/handoff/backlog_export_github.csv` schema (`backlog_export_github.schema.json`) for GitHub Projects v2. CSV-based — operator-side `gh` script (or GitHub Actions workflow) consumes the CSV to call `gh issue create` + `gh project item-create` + `gh project item-edit` per row. Columns mirror Linear (Title/Body/Status/Priority/Size/Labels/StoryID/SourceClaimIDs/RelatedNFRIDs); same Labels regex enforces `bsa-export` + `level-N` + `invest-N` membership. F5 dispatcher entry registered.
- `[TODO-S9-LIVE-API]` — optional live-API mode (POST to Jira / Linear / GitHub directly instead of static file output). Higher risk surface (auth, rate limits, partial failures); v1.3 candidate (Section C).
