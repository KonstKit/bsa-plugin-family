# Fixture project_0003 — Procurement Approval Workflow (Multi-Stakeholder Conflict)

Third golden fixture for the BSA plugin family. Process-path + `discovery_then_bsa` mode + multi-stakeholder conflict scenario, completing the fixture-axis matrix established in Sprint 2 + Sprint 4.5.

## Scenario

A mid-size organization runs a procurement approval workflow where three stakeholder teams (**finance**, **legal**, **ops**) have overlapping and partially-contested authority over the approval gates. Specifically:

- **Finance** claims sole authority over any procurement > $50k.
- **Legal** claims mandatory review for any contract with a non-standard indemnity clause (regardless of dollar amount).
- **Ops** claims they must approve anything affecting operational capacity (regardless of dollar amount).

The three claims are not incompatible in theory — a $200k purchase of a contract-bound operational SaaS legitimately needs all three. But **in practice** the teams disagree on the ordering, the veto power (can legal block a decision finance has already approved?), and the SLA for each gate. Two PMs interviewed for the pilot describe radically different versions of the same workflow.

Discovery mode is required because:
- Scope is fuzzy: "document procurement approvals" does not yet specify which goods/services, which vendor tiers, or which dollar brackets.
- Stakeholder contradiction is structural (not a documentation gap). Each team genuinely believes they have primacy.
- The goal of the BSA run is to surface the conflict explicitly (via `A51` contradiction rows) rather than paper over it.

## Fixture axes vs project_0001 / project_0002

| Axis | `project_0001` | `project_0002` | `project_0003` (this) |
|---|---|---|---|
| Pipeline path | process (ticket triage flow) | structural (dbt lineage ownership) | **process (procurement approval flow)** |
| Run mode | `direct` | `discovery_then_bsa` | **`discovery_then_bsa`** |
| Domain | support-ticket ops | analytics platform | **procurement** |
| Evidence mix | T2 process note + T4 PM interview | T2 dbt config + T4 AE interview | **T2 policy doc + T4 finance-PM + T4 legal-PM interviews (two contradicting T4)** |
| Primary purpose | Demonstrate canonical pipeline end-to-end, single stakeholder viewpoint | Demonstrate discovery-mode + structural path + source tier-operations | **Demonstrate discovery-mode + structural contradiction between two T4 sources + `A51` contradiction surfacing** |

Three fixtures together exercise: both modes (direct + discovery), both paths (process + structural), single-stakeholder and multi-stakeholder evidence mixes, and both the happy-path and contradiction-surfacing behaviors.

## Inputs

- `inputs/source_001_procurement_policy.md` — T2 (authored-primary): excerpted from the org's written procurement policy. Declares the $50k threshold as the finance-authority trigger.
- `inputs/source_002_finance_pm_interview.md` — T4 (attestation): finance PM's account of the approval flow. Emphasizes finance primacy + aligns with the T2 policy doc.
- `inputs/source_003_legal_pm_interview.md` — T4 (attestation): legal PM's account. Explicitly disagrees with the finance PM on veto power — claims legal can block a finance-approved purchase if the contract has a non-standard indemnity clause.

All inputs are sanitized and synthetic; no real company, person, or contract identifiers.

## What this fixture demonstrates

1. **Two T4 sources producing contradictory attestations**: under the tier-delta ≤ 1 rule from `reliability_tier_spec.md`, same-tier conflicts route to `A51` with `IssueType=contradiction`, `BlockingStatus=hard` (the closed A51 enum from `shared-control-surface-contracts.md` uses `contradiction`; the tier-spec `cross_tier_contradiction` label is an internal classification that maps onto this A51 value + a `NextAction` note pointing at the tier-delta rule). The fixture `A51` carries that row (`A51-002`).
2. **Discovery-stage surfacing of a hard blocker**: even before Stage 1 authors canonical claim rows, D4 feasibility assessment flags the ownership contestation as a hard A51 route that blocks direct promotion.
3. **Analyst-judgment recommendation under contradiction**: C-007 is an `analyst_judgment` row proposing a reconciliation model (finance primary, legal review blocking, ops consult); `JustificationRationale` cites both T4 sources + the T2 policy gap per INV-07.

## Synthetic vs live-run

- `authoring_mode`: `synthetic_representative`.
- Not a live pipeline run. The canonical content + markers were hand-authored to exercise every fixture_runner invariant + the marker chain validator + the H1-H4 handoff shape. Per-claim Locator references resolve to the committed input files.

## Fixture metadata

- `scenario_tags`: `discovery-mode`, `process-path`, `multi-stakeholder-conflict`.
- `canon_policy_version`: `1.0.0-rc2` (matches Sprint 4.5 cohort; will bump to `1.0.0` at the final cut).

## Links

- Sprint plan: US-S45-01 AC-1(c) "process-path + discovery mode + multi-stakeholder conflict".
- Sibling fixtures: `project_0001` (process + direct), `project_0002` (structural + discovery).
- Related spec: `skills/bsa-evidence-intake/references/reliability_tier_spec.md` §"Conflict Resolution" (tier-delta ≤ 1 contested behavior).
- Related auditor: `skills/bsa-citation-auditor/SKILL.md` §"EpistemicInsufficiency findings" (not_independent for two T4 same-role sources).
