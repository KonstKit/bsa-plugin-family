# H4 Open Items Packet — Content Contract

Authoritative section / content rules for `H4_open_items_packet.md`. Peer specs: `h1_spec.md`, `h2_spec.md`, `h3_spec.md`.

## Purpose

Give the PMO / steering function the **single sink** for unresolved items: what is open, what decisions are needed, who owns each item, when it must close, and how to escalate. H4 is the only valid sink for unresolved items — hard rule from `handoff-contract.md`. Everything open lives here; nothing opens ad-hoc in H1/H2/H3.

## Audience

- **Primary:** PMO, program manager, product owner, steering committee.
- **Secondary:** Sponsor (cross-reads from H1), delivery lead (cross-reads from H2) when an open item blocks their path.
- **Non-audience:** QA (H3).

## Length

- Soft cap: ≤ 4 printed pages.
- Tables dominate; prose only for `## Decisions Required` judgment bodies.
- If H4 grows past 4 pages, the project has an open-item-volume problem that H4 surfaces rather than hides.

## Required Sections

Every `H4_open_items_packet.md` MUST contain these five sections, in this order, with the exact headings below.

### `## Open Items Digest (A51 filtered)`
- Table with columns: `A51Ref | IssueType | Severity | BlockingStatus | RaisedByStage | Age (days) | Summary | Related ClaimID`.
- One row per A51 row with `ResolutionStatus != closed`.
- `IssueType` exactly matches A51 schema: `uncertainty | contradiction | missing_source | decision_needed | boundary_risk`.
- `BlockingStatus` exactly matches A51 schema: `hard | soft | informational`.
- Order: `hard` first, then `soft`, then `informational`; within each tier by descending `Severity`.
- `Summary` ≤ 1 sentence, paraphrased from A51 row — MUST NOT introduce new actors/quantities (INV-03).
- `Age (days)` = handoff emit date − A51 row raise date.

### `## Decisions Required (by severity)`
- Ordered list, grouped by severity (`blocker` → `high` → `medium` → `low`).
- Every item has:
  - A 1-line decision statement (imperative form: "Approve …", "Accept …", "Reject …", "Defer …").
  - Trace `[A51-xxx]` pointing to the underlying A51 row.
  - If the recommendation rests on analyst judgment, `[AJ:C-xxx]` tag with upstream `[C-xxx]` refs (INV-07 rule — analyst_judgment ClaimID must have JustificationRationale referencing ≥ 1 upstream ClaimID different from its own).
  - One-sentence rationale drawn from A59 / A51 — NO new supporting arguments introduced here.
- Decisions authored here may be `CONDITIONAL_PASS` waivers referenced by H3 `## Validation Outcome`.

### `## Suggested Owners`
- Table with columns: `A51Ref | Suggested owner role | Rationale | Backup role`.
- Owner role values are project-specific but MUST match a role named in canonical stakeholder_authority_map or A51 `NextAction` field.
- `Rationale` cites the A51 row's `NextAction` content or a stakeholder-map claim (`[C-xxx]`).
- One row per entry in `## Open Items Digest`; no row may be ownerless (ownerless items return to pipeline via `A51` with `IssueType=decision_needed`).

### `## Target Resolution Windows`
- Table with columns: `A51Ref | Severity | Target resolution date | SLA source | Escalation trigger date`.
- `Target resolution date` derived from severity-to-SLA mapping documented in `skills/bsa-orchestrator/references/sla_mapping.md` (falls back to default SLA when unspecified: blocker = 2 business days, high = 5, medium = 10, low = 20).
- `Escalation trigger date` = `Target resolution date` + `grace window` (default 2 business days).
- `SLA source` names the applicable policy doc or defaults to "orchestrator default".

### `## Escalation Routes`
- Table with columns: `A51Ref | Owner role | Level-1 escalation | Level-2 escalation | Final escalation`.
- Escalation levels are role/group names, not individuals (avoids churn when people rotate).
- `Final escalation` must terminate at a role with decision authority (e.g., `steering_committee`, `sponsor`, `architecture_review_board`).
- Every `hard` BlockingStatus row MUST have all three escalation levels populated; `soft` may leave `Level-2` empty; `informational` may leave `Level-2` and `Final` empty.

## Citation Rules

Same as H1 (`[C-xxx]`, `[AJ:C-xxx]`, `[A51-xxx]`). In `## Decisions Required`, `[AJ:C-xxx]` is the most common marker — the pack is structurally biased toward judgment-heavy content.

## Forbidden Content

- A51 rows that are not also in the canonical A51 register (no H4-only items).
- Decisions that resolve themselves (e.g., "proceed as planned" with no owner and no trace) — those aren't decisions, they're noise.
- Silent blending of open items into H1/H2/H3 — hard violation of `handoff-contract.md` rule 2.
- Analyst-judgment recommendations in H4 without matching A59 analyst_judgment rows (INV-07).

## Audit Binding

- `bsa-no-new-claims-auditor` validates every H4 row traces to A51 / A59.
- `bsa-citation-auditor` validates `[A51-xxx]`, `[C-xxx]`, `[AJ:C-xxx]` resolve.
- `SCN-STAGE78-001-E-H4` (see validation-scenario-manifest.csv) checks H4 shape + A51 coverage (every non-closed A51 row appears).
- `SCN-STAGE78-001-E-H4` also validates that every `[AJ:C-xxx]` tag in H4 `## Decisions Required` points to a real A59 `ClaimType=analyst_judgment` row with a valid `JustificationRationale`.

## Cross-References

- Peer specs: `h1_spec.md`, `h2_spec.md`, `h3_spec.md`.
- Manifest schema: `handoff_manifest.schema.json`.
- Upstream: `analysis/canonical/core_controls/A51_issue_route_register.csv`, `A59_claim_register.csv`.
- Stakeholder map: `analysis/canonical/stage2/stakeholder_authority_map.md`.
- Invariants: INV-01, INV-03, INV-07.
