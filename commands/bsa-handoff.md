---
name: bsa-handoff
description: Assemble H1-H4 handoff packets after Stage 8 passes. Runs bsa-handoff-packager, builds the manifest + evidence binding map, validates against schemas, runs no-new-claims gate.
---

# `/bsa-handoff`

Assemble the H1-H4 handoff bundle for delivery.

## Usage

```
/bsa-handoff [--verbose]
```

- `--verbose` — emit the full binding-map build log and every manifest field as it's computed.

## Prerequisites

- Stage 8 passed: `stage8.no_new_claims.pass.json` marker present.
- All prior stage markers present (enforced by the `PreToolUse:Bash` hook wrapping this command).

## What this command does

Delegate to `bsa-orchestrator`, which routes to `bsa-handoff-packager`:

1. Read Stage 8 canonical outputs + `A58/A59/A60/A51` + `A61` anchor map.
2. Build the four handoff packets per their specs (`skills/bsa-handoff-packager/references/h1_spec.md`, `h2_spec.md`, `h3_spec.md`, `h4_spec.md`):
   - `H1_exec_brief.md` (≤ 2 pages, executive audience, SCQA opener, `[AJ:Cxxx]` tags on analyst judgments).
   - `H2_delivery_packet.md` (7 required sections, table-heavy, delivery-team audience).
   - `H3_validation_packet.md` (5 required sections, KPI-001..005 scorecard with per-tier breakdown per Sprint 3 US-S3-03, Phase-3 SCN-seed placeholder).
   - `H4_open_items_packet.md` (5 required sections, A51 as single sink, analyst-judgment-heavy Decisions Required).
3. Build `handoff_evidence_binding_map.csv` — one row per inline `[C-xxx]`, `[AJ:C-xxx]`, `[A51-xxx]` citation across H1-H4, linked back to its A59/A51 row.
4. Build `handoff_manifest.json` per `handoff_manifest.schema.json`: pack_id, pack_version, generated_at, canon_policy_version, includes (h1..h4 paths), evidence_binding_map_path, no_new_claims_verdict, checksum (sha256 over covers[]).
5. Run `bsa-no-new-claims-auditor` in handoff mode over H1-H4. Embed the verdict (verdict + leakage_count + analyst_judgment_valid/invalid + report_path) in `handoff_manifest.json.no_new_claims_verdict`.
6. **Route H1-H4 to `analysis/handoff/`** (v1.3.7+ — output review #3.8 fix). On no-new-claims PASS, copy each of `H1_exec_brief.md`, `H2_delivery_packet.md`, `H3_validation_packet.md`, `H4_open_items_packet.md`, `handoff_manifest.json`, and `handoff_evidence_binding_map.csv` from `analysis/proposals/stage7_8/handoff/` to `analysis/handoff/`. The route is a byte-identical copy — the manifest's checksum (computed in step 4) remains valid post-route. Pre-v1.3.7 the handoff command stopped at step 5 and silently relied on the orchestrator to know the terminal location; downstream consumers (`/bsa-dev-handoff`, dashboard, backlog-bridge) found nothing at the documented `analysis/handoff/` paths because the routing step was implicit/missing.
7. Emit `handoff.ready.json` marker on success.

## Output

- With `--verbose`: full manifest field-by-field, full binding map row-by-row, full no-new-claims report summary.
- Without: summary — `Handoff pack assembled: H1-H4 + manifest + binding map (NN citations, M analyst_judgments). No-new-claims verdict: PASS. Digest <sha256-prefix>.`

## Failure modes

- **`stage8.no_new_claims.pass.json` missing**: refuse. Run `/bsa-stage 8 run` + `/bsa-audit no-new-claims` first.
- **Manifest schema validation fails**: surface the jsonschema error and refuse to emit `handoff.ready.json`. Usually indicates a regression in either h*_spec section content or the schema itself; escalate via a bug report.
- **Evidence binding map has orphan citations** (a `[C-xxx]` in H1-H4 that doesn't resolve to any A59 row): the manifest's `no_new_claims_verdict.verdict` is `FAIL` and the binding map includes the dangling entries. User must fix H1-H4 content and re-run.
- **Checksum mismatch on a second run** (e.g., after editing H1 by hand): expected — the checksum is over the current file bytes. Re-running `/bsa-handoff` recomputes and re-emits the manifest cleanly.

## Related

- H1/H4 content that uses `[AJ:C-xxx]` analyst-judgment tags requires the referenced A59 row to carry a `JustificationRationale` that references ≥ 1 upstream `ClaimID` different from its own (INV-07). The handoff-packager validates this as part of step 5; failure surfaces as a `no_new_claims_verdict.analyst_judgment_invalid` count > 0 and blocks the `handoff.ready` marker.
- The fixture `fixtures/golden/project_0001/expected_outputs/handoff/` is the canonical shape reference — use it to sanity-check a hand-produced pack against the expected structure.
