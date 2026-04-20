# Install — bsa-full

Installation, uninstall, and troubleshooting guide for the BSA Plugin Family (`bsa-full`) in Claude Code.

## Prerequisites

- Claude Code installed (any version supporting the plugin system).
- Python 3.9+ (for the included `compute_canon_hash.py` and `validate_marker_chain.py` scripts).
- Optional: `plantuml` for C4 sidecar rendering, `xmllint` for BPMN sidecar validation. Both are optional; the plugin degrades gracefully if either is absent.

## Install

```
/plugin marketplace add https://github.com/kkitanin/bsa-plugin-family
/plugin install bsa-full
```

What happens under the hood:
1. Claude Code clones the repo into its plugin cache.
2. It reads `.claude-plugin/plugin.json` to discover the plugin name (`bsa-full`) and skill/command/hook paths.
3. All 23 skills under `./skills/` become available via their `SKILL.md` `name` field.
4. All 6 slash commands under `./commands/` become available as `/bsa-start`, `/bsa-status`, `/bsa-stage`, `/bsa-promote`, `/bsa-audit`, `/bsa-handoff`.
5. The three hooks in `./hooks/hooks.json` (SessionStart, PreToolUse:Write, PreToolUse:Bash) register with the event dispatcher.

Verify the install:

```
/plugin list
```

Expected output includes `bsa-full@1.0.0-rc1` (or `@1.0.0` at the final cut).

## First use — in a fresh project directory

```
/bsa-start --mode=direct
/bsa-status
```

`/bsa-start` creates the `analysis/` runtime layout and seeds `A48_run_context_card.md`. `/bsa-status` confirms the workspace is ready for `/bsa-stage 1 run`.

If you are working in a directory that already has a prior BSA workspace, the **SessionStart hook** surfaces a suggestion automatically — no need to type `/bsa-status` manually.

## Uninstall

```
/plugin uninstall bsa-full
```

What this does:
- Removes the plugin binaries from Claude Code's plugin cache.
- **Does NOT touch your `analysis/` runtime state.** Any workspace you've initialized with `/bsa-start` keeps its canonical / proposal / runtime content intact.
- If you want to remove the workspace too, delete `./analysis/` manually. Always back up first if there's promoted canonical content you care about.

To reinstall later, re-run the install commands. Your workspace picks up where it left off as long as the marker chain is consistent (the marker-chain validator will tell you otherwise).

## Upgrade

```
/plugin marketplace add https://github.com/kkitanin/bsa-plugin-family   # already-added is OK, refreshes cache
/plugin install bsa-full@latest
```

Claude Code checks GitHub Releases to determine available versions; pinning to an earlier tag is supported via `@v1.0.0-rc1`.

After an upgrade, check the `/bsa-status` output for a `policy_version_drift_warning`: the plugin's `CanonPolicyVersion` may have moved between your last workspace run and the new plugin version. This is advisory in Sprint 3/4 (bumps are expected); Phase 3+ may elevate it to blocking for production runs.

## Troubleshooting

### "Plugin installed but `/bsa-*` commands don't appear"

- Restart Claude Code.
- Run `/plugin list` — if `bsa-full` is not listed, the install didn't take. Re-run `/plugin install bsa-full`.
- Check for a conflicting plugin with the same name in your installed set.

### "`/bsa-promote` fails with 'missing required marker: ...' even though I ran the audit"

The `PreToolUse:Bash` hook reads `A48_run_context_card.md.CurrentStage` to determine which markers are required. If you ran the stage's audit but `A48` still reports an earlier `CurrentStage`, the hook looks for the wrong marker set.

- Check `analysis/canonical/core_controls/A48_run_context_card.md` — the `CurrentStage` value must match the stage you're promoting.
- If `A48` drifted from reality, do NOT edit it by hand. Run `/bsa-stage <stage>` + `/bsa-audit <kind>` + `/bsa-promote` for the matching stage so the orchestrator rewrites `A48.CurrentStage` as part of a promotion. Manual edits are a maintenance procedure (see next section) and should not be a routine troubleshooting step.

### "Canonical writes are blocked but I need to hand-edit — maintenance procedure"

The `PreToolUse:Write` hook enforces INV-02 (single-writer canonical). Only `bsa-orchestrator` may write to `analysis/canonical/`. There are rare cases where a maintainer must edit canonical state by hand — recovering from a corrupted A48 row, applying a migration that the orchestrator cannot drive, backfilling a `Provenance` column on a pre-Sprint-3 workspace. The override procedure is deliberately formal to keep the audit trail intact:

1. **Check whether a scripted migration already exists** under `migrations/`. If yes, prefer the scripted path — the migration script emits a log entry automatically.
2. **Open an `A51` row** with `IssueType=decision_needed`, `BlockingStatus=soft`, `RaisedByStage=maintenance`, `NextAction` describing the planned edit + rationale + expected rollback procedure. The A51 entry is the approval record.
3. **Attach sponsor sign-off** in the A51 row's `ResolutionStatus` field (e.g., `approved-by: <sponsor-name>` with a date).
4. **Create a matching migration log** at `migrations/manual_canonical_edits/<YYYY-MM-DD>_<short_slug>.md` documenting the before/after diff, the A51Ref, the sponsor, and the expected canon-hash impact.
5. **Perform the edit** with the override only after steps 1-4 are in place:
   ```
   BSA_WRITER=bsa-orchestrator <your edit command>
   ```
6. **Run `/bsa-status`** afterwards to confirm the marker chain + canon hash + A51 set are consistent. The drift detection (see `skills/bsa-anchor-auditor/references/anchor-audit-contract.md`) will flag the change on the next anchor audit; the matching A51 row is how you mark it as "known and approved".

Skipping any of steps 1-6 leaves the maintenance edit invisible to downstream auditors, which is a governance failure. The `BSA_WRITER` env-var override is the TECHNICAL gate; the A51 + migration log is the PROCEDURAL gate. Both must hold.

### "`plantuml` or `xmllint` not found — should I worry?"

No. These are optional sidecar dependencies. The plugin reports their absence as an informational notice and skips the sidecar view generation:

- Without `plantuml`: `analysis/views/c4/*.puml` files are still emitted, but `.png` / `.svg` rendering is skipped.
- Without `xmllint`: well-formedness / schema validation of the emitted `.bpmn` XML is skipped. Structural checks inside the skill (`skills/camunda-bpmn-from-context/scripts/semantic_validate_bpmn.py`) still run; only the extra `xmllint --noout` pass is missing.

Install via your system package manager if you want the full sidecar experience (`apt install plantuml libxml2-utils` on Debian/Ubuntu; `brew install plantuml libxml2` on macOS).

### "`/bsa-status` reports 'chain-gap' for my workspace"

The marker-chain validator (`scripts/validate_marker_chain.py`) detected a prefix gap — e.g., `stage2.context_state.pass.json` is present but `stage1.excerpts.merged.json` is missing. Common causes:

- Manually deleted a marker.
- Ran `/bsa-stage` without promoting the prior stage (the stage workers emit `.ready.json`, but only `/bsa-promote` turns that into the next stage's pass marker).

Fix by running the missing stage's worker + audit + promote sequence, or by clearing downstream markers and restarting from the gap.

### "Install succeeds on macOS but fails on Linux with 'permission denied' on hook scripts"

The hook scripts (`./hooks/*.sh`) need the execute bit. If your shell/filesystem stripped it during cloning:

```
chmod +x <plugin-install-dir>/hooks/*.sh
```

GitHub's archive step preserves file modes; this should only happen with a manual `wget`/`unzip` install flow.

## Uninstall with preservation

If you want to remove the plugin but keep all your workspace state:

```
/plugin uninstall bsa-full
# your analysis/ directory stays intact
```

If you want to reset your workspace but keep the plugin installed:

```
mv analysis analysis.bak  # never delete outright
/bsa-start --mode=direct
```

## Support

- Issues: https://github.com/kkitanin/bsa-plugin-family/issues
- Plugin docs: this repo's `README.md`, `CHANGELOG.md`, and per-skill `SKILL.md` files.
- BSA methodology docs: `docs/`, `skills/bsa-orchestrator/references/`, `governance/immutable_invariants.md`.
