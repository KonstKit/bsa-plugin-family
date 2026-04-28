"""Tests for A63 analyst-judgment register schema (v1.4.0).

Closes review #3.3. The A63 register tracks every A59 ClaimType=
analyst_judgment claim with hard-to-fake metadata (AnalystID +
EmittedAt + UpstreamClaimRefs + ValidationStatus). The schema enforces
field shapes + the new x-bsa-aj-validation-rules cross-field invariants
(peer-review fields required when ValidationStatus=peer_reviewed;
rejection rationale required when ValidationStatus=rejected).

Coverage:
  * Happy path: well-formed pending row passes.
  * Required-field violations (each of the 7 required fields).
  * AJID pattern (AJ-NNN with 3-4 digits).
  * ValidationStatus enum (3 values; reject anything else).
  * UpstreamClaimRefs ≥1 ClaimID + multi-valued shape.
  * Cross-field rule: ValidationStatus=peer_reviewed requires
    PeerReviewerID + PeerReviewedAt non-empty.
  * Cross-field rule: ValidationStatus=rejected requires Notes non-empty.
  * EmittedAt timestamp pattern.
  * additionalProperties: false (unknown fields rejected).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def schema() -> dict:
    p = REPO_ROOT / "governance" / "schemas" / "a63.schema.json"
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator(schema) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )


def _baseline_row() -> dict:
    return {
        "AJID": "AJ-001",
        "ClaimID": "C-042",
        "AnalystID": "operator-kk",
        "EmittedAt": "2026-04-28T10:00:00Z",
        "UpstreamClaimRefs": "C-001",
        "ValidationStatus": "pending",
        "Notes": "",
    }


# ---- Happy path --------------------------------------------------------


def test_baseline_pending_row_passes(validator) -> None:
    row = _baseline_row()
    errors = list(validator.iter_errors(row))
    assert not errors, f"baseline row rejected: {[e.message for e in errors]}"


def test_peer_reviewed_row_passes(validator) -> None:
    row = _baseline_row()
    row["ValidationStatus"] = "peer_reviewed"
    row["PeerReviewerID"] = "operator-other"
    row["PeerReviewedAt"] = "2026-04-28T11:00:00Z"
    row["Notes"] = "Reviewed; rationale sound."
    errors = list(validator.iter_errors(row))
    assert not errors, (
        f"peer-reviewed row rejected: {[e.message for e in errors]}"
    )


def test_rejected_row_passes_with_rationale(validator) -> None:
    row = _baseline_row()
    row["ValidationStatus"] = "rejected"
    row["PeerReviewerID"] = "operator-other"
    row["PeerReviewedAt"] = "2026-04-28T11:00:00Z"
    row["Notes"] = "AJ chains on another AJ; route via A51 instead."
    errors = list(validator.iter_errors(row))
    assert not errors


def test_multi_valued_upstream_claim_refs_pass(validator) -> None:
    row = _baseline_row()
    row["UpstreamClaimRefs"] = "C-001;C-002;C-003"
    errors = list(validator.iter_errors(row))
    assert not errors


# ---- Required-field violations -----------------------------------------


@pytest.mark.parametrize("field", [
    "AJID", "ClaimID", "AnalystID", "EmittedAt",
    "UpstreamClaimRefs", "ValidationStatus", "Notes",
])
def test_required_field_missing_rejected(validator, field) -> None:
    row = _baseline_row()
    del row[field]
    errors = list(validator.iter_errors(row))
    assert errors, f"missing {field} should be rejected"
    assert any(field in e.message for e in errors)


# ---- Pattern + enum violations -----------------------------------------


@pytest.mark.parametrize("bad_ajid", [
    "AJ-12",       # too few digits
    "AJ-12345",    # too many
    "AJ_001",      # underscore not hyphen
    "aj-001",      # lowercase
    "C-001",       # wrong prefix (looks like ClaimID)
])
def test_ajid_pattern_violation_rejected(validator, bad_ajid) -> None:
    row = _baseline_row()
    row["AJID"] = bad_ajid
    errors = list(validator.iter_errors(row))
    assert errors, f"AJID={bad_ajid!r} should be rejected"


@pytest.mark.parametrize("bad_status", [
    "approved",            # not in enum
    "Pending",             # case-sensitive
    "PEER_REVIEWED",       # case
    "",                    # empty
])
def test_validation_status_enum_violation_rejected(validator, bad_status) -> None:
    row = _baseline_row()
    row["ValidationStatus"] = bad_status
    errors = list(validator.iter_errors(row))
    assert errors


def test_unknown_property_rejected(validator) -> None:
    """additionalProperties: false should reject typo'd field names."""
    row = _baseline_row()
    row["AnalystId"] = "typo-id"  # camelCase typo of AnalystID
    errors = list(validator.iter_errors(row))
    assert errors


def test_empty_upstream_claim_refs_rejected(validator) -> None:
    row = _baseline_row()
    row["UpstreamClaimRefs"] = ""
    errors = list(validator.iter_errors(row))
    assert errors


def test_emitted_at_pattern_rejected(validator) -> None:
    row = _baseline_row()
    row["EmittedAt"] = "2026-04-28 10:00:00"  # space not T
    errors = list(validator.iter_errors(row))
    assert errors


# ---- Cross-field rules (x-bsa-aj-validation-rules) ---------------------


def test_aj_validation_rules_handler_imports() -> None:
    """The handler MUST be importable from write_validator (re-export)."""
    from governance.schemas.write_validator import _apply_aj_validation_rules
    assert callable(_apply_aj_validation_rules)


def test_peer_reviewed_without_reviewer_id_blocked() -> None:
    """ValidationStatus=peer_reviewed with empty PeerReviewerID
    is a cross-field rule violation."""
    from governance.schemas.write_validator import (
        _apply_aj_validation_rules,
    )
    row = _baseline_row()
    row["ValidationStatus"] = "peer_reviewed"
    row["PeerReviewerID"] = ""
    row["PeerReviewedAt"] = "2026-04-28T11:00:00Z"
    schema = {
        "x-bsa-aj-validation-rules": {
            "applies_to_all_rows": True,
            "rules": [
                {
                    "name": "peer_review_required_fields",
                    "when_status": "peer_reviewed",
                    "requires_non_empty": ["PeerReviewerID", "PeerReviewedAt"],
                }
            ],
        }
    }
    violations = _apply_aj_validation_rules(row, schema, 2)
    assert violations
    assert any("PeerReviewerID" in v for v in violations)


def test_rejected_without_notes_blocked() -> None:
    """ValidationStatus=rejected with empty Notes is a violation."""
    from governance.schemas.write_validator import (
        _apply_aj_validation_rules,
    )
    row = _baseline_row()
    row["ValidationStatus"] = "rejected"
    row["Notes"] = ""
    schema = {
        "x-bsa-aj-validation-rules": {
            "applies_to_all_rows": True,
            "rules": [
                {
                    "name": "rejection_rationale_required",
                    "when_status": "rejected",
                    "requires_non_empty": ["Notes"],
                }
            ],
        }
    }
    violations = _apply_aj_validation_rules(row, schema, 5)
    assert violations
    assert any("Notes" in v for v in violations)


def test_pending_status_does_not_trigger_peer_review_rule() -> None:
    """Pending rows should NOT trigger the peer-review rule (it's
    gated by when_status=peer_reviewed)."""
    from governance.schemas.write_validator import (
        _apply_aj_validation_rules,
    )
    row = _baseline_row()
    row["ValidationStatus"] = "pending"
    row["PeerReviewerID"] = ""  # legitimately empty for pending
    row["PeerReviewedAt"] = ""
    schema = {
        "x-bsa-aj-validation-rules": {
            "applies_to_all_rows": True,
            "rules": [
                {
                    "name": "peer_review_required_fields",
                    "when_status": "peer_reviewed",
                    "requires_non_empty": ["PeerReviewerID", "PeerReviewedAt"],
                }
            ],
        }
    }
    violations = _apply_aj_validation_rules(row, schema, 2)
    assert not violations


def test_handler_skips_when_extension_absent() -> None:
    """No x-bsa-aj-validation-rules in schema → handler no-ops."""
    from governance.schemas.write_validator import (
        _apply_aj_validation_rules,
    )
    row = _baseline_row()
    row["ValidationStatus"] = "rejected"  # would trigger rule if present
    violations = _apply_aj_validation_rules(row, {}, 2)
    assert not violations


# ---- Dispatcher integration --------------------------------------------


def test_dispatcher_routes_a63_csv_path() -> None:
    """validate_canonical_write should dispatch A63_*.csv to the a63 schema."""
    from governance.schemas.write_validator import _dispatch
    result = _dispatch(
        "analysis/canonical/core_controls/A63_analyst_judgment_register.csv"
    )
    assert result is not None
    schema_name, _ = result
    assert schema_name == "a63"


def test_dispatcher_routes_discovery_a63_csv_path() -> None:
    """Discovery zone A63 also dispatches."""
    from governance.schemas.write_validator import _dispatch
    result = _dispatch(
        "analysis/discovery/canonical/core_controls/A63_analyst_judgment_register.csv"
    )
    assert result is not None
    schema_name, _ = result
    assert schema_name == "a63"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
