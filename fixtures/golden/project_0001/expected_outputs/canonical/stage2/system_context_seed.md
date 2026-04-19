# System Context Seed — fixture-project-0001

## System Boundary

The in-scope system is the support-ticket triage process of the ops team, from ticket arrival at any intake channel through assignment of a closure outcome [C-001] [C-002] [C-004]. Out of scope: billing-team internal workflow and engineering escalation queue internals — both are treated as neighboring systems.

## Neighboring Systems

- Support email inbox (`support@example.test`) — inbound intake channel for customer tickets [C-001].
- Self-service portal — inbound intake channel queued directly into the ticketing database [C-001].
- Billing-team intake form — upstream feeder that produces tagged copies of billing tickets for triage [C-001].
- On-call agent pager — outbound notification channel triggered by High/Critical severity [C-003].
- Engineering escalation queue — downstream consumer of tickets routed via "escalated to engineering" outcome [C-006].

## Interface Obligations

- Inbound: receive tickets from email/portal/billing-tag — no protocol constraint documented [C-001] [A51-002].
- Inbound: attach-severity decision within one hour of arrival — clock starts at intake timestamp [C-002].
- Outbound: page on-call agent for High/Critical severity — pager protocol not documented in source material, routed to [A51-002].
- Outbound: route "escalate to engineering" with reproduction steps attached — quality gap surfaced by [C-006].
- Outbound: route "route to billing" as tagged forward — billing path reported as friction-free in source [C-001].

## Context Triggers

- Ticket-arrived (via email, portal, or billing tag) initiates a new triage instance [C-001].
- Severity-assigned event completes triage entry; main-cycle triage work runs on every ticket [C-002].
- No explicit batch-triage trigger documented in the current flow [A51-002].
