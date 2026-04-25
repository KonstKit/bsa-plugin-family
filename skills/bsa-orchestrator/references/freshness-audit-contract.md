# Freshness Audit Contract

Status: **opt-in operator runner** as of v1.2.16. Not invoked automatically by the orchestrator and not part of any mandatory marker family. The skill is `scripts/freshness_audit.py` (stdlib-only, observation pattern of `phase_7_telemetry_collector.py`).

## Scope

Freshness audit assesses whether sources in `analysis/canonical/core_controls/A50_source_register.csv` are recent enough to be considered authoritative for downstream evidence-binding (INV-01). It is purely **temporal** — it does not re-validate access status, content, or tier; those are A50-intake concerns covered by `bsa-evidence-intake`.

Audit input:
- `analysis/canonical/core_controls/A50_source_register.csv` (canonical post-promotion).
- Optional A59 cross-reference for impact reporting (which level-1 / level-2 claims depend on stale sources).

Audit output:
- Markdown report `analysis/canonical/stage1/freshness_audit.md`.
- JSON marker `analysis/canonical/stage1/freshness_audit.json` carrying the verdict.
- Optional A51 entries when blocking-stale sources are tied to evidence-bound claims (operator-confirmed flag, never auto-emitted to canonical state).

## EffectiveDate field

`EffectiveDate` is an optional field on A50 (added in v1.2.16, see `governance/schemas/a50.schema.json`). Three accepted forms:

1. **ISO-8601 calendar date** (`YYYY-MM-DD`) — the operator-attested effective date. Must be a real calendar date — `2025-02-30` is shape-valid by regex but rejected by the F5 hook via the `x-bsa-strict-date-rules` extension (closed v1.2.16 R2).
2. **Literal `unknown`** — operator declares "cannot assess". Audit verdict for that row is `n/a` (never blocks).
3. **Empty string** — gradual row-by-row backfill state; same semantics as the field being absent on a pre-v1.2.16 row. Audit verdict is `n/a`. This form lets an operator add the column to an existing manifest, populate values one at a time, and have the half-backfilled CSV still pass canonical promotion.

Absent field is also `n/a` — backward-compatible with pre-v1.2.16 A50 rows that have no `EffectiveDate` column at all.

`EffectiveDate` is intentionally separate from the free-form `DateOrVersion` field. `DateOrVersion` may carry semver tags, commit hashes, or human dates (`"v3.4"`, `"abc12def"`, `"early 2024"`); none of those are machine-comparable for staleness. `EffectiveDate`, when populated with a date, MUST parse as a real calendar date — that is the contract that lets the audit do arithmetic.

## Rules

For each A50 row:

1. **Missing or `unknown` EffectiveDate** → `status: n/a`. No A51 raised. Audit does not infer a date from `DateOrVersion`; the operator is the only authority for what counts as the "effective" calendar date of a source.
2. **EffectiveDate parseable, `(today_utc - EffectiveDate) <= freshness_threshold_days`** → `status: fresh`.
3. **EffectiveDate parseable, `(today_utc - EffectiveDate) > freshness_threshold_days`** → `status: stale`. Routing depends on the dependent-claim coupling (next section).

The audit uses UTC midnight for `today_utc` to keep results stable across operator timezones and to avoid off-by-one flapping in tests run near midnight.

## Tunable bind

The threshold lives in `config/tunables.yaml` as `freshness_threshold_days` with `current_value: "180"` days (default). Allowed range: `[30, 720]`. Change class: `L2_proposal_only` with `linked_invariants: [INV-01]` — the threshold influences which sources are still acceptable evidence for claim-binding, so any change goes through analyst sign-off (no L1 auto-patch).

The `current_value: "180"` literal MUST appear verbatim in this contract (this paragraph) so `scripts/phase_7_lint.py` C1 (source_file:source_line substring match) passes.

## Tier-aware policy

Reliability tiers (T1..T5 per `skills/bsa-evidence-intake/references/reliability_tier_spec.md`) are NOT used as freshness multipliers. A T5 source that is 200 days old is just as stale as a T1 source that is 200 days old — tier is about epistemic proximity at the moment of capture, not about decay. The tier-vs-decay coupling that DOES exist (`decay_factor_cap` tunable) is a separate, opt-in mechanism on `ClaimStrength` and is unaffected by this audit.

Operators who genuinely want tier-conditional freshness (e.g. tighten threshold for T1 live-system observations) should raise an A51 `decision_needed` route requesting a per-tier threshold extension. v1.2.16 ships only the single global threshold.

## Gate behavior

The freshness audit is **non-blocking by default** in v1.2.16:

- The audit always emits a report and marker, regardless of stale-row count.
- Stale rows are reported per row with their dependent-claim count (joined via A59 `SourceID`).
- Stale rows DO NOT auto-emit A51 entries; the audit prints the suggested A51 row contents so the operator can decide whether to raise them.
- The marker `freshness_audit.json` carries `verdict: pass | warn | n/a`:
  - `pass` — zero stale rows OR stale rows have no dependent claims.
  - `warn` — at least one stale row with at least one dependent A59 claim (any criticality).
  - `n/a` — A50 absent OR A50 has zero rows with parseable EffectiveDate (audit has nothing to say).

The audit never emits `verdict: fail` in v1.2.16. Mandatory enforcement (e.g., blocking promotion when a level-1 claim binds to a stale source) is intentionally deferred — adding it now would break every downstream operator workspace whose A50 rows have no EffectiveDate yet. If mandatory enforcement is wanted later, ship it as a separate hotfix v1.2.16.x and gate it behind a CLI flag, not the default.

## Marker schema

```json
{
  "schema_version": "1.0",
  "captured_at": "2026-04-25T12:00:00Z",
  "verdict": "pass",
  "threshold_days": 180,
  "today_utc": "2026-04-25",
  "summary": {
    "rows_total": 12,
    "rows_with_effective_date": 8,
    "rows_fresh": 7,
    "rows_stale": 1,
    "rows_na": 4,
    "stale_rows_with_dependent_claims": 0
  },
  "stale_rows": [
    {
      "source_id": "S-007",
      "effective_date": "2025-08-10",
      "age_days": 258,
      "dependent_claim_count": 0,
      "suggested_a51": null
    }
  ]
}
```

A51 suggestion is `null` when `dependent_claim_count == 0`; otherwise it carries a **partial draft** with the placeholder string `"<assign-on-create>"` in the `A51Ref` field. The placeholder is intentional — A51 ID assignment is single-writer to the orchestrator (INV-02), and a verbatim copy of the suggestion would fail `governance/schemas/a51.schema.json` validation (the `A51Ref` pattern requires `A51-NNN`). The operator MUST replace `<assign-on-create>` with the next free A51 identifier before promoting the row. The audit never writes A51 directly.

## CLI

```
scripts/freshness_audit.py --workspace <path>
scripts/freshness_audit.py --workspace <path> --threshold-days 90
scripts/freshness_audit.py --workspace <path> --print-only
scripts/freshness_audit.py --workspace <path> --quiet
```

`--threshold-days` overrides the tunable for ad-hoc operator runs (the canonical value still lives in `config/tunables.yaml`).

## Relationship to other audits

- **Independent of `bsa-citation-auditor`**: citation audit verifies that a claim's `SourceID + ExcerptID` resolves to A58; freshness audit verifies that the source dates haven't expired. A claim may have a perfectly-bound but stale source.
- **Independent of `bsa-anchor-auditor`**: anchor audit detects drift in canonical anchors; freshness audit looks at upstream A50 sources only.
- **Complements INV-01**: INV-01 says "every claim has bound evidence". Freshness audit asks "is that evidence still timely?". INV-01 is unconditional; freshness is operator-policy.
