# Pilot Validation

Status, findings, and follow-up backlog from real-world pilot workspaces against the BSA plugin family.

## Active pilots

### Sysco (v1.0.3 → v1.1.1)

**Workspace:** `/private/tmp/sysco-pilot-v103` (operator-local; not committed).

**Status:** v1.1.1 unblocks the schema-extendable subset; mechanical migration steps + manual review items remain pending.

**Doctor verdict (against v1.1.1 schemas):**
- marker chain (main + discovery): FAIL — payload field-name drift (camelCase vs snake_case) + missing required fields.
- A51 reconciliation: FAIL — 3 rows (`A51-MISS-010`, `A51-MISS-011`, `A51-MISS-015`) with `ResolutionStatus=open` declared resolved/remediated upstream.
- privacy scan: OK.
- content validation: FAIL (21 of 22 files) — drift in marker payloads, A50 enums (Priority/ReliabilityTier/AccessStatus/SourceID format), A60 column set.
- no-new-stories: SKIP (Phase 3 not run on this pilot).

**Drift catalogue + per-class migration backlog:** [migrations/v1.0_to_v1.1/README.md](../migrations/v1.0_to_v1.1/README.md).

**Closed in v1.1.1:**
- A51 IssueType `inventory_gap` (additive enum extension; no migration needed).
- A51 Severity `critical` (additive enum extension; no migration needed).
- Schema-and-contract consistency drift (h1_spec.md / h4_spec.md / shared-control-surface-contracts.md / docs/architecture_overview.md / docs/workflow.md all aligned to the new closed sets).

**Open backlog (in priority order):**

1. **Implement `scripts/migrate_v1.0_to_v1.1.py`** (mechanical steps + `--report` flags for manual review) — see migration spec in `migrations/v1.0_to_v1.1/README.md`. Estimated effort: Medium (1-2 days).
2. **Operator runbook** for the manual-review steps (verdict caveats, A50 AccessStatus partial, A60 column-set mapping, A51 reconciliation). Estimated effort: Short (1-4h).
3. **Second-round Sysco doctor pass** after the migration extension lands. Verifies the script closes the mechanical drift; identifies any unforeseen edge cases.
4. **A60 schema-and-doc alignment**: confirm the Sysco A60 column drift is genuine schema misuse (not a draft-schema artifact). If draft-schema, note in changelog; if genuine misuse, harden the operator-facing A60 docs.

**Pilot lessons captured into the framework:**
- The `bsa doctor` validator successfully surfaces every drift class without requiring custom Sysco-specific code — confirms the dispatcher pattern in `scripts/bsa_doctor.py` is operator-friendly.
- The schema-and-contract consistency rule (every enum extension touches schema + `shared-control-surface-contracts.md` + downstream specs in the same patch) caught two would-be drift introductions in v1.1.1 (h4_spec L28 + L35) and one in h1_spec L46. Pattern is enforced via Codex review discipline and pre-commit grep checks.
- v1.1.x patch line versioning is suitable for additive enum extensions (backward-compatible).

## Pilot workflow (template for future pilots)

1. **Capture baseline doctor output** before any operator action: `bsa doctor > pre_pilot_baseline.txt`.
2. **Run the pilot end-to-end** (Stage 1 → Handoff or Discovery → Main → Handoff).
3. **Capture post-pilot doctor output**: `bsa doctor > post_pilot.txt`.
4. **Diff** the two doctor outputs to surface drift introduced by the pilot.
5. **Triage drift**:
   - Schema-extendable (additive) → close in next patch with a backward-compatible enum extension + cross-doc consistency update.
   - Mechanical migration → add to `migrations/v<N>_to_v<N+1>/` with per-row mapping rules.
   - Manual review → add to `--report` flag set; document the operator decision tree.
   - Genuine schema violation → operator-driven fix; framework does not "loosen" the schema.
6. **Update this doc** with the pilot's status + closed/open backlog.

## Pilot-validation invariants

- A pilot doctor failure is **never** unblocked by relaxing a schema invariant — only by additive extensions or by operator-driven content fixes.
- The `bsa doctor` exit code is non-zero when ANY validator reports findings; pilots are unblocked only when the exit code is zero.
- Schema extensions discovered through pilot validation MUST be reflected in EVERY contract doc in POLICY_GLOBS in the same patch (schema-and-contract consistency rule). Codex Code Reviewer guards this on every patch.
