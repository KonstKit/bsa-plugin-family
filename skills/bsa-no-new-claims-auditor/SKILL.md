---
name: bsa-no-new-claims-auditor
description: Audit Stage 8, handoff, and discovery D5 synthesis outputs for net-new claims (previously "facts"; see INV-07), hidden synthesis, and unsupported wording drift against canonical upstream artifacts. ClaimType-aware: analyst_judgment rows are allowed when JustificationRationale references upstream ClaimIDs.
---

# BSA No New Claims Auditor

Use this skill before Stage 8 readiness promotion, before handoff promotion, and for discovery D5 reuse.

**Terminology note (Sprint 2 US-S2-02):** this skill was renamed from `bsa-no-new-facts-auditor`. The shift from "facts" to "claims" is semantic, not cosmetic: the pipeline tracks **claims** (potentially-false assertions that require evidence) rather than **facts** (established truths). A claim is validated by `SourceID+ExcerptID` or explicitly routed through `A51Ref`; a claim is never assumed true by default. Authoritative terminology source: `governance/immutable_invariants.md` INV-01 / INV-07. The downstream-skill semantic-audit checklist is `docs/sem_audit_rename.md` (landed in US-S2-02 part 3/3).

## Scope
- Compare Stage 8 outputs against canonical stage artifacts and core controls.
- Compare handoff packages against canonical Stage 8 outputs and claim-layer controls.
- Compare discovery D5 report/brief/seed outputs against discovery `A58/A59/A60` and shared `A51`.
- Flag statement-level or element-level additions that cannot be traced upstream.
- Distinguish acceptable compression/paraphrase from new-claim leakage.
- Recognise `ClaimType=analyst_judgment` rows (INV-07): they are **not** leakage when they carry non-empty `JustificationRationale` referencing at least one upstream `ClaimID` different from the row's own `ClaimID`. Missing or self-only rationales ARE leakage and fail the gate.

## Invocation Modes
- Main cycle (Stage 8 + handoff):
  - Read from `analysis/proposals/stage7_8/stage8/` and `analysis/proposals/stage7_8/handoff/`.
  - Write reports into same stage directories.
  - Supports runtime marker `stage8.no_new_claims.pass.json`.
- Discovery (D5):
  - Read from `analysis/discovery/proposals/d5/`.
  - Write `discovery_no_new_claims_report.md` into same directory.
  - Discovery marker availability depends on active run profile.
- Mode routing is orchestrator-owned.

## Inputs
- Active mode proposal artifacts (Stage 8/handoff or discovery D5).
- Upstream canonical artifacts for the same scope.
- Claim-layer controls `A58/A59/A60` and shared `A51` routes.

## Outputs
- `analysis/proposals/stage7_8/stage8/no_new_claims_report.md`
- `analysis/proposals/stage7_8/handoff/handoff_no_new_claims_report.md`
- `analysis/discovery/proposals/d5/discovery_no_new_claims_report.md`

## Gate Rules
- `stage8.no_new_claims.pass.json` requires leakage count = `0` for Stage 8/handoff promotion.
- Optional discovery pass marker (if profile enables it) requires leakage count = `0`.
- `ClaimType=analyst_judgment` rows with valid JustificationRationale do NOT count as leakage (INV-07); rows with missing or self-only rationale DO count.

## On Audit Failure
1. Emit leakage findings with statement-level trace.
2. Block pass marker emission for active mode.
3. Route unresolved additions to `A51Ref`.
4. Re-audit only after upstream proposal rework.

## Backward compatibility
- Legacy report filenames accepted for read-only consumption when migrating older workspaces: `no_new_facts_report.md`, `handoff_no_new_facts_report.md`, and `discovery_no_new_facts_report.md`. New writes always use the `no_new_claims` naming.
- Workspace migration from legacy filenames is performed by `scripts/migrate_v0.9_to_v1.0.py` (landed in US-S2-02 part 2/3); it renames in-place on committed canonical paths and emits an idempotent migration log.

## Reference
- [references/no-new-claims-contract.md](references/no-new-claims-contract.md)
