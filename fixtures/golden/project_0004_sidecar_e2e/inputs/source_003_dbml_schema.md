# Ticket-Persistence Data Model (Source 003)

Origin: internal architecture-of-record database design note, authored by internal architect, 2026-02-15.

The ticket-persistence layer stores every incoming support ticket in a `tickets` table and every triaging agent's profile in an `agents` table. Each ticket references exactly one agent via the `tickets.assigned_agent_id` foreign key — this is a many-to-one relationship (one agent triages many tickets; each ticket has at most one currently-assigned agent; unassigned tickets carry a NULL in this column).

Column shapes:
- `agents.id` — integer primary key, autoincrement.
- `agents.username` — varchar, NOT NULL, unique.
- `tickets.id` — integer primary key, autoincrement.
- `tickets.assigned_agent_id` — integer, nullable; foreign key to agents.id.
- `tickets.severity` — enum (Low / Medium / High / Critical), NOT NULL.
- `tickets.created_at` — timestamp, NOT NULL.

Both tables belong to the `support_desk` bounded context. The DBML schema file lives at `analysis/views/dbml/ticket_persistence.dbml`, with 10 anchors tracked in A61 (2 tables + 6 columns + 1 ref + 1 enum) consumed by the dbml-from-context sidecar in orchestrated mode.
