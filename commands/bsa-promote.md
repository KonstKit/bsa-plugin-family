---
name: bsa-promote
description: Two-key promote proposal-layer outputs to canonical for the current stage. Verifies evidence-binding + required audit markers, acquires merge lock, promotes, emits next stage marker. Supports --dry-run.
---

# `/bsa-promote`

Promote `analysis/proposals/<stage>/` to `analysis/canonical/<stage>/` under the two-key promotion rule.

## Usage

```
/bsa-promote [--dry-run] [--verbose]
```

- `--dry-run` — **Non-mutating preview**. Show exactly which files would be promoted, which markers would be emitted, which A51 rows would be flagged. Does NOT touch any file under `analysis/canonical/`. Run this before every real promotion.
- `--verbose` — emit full trace: marker check results, lock acquisition, per-file copy operations.

## What this command does

Delegate to `bsa-orchestrator`:

1. Read `A48` to determine current stage.
2. Run pre-merge preconditions per `skills/bsa-orchestrator/references/merge-and-reentry-policy.md`:
   - Proposal path valid.
   - Evidence-binding gate: every A59 row has `SourceID+ExcerptID` or `A51Ref`.
   - Required audit markers present for the stage (from `run-profile-gates.md`).
   - No parallel-ledger violations (`A48/A50/A51` single-source).
   - No unresolved hard-blocking A51 items covering this promotion scope.
   - Merge lock can be acquired.
   - Discovery → main merge step completed with no hard-blocking events (if `discovery_then_bsa` mode + `discovery.go`).
3. If `--dry-run`: print the planned actions and STOP. Nothing changes on disk.
4. If not `--dry-run`: run the Promotion Sequence per `workflow-contract.md`:
   - Acquire merge lock.
   - Run discovery→main merge step (if applicable) and append events to `analysis/canonical/merge_logs/discovery_to_main_merge_log.jsonl`.
   - Promote artifacts + control surfaces.
   - Emit next stage's `.ready.json` marker.
   - Release lock.

## `--dry-run` output example

```
DRY RUN — no files will be modified.

Pre-merge preconditions:
  [OK] proposal path: analysis/proposals/stage3/
  [OK] evidence-binding: 23/23 A59 rows have SourceID+ExcerptID or A51Ref
  [OK] required markers: stage3.citation_audit.pass, stage3.consistency_audit.pass
  [OK] A51 hard-blockers for stage3 scope: 0
  [OK] merge lock available

Plans to promote:
  analysis/proposals/stage3/semantic_core_rows.md       → analysis/canonical/stage3/
  analysis/proposals/stage3/semantic_issues.md          → analysis/canonical/stage3/
  analysis/proposals/stage3/semantic_traceability_report.md → analysis/canonical/stage3/
  (3 files total, 127 KB)

Markers to emit:
  stage4.ready.json (next stage)

Merge log events (none in direct mode).

Run without --dry-run to execute.
```

## Real-run output

On success: `Stage 3 promoted. Next stage: stage4. Emit markers: stage4.ready.json.`

On failure: per-precondition diagnostic + guidance ("stage3.citation_audit.pass marker missing — run `/bsa-audit citation` first"). No partial promotion is ever left behind — if any precondition fails, the lock is not acquired and `canonical/` stays untouched.

## Failure modes

- **Required audit marker missing** (e.g., running promote at stage3 without `stage3.citation_audit.pass.json`): refuse with a `missing marker: <name>` diagnostic pointing at the `/bsa-audit` command that produces it. The `PreToolUse:Bash` hook also catches this at the hook layer.
- **Merge lock already held** (concurrent run in the same workspace): refuse and report the lock holder. Single-writer guarantee.
- **Canonical path write blocked by hook**: the `PreToolUse:Write` hook refuses writes by any identity other than `bsa-orchestrator`. If you see this, a non-orchestrator caller is trying to touch `analysis/canonical/*` — investigate rather than bypass.
- **Discovery merge conflict (`claim_conflict` or `excerpt_text_conflict`)**: hard-blocks promotion; the merge step emits an `A51` row and exits. Resolve the A51 row first, then re-run.

## Safety

- The `PreToolUse:Bash` hook (`hooks/hooks.json` + `hooks/pre_bash_promote.sh`) intercepts every `/bsa-promote` invocation and verifies required markers BEFORE Claude actually runs the command logic. A missing marker yields a hook-level block with a message naming the missing marker.
- Canonical writes are additionally protected by the `PreToolUse:Write` hook (`hooks/pre_write_canonical.sh`): only the orchestrator is allowed to write to `analysis/canonical/*` paths. Manual edits by Claude or other tools are blocked at the hook level.
- `--dry-run` is always safe to run, even from inside a hook-blocked context.
