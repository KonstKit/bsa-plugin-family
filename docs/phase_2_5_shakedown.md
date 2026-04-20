# Phase 2.5 — Internal-Only Shakedown Gate

**Status:** OPEN. Gate blocking Phase 3 kickoff.
**Mode:** **Internal-only** — solo maintainer on paid-client engagements + own analytical work. No external-user recruitment (decided 2026-04-20 post-v1.0.0).
**Duration target:** 2-4 weeks from first engagement start. Not calendar-time — it's "engagement-count × depth" weighted.
**Minimum cohort:** 2-3 distinct engagements. Each engagement must exercise the full `/bsa-start` → `/bsa-handoff` loop end-to-end; a run that stops mid-pipeline counts as a partial data point but not a completed engagement.

## Why internal-only

Alternative was external analyst recruitment (2-3 non-owned-projects). Rejected because:
- The plugin is a solo-maintainer tool used only by its maintainer; there is no external-user population to recruit from in scope for this phase. A follow-up local-only cleanup commit is removing the public-marketplace install path + CI/release workflows that currently still live in the repo metadata, making the "this plugin is for me" stance explicit throughout.
- Internal paid-client + own-engagement usage gives the same structural feedback (UX, audit verdicts, KPI-001 target re-calibration data, H1-H4 usefulness) without the coordination overhead of external users.
- Blocker findings surface the same way; remediation cadence is actually faster with a solo feedback loop.

Known trade-off: UX friction that only shows up "in a stranger's hands" (cognitive assumption gaps, undocumented conventions) will NOT surface here. Mitigated by: (a) the 6 docs pages in `docs/` are reader-ready; (b) any remaining doc gap the maintainer stumbles on is immediately loggable below; (c) the first post-Phase-3 external user effectively becomes the "zero-th external shakedown" and any blocker there is treated as a v1.x-patch candidate.

## Install procedure (for the shakedown cohort)

Per [INSTALL.md](../INSTALL.md) §Install — Local marketplace. Short form:

```
/plugin marketplace add /Users/kkitanin/projects/bsa-plugin-family
/plugin install bsa-full@bsa-marketplace
/plugin list    # expect bsa-full@1.0.0
```

Re-install after plugin-side changes: `/plugin marketplace update bsa-marketplace`.

## 6 Gate Criteria — structured feedback axes

Every per-engagement section below MUST fill each of these six axes (even if the fill is "no friction observed"). Findings with `severity ≥ medium` escalate to the Aggregated findings block.

1. **UX of slash-commands** — `/bsa-start`, `/bsa-stage`, `/bsa-promote`, `/bsa-audit`, `/bsa-handoff`, `/bsa-status`. Are the commands discoverable, do they refuse gracefully on bad preconditions, do flags (`--verbose`, `--dry-run`, `--mode`) behave as the command file documents?
2. **Audit-findings readability** — when an auditor emits a finding (evidence-binding violation, EpistemicInsufficiency, drift_findings, chain-gap, no-new-claims leakage), is the message specific enough that the analyst can act on it without re-reading the auditor's SKILL.md?
3. **Evidence-binding friction** — how often does the analyst hit INV-01 on a row where they actually HAVE evidence but the A58 excerpt isn't authored yet? Does the flow "route via A51 first, then back-fill evidence" feel natural or painful?
4. **H1-H4 pack usefulness** — do the four handoff packets actually land with stakeholders as-delivered, or do they require manual post-editing? Which packet (H1/H2/H3/H4) takes the most rework?
5. **False-positive rate of auditors** — citation auditor, consistency auditor, skeptical reviewer, no-new-claims auditor, anchor auditor. Rate per 100 findings: how many were real issues vs. correctly-shaped claims the auditor misclassified. Target ≤ 5%.
6. **Missing capabilities** — things the analyst wanted to express but couldn't within the v1.0.0 vocabulary. Captured as `MISSING-CAP-<N>` entries in the Aggregated findings block with a Phase 3+ routing recommendation.

## Per-engagement sections

### Engagement #1 — `<slug>`

- **Started:** _`YYYY-MM-DD`_
- **Completed:** _(in-progress OR `YYYY-MM-DD`)_
- **Mode used:** _(`direct` / `discovery_then_bsa`)_
- **Source count:** _(total A50 rows)_
- **Source tier mix:** _(e.g., `3×T2 + 5×T4 + 2×T5`)_
- **Claim count:** _(A59 row count; break down by ClaimType if helpful)_
- **A51 routes raised:** _(count + severity mix)_
- **Stages completed:** _(1..8 or "halted at stage N")_
- **Pipeline runtime:** _(approximate wall-clock — useful for Phase 6 re-baseline)_

#### 6-axis feedback

1. **UX of slash-commands:** _(notes)_
2. **Audit-findings readability:** _(notes)_
3. **Evidence-binding friction:** _(notes)_
4. **H1-H4 pack usefulness:** _(notes)_
5. **False-positive rate of auditors:** _(rate + examples)_
6. **Missing capabilities:** _(list, reference MISSING-CAP-N)_

#### Engagement-specific notes

_(sanitized observations, anonymized if the engagement is under NDA. Do NOT paste real source content here — use paraphrases + shape descriptions.)_

---

### Engagement #2 — `<slug>`

_(same template)_

---

### Engagement #3 — `<slug>`

_(same template)_

---

## Aggregated findings

### Blocker-candidate findings (routed to v1.0.x hotfix queue)

| ID | Title | Severity | Observed-in | Current-state | Remediation | Status |
|---|---|---|---|---|---|---|
| (no findings yet — add rows as they surface) |

### Non-blocking findings (routed to Phase 3+ backlog)

| ID | Title | Severity | Observed-in | Phase-route | Status |
|---|---|---|---|---|---|
| (no findings yet) |

### Missing-capability log

| ID | Capability | Observed-in | Phase-route | Priority-guess |
|---|---|---|---|---|
| (no findings yet) |

### KPI-001 target re-calibration data

Per `skills/bsa-orchestrator/references/kpi-definitions.md`, the `≥ 0.75` target was set at Sprint 3 US-S3-03 with "revisit after 3 real projects". Collect per-engagement observed KPI-001 values here.

| Engagement | Run | Observed KPI-001 | Tier breakdown | Target-comfort (subjective) |
|---|---|---|---|---|
| (no data yet) |

Target-comfort decision deferred until ≥ 3 observed runs land. Do NOT adjust the target until then.

## Blocker → hotfix → re-release procedure

If any shakedown finding is flagged `severity=critical` (pipeline cannot complete, audit verdicts incorrect for real data, install flow broken):

1. **Create branch** `release/1.0.x` from `v1.0.0` tag (if not already exists).
2. **Patch fix** — minimal-scope change targeting the specific finding.
3. **CHANGELOG** — add `## [v1.0.1] — <date>` (or appropriate patch number) with finding + fix citation.
4. **Plugin version bump** `.claude-plugin/plugin.json`: `1.0.0` → `1.0.1`. `canonPolicyVersion.semver` matching. If the fix touched a POLICY_GLOBS file, recompute canon hash and bump accordingly per [contract-versioning.md](../skills/bsa-orchestrator/references/contract-versioning.md) major/minor/patch rules.
5. **Local smoke-test** on the engagement that surfaced the finding, and at least one other fixture.
6. **Tag** `v1.0.1` on the hotfix branch, then **cherry-pick** the fix commits onto `main` (fast-forward back-merge is not available because `main` has already moved past `v1.0.0` with post-release cleanup commits). The resulting `main` state should be equivalent to the hotfix branch's contents.
7. **Re-install** in the shakedown cohort via `/plugin marketplace update bsa-marketplace` + `/plugin install bsa-full@bsa-marketplace`.

After the cherry-pick lands on `main`, the `release/1.0.x` branch can be deleted; the `v1.0.1` tag retains the exact tree that was re-installed. No long-lived `release/1.0.x` branch beyond the hotfix window.

## Phase 3 kickoff decision

Phase 2.5 closes when:
- [ ] ≥ 2 engagements completed end-to-end (`/bsa-start` → `/bsa-handoff` with PASS verdicts on all gates OR explicit acknowledged `A51` hard-blockers in H4).
- [ ] All 6 gate criteria have at least one concrete data point per engagement.
- [ ] Aggregated findings block triaged: blocker-candidates resolved via v1.0.x hotfix releases; non-blocker + missing-capability findings scoped to Phase 3+ backlog with priority guesses.
- [ ] KPI-001 target-comfort decision recorded (keep `≥ 0.75` or adjust + rationale).
- [ ] Final commit closes this doc with a "Phase 2.5 decision" section including: total engagements, total findings by severity, go/no-go verdict for Phase 3, and any v1.0.x patches that landed during the window.

## Phase 2.5 decision

_(to be filled at gate-close)_

**Verdict:** _(GO for Phase 3 / HOLD for additional v1.0.x patch-cycle / pivot)_
**Engagements:** _(count)_
**v1.0.x hotfixes:** _(count + tags)_
**Summary:** _(short)_
**Next:** _(Phase 3 first story OR continued shakedown OR plan-revision)_

---

Last updated: 2026-04-20 (Phase 2.5 gate opened; no engagement data yet).
