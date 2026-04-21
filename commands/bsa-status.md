---
name: bsa-status
description: Report current BSA pipeline state — active stage, pending markers, open A51 items, last audit verdicts, KPI snapshot. Read-only.
---

# `/bsa-status`

Summarize the current state of a BSA-initialized workspace.

## Usage

```
/bsa-status [--verbose]
```

- `--verbose` — Expand every section with full detail (all markers + all A51 rows + per-tier KPI breakdown). Default is a compact summary.

## What this command does

Delegate to `bsa-orchestrator` (read-only):

1. Read `analysis/canonical/core_controls/A48_run_context_card.md` to determine current stage and mode.
2. Enumerate markers under `analysis/runtime/ready/` (and `analysis/discovery/runtime/ready/` if discovery mode).
3. Run `scripts/validate_marker_chain.py` over the marker zone to detect chain integrity issues; surface any findings.
4. Read A51 and count open items by BlockingStatus.
5. Read the latest promoted audit reports (`citation_audit_report`, `consistency_audit_report`, `skeptical_review_report`, `no_new_claims_report`, `anchor_audit_report`) if present and extract their verdicts + KPI-001..005 snapshot.
6. Run `scripts/compute_canon_hash.py --diff-breakdown` and compare to the `canon_policy_version_hash` recorded in the latest marker — surface a `policy_version_drift_warning` if they differ.

## Output (compact, default)

```
BSA workspace: <cwd>
Run ID:         <A48.RunID>
Mode:           direct | discovery_then_bsa
Current stage:  stage3 (next: stage4.ready)
Last marker:    stage3.citation_audit.pass @ 2026-04-19T16:30:00Z
Canon policy:   1.0.0-rc1+hash:cbba8e53 (workspace); current repo hash MATCHES
Open A51:       5 (hard: 0, soft: 2, informational: 3)
Audits:         cit=PASS skp=PASS consistency=PASS nnc=PASS anchor=PASS
KPI-001:        0.85 (target >=0.75, weighted)
KPI-005:        0 leakage (handoff not yet promoted)
Marker chain:   OK
```

## Output (`--verbose`)

Adds:
- Full marker list (filename + verdict + timestamp + canon_policy_version_hash prefix).
- Every A51 row with A51Ref, IssueType, Severity, BlockingStatus, NextAction, ResolutionStatus.
- Full KPI scorecard (KPI-001..005 with per-tier breakdown for KPI-001, per-rule counts for KPI-003).
- Tool availability check: `plantuml`, `xmllint`, `python3 jsonschema` (test dep for handoff-manifest validation).

## State-aware notices

After the compact summary, surface a one-block notice if the workspace is in an actionable transition state. The orchestrator decides which (if any) of these applies based on the marker zone + A48 contents:

### `discovery-deliverable-only`
**Trigger:** A48.CurrentStage = `discovery.complete` AND `discovery.go.json` present AND `bsa.stage1.entry.enabled.json` present AND no `stage1.*` markers in `analysis/runtime/ready/`.

**Print:**
```
NOTICE — Discovery cycle is complete and the bridge into main cycle is open,
but no main-cycle stage has started. Two paths from here:

  1. Continue to main cycle (Stage 1..8 → handoff):
       /bsa-stage 1 run

  2. Treat this as a discovery-only deliverable. The artifacts under
     analysis/discovery/canonical/ + analysis/canonical/core_controls/ are
     the deliverable; no further action needed. /bsa-handoff will refuse
     until at least Stage 1 has been promoted.
```

This notice exists because operators reaching D-Exit + bridge often pause without realizing the workspace is intentionally between cycles, not stuck. It is read-only documentation, not a prompt for the user — just print and continue.

### `pre-stage-ready` (stage just promoted, next stage entry not yet declared)
**Trigger:** Last marker is `stageN.<audit>.pass` AND `stage{N+1}.ready.json` not present AND N < 8.

**Print:**
```
NOTICE — Stage <N> is fully promoted but Stage <N+1> entry has not been
declared. Run `/bsa-stage <N+1> run` to advance.
```

### `handoff-ready-not-emitted`
**Trigger:** `stage8.no_new_claims.pass.json` present AND `handoff.ready.json` not present.

**Print:**
```
NOTICE — Stage 8 is promoted; handoff package not yet generated.
Run `/bsa-handoff` to emit H1-H4 + manifest.
```

## Failure modes

- **`analysis/` not initialized**: suggest `/bsa-start` (also the SessionStart hook emits this suggestion proactively).
- **`A48` unreadable or malformed**: report `workspace corrupt at A48` and exit without further action.
- **`validate_marker_chain.py` exits non-zero**: include the findings in the status output; mark workspace as `chain-inconsistent`.
- **Canon hash mismatch against current repo**: emit `policy_version_drift_warning` (non-blocking — the workspace may pre-date a repo-side policy bump).

## Side effects

None. This command is strictly read-only. No files are written.
