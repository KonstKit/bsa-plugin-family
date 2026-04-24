# project_0004_sidecar_e2e — End-to-End Sidecar Fixture

**Purpose:** close the open follow-up at `docs/sidecar_inventory.md`
("End-to-end test fixture that exercises an orchestrated sidecar
invocation against a `project_NNNN/` happy-path fixture") by shipping
the first golden fixture that exercises the full A61-anchor → manifest
→ view-file cross-product for both stable sidecars
(`c4-plantuml-from-context` and `camunda-bpmn-from-context`).

Pre-v1.2.6 the sidecars had isolated tests:
- `tests/test_sidecar_anchor_manifest_schema.py` — schema-shape only.
- `tests/test_sidecar_f5_boundary.py` — F5/POLICY_GLOBS boundary only.
- `tests/test_sidecar_registry.py` — registry-lint contract.

What was missing: a single end-to-end pass that took a real-shaped A61
register, a real-shaped sidecar manifest pointing back at it, and a
real view file (`.puml` / `.bpmn`) referencing the manifest's element
IDs, then walked the full chain and asserted every cross-reference
resolved. That's what this fixture + the companion
`tests/test_sidecar_e2e_fixture.py` provide.

## Scope

This is **synthetic** (hand-authored, not the output of a live model
run). It's the smallest workspace that exercises:

| Surface | What's covered |
|---------|----------------|
| A50 source register | 2 sources (one architecture note, one process narrative) |
| A58 evidence excerpts | 4 excerpts (2 per source) |
| A59 claim register | 4 claims (each excerpt → one claim, each direct) |
| A61 anchor map | 10 anchors (5 C4 anchors + 5 BPMN anchors) |
| C4 sidecar | 1 view file (system_context.puml) + manifest mapping all 5 view elements to A61 |
| BPMN sidecar | 1 view file (ticket_intake.bpmn) + manifest mapping all 5 BPMN elements (start event + task + 2 sequence flows + end event) to A61 |

A61 deliberately covers BOTH sidecars from a single canonical register
(matches the sidecar-integration contract: A61 is the single source of
truth, sidecars consume from it).

## What the test pins

`tests/test_sidecar_e2e_fixture.py` walks this fixture and asserts:

1. **A61 register loads cleanly** (header + per-row validation).
2. **C4 manifest validates against the per-sidecar JSON Schema.**
3. **C4 manifest cross-refs:** every `a61_anchor_id` in the manifest
   exists as a row in the A61 register (no unmapped IDs).
4. **C4 view-file cross-refs:** every C4 macro in the `.puml` source
   that the integration contract calls "view element" appears in the
   manifest's `anchor_map` (no orphan view elements).
5. **BPMN side:** same three cross-checks against `.bpmn` + BPMN
   manifest + same A61 register.
6. **Negative-path regression pins** (each calls the SAME helper as
   the corresponding positive test, so weakening the positive can
   never silently green the negative):
   - Mutating a manifest entry's `a61_anchor_id` to a non-existent ID
     → cross-ref helper surfaces it as unmapped.
   - Dropping one anchor_map entry → view-element helper surfaces
     the corresponding `.puml` element as an orphan.
   - Mutating the C4 manifest's `sidecar` field to the BPMN literal
     → schema-validation helper raises (proves the schema check is
     doing real work, not just JSON parsing).
   - Mutating `generated_at` to a non-RFC-3339 string → format-checker
     helper raises (proves the custom `date-time` checker is wired in;
     `jsonschema.FormatChecker()` does not check `date-time` by
     default — it depends on optional rfc3339 libs).

This is the "orchestrator integration drift" guard called out at
`docs/sidecar_inventory.md` line 108 (pre-v1.2.6 wording): a future
refactor that breaks the sidecar's manifest emission contract, or
the per-sidecar schema, or the cross-reference back to A61, surfaces
here on the next pytest run.

## What this fixture does NOT cover

- Live sidecar invocation (no Claude in the loop). The fixture
  represents what an orchestrated sidecar pass would emit; the test
  walks that representation. A live-run fixture would be a separate
  Sprint 4.5+ deliverable.
- ~~A61 schema enforcement at the F5 hook layer.~~ — **CLOSED in
  v1.2.7.** `governance/schemas/a61.schema.json` (Draft 2020-12)
  pins the row shape (AnchorID + AnchorKind + SourceClaimID + Label
  + Notes); `iter_a61_rows()` lives in `governance/schemas/loader.py`;
  the F5 dispatcher in `governance/schemas/write_validator.py` routes
  `analysis/canonical/core_controls/A61_*.csv` to the new validator.
  This fixture's A61 register validates against the v1.2.7 schema —
  see `test_fixture_a61_validates_against_a61_schema` in
  `tests/test_sidecar_e2e_fixture.py`.
- ~~**Relationship coverage** for C4 (`Rel`, `BiRel`, `RelIndex`).~~
  — **CLOSED in v1.2.9.** The relationship `view_element_id` convention
  is now documented in
  `skills/c4-plantuml-from-context/references/integration-contract.md`
  §"Relationship view_element_id convention" — derived deterministically
  as `rel_<from>_<connector>_<to>` with `__N` suffix for multi-
  occurrence same-pair cases. The fixture's `.puml` now ships two
  `Rel(...)` calls, both mapped to A61 (ANC-REL-001 + ANC-REL-002)
  and pinned by the manifest's `anchor_map`. The e2e test's
  `_load_c4_view_elements` extractor now uses `_derive_c4_relationship_ids`
  to apply the v1.2.9 convention.
- DBML / sequence-diagram sidecars (the third / fourth sidecars
  remain on the post-v1.1.x roadmap).
