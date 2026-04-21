---
name: bsa-backlog-bridge
description: SCAFFOLD (Sprint 9 US-S9-01..03). Export A70 stories + A71 scenarios + A72 traceability matrix to platform-specific backlog formats (Jira JSON, Linear CSV, generic CSV). Read-only — never mutates upstream artifacts. Phase 3 terminal skill.
---

# BSA Backlog Bridge (SCAFFOLD)

> **Status:** scaffold only. Implementation lands in Sprint 9 across three sub-stories (US-S9-01 Jira, US-S9-02 Linear, US-S9-03 generic CSV).
>
> **TODO anchors:**
> - `[TODO-S9-01-JIRA-JSON]` — Jira REST v3 issue-create JSON format. Fields: project, issuetype, summary, description, labels, customfield_<NFR-id>.
> - `[TODO-S9-02-LINEAR-CSV]` — Linear's CSV import shape (Title, Description, Status, Priority, Labels, Assignee).
> - `[TODO-S9-03-GENERIC-CSV]` — minimal column set for "paste into our home-grown tool" — (Title, Description, AcceptanceCriteria, Priority, SourceClaimIDs).
> - `[TODO-S9-04-IDEMPOTENCY]` — re-running the bridge against the same A70/A71 should produce byte-identical output (sorted, deterministic).

## Scope (planned)

- Read promoted A70/A71/A72 + handoff packets.
- Emit `analysis/handoff/backlog_export.{json,csv}` per platform request.
- Strictly read-only — does NOT touch canonical state.

## Inputs (planned)

- Promoted A70/A71/A72 + H1-H4 packets.
- CLI flag `--platform={jira|linear|generic}` (default: emit all three).

## Outputs (planned)

- `analysis/handoff/backlog_export_jira.json`
- `analysis/handoff/backlog_export_linear.csv`
- `analysis/handoff/backlog_export_generic.csv`
- `analysis/handoff/backlog_export_report.md` — counts, format choices, A51 routes that ended up as "open issues" in the export.

## Invariants (planned)

- INV-08 carries through: every exported backlog item links back to a ClaimID or NFRID via `SourceClaimIDs` / `RelatedNFRIDs` in the export payload (preserved field).
- Read-only — `BSA_WRITER` is NOT set; F5 hook accepts because target is `analysis/handoff/`, not `analysis/canonical/`.
- Idempotent — same A70/A71/A72 input → byte-identical output (sorted, deterministic field ordering).

## TODO

- `[TODO-S9-RELEASE-NOTES]` — Phase-3 release notes template, includes backlog-bridge sample outputs.
