---
name: bsa-audit
description: Run a named audit (citation, consistency, skeptical, no-new-claims, anchor) against current stage outputs. Delegates to the matching auditor skill.
---

# `/bsa-audit`

Run one of the BSA audit skills against the active stage's proposal-layer outputs.

## Usage

```
/bsa-audit <kind> [--verbose]
```

`<kind>` — REQUIRED, one of:

| kind | Auditor skill | Typical invocation stage |
|---|---|---|
| `citation` | `bsa-citation-auditor` | Stage 3, Stage 7 (critical-claim coverage + EpistemicInsufficiency per US-S3-03) |
| `consistency` | `bsa-consistency-auditor` | Stage 3 (claim-layer contradictions + broken claim-binding) |
| `skeptical` | `bsa-skeptical-reviewer` | Stage 7 (reviewer pass on all promoted content) |
| `no-new-claims` | `bsa-no-new-claims-auditor` | Stage 8 + handoff (KPI-005 = 0 leakage) |
| `anchor` | `bsa-anchor-auditor` | Stage 5, Stage 6 (A61 anchor integrity + drift detection per US-S3-04) |

Aliases accepted: `nnc` for `no-new-claims`; `cit` for `citation`; `skp` for `skeptical`.

## What this command does

Delegate to `bsa-orchestrator`, which routes to the named auditor:

1. Verify the current stage is appropriate for the requested audit (e.g., `anchor` during stage5 or stage6 only; `no-new-claims` during stage8 or handoff only). If mismatched, warn but proceed if the user explicitly opted in via `--force` (reserved, not part of MVP).
2. Read the stage's proposal artifacts + the canonical upstream A58/A59/A60/A51/A61 as inputs.
3. Invoke the auditor. It writes its report into `analysis/proposals/<stage>/audit_reports/` (or the discovery equivalent if active mode is discovery).
4. On audit PASS (0 critical findings, KPIs within targets): emit the stage-specific pass marker (e.g., `stage3.citation_audit.pass.json`).
5. On audit FAIL: do NOT emit the marker; leave the failing report under `analysis/proposals/<stage>/audit_reports/` and surface guidance ("revise upstream rows, then re-run `/bsa-audit <kind>`").

## Output

- With `--verbose`: per-check trace — e.g., for `citation`, every A59 row's binding status + any `EpistemicInsufficiency` sub-type assigned.
- Without: summary — `citation audit PASS, 0 critical unsupported claims, weighted coverage 0.85` (or the corresponding FAIL variant).

## Failure modes

- **Stage mismatch** (e.g., `/bsa-audit anchor` during stage3): refuse with guidance. Anchor audit needs `A61_anchor_map_candidate.csv` which only exists from stage5 onward.
- **Missing upstream canonical**: e.g., running citation audit when `A58` is empty. Refuse with pointer to `/bsa-stage N run` to generate upstream material.
- **Auditor emits FAIL**: report is written; marker is not. User revises proposal-layer + re-runs audit; if they want to escape via explicit A51 route, they must edit the proposal + add the `A51Ref` and re-run.

## Related

- `/bsa-stage <n> run` also runs the stage's auditors as part of the run sequence — but if you want to re-run a single audit after fixing something, `/bsa-audit` is the targeted tool.
- `/bsa-promote` depends on the audit pass markers; running an audit without the corresponding stage run is allowed but you'll need to make sure the upstream proposal layer is fresh.
