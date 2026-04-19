# Support Ticket Triage — Current Flow (Source 001)

Origin: internal process note, authored by ops team lead, 2026-02-10.

Support tickets arrive via three channels:
- Email inbox `support@example.test` (monitored by the on-call agent).
- Self-service portal form (queued in the ticket database).
- Escalation from the billing team (arrives as a tagged copy of a billing-team ticket).

Every ticket is assigned a severity within one hour. The ticketing system supports severities Low, Medium, High, Critical. Only High and Critical severity tickets page the on-call agent. Tickets remain in New status until an agent picks them up.

Triage closes with one of four outcomes:
- Resolved in first contact.
- Escalated to engineering.
- Marked duplicate of an existing ticket.
- Routed to billing team.

The SLA is 4 hours for initial response on High/Critical, 1 business day on Low/Medium.
