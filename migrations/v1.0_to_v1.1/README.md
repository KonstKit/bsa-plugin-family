# Migration v1.0 → v1.1 (Sysco pilot drift bundle)

Authoritative migration guide for workspaces created against pre-v1.1.0 schema drafts (notably the Sysco pilot workspace at v1.0.x). Brings them forward to the v1.1.1 schema-and-marker contract.

## Why this migration exists

The Sysco pilot was built against early v1.0.x schema drafts before the marker / A50 / verdict / A51 enums were finalized. The drift fell into two buckets:

1. **Schema-extendable drift** — closed inside v1.1.1 itself by additive enum extensions (no migration step needed). See `governance/schemas/a51.schema.json` v1.1.1 changelog and root [CHANGELOG](../../CHANGELOG.md) once published.
2. **Migration-required drift** — the workspace content has to change. This README enumerates the migration steps and points at the (planned) `scripts/migrate_v1.0_to_v1.1.py` extension.

This document is the **migration backlog**. The script extension lands in a follow-up patch (tracked in [pilot_validation.md](../../docs/pilot_validation.md)).

## Drift catalog (Sysco pilot, v1.0.3 → v1.1.1)

The catalog is grouped by schema family. Each entry records: the legacy form found in the pilot, the canonical form mandated by v1.1.1 schemas, the migration verdict (`additive` / `mechanical` / `manual`), and the responsible migration step.

### A. Marker payload schema (mechanical)

**Symptom:** `marker_id`, `stage`, `verdict`, `timestamp`, `canon_policy_version` reported as missing required properties on every marker file.

**Root cause:** Pilot wrote markers with camelCase fields (`marker`, `emittedAt`, `canonPolicyVersion`) — pre-finalization payload shape. Validator (since v1.0.0) requires snake_case canonical fields per `governance/schemas/marker.schema.json`.

| Legacy field | Canonical field |
|---|---|
| `marker` (string) | `marker_id` (string, must be in documented alphabet) |
| `emittedAt` (ISO-8601) | `timestamp` (ISO-8601) |
| `canonPolicyVersion` (string) | `canon_policy_version` (string) |
| `stage` (already present) | `stage` (no change) |
| (missing) | `verdict` (must be one of the closed enum) |

**Migration:** mechanical rename of three field names; for `verdict` the operator MUST inspect the marker context and assign the correct enum value (`PASS|FAIL|READY|MERGED|GO|PIVOT|MORE_RESEARCH|NO_GO`). The script can suggest a default based on the marker filename pattern (`*.ready.json` → `READY`; `*.pass.json` → `PASS`; `*.merged.json` → `MERGED`; `discovery.go.json` → `GO`; `discovery.exit.pass.json` → `PASS`) and prompt the operator to confirm.

**Migration step:** `migrate_v1.0_to_v1.1.py --apply --markers-only` (planned).

### B. Verdict enum drift (manual review)

**Symptom:** `verdict: 'PASS (with caveats)'` rejected — not in the closed enum.

**Root cause:** Pilot operator added a freeform suffix to the verdict to flag that the gate passed but with caveats (e.g., open A51 routes that didn't block promotion).

**Migration:** Pre-v1.1.1 contract did not have a `PASS_WITH_CAVEATS` enum value, and the v1.1.1 hardening explicitly preserves the closed set. The migration step is operator-driven:
- If the caveats are real and unresolved → split into `verdict: PASS` + a new A51 row with `BlockingStatus=informational` documenting the caveat.
- If the caveats are already routed via existing A51 rows → drop the suffix, set `verdict: PASS`.
- If the gate genuinely should not have passed → set `verdict: FAIL` and re-run the audit.

**Migration step:** `migrate_v1.0_to_v1.1.py --report verdict-caveats` lists every affected marker; the operator handles each manually.

### C. A50 Priority enum drift (mechanical)

**Symptom:** `Priority: 'P1_high' | 'P2_medium' | 'P3_low'` rejected — not in `[low, medium, high]`.

**Root cause:** Pilot used Jira-style priority codes prefixed to the canonical value.

**Migration:** mechanical strip of the `Pn_` prefix:
| Legacy | Canonical |
|---|---|
| `P1_high` | `high` |
| `P2_medium` | `medium` |
| `P3_low` | `low` |
| `P0_critical` | (escalate to A51 — A50 schema does not have a `critical` priority; the source is critical-priority, document via A51 `IssueType=decision_needed`) |

**Migration step:** `migrate_v1.0_to_v1.1.py --apply --a50-priority` (planned).

### D. A50 ReliabilityTier enum drift (mechanical)

**Symptom:** `ReliabilityTier: 'T2_primary_notes' | 'T1_primary_recording'` rejected — not in `[T1, T2, T3, T4, T5]`.

**Root cause:** Pilot appended a free-text suffix describing the source variety.

**Migration:** mechanical strip of the `_<descriptor>` suffix; the descriptor moves into the A50 `Notes` column.
| Legacy | Canonical | New `Notes` content |
|---|---|---|
| `T1_primary_recording` | `T1` | "primary recording" appended (semicolon-separated) |
| `T2_primary_notes` | `T2` | "primary notes" appended |
| (any `Tn_*`) | `Tn` | suffix appended to Notes |

**Migration step:** `migrate_v1.0_to_v1.1.py --apply --a50-reliability-tier` (planned).

### E. A50 AccessStatus enum drift (manual review)

**Symptom:** `AccessStatus: 'readable_partial'` rejected — not in `[readable, unreadable, denied, expired, missing]`.

**Root cause:** Pilot used `readable_partial` to flag a source where only part of the document was accessible.

**Migration:** Operator decides:
- If most of the source is readable and the missing portion is non-critical → `readable` + A51 row with `IssueType=missing_source` (or `inventory_gap` if the missing portion is a category) and `BlockingStatus=informational`.
- If the missing portion is critical → `unreadable` + A51 with `BlockingStatus=hard`.

**Migration step:** `migrate_v1.0_to_v1.1.py --report a50-access-status-partial` (planned).

### F. A50 SourceID format drift (mechanical)

**Symptom:** `SourceID: 'CALL-001' does not match '^S-(?:[A-Z]{2,5}-)?[0-9]{3,4}$'`.

**Root cause:** Pilot omitted the canonical `S-` prefix on a custom source-ID family.

**Migration:** mechanical prefix:
| Legacy | Canonical |
|---|---|
| `CALL-001` | `S-CALL-001` |
| `EMAIL-001` | `S-EMAIL-001` |
| `<TYPE>-NNN` (any uppercase 2-5 char `<TYPE>` + 3-4 digit `NNN`) | `S-<TYPE>-NNN` |

**Migration step:** `migrate_v1.0_to_v1.1.py --apply --a50-source-id-prefix` (planned). The script also rewrites every A58/A59/A60 `SourceID` cross-reference in the same workspace to keep the foreign keys consistent.

### G. A60 column-set drift (manual review)

**Symptom:** A60 row lines 2..N reported missing every required column (`NegEvID`, `SourceID`, `ExcerptRef`, `RelatedClaimID`, `NegativeFinding`).

**Root cause:** Pilot's A60 file uses an entirely different column set (likely a draft schema). The CSV header in the pilot must be inspected to determine the actual columns.

**Migration:** No mechanical mapping is possible without seeing the pilot's actual A60 header. Migration step is:
1. Run `migrate_v1.0_to_v1.1.py --report a60-header-mismatch` — prints the pilot header alongside the canonical header.
2. Operator writes a per-pilot column-mapping table.
3. Operator manually rewrites the A60 (or scripts a one-off transform).

This drift is the highest-effort item in the bundle and the most likely to require operator judgment.

### H. A51 reconciliation drift (manual review)

**Symptom:** 3 A51 rows (`A51-MISS-010`, `A51-MISS-011`, `A51-MISS-015`) have canonical `ResolutionStatus=open` but are declared resolved/remediated in marker payloads (`discovery.d5.ready.json`, `discovery.go.json`).

**Root cause:** Operator marked the routes as resolved in the marker without updating the canonical A51 register. Symptom of the absence of an A51-reconciliation gate at the time the pilot was built.

**Migration:** Operator-driven decision per row:
- If the row genuinely is resolved → bump `ResolutionStatus` to `resolved | resolved_by_remediation | superseded | wontfix` (matching the upstream payload's claim).
- If the row is genuinely still open → strip the resolved/remediated language from the marker payload (or attach a sponsor waiver via H4 `## Decisions Required`).

**Migration step:** `migrate_v1.0_to_v1.1.py --report a51-reconciliation` (planned). Reads the pilot doctor output and prints each finding with both options.

### I. Legacy marker rename (already handled by v0.9 → v1.0 migration)

**Symptom:** `discovery.d5.no_new_facts.pass.json` present alongside or instead of `discovery.d5.no_new_claims.pass.json`.

**Migration:** Run `scripts/migrate_v0.9_to_v1.0.py --apply --workspace=<path>` first. This is a v0.9→v1.0 step that the pilot may have skipped; v1.1 retains the canonical `no_new_claims` filename.

**Migration step:** existing `migrate_v0.9_to_v1.0.py` (no extension needed).

## Schema-extendable drift (CLOSED in v1.1.1, NO migration needed)

Three symptoms were closed inside v1.1.1 itself by **additive** enum extensions in `governance/schemas/a51.schema.json`. Workspaces using these values will validate green against v1.1.1 schemas with no rewrite.

| Symptom | Source | v1.1.1 resolution |
|---|---|---|
| `A51 IssueType: 'inventory_gap'` rejected | Sysco pilot | `inventory_gap` added to IssueType enum (now 7 values total) |
| `A51 IssueType: 'cross_tier_contradiction'` rejected | Internal alignment (orchestrator-emitted variant for the reliability-tier-delta ≤ 1 contested rule) | `cross_tier_contradiction` added to IssueType enum (now 7 values total) |
| `A51 Severity: 'critical'` rejected | Sysco pilot | `critical` added to Severity enum (now 4 values total) |

All three extensions are backward-compatible (existing 5-value IssueType + 3-value Severity rows still validate). See `governance/schemas/a51.schema.json` field descriptions for the v1.1.1 alignment notes.

## Recommended migration order

For a v1.0.x pilot workspace:

1. **Backup** the workspace (`cp -r analysis/ analysis.bak/`).
2. **Run `bsa doctor`** to capture the current drift report (`bsa doctor > pre_migration.txt`).
3. **Run v0.9 → v1.0 migration** if not already done: `scripts/migrate_v0.9_to_v1.0.py --apply --workspace=path/to/analysis/`.
4. **Run mechanical v1.0 → v1.1 steps** (planned `scripts/migrate_v1.0_to_v1.1.py --apply --markers-only --a50-priority --a50-reliability-tier --a50-source-id-prefix`).
5. **Review and resolve manual-review findings** using the `--report` flags listed under sections B / E / G / H.
6. **Bump `A48.CanonPolicyVersion`** to match the live `.claude-plugin/plugin.json` `canonPolicyVersion.semver` (currently `1.1.1`).
7. **Re-run `bsa doctor`** — expected to be GREEN. Any remaining findings are real schema/contract violations the migration cannot mechanically fix.

## Migration tool status

`scripts/migrate_v1.0_to_v1.1.py` is **not yet implemented** as of v1.1.1. The migration backlog above is the spec for that script. Until it lands, operators with a v1.0.x pilot workspace must apply the mechanical steps manually (the catalog above gives the per-row mapping rules) and use the `bsa doctor` output as a checklist.

Tracking item: see [docs/pilot_validation.md](../../docs/pilot_validation.md) §Sysco workstream for the latest status.

## Related

- `governance/schemas/a51.schema.json` — A51 schema with v1.1.1 enum extensions.
- `governance/schemas/marker.schema.json` — marker payload schema (canonical snake_case fields).
- `skills/bsa-orchestrator/references/runtime-marker-schema.md` — marker alphabet + verdict enum.
- `scripts/migrate_v0.9_to_v1.0.py` — predecessor migration tool (sets the structural template for the v1.0 → v1.1 extension).
- `migrations/v0.9_to_v1.0/README.md` + `no_new_facts_rename.md` — predecessor migration spec.
