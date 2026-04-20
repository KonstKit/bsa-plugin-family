---
name: bsa-start
description: Initialize the BSA analysis/ runtime layout and seed A48/A50/A51 control surfaces. Supports --mode=direct (default) and --mode=discovery_then_bsa. Use at project kickoff.
---

# `/bsa-start`

Bootstrap a BSA-orchestrated analysis workspace in the current directory.

## Usage

```
/bsa-start [--mode=<direct|discovery_then_bsa>] [--verbose]
```

Arguments (parsed from the raw command-line string — Claude Code does NOT auto-parse flags):

- `--mode=direct` — **default**. Skip discovery; start directly at main-cycle Stage 1 on the user-provided source set. Use when the problem is well-scoped and sources are pre-identified.
- `--mode=discovery_then_bsa` — Run `d0-*` discovery skills (d1..d5) first, emit a `discovery.go` decision, then enter Stage 1 via the bridge. Use when scope is fuzzy or multiple stakeholders disagree on what the problem is.
- `--verbose` — Emit per-step trace: which skills are invoked, which files are read/written, which markers land. Default output is a short summary only.

## What this command does

Delegate to `bsa-orchestrator`:

1. Verify the cwd is empty of prior `analysis/` state (or ask the user to confirm continuation if found).
2. Create runtime layout:
   - `analysis/canonical/core_controls/` (A48, A50, A51, A58, A59, A60, A61)
   - `analysis/canonical/stage1..stage8/` (empty dirs ready for promotion)
   - `analysis/proposals/stage1..stage8_/`
   - `analysis/runtime/ready/` (marker zone)
   - `analysis/runtime/locks/`
   - `analysis/runtime/reentry/`
   - `analysis/runtime/events/`
   - `analysis/views/c4/`, `analysis/views/bpmn/` (sidecar view zones)
   - `analysis/canonical/merge_logs/` (if discovery mode)
   - If `--mode=discovery_then_bsa`: additionally `analysis/discovery/{runtime,canonical,proposals}/`
3. Seed `A48_run_context_card.md` with the declared mode + current date + `CanonPolicyVersion` (read from `.claude-plugin/plugin.json`).
4. Emit the first marker:
   - direct mode → `analysis/runtime/ready/stage1.ready.json`
   - discovery mode → `analysis/discovery/runtime/ready/discovery.d1.ready.json`

See `skills/bsa-orchestrator/references/workflow-contract.md` for the canonical runtime layout, and `skills/bsa-orchestrator/references/runtime-marker-schema.md` for marker payload shape (every emitted marker carries `marker_id`, `stage`, `verdict`, `timestamp`, `canon_policy_version`, and — for Sprint-3+ runs — `canon_policy_version_hash`).

## Next step after success

- `/bsa-status` to see current stage and pending markers.
- `/bsa-stage <n> run` to execute the first stage (stage1 for direct, d1 for discovery).

## Failure modes

- **Existing `analysis/` directory present**: refuse to overwrite. User must either remove it manually or run in a fresh directory.
- **`analysis/canonical/` partially corrupt** (e.g., missing A48): emit a findings report rather than trying to repair; operator fixes upstream before re-running.
- **Optional tooling missing** (e.g., `plantuml`, `xmllint`): init proceeds, but `/bsa-status` will report `plantuml not found, sidecar c4 output will be skipped` — graceful degradation. Hard blocker only if a required tool is absent (currently none at init time).

## Output

- With `--verbose`: list each created path + marker + seed file + tool-check result.
- Without `--verbose`: one-line summary like `BSA workspace initialized in <cwd>, mode=direct, first marker emitted`.
