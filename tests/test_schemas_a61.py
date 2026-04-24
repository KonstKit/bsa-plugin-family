"""Schema-conformance tests for ``governance/schemas/a61.schema.json`` (v1.2.7).

A61 is the canonical bridge between A59 evidence-bound claims and the
diagram sidecars (c4-plantuml-from-context + camunda-bpmn-from-context,
plus future DBML / sequence-diagram sidecars). Pre-v1.2.7 there was
no formal schema — the v1.2.6 sidecar e2e fixture documented this as
forward-looking. v1.2.7 closes that gap by adding:

- ``governance/schemas/a61.schema.json`` (Draft 2020-12).
- ``iter_a61_rows()`` in ``governance/schemas/loader.py``.
- A61 dispatcher entry in ``governance/schemas/write_validator.py``
  (pre-v1.2.7 A61 writes were silently allowed; post-v1.2.7 they are
  row-shape-validated at the F5 hook layer).

Test groups (mirroring the test_schemas_a51.py / test_schemas_csv_artifacts.py shape):

1. **Schema meta-validity** (Draft 2020-12).
2. **CSV reader** — column-set assertion via ``iter_a61_rows``.
3. **Positive cases** — every row in every golden fixture (today only
   project_0004_sidecar_e2e ships an A61 register; the test scopes to
   that fixture but uses a glob so future fixtures with A61 are
   automatically picked up).
4. **Negative cases** — common drift class is rejected:
   - AnchorID without the ``ANC-`` prefix.
   - SourceClaimID with the wrong prefix or shape.
   - Empty Label.
   - Missing required field.
   - AnchorKind containing illegal characters (whitespace, etc.).
5. **Foreign-key shape pin** — the ``x-bsa-foreign-keys`` block points
   at A59.ClaimID and is shaped consistently with a72.schema.json's
   FK block (pinned so a future refactor can't silently drop it).
6. **Dispatcher pin** — the F5 dispatcher routes
   ``analysis/canonical/core_controls/A61_anchor_map.csv`` to the
   ``a61`` schema validator (pre-v1.2.7 such writes were silently
   allowed; this regression pins the wire-up).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
A61_SCHEMA_PATH = REPO_ROOT / "governance" / "schemas" / "a61.schema.json"
FIXTURES_GLOB = (
    "fixtures/golden/*/expected_outputs/canonical/core_controls/"
    "A61_anchor_map.csv"
)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(A61_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator(schema: dict) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(schema)


# ---- Schema meta-validity -----------------------------------------


def test_a61_schema_is_valid_draft_2020_12(schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(schema)


def test_a61_schema_required_fields_match_x_bsa_csv_columns_order(schema: dict) -> None:
    """Required fields and the documented column order MUST match
    set-wise. Drift between them is the most common cause of producer
    /consumer disagreement on column ordering."""
    required = set(schema["required"])
    column_order = set(schema["x-bsa-csv-columns-order"]["order"])
    assert required == column_order, (
        f"required fields {required} != column order {column_order}; "
        f"drift would break producer/consumer agreement"
    )


def test_a61_schema_disallows_additional_properties(schema: dict) -> None:
    assert schema.get("additionalProperties") is False


# ---- Loader API ----------------------------------------------------


def test_iter_a61_rows_loads_fixture() -> None:
    from governance.schemas.loader import iter_a61_rows
    fixture = (
        REPO_ROOT
        / "fixtures"
        / "golden"
        / "project_0004_sidecar_e2e"
        / "expected_outputs"
        / "canonical"
        / "core_controls"
        / "A61_anchor_map.csv"
    )
    rows = list(iter_a61_rows(fixture))
    # v1.2.6 baseline = 10 anchors (5 C4 decl + 5 BPMN).
    # v1.2.9 added 2 C4 relationship anchors → 12.
    # v1.2.11 added 10 DBML anchors (2 tables + 6 cols + 1 ref + 1 enum) → 22.
    assert len(rows) == 22
    assert {r["AnchorID"] for r in rows} == {
        # v1.2.6 C4 declaration anchors
        "ANC-SYS-001", "ANC-ACTOR-001", "ANC-BOUNDARY-001",
        "ANC-CONTAINER-001", "ANC-CONTAINER-002",
        # v1.2.9 C4 relationship anchors (rel_<from>_to_<to> convention)
        "ANC-REL-001", "ANC-REL-002",
        # v1.2.6 BPMN anchors
        "ANC-EVT-001", "ANC-TASK-001", "ANC-FLOW-001",
        "ANC-FLOW-002", "ANC-EVT-002",
        # v1.2.11 DBML anchors
        "ANC-TABLE-001", "ANC-TABLE-002",
        "ANC-COLUMN-001", "ANC-COLUMN-002", "ANC-COLUMN-003",
        "ANC-COLUMN-004", "ANC-COLUMN-005", "ANC-COLUMN-006",
        "ANC-REF-001", "ANC-ENUM-001",
    }


# ---- Positive cases (every golden fixture row validates) ----------


def test_every_a61_row_in_every_golden_fixture_validates(
    validator: jsonschema.Draft202012Validator,
) -> None:
    from governance.schemas.loader import iter_a61_rows

    fixtures = sorted(REPO_ROOT.glob(FIXTURES_GLOB))
    assert fixtures, (
        f"no A61 fixtures found at {FIXTURES_GLOB}; v1.2.6 fixture "
        f"project_0004_sidecar_e2e/ should provide one"
    )

    for fixture_path in fixtures:
        rows = list(iter_a61_rows(fixture_path))
        for row_no, row in enumerate(rows, start=1):
            errors = list(validator.iter_errors(row))
            assert not errors, (
                f"{fixture_path.relative_to(REPO_ROOT)}:row {row_no} "
                f"({row.get('AnchorID', '?')}) failed schema validation: "
                f"{[e.message for e in errors]}"
            )


# ---- Negative cases (drift class is rejected) ---------------------


def _good_row() -> dict:
    return {
        "AnchorID": "ANC-SYS-001",
        "AnchorKind": "system",
        "SourceClaimID": "C-001",
        "Label": "Support-desk system",
        "Notes": "Primary system in scope",
    }


def test_negative_anchor_id_without_anc_prefix_is_rejected(
    validator: jsonschema.Draft202012Validator,
) -> None:
    row = _good_row()
    row["AnchorID"] = "SYS-001"  # missing ANC- prefix
    errors = list(validator.iter_errors(row))
    assert errors, "schema accepted AnchorID without ANC- prefix"


def test_negative_anchor_id_lowercase_is_rejected(
    validator: jsonschema.Draft202012Validator,
) -> None:
    row = _good_row()
    row["AnchorID"] = "anc-sys-001"  # lowercase forbidden by pattern
    errors = list(validator.iter_errors(row))
    assert errors, "schema accepted lowercase AnchorID"


def test_negative_source_claim_id_wrong_prefix_is_rejected(
    validator: jsonschema.Draft202012Validator,
) -> None:
    row = _good_row()
    row["SourceClaimID"] = "S-001"  # S- is for sources, not claims
    errors = list(validator.iter_errors(row))
    assert errors, "schema accepted SourceClaimID with wrong prefix"


def test_negative_source_claim_id_too_short_is_rejected(
    validator: jsonschema.Draft202012Validator,
) -> None:
    row = _good_row()
    row["SourceClaimID"] = "C-1"  # min 3 digits per A59 ClaimID pattern
    errors = list(validator.iter_errors(row))
    assert errors, "schema accepted SourceClaimID with <3 digits"


def test_negative_label_empty_is_rejected(
    validator: jsonschema.Draft202012Validator,
) -> None:
    row = _good_row()
    row["Label"] = ""  # minLength=1
    errors = list(validator.iter_errors(row))
    assert errors, "schema accepted empty Label"


def test_negative_missing_required_field_is_rejected(
    validator: jsonschema.Draft202012Validator,
) -> None:
    row = _good_row()
    del row["AnchorKind"]
    errors = list(validator.iter_errors(row))
    assert errors, "schema accepted row missing AnchorKind"


def test_negative_anchor_kind_with_whitespace_is_rejected(
    validator: jsonschema.Draft202012Validator,
) -> None:
    row = _good_row()
    row["AnchorKind"] = "system_ boundary"  # space in middle
    errors = list(validator.iter_errors(row))
    assert errors, "schema accepted AnchorKind with whitespace"


def test_negative_anchor_kind_starting_with_digit_is_rejected(
    validator: jsonschema.Draft202012Validator,
) -> None:
    row = _good_row()
    row["AnchorKind"] = "1stClass"  # pattern requires letter at start
    errors = list(validator.iter_errors(row))
    assert errors, "schema accepted AnchorKind starting with a digit"


def test_negative_extra_field_is_rejected(
    validator: jsonschema.Draft202012Validator,
) -> None:
    row = _good_row()
    row["UnexpectedColumn"] = "should be rejected"
    errors = list(validator.iter_errors(row))
    assert errors, (
        "schema accepted unknown column "
        "(additionalProperties=false should reject)"
    )


# ---- Positive cases for both sidecar conventions -------------------


@pytest.mark.parametrize("kind", [
    # C4-PlantUML conventions
    "Person", "System", "System_Boundary", "Container", "Component",
    "Deployment_Node", "Rel", "BiRel", "RelIndex",
    # BPMN conventions
    "startEvent", "endEvent", "task", "userTask", "serviceTask",
    "exclusiveGateway", "parallelGateway", "sequenceFlow", "messageFlow",
    "intermediateCatchEvent", "boundaryEvent",
    # Hypothetical future-sidecar conventions
    "table", "column", "fk_relation",  # DBML-like
    "actor", "lifeline", "activation",  # sequence-diagram-like
])
def test_anchor_kind_accepts_both_sidecar_conventions(
    validator: jsonschema.Draft202012Validator, kind: str,
) -> None:
    """A61 stays sidecar-agnostic by design — AnchorKind accepts BOTH
    C4 PascalCase and BPMN camelCase, plus future sidecar conventions
    (DBML / sequence-diagram). The strict per-kind enum lives downstream
    in each sidecar's anchor_manifest.schema.json (view_element_kind /
    element_kind). Spot-check that the loose pattern actually accepts
    representative kinds from each convention."""
    row = _good_row()
    row["AnchorKind"] = kind
    errors = list(validator.iter_errors(row))
    assert not errors, (
        f"schema rejected legitimate AnchorKind {kind!r}: "
        f"{[e.message for e in errors]}"
    )


# ---- Foreign-key shape pin ----------------------------------------


def test_x_bsa_foreign_keys_documents_a59_link_documentary_only(schema: dict) -> None:
    """A61.SourceClaimID is a FK into A59.ClaimID. The
    ``x-bsa-foreign-keys`` block documents the relationship for human
    + tooling readers but is NOT executed at the F5 hook layer in
    v1.2.7 — the executable FK rules use the differently-named
    extension ``x-bsa-foreign-key-rules`` (a72.schema.json). FK
    enforcement for A61 is a deferred follow-up release.

    This test pins the documentary block's SHAPE (so reviewers /
    follow-up-release tooling can rely on it being well-formed) AND
    pins the deferral (so the schema's ``_comment`` cannot drift
    silently from "documentary" to "executable" without a paired
    write_validator change)."""
    fks = schema.get("x-bsa-foreign-keys", {})
    assert "SourceClaimID" in fks
    sc = fks["SourceClaimID"]
    assert sc["table"] == "A59_claim_register.csv"
    assert sc["column"] == "ClaimID"
    assert "rationale" in sc and sc["rationale"]
    # Pin the documentary-vs-executable distinction so a future
    # rename to `x-bsa-foreign-key-rules` (executable) without
    # paired write_validator wire-up cannot silently land.
    assert "x-bsa-foreign-key-rules" not in schema, (
        "schema added the executable FK extension name "
        "(x-bsa-foreign-key-rules) — write_validator.py wire-up MUST "
        "land in the same release. See a72.schema.json for the "
        "executable pattern + write_validator.py:744 for the handler."
    )
    comment = fks.get("_comment", "").lower()
    assert "documentary" in comment, (
        "FK block _comment dropped the 'DOCUMENTARY ONLY' marker — "
        "either re-add it or land the executable wire-up."
    )


def test_a61_source_claim_id_pattern_matches_a59_claim_id_pattern(schema: dict) -> None:
    """v1.2.7 round-1 Codex recommendation #1: the A61.SourceClaimID
    pattern MUST stay byte-identical with A59.ClaimID. Drift between
    them would let a malformed ClaimID land in A61 even when A59's
    schema would have caught it (and vice versa). Pin so a future
    refactor to either schema cannot silently desync."""
    a59_schema_path = REPO_ROOT / "governance" / "schemas" / "a59.schema.json"
    a59 = json.loads(a59_schema_path.read_text(encoding="utf-8"))
    a59_claim_pattern = a59["properties"]["ClaimID"]["pattern"]
    a61_source_claim_pattern = schema["properties"]["SourceClaimID"]["pattern"]
    assert a59_claim_pattern == a61_source_claim_pattern, (
        f"A59.ClaimID pattern {a59_claim_pattern!r} != "
        f"A61.SourceClaimID pattern {a61_source_claim_pattern!r}. "
        f"Update both schemas in lockstep."
    )


# ---- Dispatcher wire-up pin ---------------------------------------


def test_dispatcher_routes_a61_csv_to_a61_validator() -> None:
    """The F5 dispatcher in write_validator.py MUST route
    analysis/canonical/core_controls/A61_*.csv to the ``a61`` schema.
    Pre-v1.2.7 such writes were silently allowed (no schema → no
    validator → no F5 enforcement); v1.2.7 wires the dispatcher."""
    from governance.schemas.write_validator import _DISPATCHER

    a61_routes = [
        (pat, tag) for (pat, tag, _validator) in _DISPATCHER
        if tag == "a61"
    ]
    assert len(a61_routes) == 1, (
        f"expected exactly one A61 dispatcher entry; got {len(a61_routes)}"
    )
    pattern, _tag = a61_routes[0]
    # Both main-cycle and discovery paths.
    assert pattern.search("analysis/canonical/core_controls/A61_anchor_map.csv")
    assert pattern.search(
        "workspace/analysis/discovery/canonical/core_controls/"
        "A61_anchor_map.csv"
    )
    # Must NOT match adjacent shapes.
    assert not pattern.search("analysis/canonical/core_controls/A61.csv")  # no _suffix
    assert not pattern.search("analysis/canonical/core_controls/A610_register.csv")  # numeric drift


def test_dispatcher_a61_validator_actually_rejects_bad_row() -> None:
    """End-to-end: feed a malformed A61 row + invoke the dispatcher's
    validator + assert it rejects. Pins the wire-up + the schema
    rejection together."""
    from governance.schemas.write_validator import validate_canonical_write

    # Row has SourceClaimID with wrong prefix (S- instead of C-).
    bad_csv = (
        "AnchorID,AnchorKind,SourceClaimID,Label,Notes\n"
        "ANC-SYS-001,system,S-001,Support-desk system,Primary system\n"
    )
    ok, findings = validate_canonical_write(
        "analysis/canonical/core_controls/A61_anchor_map.csv",
        bad_csv,
    )
    assert not ok, "dispatcher accepted A61 row with malformed SourceClaimID"
    assert findings, "dispatcher rejected the row but emitted no findings"
    # The rejection should mention SourceClaimID or the pattern.
    blob = " ".join(findings).lower()
    assert (
        "sourceclaimid" in blob or "pattern" in blob or "c-" in blob
    ), f"findings missed SourceClaimID-related signal: {findings}"


def test_dispatcher_a61_validator_accepts_good_row() -> None:
    """Counterpart to the bad-row test: a well-formed A61 row MUST
    flow through the dispatcher cleanly. Pins that the validator
    isn't accidentally rejecting valid input."""
    from governance.schemas.write_validator import validate_canonical_write

    good_csv = (
        "AnchorID,AnchorKind,SourceClaimID,Label,Notes\n"
        "ANC-SYS-001,system,C-001,Support-desk system,Primary system\n"
        "ANC-EVT-001,startEvent,C-003,Ticket intake,BPMN start event\n"
    )
    ok, findings = validate_canonical_write(
        "analysis/canonical/core_controls/A61_anchor_map.csv",
        good_csv,
    )
    assert ok, f"dispatcher rejected well-formed A61 row(s): {findings}"
    # validate_canonical_write returns (True, [info_message]) on
    # successful schema match — the info message names the matched
    # schema. Pin that we got an A61 info message, not silence
    # (silence would mean the dispatcher missed the path entirely).
    assert findings, (
        "dispatcher matched no schema for the A61 path — wire-up gap"
    )
    assert any("a61" in m.lower() for m in findings), (
        f"info message does not mention a61: {findings}"
    )


# ---- v1.2.8: x-bsa-anchor-binding-rules (executable cross-row) ----
#
# Closes the two cross-row deferrals from v1.2.7:
#   * SourceClaimID FK to A59.ClaimID
#   * AnchorID uniqueness across rows
#
# Each test sets up an in-memory canonical-layout workspace under
# tmp_path, writes a sibling A59 register with known ClaimIDs, then
# routes A61 content through validate_canonical_write to exercise
# the dispatcher → row-shape → cross-row chain end-to-end.

A59_SIBLING_HEADER = (
    "ClaimID,SourceID,ExcerptID,ClaimType,Statement,"
    "JustificationRationale,A51Ref,ClaimStrength,Criticality,Notes\n"
)

A59_SIBLING_BODY = (
    "C-001,S-001,E-001,direct,foo,,,0.85,level-2,\n"
    "C-002,S-001,E-002,direct,bar,,,0.85,level-2,\n"
    "C-003,S-002,E-003,direct,baz,,,0.85,level-2,\n"
    "C-004,S-002,E-004,direct,qux,,,0.85,level-2,\n"
)


def _make_canon_workspace(tmp_path: Path, with_a59: bool = True) -> Path:
    """Create a tmp canonical-layout workspace; return the A61 csv path
    (not yet written). Optionally writes a sibling A59 register so FK
    resolution has something to resolve against."""
    canon = tmp_path / "analysis" / "canonical" / "core_controls"
    canon.mkdir(parents=True, exist_ok=True)
    if with_a59:
        (canon / "A59_claim_register.csv").write_text(
            A59_SIBLING_HEADER + A59_SIBLING_BODY, encoding="utf-8",
        )
    return canon / "A61_anchor_map.csv"


def test_executable_anchor_binding_well_formed_passes(tmp_path: Path) -> None:
    """Sanity: a well-formed A61 with valid FKs + unique AnchorIDs
    passes the executable cross-row check end-to-end."""
    from governance.schemas.write_validator import validate_canonical_write
    a61_path = _make_canon_workspace(tmp_path)
    good = (
        "AnchorID,AnchorKind,SourceClaimID,Label,Notes\n"
        "ANC-SYS-001,system,C-001,System A,note\n"
        "ANC-EVT-001,startEvent,C-003,Event,note\n"
    )
    ok, msgs = validate_canonical_write(str(a61_path), good)
    assert ok, f"good A61 rejected: {msgs}"


def test_executable_anchor_binding_orphan_source_claim_id_rejected(
    tmp_path: Path,
) -> None:
    """An A61 row whose SourceClaimID does not exist in A59 MUST fail
    with a clear "does not resolve" violation. ART-VAL-001-07-style
    orphan guard, now executable at the F5 hook layer."""
    from governance.schemas.write_validator import validate_canonical_write
    a61_path = _make_canon_workspace(tmp_path)
    bad = (
        "AnchorID,AnchorKind,SourceClaimID,Label,Notes\n"
        "ANC-SYS-001,system,C-999,System,orphan claim\n"
    )
    ok, msgs = validate_canonical_write(str(a61_path), bad)
    assert not ok, f"orphan SourceClaimID accepted: {msgs}"
    assert any("does not resolve" in m for m in msgs), (
        f"expected 'does not resolve' violation; got: {msgs}"
    )
    assert any("C-999" in m for m in msgs)


def test_executable_anchor_binding_duplicate_anchor_id_rejected(
    tmp_path: Path,
) -> None:
    """Two A61 rows with the same AnchorID MUST fail with a clear
    "duplicate value" violation. Without this guard, two distinct
    claims would silently project to the same diagram element."""
    from governance.schemas.write_validator import validate_canonical_write
    a61_path = _make_canon_workspace(tmp_path)
    dup = (
        "AnchorID,AnchorKind,SourceClaimID,Label,Notes\n"
        "ANC-SYS-001,system,C-001,System A,first\n"
        "ANC-SYS-001,system,C-002,System B,duplicate id\n"
    )
    ok, msgs = validate_canonical_write(str(a61_path), dup)
    assert not ok, f"duplicate AnchorID accepted: {msgs}"
    dup_msgs = [m for m in msgs if "duplicate" in m.lower()]
    assert dup_msgs, f"expected duplicate-value violation; got: {msgs}"
    # The violation should name BOTH the duplicate value AND the
    # first-seen line so the operator can find both occurrences.
    assert any("ANC-SYS-001" in m for m in dup_msgs)
    assert any("first seen on line 2" in m for m in dup_msgs), (
        f"violation missed first-seen-line context: {dup_msgs}"
    )


def test_executable_anchor_binding_three_duplicates_emits_two_violations(
    tmp_path: Path,
) -> None:
    """When the same AnchorID appears 3 times, expect exactly 2
    violations (rows 3 + 4 each violate against the row-2 sighting).
    Pins that the duplicate detection is per-occurrence-after-first,
    not just one summary violation per duplicate value."""
    from governance.schemas.write_validator import validate_canonical_write
    a61_path = _make_canon_workspace(tmp_path)
    triple = (
        "AnchorID,AnchorKind,SourceClaimID,Label,Notes\n"
        "ANC-SYS-001,system,C-001,A,first\n"
        "ANC-SYS-001,system,C-002,B,2nd\n"
        "ANC-SYS-001,system,C-003,C,3rd\n"
    )
    ok, msgs = validate_canonical_write(str(a61_path), triple)
    assert not ok
    dup_msgs = [m for m in msgs if "duplicate" in m.lower()]
    assert len(dup_msgs) == 2, (
        f"expected 2 duplicate violations (rows 3 + 4); got {len(dup_msgs)}: "
        f"{dup_msgs}"
    )


def test_executable_anchor_binding_missing_a59_emits_per_row_sibling_violations(
    tmp_path: Path,
) -> None:
    """v1.2.8 round-1 Codex recommendation #1: when A59 is missing,
    EVERY A61 row with a non-blank SourceClaimID MUST emit a
    "sibling not readable" violation — pinned per-row, not just
    "at least one". This matches A72's per-row behavior + gives the
    operator the full scope of affected rows in one error report."""
    from governance.schemas.write_validator import validate_canonical_write
    # Don't write A59 — it's intentionally missing.
    a61_path = _make_canon_workspace(tmp_path, with_a59=False)
    content = (
        "AnchorID,AnchorKind,SourceClaimID,Label,Notes\n"
        "ANC-SYS-001,system,C-001,System,note\n"  # row 2 — non-blank
        "ANC-EVT-001,startEvent,C-003,Event,note\n"  # row 3 — non-blank
        "ANC-TASK-001,task,C-004,Task,note\n"  # row 4 — non-blank
    )
    ok, msgs = validate_canonical_write(str(a61_path), content)
    assert not ok, "A61 silently passed despite missing A59 sibling"
    sibling_msgs = [
        m for m in msgs
        if "missing or unreadable" in m or "sibling artifact" in m
    ]
    # Three rows, three non-blank SourceClaimIDs → exactly three
    # sibling-not-readable violations (one per row).
    assert len(sibling_msgs) == 3, (
        f"expected exactly 3 per-row sibling violations (one per "
        f"non-blank SourceClaimID row); got {len(sibling_msgs)}: "
        f"{sibling_msgs}"
    )
    # Each violation should reference its own row line + claim id.
    assert any("line 2" in m and "C-001" in m for m in sibling_msgs)
    assert any("line 3" in m and "C-003" in m for m in sibling_msgs)
    assert any("line 4" in m and "C-004" in m for m in sibling_msgs)


# ---- v1.2.8 round-1 Codex recommendation #2: malformed-extension
#       fail-CLOSED tests. Each pins that a partial / wrong-typed
#       executable extension surfaces a `<schema config>` violation
#       at the F5 hook layer rather than silently skipping FK
#       enforcement (the round-1 critical fail-open path).


def _make_a61_schema_with_partial_fk(table_only: bool, column_only: bool) -> dict:
    """Helper: return an in-memory A61 schema copy with a partially
    configured ``source_claim_id_resolves_in``. Caller picks which
    side is missing."""
    from governance.schemas.loader import load_schema
    schema = json.loads(json.dumps(load_schema("a61")))  # deep copy
    fk = {}
    if table_only:
        fk["table"] = "A59_claim_register.csv"
    if column_only:
        fk["column"] = "ClaimID"
    schema["x-bsa-anchor-binding-rules"]["source_claim_id_resolves_in"] = fk
    return schema


def _run_handler(schema: dict, rows: list[dict]) -> list[str]:
    """Helper: invoke `_apply_anchor_binding_rules` directly (bypassing
    the dispatcher) so the malformed-extension path is exercised
    independent of any specific path / sibling-cache state."""
    from governance.schemas.write_validator import (
        _apply_anchor_binding_rules,
    )
    # sibling_cache=None — these tests are about config-shape errors,
    # which surface BEFORE the cache is consulted.
    return _apply_anchor_binding_rules(rows, schema, "fake/path.csv", None)


def test_executable_anchor_binding_partial_fk_table_only_fail_closed() -> None:
    """v1.2.8 round-1 Codex critical: present-but-partial
    ``source_claim_id_resolves_in`` must NOT silently skip FK
    enforcement. Schema with only `table` set → `<schema config>`
    violation surfaces."""
    schema = _make_a61_schema_with_partial_fk(table_only=True, column_only=False)
    rows = [{"AnchorID": "ANC-X-001", "AnchorKind": "system",
             "SourceClaimID": "C-001", "Label": "L", "Notes": ""}]
    violations = _run_handler(schema, rows)
    config_violations = [v for v in violations if "<schema config>" in v]
    assert config_violations, (
        f"partial FK config (table-only) silently skipped — "
        f"fail-CLOSED expected. Got: {violations}"
    )
    assert any("column" in v for v in config_violations), (
        f"violation missed 'column' as the missing key: {config_violations}"
    )


def test_executable_anchor_binding_partial_fk_column_only_fail_closed() -> None:
    """Same critical, mirror case: only `column` set → fail-CLOSED."""
    schema = _make_a61_schema_with_partial_fk(table_only=False, column_only=True)
    rows = [{"AnchorID": "ANC-X-001", "AnchorKind": "system",
             "SourceClaimID": "C-001", "Label": "L", "Notes": ""}]
    violations = _run_handler(schema, rows)
    config_violations = [v for v in violations if "<schema config>" in v]
    assert config_violations
    assert any("table" in v for v in config_violations)


def test_executable_anchor_binding_fk_spec_wrong_type_fail_closed() -> None:
    """If `source_claim_id_resolves_in` is a string (not an object),
    that's also misconfig — fail-CLOSED with a clear message."""
    from governance.schemas.loader import load_schema
    schema = json.loads(json.dumps(load_schema("a61")))
    schema["x-bsa-anchor-binding-rules"]["source_claim_id_resolves_in"] = (
        "A59_claim_register.csv"  # wrong shape — should be an object
    )
    rows = [{"AnchorID": "ANC-X-001", "AnchorKind": "system",
             "SourceClaimID": "C-001", "Label": "L", "Notes": ""}]
    violations = _run_handler(schema, rows)
    config_violations = [v for v in violations if "<schema config>" in v]
    assert config_violations
    assert any("must be an object" in v for v in config_violations)


def test_executable_anchor_binding_non_string_table_fail_closed() -> None:
    """Field present but not a string (e.g., null / int) → fail-CLOSED."""
    from governance.schemas.loader import load_schema
    schema = json.loads(json.dumps(load_schema("a61")))
    schema["x-bsa-anchor-binding-rules"]["source_claim_id_resolves_in"] = {
        "table": None,  # null instead of string
        "column": "ClaimID",
    }
    rows = [{"AnchorID": "ANC-X-001", "AnchorKind": "system",
             "SourceClaimID": "C-001", "Label": "L", "Notes": ""}]
    violations = _run_handler(schema, rows)
    assert any("<schema config>" in v for v in violations), (
        f"non-string table silently accepted — fail-CLOSED expected. "
        f"Got: {violations}"
    )


def test_executable_anchor_binding_blank_source_claim_id_does_not_double_violate(
    tmp_path: Path,
) -> None:
    """Schema's per-row required check already rejects a blank
    SourceClaimID. The cross-row FK handler MUST NOT add a redundant
    "doesn't resolve" violation on top — that would noise the operator's
    output (e.g., a single missing cell would emit 2 messages, one
    per layer)."""
    from governance.schemas.write_validator import validate_canonical_write
    a61_path = _make_canon_workspace(tmp_path)
    bad = (
        "AnchorID,AnchorKind,SourceClaimID,Label,Notes\n"
        "ANC-SYS-001,system,,System,blank claim\n"
    )
    ok, msgs = validate_canonical_write(str(a61_path), bad)
    assert not ok  # schema-level required check rejects
    # Make sure the FK handler did NOT add a "does not resolve" message
    # — only the schema-level "required" / pattern violation should fire.
    fk_msgs = [m for m in msgs if "does not resolve" in m]
    assert not fk_msgs, (
        f"FK handler double-reported on blank SourceClaimID: {fk_msgs}"
    )


def test_executable_anchor_binding_outside_canonical_layout_no_ops(
    tmp_path: Path,
) -> None:
    """When the path is outside the canonical layout (e.g., the
    fixture's `expected_outputs/` mirror), the FK check no-ops
    silently — the dispatcher doesn't even match. Same convention
    as the A72 handler. Uniqueness check ALSO no-ops because the
    dispatcher never runs."""
    from governance.schemas.write_validator import validate_canonical_write
    # Path outside analysis/canonical/...
    bogus_path = str(tmp_path / "fixtures/golden/x/expected_outputs/A61_anchor_map.csv")
    content = (
        "AnchorID,AnchorKind,SourceClaimID,Label,Notes\n"
        "ANC-SYS-001,system,C-999,System,orphan but path outside canon\n"
        "ANC-SYS-001,system,C-001,Dup,duplicate but path outside canon\n"
    )
    ok, msgs = validate_canonical_write(bogus_path, content)
    # Outside-canon paths are not dispatched at all → unconditional pass
    # with no info message. Pin this so a future dispatcher loosening
    # that accidentally matches non-canonical paths surfaces.
    assert ok
    assert msgs == []


def test_executable_anchor_binding_v1_2_6_fixture_still_passes(
    tmp_path: Path,
) -> None:
    """Regression: the v1.2.6 sidecar e2e fixture's A61 register
    + A59 register together MUST validate cleanly through the v1.2.8
    executable rules. Copies both fixtures into a tmp canonical
    workspace + runs validate_canonical_write."""
    from governance.schemas.write_validator import validate_canonical_write
    src_root = REPO_ROOT / "fixtures" / "golden" / "project_0004_sidecar_e2e" / "expected_outputs" / "canonical" / "core_controls"
    a61_src = src_root / "A61_anchor_map.csv"
    a59_src = src_root / "A59_claim_register.csv"
    canon = tmp_path / "analysis" / "canonical" / "core_controls"
    canon.mkdir(parents=True, exist_ok=True)
    (canon / "A59_claim_register.csv").write_text(
        a59_src.read_text(encoding="utf-8"), encoding="utf-8",
    )
    a61_path = canon / "A61_anchor_map.csv"
    ok, msgs = validate_canonical_write(
        str(a61_path), a61_src.read_text(encoding="utf-8"),
    )
    assert ok, (
        f"v1.2.6 fixture rejected by v1.2.8 executable rules — "
        f"would break the existing e2e test: {msgs}"
    )


def test_executable_anchor_binding_extension_is_present_in_schema() -> None:
    """Static pin: the schema MUST declare the executable extension
    with applies_to_all_rows=true. Without this gate the handler
    would no-op even if the schema appears to declare the rules."""
    from governance.schemas.loader import load_schema
    schema = load_schema("a61")
    ext = schema.get("x-bsa-anchor-binding-rules")
    assert isinstance(ext, dict), "x-bsa-anchor-binding-rules block missing"
    assert ext.get("applies_to_all_rows") is True, (
        "applies_to_all_rows gate missing or false — handler would no-op"
    )
    fk_spec = ext.get("source_claim_id_resolves_in")
    assert isinstance(fk_spec, dict)
    assert fk_spec.get("table") == "A59_claim_register.csv"
    assert fk_spec.get("column") == "ClaimID"
    assert ext.get("unique_columns") == ["AnchorID"]
    # The _comment must explicitly say EXECUTABLE so a future revert
    # to documentary-only surfaces here.
    comment = ext.get("_comment", "").upper()
    assert "EXECUTABLE" in comment, (
        f"executable marker missing from _comment: "
        f"{ext.get('_comment', '')[:200]!r}"
    )
