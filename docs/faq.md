# FAQ

## Is this ready for production use?

Phase 0-2 ships the MVP `bsa-full@1.0.0-rc2` on HEAD, with the final `@1.0.0` tag landing at Sprint 4.5 close (US-S45-03) — core pipeline end-to-end, three golden fixtures, CI regression, solo-maintainer-reviewed. It is **not** certified for regulated domains (fintech, healthcare, etc.) — those need the Phase 5 pack layer and Phase 8 certification framework.

Phase 2.5 external shakedown (2-4 weeks of real-project usage by non-self-owned analysts) is the gate before Phase 3 feature work begins. If you're trying the plugin on a small internal engagement, you're part of that shakedown — see CONTRIBUTING.md for how to file feedback.

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

`A59.ClaimStrength = max_supporting_tier_weight × (1 - decay_factor)` (decay defaults to 0 in v1.0).

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

Yes. Each sidecar skill has a "standalone mode" documented in its `integration-contract.md`. The sidecar still expects an `anchor_manifest.json` input, but you can construct that manually instead of relying on the orchestrator to emit it from A61.

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

## What isn't in v1.0.0?

Deferred to Phase 3+ (see Sprint plan):

- Dev-handoff extension (FR/NFR collector, story writer, test-scenario builder, traceability matrix, backlog bridge).
- Machine-readable Stage 6 (OpenAPI / AsyncAPI / proto generation).
- Plugin decomposition (bsa-core / bsa-discovery / bsa-sidecars split).
- Domain/stack packs (fintech, healthcare, regulated).
- Reality-probe layer (freshness, triangulation, runtime invariants).
- Self-improvement telemetry + evolution-miner.
- Marketplace + certification framework.
- Multi-session / concurrency handling beyond the file-lock.
- Full GDPR / retention / right-to-erasure controls.

## Where do I file an issue?

This is a solo-maintainer, local-only tool. There is no public issue tracker. For findings surfaced during the Phase 2.5 shakedown, log them under `docs/phase_2_5_shakedown.md` §Aggregated findings. For anything else, note them in your own project log and promote to a v1.0.x hotfix or Phase 3+ backlog item when scope is clearer. A useful issue note includes:
- Plugin version (`/plugin list`).
- Canon hash (from any recent `*.pass.json` marker).
- Claude Code version.
- The exact slash command you ran + its output.
- If an audit failed: the audit report + the affected A59 / A51 rows.
