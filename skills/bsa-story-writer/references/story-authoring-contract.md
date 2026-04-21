# Story Authoring Contract

Authoritative rules for `bsa-story-writer`. Consumers (`bsa-test-scenario-builder`, `bsa-traceability-matrix`, `bsa-backlog-bridge`) rely on these; violating them breaks downstream skills.

## Story shape

Canonical form: `As a <persona>, I want <goal>, so that <benefit>`.

- `<persona>` — a specific actor, not a generic label. "Triage Agent" / "Delivery Customer" / "Compliance Auditor" are specific; "user" / "stakeholder" / "admin" are generic (banned).
- `<goal>` — imperative verb phrase describing what the persona wants to accomplish.
- `<benefit>` — outcome the persona cares about. Strongly recommended; omit only when truly redundant.

## Derivation rules

**Rule 1 — Source filter.** A story candidate arises from:
- A59 claims where `Criticality IN (level-1, level-2)` AND the claim describes an actor performing (or needing to perform) a workflow action.
- A62 NFRs where the quality attribute translates into a persona-observable experience (e.g., availability NFR → "I want to use the system at 3 AM" story).

Claims that describe system-internal behavior only (architectural observations, data-flow descriptions) do NOT map to stories directly; they may inform NFRs (via `bsa-nfr-collector`) or technical tasks (not yet in scope).

**Rule 2 — One subject-verb pair per story.** If a candidate grouping touches two workflow actions or two personas, split into multiple rows. INVESTStatus = `needs-splitting` when a story straddles these boundaries.

**Rule 3 — Persona grounding.** `Persona` MUST name an actor explicitly identified in the upstream A50 / A59 material. Use A50's source attribution (e.g., a transcript from "Jennifer, Triage Ops Lead" → persona "Triage Ops Lead"). When multiple actors are candidates, pick the one most concretely supported by evidence.

**Rule 4 — No net-new subjects or verbs.** The subjects and verbs in `StoryText` MUST appear in the linked SourceClaimIDs or RelatedNFRIDs. Introducing a new subject ("As a Triage Agent, I want the mobile app to …") when no upstream claim mentions a mobile app = drift = rejected. If the story genuinely needs a subject not present upstream, raise an A51 `decision_needed` for "add claim about mobile-app touchpoint" and set INVESTStatus=`escalate`.

**Rule 5 — Acceptance criteria must be observable.** Each criterion is a checkable statement of external behavior. Bad: "the system works correctly". Good: "when an order times out, the Triage Agent sees an escalation card within 2 seconds". Non-observable criteria → INVESTStatus=`needs-testable-acceptance`, raise A51.

**Rule 6 — Measurable NFR acceptance.** When `RelatedNFRIDs` is non-empty and points at a quantitative NFR (Metric + Target populated), at least one acceptance criterion MUST embed that Metric+Target. Example: NFR "p95 latency < 500ms" → acceptance "order-submission response observed < 500ms at p95 under 50 concurrent users".

**Rule 7 — Priority inheritance.** `Priority` = max of source-claim Criticality values (level-1 > level-2 > level-3). May be raised (never lowered) with explicit rationale recorded in Notes + A51Ref pointing to a `decision_needed` row that documents why.

**Rule 8 — INVEST check.**

| Criterion | What it checks | Failure → INVESTStatus |
|---|---|---|
| **I**ndependent | Story does not depend on a sibling story to be valuable. | `needs-splitting` if dependency is structural; `pass` with Notes if dependency is soft. |
| **N**egotiable | Story is a conversation starter, not a spec mandate. | `needs-negotiation` when story text reads as a hard requirement. |
| **V**aluable | Delivers observable benefit to the persona. | Rare — usually means the claim doesn't actually describe user value. Raise A51. |
| **E**stimable | Team could T-shirt-size it. | `needs-estimation` when upstream context is too vague. |
| **S**mall | Fits in one iteration. | `needs-splitting` when it clearly doesn't. |
| **T**estable | Acceptance criteria are observable. | `needs-testable-acceptance` when criteria are fuzzy. |

Any non-`pass` status → co-populate `A51Ref` (INVEST-A51 coupling).

## Banned anti-patterns

Refuse to emit any of these:

| Anti-pattern | Why banned | Right place |
|---|---|---|
| "As a user I want feature X" | Persona is generic | Use specific actor; if genuinely unknown, raise A51 |
| "As a developer I want clean code" | Dev-facing, not user story | Not a story at all; belongs in engineering backlog (out of BSA scope) |
| "As an admin I want to configure Y" | "Admin" is a proxy; real actor vague | Identify the real actor (ops engineer, support lead); if unknown, A51 |
| "The system shall do X" | Requirement, not a story | Belongs in A62 (if quality) or A59 (if observed fact) |
| "As a Triage Agent I want the system to be fast" | Measurable qualities are NFRs, not stories | Move to A62, link from story via RelatedNFRIDs |
| Story with empty `SourceClaimIDs` AND empty `RelatedNFRIDs` | INV-08 violation | Raise A51; never author |

## Report shape (story_authoring_report.md)

```markdown
# Story Authoring Report

## Summary
- Claims scanned: 42
- NFRs scanned: 12
- Candidate story groupings identified: 18
- A70 rows emitted: 15
- A51 routes raised: 5 (3 needs-splitting, 1 needs-estimation, 1 escalate)

## INVESTStatus distribution
| Status | Count | % of rows |
|---|---|---|
| pass | 10 | 67% |
| needs-splitting | 3 | 20% |
| needs-estimation | 1 | 7% |
| escalate | 1 | 7% |

## Coverage gaps
- Claims with no resulting story: [C-007, C-023]
- NFRs with no linking story: [NFR-PERF-002]

## A51 routes raised
| StoryID | INVEST criterion | A51Ref | Next action |
|---|---|---|---|
| STORY-UX-003 | Small | A51-DEC-019 | Split into 3 sub-stories |
```

## Acceptance criteria

The skill's output passes iff:

1. Every A70 row validates against `governance/schemas/a70.schema.json` (F5 enforces this at write time).
2. Every row has non-empty SourceClaimIDs OR non-empty RelatedNFRIDs (INV-08).
3. Every row where INVESTStatus != 'pass' has non-empty A51Ref.
4. Every referenced ClaimID exists in promoted A59; every referenced NFRID exists in promoted A62; every A51Ref exists in A51.
5. Every quantitative NFR linked via RelatedNFRIDs has at least one acceptance criterion embedding its Metric+Target.
6. No story introduces subjects / verbs / conditions absent from its SourceClaimIDs or RelatedNFRIDs (enforced by the no-new-stories auditor).

## Integration with the no-new-stories auditor

Sprint 7 US-S7-03 adds a no-new-stories auditor that runs against A70 pre-promotion. Its check:

- Tokenize each row's StoryText + AcceptanceCriteria.
- Tokenize the referenced source claims' Statement + evidence excerpts (A58).
- Flag any significant noun / verb in the story not traceable to the source tokens.
- Surface findings as `STORY_LEAKAGE` — blocks promotion until the story is re-authored or the gap is raised as A51.

Mirror of the main-cycle `bsa-no-new-claims-auditor`: the discipline that keeps handoff bound to claims also binds stories.
