"""Schema-conformance tests for ``governance/schemas/a62.schema.json`` (Phase 3, US-S6-01).

First Phase-3 canonical artifact. Follows the same structure as the
Sprint-5 CSV schema tests (a51 / csv_artifacts): meta-validity,
positive cases, negative regression guards, CLI/dispatch integration.

The write-validator dispatcher was extended in the same commit — the
F5 hook now mechanically enforces A62 at write time, same as
A50/A51/A58/A59/A60. No new hook code needed; the infrastructure from
Sprint 5 absorbs this artifact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
A62_SCHEMA_PATH = REPO_ROOT / "governance" / "schemas" / "a62.schema.json"


@pytest.fixture(scope="module")
def a62_schema() -> dict:
    return json.loads(A62_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def a62_validator(a62_schema: dict) -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(a62_schema)


def _base_row() -> dict:
    return {
        "NFRID": "NFR-001",
        "NFRCategory": "performance",
        "Statement": "The triage agent SHALL respond within 500ms at p95 under 50 concurrent users.",
        "SourceClaimIDs": "C-042",
        "MeasurabilityType": "quantitative",
        "Metric": "p95 latency ms",
        "Target": "< 500",
        "TestabilityNotes": "k6 load test with 50 VUs against /triage endpoint.",
        "Criticality": "level-1",
        "A51Ref": "",
        "Notes": "",
    }


# ---- Meta ------------------------------------------------------------


def test_schema_meta_valid(a62_schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(a62_schema)


def test_required_subset_of_canonical_columns(a62_schema: dict) -> None:
    canonical = set(a62_schema["x-bsa-csv-columns-order"]["order"])
    required = set(a62_schema["required"])
    assert required.issubset(canonical)


def test_measurability_rules_extension_exposed(a62_schema: dict) -> None:
    """INV-09 cross-field rules live in x-bsa-measurability-rules for
    downstream validators to key on."""
    ext = a62_schema["x-bsa-measurability-rules"]
    assert "performance" in ext["quantitative_categories_requiring_metric_and_target"]
    assert "availability" in ext["quantitative_categories_requiring_metric_and_target"]
    assert "scalability" in ext["quantitative_categories_requiring_metric_and_target"]
    assert ext["testability_notes_required_for_all"] is True


def test_loader_iter_a62_rows_exists() -> None:
    from governance.schemas import loader

    assert hasattr(loader, "iter_a62_rows")


# ---- Positive cases --------------------------------------------------


@pytest.mark.parametrize(
    "category",
    ["performance", "availability", "scalability", "security", "usability",
     "compliance", "maintainability", "observability", "portability"],
)
def test_all_categories_accepted(
    a62_validator: "jsonschema.Draft202012Validator", category: str
) -> None:
    row = _base_row()
    row["NFRCategory"] = category
    errors = list(a62_validator.iter_errors(row))
    assert not errors, [e.message for e in errors]


def test_category_prefixed_nfrid_accepted(
    a62_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["NFRID"] = "NFR-PERF-001"
    errors = list(a62_validator.iter_errors(row))
    assert not errors


def test_multi_source_claims_accepted(
    a62_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["SourceClaimIDs"] = "C-001;C-042;C-PERF-007"
    errors = list(a62_validator.iter_errors(row))
    assert not errors


def test_qualitative_category_with_empty_metric_target_accepted(
    a62_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Qualitative NFR (compliance) may have empty Metric/Target —
    TestabilityNotes carries the verification path instead."""
    row = _base_row()
    row["NFRCategory"] = "compliance"
    row["MeasurabilityType"] = "qualitative"
    row["Metric"] = ""
    row["Target"] = ""
    row["TestabilityNotes"] = "SOC2 Control C-04 quarterly review + evidence in audit log."
    errors = list(a62_validator.iter_errors(row))
    assert not errors, [e.message for e in errors]


# ---- Negative cases --------------------------------------------------


def test_missing_source_claim_ids_rejected(
    a62_validator: "jsonschema.Draft202012Validator",
) -> None:
    """INV-08: NFR without SourceClaimIDs is drift — must be rejected."""
    row = _base_row()
    row["SourceClaimIDs"] = ""
    errors = list(a62_validator.iter_errors(row))
    assert errors
    err_text = " ".join(e.message for e in errors)
    assert "SourceClaimIDs" in err_text or "does not match" in err_text


def test_unknown_category_rejected(
    a62_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["NFRCategory"] = "fast-and-cheap"  # not in enum
    errors = list(a62_validator.iter_errors(row))
    assert errors


def test_empty_statement_rejected(
    a62_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["Statement"] = ""
    errors = list(a62_validator.iter_errors(row))
    assert errors


def test_empty_testability_notes_rejected(
    a62_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Every NFR needs a verification path — empty TestabilityNotes → rejected."""
    row = _base_row()
    row["TestabilityNotes"] = ""
    errors = list(a62_validator.iter_errors(row))
    assert errors


def test_unknown_measurability_type_rejected(
    a62_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["MeasurabilityType"] = "vibey"
    errors = list(a62_validator.iter_errors(row))
    assert errors


def test_unknown_criticality_rejected(
    a62_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["Criticality"] = "catastrophic"
    errors = list(a62_validator.iter_errors(row))
    assert errors


def test_malformed_nfrid_rejected(
    a62_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["NFRID"] = "NFR-001a"  # trailing letter
    errors = list(a62_validator.iter_errors(row))
    assert errors


def test_source_claim_id_with_wrong_prefix_rejected(
    a62_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["SourceClaimIDs"] = "X-042"  # not C-NNN
    errors = list(a62_validator.iter_errors(row))
    assert errors


# ---- F5 integration --------------------------------------------------


def test_write_validator_dispatches_a62_path() -> None:
    """F5 hook must route A62 writes through a62.schema.json."""
    from governance.schemas.write_validator import _dispatch

    result = _dispatch("analysis/canonical/core_controls/A62_nfr_register.csv")
    assert result is not None
    schema_name, _fn = result
    assert schema_name == "a62"


def test_write_validator_blocks_pilot1_style_nfr_drift() -> None:
    """Pre-F5, a Phase-3 skill emitting A62 without SourceClaimIDs
    would land without complaint. Post-F5 this MUST block at the
    hook. This is the forward-looking equivalent of the Pilot-1-class
    guard."""
    from governance.schemas.write_validator import validate_canonical_write

    drift_content = (
        "NFRID,NFRCategory,Statement,SourceClaimIDs,MeasurabilityType,"
        "Metric,Target,TestabilityNotes,Criticality,A51Ref,Notes\n"
        # Row without SourceClaimIDs (would be drift):
        'NFR-001,performance,"Fast please.",,quantitative,"p95 ms","< 500","load test",level-1,,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A62_nfr_register.csv", drift_content
    )
    assert not ok
    err_text = " ".join(msgs)
    assert "SourceClaimIDs" in err_text or "does not match" in err_text


def test_write_validator_accepts_valid_a62_content() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "NFRID,NFRCategory,Statement,SourceClaimIDs,MeasurabilityType,"
        "Metric,Target,TestabilityNotes,Criticality,A51Ref,Notes\n"
        'NFR-PERF-001,performance,"The API SHALL respond within 500ms at p95.",'
        'C-042,quantitative,"p95 latency ms","< 500",'
        '"k6 load test",level-1,,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A62_nfr_register.csv", content
    )
    assert ok, msgs
