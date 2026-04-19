# US-S2-02 Rename Specification

Authoritative rename specification for the Sprint 2 US-S2-02 no-new-facts → no-new-claims migration. Consumed by `scripts/migrate_v0.9_to_v1.0.py` and its tests.

## Rename mappings

Exactly four filename patterns are renamed. Each entry is `{legacy_pattern → canonical_pattern}` relative to the workspace root (usually `analysis/`).

### 1. Discovery marker

- **Legacy:** `**/discovery/runtime/ready/discovery.d5.no_new_facts.pass.json`
- **Canonical:** `**/discovery/runtime/ready/discovery.d5.no_new_claims.pass.json`
- **Semantics:** optional run-profile marker for discovery D5 no-new-claims gate. Main-cycle `stage8.no_new_claims.pass.json` marker already used the canonical name since Sprint 0 and is NOT touched by the migration.

### 2. Stage 8 report (main cycle, promoted canonical)

- **Legacy:** `**/canonical/stage8/no_new_facts_report.md`
- **Canonical:** `**/canonical/stage8/no_new_claims_report.md`

### 2a. Stage 8 report (proposal layer, pre-promotion)

- **Legacy:** `**/proposals/stage7_8/stage8/no_new_facts_report.md`
- **Canonical:** `**/proposals/stage7_8/stage8/no_new_claims_report.md`

### 3. Handoff report

- **Legacy:** `**/proposals/stage7_8/handoff/handoff_no_new_facts_report.md`
- **Canonical:** `**/proposals/stage7_8/handoff/handoff_no_new_claims_report.md`

### 4. Discovery D5 report

- **Legacy:** `**/discovery/canonical/d5/discovery_no_new_facts_report.md` AND `**/discovery/proposals/d5/discovery_no_new_facts_report.md`
- **Canonical:** same paths with `no_new_claims` in place of `no_new_facts`.

## Out of scope

The migration deliberately does NOT touch:

- `A48_run_context_card.md` `CanonPolicyVersion` field — operator-controlled.
- Main-cycle marker `stage8.no_new_claims.pass.json` — already canonical.
- Any file outside `analysis/`.
- File *content* changes (the rename is filename-only; body edits, if any, are operator responsibility and handled by the usual skill/orchestrator flow).

## Migration log schema

Each migration operation appends one JSONL record to `analysis/runtime/migration_log_v0.9_to_v1.0.jsonl`:

```json
{
  "timestamp": "2026-04-19T12:00:00Z",
  "migration": "v0.9_to_v1.0",
  "mapping_id": 1,
  "from_path": "analysis/discovery/runtime/ready/discovery.d5.no_new_facts.pass.json",
  "to_path": "analysis/discovery/runtime/ready/discovery.d5.no_new_claims.pass.json",
  "mode": "renamed",
  "dry_run": false
}
```

`mode` values: `renamed | skipped | error`. For `skipped` and `error`, an additional `reason` field gives the cause (`source-missing`, `target-conflict`, `permission-denied`, etc.).

## Idempotency

A second run after a clean apply produces zero `renamed` records; every mapping becomes `skipped` with `reason=source-missing`. That is the expected steady state.

## Conflict resolution

If both legacy and canonical filenames exist for any mapping, the run fails with exit code `1` and logs an `error` record with `reason=target-conflict`. No renames are applied for any mapping, so the workspace state is not partially migrated. The operator reconciles manually by choosing which file to keep (diff them; typically the canonical already contains the authoritative content), deletes the other, and re-runs the migration.
