# Shared Control Surface Contracts

## Shared Canonical Surfaces
- `A48_run_context_card.md`
- `A50_source_register.csv`
- `A51_issue_route_register.csv`

## A48 Minimal Fields
- `RunID`
- `RequestType`
- `Mode` (`direct` | `discovery_then_bsa`)
- `ProblemStatement`
- `InScope`
- `OutOfScope`
- `EntryCondition`
- `CurrentStage`
- `SelectedPath` (or `TBD`)
- `CanonPolicyVersion`

## A50 Minimal Columns
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

## A51 Minimal Columns
- `A51Ref`
- `IssueType` (`uncertainty|contradiction|missing_source|decision_needed|boundary_risk`)
- `Severity`
- `BlockingStatus` (`hard|soft|informational`)
- `RaisedByStage`
- `RelatedSourceID`
- `RelatedClaimID`
- `NextAction`
- `ResolutionStatus`

## Global Rules
- Discovery and main-cycle reference the same canonical `A48/A50/A51`; mirrored ledgers are forbidden.
- Any unreadable, inaccessible, or missing source becomes an `A51` route before downstream synthesis.
- Any promoted statement, row, or anchor must trace to `ClaimID` or explicit `A51Ref`.
- `A51` is not a claim source; it is a container for unresolved items, contradictions, and guarded hypotheses.
- `CanonPolicyVersion` changes require explicit compatibility handling defined in `contract-versioning.md`.
