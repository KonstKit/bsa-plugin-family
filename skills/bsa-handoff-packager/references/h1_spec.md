# H1 Executive Brief — Content Contract

Authoritative section / content rules for `H1_exec_brief.md`. This is the first of the four H-pack specs; peers are `h2_spec.md`, `h3_spec.md`, `h4_spec.md`.

## Purpose

Give an executive sponsor (decision-owner with limited time) enough grounded signal to decide whether to proceed, pivot, or hold. H1 is the **answer first** artifact: it opens with the recommendation, not with the analysis that produced it.

## Audience

- **Primary:** C-level sponsor, steering committee chair, portfolio owner.
- **Secondary:** Product director, engineering director (read-only; they operate on H2/H3).
- **Non-audience:** Delivery team (use H2), QA (use H3), PMO (use H4).

## Length

- **Hard cap:** ≤ 2 printed pages equivalent (≤ 600 lines of markdown, including tables).
- If content exceeds the cap, **compress** (cut words, not claims) — never spill an H1 finding into H2/H3/H4.
- Tables are preferred over paragraphs for structured claims (risks, confidence).

## Required Sections

Every `H1_exec_brief.md` MUST contain these five sections, in this order, with the exact headings below.

### `## Executive Summary`
- 1-2 short paragraphs.
- Opens with the recommendation (answer first — SCQA-style: Situation, Complication, Question, Answer).
- Cites ≥ 1 upstream `[C-xxx]` or `[A51-xxx]` reference.
- No new claims, no numbers absent from canonical A58/A59.

### `## Key Findings (≤5)`
- Bulleted list, 3-5 findings, grouped MECE (mutually exclusive, collectively exhaustive).
- Each bullet: a one-sentence finding + inline `[C-xxx]` reference(s) to A59 direct/inference rows.
- Findings MUST be canonical — do NOT paraphrase in a way that introduces new actors, quantities, dates, or causal links (INV-03).
- Table alternative allowed when claims share columns (e.g., scope area | finding | confidence | `[C-xxx]`).

### `## Recommended Next Steps`
- Ordered list, 3-7 steps.
- Every step that is a **recommendation or judgment** (not a canonical direct/inference claim) MUST be tagged `[AJ:C-xxx]` pointing to a `ClaimType=analyst_judgment` row in A59, AND MUST include inline `[C-xxx]` references back to upstream ClaimIDs in that row's `JustificationRationale`.
- Steps that are purely operational (already in canonical readiness plan) use plain `[C-xxx]` references.
- Every step MUST have an owner role or escalation path; if missing, route via `[A51-xxx]`.
- Aligns with INV-03: analyst_judgment here is **allowed** provided JustificationRationale references upstream ClaimIDs different from the judgment's own ClaimID.

### `## Risks & Blockers`
- Table with columns: `Risk | Severity | Impacted scope | Trace`.
- Severity ∈ {`critical`, `high`, `medium`, `low`} — matches A51 schema enum (pre-v1.1.1 doc used a `blocker` synonym at the top tier; v1.1.1 aligned the H1 risk table with A51's actual enum).
- `Trace` cites either a `[C-xxx]` claim + `[A51-xxx]` route or `[A51-xxx]` alone for pure uncertainty.
- Exactly 3-5 rows; if more exist, move to H4 `## Open Items Digest`.

### `## Confidence Assessment`
- 1-line overall verdict (`high` / `medium` / `low`) with one-sentence rationale.
- Short table with KPI roll-up: `KPI | Target | Actual | Verdict`. KPIs are the five defined in `skills/bsa-orchestrator/references/kpi-definitions.md`:
  - `KPI-001` weighted claim coverage
  - `KPI-002` anchor drift count
  - `KPI-003` critical unsupported claims
  - `KPI-004` A51 unresolved hard-blocking count
  - `KPI-005` handoff new-claim leakage count
- Full breakdown belongs in H3; H1 shows the roll-up only.

## Citation Rules

- `[C-xxx]` — reference to A59 direct/inference ClaimID. Required for every positive statement that asserts an entity, quantity, date, commitment, or causal relation.
- `[AJ:C-xxx]` — reference to A59 analyst_judgment ClaimID. Required for every recommendation / judgment / priority call. The cited row MUST exist in A59 with non-empty `JustificationRationale` referencing ≥ 1 upstream `ClaimID` different from its own (INV-07).
- `[A51-xxx]` — reference to unresolved item in A51. Required for every uncertainty, contradiction, or decision-needed hypothesis surfaced in H1.
- Citations MUST resolve to actual rows in the promoted canonical CSVs; `bsa-no-new-claims-auditor` fails the gate on dangling references.
- Bare unreferenced assertions = INV-01 violation = leakage.

## Forbidden Content

- New actors, quantities, dates, commitments, causal claims not present in canonical A59.
- Any positive assertion lacking `[C-xxx]` / `[AJ:C-xxx]` / `[A51-xxx]` citation — unreferenced assertions are INV-01 violations.
- Speculation about causes or futures absent from canonical claim-layer.
- KPI numbers not derived from promoted audit reports.
- Framings that present a claim as already validated ("as confirmed", "as we know") — per `docs/sem_audit_rename.md`, claims always travel one of the three routes (direct/inference evidence-binding, analyst_judgment with JustificationRationale, or `A51Ref`) and are never carried as default-true.
- Legacy pre-Sprint-2 terminology naming the auditor by its old identifier; see `bsa-no-new-claims-auditor/SKILL.md` terminology note for the narrow legacy-compat exemption.

## Illustrative Structure

```
# H1 Executive Brief — <project / run id>

## Executive Summary
<1-2 paragraphs opening with the recommendation; at least one [C-xxx] citation>

## Key Findings (≤5)
- <finding 1> [C-xxx]
- <finding 2> [C-xxx] [C-yyy]
...

## Recommended Next Steps
1. <step 1 referencing analyst_judgment> [AJ:C-xxx] supported by [C-aaa] [C-bbb]
2. <step 2 referencing canonical plan> [C-zzz]
...

## Risks & Blockers

| Risk | Severity | Impacted scope | Trace |
|---|---|---|---|
| <risk 1> | high | <scope> | [C-xxx] [A51-xxx] |
| <risk 2> | medium | <scope> | [A51-yyy] |

## Confidence Assessment

Overall: medium. <one-sentence rationale>

| KPI | Target | Actual | Verdict |
|---|---|---|---|
| KPI-001 | ≥ 0.75 | 0.82 | PASS |
| KPI-003 | 0 critical | 0 | PASS |
| KPI-005 | 0 leakage | 0 | PASS |
```

## Audit Binding

- `bsa-no-new-claims-auditor` validates that every H1 statement resolves to canonical ClaimID, analyst_judgment (with valid JustificationRationale), or A51Ref.
- `bsa-citation-auditor` validates that `[C-xxx]` and `[AJ:C-xxx]` IDs match existing canonical A59 rows.
- `SCN-STAGE78-001-E-H1` (see validation-scenario-manifest.csv) checks H1 shape + citation closure.

## Cross-References

- Peer specs: `h2_spec.md`, `h3_spec.md`, `h4_spec.md`.
- Manifest schema: `handoff_manifest.schema.json`.
- Terminology: `docs/sem_audit_rename.md` (US-S2-02 part 3/3).
- Invariants: `governance/immutable_invariants.md` INV-01 / INV-03 / INV-07.
