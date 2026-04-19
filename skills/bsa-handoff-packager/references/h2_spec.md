# H2 Delivery Packet — Content Contract

Authoritative section / content rules for `H2_delivery_packet.md`. Peer specs: `h1_spec.md`, `h3_spec.md`, `h4_spec.md`.

## Purpose

Give the delivery team (engineering, solution delivery, integrators) the **operational index** into canonical artifacts: what to build, against which contracts, with which dependencies. H2 is a navigation document — it compresses and tables canonical content, then points to the promoted files for detail.

## Audience

- **Primary:** Engineering leads, solution architects, delivery managers.
- **Secondary:** Integration partners (read-only), product owner (read-only).
- **Non-audience:** Executives (H1), QA (H3), PMO (H4).

## Length

- No hard cap — H2 is the largest pack by design.
- Soft guideline: target 4-12 printed pages; beyond that, audience disengages.
- If H2 grows unbounded, push detail into linked canonical artifacts rather than expanding inline.

## Required Sections

Every `H2_delivery_packet.md` MUST contain these seven sections, in this order, with the exact headings below.

### `## Delivery Manifest (what's included)`
- Table with columns: `Artifact | Role | Canonical path | Version`.
- One row per canonical artifact that informs delivery (A50, A51, A58, A59, A60, A61, stage3 semantic index, stage4 domain model, stage5 backbone, stage6 contracts, stage7 validation report, stage8 readiness assessment).
- `Version` = `canon_policy_version_hash` from the promoted marker at time of handoff.
- This table is the single source of truth for "what's in the drop" — any file not listed here MUST NOT be relied on by delivery.

### `## Requirements Summary (references fr_register/nfr_register)`
- Two tables (FR / NFR).
- FR table columns: `FR-ID | Title | Priority | Owner role | ClaimID refs`.
- NFR table columns: `NFR-ID | Category | Target | Measurement | ClaimID refs`.
- Priority ∈ {`must`, `should`, `could`, `won't-now`} (MoSCoW).
- NFR Category ∈ {`performance`, `security`, `availability`, `compliance`, `usability`, `observability`, `maintainability`}.
- Every row MUST cite `[C-xxx]`; rows resting on analyst_judgment cite `[AJ:C-xxx]` + upstream.
- Rows with unresolved decision-needed items MUST cite `[A51-xxx]`.

### `## Contracts & Interfaces (references A61)`
- Table with columns: `AnchorID | Contract name | Consumer | Producer | Contract kind | Reference`.
- Contract kind ∈ {`api`, `event`, `data`, `integration`, `process`}.
- `AnchorID` matches canonical A61 anchor map exactly.
- `Reference` points to canonical contract artifact (e.g., `analysis/canonical/stage6/contracts/<name>.md`) or to a derived sidecar (OpenAPI/AsyncAPI/proto) with `derived-only` label.
- **Rule:** H2 lists anchors; it does not duplicate the contract body. Delivery reads the referenced file for the schema.

### `## Data & State (references entity/status catalogs)`
- Two tables (Entities / State machines).
- Entities table columns: `Entity | Owner | Lifecycle | Canonical ref`.
- State machines table columns: `Entity | States | Transitions | Terminal states | Canonical ref`.
- `Canonical ref` points to `analysis/canonical/stage4/domain_model/<file>.md`.
- Rule: no inline schema dumps in H2 — if the catalog is > 5 rows, split into a linked appendix.

### `## Processes (references backbone)`
- Table with columns: `Process | Trigger | Steps (summary) | Stakeholder | Canonical ref | Sidecar (if any)`.
- `Steps (summary)` is a 1-line compression, not the full BPMN narrative.
- `Canonical ref` points to `analysis/canonical/stage5/backbone/<file>.md`.
- `Sidecar` column marks `c4` / `bpmn` / `none`; sidecar outputs are non-canonical navigation aids only.

### `## Assumptions & A51 Routes`
- Table with columns: `A51Ref | IssueType | Severity | BlockingStatus | Owner role | Next action`.
- Only rows with `ResolutionStatus != closed` at handoff time.
- Rows with `BlockingStatus=hard` MUST also appear in H4 `## Decisions Required` — delivery needs to see the same item, but H4 drives resolution.
- Rows with `BlockingStatus=soft` are delivery's to track unless escalated.

### `## Next Gate Preconditions`
- Checklist (markdown `- [ ]` items) listing what must be true before delivery starts next phase.
- At minimum: (a) all `## Assumptions & A51 Routes` `hard` rows closed or explicitly waived by sponsor, (b) Stage 8 readiness_assessment `PASS`, (c) H1 sponsor sign-off recorded.
- Each item may cite `[C-xxx]` or `[A51-xxx]` where applicable.

## Citation Rules

Same as H1 (`[C-xxx]`, `[AJ:C-xxx]`, `[A51-xxx]`), applied inside table cells as well as in prose. Table cells may hold multiple IDs separated by whitespace.

## Forbidden Content

- New actors, entities, interfaces, processes, or contracts not present in canonical artifacts.
- Inline contract bodies or schema dumps — link to canonical instead.
- Duplicates of H1 findings or H4 open items (link, do not restate).
- Performance / availability targets not derived from canonical NFR register.

## Audit Binding

- `bsa-no-new-claims-auditor` validates every H2 row for claim traceability (same rule as other H-packs).
- `bsa-citation-auditor` validates `[C-xxx]` and anchor references resolve to A59 / A61.
- `SCN-STAGE78-001-E-H2` (see validation-scenario-manifest.csv) checks H2 shape + anchor closure.

## Cross-References

- Peer specs: `h1_spec.md`, `h3_spec.md`, `h4_spec.md`.
- Manifest schema: `handoff_manifest.schema.json`.
- Upstream: `analysis/canonical/stage4/`, `stage5/`, `stage6/`, `stage7/`, `stage8/`.
- Invariants: INV-01 (evidence), INV-03 (no new claims), INV-06 (no parallel governance ledgers).
