# `--strict-on-hard-a51` Mode

**Status:** v1.1.16 (Sprint 1 / T6). Opt-in failure-mode for `/bsa-promote`. Default behavior is unchanged (permissive).

## What it does

When the operator passes `/bsa-promote --strict-on-hard-a51` (or sets the env-var `BSA_STRICT_ON_HARD_A51=1`), the orchestrator hook runs a pre-flight check **BEFORE acquiring the canonical merge lock**:

1. Scan `analysis/canonical/core_controls/A51_issue_route_register.csv` (and the `analysis/discovery/...` equivalent if it exists) for rows matching:
   - `BlockingStatus = hard`
   - `ResolutionStatus = open`
2. For each blocking row, check whether any H4 packet under `analysis/handoff/H4*.md` references the row's `A51Ref` inside the `## Decisions Required` section. If yes → **waivered** (proceed). If no → **blocker** (refuse).
3. If any non-waivered blocker remains, exit 1 with a structured `BLOCKED:` message naming every blocker by `A51Ref + IssueType + Severity + NextAction`. The canonical lock is NOT acquired and `analysis/canonical/` stays untouched.

## Why opt-in (and not default)

The default contract is "surface contradictions as A51, do not block the pipeline" — operators can ship a handoff with hard-blocking A51s open if they choose, knowing those items are flagged for the steering / sponsor track. Real-world engagements sometimes want the **opposite** posture: refuse to ship anything until all hard-blockers are closed. That's a valid but distinct contract — opt-in, not default.

Switching the default would break every existing pilot's promote flow. Strict mode lets the same contract land for engagements that want it without breaking the rest.

## Operator escape hatches

When strict-mode pre-flight blocks, the operator has three ways forward:

1. **Drop the flag** — re-run `/bsa-promote` without `--strict-on-hard-a51` (or unset the env-var). Default permissive mode lands.
2. **Resolve the A51 row** — edit `A51_issue_route_register.csv` and set `ResolutionStatus` to one of `resolved | resolved_by_remediation | superseded | wontfix` (per `governance/schemas/a51.schema.json` enum). The canonical write goes via the proposal layer + `/bsa-promote` like any other A51 edit.
3. **Add an H4 waiver** — open the H4 packet (or generate it via `/bsa-handoff` if not yet emitted) and add a `[A51-xxx]` reference inside the `## Decisions Required` section. This records the sponsor's accept-and-proceed decision. The pre-flight then treats the row as waivered.

## BLOCKED message shape

The structured BLOCKED message goes to stderr (so operators see it in the same channel as other hook diagnostics):

```
BLOCKED: /bsa-promote --strict-on-hard-a51 refused canonical write — N unresolved hard-blocking A51 row(s):
  A51-CONFL-003 (contradiction, Severity=critical, BlockingStatus=hard, ResolutionStatus=open) — NextAction: Resolve customer-refund authority: support runbook (S-001) says front-line up to...
```

The format is pinned by `tests/test_adversarial_b3_fixtures.py::test_proposed_strict_mode_preflight_blocks_on_open_hard_a51` so any future format drift is caught at CI.

## Exit codes

| Exit | Meaning |
|---|---|
| `0` | Pre-flight passes — no hard-blocking A51, OR all blockers waivered in H4. Promote proceeds. |
| `1` | Pre-flight blocks — at least one non-waivered hard-blocking A51. The canonical lock is NOT acquired. |
| `2` | Invocation / parse error — workspace not initialized (no `analysis/`), A51 CSV malformed, or preflight script missing. The BLOCKED message is NOT printed (this is operator misconfiguration, not a real block). |

## Implementation

| Layer | File | Role |
|---|---|---|
| Hook | `hooks/pre_bash_promote.sh` | Detects `--strict-on-hard-a51` flag or `BSA_STRICT_ON_HARD_A51=1` env. Invokes the preflight script. Propagates exit code. |
| Preflight | `scripts/promote_strict_preflight.py` | Stdlib-only. Reads A51, classifies blockers, scans H4 waivers, formats BLOCKED message. |
| Spec | `fixtures/golden/adversarial_block_on_contradiction_001/` | The spec-as-fixture (v1.1.5). One A51 row at `BlockingStatus=hard + ResolutionStatus=open` with no H4 waiver — the canonical "must block" scenario. |
| Test | `tests/test_adversarial_b3_fixtures.py` | Pins the BLOCKED message shape + the spec scenario behavior. |

## Use it when

- Your engagement contractually cannot ship with open contradictions (regulated industries, audit-sensitive deliverables, formal acceptance gates).
- You want CI to enforce zero-open-blockers as a release gate (set `BSA_STRICT_ON_HARD_A51=1` in the CI env; the hook fires regardless of how `/bsa-promote` is invoked).
- You're piloting the strict workflow before flipping it as a project-wide default.

## Don't use it when

- Your engagement legitimately ships with open A51 routes acknowledged in H4 (the most common case — strict mode just adds friction).
- You're in early-stage discovery / Stage 1-2 — too many A51s land before promotion windows for strict mode to be useful.
- You want to "see what would block" without actually blocking — use `--dry-run` instead, which previews everything including A51 state without invoking the strict preflight.
