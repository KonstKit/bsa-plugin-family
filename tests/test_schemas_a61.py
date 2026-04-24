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
    assert len(rows) == 10  # 5 C4 + 5 BPMN per the v1.2.6 fixture design
    assert {r["AnchorID"] for r in rows} == {
        "ANC-SYS-001", "ANC-ACTOR-001", "ANC-BOUNDARY-001",
        "ANC-CONTAINER-001", "ANC-CONTAINER-002",
        "ANC-EVT-001", "ANC-TASK-001", "ANC-FLOW-001",
        "ANC-FLOW-002", "ANC-EVT-002",
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
