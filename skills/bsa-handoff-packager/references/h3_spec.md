# H3 Validation Packet — Content Contract

Authoritative section / content rules for `H3_validation_packet.md`. Peer specs: `h1_spec.md`, `h2_spec.md`, `h4_spec.md`.

## Purpose

Give QA, validation engineers, and compliance reviewers the **verification map**: what was audited, what verdicts came back, which KPIs passed, and what remains open. H3 is the evidence-of-quality pack; it must be auditable from a fresh reader with no prior project context.

## Audience

- **Primary:** QA leads, validation engineers, compliance reviewers.
- **Secondary:** Regulated-domain sign-off roles (privacy officer, security officer), external auditors.
- **Non-audience:** Executives (H1), delivery team (H2), PMO (H4).

## Length

- Soft cap: ≤ 6 printed pages.
- Tables dominate; prose only for verdicts and narrative summaries.
- Detailed audit bodies live in `audit_reports/` — H3 indexes, it does not duplicate.

## Required Sections

Every `H3_validation_packet.md` MUST contain these five sections, in this order, with the exact headings below.

### `## Validation Outcome`
- 1-line overall verdict: `PASS` / `FAIL` / `CONDITIONAL_PASS`.
- Short paragraph (2-3 sentences) summarizing the gate set actually executed for this run profile.
- Table with columns: `Gate | Marker | Verdict | Emitted at`. One row per mandatory marker used (e.g., `stage3.citation_audit.pass`, `stage5.anchor_audit.pass`, `stage6.anchor_audit.pass`, `stage7.skeptical_review.pass`, `stage8.no_new_claims.pass`).
- `Emitted at` = ISO-8601 timestamp from the marker file.
- `CONDITIONAL_PASS` verdict is valid ONLY when at least one A51 hard-blocker has an explicit sponsor waiver referenced in H4 `## Decisions Required`.

### `## KPI Scorecard (001..005)`
- Table with columns: `KPI | Definition ref | Target | Actual | Delta | Verdict | Trace`.
- Exactly five rows, one per KPI defined in `skills/bsa-orchestrator/references/kpi-definitions.md`:
  - `KPI-001` weighted claim coverage (target ≥ 0.75)
  - `KPI-002` anchor drift count (target = 0)
  - `KPI-003` critical unsupported claims (target = 0)
  - `KPI-004` A51 unresolved hard-blocking count (target = 0)
  - `KPI-005` handoff new-claim leakage count (target = 0)
- `Trace` cites the report filename + section that produced the number (e.g., `citation_audit_report.md#weighted-coverage`).
- If any KPI fails target, the overall `## Validation Outcome` MUST be `FAIL` or `CONDITIONAL_PASS` (with waiver trace).

### `## Audit Reports Index`
- Table with columns: `Audit | Report path | Verdict | Critical findings count | Secondary findings count`.
- One row per audit that ran (citation, consistency, skeptical, no-new-claims, anchor, plus any discovery-mode discovery_citation_audit and no_solution_leakage).
- `Report path` points to the canonical audit report under `analysis/canonical/stage*/audit_reports/`.
- Rows are read-only pointers; do not summarize findings inline here — H3 readers open the referenced report.

### `## Test Scenario Seed (placeholders for bsa-test-scenario-builder, Phase 3)`
- Placeholder section — kept visible so Phase 3 can fill it without structural changes.
- Table with columns: `SCN-ID (planned) | Scope area | Intent | Upstream ClaimID refs | Status`.
- `Status` ∈ {`planned`, `seeded`, `N/A-for-profile`}. Sprint 2 default = `planned`.
- Seeding rule (when Phase 3 lands): every planned SCN references ≥ 1 upstream `[C-xxx]`; any SCN resting on judgment cites `[AJ:C-xxx]` + upstream.
- A non-empty placeholder table with `planned` rows is MANDATORY even in Sprint 2 — it anchors Phase 3 integration. An empty placeholder is a shape violation.

### `## Outstanding Audit Findings`
- Table with columns: `Finding ID | Source audit | Severity | Related ClaimID | Related A51Ref | Status`.
- Only rows for findings NOT already PASS'd but that didn't fail the gate (e.g., informational findings, accepted residual risk).
- `Status` ∈ {`open-informational`, `open-accepted`, `routed-to-a51`}.
- `open-accepted` MUST have a sponsor decision recorded in H4 — H3 just points; H4 drives.
- If there are no outstanding findings, render the table header with a single row `(none)` — do not remove the section.

## Citation Rules

Same as H1 (`[C-xxx]`, `[AJ:C-xxx]`, `[A51-xxx]`). H3 is especially strict: every KPI number, every verdict, every audit outcome MUST be traceable to a promoted report or canonical control row.

## Forbidden Content

- New findings not present in the cited audit reports.
- Verdicts that disagree with promoted marker files — the marker is the authority.
- KPI numbers invented or re-computed; take them from the audit reports.
- Narrative excuses for FAIL verdicts; narrative belongs in H4 `## Decisions Required`.

## Audit Binding

- `bsa-no-new-claims-auditor` validates H3 (same gate as other H-packs) — KPI numbers, verdicts, and findings must resolve to upstream audit reports or canonical control rows.
- `bsa-citation-auditor` validates marker timestamps match the referenced marker files.
- `SCN-STAGE78-001-E-H3` (see validation-scenario-manifest.csv) checks H3 shape + KPI roll-up consistency with canonical audit reports.

## Cross-References

- Peer specs: `h1_spec.md`, `h2_spec.md`, `h4_spec.md`.
- Manifest schema: `handoff_manifest.schema.json`.
- Upstream: canonical audit reports under `analysis/canonical/stage*/audit_reports/`.
- KPI definitions: `skills/bsa-orchestrator/references/kpi-definitions.md`.
- Invariants: INV-01, INV-03, INV-07.
