# No New Claims Contract

**Terminology note (Sprint 2 US-S2-02):** the auditor and its contract were renamed from `no-new-facts` to `no-new-claims`. The shift is semantic, not cosmetic — see `skills/bsa-no-new-claims-auditor/SKILL.md`. Canonical pipeline vocabulary is "claim" (potentially-false assertion requiring evidence), not "fact" (implied established truth). The downstream-skill semantic-audit checklist is `docs/sem_audit_rename.md` (landed in US-S2-02 part 3/3).

## Required Sections
- artifacts audited
- upstream canonical surfaces used
- statements/elements audited
- allowed paraphrase count
- new-claim leakage count
- hidden synthesis count
- analyst_judgment rows examined (count); split into `with_valid_rationale` and `missing_or_self_only_rationale`
- verdict (`PASS`/`FAIL`)

## Rule
A wording change is allowed only when it preserves upstream factual content without adding new actors, constraints, states, commitments, dates, quantities, or causal claims.

## Analyst-judgment allowance (INV-07)
- A row with `ClaimType=analyst_judgment` is NOT leakage when:
  - `JustificationRationale` is non-empty, and
  - `JustificationRationale` references at least one upstream `ClaimID` different from the row's own `ClaimID`.
- A row with `ClaimType=analyst_judgment` IS leakage when:
  - `JustificationRationale` is missing or empty, or
  - `JustificationRationale` references only the row's own `ClaimID` (self-only).
- The auditor report MUST split the analyst-judgment count into the two buckets above; a single aggregate count hides the leakage.

## Marker Link
- Main-cycle gate uses `stage8.no_new_claims.pass.json`.
- Report filenames are `no_new_claims_report.md` / `handoff_no_new_claims_report.md` / `discovery_no_new_claims_report.md`. Legacy `no_new_facts_*` filenames are accepted for read-only consumption of pre-v1.0 workspaces; new writes always use the `no_new_claims` naming.
- Workspace migration from legacy filenames is performed by `scripts/migrate_v0.9_to_v1.0.py` (landed in US-S2-02 part 2/3).
