# Phase 7 Self-Improvement Loop — Design

**Status:** Foundation only (v1.1.14 / Section D). The actual telemetry collection + auto-patcher backend is **v1.2.x scope** and not implemented in v1.1.x. This doc + `config/tunables.yaml` + `scripts/phase_7_lint.py` set up the contract so the implementation can land safely.

**Anchor:** `governance/immutable_invariants.md` §"Scope of self-improvement (Phase 7 L1/L2)" defines what may / may not be tuned. This doc is the operational expansion.

## Goal

Allow the BSA plugin family to safely tune **non-invariant** thresholds, KPI targets, and scoring weights based on observed pipeline telemetry — without risking drift in the 10 immutable invariants (`INV-01..INV-10`) or the canon-policy hash.

## Why a foundation-first release

Phase 7 has three layers:

| Layer | What it does | When it ships |
|---|---|---|
| **L0 (foundation)** | Formal tunable inventory + IMMUTABLE_CONFLICT lint + safety contract doc | **v1.1.14** |
| **L1a (telemetry collector)** | Per-run KPI snapshot + storage shape | **v1.2.4** (P1+P2: schema + collector skeleton; KPI-001 + KPI-006 covered) |
| **L1b (miner)** | Aggregate snapshots across N runs + detect tunable-knob drift + propose tuning patches | v1.2.5+ candidate (deferred — needs real pilot data to calibrate) |
| **L2 (auto-patcher)** | Auto-emit proposals (PRs) for tunables that need analyst sign-off (always reviewed before merge — no auto-merge in L2; the "auto" is the proposal generation, not the apply) | v1.3+ |

Shipping L0 first lets the tunable inventory get pinned (so future drift is caught) without committing to a full collector backend before there's real pilot telemetry to learn from.

## Tunable inventory (L0)

`config/tunables.yaml` is the **single source of truth** for which knobs Phase 7 may touch. Every entry carries:

| Field | Purpose |
|---|---|
| `id` | Stable identifier (e.g., `tier_weight_T2`, `kpi_001_target`, `bpmn_max_shape_shift`) |
| `current_value` | The value as it appears in the source-of-truth file today |
| `allowed_range` | `[min, max]` numeric bounds the auto-patcher may stay within. **v1.1.14 only supports numeric ranges**; enum-style tunables are deferred until a use case appears. |
| `owner_skill` | The skill that owns the canonical definition |
| `source_file` | Repo-relative path containing the value |
| `source_line` | 1-indexed line number where the value lives |
| `linked_invariants` | List of `INV-XX` IDs this tunable interacts with (read-only — Phase 7 must not change those) |
| `change_class` | `L1_auto_tunable` (auto-patch ok within range) or `L2_proposal_only` (always requires analyst sign-off) |
| `rationale` | Why the tunable exists + what observation should drive a tuning change |

**Lint contract** (`scripts/phase_7_lint.py` — 8 checks):

1. **C1**: every entry's `source_file:source_line` must contain the declared `current_value` (verbatim substring match). Catches drift if a maintainer edits the value but forgets to update tunables.yaml.
2. **C2**: every entry's `linked_invariants` must reference real `INV-XX` IDs from `governance/immutable_invariants.md`.
3. **C3**: every `owner_skill` must reference a real skill directory (or `governance` / `sidecar:<name>` for non-skill owners).
4. **C4**: no two entries may share the same `id`.
5. **C5 (IMMUTABLE_CONFLICT)**: every `L1_auto_tunable` with non-empty `linked_invariants` is rejected — auto-patch is forbidden when the tunable touches an invariant.
6. **C6**: `L1_auto_tunable` entries' `source_file` must NOT match any POLICY_GLOBS pattern. L2_proposal_only entries MAY (analyst sign-off includes the manifest bump).
7. **C7**: `change_class` MUST be one of `{L1_auto_tunable, L2_proposal_only}`.
8. **C8**: `allowed_range = [min, max]` with `min < max`, both numeric, AND `current_value` (parsed as float when possible) MUST fall within the range.

The lint runs in CI (added to `.github/workflows/ci.yml::phase-7-lint`) so any drift is caught at PR time, not at the moment Phase 7 actually fires.

## IMMUTABLE_CONFLICT detection

Per `governance/immutable_invariants.md` line 169:

> Attempted L1 auto-patch that touches a derived rule whose upstream is an invariant MUST be flagged `IMMUTABLE_CONFLICT` and rejected automatically.

Implementation in v1.1.14 (foundation):

* The lint script catches the static case: any tunable whose `linked_invariants` is non-empty AND whose `change_class=L1_auto_tunable` is flagged. L1 auto-patching is forbidden when the tunable touches an invariant.
* The dynamic case (Phase 7 actually proposes a patch that violates the contract) is L1's responsibility — it MUST consult `tunables.yaml` before emitting a patch.

## Safety contract

1. **No invariant edits.** L1/L2 may not modify any value listed in `governance/immutable_invariants.md`. The lint catches static drift; runtime governance gates catch dynamic drift.
2. **Range-bounded.** Every L1 patch MUST stay within `allowed_range`. Patches outside range are L2-proposal-only and require analyst sign-off.
3. **Provenance.** Every L1 patch MUST carry the telemetry rows it observed + the rule it triggered. Analyst-readable.
4. **Reversible.** Every L1 patch MUST be reversible via a single git revert. No "auto-tuning" that touches multiple files in one patch.
5. **L1 is canon-hash neutral by construction.** The lint hard-fails any `L1_auto_tunable` whose `source_file` matches POLICY_GLOBS — this guarantees auto-merge never silently bumps canon state. **L2_proposal_only entries MAY live in POLICY_GLOBS**: the analyst-sign-off step naturally includes a manifest version bump + canon-hash refresh, so the two-semver discipline (manifest version vs git tag) stays intact. KPI targets and tier weights live in canonical references, so they're necessarily L2.
6. **Pilot-data-driven only.** L1 may not propose patches based on synthetic data, fixture runs, or hypothetical scenarios. The miner ingests only real pilot telemetry. (L2 may propose patches based on analyst-supplied scenarios with explicit `--scenario` flag.)

## What's NOT in scope for v1.1.14

- Telemetry collection backend (where do per-run KPI values get written? what schema? what retention?)
- The miner / pattern detector (what algorithm? statistical significance gate? confidence intervals?)
- Auto-patch emission (PR generation, commit message format)
- Multi-pilot aggregation (how do we combine telemetry across N pilots?)
- Roll-back mechanism beyond `git revert`

These are L1/L2 concerns — v1.2.x candidates pending real pilot data.

## L1a status (v1.2.4)

**Telemetry storage shape (P1)** — schema at `governance/schemas/telemetry_run.schema.json`. Per-run JSON file at `analysis/telemetry/run_<run_id>.json`. Required top-level fields: `schema_version`, `captured_at`, `run_id`, `plugin_version`, `canon_policy_version`, `kpi_observations`, `summary`. Per-KPI block carries `value`, `target`, `comparison`, `status` ∈ {at_target, below_target, n/a}, plus optional `numerator` / `denominator` for fail-mode debugging. NOT F5-validated; NOT in POLICY_GLOBS. Deletion is safe (forces fresh capture next run).

**Telemetry collector (P2)** — `scripts/phase_7_telemetry_collector.py`. Stdlib-only. v1.2.4 captures KPI-001 weighted (per `reliability_tier_spec.md` line 142) + KPI-006 story coverage (per `bsa-traceability-matrix/SKILL.md` line 71). Both compute null + `status=n/a` when their upstream artifacts (A59 / A70 / A72) are absent. Optional `validator_observations` + `threshold_trigger_counts` are schema fields but unpopulated in v1.2.4 — operator-side L1b miner work will populate them once a structured marker-emission convention exists.

**v1.2.4 boundary**: ships data capture only. No miner; no patch proposer; no aggregation across runs. Operators may capture snapshots today + retain them for the L1b miner without backend dependencies. The intent is to start collecting real-pilot data NOW so L1b lands with an actual training set instead of synthetic baselines.

## Open questions for v1.2.x design

1. **Telemetry storage shape.** Per-run JSON in `analysis/telemetry/`? Or a separate ledger file? Implications for F5 (canonical or not) + privacy_scan (PII risk).
2. **Statistical significance gate.** How many observations does L1 need before proposing a tuning patch? Bayesian update vs frequentist threshold?
3. **Multi-pilot aggregation.** When does pilot-A's telemetry dominate pilot-B's signal? Per-pilot tunable overrides?
4. **Auto-patch emission cadence.** Per-PR? Per-release? Per-N-runs?
5. **Operator opt-out.** Per-tunable disable flag? Per-pilot Phase-7 disable flag?

## Cross-references

- `governance/immutable_invariants.md` §"Scope of self-improvement" — what may / may not be tuned.
- `config/tunables.yaml` — the formal inventory + ranges + invariant links.
- `scripts/phase_7_lint.py` — the IMMUTABLE_CONFLICT + drift detector.
- `tests/test_phase_7_lint.py` — pins the lint contract.
- `CONTRIBUTING.md` §"Immutable invariants" — the policy summary for new contributors.
- `docs/faq.md` "What isn't in v1.1.x" — Phase 7 listed as deferred.
