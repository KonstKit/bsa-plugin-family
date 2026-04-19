# Migration v0.9 → v1.0

Authoritative migration guide for workspaces (`analysis/` runtime state directories) created under CanonPolicyVersion 0.9 that need to be brought forward to the Sprint-2 rename contract.

## Scope

Sprint 2 (US-S2-02) renamed `bsa-no-new-facts-auditor` → `bsa-no-new-claims-auditor`. The rename propagates to four places in workspace runtime state:

1. **Discovery marker filename:** `analysis/discovery/runtime/ready/discovery.d5.no_new_facts.pass.json` → `discovery.d5.no_new_claims.pass.json`
2. **Stage 8 report:** `analysis/**/stage7_8/stage8/no_new_facts_report.md` → `no_new_claims_report.md`
3. **Handoff report:** `analysis/**/stage7_8/handoff/handoff_no_new_facts_report.md` → `handoff_no_new_claims_report.md`
4. **Discovery D5 report:** `analysis/**/discovery/**/d5/discovery_no_new_facts_report.md` → `discovery_no_new_claims_report.md`

The `stage8.no_new_claims.pass.json` main-cycle marker already uses the correct `no_new_claims` naming — no rename needed there.

## Migration tool

`scripts/migrate_v0.9_to_v1.0.py` performs the workspace-level rename. It is:

- **Idempotent:** re-running after a clean migration is a no-op.
- **Non-destructive:** it never overwrites an existing target file. If both `no_new_facts_report.md` and `no_new_claims_report.md` exist, the migration halts with `migration-target-conflict` so the operator can reconcile manually.
- **Scoped:** it touches only the 4 filename patterns above, under `analysis/` (main cycle) and `analysis/discovery/` (discovery branch). No other files are modified.
- **Logged:** emits a JSONL migration log at `analysis/runtime/migration_log_v0.9_to_v1.0.jsonl` with one record per rename (`from_path`, `to_path`, `timestamp`, `mode=renamed|skipped|error`).

## Usage

```bash
# Dry-run (default): scan but do not modify
scripts/migrate_v0.9_to_v1.0.py --workspace=path/to/analysis/

# Apply the migration
scripts/migrate_v0.9_to_v1.0.py --workspace=path/to/analysis/ --apply
```

Exit codes:

- `0` — migration successful (or dry-run without conflicts).
- `1` — migration-target-conflict detected (both legacy and new filenames exist for at least one mapping). Log lists every conflict; no renames applied.
- `2` — invocation error (missing workspace, unreadable file).

## Partial-state workspaces

The migration tolerates partial-state workspaces where Stage 8 and/or handoff outputs are incomplete:

- A missing legacy filename is simply skipped (logged as `mode=skipped`, reason `source-missing`).
- A present legacy filename with no existing target counterpart is renamed.
- Both present → conflict (see above).

## Canon policy version

- Before migration: `A48.CanonPolicyVersion = 0.9` (or unspecified on pre-Sprint-0 workspaces).
- After migration: the tool does not touch `A48_run_context_card.md` directly. The operator is responsible for bumping `CanonPolicyVersion` and any dependent marker fields after the rename migration succeeds — see `governance/immutable_invariants.md` contract-versioning section.

## Related

- `scripts/migrate_v0.9_to_v1.0.py` (the tool)
- `tests/test_migrate_v0_9_to_v1_0.py` (regression tests covering fresh, partial, conflict, idempotent, and dry-run cases)
- `skills/bsa-no-new-claims-auditor/SKILL.md` (backward-compatibility section)
- Sprint 2 US-S2-02 ACs in `/Users/kkitanin/.claude/plans/dreamy-wiggling-zebra.md`
