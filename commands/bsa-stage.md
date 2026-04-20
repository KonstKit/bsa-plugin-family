---
name: bsa-stage
description: Execute a specific BSA main-cycle stage by number (1..8) or discovery stage (d1..d5). Delegates to the stage-owner worker skill(s) via orchestrator routing.
---

# `/bsa-stage`

Run the worker skills for one pipeline stage.

## Usage

```
/bsa-stage <stage> [run] [--verbose]
```

- `<stage>` — REQUIRED. One of `stage1 .. stage8` for main cycle, or `d1 .. d5` for discovery. Aliases: plain numeric `1..8` is accepted and normalized to `stage<n>`.
- `run` — optional literal. Accepting either `/bsa-stage 3 run` or `/bsa-stage 3` keeps the syntax tolerant to the plan's documented form.
- `--verbose` — emit per-worker trace (which skills were invoked, which A58/A59/A60 rows were authored).

Examples:

```
/bsa-stage 1
/bsa-stage stage2 run
/bsa-stage d1
/bsa-stage 5 --verbose
```

## What this command does

Delegate to `bsa-orchestrator`:

1. Read `config/request_skill_routes.json` to look up the worker set for the current run's `RequestType`.
2. Verify the pre-stage marker exists (e.g., `stage1.ready.json` before stage1 run). If missing, refuse with guidance.
3. Invoke the stage's worker skills in the order the routing manifest specifies:
   - **stage1**: `bsa-evidence-intake` → `bsa-claim-binder`.
   - **stage2**: `bsa-context-framer`.
   - **stage3**: `bsa-semantic-extractor`, then `bsa-citation-auditor` + `bsa-consistency-auditor` for validation.
   - **stage4**: `bsa-domain-modeler`.
   - **stage5**: `bsa-backbone-builder`, then `bsa-anchor-auditor`.
   - **stage6**: `bsa-contract-builder`, then `bsa-anchor-auditor` again.
   - **stage7**: `bsa-skeptical-reviewer`, then `bsa-citation-auditor` (re-run).
   - **stage8**: `bsa-validation-readiness`, then `bsa-no-new-claims-auditor`.
   - **d1..d5**: the corresponding `d0-*` skills.
4. Outputs land in `analysis/proposals/<stage>/` (NOT canonical).
5. On success, emit the stage's ready-for-promotion marker (e.g., `stage3.ready.json`). Run itself is NOT a promotion — user runs `/bsa-promote` after reviewing proposals.

## Output

- With `--verbose`: per-skill log lines — `[bsa-evidence-intake] read 12 sources, wrote 45 excerpts to A58 proposal`, etc.
- Without: one summary line per worker + an exit line like `Stage 3 proposals ready under analysis/proposals/stage3/. Run /bsa-promote when reviewed.`

## Failure modes

- **Pre-stage marker missing**: refuse with `stage N cannot start until stage (N-1) is promoted — emit required markers first`.
- **`A48.Mode=direct` + `<stage>=d1..d5`**: refuse — discovery stages are only valid in `discovery_then_bsa` mode.
- **Worker skill blocks on missing input**: forward the skill's error verbatim. The orchestrator does not rewrite worker errors into a different vocabulary.
- **`analysis/proposals/<stage>/` already populated**: prompt user to either keep, overwrite, or move to a backup. Never silently clobber prior output.
- **Optional sidecar tool missing** (e.g., `plantuml` for stage5/6 C4 views): continue the stage run, emit a `::notice::` in output, and mark the `.puml` view step as skipped. The anchor audit still runs; it's only the view-rendering step that degrades gracefully.

## Related

- `/bsa-audit <kind>` runs an individual audit skill against current stage outputs without re-running the producing worker.
- `/bsa-promote` promotes `analysis/proposals/<stage>/` into `analysis/canonical/<stage>/` after the required audit markers exist.
