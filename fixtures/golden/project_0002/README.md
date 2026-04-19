# Fixture project_0002 — Data-Lineage Audit (Prep Shell)

Second golden fixture for the BSA plugin family. Landed in **Sprint 2 US-S2-03** as a **prep shell** (scenario + inputs + metadata only); Sprint 4.5 US-S45-01 will populate the full `expected_outputs/` tree once Sprints 3 and 4 stabilize the Stage 3-8 contracts.

## Why this fixture exists

The Sprint 2 plan requires at least two golden fixtures before v1.0.0 so that pipeline-level changes in Sprint 3 (sidecar contracts, merge/dedup rules, ReliabilityTier operationalization, drift detection, marker-chain validator) have **more than one** regression baseline. `project_0001` is a process-path direct-mode fixture; this one deliberately differs on three axes:

| Axis | `project_0001` | `project_0002` (this) |
|---|---|---|
| Pipeline path | process-path (ticket intake → triage → outcome) | **structural-path** (data boundaries, lineage edges, model ownership) |
| Run mode | `direct` | **`discovery_then_bsa`** |
| Domain | support-ticket operations | **data-lineage / analytics platform** |
| Tier mix | primarily T1/T2 (process notes + PM interview) | **mixed T2 + T4** (production config + attestation interview) |

Together the two fixtures exercise both pipeline modes and both paths on independent domains.

## Scenario

A mid-size product organization runs an internal analytics platform. Raw event data lands in a lake, gets staged by a small data-engineering team, then promoted into dimensional models by analytics engineering, and finally consumed by BI dashboards. Ownership between data-engineering, analytics-engineering, and BI is informal; there is no canonical map of which team owns which layer, and model-lineage documentation drifts behind actual dbt DAG changes.

The analyst invokes BSA in **discovery mode** because:

- Scope is fuzzy ("document lineage and boundaries" is not yet a crisp problem statement)
- Multiple stakeholder teams disagree on ownership lines
- No single authoritative source-of-truth exists (dbt config is partial, team wiki is stale, interviews produce conflicting boundaries)

Expected D0 → BSA flow (to be populated in Sprint 4.5):

1. **D1 problem framing** surfaces the fuzzy scope and flags ownership ambiguity as an open A51 item.
2. **D2 research** intakes the dbt config and analyst interview; classifies the interview verbatim as T4 attestation (not promoted to claim without a second source).
3. **D3 prioritization** identifies lineage-boundary clarity as the highest-value discovery question.
4. **D4 feasibility** routes the ownership decision to A51 (decision_needed) because no single stakeholder can unilaterally settle it.
5. **D5 synthesis** produces a Discovery Report recommending BSA structural path rather than process path.
6. **BSA main cycle** enters Stage 1 with the discovery seed and the T2+T4 source mix carried forward.

## Inputs

- `inputs/source_001_dbt_project.yml` — T2 (authored-primary): a sanitized snippet from a production dbt config. Shows staging → marts model hierarchy with implicit ownership by schema naming convention.
- `inputs/source_002_ae_interview.md` — T4 (attestation): a transcribed interview with an analytics engineer describing pain points around lineage drift and cross-team handoffs. Interview is contemporaneous but contains subjective characterizations (rough percentages, "I think", "probably").

Both inputs are synthetic and contain no real company, person, or system identifiers.

## Intended `ReliabilityTier` mix

- T2 authored-primary: `source_001_dbt_project.yml` — production configuration file, written by system owner, current-state.
- T4 attestation: `source_002_ae_interview.md` — recorded interview verbatim, single stakeholder perspective, current-week recency.

When Sprint 3 US-S3-03 operationalizes `ReliabilityTier`, this mix will exercise:

- Tier-delta = 2 conflict-resolution rule (AC-3 of US-S3-03): if the two sources disagree, higher-tier (T2) wins by default.
- Independence rule (AC-2): the two sources are independent — different author (owner vs analyst), different artifact type (config vs interview), different stakeholder role.
- Critical-claim epistemic sufficiency: any `Criticality=1` claim supported only by T4 would trip the `EpistemicInsufficiency` finding.

## What this fixture currently validates

- `scripts/fixture_runner.py --fixture project_0002 --mode=validate` → PASS via the prep-shell branch (US-S2-03 AC-3). The runner detects `authoring_mode: synthetic_representative_prep` in `fixture_metadata.json` and validates only the shell (metadata keys, README presence, inputs non-empty) — it does NOT require the canonical CSVs, markers, or audit expectations yet.
- CI stays green on this fixture while Sprint 3 / Sprint 4.5 build out the full state.

## What Sprint 4.5 US-S45-01 will add

- `expected_outputs/discovery/` — D1-D5 proposal and canonical artifacts.
- `expected_outputs/canonical/core_controls/A48..A60` — populated with discovery-seeded rows.
- `expected_outputs/canonical/stage1..stage8/` — BSA main-cycle artifacts.
- `expected_outputs/handoff/` — H1-H4 pack (per US-S2-01 specs), with structural-path evidence of how the discovery seed was lifted into main canonical claims.
- `expected_markers/` — full discovery + main-cycle marker chain.
- `audit_expectations.json` — per-audit verdict expectations.
- `fixture_metadata.json` — `authoring_mode` flipped from `synthetic_representative_prep` to `synthetic_representative` (or `captured_live` for Sprint-4.5 live runs).

## Links

- Sprint plan entry: `US-S2-03` in `/Users/kkitanin/.claude/plans/dreamy-wiggling-zebra.md`.
- Per-axis contrast with `project_0001`: see table above.
- Sprint 4.5 follow-up: `US-S45-01` AC-1 references this shell as its starting point.
- ReliabilityTier model (planned Sprint 3): `US-S3-03`.
