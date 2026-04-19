# Context-State Frame — fixture-project-0001

## Problem Or Objective

Analyze the current support-ticket triage flow and surface recurring pain points from ops + product viewpoints [C-001] [C-005] [C-006].

## Scope Boundary

### In

- Ticket intake channels (email, self-service portal, billing-team escalation) [C-001].
- Severity taxonomy and pager routing [C-002] [C-003].
- Triage-outcome space (four closure types) [C-004].
- SLA windows for High/Critical and Low/Medium [C-007].

### Out

- Billing-team internal process beyond the tagged-copy interface [C-001].
- Engineering downstream workflow internals (scope only intersects at the escalation handoff) [C-006].

## Context Mode

direct

## Stakeholders

- Ops team lead (role: process owner for current triage flow) [C-001] [ST-001].
- Product manager (role: backlog prioritization and product direction) [C-005] [C-006] [ST-002].

## Constraints

- Severity assignment MUST happen within one hour of ticket arrival [C-002] [CN-001].
- Only High and Critical severity tickets page the on-call agent — paging rule is fixed [C-003] [CN-002].
- SLA-for-initial-response is 4 hours on High/Critical and 1 business day on Low/Medium [C-007] [CN-003].

## Dependencies

- Ticketing-system severity metadata (source of truth for pager routing) [C-002] [DP-001].
- Billing-team's own intake form (upstream feeder for billing-tagged tickets) [C-001] [DP-002].
- Engineering escalation queue (downstream consumer requiring reproduction steps) [C-006] [DP-003].

## Open Uncertainties

- Exact duplicate-ticket rate is the PM's estimate, not a measured system metric [A51-001].
- Whether SLA windows need channel-specific variants is unresolved [A51-002].
