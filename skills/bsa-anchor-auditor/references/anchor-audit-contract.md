# Anchor Audit Contract

## Required Sections
- anchors audited
- anchors with `ClaimID`
- anchors with `A51Ref`
- orphan anchors count
- duplicate anchors count
- class mismatch count
- drift findings count (Sprint 3 US-S3-04)
- drift findings (detailed list; see below)
- verdict (`PASS`/`FAIL`)

## Rules
- A positive anchor cannot be justified by `A51Ref` alone when upstream evidence is expected to exist.
- `A51Ref` is allowed only for explicitly unresolved candidate anchors that remain unpromoted.

## Drift Detection Rules (Sprint 3 US-S3-04)

An anchor has "drifted" when its identity, class, or bound claim reference changes between audit runs in a way that upstream canonical claims do not justify. Three drift categories MUST be detected and reported:

### `drift_type=semantic_rename_no_pivot`
The anchor's `name` changed (e.g., `PaymentService` → `TransactionService`) WITHOUT a matching "pivot claim" — an A59 row of `ClaimType=direct` or `ClaimType=inference` whose Statement justifies the rename. A silent rename is the most dangerous drift mode because downstream consumers (contracts, diagrams, handoff packs) follow the new name without evidence of the change.

Detection: compare current `A61_anchor_map_candidate.csv` row's `name` against the same `AnchorID` in the last promoted `A61_anchor_map.csv`. If the name changed AND no A59 row dated after the previous A61 promotion binds to the AnchorID, fire `semantic_rename_no_pivot`.

### `drift_type=semantic_change_no_claim`
The anchor's `description`, `bindings`, or `class` field changed without a matching new A59 claim justifying the change. Catches mutations that keep the name but alter what it means.

Detection: diff the row against the prior promoted version (ignoring cosmetic whitespace). If any substantive field changed AND no new A59 row links to the AnchorID with a post-promotion ExcerptID, fire `semantic_change_no_claim`.

### `drift_type=class_change_no_pivot`
The anchor's `class` changed (e.g., `actor` → `system`) without a pivot claim. This is a schema-level drift that invalidates every downstream view-element mapping to this anchor.

Detection: compare class value across runs. If class changed AND no new A59 row is present OR the change contradicts a prior still-valid A59 row, fire `class_change_no_pivot`.

### Report schema

The audit JSON report (`anchor_audit_report.json`) MUST carry a `drift_findings` array alongside the existing summary counts:

```json
{
  "anchors_audited": 42,
  "drift_findings_count": 1,
  "drift_findings": [
    {
      "anchor_id": "ANC-SYS-007",
      "drift_type": "semantic_rename_no_pivot",
      "old_value": "PaymentService",
      "new_value": "TransactionService",
      "pivot_claim_id": null,
      "observed_at": "2026-04-20T14:30:00Z"
    }
  ]
}
```

`pivot_claim_id` is `null` when no justifying claim exists; populated with the ClaimID when the change IS legitimately pivot-justified (in which case the finding is NOT raised — the field is informational for audit-trail readers).

### Gate behavior

Every drift finding fires an `A51` row with `IssueType=boundary_risk`, `BlockingStatus=hard`, `RaisedByStage=stage5` (or `stage6`), `RelatedClaimID=<anchor_id>`. Anchor audit verdict is `FAIL` until the A51 is either (a) resolved with a pivot claim added and anchor re-evaluated, or (b) explicitly waived via sponsor sign-off recorded in the same A51 row.

## CanonPolicyVersion hash (Sprint 3 US-S3-04)

Every runtime marker (`*.pass.json`, `*.ready.json`, etc.) MUST carry a `canon_policy_version_hash` field alongside the existing `canon_policy_version` field. The hash is computed by `scripts/compute_canon_hash.py` over a fixed set of policy files. See `skills/bsa-orchestrator/references/contract-versioning.md` for the authoritative specification.

During anchor audit, markers from the prior promotion are compared against the current canon hash: if the hash differs between the prior-promotion marker and the current run, the report emits a `policy_version_drift_warning` in the header. This is advisory-only during Sprint 3 (policy bump is expected); Sprint 4+ may elevate it to blocking for production runs.
