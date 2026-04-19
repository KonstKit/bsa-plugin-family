# Stakeholder Authority Rules

Rules governing `stakeholder_authority_map.md` (Stage 2 artifact owned by `bsa-context-framer`).

## Authority taxonomy

Exactly three authority levels. No synonyms:

| Level | Meaning | Examples |
|---|---|---|
| `decision` | Binds the organization — their approval is sufficient to change scope or enact a constraint | Sponsor, product owner for the in-scope system, domain regulatory officer |
| `consultation` | Must be consulted; cannot unilaterally decide | Subject-matter expert, ops lead, downstream team lead |
| `informational` | Receives updates but is neither decider nor consulted gate | Adjacent team member, auditor, stakeholder-of-record on a neighboring system |

RACI mapping hint (non-normative): `decision` ≈ A/R, `consultation` ≈ C, `informational` ≈ I.

## ID assignment

- `stakeholder_id` uses pattern `ST-[0-9]{3}`.
- IDs are assigned once and never re-used across runs of the same `RunID`.
- When a new stakeholder appears in promoted claim-layer across Stage 1 re-entry, allocate the next unused number.

## Evidence-binding per row

Every row must be traceable upstream. Two acceptable patterns:

1. **Claim-cited row** — add a trailing narrative line below the table (one per stakeholder) in the form:
   ```
   ST-001 evidence: [C-023] (ops process note); [C-031] (interview).
   ```
2. **A51-routed row** — populate `linked_a51_refs` with the `A51-xxx` ID(s) that raise uncertainty about this stakeholder's authority level or decision scope.

A row with neither pattern fails the `SCN-STAGE2-001-B` binding check.

## Authority-contestation flow

When promoted evidence assigns the same `decision_scope` to two stakeholders at different authority levels, or two `decision` stakeholders overlap on the same scope:

1. Raise a new `A51` entry with `IssueType=decision_needed`, `Severity=medium`, `BlockingStatus=soft` (escalate to `hard` only if downstream stages cannot progress without resolution).
2. Link every affected row to the new `A51Ref` via `linked_a51_refs`.
3. Do NOT attempt to resolve by picking one — route it out.

When PROMOTION is attempted with unresolved `hard`-status authority contestation, Stage 2 `stage2.context_state.pass` marker MUST NOT be emitted.

## Analyst-judgment rows

This artifact is a stakeholder map, not an opinion document. `ClaimType=analyst_judgment` rows do NOT appear in `stakeholder_authority_map.md` itself — they may only appear in A59 proposal layer when the analyst needs to surface a recommendation about how authority should be structured (e.g., "recommend consolidating approval authority for SLA changes under a single owner"). Such a recommendation goes into A59 with `JustificationRationale` referencing the `ClaimID`s of contested authority claims, not into the stakeholder map table itself.

## Decision-scope phrasing

- One sentence per row, present tense, active voice.
- Bounded: state what the stakeholder decides, not the business area generally.
- Example (good): "Approves changes to SLA windows on High/Critical severity."
- Example (bad): "Owns customer support." (Too broad; does not constrain downstream reasoning.)

## Out of scope for this artifact

- Organizational reporting lines (who reports to whom) — not relevant to BSA reasoning unless it directly affects a decision boundary.
- Role-specific compensation, titles, vacation calendars — out of scope.
- Multi-org stakeholder federation — if in-scope system spans organizations, handle via `collaboration`-style system context, not via expanding the stakeholder map to cover the full partner org tree.
