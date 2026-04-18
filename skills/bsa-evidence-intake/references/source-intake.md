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
