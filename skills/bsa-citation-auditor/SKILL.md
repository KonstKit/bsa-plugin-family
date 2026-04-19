---
name: bsa-citation-auditor
description: Audit Stage 7-8 and discovery D5 candidate outputs for citation completeness and overclaim risk using canonical claim-layer controls A58/A59/A60.
---

# BSA Citation Auditor

Run this skill before readiness promotion.

## Scope
- Verify that critical statements map to canonical claim-layer evidence.
- Detect unsupported or weakly supported claims.
- Classify critical unsupported claims for `KPI-003`.
- Reuse the same citation and overclaim logic for D5 discovery synthesis outputs when discovery is enabled.

## Invocation Modes
- Main cycle:
  - Read from `analysis/proposals/stage7_8/stage7/` plus canonical `A58/A59/A60`.
  - Write `citation_audit_report.md|json` into `analysis/proposals/stage7_8/stage7/`.
  - Supports optional marker `stage7.citation_audit.pass.json` when enabled by run profile.
- Discovery (D5):
  - Read from `analysis/discovery/proposals/d5/` plus discovery claim-layer controls.
  - Write `discovery_citation_audit_report.md` into `analysis/discovery/proposals/d5/`.
  - Supports marker `discovery.d5.citation_audit.pass.json`.
- Mode is routed by orchestrator; do not self-select mode from chat text.

## Inputs
- Canonical/discovery `A58/A59/A60` according to active mode.
- Candidate synthesis package in active mode proposal path.

## Outputs
- `analysis/proposals/stage7_8/stage7/citation_audit_report.md`
- `analysis/proposals/stage7_8/stage7/citation_audit_report.json`
- `analysis/discovery/proposals/d5/discovery_citation_audit_report.md`

## Workflow
1. Read canonical `A58/A59/A60` and Stage 7/8 proposal outputs.
2. Build citation coverage table (`statement -> ClaimID/A51Ref`).
3. Flag unsupported critical claims.
4. Emit `citation_audit_report.md` and `citation_audit_report.json` in `analysis/proposals/stage7_8/stage7/`.
5. For discovery reuse, emit `discovery_citation_audit_report.md` in `analysis/discovery/proposals/d5/`.

## Invariant
- Readiness cannot pass when critical unsupported claims > 0.

## EpistemicInsufficiency findings (Sprint 3 US-S3-03)
In addition to classical "critical unsupported claims" detection (KPI-003 = 0), this auditor emits `EpistemicInsufficiency` findings on claims with `Criticality=1` whose supporting tier mix fails the epistemic-sufficiency rule from `../bsa-evidence-intake/references/reliability_tier_spec.md`.

Finding sub-types:
- `EpistemicInsufficiency / low_tier_only` — critical claim supported exclusively by T4-T5 sources; no T1-T3 anchor and no `A51Ref` waiver.
- `EpistemicInsufficiency / not_independent` — critical claim supported by ≥ 2 T4 sources but all supporting pairs fail independence (per the 2-of-4-conditions rule: different author, different artifact type, ≥ 6-month time gap, different stakeholder role).
- `EpistemicInsufficiency / anecdotal_only` — critical claim supported only by T5 rows all carrying `anecdotal=true`.
- `EpistemicInsufficiency / judgment_on_low_tier` — critical `ClaimType=analyst_judgment` row whose `JustificationRationale` references upstream ClaimIDs whose supporting sources are all T4-T5.

Gate behavior:
- Each finding routes via `A51` with `IssueType=missing_source`, `BlockingStatus=hard`, `RaisedByStage=stage7`.
- Stage 7/8 promotion is halted until either (a) a stronger supporting source is added and the claim rebound, or (b) an explicit `A51Ref` waiver is attached to the claim with sponsor sign-off.
- Findings appear in `citation_audit_report.md` with sub-type enumeration; the JSON companion groups findings by sub-type for downstream tooling.

Independence check algorithm:
For each critical claim with N supporting sources, build the pair graph over (source_i, source_j) for all i < j. A pair is "independent" if ≥ 2 of the 4 independence conditions hold. A claim has independent support iff EVERY pair in its supporting set is independent OR a single-source T1-T3 path exists. Partially-independent (some pairs independent, some not) counts as NOT independent and triggers `not_independent`.

## On Audit Failure
1. Emit failing report with statement-level findings.
2. Do not emit pass marker.
3. Route unresolved evidence gaps to shared `A51`.
4. Request producer rework in the same mode path and re-audit.

## Reference
- [references/citation-and-overclaim.md](references/citation-and-overclaim.md)
