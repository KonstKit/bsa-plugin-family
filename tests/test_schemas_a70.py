"""Schema-conformance tests for ``governance/schemas/a70.schema.json`` (Phase 3, US-S7-01).

Second Phase-3 canonical artifact (after A62). Same structural pattern
as test_schemas_a62.py / test_schemas_a51.py: meta-validity, positive
cases across parametrized variations, negative regression guards,
F5 write-validator dispatch integration.

Special attention: INV-08 provenance rule (SourceClaimIDs OR
RelatedNFRIDs non-empty) and INVEST-A51 coupling. These are cross-
field rules outside the comfort zone of pure JSON Schema for CSV
semantics; tests here document the schema-level surface + leave the
cross-field enforcement to the skill's output validator (which has
access to both fields simultaneously).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
A70_SCHEMA_PATH = REPO_ROOT / "governance" / "schemas" / "a70.schema.json"


@pytest.fixture(scope="module")
def a70_schema() -> dict:
    return json.loads(A70_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def a70_validator(a70_schema: dict) -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(a70_schema)


def _base_row() -> dict:
    return {
        "StoryID": "STORY-001",
        "Title": "Triage Agent receives order-timeout escalation",
        "Persona": "Triage Ops Lead",
        "StoryText": (
            "As a Triage Ops Lead, I want an order-timeout escalation card to appear within "
            "2 seconds, so that I can reassign the order before SLA breach."
        ),
        "AcceptanceCriteria": (
            "Escalation card appears < 2s of order timeout; card shows order ID + last-known status; "
            "reassignment action is one click."
        ),
        "SourceClaimIDs": "C-042;C-045",
        "RelatedNFRIDs": "NFR-PERF-001",
        "Priority": "level-1",
        "EstimationHint": "m",
        "INVESTStatus": "pass",
        "A51Ref": "",
        "Notes": "",
    }


# ---- Meta ------------------------------------------------------------


def test_schema_meta_valid(a70_schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(a70_schema)


def test_required_subset_of_canonical_columns(a70_schema: dict) -> None:
    canonical = set(a70_schema["x-bsa-csv-columns-order"]["order"])
    required = set(a70_schema["required"])
    assert required.issubset(canonical)


def test_provenance_rules_extension_exposed(a70_schema: dict) -> None:
    """INV-08 (one-of provenance fields) lives in x-bsa-provenance-rules."""
    ext = a70_schema["x-bsa-provenance-rules"]
    assert set(ext["at_least_one_of_non_empty"]) == {"SourceClaimIDs", "RelatedNFRIDs"}


def test_invest_rules_extension_exposed(a70_schema: dict) -> None:
    """INVEST-A51 coupling lives in x-bsa-invest-rules."""
    ext = a70_schema["x-bsa-invest-rules"]
    assert ext["requires_a51_when_status_not_pass"] is True
    assert "escalate" in ext["fail_fast_status"] or ext["fail_fast_status"] == "escalate"


def test_loader_iter_a70_rows_exists() -> None:
    from governance.schemas import loader

    assert hasattr(loader, "iter_a70_rows")


# ---- Positive cases --------------------------------------------------


def test_all_invest_statuses_accepted(a70_validator: "jsonschema.Draft202012Validator") -> None:
    for status in (
        "pass",
        "needs-splitting",
        "needs-estimation",
        "needs-testable-acceptance",
        "needs-negotiation",
        "escalate",
    ):
        row = _base_row()
        row["INVESTStatus"] = status
        # Non-pass statuses should co-populate A51Ref (skill's responsibility,
        # not enforced at pure schema level), but the schema accepts any enum
        # value standalone.
        if status != "pass":
            row["A51Ref"] = "A51-DEC-042"
        errors = list(a70_validator.iter_errors(row))
        assert not errors, f"INVESTStatus={status} rejected: {[e.message for e in errors]}"


def test_category_prefixed_storyid_accepted(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["StoryID"] = "STORY-UX-007"
    errors = list(a70_validator.iter_errors(row))
    assert not errors


def test_multiple_source_claims_accepted(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["SourceClaimIDs"] = "C-001;C-042;C-UX-007"
    errors = list(a70_validator.iter_errors(row))
    assert not errors


def test_nfr_only_provenance_accepted(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Story with RelatedNFRIDs but empty SourceClaimIDs passes the
    schema (INV-08 cross-field rule is the skill's job; schema-level
    allows either provenance route independently)."""
    row = _base_row()
    row["SourceClaimIDs"] = ""
    row["RelatedNFRIDs"] = "NFR-PERF-001"
    errors = list(a70_validator.iter_errors(row))
    assert not errors


def test_claim_only_provenance_accepted(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["SourceClaimIDs"] = "C-042"
    row["RelatedNFRIDs"] = ""
    errors = list(a70_validator.iter_errors(row))
    assert not errors


def test_story_text_without_so_that_accepted(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    """The 'so that' clause is recommended but not strictly required."""
    row = _base_row()
    row["StoryText"] = "As a Triage Ops Lead, I want an order-timeout escalation card"
    errors = list(a70_validator.iter_errors(row))
    assert not errors, [e.message for e in errors]


def test_all_priorities_accepted(a70_validator: "jsonschema.Draft202012Validator") -> None:
    for p in ("level-1", "level-2", "level-3"):
        row = _base_row()
        row["Priority"] = p
        errors = list(a70_validator.iter_errors(row))
        assert not errors


def test_all_estimation_hints_accepted(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    for e in ("xs", "s", "m", "l", "xl", "unknown"):
        row = _base_row()
        row["EstimationHint"] = e
        errors = list(a70_validator.iter_errors(row))
        assert not errors


# ---- Negative cases --------------------------------------------------


def test_malformed_storyid_rejected(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    for bad in ("US-001", "STORY001", "STORY-1", "story-001", "STORY-abc-001"):
        row = _base_row()
        row["StoryID"] = bad
        errors = list(a70_validator.iter_errors(row))
        assert errors, f"Malformed StoryID {bad!r} not rejected"


def test_unknown_invest_status_rejected(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["INVESTStatus"] = "vibey"
    errors = list(a70_validator.iter_errors(row))
    assert errors


def test_unknown_priority_rejected(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["Priority"] = "urgent"
    errors = list(a70_validator.iter_errors(row))
    assert errors


def test_unknown_estimation_rejected(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["EstimationHint"] = "5 points"
    errors = list(a70_validator.iter_errors(row))
    assert errors


def test_empty_title_rejected(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["Title"] = ""
    errors = list(a70_validator.iter_errors(row))
    assert errors


def test_title_too_long_rejected(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["Title"] = "x" * 121
    errors = list(a70_validator.iter_errors(row))
    assert errors


def test_empty_persona_rejected(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["Persona"] = ""
    errors = list(a70_validator.iter_errors(row))
    assert errors


def test_story_text_wrong_shape_rejected(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    """StoryText must match 'As a <persona>, I want <goal>...' pattern."""
    for bad in (
        "The system shall respond quickly",  # requirement, not story
        "Developer writes clean code",  # not a story
        "User wants feature",  # missing 'As a ... I want ...' shape
    ):
        row = _base_row()
        row["StoryText"] = bad
        errors = list(a70_validator.iter_errors(row))
        assert errors, f"Non-story shape {bad!r} not rejected"


def test_empty_acceptance_criteria_rejected(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["AcceptanceCriteria"] = ""
    errors = list(a70_validator.iter_errors(row))
    assert errors


def test_malformed_source_claim_id_rejected(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["SourceClaimIDs"] = "STORY-042"  # wrong prefix, should be C-
    errors = list(a70_validator.iter_errors(row))
    assert errors


def test_malformed_nfr_id_rejected(
    a70_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["RelatedNFRIDs"] = "C-042"  # wrong prefix, should be NFR-
    errors = list(a70_validator.iter_errors(row))
    assert errors


# ---- F5 integration --------------------------------------------------


def test_write_validator_dispatches_a70_path() -> None:
    from governance.schemas.write_validator import _dispatch

    result = _dispatch("analysis/canonical/core_controls/A70_story_register.csv")
    assert result is not None
    schema_name, _fn = result
    assert schema_name == "a70"


def test_write_validator_blocks_anti_pattern_story_content() -> None:
    """Direct Pilot-1-class regression guard: if a skill emits a story
    with the banned "The system shall..." shape, F5 hook blocks at
    write time."""
    from governance.schemas.write_validator import validate_canonical_write

    bad_content = (
        "StoryID,Title,Persona,StoryText,AcceptanceCriteria,SourceClaimIDs,"
        "RelatedNFRIDs,Priority,EstimationHint,INVESTStatus,A51Ref,Notes\n"
        'STORY-001,"Fast system","System","The system shall respond within 500ms",'
        '"criterion",C-042,,level-1,m,pass,,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A70_story_register.csv", bad_content
    )
    assert not ok
    err_text = " ".join(msgs)
    assert "StoryText" in err_text or "does not match" in err_text


def test_write_validator_accepts_valid_a70_content() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "StoryID,Title,Persona,StoryText,AcceptanceCriteria,SourceClaimIDs,"
        "RelatedNFRIDs,Priority,EstimationHint,INVESTStatus,A51Ref,Notes\n"
        'STORY-001,"Triage escalation","Triage Ops Lead",'
        '"As a Triage Ops Lead, I want an escalation card to appear within 2 seconds, '
        'so that I can reassign before SLA breach.",'
        '"Escalation card appears < 2s; shows order ID; one-click reassign",'
        'C-042,NFR-PERF-001,level-1,m,pass,,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A70_story_register.csv", content
    )
    assert ok, msgs


def test_write_validator_blocks_generic_persona() -> None:
    """Anti-pattern 'As a user I want X' — the StoryText pattern still
    matches (it's lexically a story) but the schema can't catch the
    generic-persona issue alone; that's the skill's output validator.
    This test documents current behavior: schema accepts, skill rejects."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "StoryID,Title,Persona,StoryText,AcceptanceCriteria,SourceClaimIDs,"
        "RelatedNFRIDs,Priority,EstimationHint,INVESTStatus,A51Ref,Notes\n"
        'STORY-001,"Generic story","user",'
        '"As a user, I want a feature, so that it works.",'
        '"it works",C-042,,level-1,m,pass,,\n'
    )
    ok, _msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A70_story_register.csv", content
    )
    # Schema-level: this passes. The banned-patterns list is documentation
    # + skill-output-validator territory. Test asserts current behavior so
    # future change is deliberate.
    assert ok


# ---- Marker schema sync (phase3.*.pass) -----------------------------


def test_marker_schema_includes_phase3_story_pass() -> None:
    """US-S6-04 / US-S7-01 incidental: phase3.story.pass must be in the
    marker alphabet now that bsa-story-writer is real."""
    from governance.schemas import loader

    alphabet = loader.marker_id_alphabet()
    assert "phase3.story.pass" in alphabet
    assert "phase3.nfr.pass" in alphabet  # also landed at S7 kickoff
