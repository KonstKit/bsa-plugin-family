# CORE-First Row Contract

## Minimal Stage 3 CORE Row

```text
RowID | ClaimID | A51Ref | SourceID | ExcerptID | ClauseID | EvidenceStatus(F/I/A/Q/C) | Actor | ActionDecision | ObjectData | OutcomeState | Confidence | IssueID
```

## Rules
- At least one of `ClaimID` or `A51Ref` must be populated.
- `SourceID` and `ExcerptID` are mandatory when `ClaimID` is present.
- If classification is uncertain, lower confidence and route to `IssueID`.
- Semantic rows may normalize wording, but may not add new entities, states, or decisions beyond the bound upstream claim.

## Output Files
- `analysis/proposals/stage3/semantic_core_rows.csv`
- `analysis/proposals/stage3/semantic_issues.md`
- `analysis/proposals/stage3/semantic_traceability_report.md`
