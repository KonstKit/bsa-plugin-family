"""Schema-conformance + CSV-row tests for A50/A58/A59/A60 (F4d, Sprint 5).

Each canonical CSV gets the same four test groups already established
in test_schemas_marker.py / test_schemas_a48.py / test_schemas_a51.py:

  1. Schema meta-validity (Draft 2020-12).
  2. Helper API (iter_aNN_rows).
  3. Positive cases — every row in every golden fixture validates.
  4. Negative cases — Pilot-1 engagement drift class is rejected,
     specifically:
       * A59.ClaimType using the legacy strings policy_statement /
         factual_state / process_step / decision_pending.
       * A50.ReliabilityTier using ad-hoc labels like
         T1_multi_source_consistent (the engagement custom vocab).
       * Missing required fields, malformed IDs.

Plus the tier-to-claim-strength lookup smoke test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "governance" / "schemas"

ARTIFACTS = ("a50", "a58", "a59", "a60")
FIXTURE_FILES = {
    "a50": "A50_source_register.csv",
    "a58": "A58_evidence_excerpts.csv",
    "a59": "A59_claim_register.csv",
    "a60": "A60_negative_evidence_register.csv",
}
ITER_FUNCTIONS = {
    "a50": "iter_a50_rows",
    "a58": "iter_a58_rows",
    "a59": "iter_a59_rows",
    "a60": "iter_a60_rows",
}


@pytest.fixture(scope="module", params=ARTIFACTS)
def artifact(request) -> str:
    return request.param


@pytest.fixture(scope="module")
def schema(artifact: str) -> dict:
    return json.loads((SCHEMAS_DIR / f"{artifact}.schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator(schema: dict) -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(schema)


# ---- 1. Schema meta-validity (per-artifact) ---------------------------


def test_schema_is_valid_draft_2020_12(schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(schema)


def test_required_subset_of_canonical_columns(schema: dict, artifact: str) -> None:
    """Every required field must appear in x-bsa-csv-columns-order."""
    canonical = set(schema["x-bsa-csv-columns-order"]["order"])
    required = set(schema["required"])
    missing = required - canonical
    assert not missing, (
        f"{artifact}: required fields not in canonical column order: {missing}"
    )


# ---- 2. Helper API ----------------------------------------------------


def test_helper_function_exists(artifact: str) -> None:
    """Each artifact has a dedicated iter_aNN_rows helper in the loader."""
    from governance.schemas import loader

    fn_name = ITER_FUNCTIONS[artifact]
    assert hasattr(loader, fn_name), f"Loader missing {fn_name}"


def test_tier_to_claim_strength_returns_canonical_values() -> None:
    from governance.schemas.loader import tier_to_claim_strength

    assert tier_to_claim_strength("T1") == 1.00
    assert tier_to_claim_strength("T2") == 0.85
    assert tier_to_claim_strength("T3") == 0.65
    assert tier_to_claim_strength("T4") == 0.45
    assert tier_to_claim_strength("T5") == 0.20


def test_tier_to_claim_strength_rejects_drift_label() -> None:
    """Pilot-1-class 'T1_multi_source_consistent' must NOT resolve."""
    from governance.schemas.loader import tier_to_claim_strength

    with pytest.raises(KeyError, match="Unknown ReliabilityTier"):
        tier_to_claim_strength("T1_multi_source_consistent")


# ---- 3. Positive cases — golden fixtures ------------------------------


def test_all_golden_fixture_rows_validate(
    artifact: str,
    validator: "jsonschema.Draft202012Validator",
) -> None:
    """Every row in every committed fixture must pass schema validation."""
    from governance.schemas import loader

    fixture_filename = FIXTURE_FILES[artifact]
    iter_fn = getattr(loader, ITER_FUNCTIONS[artifact])
    failures: list[tuple[Path, int, list[str]]] = []
    fixtures_seen = 0
    for fixture_path in sorted(REPO_ROOT.glob(
        f"fixtures/golden/*/expected_outputs/canonical/core_controls/{fixture_filename}"
    )):
        fixtures_seen += 1
        for idx, row in enumerate(iter_fn(fixture_path), start=2):  # +2 for header
            errors = list(validator.iter_errors(row))
            if errors:
                failures.append((fixture_path, idx, [e.message for e in errors]))
    assert fixtures_seen >= 1, f"No fixtures found for {artifact}"
    assert not failures, (
        f"{artifact} fixture rows failed validation:\n"
        + "\n".join(f"  {p} line {i}: {msgs}" for p, i, msgs in failures)
    )


# ---- 4. Negative cases (the Pilot-1-class regression guards) -----------


def test_a59_rejects_legacy_claim_type_values() -> None:
    """A59 ClaimType using the Pilot-1 engagement legacy values
    (policy_statement / factual_state / process_step / decision_pending)
    MUST fail validation. This is the most-impactful negative test in
    the F4d set — it directly closes the drift class identified by the
    engagement review."""
    schema = json.loads((SCHEMAS_DIR / "a59.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    base_row = {
        "ClaimID": "C-001",
        "SourceID": "S-001",
        "ExcerptID": "E-001",
        "Statement": "Some statement",
        "JustificationRationale": "",
        "A51Ref": "",
        "ClaimStrength": "0.85",
        "Criticality": "level-2",
        "Notes": "",
    }
    for legacy_value in ("policy_statement", "factual_state", "process_step", "decision_pending", "boundary_statement"):
        bad_row = {**base_row, "ClaimType": legacy_value}
        errors = list(v.iter_errors(bad_row))
        assert errors, f"Legacy ClaimType {legacy_value!r} not rejected"


def test_a59_accepts_inv07_enum_values() -> None:
    schema = json.loads((SCHEMAS_DIR / "a59.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    base_row = {
        "ClaimID": "C-001",
        "SourceID": "S-001",
        "ExcerptID": "E-001",
        "Statement": "Some statement",
        "JustificationRationale": "",
        "A51Ref": "",
        "ClaimStrength": "0.85",
        "Criticality": "level-2",
        "Notes": "",
    }
    for valid_value in ("direct", "inference", "analyst_judgment"):
        row = {**base_row, "ClaimType": valid_value}
        errors = list(v.iter_errors(row))
        assert not errors, f"Valid ClaimType {valid_value!r} rejected: {[e.message for e in errors]}"


def test_a50_rejects_drift_tier_label() -> None:
    """Pilot-1 engagement custom-tier labels (T1_multi_source_consistent etc.)
    must fail the A50.ReliabilityTier enum."""
    schema = json.loads((SCHEMAS_DIR / "a50.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    bad_row = {
        "SourceID": "S-001",
        "SourceType": "document",
        "Title": "Test",
        "Origin": "/tmp/test.md",
        "AccessStatus": "readable",
        "ReliabilityTier": "T1_multi_source_consistent",  #  Pilot-1 drift
        "Priority": "medium",
        "Language": "en",
        "DateOrVersion": "2026-04-20",
        "Notes": "",
    }
    errors = list(v.iter_errors(bad_row))
    assert errors


def test_a50_accepts_canonical_tiers() -> None:
    schema = json.loads((SCHEMAS_DIR / "a50.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    base_row = {
        "SourceID": "S-001",
        "SourceType": "document",
        "Title": "Test",
        "Origin": "/tmp/test.md",
        "AccessStatus": "readable",
        "Priority": "medium",
        "Language": "en",
        "DateOrVersion": "2026-04-20",
        "Notes": "",
    }
    for tier in ("T1", "T2", "T3", "T4", "T5"):
        row = {**base_row, "ReliabilityTier": tier}
        errors = list(v.iter_errors(row))
        assert not errors, f"Valid tier {tier} rejected"


def test_a58_rejects_empty_locator() -> None:
    schema = json.loads((SCHEMAS_DIR / "a58.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    bad_row = {
        "ExcerptID": "E-001",
        "SourceID": "S-001",
        "Locator": "",  # locator-less excerpts cannot be re-verified
        "ExcerptText": "some text",
        "Notes": "",
    }
    errors = list(v.iter_errors(bad_row))
    assert errors


def test_a58_rejects_orphan_excerpt_no_source() -> None:
    """A58 row without SourceID is rejected — every excerpt must trace back to a source."""
    schema = json.loads((SCHEMAS_DIR / "a58.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    bad_row = {
        "ExcerptID": "E-001",
        "SourceID": "",  # empty
        "Locator": "p.42",
        "ExcerptText": "some text",
        "Notes": "",
    }
    errors = list(v.iter_errors(bad_row))
    assert errors


def test_a59_claim_strength_pattern_accepts_canonical_tiers() -> None:
    """ClaimStrength CSV values follow tier-derived strings."""
    schema = json.loads((SCHEMAS_DIR / "a59.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    base_row = {
        "ClaimID": "C-001",
        "SourceID": "S-001",
        "ExcerptID": "E-001",
        "ClaimType": "direct",
        "Statement": "test",
        "JustificationRationale": "",
        "A51Ref": "",
        "Criticality": "level-2",
        "Notes": "",
    }
    for cs in ("0.0", "0.20", "0.45", "0.65", "0.85", "1.00"):
        row = {**base_row, "ClaimStrength": cs}
        errors = list(v.iter_errors(row))
        assert not errors, f"ClaimStrength {cs} rejected: {[e.message for e in errors]}"


def test_a60_negative_finding_required_non_empty() -> None:
    schema = json.loads((SCHEMAS_DIR / "a60.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    bad_row = {
        "NegEvID": "N-001",
        "SourceID": "S-001",
        "ExcerptRef": "p.10",
        "RelatedClaimID": "C-001",
        "NegativeFinding": "",  # empty
        "A51Ref": "",
        "Notes": "",
    }
    errors = list(v.iter_errors(bad_row))
    assert errors


def test_csv_iter_helpers_assert_column_set() -> None:
    """Each iter_aNN_rows helper raises ValueError if the CSV's column
    set does not match the schema's canonical order."""
    import tempfile
    from governance.schemas import loader

    for artifact_name in ARTIFACTS:
        fn = getattr(loader, ITER_FUNCTIONS[artifact_name])
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
            fh.write("wrong,columns\n")
            fh.write("1,2\n")
            tmpname = fh.name
        try:
            with pytest.raises(ValueError, match="missing columns|unexpected columns"):
                list(fn(Path(tmpname)))
        finally:
            Path(tmpname).unlink(missing_ok=True)
