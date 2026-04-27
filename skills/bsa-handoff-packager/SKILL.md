---
name: bsa-handoff-packager
description: Assemble consumer-specific H1-H4 handoff proposals from validated canonical outputs with quote-fidelity and no-new-claims enforcement (INV-03). ClaimType=analyst_judgment rows in H1/H4 are allowed when JustificationRationale references upstream ClaimIDs (INV-07).
---

# BSA Handoff Packager

Use this skill after Stage 8 no-new-claims pass.

## Scope
- Build `H1-H4` package proposals from validated canonical artifacts only.
- Enforce quote-fidelity to canonical claim-layer (`A58/A59`).
- Prevent new-claim leakage in package outputs (`KPI-005`).
- Keep discovery `Discovery Report/Brief` as non-canonical wording aids only; they can seed wording but cannot add claims beyond canonical claim-layer.

## Inputs
- `analysis/canonical/stage8/readiness_assessment.md`
- `analysis/canonical/stage8/readiness_profile_scorecard.md`
- `analysis/canonical/stage7/validation_report.md`
- `analysis/canonical/core_controls/A58_evidence_excerpts.csv`
- `analysis/canonical/core_controls/A59_claim_register.csv`
- `analysis/canonical/core_controls/A51_issue_route_register.csv`

## Outputs

Two-stage flow (v1.3.7+ explicit routing — the pre-v1.3.7 contract listed only the proposal-stage paths and silently relied on the orchestrator to know where the terminal location was):

**Stage A — proposals (worker output, gated by F5 + no-new-claims auditor):**
- `analysis/proposals/stage7_8/handoff/H1_exec_brief.md`
- `analysis/proposals/stage7_8/handoff/H2_delivery_packet.md`
- `analysis/proposals/stage7_8/handoff/H3_validation_packet.md`
- `analysis/proposals/stage7_8/handoff/H4_open_items_packet.md`
- `analysis/proposals/stage7_8/handoff/handoff_manifest.json`
- `analysis/proposals/stage7_8/handoff/handoff_evidence_binding_map.csv`

**Stage B — terminal handoff dir (post-audit, operator-facing):**
- `analysis/handoff/H1_exec_brief.md`
- `analysis/handoff/H2_delivery_packet.md`
- `analysis/handoff/H3_validation_packet.md`
- `analysis/handoff/H4_open_items_packet.md`
- `analysis/handoff/handoff_manifest.json`
- `analysis/handoff/handoff_evidence_binding_map.csv`

The Stage-B copies are byte-identical to Stage A — the route is a copy, not a regenerate (no second build, no checksum recomputation). Downstream consumers (`/bsa-dev-handoff`, the operator dashboard, the backlog-bridge) read from `analysis/handoff/` only — they MUST NOT reach into `analysis/proposals/stage7_8/handoff/` (that path is worker-internal). Pre-v1.3.7 the SKILL.md listed only Stage A; consumers found nothing at the documented terminal path because the routing step was implicit/missing — output review #3.8 fix.

## Workflow
1. Read canonical Stage 8 outputs, canonical artifact map, and canonical control surfaces.
2. Build H1-H4 packages by consumer profile.
3. Attach claim references or `A51Ref` to every high-impact statement.
4. Emit package outputs under `analysis/proposals/stage7_8/handoff/` (Stage A).
5. Submit outputs to `bsa-no-new-claims-auditor`. ON FAILURE: stop; revise per the on-audit-failure section; do not route to terminal location until the auditor passes.
6. **Route to terminal handoff dir** (v1.3.7+): on successful no-new-claims pass, copy each Stage-A file byte-for-byte into `analysis/handoff/`. The copy MUST preserve content exactly (no re-render, no re-timestamp); the manifest's checksum stays valid. Existing files at the terminal location are overwritten (the manifest's `pack_version` field bumps on every re-run; downstream consumers identify staleness via that field, not file timestamps). After all 6 files land at the terminal location, the orchestrator emits `handoff.ready.json`.

## Invariant
- Once a canonical equivalent exists, raw proposal folders are not valid claim sources for package generation.

## On Audit Failure
1. Read handoff no-new-claims findings.
2. Revise proposal-layer H1-H4 and manifest only.
3. Route unresolved wording disputes via `A51Ref`.
4. Re-submit handoff package for no-new-claims verification.

## Validation Binding
- `SCN-STAGE78-001-E`: H1-H4 generated without new-claim leakage (aggregate).
- `SCN-STAGE78-001-E-H1` / `-E-H2` / `-E-H3` / `-E-H4`: per-pack shape and citation closure.

## References
- [references/handoff-contract.md](references/handoff-contract.md) — cross-pack rules + manifest pointer.
- [references/h1_spec.md](references/h1_spec.md) — H1 executive brief content contract.
- [references/h2_spec.md](references/h2_spec.md) — H2 delivery packet content contract.
- [references/h3_spec.md](references/h3_spec.md) — H3 validation packet content contract.
- [references/h4_spec.md](references/h4_spec.md) — H4 open items packet content contract.
- [references/handoff_manifest.schema.json](references/handoff_manifest.schema.json) — JSON schema for `handoff_manifest.json`.
