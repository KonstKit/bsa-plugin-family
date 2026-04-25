# Triangulation Audit Contract

Status: **opt-in operator runner** as of v1.2.17. Not invoked automatically by the orchestrator and not part of any mandatory marker family. The skill is `scripts/triangulation_audit.py` (stdlib-only, mirrors v1.2.16 `freshness_audit.py` pattern).

## Scope

Triangulation audit verifies that every **important** A59 claim is supported by **at least N independent source types** — not just N sources that happen to be the same kind of artifact. A claim with three sources all of `SourceType=document` is supported by one observation channel; a claim with one `document` + one `code` + one `interview_transcript` is corroborated across three channels and is materially stronger.

The audit is purely **structural** — it does not re-read source content, does not re-validate evidence binding (that's `bsa-citation-auditor` per INV-01), and does not interact with stages 5-8.

Audit input:
- `analysis/canonical/core_controls/A59_claim_register.csv` (claims to triangulate).
- `analysis/canonical/core_controls/A50_source_register.csv` (joined for `SourceType` + `Priority`).
- `analysis/canonical/core_controls/A51_issue_route_register.csv` (joined for `Severity` via `RelatedClaimID`).

Audit output:
- Markdown report `analysis/canonical/stage7/triangulation_audit.md`.
- JSON marker `analysis/canonical/stage7/triangulation_audit.json` carrying the verdict.
- Per-claim findings with the resolved triggering reason and the source-type breakdown.

## Triggering set

A claim enters the triangulation set if **ANY** of three branches matches (three-branch OR):

1. **Criticality branch**: A59 row's `Criticality == "level-1"`. Direct from A59 — no join needed.
2. **Severity branch**: any A51 row whose `RelatedClaimID` lists this `ClaimID` AND whose `Severity ∈ {high, critical}` (default; overridable per-run via the `--severity-threshold` CLI flag — see "Branch threshold overrides (CLI-only)" below). Both `RelatedClaimID` and the `;`/`/`-joined multi-value form are honored per v1.2.14 multi-FK contract.
3. **Priority branch**: any A50 row whose `SourceID` is referenced by this claim's `SourceID` cell AND whose `Priority == "high"` (default; overridable per-run via the `--priority-threshold` CLI flag).

`analyst_judgment` claims are **always skipped** regardless of branch matches. They have no source binding by design (INV-07 / `x-bsa-claim-type-rules`) so triangulation arithmetic is meaningless. The skip is reflected in the snapshot summary as `claims_skipped_analyst_judgment` (count only — individual skipped claims are NOT enumerated; surfacing them as actionable findings would be noise since they're correctly excluded by the contract).

A claim that does not match any branch is **not in the triangulation set** — the audit does not assess it. The summary tracks `claims_in_triangulation_set` separately from `claims_total`.

## Independence rule

Two sources are **independent** for triangulation purposes if their A50 `SourceType` values differ. `SourceType` is a free-form lowercase identifier (`document`, `code`, `interview_transcript`, `process_note`, `policy_document`, `screenshot`, `dashboard`, `ticket`, `config_file`, ...) — open vocabulary. Two `interview_transcript` sources count as ONE source type even if their `SourceID` differs.

Why SourceType, not SourceID:
- Three documents from the same author corroborate authorship, not the underlying claim.
- A document, a code reference, and a stakeholder interview corroborate from three observation channels.
- The audit is about **epistemic independence**, not raw count.

## Tunable

| Tunable | Default | Range | Class | Purpose |
|---|---|---|---|---|
| `triangulation_min_distinct_sourcetypes` | `2` | `[2, 5]` | `L2_proposal_only` | How many distinct SourceType values a triggered claim must have. Tightening (3+) raises the bar; loosening below 2 defeats the audit. |

`L2_proposal_only` because the threshold affects which claims must clear the bar — loosening could let weakly-corroborated critical claims pass; tightening would mass-flag historic data. `linked_invariants: [INV-01]` because tighter triangulation strengthens evidence-binding semantics.

The literal `current_value: "2"` MUST appear verbatim in this contract for `scripts/phase_7_lint.py` C1 (substring match) to pass. Concrete default: `current_value: "2"` (this paragraph).

## Branch threshold overrides (CLI-only)

The Severity and Priority branch thresholds are **operator-level CLI overrides**, not Phase 7 tunables — `phase_7_lint.py` C8 requires numeric `allowed_range`, and these are enums (low/medium/high/critical for Severity; low/medium/high for Priority). They live as defaults in `scripts/triangulation_audit.py`:

| CLI flag | Default | Choices | Purpose |
|---|---|---|---|
| `--severity-threshold` | `high` | `high`, `critical` | Lowest A51 Severity that triggers the Severity branch. `critical` would skip `high`-only claims. |
| `--priority-threshold` | `high` | `medium`, `high` | Lowest A50 Priority that triggers the Priority branch. `medium` would route ~70% of typical workspaces (broader). |

If/when these defaults need persistent change across operator runs, that's a code edit + new release (since the defaults are policy-bearing). Future option: extend Phase 7 lint to support enum tunables, then promote these into `config/tunables.yaml`.

## Verdict policy

**Non-blocking by default in v1.2.17.** Verdicts:

- `pass` — every claim in the triangulation set has `>= triangulation_min_distinct_sourcetypes` distinct SourceTypes from its bound A50 sources.
- `warn` — at least one claim in the triangulation set falls below the threshold.
- `n/a` — A59 absent OR triangulation set is empty (no claim matches any branch).

The audit never emits `verdict: fail` in v1.2.17. Mandatory enforcement (e.g., blocking promotion when a level-1 claim has only 1 distinct SourceType) is intentionally deferred — adding it now would break every downstream operator workspace whose level-1 claims happen to bind a single source type. If mandatory enforcement is wanted later, ship it as a separate hotfix v1.2.17.x and gate it behind a CLI flag.

## Edge case handling

- **Empty `SourceID`** on a triggered claim: 0 distinct SourceTypes. Reported as `under_triangulation` with `distinct_sourcetypes_count: 0`. Suggested A51 carries the diagnostic.
- **Dangling SourceID** (claim's `SourceID` references an A50 entry that does not exist): the dangling token is silently skipped for SourceType counting. The audit relies on F5 hook's `x-bsa-foreign-key-refs` (v1.2.13) to have already rejected such writes — if a dangling token still appears in canonical state, that's an upstream invariant violation surfaced by other auditors (citation / consistency); this audit does NOT log or double-count, it just doesn't get any SourceType signal from the dangling reference.
- **Dangling RelatedClaimID** in A51: same — silently skipped for the Severity branch.
- **Multi-value cells**: `;`-joined and `/`-joined SourceID / RelatedClaimID tokens are split using the same convention as v1.2.14 multi-FK contract.
- **Whitespace tokens**: stripped per token after split (a stray `S-001 ; S-002 ` resolves to `["S-001", "S-002"]`).
- **A50 missing OR A51 missing**: the affected branch becomes inactive (no Priority / no Severity data to consult). The Criticality branch still fires from A59 alone. If both A50 and A51 are missing AND no level-1 claims exist, the triangulation set is empty → verdict `n/a`.

## Marker schema

```json
{
  "schema_version": "1.0",
  "captured_at": "2026-04-25T12:00:00Z",
  "verdict": "warn",
  "thresholds": {
    "min_distinct_sourcetypes": 2,
    "severity_threshold": "high",
    "priority_threshold": "high"
  },
  "summary": {
    "claims_total": 42,
    "claims_in_triangulation_set": 9,
    "claims_passing": 7,
    "claims_under_triangulation": 2,
    "claims_skipped_analyst_judgment": 3
  },
  "under_triangulation": [
    {
      "claim_id": "C-007",
      "criticality": "level-1",
      "trigger_reasons": ["criticality_level_1"],
      "source_ids": ["S-003"],
      "distinct_sourcetypes": ["document"],
      "distinct_sourcetypes_count": 1,
      "min_required": 2,
      "suggested_a51": {
        "A51Ref": "<assign-on-create>",
        "IssueType": "uncertainty",
        "Severity": "medium",
        "BlockingStatus": "soft",
        "RaisedByStage": "stage7",
        "RelatedClaimID": "C-007",
        "RelatedSourceID": "S-003",
        "NextAction": "Claim C-007 triggered triangulation (criticality_level_1) but binds only 1 distinct SourceType (document). Consider corroborating from a different SourceType (e.g., code, interview_transcript, screenshot).",
        "ResolutionStatus": "open"
      }
    }
  ]
}
```

`trigger_reasons` is a list because all three branches may fire on the same claim simultaneously (e.g., a level-1 claim WITH a high-Severity A51 link AND a high-Priority source). The list captures every reason, not just the first match.

`suggested_a51` carries the placeholder `"<assign-on-create>"` for `A51Ref` — operator MUST replace before promoting (intentional pattern-mismatch by design; mirrors v1.2.16 freshness audit suggestion).

## CLI

```
scripts/triangulation_audit.py --workspace <path>
scripts/triangulation_audit.py --workspace <path> --min-sourcetypes 3
scripts/triangulation_audit.py --workspace <path> --severity-threshold critical
scripts/triangulation_audit.py --workspace <path> --priority-threshold medium
scripts/triangulation_audit.py --workspace <path> --print-only
scripts/triangulation_audit.py --workspace <path> --quiet
```

`--min-sourcetypes` overrides the `triangulation_min_distinct_sourcetypes` tunable in `config/tunables.yaml` for ad-hoc operator runs (the canonical value still lives there). `--severity-threshold` and `--priority-threshold` override the script's built-in defaults — those branch thresholds are NOT in `config/tunables.yaml` (Phase 7 lint requires numeric ranges; both are enums). Persistent change to either branch threshold requires a code edit + new release.

## Relationship to other audits

- **Independent of `bsa-citation-auditor`**: citation audit verifies that every claim has SourceID+ExcerptID resolving to A58 (INV-01 evidence-binding). Triangulation asks "are those sources independent?" A claim may pass citation but fail triangulation.
- **Independent of `freshness_audit.py`** (v1.2.16): freshness asks "is the evidence timely?" Triangulation asks "is the evidence corroborated across channels?" A fresh, single-source claim still fails triangulation.
- **Complements INV-01**: INV-01 says "every claim has bound evidence". Triangulation asks "is that evidence epistemically independent?". INV-01 is unconditional; triangulation is operator-policy.

## Non-goals (explicit deferrals)

- **Cross-claim consistency**: triangulation does not check that the bound sources actually agree about the claim's content. That is `bsa-consistency-auditor` (broken claim-binding count) + `bsa-citation-auditor` (overclaim detection).
- **Tier-weighted independence**: a T1 source from one channel may be epistemically stronger than three T5 sources from three channels; triangulation deliberately uses raw `SourceType` count, not a tier-weighted sum. Adding a `claim_strength_weighted_triangulation` variant is a future option (would require contract extension).
- **Source-content overlap**: two sources of different `SourceType` may still be derivative (e.g., a code comment that quotes a document verbatim). Detecting that is an LLM-judgment call, not a structural audit; out of scope.
