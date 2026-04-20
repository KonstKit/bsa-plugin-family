# Semantic Audit: `fact` → `claim` Rename (US-S2-02 part 3/3)

Authoritative checklist for verifying that downstream skills' descriptions, scopes, invariants, and references use the **claim-as-potentially-false-assertion** semantics consistently after the Sprint 2 US-S2-02 rename.

## Why this audit matters

The Sprint 2 rename from `bsa-no-new-facts-auditor` to `bsa-no-new-claims-auditor` was **semantic, not cosmetic**. Pre-Sprint-2 language occasionally used "fact" as a synonym for "claim" in the pipeline vocabulary, which implicitly treated downstream content as established truth. The new vocabulary forces authors to treat every positive assertion as a claim that is **never assumed true by default** and must travel one of three routes:

1. `ClaimType=direct` or `ClaimType=inference` — requires `SourceID+ExcerptID` evidence-binding per INV-01.
2. `ClaimType=analyst_judgment` — requires `JustificationRationale` that references ≥ 1 upstream `ClaimID` (see INV-07 and `bsa-claim-binder`/`bsa-no-new-claims-auditor` contracts). Not leakage under INV-03; not evidence-bound in the INV-01 sense.
3. Explicit `A51Ref` routing for unresolved items, contradictions, or decision-needed hypotheses.

Any wording that flattens these three routes into a blanket "every claim needs SourceID+ExcerptID or A51Ref" is itself a semantic-audit failure — it would misclassify valid `analyst_judgment` rows as leakage.

Reference invariants:
- `governance/immutable_invariants.md` **INV-01** (evidence-binding, scoped): every positive `direct`/`inference` claim needs `SourceID+ExcerptID` OR `A51Ref`. `analyst_judgment` claims are exempt from evidence-binding but bound by their own JustificationRationale rule.
- `governance/immutable_invariants.md` **INV-03** (no new claims in Stage 8 / handoff): `ClaimType=analyst_judgment` rows with valid `JustificationRationale` are NOT leakage; everything else new is.
- `governance/immutable_invariants.md` **INV-07** (ClaimType schema closed): exactly `direct | inference | analyst_judgment`.

## Terminology key

| Term | Semantics | When to use |
|---|---|---|
| **claim** | Potentially-false assertion. Never "assumed true". Must be routed through exactly one of: (a) `ClaimType=direct`/`inference` with `SourceID+ExcerptID` evidence-binding (INV-01), (b) `ClaimType=analyst_judgment` with `JustificationRationale` referencing ≥ 1 upstream ClaimID (INV-07), or (c) explicit `A51Ref` for unresolved/contradictory items. Always the right word for pipeline content. | Description fields, invariants, scope bullets, workflow steps, on-audit-failure remediation. |
| **factual content** | Acceptable ONLY as a disambiguator that contrasts direct/inference ClaimTypes with `analyst_judgment`. Avoid when plain "claim" reads naturally. | Narrow contexts: INV-07 wording splits, no-new-claims-contract paraphrase rules. |
| **fact** (bare, no context) | Banned in canonical pipeline text. Exceptions: (a) the explicit legacy-compat note in `bsa-no-new-claims-auditor` + its contract; (b) migration artifacts (`migrations/v0.9_to_v1.0/`). | Never in skill SKILL.md or non-migration reference. |
| **assumed true / established truth** | Banned as implicit framing. Claims are never assumed true; they are evidence-bound or A51-routed. | Never. |

## Audit scope

Every skill under `skills/` that participates in claim-layer production, auditing, or handoff. The initial scope (Sprint 2) targets:

- `bsa-skeptical-reviewer`
- `bsa-citation-auditor`
- `bsa-validation-readiness`
- `bsa-claim-binder`
- `bsa-handoff-packager`
- `bsa-evidence-intake`
- `bsa-no-new-claims-auditor` (renamed skill; legacy-compat exemptions allowed)
- `bsa-orchestrator`
- `d0-synthesis-gatekeeper`

Out of scope for Sprint 2: sidecars (`c4-plantuml-from-context`, `camunda-bpmn-from-context`, `inot-prompt-builder`) — they don't participate in claim semantics.

**Sprint 3 retroactive:** `governance/immutable_invariants.md` was excluded from the Sprint 2 sweep but holds the canonical invariant text that downstream skills cite. It was swept in Sprint 3 (4 hits, all rewrites — see Sprint 3 retroactive findings sub-section below and the matching change-log entry in `governance/immutable_invariants.md`).

## Audit protocol

1. **Grep sweep** — run from repo root:
   ```bash
   grep -rEn '\bfact\b|\bfactual\b|\bfacts\b|established truth|assumed true' \
     skills/bsa-*/ skills/d0-*/
   ```
2. **Classify each hit** into one of:
   - `accept-legacy-compat`: explicit backward-compatibility note mentioning the old term (only in `bsa-no-new-claims-auditor` or migration docs).
   - `accept-narrow-disambiguator`: "factual" used to contrast `direct/inference` vs `analyst_judgment`.
   - `rewrite-to-claim`: bare "fact"/"facts"/"factual" that should become "claim"/"claims" with no loss of meaning.
   - `rewrite-to-evidence-bound`: "as a fact" / "promote … as fact" → "with evidence-binding" / "without `A51Ref` routing".
   - `rewrite-structural`: whole sentence needs rephrasing (rare; flag for discussion).
3. **Apply rewrites** in the same PR as this checklist; every rewrite gets a one-line commit message entry.
4. **Commit the filled checklist** as part of US-S2-02 part 3/3.

## Sprint 2 findings

Initial run of the grep sweep produced 16 hits across 9 files. After classification + rewrite:

| # | File | Line (pre-fix) | Legacy phrase | Classification | Rewrite |
|---|---|---|---|---|---|
| 1 | `skills/bsa-claim-binder/references/claim-layer.md` | 46 | "do not promote it as fact" | rewrite-to-evidence-bound | "do not promote it without evidence-binding" |
| 2 | `skills/bsa-claim-binder/SKILL.md` | 43 | "Positive factual claims are never authored from `A51` alone" | rewrite-to-claim | "Positive claims (direct or inference) are never authored from `A51` alone" |
| 3 | `skills/bsa-claim-binder/SKILL.md` | 49 | "fabricating fact rows" | rewrite-to-claim | "fabricating unsupported claim rows" |
| 4 | `skills/bsa-handoff-packager/references/handoff-contract.md` | 13 | "cannot introduce new facts, actors…" | rewrite-to-claim | "cannot introduce new claims, actors…" |
| 5 | `skills/bsa-handoff-packager/SKILL.md` | 14 | "cannot add facts beyond canonical claim-layer" | rewrite-to-claim | "cannot add claims beyond canonical claim-layer" |
| 6 | `skills/bsa-handoff-packager/SKILL.md` | 40 | "not valid fact sources" | rewrite-to-claim | "not valid claim sources" |
| 7 | `skills/bsa-evidence-intake/SKILL.md` | 41 | "it does not author domain facts" | rewrite-to-claim | "it does not author domain claims" |
| 8 | `skills/bsa-orchestrator/references/shared-control-surface-contracts.md` | 47 | "A51 is not a fact source" | rewrite-to-claim | "A51 is not a claim source" |
| 9 | `skills/bsa-orchestrator/references/workflow-contract.md` | 95 | "Canonical promotion stops when new facts…" | rewrite-to-claim | "Canonical promotion stops when new claims…" |
| 10 | `skills/bsa-orchestrator/references/workflow-contract.md` | 97 | "may not add net-new facts…" | rewrite-to-claim | "may not add net-new claims…" |
| 11 | `skills/bsa-orchestrator/references/ownership-and-lifecycle.md` | 24 | "substitute evidence source for positive factual claims" | accept-narrow-disambiguator | kept — "factual claims" explicitly contrasts with `analyst_judgment` |
| 12 | `skills/d0-synthesis-gatekeeper/references/discovery-to-bsa-handoff.md` | 12 | "cannot directly promote canonical main-cycle facts" | rewrite-to-claim | "cannot directly promote canonical main-cycle claims" |
| 13 | `skills/d0-synthesis-gatekeeper/SKILL.md` | 14 | "seed outputs contain only discovery-claim-linked facts" | rewrite-to-claim | "seed outputs contain only discovery-claim-linked assertions" |
| 14 | `skills/bsa-no-new-claims-auditor/SKILL.md` | 3, 10 | "previously 'facts'", "facts (established truths)" | accept-legacy-compat | kept — explicit terminology-note on the renamed skill |
| 15 | `skills/bsa-no-new-claims-auditor/references/no-new-claims-contract.md` | 3 | "renamed from `no-new-facts`" | accept-legacy-compat | kept — terminology note at top of the contract |
| 16 | `skills/bsa-no-new-claims-auditor/references/no-new-claims-contract.md` | 16 | "preserves upstream factual content" | accept-narrow-disambiguator | kept — "factual content" = direct+inference content, contrasted implicitly with analyst_judgment in the surrounding rule set |
| 17 | `skills/bsa-context-framer/SKILL.md` | 40 | "never as fact source" | rewrite-to-claim | "never as claim source" |
| 18 | `skills/bsa-context-framer/SKILL.md` | 49 | "Every row … containing a positive factual claim must trace to ClaimID" | accept-narrow-disambiguator | kept — "factual claim" contrasts direct/inference rows with analyst_judgment rows in the same INV-01 restatement |
| 19 | `skills/bsa-context-framer/references/context-state-contract.md` | 19 | "Every positive factual claim cites ClaimID" | accept-narrow-disambiguator | kept — same disambiguator pattern as #18 |
| 20 | `skills/bsa-semantic-extractor/SKILL.md` | 41 | "does not create net-new facts, actors, states, or boundaries" | rewrite-to-claim | "does not create net-new claims, actors, states, or boundaries" |
| 21 | `skills/d0-feasibility-assessor/references/constraints-and-feasibility.md` | 20 | "cannot become canonical discovery facts" | rewrite-to-claim | "cannot become canonical discovery claims" |

**Summary:** 14 rewrites applied; 7 accepts (3 legacy-compat in `bsa-no-new-claims-auditor`, 4 narrow-disambiguator across orchestrator + context-framer + no-new-claims contract). Hits 17-21 were surfaced on the second grep sweep performed after the first batch of 11 rewrites landed; documenting them here for completeness of the Sprint 2 audit.

### No separate "skeptical-reviewer / citation-auditor / validation-readiness" findings
Those three skills (primary US-S2-02 AC-7 audit targets) contain **zero** legacy-compat violations. Both SKILL.md files and their references consistently use "claim" throughout. `bsa-validation-readiness` was already updated in US-S2-02 part 1/3. The claim here is empirically verified by the grep sweep + classification above.

## Sprint 3 retroactive findings (governance)

Grep sweep run against `governance/` after Sprint 2 closed surfaced 4 hits in `governance/immutable_invariants.md` that the Sprint 2 scope had excluded. All four classified as rewrites (no accepts).

| # | File | Line (pre-fix) | Legacy phrase | Classification | Rewrite |
|---|---|---|---|---|---|
| G1 | `governance/immutable_invariants.md` | 11 (INV-01 statement) | "Every positive factual claim promoted into canonical surfaces" | rewrite-to-claim | "Every positive `direct` or `inference` claim promoted into canonical surfaces" |
| G2 | `governance/immutable_invariants.md` | 49 (INV-03 override policy) | "`none` for positive factual claims" | rewrite-to-claim | "`none` for positive `direct`/`inference` claims" |
| G3 | `governance/immutable_invariants.md` | 69 (INV-05 heading) | "INV-05: A51 is not a fact source" | rewrite-to-claim | "INV-05: A51 is not a claim source" |
| G4 | `governance/immutable_invariants.md` | 70 (INV-05 body, two phrases) | "source of positive factual claims" / "guarded hypothesis, not a fact" | rewrite-to-claim / rewrite-to-evidence-bound | "source of positive claims" / "guarded hypothesis, not a canonical claim" |

**Summary:** 4 rewrites applied; 0 accepts. Wording-only cleanup — no semantic change to any invariant, no `CanonPolicyVersion` bump. INV-01 and INV-03 use explicit ClaimType naming (`direct`/`inference`) rather than the narrow-disambiguator `factual` shorthand because the foundational invariant text is the canonical scoping source that skill docs cite. INV-05 body uses bare "claim source" matching the Sprint 2 phrasing already in `skills/bsa-orchestrator/references/shared-control-surface-contracts.md` line 47. See change-log entry `2026-04-20` in `governance/immutable_invariants.md`.

Cross-ref check: only `skills/bsa-orchestrator/references/discovery_to_main_merge.md:157` references INV-05 by name; it already paraphrases as "A51 is not a positive-claim source", so no breakage from the heading rename.

Documented accepts (post-rewrite): the `2026-04-20` change-log entry inside `governance/immutable_invariants.md` quotes the five legacy phrases verbatim to document the rename. These are `accept-legacy-compat` by the same principle as the `bsa-no-new-claims-auditor` terminology note — quoting a legacy phrase inside an explicit rename-history entry is the only way to keep the audit trail readable. Future grep sweeps over `governance/` should treat hits inside that change-log entry as expected.

## Ongoing governance

Any future PR that edits any skill under `skills/` or any file under `governance/` MUST:

1. Rerun the grep sweep on the files it touches.
2. For every hit, declare the classification (accept-legacy-compat / accept-narrow-disambiguator / rewrite-to-*) in the PR description.
3. Apply rewrites in the same PR — no "will address later" deferrals for `rewrite-to-*` findings.
4. Update this checklist's findings table (Sprint 2 for skills, Sprint 3 retroactive for governance, or a new sub-section if the scope expands again) with any new hits discovered.

Any deviation from the above requires explicit approval + major `CanonPolicyVersion` bump (see `governance/immutable_invariants.md` change control).

## Related

- Sprint 2 US-S2-02 plan entry: `/Users/kkitanin/.claude/plans/dreamy-wiggling-zebra.md`
- Migration tool: `scripts/migrate_v0.9_to_v1.0.py` (Sprint 2 US-S2-02 part 2/3)
- Renamed skill: `skills/bsa-no-new-claims-auditor/SKILL.md` + `references/no-new-claims-contract.md`
- Governance: `governance/immutable_invariants.md` (INV-01, INV-03, INV-07)
