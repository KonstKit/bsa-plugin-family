# Pilot-1 — 2nd Pass Operator Runbook

**Status:** v1.1.15 (Section K prep). The runbook closes Open Backlog #1 from `docs/pilot_validation.md`. The actual 2nd pass is operator-driven — this doc is the prep / decision-tree material.

**Prerequisite reading:** [docs/pilot_validation.md](pilot_validation.md) §"Pilot-1" (status + open backlog) and [migrations/v1.0_to_v1.1/README.md](../migrations/v1.0_to_v1.1/README.md) (drift catalogue A..I).

## When to run this runbook

You're an operator with access to a v1.0.x BSA workspace (e.g., `/private/tmp/pilot1-workspace-v1.0.x`) that needs to be brought forward to v1.1.x schemas. The 1st-pass doctor against v1.1.1 returned FAIL on multiple sections; v1.1.2 shipped `scripts/migrate_v1.0_to_v1.1.py` to mechanically close 4 of the 8 drift classes. This runbook walks you through the 2nd pass: applying the migration tool, completing the 4 manual-review steps, and verifying the workspace is now `bsa doctor`-clean.

## Time budget

* Mechanical migration apply: 5 minutes (`--all-mechanical` is one command).
* Manual reviews (B, E, G, H): 30-90 minutes total, depending on workspace size + how many marker / A50 / A60 / A51 rows the operator has to inspect.
* Doctor pre/post diff: 5 minutes.
* Reporting back: 15 minutes.
* **Total: 60-120 minutes.**

## Step 1 — Pre-flight capture

Capture the doctor baseline + back up the workspace before any migration step. The baseline is what the post-pass diff (Step 5) compares against.

```bash
# From the plugin repo:
WORKSPACE=/private/tmp/pilot1-workspace-v1.0.x
PLUGIN_REPO=$(pwd)

# Capture pre-migration doctor output.
python3 "$PLUGIN_REPO/scripts/bsa_cli.py" doctor --workspace "$WORKSPACE" \
  > /tmp/pilot1_pre_doctor.txt 2>&1

# Snapshot the workspace (rsync, NOT cp -r — preserves modes + handles
# nested symlinks predictably).
rsync -a --delete "$WORKSPACE/" "$WORKSPACE.pre-v1.1.bak/"
```

Sanity check: the pre-doctor output should be non-empty and contain at least one `FAIL` section (otherwise there's nothing for the migration to do).

## Step 2 — Mechanical migration

The 4 mechanical drift classes (A markers / C Priority / D ReliabilityTier / F SourceID format) are closed with one command:

```bash
python3 "$PLUGIN_REPO/scripts/migrate_v1.0_to_v1.1.py" \
  --workspace "$WORKSPACE" \
  --all-mechanical \
  --apply
```

The migrator writes `.pre-v1.1.bak` files alongside each modified file (idempotent — re-running is a no-op). A JSONL log lands at `$WORKSPACE/runtime/migration_log_v1.0_to_v1.1.jsonl`.

**Expected outcome**: `marker chain (main)` and `marker chain (discovery)` doctor sections close (FAIL → OK). `content validation` may still FAIL (because the manual-review classes haven't been touched yet — that's Step 3).

## Step 3 — Manual reviews (B, E, G, H)

Each manual-review class has a `--report` flag that lists the affected rows so you don't have to grep the workspace yourself.

### Class B: Verdict caveats (markers)

```bash
python3 "$PLUGIN_REPO/scripts/migrate_v1.0_to_v1.1.py" \
  --workspace "$WORKSPACE" \
  --report verdict-caveats
```

For each marker in the report output, decide:

| Pre-v1.1 marker says ... | The reality is ... | Action |
|---|---|---|
| `verdict: PASS (with caveats)` | The caveats are unresolved + still open | **Split**: set `verdict: PASS` AND add an A51 row with `BlockingStatus=informational` referencing the caveat. |
| `verdict: PASS (with caveats)` | The caveats are already routed via existing A51 rows | **Drop suffix**: set `verdict: PASS`. The A51 row(s) are sufficient documentation. |
| `verdict: PASS (with caveats)` | The caveats indicate the gate genuinely should NOT have passed | **Re-route**: set `verdict: FAIL`, re-run the audit step that emitted the marker. The downstream stage promotion gates on this marker. |
| `verdict: FAIL (with caveats)` | (any) | Drop suffix; `verdict: FAIL` is correct. The "caveats" are typically a free-text note that belongs in the marker's `notes` field, not in `verdict`. |

**Don't** invent new verdict enum values. The closed set is `{PASS, FAIL, READY, MERGED, GO, PIVOT, MORE_RESEARCH, NO_GO}`. Any other value will fail F5 validation.

### Class E: A50 AccessStatus partial (sources)

```bash
python3 "$PLUGIN_REPO/scripts/migrate_v1.0_to_v1.1.py" \
  --workspace "$WORKSPACE" \
  --report a50-access-status-partial
```

Pre-v1.1 A50 rows used `AccessStatus=readable_partial` to flag a source where only part of the document was accessible. v1.1 closes the enum to `[readable, unreadable, denied, expired, missing]` per `governance/schemas/a50.schema.json`. The migration is per-row operator judgment (per `migrations/v1.0_to_v1.1/README.md` Class E):

| Situation | Action |
|---|---|
| Most of the source is readable AND the missing portion is non-critical (e.g., an appendix the operator didn't need) | **`AccessStatus=readable`** + add an A51 row with `IssueType=missing_source` (or `inventory_gap` if the missing portion is a category) and `BlockingStatus=informational`. |
| The missing portion is critical (the operator needs that section to ground a direct claim) | **`AccessStatus=unreadable`** + add an A51 row with `IssueType=missing_source` and `BlockingStatus=hard`. The source can't ground any `direct` claim until the gap is closed. |

**Don't** add a new enum value. The closed set is `[readable, unreadable, denied, expired, missing]`. If neither row above fits, the source is one of the other 3 (`denied` = access requested but refused; `expired` = a credential lapsed; `missing` = the source itself is gone, not just access).

### Class G: A60 column-set drift (negative evidence)

```bash
python3 "$PLUGIN_REPO/scripts/migrate_v1.0_to_v1.1.py" \
  --workspace "$WORKSPACE" \
  --report a60-header-mismatch
```

Pre-v1.1 A60 may use an entirely different column set (likely a draft schema from before v1.1 finalized). The canonical v1.1 columns per `governance/schemas/a60.schema.json` are **all 7 required** (the schema marks them all in `required`; an empty string is a valid value for the optional ones, but the column header itself MUST be present):

| Column | Pattern | Purpose |
|---|---|---|
| `NegEvID` | `^NE?-(?:[A-Z]{2,5}-)?[0-9]{3,4}$` | Stable negative-evidence ID (`N-001` or `NE-001`; category-prefixed `N-INJ-001` accepted). |
| `SourceID` | `^(S-...)?$` | A50 SourceID this finding is grounded in. May be empty for global findings (no specific source). |
| `ExcerptRef` | free-form | Optional locator (A58 ExcerptID, page number, or literal `absent`). |
| `RelatedClaimID` | `^(C-...)?$` | A59 ClaimID(s) this negative-evidence relates to. May be empty. Semicolon-list for multi-claim. |
| `NegativeFinding` | non-empty | Required. Free-text description of what's absent / refuted. |
| `A51Ref` | `^(A51-...)?$` | Optional A51 cross-reference when the negative finding warrants tracking as an issue route. |
| `Notes` | free-form | Optional notes (tier-delta resolutions, contested pairs, operator context). Empty string allowed. |

Per `migrations/v1.0_to_v1.1/README.md` Class G: **no mechanical mapping is possible without seeing the pilot's actual A60 header**. Workflow:

1. The `--report a60-header-mismatch` output shows the pilot's A60 header alongside the canonical header.
2. Operator writes a per-pilot column-mapping table (which legacy column name maps to which canonical column).
3. Operator manually rewrites the A60 file (or scripts a one-off transform) per the mapping.

For tier-delta auto-resolutions or contested-pair documentation, use the **`Notes`** column free-text — there is no dedicated `SupersedingClaimID` column in v1.1 A60. Tier-delta supersession is recorded in the **A59** row's `Notes` column (`SupersededBy=<winning-ClaimID>`) per `reliability_tier_spec.md` §"By tier delta", not in A60.

Don't drop existing A60 rows during the column rewrite — every row is an audit-trail entry that's already been referenced by something downstream. This drift is the highest-effort item in the bundle and the most likely to require operator judgment.

### Class H: A51 reconciliation (issue routing)

```bash
python3 "$PLUGIN_REPO/scripts/migrate_v1.0_to_v1.1.py" \
  --workspace "$WORKSPACE" \
  --report a51-reconciliation
```

The 1st pass identified 3 rows (`A51-MISS-010`, `A51-MISS-011`, `A51-MISS-015`) with canonical `ResolutionStatus=open` but declared resolved/remediated in marker payloads (`discovery.d5.ready.json`, `discovery.go.json`). The A51 columns per `governance/schemas/a51.schema.json` are: `A51Ref, IssueType, Severity, BlockingStatus, RaisedByStage, RelatedSourceID, RelatedClaimID, NextAction, ResolutionStatus`. The `ResolutionStatus` enum is `[open, resolved, resolved_by_remediation, superseded, wontfix]`.

Per `migrations/v1.0_to_v1.1/README.md` Class H, the operator decision per row is:

| Situation | Action |
|---|---|
| The row genuinely IS resolved (the marker payload is correct) | Bump `ResolutionStatus` to one of `resolved` / `resolved_by_remediation` / `superseded` / `wontfix` — pick the value matching the upstream payload's claim. The row stays in A51 as the audit-trail entry. |
| The row is genuinely STILL OPEN (the marker payload was wrong) | Leave `ResolutionStatus=open`. **Strip the resolved/remediated language from the marker payload** (`discovery.d5.ready.json` etc.), or attach a sponsor waiver via the H4 packet's `## Decisions Required` section if the open A51 should not block downstream promotion. |

The 4 valid non-open `ResolutionStatus` values map to:
- `resolved` — closed by upstream change (the source got re-extracted, the contradiction was resolved by stakeholder input, etc.).
- `resolved_by_remediation` — closed by an in-workspace fix (e.g., a workaround landed in the proposal layer, then promoted).
- `superseded` — replaced by another `A51Ref` (the original route was split or merged into a different issue).
- `wontfix` — accepted, no action planned (e.g., the gap is acknowledged but lower-priority than the work it would block).

**Don't** silently delete the row — every A51 entry is a routed issue that's already been reported in marker output. Deletion creates audit-trail gaps. The `NextAction` column documents what was done (or what should happen next).

## Step 4 — Re-run doctor

```bash
python3 "$PLUGIN_REPO/scripts/bsa_cli.py" doctor --workspace "$WORKSPACE" \
  > /tmp/pilot1_post_doctor.txt 2>&1
```

Inspect the output. Expected end state for a successful 2nd pass:

* All `marker chain` sections: `OK` (Step 2 closes these).
* `A51 reconciliation`: `OK` (Step 3 / Class H closes this).
* `privacy scan`: `OK` (was already OK in 1st pass).
* `content validation`: `OK` (Step 2 closes the mechanical drift; Step 3 / Classes E + G close the manual-review drift).
* `no-new-stories`: `SKIP` (Phase 3 not run on Pilot-1).

If any section is still `FAIL`, the migration is incomplete — return to Step 3 with the section-specific report.

## Step 5 — Diff pre/post

```bash
python3 "$PLUGIN_REPO/scripts/compare_doctor_outputs.py" \
  /tmp/pilot1_pre_doctor.txt \
  /tmp/pilot1_post_doctor.txt
```

The helper buckets each status: `OK` and `SKIP` count as **non-problem** (clean state); `FAIL` and `ERROR` count as **problem** (operator attention needed). The classification is the cross-product:

* **CLOSED**: pre `FAIL`/`ERROR` → post `OK`/`SKIP`. Migration worked.
* **NEW**: pre `OK`/`SKIP` → post `FAIL`/`ERROR`. **Regression — investigate before declaring success.** The helper exits 1 when any NEW section is present, so CI pipelines + operators see the alert.
* **PERSISTED**: both pre and post are `FAIL` (or both `ERROR`) AND the detail content is byte-identical. Migration didn't move this item; return to Step 3 with the matching report flag.
* **CHANGED**: both pre and post are `FAIL`/`ERROR` BUT the detail content differs — partial progress (e.g., 21/22 files flagged → 3/22 files flagged), OR a status swap inside the problem bucket (`FAIL` → `ERROR`).
* **STILL_OK**: both sides are non-problem (`OK` or `SKIP`). No-op.
* **DROPPED**: section was in pre but not post.
* **ADDED**: section was in post but not pre. DROPPED + ADDED usually mean doctor was invoked with different mode flags between runs (e.g., the workspace gained an `A70_story_register.csv` between runs, which adds the `no-new-stories` section).

The helper exits with code 1 if there's any **NEW** section — operator MUST resolve regressions before reporting the migration as successful.

## Step 6 — Report back

If the 2nd pass closes the workspace cleanly, capture the following for the maintainer:

1. **`/tmp/pilot1_pre_doctor.txt`** — pre-migration baseline.
2. **`/tmp/pilot1_post_doctor.txt`** — post-migration verdict.
3. **`$WORKSPACE/runtime/migration_log_v1.0_to_v1.1.jsonl`** — the migrator's per-action log.
4. **The compare-helper output** — the operator's CLOSED / NEW / PERSISTED / CHANGED summary.
5. **Notes on each manual-review decision** — for B / E / G / H, what was the situation and what action did the operator take? This is the corpus the maintainer uses to decide whether the v1.1 schema needs further refinement (e.g., should `readable_partial` come back as a 6th AccessStatus value alongside the existing `[readable, unreadable, denied, expired, missing]`? — answer is "no" if the operator's mappings to `readable` + informational A51 OR `unreadable` + hard-block A51 were unambiguous).

Submit the bundle via the issue tracker (or attach to the `pilot_validation.md` PR if the operator has commit access). The maintainer uses it to update `pilot_validation.md` Status from "v1.1.1 unblocks the schema-extendable subset; mechanical migration steps + manual review items remain pending" to a closure note documenting the 2nd-pass outcome.

## Common gotchas

* **The migration script is idempotent.** Re-running `--all-mechanical` after a partial application is safe — it skips rows already at the v1.1 form.
* **The `.pre-v1.1.bak` files don't get auto-cleaned.** They're the rollback path. Delete them after the operator confirms the 2nd pass is successful AND the maintainer has signed off (typically 1-2 weeks later when downstream consumers have re-verified the workspace).
* **F5 hook may reject some manual-review fixes** if the row is on a canonical path. That's the contract — the hook is the last-line gate. Either route the change through the proposal layer (`analysis/proposals/`) and use `/bsa-promote`, or use the `BSA_HOOK_BYPASS_GOVERNANCE=1` env-var override (sparingly, with a comment in the migration log explaining why).
* **`runtime/migration_log_v1.0_to_v1.1.jsonl` is NOT gitignored** in the pilot workspace by default. Add `runtime/migration_log_v1.0_to_v1.1.jsonl` (or the broader `runtime/` directory) to the workspace's `.gitignore` if the operator commits the workspace to source control — the log carries timestamps + per-row diff info that doesn't need to be in version history.
* **Doctor's `no-new-stories: SKIP` is normal for Pilot-1.** That section is Phase 3 (story register) territory; Pilot-1 didn't run Phase 3.

## Cross-references

- `docs/pilot_validation.md` — pilot status registry + open backlog.
- `migrations/v1.0_to_v1.1/README.md` — drift catalogue (A..I).
- `scripts/migrate_v1.0_to_v1.1.py` — the migration tool.
- `scripts/compare_doctor_outputs.py` — pre/post diff helper.
- `scripts/bsa_cli.py::cmd_doctor` — the doctor implementation.
