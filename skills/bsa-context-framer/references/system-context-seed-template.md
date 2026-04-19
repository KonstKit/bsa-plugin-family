# System Context Seed Template

Authoritative template for `system_context_seed.md` (Stage 2 artifact owned by `bsa-context-framer`).

## Purpose

Seed the system-context view that downstream stages consume:

- Stage 4 `bsa-domain-modeler` uses `## Neighboring Systems` as a starting actor set.
- Stage 5 `bsa-backbone-builder` uses `## Context Triggers` when choosing path (process vs structural).
- Stage 6 `bsa-contract-builder` uses `## Interface Obligations` as the initial A61 candidate surface.
- Optional `c4-plantuml-from-context` sidecar uses this as the System Context diagram source.

## Required structure

```markdown
# System Context Seed — <RunID>

## System Boundary

Single-paragraph statement of the one software system in scope, citing at least one `ClaimID` or `A51Ref`. No bullet lists here; if multiple systems are candidates, raise `A51` with `IssueType=boundary_risk` and cite it.

## Neighboring Systems

- <External actor or system name> — <one-sentence role relative to in-scope system> [C-xxx or A51-xxx]
- ...

## Interface Obligations

- <Inbound | Outbound>: <short obligation description> — <protocol/technology when known> [C-xxx or A51-xxx]
- ...

## Context Triggers

- <Trigger name>: <what event initiates a main-cycle instance> [C-xxx or A51-xxx]
- ...
```

## Authoring rules

1. **Single in-scope system.** If evidence supports multiple candidate boundaries, `## System Boundary` picks the narrowest workable boundary and raises an `A51` for the alternatives. Never enumerate candidates as bullets.
2. **No invented neighbors.** A neighbor may only appear here if upstream claim-layer (A59) mentions it, or if the omission is explicitly routed to `A51`.
3. **Protocol labels are optional.** When a claim documents HTTP/REST/Kafka/gRPC/etc., include it in the Interface Obligations bullet. When silent, omit — do not guess.
4. **Inbound vs Outbound.** Prefix every Interface Obligation with `Inbound:` or `Outbound:`. Bidirectional flows become two bullets.
5. **Context Triggers are concrete.** A trigger bullet names the event and the initiator. "User submits a ticket" is a trigger; "User interaction" is not (too vague — raise A51 if only that is known).
6. **Evidence citation is mandatory.** Every bullet ends with `[C-xxx]` or `[A51-xxx]`. Bare narrative fails `SCN-STAGE2-001-B`.

## Sidecar hook

When the user requests a diagram, `c4-plantuml-from-context` can consume this file directly. The sidecar must write to `analysis/views/c4/<timestamp>/system_context.puml` and emit `anchor_manifest.json` tying each diagram element to a `ClaimID` in A59 (see `bsa-orchestrator/references/sidecar-integration.md`). This skill does not invoke the sidecar itself — it stays in control-plane; sidecar routing is orchestrator-owned.

## Out of scope

- Component-level decomposition (Stage 5+ territory).
- Deployment topology (regions, availability zones, replica counts) — that belongs in Stage 6 data/rule/state contract pack or in a separate deployment sidecar.
- Security zones and trust boundaries — Phase 2 adds `bsa-threat-modeler` (Sprint 5+); meanwhile, obvious trust-boundary claims are surfaced here as Interface Obligations but full threat modeling is deferred.
