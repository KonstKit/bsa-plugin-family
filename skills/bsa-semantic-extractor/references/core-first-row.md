# CORE-First Row Contract

## Minimal Stage 3 CORE Row

```text
RowID | ClaimID | A51Ref | SourceID | ExcerptID | ClauseID | EvidenceStatus(F/I/A/Q/C) | Actor | ActionDecision | ObjectData | OutcomeState | Confidence | IssueID
```

## EvidenceStatus enum (epistemic axis)

The `EvidenceStatus` column carries one of five single-letter codes capturing the analyst's epistemic stance on the row at extraction time. Choose exactly one — the codes are mutually exclusive, not a confidence scale.

| Code | Meaning | When to use |
|------|---------|-------------|
| `F` | **Fact** | Row is directly grounded in a bound `SourceID`+`ExcerptID` and the upstream claim is verbatim or near-verbatim. The reader can audit the row by reading the cited excerpt without further inference. |
| `I` | **Inference** | Row is logically derivable from one or more bound excerpts but requires combining or paraphrasing them. The inference step itself must be obvious to a peer reviewer reading the same excerpts. |
| `A` | **Assumption** | Row encodes a working assumption the analyst is carrying forward without direct evidence (e.g., a domain default, a convention from a sister system). MUST also lower `Confidence` and SHOULD route a question to `IssueID` so the assumption is reviewable downstream. |
| `Q` | **Question** | Row is a placeholder for an open question that blocks full extraction. MUST be paired with a routed `IssueID`/`A51Ref`; the row exists so the question is visible in the row register, not as a definite claim. |
| `C` | **Contradiction** | Row records a conflict between two or more bound sources. MUST route to `IssueID` so the contradiction is reconciled before promotion. |

The five codes match the industry-standard epistemic ladder (fact / inference / assumption / open-question / contradiction) and are intentionally distinct from `Confidence` (a 0..1 numeric) and `IssueType` (the A51 routing taxonomy).

## Rules
- At least one of `ClaimID` or `A51Ref` must be populated.
- `SourceID` and `ExcerptID` are mandatory when `ClaimID` is present and `EvidenceStatus` is `F` or `I`.
- `A`, `Q`, and `C` rows MUST lower `Confidence` AND route a question through `IssueID` (or `A51Ref`).
- If classification is uncertain, lower confidence and route to `IssueID`.
- Semantic rows may normalize wording, but may not add new entities, states, or decisions beyond the bound upstream claim.

## Output Files
- `analysis/proposals/stage3/semantic_core_rows.csv`
- `analysis/proposals/stage3/semantic_issues.md`
- `analysis/proposals/stage3/semantic_traceability_report.md`
