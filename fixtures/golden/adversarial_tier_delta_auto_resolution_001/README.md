# Fixture `adversarial_tier_delta_auto_resolution_001` — Tier-Delta Auto-Resolution Regression Baseline

Synthetic adversarial fixture for v1.1.5 (B3). Establishes a regression baseline for the cross-tier contradiction case: when two upstream sources at **substantially different reliability tiers** (delta ≥ 2) disagree on a single measurable target, the chain MUST silently pick the higher-tier source as the winner, mark the lower-tier source as superseded, and DOCUMENT the override in A60 — **without** raising an A51 contradiction route (auto-resolution is by design).

## Why this fixture exists

The existing `adversarial_nfr_claim_contradiction_001` covers the SAME-tier case (no auto-resolution; A51 raised). This fixture covers the OPPOSITE end of the spectrum: tier-delta ≥ 2, where `reliability_tier_spec.md` mandates automatic resolution. Without this regression baseline, a future drift could cause the chain to either (a) raise spurious A51 contradictions for cases where tier hierarchy already decides, or (b) silently lose the override evidence (so operators can't audit why the lower-tier was discarded).

## Tier-delta covered

Two synthetic input files asserting different SLA windows for the same target. Tiers are intentionally far apart (T1 vs T4):

| Input file | Tier | What it claims |
|---|---|---|
| `inputs/source_001_signed_engineering_spec.md` | T1 (primary, signed engineering spec, version-controlled) | "API p95 latency target: 200 ms." |
| `inputs/source_002_marketing_blog.md` | T4 (secondary, marketing blog post, freeform paraphrase) | "Our API responds in under 1 second." |

Tier-delta = 4 - 1 = 3, well above the ≥ 2 threshold per `reliability_tier_spec.md` §By tier delta:

> **≥ 2** (e.g., T1 vs T3, T2 vs T4) | **Higher-tier wins by default.** The lower-tier row is auto-marked `SupersededBy=<higher-tier ClaimID>` in A59. Orchestrator logs `source_tier_mismatch` with `resolution=soft_resolved`. Analyst can override with an explicit A51 route if needed.

## Expected pipeline handling

A well-behaved chain must:

1. **Both claims captured in A59** — the lower-tier claim is NOT discarded entirely; it carries `SupersededBy=C-001` (pointing at the higher-tier winner) so the override evidence is auditable.
2. **Higher-tier (T1) claim wins** — `C-001` (200 ms target) carries the full tier-derived ClaimStrength (≈ 0.95 for T1).
3. **Lower-tier (T4) claim marked superseded** — `C-002` (under 1 sec) carries `ClaimStrength=0.0` AND a non-empty `SupersededBy=C-001` AND a `Notes` cell explaining the override.
4. **A60 captures the override evidence** — one row recording that C-002 is negative evidence for itself (the marketing claim is contradicted by the engineering spec at tier-delta ≥ 2).
5. **NO A51 contradiction row raised** — auto-resolution is the contract; the operator is NOT prompted with a decision they don't need to make.
6. **A60 carries the audit trail** — the override is documented for posterity, so any later operator can answer "why did we pick 200 ms?".

## Auto-resolution contract

Per `reliability_tier_spec.md`:

```
Tier-delta ≥ 2  →  higher-tier wins automatically. Log the override; raise NO A51.
Tier-delta ≤ 1  →  contested. Raise A51 with IssueType=cross_tier_contradiction.
```

This fixture covers the FIRST branch. The SECOND branch is covered by `adversarial_nfr_claim_contradiction_001` (same-tier case) and the existing tier-conflict tests (`tests/test_tier_conflict_scenarios.py`).

## Override audit trail

Operators who later wonder "why is the documented latency target 200 ms when the marketing blog says under 1 second?" can resolve by:

1. Reading `A59[C-002].SupersededBy` → points at C-001.
2. Reading `A59[C-001].Notes` → explains the tier-delta auto-resolution.
3. Reading `A60` row N-001 → captures C-002 as negative-evidence-for-itself with the rationale.
4. If the operator DISAGREES with the auto-resolution (e.g., the marketing blog actually reflects a more recent measurement), they can manually raise an A51 with `IssueType=cross_tier_contradiction` to override the auto-pick. That's the "Analyst can override" branch from the spec.

## Files

- `inputs/source_001_signed_engineering_spec.md` — first source (T1, claims 200 ms).
- `inputs/source_002_marketing_blog.md` — second source (T4, claims under 1 sec).
- `expected_outputs/canonical/core_controls/A50_source_register.csv` — 2 sources at different tiers.
- `expected_outputs/canonical/core_controls/A58_evidence_excerpts.csv` — 2 excerpts.
- `expected_outputs/canonical/core_controls/A59_claim_register.csv` — 2 claims; one with SupersededBy populated.
- `expected_outputs/canonical/core_controls/A60_negative_evidence_register.csv` — 1 audit-trail row recording the override.
- `expected_outputs/canonical/core_controls/A51_issue_route_register.csv` — EMPTY (header-only) — pinning that NO A51 row is raised for auto-resolved cases.
- `audit_expectations.json` — declarative regression baseline.
- `fixture_metadata.json` — provenance + authoring mode.

## What this fixture does NOT cover

- Same-tier contradictions (tier-delta ≤ 1) — covered by `adversarial_nfr_claim_contradiction_001` and `adversarial_multi_way_contradiction_001`.
- Block-on-contradiction failure mode — covered by `adversarial_block_on_contradiction_001`.
- Phase-3 propagation — auto-resolved cases propagate normally (the higher-tier claim's value flows down through A62/A70/A71/A72 as if there was no contradiction); the existing project_0001 happy-path fixture covers that.

## Synthetic vs live-run

`authoring_mode = synthetic_adversarial`. Hand-authored canonical state pinning the auto-resolution shape. Re-run by `tests/test_adversarial_b3_fixtures.py::TestTierDeltaAutoResolution`.

## Important note on SupersededBy

The A59 schema does not currently declare `SupersededBy` as a typed column — it's documented in `reliability_tier_spec.md` as a logical relationship. This fixture uses the `Notes` column to encode the SupersededBy reference (`SupersededBy=C-001`) so the auto-resolution audit trail is preserved without requiring a schema extension. A future v1.2 candidate is to promote `SupersededBy` to a first-class column.
