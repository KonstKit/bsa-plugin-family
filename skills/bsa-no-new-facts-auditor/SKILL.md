---
name: bsa-no-new-facts-auditor
description: Audit Stage 8, handoff, and discovery D5 synthesis outputs for net-new claims (legacy term: facts), hidden synthesis, and unsupported wording drift against canonical upstream artifacts.
---

# BSA No New Claims Auditor (Legacy Skill Name: no-new-facts)

Use this skill before Stage 8 readiness promotion, before handoff promotion, and for discovery D5 reuse.

## Scope
- Compare Stage 8 outputs against canonical stage artifacts and core controls.
- Compare handoff packages against canonical Stage 8 outputs and claim-layer controls.
- Compare discovery D5 report/brief/seed outputs against discovery `A58/A59/A60` and shared `A51`.
- Flag statement-level or element-level additions that cannot be traced upstream.
- Distinguish acceptable compression/paraphrase from new-claim leakage.

## Invocation Modes
- Main cycle (Stage 8 + handoff):
  - Read from `analysis/proposals/stage7_8/stage8/` and `analysis/proposals/stage7_8/handoff/`.
  - Write reports into same stage directories.
  - Supports runtime marker `stage8.no_new_claims.pass.json`.
- Discovery (D5):
  - Read from `analysis/discovery/proposals/d5/`.
  - Write `discovery_no_new_facts_report.md` into same directory.
  - Discovery marker availability depends on active run profile.
- Mode routing is orchestrator-owned.

## Inputs
- Active mode proposal artifacts (Stage 8/handoff or discovery D5).
- Upstream canonical artifacts for the same scope.
- Claim-layer controls `A58/A59/A60` and shared `A51` routes.

## Outputs
- `analysis/proposals/stage7_8/stage8/no_new_facts_report.md`
- `analysis/proposals/stage7_8/handoff/handoff_no_new_facts_report.md`
- `analysis/discovery/proposals/d5/discovery_no_new_facts_report.md`

## Gate Rules
- `stage8.no_new_claims.pass.json` requires leakage count = `0` for Stage 8/handoff promotion.
- Optional discovery pass marker (if profile enables it) requires leakage count = `0`.

## On Audit Failure
1. Emit leakage findings with statement-level trace.
2. Block pass marker emission for active mode.
3. Route unresolved additions to `A51Ref`.
4. Re-audit only after upstream proposal rework.

## Reference
- [references/no-new-facts-contract.md](references/no-new-facts-contract.md)
