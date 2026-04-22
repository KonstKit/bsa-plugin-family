"""Schema-conformance tests for ``governance/schemas/a71.schema.json`` (Phase 3, US-S8-01).

Third Phase-3 canonical artifact (after A62 + A70). Same structural
pattern as test_schemas_a62.py / test_schemas_a70.py: meta-validity,
positive cases across parametrized variations, negative regression
guards, F5 write-validator dispatch integration.

Cross-field rules covered:
  - INV-10 (SourceStoryID required) — JSON Schema enforces directly via
    `required` + pattern; pinned positively + negatively.
  - x-bsa-deferral-rules (AutomationStatus == 'deferred' → A51Ref
    required) — generalized version of A70's INVEST-A51 coupling;
    enforced by write_validator._apply_deferral_rules at hook time
    and tested in tests/test_schemas_write_validator.py (Group 8b).
  - x-bsa-nfr-coverage-rules (when RelatedNFRID set, Then-clause MUST
    embed Metric+Target) — declared here as a documentary cross-field
    extension; executable enforcement is bsa-test-scenario-builder's
    own output-validator responsibility because the rule needs access
    to A62_nfr_register.csv at hook time (cross-artifact lookup
    deliberately deferred from F5 path-bound dispatch).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
A71_SCHEMA_PATH = REPO_ROOT / "governance" / "schemas" / "a71.schema.json"


@pytest.fixture(scope="module")
def a71_schema() -> dict:
    return json.loads(A71_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def a71_validator(a71_schema: dict) -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(a71_schema)


def _base_row() -> dict:
    """Minimal valid A71 row — automated functional scenario (no NFR)."""
    return {
        "ScenarioID": "TS-001",
        "Title": "High-severity ticket pages on-call within SLA",
        "SourceStoryID": "STORY-001",
        "RelatedNFRID": "",
        "Given": "a high-severity ticket has been created",
        "When": "the triage flow assigns severity High",
        "Then": "the on-call agent receives a page within 60 seconds",
        "Tags": "@smoke,@critical",
        "Priority": "level-1",
        "AutomationStatus": "automated",
        "A51Ref": "",
        "Notes": "",
    }


# ---- Meta ------------------------------------------------------------


def test_schema_meta_valid(a71_schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(a71_schema)


def test_required_subset_of_canonical_columns(a71_schema: dict) -> None:
    canonical = set(a71_schema["x-bsa-csv-columns-order"]["order"])
    required = set(a71_schema["required"])
    assert required == canonical, (
        f"For A71 every canonical column is required (no optional cells "
        f"in the test-scenario register). required - canonical = "
        f"{required - canonical}; canonical - required = "
        f"{canonical - required}"
    )


def test_nfr_coverage_rules_extension_exposed(a71_schema: dict) -> None:
    """Documentary INV-10-companion rule (NFR scenario MUST embed
    Metric+Target) lives in x-bsa-nfr-coverage-rules. Pin the shape
    so a future schema edit can't silently drop it."""
    ext = a71_schema["x-bsa-nfr-coverage-rules"]
    assert ext["requires_then_embeds_metric_and_target_when_nfr_set"] is True
    assert "rationale" in ext


def test_deferral_rules_extension_exposed(a71_schema: dict) -> None:
    """x-bsa-deferral-rules is the generalized status+A51-coupling
    pattern (mirrors A70.x-bsa-invest-rules but configurable). Pin
    shape so a future edit can't silently disable the executable
    check in write_validator._apply_deferral_rules."""
    ext = a71_schema["x-bsa-deferral-rules"]
    assert ext["requires_a51_when_status"] == "deferred"


def test_loader_iter_a71_rows_exists() -> None:
    from governance.schemas import loader

    assert hasattr(loader, "iter_a71_rows")


# ---- Positive cases --------------------------------------------------


def test_baseline_valid_row_passes(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    errors = list(a71_validator.iter_errors(_base_row()))
    assert not errors, [e.message for e in errors]


def test_all_automation_statuses_accepted(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    for status in (
        "automated",
        "partial",
        "manual",
        "deferred",
        "not-automated",
    ):
        row = _base_row()
        row["AutomationStatus"] = status
        # 'deferred' must co-populate A51Ref (skill / write_validator's
        # responsibility); other statuses pass standalone.
        if status == "deferred":
            row["A51Ref"] = "A51-DEC-007"
        errors = list(a71_validator.iter_errors(row))
        assert not errors, (
            f"AutomationStatus={status} rejected: {[e.message for e in errors]}"
        )


def test_category_prefixed_scenario_id_accepted(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    for sid in ("TS-002", "TS-PERF-001", "TS-UX-042", "TS-COMP-9999"):
        row = _base_row()
        row["ScenarioID"] = sid
        errors = list(a71_validator.iter_errors(row))
        assert not errors, f"ScenarioID={sid!r} rejected"


def test_nfr_bound_scenario_accepted(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Scenario keyed to an NFR — RelatedNFRID populated, Then-clause
    contains the measurable target. Note: the NFR-coverage rule
    (Then-clause references Metric + asserts literal Target) is
    enforced by bsa-test-scenario-builder's OWN output validator at
    skill-run time, NOT by F5 / write_validator at hook time
    (cross-artifact A62 lookup is outside F5's path-bound dispatch;
    filed as [TODO-S8-01-X-ARTIFACT-NFR-COVERAGE]). Schema-level
    just accepts the row's shape."""
    row = _base_row()
    row["RelatedNFRID"] = "NFR-PERF-001"
    row["Then"] = (
        "the on-call agent receives a page within 60 seconds (p95) AND "
        "the ticket transitions to `acknowledged`"
    )
    errors = list(a71_validator.iter_errors(row))
    assert not errors


def test_empty_optional_fields_accepted(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Tags + RelatedNFRID + A51Ref + Notes all allow empty strings."""
    row = _base_row()
    row["Tags"] = ""
    row["RelatedNFRID"] = ""
    row["A51Ref"] = ""
    row["Notes"] = ""
    errors = list(a71_validator.iter_errors(row))
    assert not errors


def test_multiple_a51_refs_accepted(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["AutomationStatus"] = "deferred"
    row["A51Ref"] = "A51-DEC-001;A51-DEC-002;A51-INF-099"
    errors = list(a71_validator.iter_errors(row))
    assert not errors


def test_well_formed_tag_list_accepted(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    for tags in ("", "@smoke", "@smoke,@perf", "@p95-page-latency,@e2e"):
        row = _base_row()
        row["Tags"] = tags
        errors = list(a71_validator.iter_errors(row))
        assert not errors, f"Tags={tags!r} rejected"


# ---- Negative cases --------------------------------------------------


def test_missing_source_story_id_rejected(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    """INV-10 — SourceStoryID is required; empty string fails the
    pattern. (jsonschema's `required` only catches a missing KEY, not
    an empty string; the pattern catches the empty case.)"""
    row = _base_row()
    row["SourceStoryID"] = ""
    errors = list(a71_validator.iter_errors(row))
    assert any("SourceStoryID" in (str(e.absolute_path) or "") for e in errors), (
        f"empty SourceStoryID was not rejected; got errors={[e.message for e in errors]}"
    )


def test_malformed_source_story_id_rejected(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    """A scenario must reference a STORY-NNN id, not a free string."""
    row = _base_row()
    row["SourceStoryID"] = "user-story-42"
    errors = list(a71_validator.iter_errors(row))
    assert errors, "malformed SourceStoryID was not rejected"


def test_unknown_automation_status_rejected(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["AutomationStatus"] = "in-progress"  # not in enum
    errors = list(a71_validator.iter_errors(row))
    assert errors, "out-of-enum AutomationStatus was not rejected"


def test_unknown_priority_rejected(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["Priority"] = "P0"
    errors = list(a71_validator.iter_errors(row))
    assert errors, "out-of-enum Priority was not rejected"


def test_malformed_tag_rejected(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Tags must be @-prefixed lowercase. A free-text label fails."""
    row = _base_row()
    row["Tags"] = "smoke,critical"  # missing @
    errors = list(a71_validator.iter_errors(row))
    assert errors, "tag without @ was not rejected"


def test_empty_given_rejected(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["Given"] = ""
    errors = list(a71_validator.iter_errors(row))
    assert errors


def test_empty_then_rejected(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["Then"] = ""
    errors = list(a71_validator.iter_errors(row))
    assert errors


def test_title_overlong_rejected(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["Title"] = "x" * 121  # over 120
    errors = list(a71_validator.iter_errors(row))
    assert errors


def test_multi_story_source_rejected(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    """SourceStoryID is SINGULAR — composite scenarios must split.
    The pattern allows a single STORY-NNN id only."""
    row = _base_row()
    row["SourceStoryID"] = "STORY-001;STORY-002"
    errors = list(a71_validator.iter_errors(row))
    assert errors, "multi-story SourceStoryID was not rejected"


def test_malformed_nfr_id_rejected(
    a71_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _base_row()
    row["RelatedNFRID"] = "PERF-001"  # missing NFR- prefix
    errors = list(a71_validator.iter_errors(row))
    assert errors


# ---- F5 write-validator dispatch integration -------------------------


def test_dispatcher_routes_a71_path() -> None:
    from governance.schemas.write_validator import _dispatch

    result = _dispatch("analysis/canonical/core_controls/A71_test_scenario_register.csv")
    assert result is not None
    schema_name, _fn = result
    assert schema_name == "a71"


def test_dispatcher_routes_discovery_a71_path() -> None:
    from governance.schemas.write_validator import _dispatch

    result = _dispatch(
        "analysis/discovery/canonical/core_controls/A71_test_scenario_register.csv"
    )
    assert result is not None
    schema_name, _fn = result
    assert schema_name == "a71"


def test_write_validator_accepts_valid_a71_content() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "ScenarioID,Title,SourceStoryID,RelatedNFRID,Given,When,Then,Tags,"
        "Priority,AutomationStatus,A51Ref,Notes\n"
        'TS-001,"Page on-call",STORY-001,,'
        '"a high-sev ticket arrives",'
        '"the triage flow assigns severity High",'
        '"on-call is paged within 60s",'
        '@smoke,level-1,automated,,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A71_test_scenario_register.csv",
        content,
    )
    assert ok, msgs


def test_write_validator_blocks_a71_missing_source_story_id() -> None:
    """INV-10 enforced at the hook layer."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "ScenarioID,Title,SourceStoryID,RelatedNFRID,Given,When,Then,Tags,"
        "Priority,AutomationStatus,A51Ref,Notes\n"
        'TS-001,"Orphan scenario",,'
        ',"a precondition","an action","an outcome",'
        ',level-2,automated,,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A71_test_scenario_register.csv",
        content,
    )
    assert not ok
    err_text = " ".join(msgs)
    assert "SourceStoryID" in err_text


def test_write_validator_blocks_a71_deferred_without_a51() -> None:
    """x-bsa-deferral-rules — deferred scenarios MUST co-populate A51Ref."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "ScenarioID,Title,SourceStoryID,RelatedNFRID,Given,When,Then,Tags,"
        "Priority,AutomationStatus,A51Ref,Notes\n"
        'TS-001,"Deferred scenario",STORY-001,,'
        '"precondition","action","outcome",'
        ',level-3,deferred,,"automation blocked on env"\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A71_test_scenario_register.csv",
        content,
    )
    assert not ok
    err_text = " ".join(msgs)
    assert (
        "A51Ref" in err_text
        and ("deferred" in err_text or "deferral" in err_text)
    )


def test_write_validator_accepts_a71_deferred_with_a51() -> None:
    """Deferred + A51Ref non-empty → passes."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "ScenarioID,Title,SourceStoryID,RelatedNFRID,Given,When,Then,Tags,"
        "Priority,AutomationStatus,A51Ref,Notes\n"
        'TS-001,"Deferred scenario",STORY-001,,'
        '"precondition","action","outcome",'
        ',level-3,deferred,A51-DEC-001,"automation blocked on env"\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A71_test_scenario_register.csv",
        content,
    )
    assert ok, msgs


# ---- Marker schema sync (phase3.test_scenario.pass) ------------------


def test_marker_schema_includes_phase3_test_scenario_pass() -> None:
    """US-S8-01 incidental: phase3.test_scenario.pass must be in the
    marker alphabet now that bsa-test-scenario-builder is real."""
    from governance.schemas import loader

    alphabet = loader.marker_id_alphabet()
    assert "phase3.test_scenario.pass" in alphabet


def test_marker_schema_includes_phase3_test_scenario_stage() -> None:
    from governance.schemas import loader

    schema = loader.load_schema("marker")
    stage_enum = schema["properties"]["stage"]["enum"]
    assert "phase3.test_scenario" in stage_enum


def test_h_sec_4_binds_phase3_test_scenario_marker_to_stage_and_verdict() -> None:
    """Sprint 8 US-S8-01 round-3 fix: H-sec-4 (marker_id ↔ stage/verdict
    binding) must reject a phase3.test_scenario.pass.json file whose
    payload claims stage='stage1' / verdict='READY'. Pre-fix, the
    marker_id pattern was outside `_expected_stage_verdict`'s table
    and the binding silently no-op'd.

    Same regression class as the pre-fix discovery.d* markers; the
    fix extends the patterned-match block to cover phase3.<sub>.pass.
    """
    from governance.schemas.write_validator import validate_canonical_write

    # Drift payload: filename says phase3.test_scenario.pass; payload
    # says stage1 / READY. Pre-fix this slipped past H-sec-4.
    drifted = {
        "marker_id": "phase3.test_scenario.pass",
        "stage": "stage1",
        "verdict": "READY",
        "timestamp": "2026-04-22T16:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/phase3.test_scenario.pass.json",
        json.dumps(drifted),
    )
    assert not ok, "H-sec-4 must reject stage/verdict drift on phase3 markers"
    err_text = " ".join(msgs)
    assert (
        "stage" in err_text.lower() or "verdict" in err_text.lower()
    ), f"expected stage/verdict mismatch surfaced; got: {err_text}"

    # Same payload but with the correct stage/verdict — must pass.
    correct = {
        "marker_id": "phase3.test_scenario.pass",
        "stage": "phase3.test_scenario",
        "verdict": "PASS",
        "timestamp": "2026-04-22T16:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/phase3.test_scenario.pass.json",
        json.dumps(correct),
    )
    assert ok, msgs


def test_h_sec_4_binds_phase3_story_marker_to_stage_and_verdict() -> None:
    """Sibling regression: phase3.story.pass (Sprint 7) had the same
    H-sec-4 binding gap; the round-3 fix extended the patterned-match
    to cover all phase3.<sub>.pass shapes. Pin so a future refactor
    that drops phase3 from the patterned-match block fails loudly."""
    from governance.schemas.write_validator import validate_canonical_write

    drifted = {
        "marker_id": "phase3.story.pass",
        "stage": "stage8",  # wrong
        "verdict": "READY",  # wrong
        "timestamp": "2026-04-22T16:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/phase3.story.pass.json",
        json.dumps(drifted),
    )
    assert not ok

    # Positive assertion (mirrors the test_scenario test above): the
    # matching stage/verdict payload must pass. Pre-round-3 the
    # patterned-match was missing entirely, so neither the negative
    # nor positive case had a binding check at all.
    correct = {
        "marker_id": "phase3.story.pass",
        "stage": "phase3.story",
        "verdict": "PASS",
        "timestamp": "2026-04-22T16:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/phase3.story.pass.json",
        json.dumps(correct),
    )
    assert ok, msgs


def test_h_sec_4_binds_phase3_nfr_marker_to_stage_and_verdict() -> None:
    """Third sibling: phase3.nfr.pass (Sprint 6). Same regression
    class; rounds out the phase3.* binding coverage."""
    from governance.schemas.write_validator import validate_canonical_write

    drifted = {
        "marker_id": "phase3.nfr.pass",
        "stage": "stage1",
        "verdict": "READY",
        "timestamp": "2026-04-22T16:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, _msgs = validate_canonical_write(
        "analysis/runtime/ready/phase3.nfr.pass.json",
        json.dumps(drifted),
    )
    assert not ok

    correct = {
        "marker_id": "phase3.nfr.pass",
        "stage": "phase3.nfr",
        "verdict": "PASS",
        "timestamp": "2026-04-22T16:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/phase3.nfr.pass.json",
        json.dumps(correct),
    )
    assert ok, msgs
