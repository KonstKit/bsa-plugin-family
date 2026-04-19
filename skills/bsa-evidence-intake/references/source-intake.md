# Source Intake Contract

## Stage 1 Proposal Artifacts
Write under `analysis/proposals/stage1/`:
- `source_inventory.md`
- `source_manifest.csv`
- `source_coverage.md`
- `contradiction_scan.md`
- `missing_sources.md`
- `a50_a51_seed_updates.md`

## Source Manifest Columns
- `SourceID`
- `SourceType`
- `Title`
- `Origin`
- `AccessStatus`
- `ReliabilityTier`
- `Priority`
- `Language`
- `DateOrVersion`
- `Notes`

## Required Semantics
- Contradiction rows must identify impacted `A51` route.
- Missing-source rows must classify blocking status (`hard`, `soft`, `informational`).
- Any inaccessible source must remain `AccessStatus != readable` and receive an `A51` route; its contents must not be inferred.
- Contradiction and missing-source outputs must be reusable by `bsa-claim-binder` for `A60` population.
- `ReliabilityTier` MUST be exactly one of `T1 | T2 | T3 | T4 | T5` per [reliability_tier_spec.md](reliability_tier_spec.md); blank values are rejected at promotion. Tier assignment is about the source's epistemic proximity to the underlying system state, NOT about recency (recency is tracked in `DateOrVersion` and optionally weighted via the decay factor defined in the tier spec).
- A T5 source that is pure hearsay, recollection, or anecdote MUST carry `anecdotal=true` in the `Notes` field. The `anecdotal=true` flag is the only per-row tier modifier; it disqualifies the source from superseding any non-anecdotal claim regardless of tier-delta.
- If a source legitimately spans tiers (e.g., a wiki page containing both archived policy text and fresh live observations), split it into two A50 rows at intake — each row with a single tier.
