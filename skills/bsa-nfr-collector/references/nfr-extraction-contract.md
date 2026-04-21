# NFR Extraction Contract

This reference formalizes what `bsa-nfr-collector` may and may not emit. Consumers (`bsa-story-writer`, `bsa-test-scenario-builder`) rely on this contract; violating it breaks downstream skills.

## Category taxonomy (ISO/IEC 25010-aligned)

| Category | Typical pattern | Measurability required? |
|---|---|---|
| `performance` | Latency, throughput, resource consumption | **Yes** (Metric + Target non-empty) |
| `availability` | Uptime, SLA, recovery time | **Yes** |
| `scalability` | Concurrent users, data volume growth | **Yes** |
| `security` | Auth, encryption, threat mitigation | TestabilityNotes required; Metric/Target optional |
| `usability` | Accessibility, UX, learnability | TestabilityNotes required |
| `compliance` | GDPR/HIPAA/SOC2/industry regs | TestabilityNotes required |
| `maintainability` | Code quality, docs, test coverage | TestabilityNotes required |
| `observability` | Logging, monitoring, tracing | TestabilityNotes required |
| `portability` | Platform/browser/env support | TestabilityNotes required |

## Derivation rules

**Rule 1 — Claim filter.** A claim is an NFR candidate iff:
- `ClaimType = analyst_judgment` (explicit recommendation / quality statement), OR
- `ClaimType = inference` AND `Criticality IN (level-1, level-2)` AND the claim text describes a quality attribute rather than a functional step.

**Rule 2 — Category assignment.** Each extracted NFR gets exactly one category. If a claim seems to span two categories, split into two A62 rows with the same `SourceClaimIDs` — this is more honest than a blended category.

**Rule 3 — Statement rephrasing.** The NFR `Statement` should be canonicalized into `<subject> SHALL <quality> <conditions>` form. Extraction MUST NOT introduce facts not in the source claim. Example:

Source claim: *"JB expects the triage agent to handle roughly 50 customers at once"*
Acceptable NFR statement: *"The triage agent SHALL support ≥ 50 concurrent users"*
NOT acceptable: *"The triage agent SHALL support 50 concurrent users with p95 latency < 200ms"* — the p95/200ms detail is net-new, not in the source. If you think a Metric+Target is implied, route through A51 (`decision_needed`) and write the statement without the invented precision.

**Rule 4 — Metric/Target rules for measurability-required categories.** If Rule 2 assigns `performance / availability / scalability` and the source claim DOES name a number:
- Extract it verbatim as `Target` (with units).
- Infer the `Metric` from the number's shape ("50 users" → `concurrent users`; "99.9%" → `availability percentage`; "< 500ms p95" → `p95 latency ms`).

If the source claim does NOT name a number:
- Author an A51 row: `IssueType=decision_needed`, `NextAction="Provide Metric + Target for NFR <NFRID>"`, `RaisedByStage=phase3.nfr`.
- In the A62 row, leave `Metric` and `Target` empty; populate `A51Ref` with the new A51 row.
- Do NOT invent numbers.

**Rule 5 — Testability notes.** Required non-empty for every row regardless of category. If you don't know how to verify an NFR, it's not yet a requirement — escalate via A51.

**Rule 6 — Criticality inheritance.** The A62 row's `Criticality` is the HIGHEST (most severe) of the source claims' Criticality values (level-1 < level-2 < level-3 where 1 is most critical).

**Rule 7 — Traceability.** Every A62 row carries `SourceClaimIDs` pointing to ≥ 1 A59 row. Multiple claims derive one NFR → semicolon-join. One claim fans out to multiple NFRs → one A62 row per NFR, each referencing the same ClaimID.

## Report shape (nfr_extraction_report.md)

```markdown
# NFR Extraction Report

## Summary
- Claims scanned: 42
- Candidate NFR rows considered: 15
- A62 rows emitted: 12
- A51 routes raised: 3 (decision_needed × 3 for missing metrics)

## Category distribution
| Category | Rows | Level-1 | Level-2 | Level-3 |
|---|---|---|---|---|
| performance | 4 | 2 | 2 | 0 |
| availability | 2 | 2 | 0 | 0 |
| ...

## Measurability gaps raised
| NFRID | Gap | A51Ref |
|---|---|---|
| NFR-PERF-002 | No latency target specified in source claim | A51-DEC-014 |
```

## Acceptance criteria

The skill's output passes iff:

1. Every A62 row validates against `governance/schemas/a62.schema.json` (F5 enforces this at write time).
2. For every row with `NFRCategory IN (performance, availability, scalability)`:
   - `Metric` non-empty AND `Target` non-empty, OR
   - `A51Ref` non-empty (measurability gap raised).
3. Every row's `TestabilityNotes` is non-empty.
4. Every `SourceClaimIDs` value references a ClaimID that exists in the promoted A59.
5. No NFR statement introduces quantities / subjects / conditions absent from the source claims.

## Integration with Phase-3 auditors

Like the main-cycle no-new-claims auditor, a Phase-3 equivalent ("no-new-nfr auditor" — Sprint 7 US-S7-03) will run against A62 pre-promotion and ensure no content leaks in that isn't traceable to upstream claims.
