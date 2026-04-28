# Run Profile Gates

## Purpose
Run profile defines which marker set is mandatory for promotion decisions in a given execution mode.

## Baseline Profile (runtime-default)

### Discovery mandatory markers
- `discovery.d1.ready.json`
- `discovery.d2.claims.merged.json`
- `discovery.d2.research_quality.pass.json`
- `discovery.d3.prioritization.pass.json`
- `discovery.d4.constraint_audit.pass.json`
- `discovery.d5.citation_audit.pass.json`
- `discovery.d5.no_solution_leakage.pass.json`
- `discovery.exit.pass.json`

### Main-cycle mandatory markers
- `stage1.excerpts.merged.json`
- `stage2.context_state.pass.json`
- `stage3.citation_audit.pass.json`
- `stage5.anchor_audit.pass.json`
- `stage6.anchor_audit.pass.json`
- `stage7.skeptical_review.pass.json`
- `stage8.no_new_claims.pass.json`

## Extended Discovery Profile (strict)
- Baseline plus:
  - `discovery.d5.skeptical_review.pass.json`
  - `discovery.d5.no_new_claims.pass.json` (legacy marker filename `discovery.d5.no_new_facts.pass.json` accepted for read-only consumption in pre-v1.0 workspaces; migrate via `scripts/migrate_v0.9_to_v1.0.py`)

## Profile Routing Rules
- Orchestrator chooses active profile.
- Workers must not self-select profile from chat.
- Profile changes require re-entry for affected downstream stages.

## Runtime Profile Linkage
- Environment-level runtime profile files live under `config/runtime_profiles/*.json`.
- Marker gate profile selection must remain compatible with active runtime profile metadata.

## Readiness Profile (v1.4.0+ — closes review #3.4)

The readiness scorecard computed by `bsa-validation-readiness` is **profile-aware** as of v1.4.0. Pre-v1.4.0 the scorecard applied a single threshold set across every engagement type — but compliance engagements need stricter citation gates than dev-handoff engagements, and discovery-handoff engagements need different KPI focus entirely. The readiness profile lets the operator (or orchestrator) select the right gate set without re-implementing the scorecard.

### Profile alphabet

| Profile | When to use | Gate emphasis |
|---|---|---|
| `default` | General BSA engagement; no domain-specific overlay. | Balanced — KPI-001..005 weighted equally. |
| `compliance` | Regulated-domain engagements (fintech audit, healthcare HIPAA, GDPR). | KPI-003 (critical-claim coverage) + KPI-005 (no-new-claim leakage) hard-blocks; **citation_audit** + **no_new_claims** + **A63 cross-check** thresholds tightened (zero tolerance). |
| `dev-handoff` | Engagement terminates with Phase-3 dev-handoff (NFRs / stories / scenarios / traceability / backlog). | KPI-006 (story-to-claim coverage ratio) hard-block + INVEST coverage required ≥ 90%; **A72 traceability completeness** and **A71 NFR scenario coverage** weighted higher. |
| `discovery` | Engagement terminates at D5 with `Discovery Report` / `Discovery Brief` for downstream main-cycle entry. | Discovery-only gate set: D5 audit markers + KPI-Disc-01 (D5 hypothesis coverage ≥ 0.80) + KPI-Disc-02 (D5 claim → A58 binding ratio = 1.0). ALL main-cycle KPIs (KPI-001..006) skipped — engagement doesn't reach Stage 7/8. |

### Profile selection

- **Operator-driven**: pass `--readiness-profile=<name>` to `/bsa-stage 7` or `/bsa-stage 8` to override the default. Falls through to A48 metadata if unset.
- **A48 metadata** (canonical state): `A48_run_context_card.md` carries an optional `ReadinessProfile` field. When present, the orchestrator uses it as the default for every readiness pass in the engagement. Field is added when `/bsa-start` is invoked with `--readiness-profile=<name>`; defaults to `default` otherwise.
- **Audit-trail invariant**: every Stage-7 / Stage-8 promotion marker carries the active `readiness_profile` field in its payload (free-text string matching the profile alphabet). `bsa-validation-readiness` reads it back at audit time so retroactive review can reconstruct WHICH profile was applied. Pre-v1.4.0 markers without the field are tolerated as `readiness_profile=default` (legacy behavior).

### Per-profile gate set

The per-profile gate definitions are operator-readable + machine-readable contracts; the actual scorecard logic lives in `bsa-validation-readiness` (consult that skill's SKILL.md for the workflow). The profile contracts themselves:

**`default` profile** — current pre-v1.4.0 behavior, unchanged:
- Hard-blocks: KPI-003=0, KPI-005=0.
- Soft-flags: KPI-001 / KPI-002 / KPI-004 / KPI-006 below historical baseline.

**`compliance` profile** — stricter than default:
- Hard-blocks: KPI-003=0, KPI-005=0, **A63 ValidationStatus∈{rejected}=0** (zero rejected AJ claims allowed in any A59 row referenced from H1/H4), **A51.BlockingStatus=hard.ResolutionStatus=open=0** (no open hard A51 routes — closes the v1.1.16 strict-on-hard-a51 gap as a profile default).
- Soft-flags: same as default.
- Additional audit: a per-promotion `compliance_audit_report.md` is required (operator authors per engagement; the auditor checks for presence + non-empty content).

**`dev-handoff` profile** — focus on Phase-3 readiness:
- Hard-blocks: KPI-003=0, KPI-005=0, **KPI-006 ≥ 0.9** (story-to-claim coverage ratio at least 90%), **A72 orphan-trace count = 0** (every A70 story has at least one A72 row).
- Soft-flags: A71 NFR-scenario coverage below 80%.
- Skipped: legacy main-cycle citation-only KPIs (still computed but informational, not blocking).

**`discovery` profile** — terminates at D5 (no main-cycle promotion):
- Hard-blocks (discovery-only gates):
  - `discovery.d5.citation_audit.pass` marker present (every D5 claim has bound source/excerpt or A51 route).
  - `discovery.d5.no_solution_leakage.pass` marker present (D5 outputs stay pre-solution).
  - `discovery.d5.no_new_claims.pass` marker present (D5 wording does not introduce claims beyond D2-D4 canonical).
  - **Discovery KPI-Disc-01** (coverage of D2 hypothesis register by D5 synthesis) ≥ 0.80 — every D2 hypothesis must surface in either `Discovery Report` (validated/refuted/inconclusive) or `Discovery Brief` (deferred-with-rationale). Below 0.80 = synthesis is incomplete.
  - **Discovery KPI-Disc-02** (D5 claim → A58 excerpt binding ratio) = 1.0 — every claim in `Discovery Report` / `Discovery Brief` MUST have at least one bound A58 excerpt OR an A51 route. Anything less = D5 leakage gate hasn't really fired.
- Skipped: ALL main-cycle KPIs (KPI-001..006). Engagement doesn't reach Stage 7/8/handoff so those scorecards don't apply.
- Note: the legacy `KPI-001` mention here was a v1.4.0 R1 doc bug — KPI-001 is a main-cycle coverage ratio with `≥ 0.75` threshold, not a discovery-zone zero-block. Discovery has its own KPI-Disc-* set documented in this section.

### Operator workflow

1. At engagement kickoff, decide profile per the table above.
2. Invoke `/bsa-start --readiness-profile=<name>` (or set the field manually in A48 if the engagement is mid-flight).
3. Subsequent `/bsa-stage 7` / `/bsa-stage 8` runs auto-honor the A48 field unless overridden via CLI.
4. Each promotion marker records the active profile; review later via `dashboard/index.html` (the dashboard surfaces the profile + gate evaluation per stage).
