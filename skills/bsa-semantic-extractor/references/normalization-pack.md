# Semantic Normalization Pack Contract

## Extended Row Shape

```text
RowID | ClaimID | A51Ref | SourceID | ExcerptID | ClauseID | EvidenceStatus | FragmentClass | MainPredicate | Actor | ObjectData | Trigger | ConditionRole | ConditionExpr | TimeRole | TimeExpr | Outcome | StateCandidate | NormativityCode | ReqType | FailureAlt | Confidence | IssueID
```

## Activation Rule
- Non-default and trigger-only.
- CORE rows must always be produced first.
- Trigger note must state reasons and decision (`ON`/`OFF`).

## Output Files
- `analysis/proposals/stage3/semantic_normalization_rows.csv`
- `analysis/proposals/stage3/normalization_trigger_note.md`
