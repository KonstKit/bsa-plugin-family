---
name: bsa-nfr-collector
description: Extract non-functional requirements (performance, availability, scalability, security, usability, compliance, maintainability, observability, portability) from promoted A59 claims + H2 delivery packet into A62_nfr_register.csv. Each NFR must carry non-empty SourceClaimIDs (INV-08) and, for measurability-required categories, non-empty Metric + Target (INV-09). Phase 3 skill — runs after stage8.no_new_claims.pass and handoff.ready.
---

# BSA NFR Collector

Run this skill AFTER the main cycle has promoted Stage 8 and the handoff package is ready. NFR extraction reads the promoted claim layer and produces the first Phase-3 canonical artifact (`A62_nfr_register.csv`).

## Scope

- Scan promoted A59 claims (with focus on `ClaimType=analyst_judgment` and high-criticality `inference` rows) for non-functional requirements.
- Categorize each extracted NFR per ISO/IEC 25010-style attributes.
- For measurable categories (performance / availability / scalability), populate Metric + Target.
- For qualitative categories (usability / compliance), populate TestabilityNotes.
- Emit A62 proposal rows that link back to source claims via `SourceClaimIDs`.

Out of scope:
- Authoring new claims — NFRs MUST derive from existing A59 rows; no net-new claim content (same discipline as INV-03).
- Deciding prioritization — Criticality values come from upstream claim Criticality, not re-derived here.
- Jira/Linear export — that's `bsa-backlog-bridge` (Sprint 9).

## Inputs

- Promoted `analysis/canonical/core_controls/A59_claim_register.csv`
- Promoted `analysis/canonical/core_controls/A50_source_register.csv`
- Promoted `analysis/handoff/H2_delivery_packet.md`
- Shared `analysis/canonical/core_controls/A51_issue_route_register.csv`

## Outputs

- `analysis/proposals/phase3/A62_nfr_register.csv`
- `analysis/proposals/phase3/nfr_extraction_report.md`

Both land under `analysis/proposals/phase3/` — promotion to `analysis/canonical/core_controls/A62_nfr_register.csv` goes through `/bsa-promote` like any other canonical artifact.

## Workflow

1. Load promoted A59; filter to rows where `ClaimType=analyst_judgment` OR (`ClaimType=inference` AND `Criticality IN (level-1, level-2)`).
2. For each candidate row, decide:
   - Is this claim about a quality attribute (performance, availability, etc.)? If not — skip, it's functional.
   - Which ISO 25010 category fits best? Use the enum in `a62.schema.json`.
3. Author an A62 row:
   - `NFRID` — NFR-NNN or NFR-XXX-NNN (category-prefixed; e.g., NFR-PERF-001 for performance items makes the register skimmable).
   - `NFRCategory` — chosen enum value.
   - `Statement` — rephrase the claim into canonical NFR form: "The <subject> SHALL <quality> <under-conditions>". Do not invent new content — stay bound to the claim text.
   - `SourceClaimIDs` — the C-NNN ClaimID(s) this NFR derives from (INV-08).
   - `MeasurabilityType` — quantitative / qualitative / hybrid.
   - `Metric` + `Target` — required for performance/availability/scalability (INV-09). Pull numbers from the claim if present; route through A51 as `decision_needed` if absent.
   - `TestabilityNotes` — how this NFR will be verified. Required non-empty for every row.
   - `Criticality` — inherit from the source ClaimIDs (highest level wins if multiple sources).
   - `A51Ref` — populate if extraction surfaced a contradiction / missing metric / decision.
4. If a claim clearly describes an NFR but has no measurable Metric/Target and the category requires one, author an A51 row (`IssueType=decision_needed`, `NextAction=Provide metric+target for <NFR>`) and set `A51Ref` on the A62 row.
5. Emit `nfr_extraction_report.md` summarizing: total claims scanned, claims classified as NFR, distribution across categories, per-category measurability gaps, A51 routes raised.

## Invariants

- **INV-08 (Phase 3)**: Every A62 row MUST have a non-empty `SourceClaimIDs` list. NFRs authored from thin air are rejected at the hook layer (`governance/schemas/a62.schema.json` pattern) and by this skill's own output check.
- **INV-09 (Phase 3)**: For `NFRCategory IN (performance, availability, scalability)`, `Metric` and `Target` MUST be non-empty (OR a `decision_needed` A51Ref must be populated). Enforced post-schema by this skill's own validator (cross-field, outside JSON Schema's `if/then` comfort zone for CSV-row semantics).
- **INV-07 (reaffirmed)**: NFR extraction never produces new A59 claims — the claim layer is upstream and immutable at this point.

## Failure modes

- **No candidate claims in A59** — emit `nfr_extraction_report.md` with `NFRs extracted: 0, reason: no analyst_judgment / high-criticality inference rows matched`. Not an error — some engagements are purely descriptive.
- **Measurability gap without A51 route** — skill refuses to write the A62 row if a performance/availability/scalability category lacks Metric+Target AND no `A51Ref` was created. Operator must either provide the metric or raise an A51 decision.
- **Upstream A59 not promoted** — skill exits with error; A62 depends on canonical A59, not proposals.

## Composition

This skill runs as part of the composite `/bsa-dev-handoff` command (Sprint 6, US-S6-03). It may also be invoked directly via `/bsa-stage phase3.nfr run` for debugging / partial re-runs.

Downstream consumers (`bsa-story-writer`, `bsa-traceability-matrix`) read promoted A62; they do not invoke this skill directly (per INV-06 composition-via-orchestrator).

## Cross-refs

- `governance/schemas/a62.schema.json` — row schema + measurability extension.
- `docs/phase_3_plan.md` — Phase-3 overall plan + US breakdown.
- `skills/bsa-claim-binder/SKILL.md` — upstream claim-layer contract (mirrored discipline).
- `skills/bsa-no-new-claims-auditor/SKILL.md` — the downstream auditor that enforces "no new claims in handoff"; the same pattern applies to NFR extraction.
