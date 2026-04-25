# Phase 7 Operator Runbook (L1b Miner + L2 Patcher)

Status: **opt-in operator workflow** as of v1.2.19. None of the steps below run automatically; the operator drives every transition. The Phase 7 self-improvement loop is observation + proposal generation; **all canonical changes still go through human review + standard release process** (`docs/RELEASING.md`).

## Pipeline overview

```
analysis/telemetry/run_*.json           (L1a — telemetry collector, v1.2.4)
            │
            ▼
phase_7_miner.py  ───▶  miner_proposals.json   (L1b — v1.2.18)
            │
            ▼
phase_7_patcher.py ───▶ proposals/<id>.patch   (L2 — v1.2.19, this doc)
            │
            ▼
analyst review + git apply + manifest bump  (operator-driven)
```

Each box is a separate, independently-runnable script. None of them invoke each other. Operators run them in sequence (or skip stages — e.g., re-run only the patcher after editing a single proposal in the bundle).

## Routine review pass

Run this as a periodic operator task — once per release cycle, or after any pilot whose runs landed in `analysis/telemetry/`.

### 1. Capture telemetry (if not already)

If you've been running `phase_7_telemetry_collector.py` after every pipeline pass, you can skip this. Otherwise:

```bash
python3 scripts/phase_7_telemetry_collector.py --workspace .
```

Each invocation appends one `run_*.json` to `analysis/telemetry/`. The collector is observation-only — safe to re-run.

### 2. Mine the telemetry window

```bash
python3 scripts/phase_7_miner.py --workspace . --window-days 30
```

Reads all in-window snapshots, emits `analysis/telemetry/miner_proposals.json`. v1.2.18 ships a stub algorithm — `proposals[]` is always empty. When the real algorithm lands, this is where it'll surface tuning candidates.

Inspect the bundle summary:

```bash
python3 -c "import json; print(json.dumps(json.load(open('analysis/telemetry/miner_proposals.json'))['summary'], indent=2))"
```

Note `runs_excluded_malformed` — non-zero means some telemetry files are corrupt or non-UTC; investigate.

### 3. Materialize patches

```bash
python3 scripts/phase_7_patcher.py --workspace .
```

Writes `<output_dir>/<proposal_id>.{patch,summary.md}` for every proposal that passes the 7 validation gates (see `docs/phase_7_design.md` §"L2 status (v1.2.19)"). Plus `<output_dir>/_index.json` summarizing all attempts (written / rejected / skipped, with reasons). Default `<output_dir>` is `analysis/telemetry/proposals/`; override via `--output-dir <path>` (works both inside and outside the workspace).

Inspect (substitute your `<output_dir>` if you used `--output-dir`):

```bash
ls analysis/telemetry/proposals/
cat analysis/telemetry/proposals/_index.json
```

If `_index.json` shows zero `patches_written`, you're done — no actionable proposals this cycle.

### 4. Per-proposal analyst review

For each `<proposal_id>.patch`:

a. **Read the summary.** `cat <output_dir>/<id>.summary.md`. The summary lists the rationale, the cited evidence-run IDs, the linked invariants, AND a copy-pasteable `git apply` command with the actual patch path (repo-relative when the patch is in the workspace, absolute when `--output-dir` placed it elsewhere).

b. **Inspect the patch.** `cat <output_dir>/<id>.patch`. The diff is single-file, single-line — minimal and reversible per Safety Contract item 4.

c. **Decide.** Is the change justified? Does the cited evidence reflect a real pattern (not pilot noise)? Does the new value align with the operator's understanding of pipeline health?

d. **If rejected**: do nothing. The patch file stays in `<output_dir>` as an audit trail (the file is operator-side, deletable safely if you want a clean tree). Record the decision somewhere if your process needs it; the patcher does NOT track operator decisions.

### 5. Apply approved patches

For each approved proposal, from the **repo root**, copy the `git apply` command from the proposal's summary file (it carries the right path verbatim — repo-relative for default `output_dir`, absolute for `--output-dir` overrides). Equivalent for the default location:

```bash
git apply analysis/telemetry/proposals/<proposal_id>.patch
git diff <source_file>           # confirm the change is what you expect
```

Then update `config/tunables.yaml` so its `current_value` matches the new live value:

```yaml
- id: <tunable_id>
  current_value: "<new_value>"   # was the previous value
  ...
```

Both edits — the source-file patch AND the tunables.yaml `current_value` — go in **one commit**. This keeps `phase_7_lint.py` C1 (source line contains current_value) green.

### 6. Re-run lint + canon hash

```bash
python3 scripts/phase_7_lint.py
python3 scripts/compute_canon_hash.py --diff-against <prev_hash>
```

If the source file is in POLICY_GLOBS (i.e., the tunable's `change_class=L2_proposal_only` AND its source_file matches a POLICY_GLOBS pattern), the canon hash will move. Bump `.claude-plugin/plugin.json::version` + `canonPolicyVersion.semver` + `hash_*` fields lockstep — see `docs/RELEASING.md` §"Two-semver convention recap".

If the source file is OUTSIDE POLICY_GLOBS, the canon hash stays — manifest does NOT need to bump (canon-neutral release).

### 7. Commit + tag

Per `docs/RELEASING.md`:

- One commit titled `release(vX.Y.Z): tune <tunable_id> from <old> to <new> per <evidence>` is preferred — operator-readable + git-bisectable.
- Tag the commit annotated; do NOT push (repo is local-only).

## Edge cases

### Proposal rejected with `current_value drift`

Means the tunable was edited between the miner run and now. Re-run the miner — its observation is stale.

### Proposal rejected with `out of allowed_range`

Means the proposed value is outside the bounds the tunable's `allowed_range` declares. If the bounds themselves are wrong (e.g., a tunable was provisioned with `[0, 1]` but real-world values cluster around `[0, 5]`), edit `tunables.yaml::allowed_range` first (separate commit), re-run the miner.

### Proposal rejected with `immutable_conflict`

Means the tunable touches an invariant AND was somehow proposed for L1 auto-merge. The patcher refuses unconditionally. Investigate `phase_7_lint.py` C5 — the static check should have caught this earlier.

### `_index.json` shows mostly `skipped` (L1 path)

That's fine — the patcher is L2-only by design. L1 auto-tunable proposals don't need the patcher; they're handled by a separate (future) L1 auto-merge tooling outside this script.

## What this runbook does NOT cover

- The mining algorithm itself. v1.2.18 ships a stub; when the real algorithm lands, `_mine_proposals` will surface real candidates.
- Multi-pilot aggregation. Currently the miner reads one workspace's telemetry; combining across pilots is a future concern.
- Auto-apply. By design the operator approves + applies + commits manually. The "auto" in L2 is the proposal-to-patch materialization, not the apply.
- Roll-back beyond `git revert`. Patches are minimal + single-line + reversible; if a tuning change misfires, `git revert <tuning-commit>` undoes it cleanly.

## Cross-references

- `docs/phase_7_design.md` — full L0 / L1a / L1b / L2 architecture + safety contract
- `governance/immutable_invariants.md` §"Scope of self-improvement (Phase 7 L1/L2)"
- `governance/schemas/miner_proposal.schema.json` — bundle shape consumed by the patcher
- `scripts/phase_7_lint.py` — static IMMUTABLE_CONFLICT check + 7 other tunable-inventory invariants
- `docs/RELEASING.md` — two-semver convention; how canon-bumping vs canon-neutral releases differ
