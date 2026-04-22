"""Schema-conformance tests for ``governance/schemas/a72.schema.json`` (Phase 3, US-S8-02).

Fourth Phase-3 canonical artifact (after A62 + A70 + A71). Same
structural pattern as test_schemas_a71.py: meta-validity, positive
cases across parametrized variations, negative regression guards,
F5 write-validator dispatch integration, marker-schema sync,
H-sec-4 binding.

Cross-field rules covered:
  - x-bsa-deferral-rules with status_field='LinkType' override
    (LinkType == 'a51-routed' → A51Ref required) — same generalized
    `_apply_deferral_rules` handler as A71; tests pin both halves
    of the configurable contract here.
  - x-bsa-foreign-key-rules — DOCUMENTARY only at this layer;
    executable enforcement is bsa-traceability-matrix's own
    output validator (cross-artifact A50/A59/A70 lookup outside
    F5 path-bound dispatch).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
A72_SCHEMA_PATH = REPO_ROOT / "governance" / "schemas" / "a72.schema.json"


@pytest.fixture(scope="module")
def a72_schema() -> dict:
    return json.loads(A72_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def a72_validator(a72_schema: dict) -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(a72_schema)


def _base_row() -> dict:
    """Minimal valid A72 row — direct claim-source link for one story."""
    return {
        "TraceID": "TR-001",
        "StoryID": "STORY-001",
        "ClaimID": "C-042",
        "SourceID": "S-001",
        "LinkType": "direct",
        "LinkStrength": "high",
        "A51Ref": "",
        "Notes": "",
    }


# ---- Meta ------------------------------------------------------------


def test_schema_meta_valid(a72_schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(a72_schema)


def test_required_subset_of_canonical_columns(a72_schema: dict) -> None:
    canonical = set(a72_schema["x-bsa-csv-columns-order"]["order"])
    required = set(a72_schema["required"])
    assert required == canonical, (
        f"For A72 every canonical column is required (no optional cells "
        f"in the matrix register). required - canonical = "
        f"{required - canonical}; canonical - required = "
        f"{canonical - required}"
    )


def test_deferral_rules_extension_uses_linktype_override(a72_schema: dict) -> None:
    """Pin x-bsa-deferral-rules shape — A72 overrides status_field
    from the default 'AutomationStatus' (A71) to 'LinkType'."""
    ext = a72_schema["x-bsa-deferral-rules"]
    assert ext["status_field"] == "LinkType", (
        f"A72 must override status_field to LinkType; got {ext.get('status_field')!r}"
    )
    assert ext["requires_a51_when_status"] == "a51-routed"


def test_foreign_key_rules_extension_exposed(a72_schema: dict) -> None:
    """x-bsa-foreign-key-rules is DOCUMENTARY at the schema layer
    today (cross-artifact lookups deferred to skill self-validation).
    Pin shape so a future schema edit can't silently drop it.

    Round-2 fix: applies_to_all_rows=true is explicit pin against
    re-introducing a LinkType-class exemption (e.g., letting
    'a51-routed' rows skip FK/consistency checks)."""
    ext = a72_schema["x-bsa-foreign-key-rules"]
    assert ext["applies_to_all_rows"] is True, (
        "applies_to_all_rows must be exactly True — any future "
        "loosening that exempts a LinkType class from FK/consistency "
        "would be a contract regression."
    )
    assert ext["story_id_resolves_in"] == "A70_story_register.csv"
    assert ext["claim_id_resolves_in"] == "A59_claim_register.csv"
    assert ext["source_id_resolves_in"] == "A50_source_register.csv"
    assert ext["claim_source_consistency"] is True
    assert "rationale" in ext


def test_loader_iter_a72_rows_exists() -> None:
    from governance.schemas import loader

    assert hasattr(loader, "iter_a72_rows")


# ---- Positive cases --------------------------------------------------


def test_baseline_valid_row_passes(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    errors = list(a72_validator.iter_errors(_base_row()))
    assert not errors, [e.message for e in errors]


def test_all_link_types_accepted(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    """LinkType enum is intentionally narrow at 3 values — direct,
    nfr-mediated, a51-routed. Round-2 fix dropped the original
    'inferred' value because it would have implied duplicate rows
    for the same (Story, ClaimID, SourceID) triple (when the trace
    is reachable both directly and via NFR), violating the row-
    identity contract."""
    for link_type in ("direct", "nfr-mediated", "a51-routed"):
        row = _base_row()
        row["LinkType"] = link_type
        # 'a51-routed' must co-populate A51Ref (skill / write_validator
        # responsibility); other types pass standalone at the schema layer.
        if link_type == "a51-routed":
            row["A51Ref"] = "A51-DEC-001"
        errors = list(a72_validator.iter_errors(row))
        assert not errors, (
            f"LinkType={link_type} rejected: {[e.message for e in errors]}"
        )


def test_inferred_link_type_intentionally_dropped(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Round-2 fix pin: the 'inferred' value MUST NOT be in the enum
    (would re-enable duplicate-row drift). If a future schema edit
    re-adds it, this test fails and forces a deliberate decision."""
    row = _base_row()
    row["LinkType"] = "inferred"
    errors = list(a72_validator.iter_errors(row))
    assert errors, (
        "LinkType='inferred' must be rejected — re-adding it would "
        "violate the row-identity contract (one row per (Story, "
        "ClaimID, SourceID) triple)."
    )


def test_all_link_strengths_accepted(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    for strength in ("high", "medium", "low"):
        row = _base_row()
        row["LinkStrength"] = strength
        errors = list(a72_validator.iter_errors(row))
        assert not errors


def test_category_prefixed_trace_id_accepted(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    for tid in ("TR-002", "TR-OPS-001", "TR-PERF-9999", "TR-99999"):
        row = _base_row()
        row["TraceID"] = tid
        errors = list(a72_validator.iter_errors(row))
        assert not errors, f"TraceID={tid!r} rejected"


def test_5_digit_trace_id_accepted(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Headroom for large engagements where a single Story may fan out
    to dozens of traces and the matrix grows past TR-999."""
    row = _base_row()
    row["TraceID"] = "TR-12345"
    errors = list(a72_validator.iter_errors(row))
    assert not errors


def test_multiple_a51_refs_accepted(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["LinkType"] = "a51-routed"
    row["A51Ref"] = "A51-DEC-001;A51-INF-099"
    errors = list(a72_validator.iter_errors(row))
    assert not errors


# ---- Negative cases --------------------------------------------------


def test_missing_story_id_rejected(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    """StoryID is required + pattern-constrained; empty string fails."""
    row = _base_row()
    row["StoryID"] = ""
    errors = list(a72_validator.iter_errors(row))
    assert errors, "empty StoryID was not rejected"


def test_malformed_story_id_rejected(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["StoryID"] = "user-story-1"
    errors = list(a72_validator.iter_errors(row))
    assert errors


def test_multi_story_rejected(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    """StoryID is SINGULAR — composite trace rows are forbidden."""
    row = _base_row()
    row["StoryID"] = "STORY-001;STORY-002"
    errors = list(a72_validator.iter_errors(row))
    assert errors


def test_multi_claim_rejected(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    """ClaimID is SINGULAR — same discipline as StoryID."""
    row = _base_row()
    row["ClaimID"] = "C-001;C-002"
    errors = list(a72_validator.iter_errors(row))
    assert errors


def test_multi_source_rejected(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    """SourceID is SINGULAR — one source per row."""
    row = _base_row()
    row["SourceID"] = "S-001;S-002"
    errors = list(a72_validator.iter_errors(row))
    assert errors


def test_unknown_link_type_rejected(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["LinkType"] = "implied"  # not in enum
    errors = list(a72_validator.iter_errors(row))
    assert errors


def test_unknown_link_strength_rejected(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["LinkStrength"] = "uncertain"
    errors = list(a72_validator.iter_errors(row))
    assert errors


def test_malformed_trace_id_rejected(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["TraceID"] = "trace-001"
    errors = list(a72_validator.iter_errors(row))
    assert errors


def test_malformed_a51ref_rejected(
    a72_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["A51Ref"] = "issue-42"
    errors = list(a72_validator.iter_errors(row))
    assert errors


# ---- F5 write-validator dispatch integration -------------------------


def test_dispatcher_routes_a72_path() -> None:
    from governance.schemas.write_validator import _dispatch

    result = _dispatch("analysis/canonical/core_controls/A72_traceability_matrix.csv")
    assert result is not None
    schema_name, _fn = result
    assert schema_name == "a72"


def test_dispatcher_routes_discovery_a72_path() -> None:
    from governance.schemas.write_validator import _dispatch

    result = _dispatch(
        "analysis/discovery/canonical/core_controls/A72_traceability_matrix.csv"
    )
    assert result is not None
    schema_name, _fn = result
    assert schema_name == "a72"


def test_write_validator_accepts_valid_a72_content() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "TraceID,StoryID,ClaimID,SourceID,LinkType,LinkStrength,A51Ref,Notes\n"
        "TR-001,STORY-001,C-042,S-001,direct,high,,\n"
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv",
        content,
    )
    assert ok, msgs


def test_write_validator_blocks_a72_a51_routed_without_a51() -> None:
    """x-bsa-deferral-rules with status_field=LinkType — a51-routed
    rows MUST co-populate A51Ref. Tests that the GENERIC handler
    correctly reads the status_field override (instead of falling
    back to the AutomationStatus default used by A71)."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "TraceID,StoryID,ClaimID,SourceID,LinkType,LinkStrength,A51Ref,Notes\n"
        'TR-001,STORY-001,C-042,S-001,a51-routed,low,,"deferred trace"\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv",
        content,
    )
    assert not ok
    err_text = " ".join(msgs)
    assert "A51Ref" in err_text
    assert "a51-routed" in err_text or "LinkType" in err_text


def test_write_validator_accepts_a72_a51_routed_with_a51() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "TraceID,StoryID,ClaimID,SourceID,LinkType,LinkStrength,A51Ref,Notes\n"
        'TR-001,STORY-001,C-042,S-001,a51-routed,low,A51-DEC-001,"deferred trace"\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv",
        content,
    )
    assert ok, msgs


def test_write_validator_blocks_a72_missing_story_id() -> None:
    """Schema-level: empty StoryID fails the singular pattern."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "TraceID,StoryID,ClaimID,SourceID,LinkType,LinkStrength,A51Ref,Notes\n"
        "TR-001,,C-042,S-001,direct,high,,\n"
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv",
        content,
    )
    assert not ok
    assert "StoryID" in " ".join(msgs)


# ---- Marker schema sync (phase3.traceability.pass) ------------------


def test_marker_schema_includes_phase3_traceability_pass() -> None:
    """US-S8-02 incidental: phase3.traceability.pass must be in the
    marker alphabet now that bsa-traceability-matrix is real."""
    from governance.schemas import loader

    alphabet = loader.marker_id_alphabet()
    assert "phase3.traceability.pass" in alphabet


def test_marker_schema_includes_phase3_traceability_stage() -> None:
    from governance.schemas import loader

    schema = loader.load_schema("marker")
    stage_enum = schema["properties"]["stage"]["enum"]
    assert "phase3.traceability" in stage_enum


def test_h_sec_4_binds_phase3_traceability_marker_to_stage_and_verdict() -> None:
    """Sprint 8 US-S8-02 incidental: the patterned-match in
    `_expected_stage_verdict` (added at US-S8-01 round 3) for
    `^phase3\\.([a-z_]+)\\.pass$` must already cover the new
    `phase3.traceability.pass` marker — no code change required.
    Pin so a future refactor that drops the patterned-match (or
    narrows it to specific subs) fails loudly."""
    from governance.schemas.write_validator import validate_canonical_write

    drifted = {
        "marker_id": "phase3.traceability.pass",
        "stage": "stage1",   # wrong
        "verdict": "READY",  # wrong
        "timestamp": "2026-04-22T17:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, _msgs = validate_canonical_write(
        "analysis/runtime/ready/phase3.traceability.pass.json",
        json.dumps(drifted),
    )
    assert not ok, "H-sec-4 must reject stage/verdict drift on phase3.traceability"

    correct = {
        "marker_id": "phase3.traceability.pass",
        "stage": "phase3.traceability",
        "verdict": "PASS",
        "timestamp": "2026-04-22T17:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/phase3.traceability.pass.json",
        json.dumps(correct),
    )
    assert ok, msgs
