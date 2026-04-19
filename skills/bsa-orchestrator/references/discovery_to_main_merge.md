# Discovery → Main Merge and Dedup Contract

Authoritative rules for merging discovery outputs (`d1..d5`) into the main cycle (`stage1..stage8`) when the orchestrator promotes `discovery.go`. This contract is consumed by `bsa-orchestrator` during the discovery→Stage-1 bridge and by `bsa-evidence-intake` and `bsa-claim-binder` during Stage 1 intake.

Companion schema: [merge_log.schema.json](merge_log.schema.json).

## Problem statement

Discovery (`d0-*` skills) and the main cycle both author `A58/A59/A60` control surfaces, but against potentially overlapping source sets. Without a formal merge/dedup contract, three pathologies are possible:

1. **ClaimID collision.** Discovery writes `C-001`; main Stage 1 also writes `C-001`. Downstream artifacts cannot tell which is which.
2. **SourceID duplication.** Discovery intakes `source_001.md` as `S-001`; main Stage 1 intakes the same file as `S-042`. Same evidence, two provenance paths.
3. **Silent contradiction.** Discovery concludes `C-005: duplicate rate is ~15%`; main Stage 1 claims `C-005: duplicate rate is ~30%`. Without a formal merge step the contradiction is never surfaced.

## Namespace isolation

### ClaimID namespaces

Discovery and main-cycle A59 use **disjoint ClaimID prefixes**:

| Lifecycle | Prefix | Pattern | Written by |
|---|---|---|---|
| Discovery | `D-C` | `D-C-\d{3,}` (e.g., `D-C-001`) | `d0-*` skills |
| Main | `C` | `C-\d{3,}` (e.g., `C-001`) | `bsa-claim-binder` and Stage 3+ workers |

- Discovery never writes to the `C-*` namespace.
- Main-cycle workers never write to the `D-C-*` namespace.
- When discovery A59 is carried into main A59 (see "Lineage propagation" below), each promoted row is **reissued** a main-cycle `C-*` identifier; the original `D-C-*` lineage is preserved in a dedicated column.

### SourceID namespaces

Discovery `d2` A50 entries are written with the `S-` prefix. Main-cycle Stage 1 A50 also uses the `S-` prefix. **SourceIDs are shared**, not namespaced — with a deduplication step on main Stage 1 intake (below).

This asymmetry is intentional: claims are lifecycle-scoped (discovery claims can be invalidated before promotion; main claims carry forward), but sources are real-world artifacts that should not be reintaked twice.

## Deduplication policy

### Source dedup on main Stage 1 intake

When `bsa-evidence-intake` begins main Stage 1 and a discovery phase already ran, it MUST:

1. Read discovery `A50` (`analysis/discovery/canonical/core_controls/A50_source_register.csv`).
2. For each source the user references in Stage 1 intake, compare against discovery `A50` using the **source identity tuple**: `(SourceType, Origin, Title)`. Exact-match on all three = same source.
3. On match, REUSE the discovery `S-xxx` identifier. Do NOT mint a new `S-yyy`.
4. On match, merge Stage-1-specific metadata (e.g., `AccessStatus` updated, new `Notes`) by **appending**, not replacing. Existing metadata is preserved.
5. On miss (new source not seen in discovery), mint a fresh `S-xxx` using the next available number across both namespaces (discovery highest `S-N` + 1).

Alias records preserving the mapping live in the `A50.Notes` field of the promoted row: `alias-source: matched discovery S-xxx via identity tuple`.

### Excerpt dedup on main Stage 1 intake

When reusing a source from discovery, `bsa-evidence-intake` MUST also check whether excerpts for that source already exist in discovery `A58`. For each excerpt about to be authored in main Stage 1:

1. Compare `(SourceID, Locator)` tuple against discovery A58.
2. On match, REUSE the discovery `E-xxx` identifier.
3. On miss, mint a fresh `E-xxx` using the next available number across both namespaces.

Excerpt body content is re-validated against the source file; if the stored `ExcerptText` no longer matches the locator window (e.g., source was edited between discovery and main Stage 1), the orchestrator raises an `A51` with `IssueType=contradiction`, `Severity=hard`, and blocks promotion until the excerpt set is reconciled.

## Lineage propagation

When `discovery.go` fires and main Stage 1 enters execution, `bsa-claim-binder` MUST:

1. **Carry forward** every discovery `D-C-*` claim into main `A59`, **renumbered** into the `C-*` namespace.
2. Preserve the original `D-C-*` ID in a new column `DiscoveryLineage` on the main `A59` row.
3. Set `Provenance=discovery-promoted` on the carried row.
4. Carry forward `SourceID` and `ExcerptID` unchanged (they are already deduped against main A50/A58 per the source/excerpt dedup rules above).
5. Preserve `ClaimType`, `JustificationRationale`, `A51Ref`, `ClaimStrength`, and `Criticality` values.
6. Preserve negative evidence: every discovery `A60` row referencing a carried-forward claim gets a corresponding main `A60` row with `RelatedClaimID` updated to the new `C-*` ID.

## Conflict detection and resolution

A "conflict" between discovery and main is any case where two promoted rows describe the **same subject** with **inconsistent content**. The orchestrator MUST detect and block:

### Claim-level conflicts

Two A59 rows (one from discovery, one from main Stage 1 intake before lineage propagation) are in conflict when:
- They bind the same `SourceID + ExcerptID` tuple, AND
- Their `Statement` fields are not token-for-token identical (after whitespace normalization).

On conflict:
1. Orchestrator MUST emit a `merge_log.jsonl` entry with `event=claim_conflict`.
2. MUST create an `A51` row with `IssueType=contradiction`, `Severity=hard`, `BlockingStatus=hard`, `RaisedByStage=stage1`, `RelatedClaimID` pointing at BOTH discovery and main claim IDs (comma-separated in `RelatedClaimID` with explicit prefix), and `NextAction` requiring manual reconciliation.
3. Main Stage 1 promotion is blocked until the A51 row reaches `ResolutionStatus=resolved`.
4. Neither version is silently chosen; analyst MUST reconcile (keep one / keep both / replace with a new unified claim) in a proposal-layer edit before re-running promotion.

### Source-metadata conflicts

A source matched via identity tuple but with conflicting `ReliabilityTier` between discovery and main is a **soft conflict**:
1. Orchestrator emits `merge_log.jsonl` entry with `event=source_tier_mismatch`.
2. The HIGHER tier wins by default (T1 > T2 > T3 > T4 > T5 per `bsa-evidence-intake/references/reliability_tier_spec.md` once Sprint 3 US-S3-03 lands that file).
3. No A51 is raised automatically; the orchestrator logs the resolution and continues promotion.
4. If the analyst wants a different resolution, they can override in the proposal-layer edit before next promotion.

### Excerpt-text conflicts

Already covered above under "Excerpt dedup on main Stage 1 intake" — these are always hard blockers because the underlying source text has drifted.

## Merge log

Every discovery→main merge event (whether successful, conflicting, or skipped) is appended to `analysis/canonical/merge_logs/discovery_to_main_merge_log.jsonl` as a single JSON object per line.

Schema: see `merge_log.schema.json`. Event types:

| event | Meaning | Resolution |
|---|---|---|
| `source_reused` | Discovery A50 row matched by identity tuple; main S-xxx = discovery S-xxx. | Informational; no analyst action needed. |
| `source_new` | Main Stage 1 introduced a source not seen in discovery. | Informational; captures namespace growth. |
| `excerpt_reused` | Discovery A58 row matched by (SourceID, Locator); main E-xxx = discovery E-xxx. | Informational. |
| `excerpt_text_conflict` | Discovery and main disagree on excerpt body for same (SourceID, Locator). | Hard block; raise A51 contradiction; promotion halts. |
| `claim_lineage` | Discovery D-C-xxx promoted to main C-yyy with preserved lineage. | Informational. |
| `claim_conflict` | Same (SourceID, ExcerptID) bound to conflicting Statement. | Hard block; raise A51 contradiction; promotion halts. |
| `source_tier_mismatch` | Source matched but ReliabilityTier differs. | Soft resolution; higher tier wins; log only. |
| `a60_lineage` | Discovery negative evidence A60 row carried forward. | Informational. |

Each log entry carries the `canon_policy_version` active at merge time, so downstream drift analysis (Sprint 3 US-S3-04) can detect events that happened under a different policy version than the current one.

## Promotion sequencing

The merge step fits into the existing Two-Key Promotion Sequence (`workflow-contract.md`) as follows:

1. Validate stage-owned proposal directory.
2. Validate evidence-binding and shared-control-surface references.
3. **NEW: Run the discovery→main merge step (when discovery phase produced `discovery.go`).** Any `claim_conflict` or `excerpt_text_conflict` events raise A51 and halt promotion here.
4. Validate required audit marker(s).
5. Acquire merge lock.
6. Promote artifacts (including the updated main A50/A58/A59/A60 with carried-forward lineage).
7. Promote control surfaces.
8. Append merge_log events to the canonical merge log.
9. Emit next ready/control markers.

## Out of scope for this contract

- **Re-merge after discovery re-entry.** If discovery is re-run after main Stage 1 already promoted, the merge-log append semantics cover it, but downstream lineage repair requires a separate "re-merge" play documented elsewhere. Sprint 3 does not specify it; Sprint 4+ may.
- **Cross-run merge** (pulling discovery output from a *different* `RunID` into the current main cycle). Forbidden by INV-02 single-writer rule; not supported.
- **Direct-mode runs.** No merge step runs when the orchestrator executes in `direct` mode — there is no discovery output to merge from. Validators MUST skip this contract entirely in that case.

## Cross-references

- Schema: `merge_log.schema.json` (this directory).
- Merge checklist: `merge-and-reentry-policy.md`.
- Promotion sequence: `workflow-contract.md` §"Promotion Sequence (Two-Key)".
- Shared control surfaces: `shared-control-surface-contracts.md`.
- ReliabilityTier (upstream of source_tier_mismatch resolution): `bsa-evidence-intake/references/reliability_tier_spec.md` (landing in Sprint 3 US-S3-03).
- Validation scenarios: `validation-scenario-manifest.csv` — see `SCN-ORCH-001-C` (lock-based merge) and the Sprint-3 sub-scenarios added for discovery→main merge.
- Invariants: `governance/immutable_invariants.md` — INV-02 (single-writer canonical), INV-05 (A51 is not a positive-claim source), INV-07 (ClaimType schema closed).
