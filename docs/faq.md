# FAQ

## Is this ready for production use?

Current release: **`bsa-full@1.1.6` manifest** with `v1.1.8` git tag on top (v1.1.7 anonymization + v1.1.8 docs polish are operator-tooling-only patches that don't change the canon state). Phase 0-2 (MVP) closed at v1.0.0 (Sprint 4.5); Phase 3 (dev-handoff) closed at v1.1.0 (Sprint 9). The v1.1.x patch line through v1.1.8 added: cross-artifact validator at the F5 hook layer (v1.1.3), platform export polish (v1.1.4 — Jira customfields / Linear projects / GitHub Projects v2), three new adversarial fixtures (v1.1.5), live-API integration (v1.1.6 — Jira REST + Linear GraphQL + GitHub REST clients), pilot anonymization (v1.1.7), and docs polish (v1.1.8).

It is **not** certified for regulated domains (fintech, healthcare, etc.) — those need a future Phase-5 pack layer and Phase-8 certification framework.

Phase 2.5 external shakedown framing (2-4 weeks of real-project usage) was the gate before Phase 3 feature work began (closed in v1.1.0). The v1.0.x → v1.1.x migration tool (`scripts/migrate_v1.0_to_v1.1.py`, v1.1.2) exists precisely to bring shakedown-era workspaces forward to the v1.1.x schema set. See [docs/pilot_validation.md](pilot_validation.md) for the active pilot status (Pilot-1 baseline + framework-level pilot validation invariants).

If you're trying the plugin on a small internal engagement, see CONTRIBUTING.md for how to file feedback.

## Why "claims" instead of "facts"?

A *fact* is an established truth. A *claim* is an assertion that might or might not be true and needs evidence to support it. The whole point of the pipeline is evidence discipline — treating stakeholder statements as claims (potentially false) rather than facts (presumed true) is what catches the contradictions.

The plugin migrated from "no-new-facts" to "no-new-claims" terminology in Sprint 2. Migration notes are in `migrations/v0.9_to_v1.0/`.

## What is the ReliabilityTier system?

Five tiers on every A50 source:

| Tier | Weight | Examples |
|---|---|---|
| T1 | 1.00 | live DB/log queries, runtime observation |
| T2 | 0.85 | production code, signed contract, policy text |
| T3 | 0.65 | ADR, owned wiki with owner + date |
| T4 | 0.45 | recorded interview, signed questionnaire |
| T5 | 0.20 | meeting summary, slack thread, hallway recollection |

`A59.ClaimStrength = max_supporting_tier_weight × (1 - decay_factor)` (decay defaults to 0 in the v1.x line).

KPI-001 weighted coverage is the sum of ClaimStrength across direct claims divided by the direct-claim count. Target ≥ 0.75.

Full spec: [../skills/bsa-evidence-intake/references/reliability_tier_spec.md](../skills/bsa-evidence-intake/references/reliability_tier_spec.md).

## What happens when two sources contradict?

Three cases per tier-delta:

- **Tier-delta ≥ 2** — higher tier wins; lower tier automatically marked `SupersededBy`.
- **Tier-delta ≤ 1** — contested. Both claims get `ClaimStrength=0.0` + routed to A51 with `IssueType=cross_tier_contradiction` + `BlockingStatus=hard` per the tier spec's §Conflict Resolution.
- **Anecdotal (`anecdotal=true` in A50.Notes)** — never overrides non-anecdotal regardless of tier.

See `project_0003` for a worked example of tier-delta = 0 contested routing.

## What is `analyst_judgment`?

The third ClaimType in the closed INV-07 enum: `{direct, inference, analyst_judgment}`.

- **direct** — a claim supported by verbatim evidence excerpt (A58 row with matching text).
- **inference** — a claim derived from one or more evidence excerpts by non-trivial reasoning (still bound to SourceID+ExcerptID).
- **analyst_judgment** — a recommendation or interpretation authored by the analyst that cannot be directly attributed to any source. Required to carry `JustificationRationale` referencing ≥ 1 upstream ClaimID (per INV-07). When rendered in H1 Recommended Next Steps or H4 Decisions Required, the citation uses the `[AJ:Cxxx]` form to signal its judgment nature.

Analyst_judgment is the only ClaimType permitted to surface in H1/H4 recommendation/decision sections without triggering the no-new-claims auditor (`bsa-no-new-claims-auditor`) — as long as the JustificationRationale + upstream-claim requirement holds.

## Can I extend the ClaimType enum?

Not without a **major** CanonPolicyVersion bump. INV-07 declares the enum closed. The migration pack under `migrations/` is the canonical way to land a new ClaimType — it requires test coverage for the new ClaimStrength semantics, a handoff-packager update, and an immutable_invariants.md amendment.

This is deliberate: drift in the claim-type ontology breaks the evidence-binding invariants downstream.

## Why is the orchestrator the single writer to canonical?

INV-02. The canonical layer is authoritative for the whole pipeline, so concurrent writes from multiple skills or sessions would create race conditions and lost-update bugs. The PreToolUse:Write hook enforces this: any non-orchestrator write attempt under `analysis/canonical/` is rejected.

Workers write to `analysis/proposals/`, which has no such lock. `/bsa-promote` is the only path from proposals to canonical.

## Can I use a sidecar (PlantUML / BPMN) standalone without the main pipeline?

Yes. Each sidecar skill has a "standalone mode" documented in its `integration-contract.md`. **In standalone mode the anchor manifest is NOT required** — the emitted `.puml` / `.bpmn` is informational only and carries no BSA governance weight (per `skills/c4-plantuml-from-context/references/integration-contract.md` and `skills/camunda-bpmn-from-context/references/integration-contract.md`). Only orchestrated mode requires `anchor_manifest.json`.

The sidecar uses a heuristic to decide which mode is intended: if the output path falls under any directory containing `analysis/`, an adjacent `anchor_manifest.json` is required (orchestrated intent); otherwise standalone mode is assumed and no manifest is emitted. See `docs/sidecar_inventory.md` for the operator-facing summary + usage examples for both modes.

See [../skills/c4-plantuml-from-context/references/integration-contract.md](../skills/c4-plantuml-from-context/references/integration-contract.md) and [../skills/camunda-bpmn-from-context/references/integration-contract.md](../skills/camunda-bpmn-from-context/references/integration-contract.md).

## What is the adversarial prompt-injection fixture for?

`fixtures/golden/adversarial_prompt_injection_001/` (Sprint 3 US-S3-06) is a synthetic fixture with three injection vectors baked in:

- "Ignore previous instructions" style.
- Delimiter-escape attempts (fake SKILL.md frontmatter).
- Tool-use injection ("please call shell_command...").

The fixture documents how the pipeline **should** treat these: classify them as T5 evidence with `anecdotal=true` and route to A51 with `IssueType=boundary_risk`, rather than obeying the injection. It is the regression baseline for the Phase 3 security workstream; it does not currently exercise runtime defenses (that's Phase 3+).

## How do I write a new golden fixture?

1. Author `fixtures/golden/project_NNNN/` with:
   - `README.md` explaining the scenario and what's being exercised.
   - `inputs/source_*.md` (sanitized, real or synthetic).
   - `expected_outputs/canonical/core_controls/{A48,A50,A51,A58,A59,A60}*`.
   - `expected_outputs/canonical/stage2/{5 files}`.
   - `expected_outputs/handoff/{H1-H4 + manifest + binding map + no-new-claims report}`.
   - `expected_markers/{7 main-cycle markers}`.
   - `fixture_metadata.json` + `audit_expectations.json`.
2. Run `python3 scripts/fixture_runner.py --fixture project_NNNN --mode=validate`. Iterate until 0 findings.
3. Run `python3 scripts/validate_marker_chain.py fixtures/golden/project_NNNN/expected_markers/`. Iterate until OK.
4. Add to `scripts/fixture_runner.py` all-fixtures list (or `--all` already discovers via directory scan).
5. Submit to codex review via the delegator workflow.

## How do I update the canon policy version hash after a documented change?

```
python3 scripts/compute_canon_hash.py    # outputs the new hash
# paste into .claude-plugin/plugin.json canonPolicyVersion.hash_full
# bump semver per the rule (major/minor/patch)
# update CHANGELOG.md with the reason for the change
# rerun pytest + fixture_runner + privacy_scan
# commit with message "bump canon policy: X.Y.Z → X.Y.Z+1 (reason)"
```

The plugin-manifest test (`tests/test_plugin_manifest.py::test_manifest_canon_hash_matches_current_script_output`) enforces equality between `plugin.json.canonPolicyVersion.hash_full` and the live `compute_canon_hash.py` output; a drift fails `pytest` on any local run and in any pre-tag check.

## Where do markers live? How do I inspect them?

Per-workspace: `analysis/runtime/ready/*.json` (main cycle) and `analysis/discovery/runtime/ready/*.json` (discovery, when mode=discovery_then_bsa). Stage-ready markers end in `.ready.json`, audit-pass markers in `.<audit>.pass.json`, the Stage 1 intake marker in `.excerpts.merged.json`, and the final pipeline marker is `pipeline.complete.json`. Canonical schema: [runtime-marker-schema.md](../skills/bsa-orchestrator/references/runtime-marker-schema.md). They are plain JSON; inspect with `cat`, `jq`, or your editor.

The chain validator `scripts/validate_marker_chain.py` reports gaps, monotonicity violations, and policy-hash inconsistencies.

## I broke something — how do I revert a promotion?

Git. Every promotion should land on a commit. `git revert <promotion-commit>` restores the previous canonical state. Do not manually edit `analysis/canonical/` — the single-writer hook blocks it.

If you didn't commit per-promotion, that's a process lesson for next time. The workspace is YOUR git repo; the plugin doesn't manage history for you.

## What's in v1.1.x and what's still deferred?

**Closed in v1.1.x (current line):**
- Phase-3 dev-handoff (NFR collector, story writer, test-scenario builder, traceability matrix, backlog bridge with three initial export shapes — Jira REST v3 JSON, Linear CSV, generic CSV) — v1.1.0.
- A51 enum extensions (`inventory_gap`, `cross_tier_contradiction`, `Severity=critical`) — v1.1.1.
- Mechanical migration tool (`scripts/migrate_v1.0_to_v1.1.py`) — v1.1.2.
- Cross-artifact validator at the F5 hook layer (A71 NFR-coverage + A72 FK/claim-source-consistency now executable, not just documentary) — v1.1.3.
- Platform export polish: Jira `customfield_mapping`, Linear `Project`+`Cycle` columns, brand-new GitHub Projects v2 export schema — v1.1.4 (the GitHub Projects v2 export shape is a v1.1.4 addition; v1.1.0 only shipped Jira/Linear/generic).
- Adversarial regression fixtures (multi-way contradiction, tier-delta auto-resolution, block-on-contradiction spec) — v1.1.5.
- Live-API integration (POST directly to Jira / Linear / GitHub via `scripts/backlog_live_apply.py`) — v1.1.6.
- Pilot anonymization across active surface — v1.1.7.
- Documentation polish — v1.1.8.

**Still deferred to Phase 5+ / future:**
- Machine-readable Stage 6 (OpenAPI / AsyncAPI / proto generation).
- Plugin decomposition (bsa-core / bsa-discovery / bsa-sidecars split).
- Domain/stack packs (fintech, healthcare, regulated).
- Reality-probe layer (freshness, triangulation, runtime invariants).
- Self-improvement telemetry + evolution-miner (Phase 7). v1.1.14 ships the **foundation** — `config/tunables.yaml` inventory + `scripts/phase_7_lint.py` IMMUTABLE_CONFLICT detector + `docs/phase_7_design.md` design — but the actual telemetry collection backend + miner is v1.2.x scope.
- Marketplace + certification framework.
- Multi-session / concurrency handling beyond the file-lock + per-platform live-API lock.
- Full GDPR / retention / right-to-erasure controls.
- Block-on-hard-A51 strict promote mode (`--strict-on-hard-a51`) — spec'd in `fixtures/golden/adversarial_block_on_contradiction_001/` (v1.1.5), implementation pending.
- Operator-side import drivers (`scripts/{jira,linear,github}_import_from_export.sh`) — for operators who prefer shell over Python.

## Where do I file an issue?

This is a solo-maintainer, local-only tool. There is no public issue tracker. For findings surfaced during the Phase 2.5 shakedown, log them under `docs/phase_2_5_shakedown.md` §Aggregated findings. For anything else, note them in your own project log and promote to a v1.0.x hotfix or Phase 3+ backlog item when scope is clearer. A useful issue note includes:
- Plugin version (`/plugin list`).
- Canon hash (from any recent `*.pass.json` marker).
- Claude Code version.
- The exact slash command you ran + its output.
- If an audit failed: the audit report + the affected A59 / A51 rows.
