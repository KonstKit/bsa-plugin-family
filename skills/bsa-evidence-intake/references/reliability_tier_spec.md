# ReliabilityTier Specification

Authoritative definition of the 5-tier reliability model used across `A50_source_register.csv` and propagated into `A59_claim_register.csv.ClaimStrength`. Consumed by:

- `bsa-evidence-intake` at Stage 1 (assigns `ReliabilityTier` on each A50 row).
- `bsa-claim-binder` at Stage 1→3 (computes `ClaimStrength` on each A59 row).
- `bsa-citation-auditor` at Stage 3 + Stage 7 (enforces `EpistemicInsufficiency` on critical claims).
- `bsa-orchestrator` KPI-001 reporting (weighted coverage).
- `bsa-orchestrator` discovery→main merge (`source_tier_mismatch` resolution).

## Rationale: why 5 tiers

The previous 6-tier informal model blended source *kind* (code, doc, interview, notes) with source *recency* and *signedness*, which made tier assignment ambiguous — the same interview could land in two different tiers depending on which dimension the annotator emphasised. The 5-tier model cuts along a single axis: **epistemic proximity to the underlying system state**, borrowing structure from:

- **NIST SP 800-53** source categorisation (primary empirical observation → authored → attestation → reported hearsay).
- **CMMI / ISO 9000 maturity levels** (observed execution > documented policy > verbal description).

Anecdotal evidence is NOT a separate tier. It lives inside T5 (`reported`) with an explicit `anecdotal=true` flag in `A50.Notes`; this prevents anecdotes from escaping the bottom tier through ambiguous classification.

## The 5 tiers

| Tier | Name | Semantics | Examples | Weight |
|---|---|---|---|---|
| **T1** | empirical | Live system state: direct measurement, observed execution, real-time telemetry. | Live DB query output, production logs (< 48h), runtime observation transcripts, metric snapshots from observability tooling. | **1.00** |
| **T2** | authored-primary | Primary-source artifact authored by the system's owner/maintainer, currently active. | Production code (current HEAD), signed contract, regulation text, enforced policy, public API schema. | **0.85** |
| **T3** | authored-secondary | Secondary-source artifact authored by a knowledgeable party, possibly stale. | ADR, engineering wiki page with owner+date, architecture doc in the team's own repo, committee minutes. | **0.65** |
| **T4** | attestation | Recorded statement by a stakeholder describing system state (without direct observation). | Recorded interview verbatim, signed questionnaire response, transcript of architecture-review discussion. | **0.45** |
| **T5** | reported | Secondhand description, hearsay, anecdote, recollection after the fact. | Slack-thread summary, hallway recollection, PM-verbatim "I think maybe ~15%" quotes, forwarded email describing a conversation. | **0.20** |

### Tier-assignment discipline

- **Exactly one tier per source.** If a source legitimately spans tiers (e.g., a wiki page with fresh observations embedded), split into two A50 rows at intake time.
- **Tier is about the source, not the claim.** A claim derived from a T1 source can still be weak for other reasons (inference density, narrow sample); tier captures only source-epistemic proximity.
- **Recency is NOT a tier modifier.** A stale T2 (production code from 18 months ago) is still T2. Recency enters via the `DateOrVersion` column and the optional decay factor below.
- **`anecdotal=true`** in A50.Notes is the only per-row tier flag. It tags T5 rows where the analyst is explicitly marking "this is hearsay without direct attribution".

## Independence definition

Two sources are **independent** when at least **2 of the following 4 conditions** hold:

1. **Different author / owner.** Distinct stakeholders or system owners (PM ≠ Engineer; Team A ≠ Team B).
2. **Different artifact type.** Code ≠ document ≠ interview ≠ live observation. Two documents from the same author in the same week are NOT different types.
3. **Time gap ≥ 6 months OR across a major org/system event.** A re-org, a major release, a regulatory change, or an SLA overhaul all count as events that break continuity.
4. **Different stakeholder role.** PM ≠ Engineer ≠ Ops ≠ Security ≠ Compliance ≠ User. Two PMs from the same org do NOT count as different roles.

Two sources authored by the same person in the same quarter (same role, same artifact type, no intervening event) are **not independent**, even if the titles differ.

Independence is a **pairwise** property: given a set of N sources supporting the same claim, independence is asserted over the pair-graph. A claim with 3 supporting sources where only 2 of the 3 pairs are independent has "partially-independent" support — downstream rules treat it as dependent unless all pairs clear the bar.

## Conflict resolution

When two A59 claims (or two A50 sources claimed to support the same content) disagree on substance or on source tier, the orchestrator resolves per this policy:

### By tier delta

| Tier-delta | Policy |
|---|---|
| **≥ 2** (e.g., T1 vs T3, T2 vs T4) | **Higher-tier wins by default.** The lower-tier row is auto-marked `SupersededBy=<higher-tier ClaimID>` in A59. Orchestrator logs `source_tier_mismatch` with `resolution=soft_resolved`. Analyst can override with an explicit A51 route if needed. |
| **≤ 1** (e.g., T1 vs T2, T3 vs T4) | **Contested — neither wins automatically.** Both rows get `ClaimStatus=contested`. Orchestrator auto-routes via A51 with `IssueType=cross_tier_contradiction`, `BlockingStatus=hard`. Downstream stage promotion is blocked until manual resolution. |
| **same tier** | Same as ≤ 1 — contested, auto-route, hard-block. |

### By anecdotal flag

A T5 source with `anecdotal=true` **never overrides** a non-anecdotal source of any tier, regardless of raw tier-weight delta. Anecdotal claims can supplement (contribute to `ClaimStrength`) but cannot supersede.

### Supplementary rules

- `SupersededBy` relationships are transitive: if A is superseded by B and B is superseded by C, A is superseded by C (auditor MUST compute the transitive closure for KPI-001 reporting).
- A claim marked `contested` contributes **0** to KPI-001 weighted coverage until resolved — contested claims are not "covered".
- Resolution of a contested pair is always an analyst action (edit the proposal layer, re-run promotion); the orchestrator never silently picks a winner at tier-delta ≤ 1.

## ClaimStrength formula

The `ClaimStrength` column on `A59_claim_register.csv` is computed by `bsa-claim-binder` at claim-binding time:

```
ClaimStrength = max_supporting_tier_weight × (1 - decay_factor)
```

Where:

- `max_supporting_tier_weight` — the **highest** tier weight across all A50 rows bound (via SourceID) to this claim's ExcerptID set. A claim supported by both T1 and T3 sources takes T1's weight (1.00). A claim with only T5 support takes 0.20.
- `decay_factor` — optional time-decay correction in `[0, 1)`. Default 0 (no decay). When applied, derived from `AsOfDate` of the **supporting source** (the one whose tier weight won the `max()` in the formula) per the decay schedule below.

### Decay schedule (optional, default off)

Decay is a Sprint-3.5 / Sprint-4 refinement — Sprint 3 ships the formula but leaves `decay_factor=0` by default. When/if decay is enabled for a project, the schedule is:

| Tier | Half-life | Rationale |
|---|---|---|
| T1 | 7 days | Live state staleness is catastrophic; yesterday's DB snapshot already drifts. |
| T2 | 12 months | Current-HEAD code or an active contract stays reliable across a release cycle but not across two. |
| T3 | 18 months | Wiki and ADR content drifts slowly; major org events reset the clock. |
| T4 | 6 months | Attested stakeholder statements stale quickly — staffing and priorities shift. |
| T5 | 3 months | Recalled details fade fast. |

`decay_factor = 1 - 2^(-age_in_tier_half_lives)`, capped at `0.80` so no claim drops below 20% of its undecayed strength. The cap is a guard against the formula producing `ClaimStrength ≈ 0` just because a row is old — if a claim is genuinely stale to that degree, it should be routed via `A51` with `IssueType=missing_source` rather than carried forward with near-zero weight.

## ClaimType interaction

- `ClaimType=direct` and `ClaimType=inference` — `ClaimStrength` computed per formula above.
- `ClaimType=analyst_judgment` (INV-07) — `ClaimStrength` is LEFT BLANK. These rows use JustificationRationale + upstream ClaimIDs for validation, not tier weights. The KPI-001 denominator excludes `analyst_judgment` rows (only direct claims count in KPI-001 per its definition).

## Critical claim epistemic sufficiency

A claim with `Criticality=1` (the highest criticality bucket — typically claims that gate a downstream decision or commitment) faces stricter tier requirements:

### Hard requirement

A critical claim MUST be supported by at least one of:

1. A single T1-T3 source, OR
2. Two or more **independent** T4 sources (independence per the 2-of-4-conditions rule above), OR
3. An explicit `A51Ref` route acknowledging the epistemic gap.

### `EpistemicInsufficiency` finding

`bsa-citation-auditor` emits an `EpistemicInsufficiency` finding when a critical claim fails the hard requirement. Sub-types:

- `EpistemicInsufficiency / low_tier_only` — critical claim supported only by T4-T5 sources.
- `EpistemicInsufficiency / not_independent` — critical claim supported by ≥ 2 T4 sources but the sources fail independence (same author + same artifact type + no time gap + same role).
- `EpistemicInsufficiency / anecdotal_only` — critical claim supported only by T5 rows all carrying `anecdotal=true`.

Each sub-type routes to A51 with `IssueType=missing_source`, `BlockingStatus=hard`. Promotion halts until the finding is either resolved (stronger source added) or explicitly waived via A51Ref attached to the claim.

### analyst_judgment critical rule

A `ClaimType=analyst_judgment` claim with `Criticality=1` has a separate rule: the `JustificationRationale` MUST reference at least one upstream ClaimID whose supporting source is T1-T3. Judgments anchored exclusively on T4-T5 evidence are `EpistemicInsufficiency / judgment_on_low_tier` findings.

## KPI-001 formula update

Pre-Sprint-3 KPI-001 was an unweighted coverage ratio:

```
KPI-001 = covered_direct_claims / total_direct_claims
target: >= 0.90
```

Post-Sprint-3 KPI-001 is weighted by `ClaimStrength`:

```
KPI-001 = sum(ClaimStrength for direct claims with bound SourceID+ExcerptID) / count(all direct claims)
target: >= 0.75
```

Rationale for the target drop from 0.90 to 0.75: the weighted denominator is `count()` not `sum()` — a fully-covered T5-only claim contributes 0.20, not 1.00 — so the numerator is structurally lower even when coverage is complete. The 0.75 target is calibrated against synthetic mixed-tier fixtures (project_0001 mixed T1/T2 content lands at ~0.82 once tiers are populated). The target is revisited after 3 real projects.

### Per-tier breakdown

KPI-001 reporting MUST expose a per-tier breakdown alongside the aggregate weighted score:

```
KPI-001 breakdown:
  T1 sources bound to 12 direct claims  → contribution 12.00
  T2 sources bound to  8 direct claims  → contribution  6.80
  T3 sources bound to  5 direct claims  → contribution  3.25
  T4 sources bound to  3 direct claims  → contribution  1.35
  T5 sources bound to  2 direct claims  → contribution  0.40
  Total direct claims:                    30
  Weighted coverage:                      23.80 / 30 = 0.793  (PASS vs 0.75)
```

This breakdown appears in `analysis/canonical/stage3/audit_reports/citation_audit_report.md` and is carried forward into the H3 KPI Scorecard section via the handoff packager.

## Migration from pre-Sprint-3 fixtures

Fixtures authored before Sprint 3 (i.e., `project_0001` at v0.95) use literal `ClaimStrength` values (`0.65`, `0.45`) without tier-weight derivation. Sprint 3 closes this gap by:

1. Populating `A50.ReliabilityTier` explicitly on every source (no blank or default).
2. Recomputing `A59.ClaimStrength` via the formula.
3. Updating the fixture expected-output to match.

Migration is idempotent (same input → same `ClaimStrength`). The fixture metadata `canon_policy_version` bumps to `0.96` for the tier-operational cohort and ultimately to `1.0.0-rc1+hash:...` at Sprint 3 close via US-S3-04.

## Cross-references

- `skills/bsa-evidence-intake/references/source-intake.md` — A50 column definitions (ReliabilityTier enum).
- `skills/bsa-claim-binder/SKILL.md` — ClaimStrength propagation invariants.
- `skills/bsa-citation-auditor/SKILL.md` — EpistemicInsufficiency findings and gate logic.
- `skills/bsa-orchestrator/references/kpi-definitions.md` — KPI-001 weighted formula.
- `skills/bsa-orchestrator/references/discovery_to_main_merge.md` — `source_tier_mismatch` resolution uses this spec's tier ordering.
- Invariants: `governance/immutable_invariants.md` — INV-01 (evidence-binding; tier weights compose with evidence presence), INV-07 (ClaimType closed; analyst_judgment bypasses tier-weight but adds judgment-on-low-tier rule).
