# Troubleshooting

Common failure modes and fixes. Ordered by what most first-time users hit.

## 1. `/plugin install bsa-full` errors out on manifest parse

**Symptom:** Claude Code prints a manifest-parse error referencing `.claude-plugin/plugin.json`.

**Cause:** either the repo wasn't fully cloned (partial fetch) or an out-of-date Claude Code is rejecting a field it doesn't recognize.

**Fix:**
1. Re-add the marketplace entry: `/plugin marketplace add https://github.com/kkitanin/bsa-plugin-family` (idempotent, refreshes).
2. Upgrade Claude Code to a version that supports the plugin system.
3. If still failing, check [plugin_api_spike.md](plugin_api_spike.md) for the expected field set; custom fields (`canonPolicyVersion`) are preserved but not required by core plugin discovery.

## 2. `/bsa-promote` refuses with "evidence-binding violation"

**Symptom:**
```
PreToolUse:Bash refused: /bsa-promote blocked — INV-01 violation
  A59 row C-00X: requires SourceID+ExcerptID OR A51Ref
```

**Cause:** a row in the Stage's `A59` proposal has no bound source and no `A51Ref`.

**Fix:**
- If the claim has a real source → fill `SourceID` + `ExcerptID` (and add the `A58` excerpt if it's missing).
- If it's an acknowledged uncertainty → route to `A51` first (add a row with the appropriate `IssueType` / `BlockingStatus`), then put the `A51Ref` on the `A59` row.
- If the row is spurious → delete it.

The check runs again after the fix — no manual marker is needed.

## 3. `/bsa-promote` refuses with "missing audit marker"

**Symptom:**
```
PreToolUse:Bash refused: stage<N> promotion requires marker stage<N>.<audit>.pass — not found
```

**Cause:** an in-stage auditor didn't run to a passing verdict, so the required marker under `analysis/runtime/ready/` is missing.

**Fix:** re-run the stage with `/bsa-stage N`, or re-run a specific audit with `/bsa-audit <kind>`. The audit-marker mapping (all markers live under `analysis/runtime/ready/`) is:

| Stage | Auditor(s) run in-stage | Required marker(s) before `/bsa-promote` |
|---|---|---|
| 1 | (none — intake emits `stage1.excerpts.merged.json`) | `stage1.excerpts.merged.json` |
| 2 | (context-framer shape-checks itself) | `stage2.context_state.pass.json` |
| 3 | `bsa-citation-auditor` + `bsa-consistency-auditor` | `stage3.citation_audit.pass.json` |
| 4 | (no dedicated audit) | `stage4.ready.json` |
| 5 | `bsa-anchor-auditor` (backbone mode) | `stage5.anchor_audit.pass.json` |
| 6 | `bsa-anchor-auditor` (contract-layer mode) | `stage6.anchor_audit.pass.json` |
| 7 | `bsa-citation-auditor` (re-run) + `bsa-skeptical-reviewer` | `stage7.skeptical_review.pass.json` |
| 8 | `bsa-no-new-claims-auditor` | `stage8.no_new_claims.pass.json` |

## 4. `/bsa-audit citation` fails KPI-001 below target

**Symptom:** the citation audit report under `analysis/proposals/stage3/` reports
```
kpi_001_weighted_coverage: 0.62 (target >= 0.75)
```
and no `stage3.citation_audit.pass.json` is emitted (audits do not write a `.fail.json` marker — a failing audit simply omits the `.pass.json` and blocks promotion).

**Cause:** weighted coverage is too low because too many direct claims are on low-tier sources. KPI-001 counts **direct claims only**; contested inferences (tier-delta ≤ 1 rule) never enter the KPI-001 formula, so they cannot "drag it down" — they surface separately via `A51` with `IssueType=cross_tier_contradiction`, `BlockingStatus=hard`.

**Fix options:**
- Add higher-tier sources for the low-scoring direct claims. The per-tier breakdown in the audit report tells you which tier is dominating.
- Re-classify a claim from `direct` to `inference` if the underlying source is really derivative — note that inference claims do NOT enter KPI-001, so this raises coverage by shrinking the denominator.
- If the contested routes are legitimately unresolvable, acknowledge them via `A51`: they show up in H4 with `BlockingStatus=hard` and a sponsor-resolution next-action.

## 5. Sidecar skill says "plantuml not found"

**Symptom:**
```
[c4-plantuml-from-context] plantuml not found; skipping render.
```

**Cause:** optional rendering tool isn't installed. This is a **graceful degradation**, not an error — the pipeline continues.

**Fix (optional):** install PlantUML (`brew install plantuml` on macOS, or download the JAR from plantuml.com). Re-run the sidecar skill — it picks up the binary automatically.

The same pattern applies to `xmllint` for the BPMN sidecar.

## 6. Marker chain validator reports a gap

**Symptom:**
```
chain-gap: stage3 missing before stage5
```

**Cause:** you tried to promote Stage 5 without completing Stage 3's audit markers, or a marker file was deleted / corrupted.

**Fix:**
- Inspect `analysis/runtime/ready/` and see which markers are present.
- Re-run the missing stage (`/bsa-stage N`) or the missing audit (`/bsa-audit <kind>`).
- The validator is deterministic; re-running it after the fix will pass.

If the marker truly was lost (editor crash, etc.), you can re-emit it by re-running the auditor — the auditor will emit a fresh marker with the current timestamp as long as the audit verdict still holds.

## 7. Pipeline run seems "frozen" at Stage 8

**Symptom:** `/bsa-audit no-new-claims` takes a long time or seems stuck.

**Cause:** the no-new-claims auditor walks every statement in H1-H4 (or Stage 7 outputs pre-handoff) and traces each citation back to a canonical row. On a large pack this can take several minutes.

**Fix:**
- Run with `--verbose` to see progress.
- If it's genuinely stuck (no output for > 5 minutes), cancel and inspect the auditor's log. Common cause: a `[C-XXX]` citation in H1 doesn't resolve to an `A59` row, and the auditor is retrying through fuzzy matchers.

## 8. "Two T4 sources contradict" — what do I do?

**Symptom:** Two same-tier attestations disagree about a gating/authority/ownership rule. The claim binder emits `ClaimStatus=contested` + `ClaimStrength=0.0` for both, and routes to `A51` with `IssueType=cross_tier_contradiction`, `BlockingStatus=hard` (per [reliability_tier_spec.md](../skills/bsa-evidence-intake/references/reliability_tier_spec.md) §Conflict Resolution).

**This is not a bug — it's the tier-delta ≤ 1 rule firing correctly.** See [reliability_tier_spec.md](../skills/bsa-evidence-intake/references/reliability_tier_spec.md) §"Conflict Resolution".

**Fix options:**
- Escalate to a higher-tier source that settles the dispute (T1 empirical telemetry, T2 signed policy text).
- Have a sponsor make a canonical-interpretation decision. Record the decision as an `A51` closure and update the policy text.
- Surface the contradiction in H4 Decisions Required as-is — that's exactly what `project_0003` demonstrates.

## 9. I deleted `analysis/canonical/` by accident

**Symptom:** canonical content is gone.

**Fix:** if you committed it to git — restore from history. If not — the source inputs under `analysis/proposals/stage1/inputs/` may still be intact; you can re-run `/bsa-stage 1` and rebuild from there, but promoted downstream work is lost.

**Prevention:** the single-writer hook prevents non-orchestrator writes to canonical paths, so accidental overwrites from Claude Code sessions are blocked. Manual `rm` is still your own responsibility. Keep frequent git commits.

## 10. CI fails with "canon_policy_version_hash mismatch"

**Symptom:** the release workflow or a marker-chain validator CI step reports a mismatch between `.claude-plugin/plugin.json` `canonPolicyVersion.hash_full` and the output of `scripts/compute_canon_hash.py`.

**Cause:** a canon-policy-defining file was edited (skill frontmatter, reference with invariants, KPI definitions, immutable invariants, reliability tier spec, validation scenario manifest), but the plugin manifest's `hash_full` wasn't recomputed.

**Fix:** run `python3 scripts/compute_canon_hash.py` and copy the output into `.claude-plugin/plugin.json` `canonPolicyVersion.hash_full` and `hash_prefix` (first 8 chars). Commit the updated manifest. If the change touched an immutable invariant, also bump the semver major per [contract-versioning.md](../skills/bsa-orchestrator/references/contract-versioning.md).

## Still stuck?

- Check the per-sprint retros under `docs/retros/` for known issues and resolutions.
- Run `python3 scripts/validate_marker_chain.py analysis/runtime/ready/` and `python3 scripts/fixture_runner.py --fixture <your-fixture>` for structured diagnostics.
- File a GitHub issue with the marker log + the audit report + your Claude Code version.
