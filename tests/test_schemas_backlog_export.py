"""Schema-conformance tests for the four backlog export schemas
(governance/schemas/backlog_export_{jira,linear,generic,github}.schema.json).

Sprint 9 US-S9-01..03 introduced the Jira/Linear/generic exports
(first F5 dispatcher entries under analysis/handoff/ rather than
canonical/). v1.1.4 (B2) extended Jira with optional `customfield_mapping`,
extended Linear with `Project` + `Cycle` columns, and added a brand-new
GitHub Projects v2 export (`backlog_export_github.csv`).

Pattern mirrors the Phase-3 canonical-artifact tests
(test_schemas_a62.py / a70 / a71 / a72): meta-validity, positive cases,
negative regression guards, write_validator dispatch integration,
marker-schema sync, H-sec-4 binding for the two new terminal markers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
JIRA_SCHEMA_PATH = REPO_ROOT / "governance" / "schemas" / "backlog_export_jira.schema.json"
LINEAR_SCHEMA_PATH = REPO_ROOT / "governance" / "schemas" / "backlog_export_linear.schema.json"
GENERIC_SCHEMA_PATH = REPO_ROOT / "governance" / "schemas" / "backlog_export_generic.schema.json"


# ---- Fixtures --------------------------------------------------------


@pytest.fixture(scope="module")
def jira_schema() -> dict:
    return json.loads(JIRA_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def linear_schema() -> dict:
    return json.loads(LINEAR_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def generic_schema() -> dict:
    return json.loads(GENERIC_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def jira_validator(jira_schema: dict) -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(jira_schema, format_checker=jsonschema.FormatChecker())


@pytest.fixture(scope="module")
def linear_validator(linear_schema: dict) -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(linear_schema)


@pytest.fixture(scope="module")
def generic_validator(generic_schema: dict) -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(generic_schema)


def _sample_jira_issue() -> dict:
    return {
        "fields": {
            "project": {"key": "BSA"},
            "issuetype": {"name": "Story"},
            "summary": "On-call agent paged for High/Critical tickets within SLA",
            "description": "As an On-call Agent, I want...\n\n## Acceptance criteria\n\n- Page fires on H/Crit\n\n*BSA provenance: STORY-001*",
            "labels": ["bsa-export", "level-1", "invest-pass"],
        },
        "bsa_provenance": {
            "story_id": "STORY-001",
            "source_claim_ids": ["C-003", "C-007"],
            "related_nfr_ids": ["NFR-PERF-001"],
            "trace_count": 2,
        },
    }


def _sample_jira_export() -> dict:
    return {
        "export_format": "jira",
        "export_format_version": "1.0",
        "generated_at": "2026-04-22T20:30:00Z",
        "source_artifacts": {
            "a70_story_register": "analysis/canonical/core_controls/A70_story_register.csv",
            "a71_test_scenario_register": "analysis/canonical/core_controls/A71_test_scenario_register.csv",
            "a72_traceability_matrix": "analysis/canonical/core_controls/A72_traceability_matrix.csv",
        },
        "issues": [_sample_jira_issue()],
    }


def _sample_linear_row() -> dict:
    return {
        "Title": "On-call agent paged for High/Critical tickets within SLA",
        "Description": "As an On-call Agent, I want to be paged...",
        "Status": "Todo",
        "Priority": "1",
        "Labels": "bsa-export,invest-pass,level-1",
        "Estimate": "3",
        "StoryID": "STORY-001",
        "SourceClaimIDs": "C-003;C-007",
        "RelatedNFRIDs": "NFR-PERF-001",
        # v1.1.4: Linear projects/cycles (TODO-S9-02-LINEAR-PROJECTS).
        # Empty strings preserve pre-v1.1.4 default (team's default
        # project, no cycle). Operator can populate per-row.
        "Project": "",
        "Cycle": "",
    }


def _sample_generic_row() -> dict:
    return {
        "Title": "On-call agent paged for High/Critical tickets within SLA",
        "Description": "As an On-call Agent, I want to be paged when High/Critical, so that initial response begins inside the 4-hour SLA.",
        "AcceptanceCriteria": "Page fires on H/Crit; first response within 240 minutes",
        "Priority": "level-1",
        "StoryID": "STORY-001",
        "SourceClaimIDs": "C-003;C-007",
        "RelatedNFRIDs": "NFR-PERF-001",
        "INVESTStatus": "pass",
        "A51Ref": "",
    }


# ---- Meta ------------------------------------------------------------


@pytest.mark.parametrize(
    "schema_path",
    [JIRA_SCHEMA_PATH, LINEAR_SCHEMA_PATH, GENERIC_SCHEMA_PATH],
    ids=["jira", "linear", "generic"],
)
def test_schema_meta_valid(schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)


def test_csv_schemas_required_subset_of_canonical_columns() -> None:
    for path in (LINEAR_SCHEMA_PATH, GENERIC_SCHEMA_PATH):
        schema = json.loads(path.read_text(encoding="utf-8"))
        canonical = set(schema["x-bsa-csv-columns-order"]["order"])
        required = set(schema["required"])
        assert required == canonical, (
            f"{path.name}: required ↔ canonical column-order mismatch. "
            f"required - canonical = {required - canonical}; "
            f"canonical - required = {canonical - required}"
        )


def test_loader_helpers_exist() -> None:
    from governance.schemas import loader

    assert hasattr(loader, "iter_backlog_export_linear_rows")
    assert hasattr(loader, "iter_backlog_export_generic_rows")


# ---- Positive cases --------------------------------------------------


def test_baseline_jira_export_passes(
    jira_validator: "jsonschema.Draft202012Validator",
) -> None:
    errors = list(jira_validator.iter_errors(_sample_jira_export()))
    assert not errors, [e.message for e in errors]


def test_baseline_linear_row_passes(
    linear_validator: "jsonschema.Draft202012Validator",
) -> None:
    errors = list(linear_validator.iter_errors(_sample_linear_row()))
    assert not errors, [e.message for e in errors]


def test_baseline_generic_row_passes(
    generic_validator: "jsonschema.Draft202012Validator",
) -> None:
    errors = list(generic_validator.iter_errors(_sample_generic_row()))
    assert not errors, [e.message for e in errors]


def test_jira_empty_issues_array_passes(
    jira_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Zero stories is a valid Phase-3 outcome — bridge emits empty
    issues array; export marker still fires."""
    export = _sample_jira_export()
    export["issues"] = []
    errors = list(jira_validator.iter_errors(export))
    assert not errors


def test_linear_empty_estimate_accepted(
    linear_validator: "jsonschema.Draft202012Validator",
) -> None:
    """A70.EstimationHint='unknown' maps to Linear Estimate='' (empty).
    Pin so a future schema edit doesn't accidentally enforce a numeric."""
    row = _sample_linear_row()
    row["Estimate"] = ""
    errors = list(linear_validator.iter_errors(row))
    assert not errors


def test_generic_empty_a51_ref_accepted_for_invest_pass(
    generic_validator: "jsonschema.Draft202012Validator",
) -> None:
    """INVESTStatus='pass' allows empty A51Ref; only deferred statuses
    require it (cross-field rule, enforced upstream by A70 schema)."""
    row = _sample_generic_row()
    row["INVESTStatus"] = "pass"
    row["A51Ref"] = ""
    errors = list(generic_validator.iter_errors(row))
    assert not errors


# ---- Negative cases --------------------------------------------------


def test_jira_wrong_export_format_rejected(
    jira_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Discriminator MUST be exactly 'jira' — protects against a future
    bridge bug emitting linear-shaped JSON under the jira filename."""
    export = _sample_jira_export()
    export["export_format"] = "linear"
    errors = list(jira_validator.iter_errors(export))
    assert errors


def test_jira_missing_provenance_block_rejected(
    jira_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Every issue MUST carry bsa_provenance — INV-08 carries through
    to the export."""
    export = _sample_jira_export()
    del export["issues"][0]["bsa_provenance"]
    errors = list(jira_validator.iter_errors(export))
    assert errors


def test_jira_unknown_issuetype_rejected(
    jira_validator: "jsonschema.Draft202012Validator",
) -> None:
    export = _sample_jira_export()
    export["issues"][0]["fields"]["issuetype"]["name"] = "Quest"
    errors = list(jira_validator.iter_errors(export))
    assert errors


def test_jira_malformed_story_id_rejected(
    jira_validator: "jsonschema.Draft202012Validator",
) -> None:
    export = _sample_jira_export()
    export["issues"][0]["bsa_provenance"]["story_id"] = "story-001"  # lowercase
    errors = list(jira_validator.iter_errors(export))
    assert errors


def test_jira_malformed_label_rejected(
    jira_validator: "jsonschema.Draft202012Validator",
) -> None:
    export = _sample_jira_export()
    export["issues"][0]["fields"]["labels"] = ["bsa export"]  # space, not hyphen
    errors = list(jira_validator.iter_errors(export))
    assert errors


def test_linear_unknown_status_rejected(
    linear_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Bridge only emits Backlog/Todo — closed states (Done, Canceled)
    are out-of-scope (lifecycle stays in receiving team's hands)."""
    row = _sample_linear_row()
    row["Status"] = "Done"
    errors = list(linear_validator.iter_errors(row))
    assert errors


def test_linear_unknown_priority_rejected(
    linear_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _sample_linear_row()
    row["Priority"] = "0"  # Linear has 0=No priority but bridge doesn't emit it
    errors = list(linear_validator.iter_errors(row))
    assert errors


def test_linear_label_must_start_with_bsa_export(
    linear_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Pin: every Linear export row's Labels MUST start with
    'bsa-export' — protects against a bridge bug that drops the
    provenance label."""
    row = _sample_linear_row()
    row["Labels"] = "invest-pass,level-1"  # missing bsa-export prefix
    errors = list(linear_validator.iter_errors(row))
    assert errors


def test_generic_unknown_invest_status_rejected(
    generic_validator: "jsonschema.Draft202012Validator",
) -> None:
    row = _sample_generic_row()
    row["INVESTStatus"] = "passed"  # extra letter
    errors = list(generic_validator.iter_errors(row))
    assert errors


# ---- INV-08 enforcement on exports (round-1 fix) -------------------


def test_jira_export_inv_08_enforced_via_anyof() -> None:
    """Round-1 fix: Jira bsa_provenance block requires anyOf
    (source_claim_ids non-empty OR related_nfr_ids non-empty).
    Pre-fix the empty-arrays case slipped through."""
    from governance.schemas.write_validator import validate_canonical_write

    bad = _sample_jira_export()
    # Both arrays empty — INV-08 violation.
    bad["issues"][0]["bsa_provenance"]["source_claim_ids"] = []
    bad["issues"][0]["bsa_provenance"]["related_nfr_ids"] = []
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json",
        json.dumps(bad),
    )
    assert not ok, (
        "Jira export with both source_claim_ids + related_nfr_ids "
        "empty must be rejected (INV-08 carry-through)"
    )


def test_jira_export_inv_08_satisfied_with_only_claims() -> None:
    """Provenance with only source_claim_ids non-empty (RelatedNFRIDs
    empty) is valid per A70 INV-08; export schema must mirror."""
    from governance.schemas.write_validator import validate_canonical_write

    export = _sample_jira_export()
    export["issues"][0]["bsa_provenance"]["related_nfr_ids"] = []
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json",
        json.dumps(export),
    )
    assert ok, msgs


def test_jira_export_inv_08_satisfied_with_only_nfrs() -> None:
    """Symmetric: only related_nfr_ids non-empty (source_claim_ids
    empty) is valid."""
    from governance.schemas.write_validator import validate_canonical_write

    export = _sample_jira_export()
    export["issues"][0]["bsa_provenance"]["source_claim_ids"] = []
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json",
        json.dumps(export),
    )
    assert ok, msgs


def test_linear_export_inv_08_enforced_via_provenance_rules() -> None:
    """Round-1 fix: Linear CSV gained x-bsa-provenance-rules
    (at_least_one_of_non_empty). The generalized
    _apply_provenance_rules handler enforces at hook time."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "Title,Description,Status,Priority,Labels,Estimate,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs\n"
        '"Orphan story","body",Todo,1,"bsa-export,invest-pass,level-1",'
        "3,STORY-001,,\n"  # both provenance columns empty
    )
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", content
    )
    assert not ok, "Linear export with empty provenance must be rejected"
    err_text = " ".join(msgs)
    assert "SourceClaimIDs" in err_text or "RelatedNFRIDs" in err_text


def test_generic_export_inv_08_enforced_via_provenance_rules() -> None:
    """Round-1 fix: generic CSV also gained x-bsa-provenance-rules."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "Title,Description,AcceptanceCriteria,Priority,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs,INVESTStatus,A51Ref\n"
        '"Orphan story","As a...","accept",level-1,STORY-001,,,pass,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_generic.csv", content
    )
    assert not ok
    err_text = " ".join(msgs)
    assert "SourceClaimIDs" in err_text or "RelatedNFRIDs" in err_text


def test_generic_export_invest_a51_coupling_enforced() -> None:
    """Round-1 fix: generic CSV gained x-bsa-invest-rules
    (requires_a51_when_status_not_pass). Pre-fix the deferred-
    without-A51 case slipped through."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "Title,Description,AcceptanceCriteria,Priority,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs,INVESTStatus,A51Ref\n"
        '"Deferred story","As a...","accept",level-1,STORY-001,'
        "C-042,,needs-estimation,\n"  # deferred + empty A51Ref
    )
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_generic.csv", content
    )
    assert not ok, (
        "Generic export with INVESTStatus=needs-estimation + empty "
        "A51Ref must be rejected (INVEST-A51 coupling carry-through)"
    )
    err_text = " ".join(msgs)
    assert "A51Ref" in err_text


def test_generic_export_invest_a51_coupling_satisfied() -> None:
    """Deferred + non-empty A51Ref → passes."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "Title,Description,AcceptanceCriteria,Priority,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs,INVESTStatus,A51Ref\n"
        '"Deferred story","As a...","accept",level-1,STORY-001,'
        "C-042,,needs-estimation,A51-007\n"
    )
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_generic.csv", content
    )
    assert ok, msgs


def test_jira_labels_must_include_required_membership() -> None:
    """Round-2 MEDIUM (round-3 fix): Jira labels must include the
    three required tags (bsa-export, level-N, invest-N) — not just
    pass the per-label regex. Pre-fix, labels=[] would silently
    accept; this test pins the schema-level membership check."""
    from governance.schemas.write_validator import validate_canonical_write

    # Empty labels — fails minItems + each contains.
    bad_empty = _sample_jira_export()
    bad_empty["issues"][0]["fields"]["labels"] = []
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(bad_empty)
    )
    assert not ok
    assert "labels" in " ".join(msgs).lower()

    # Missing 'bsa-export' specifically (other two present).
    bad_no_provenance = _sample_jira_export()
    bad_no_provenance["issues"][0]["fields"]["labels"] = ["level-1", "invest-pass"]
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(bad_no_provenance)
    )
    assert not ok, (
        "Jira labels missing the 'bsa-export' provenance tag must be "
        "rejected"
    )

    # Missing level-N tier.
    bad_no_level = _sample_jira_export()
    bad_no_level["issues"][0]["fields"]["labels"] = ["bsa-export", "invest-pass"]
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(bad_no_level)
    )
    assert not ok

    # Missing invest-N tier.
    bad_no_invest = _sample_jira_export()
    bad_no_invest["issues"][0]["fields"]["labels"] = ["bsa-export", "level-1"]
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(bad_no_invest)
    )
    assert not ok

    # Out-of-vocab invest tier (e.g., 'invest-something-else').
    bad_invest_vocab = _sample_jira_export()
    bad_invest_vocab["issues"][0]["fields"]["labels"] = [
        "bsa-export", "level-1", "invest-something-else"
    ]
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(bad_invest_vocab)
    )
    assert not ok

    # All three tags present + extras allowed → passes.
    good = _sample_jira_export()
    good["issues"][0]["fields"]["labels"] = [
        "bsa-export", "level-1", "invest-pass", "operator-added-tag"
    ]
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(good)
    )
    assert ok, msgs


def test_jira_labels_singularity_enforced_via_max_contains() -> None:
    """Round-3 LOW (round-4 fix): Jira labels `contains` constraints
    gained `maxContains: 1` so contradictory exports like
    ['bsa-export', 'level-1', 'level-2', 'invest-pass'] (two priority
    tiers) and ['bsa-export', 'level-1', 'invest-pass',
    'invest-needs-estimation'] (two INVEST tiers) fail validation."""
    from governance.schemas.write_validator import validate_canonical_write

    bad_two_levels = _sample_jira_export()
    bad_two_levels["issues"][0]["fields"]["labels"] = [
        "bsa-export", "level-1", "level-2", "invest-pass"
    ]
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(bad_two_levels)
    )
    assert not ok, (
        "Jira labels with two priority tiers (level-1 + level-2) must "
        "be rejected — leaves the receiving team's import ambiguous"
    )

    bad_two_invest = _sample_jira_export()
    bad_two_invest["issues"][0]["fields"]["labels"] = [
        "bsa-export", "level-1", "invest-pass", "invest-needs-estimation"
    ]
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(bad_two_invest)
    )
    assert not ok

    # Duplicate bsa-export — also rejected.
    bad_two_provenance = _sample_jira_export()
    bad_two_provenance["issues"][0]["fields"]["labels"] = [
        "bsa-export", "bsa-export", "level-1", "invest-pass"
    ]
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(bad_two_provenance)
    )
    assert not ok


def test_linear_labels_membership_enforced_via_lookahead() -> None:
    """Round-4 MEDIUM: Linear Labels regex used to only require
    'bsa-export' prefix; missing 'level-N' or 'invest-N' silently
    passed. Tightened with three lookaheads — pin the missing-tag
    cases."""
    from governance.schemas.write_validator import validate_canonical_write

    # v1.1.4: Project + Cycle columns required (empty values OK).
    base_csv = (
        "Title,Description,Status,Priority,Labels,Estimate,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs,Project,Cycle\n"
    )

    # Only bsa-export — missing level + invest.
    bad_only_provenance = base_csv + (
        '"On-call paged","body",Todo,1,"bsa-export",'
        "3,STORY-001,C-003,NFR-PERF-001,,\n"
    )
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", bad_only_provenance
    )
    assert not ok, (
        "Linear Labels with only 'bsa-export' (no level / no invest) "
        "must be rejected — drops priority + INVEST tagging"
    )

    # bsa-export + level only, no invest.
    bad_no_invest = base_csv + (
        '"On-call paged","body",Todo,1,"bsa-export,level-1",'
        "3,STORY-001,C-003,NFR-PERF-001,,\n"
    )
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", bad_no_invest
    )
    assert not ok

    # bsa-export + invest only, no level.
    bad_no_level = base_csv + (
        '"On-call paged","body",Todo,1,"bsa-export,invest-pass",'
        "3,STORY-001,C-003,NFR-PERF-001,,\n"
    )
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", bad_no_level
    )
    assert not ok

    # Out-of-vocab invest tier.
    bad_invest_vocab = base_csv + (
        '"On-call paged","body",Todo,1,"bsa-export,level-1,invest-something",'
        "3,STORY-001,C-003,NFR-PERF-001,,\n"
    )
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", bad_invest_vocab
    )
    assert not ok

    # All three tags + extras → passes.
    good_extras = base_csv + (
        '"On-call paged","body",Todo,1,"bsa-export,level-1,invest-pass,team-on-call",'
        "3,STORY-001,C-003,NFR-PERF-001,,\n"
    )
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", good_extras
    )
    assert ok, msgs


def test_linear_labels_singularity_enforced_via_negative_lookahead() -> None:
    """Round-5 LOW: Linear Labels regex gained 3 negative lookaheads
    so contradictory duplicate tags are rejected (mirrors the
    Jira-side maxContains:1 fix). Linear has no separate INVESTStatus
    field; a duplicate invest-* in the Labels string would be
    silently ambiguous."""
    from governance.schemas.write_validator import validate_canonical_write

    # v1.1.4: Project + Cycle columns required (empty values OK).
    base_csv = (
        "Title,Description,Status,Priority,Labels,Estimate,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs,Project,Cycle\n"
    )

    # Two priority tiers.
    bad_two_levels = base_csv + (
        '"Page","body",Todo,1,"bsa-export,level-1,level-2,invest-pass",'
        "3,STORY-001,C-003,NFR-PERF-001,,\n"
    )
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", bad_two_levels
    )
    assert not ok, "Linear Labels with two priority tiers must be rejected"

    # Two INVEST tiers — most important; Linear can't disambiguate
    # because there's no separate INVESTStatus column.
    bad_two_invest = base_csv + (
        '"Page","body",Todo,1,"bsa-export,level-1,invest-pass,invest-needs-estimation",'
        "3,STORY-001,C-003,NFR-PERF-001,,\n"
    )
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", bad_two_invest
    )
    assert not ok, (
        "Linear Labels with two INVEST tiers must be rejected — "
        "without a separate INVESTStatus column the export is "
        "silently ambiguous"
    )

    # Duplicate bsa-export.
    bad_two_provenance = base_csv + (
        '"Page","body",Todo,1,"bsa-export,bsa-export,level-1,invest-pass",'
        "3,STORY-001,C-003,NFR-PERF-001,,\n"
    )
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", bad_two_provenance
    )
    assert not ok


def test_jira_label_regex_lowercase_only() -> None:
    """Round-1 fix: tightened label pattern from [a-zA-Z...] to
    [a-z...] to match the SKILL.md vocabulary. A future bridge bug
    emitting 'BSA-EXPORT' would slip through pre-fix."""
    from governance.schemas.write_validator import validate_canonical_write

    bad = _sample_jira_export()
    bad["issues"][0]["fields"]["labels"] = ["BSA-EXPORT", "level-1"]  # uppercase
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json",
        json.dumps(bad),
    )
    assert not ok, "Uppercase Jira labels must be rejected"


def test_jira_export_a71_field_optional_in_source_artifacts() -> None:
    """Round-1 fix: a71_test_scenario_register dropped from
    source_artifacts.required (bridge does NOT read A71). Optional
    so an operator who wants to record the A71 state at export
    time can populate it."""
    from governance.schemas.write_validator import validate_canonical_write

    export = _sample_jira_export()
    # Drop a71 field entirely.
    del export["source_artifacts"]["a71_test_scenario_register"]
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json",
        json.dumps(export),
    )
    assert ok, msgs


# ---- F5 write-validator dispatch integration -------------------------


@pytest.mark.parametrize(
    "rel_path,schema_name",
    [
        ("analysis/handoff/backlog_export_jira.json", "backlog_export_jira"),
        ("analysis/handoff/backlog_export_linear.csv", "backlog_export_linear"),
        ("analysis/handoff/backlog_export_generic.csv", "backlog_export_generic"),
    ],
)
def test_dispatcher_routes_handoff_export_paths(rel_path: str, schema_name: str) -> None:
    """Sprint 9 US-S9-01..03: F5 dispatcher gains analysis/handoff/
    paths for the first time. Pin so a future refactor that drops
    the handoff/ entries doesn't silently un-validate the exports."""
    from governance.schemas.write_validator import _dispatch

    result = _dispatch(rel_path)
    assert result is not None, f"dispatcher missing entry for {rel_path}"
    routed_schema, _fn = result
    assert routed_schema == schema_name, (
        f"{rel_path} routed to {routed_schema!r}; expected {schema_name!r}"
    )


def test_write_validator_accepts_valid_jira_export() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = json.dumps(_sample_jira_export(), indent=2)
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", content
    )
    assert ok, msgs


def test_write_validator_blocks_jira_export_with_drifted_format() -> None:
    """End-to-end F5 test: emit a JSON file with export_format='linear'
    under the jira filename; F5 must block."""
    from governance.schemas.write_validator import validate_canonical_write

    bad = _sample_jira_export()
    bad["export_format"] = "linear"
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json",
        json.dumps(bad),
    )
    assert not ok
    assert "export_format" in " ".join(msgs)


def test_write_validator_accepts_valid_linear_csv() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    # v1.1.4: Project + Cycle columns are required; empty values
    # preserve the pre-v1.1.4 default (team's default project, no cycle).
    content = (
        "Title,Description,Status,Priority,Labels,Estimate,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs,Project,Cycle\n"
        '"On-call paged","As an On-call...",Todo,1,"bsa-export,invest-pass,level-1",'
        "3,STORY-001,C-003;C-007,NFR-PERF-001,,\n"
    )
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", content
    )
    assert ok, msgs


def test_write_validator_accepts_valid_linear_csv_with_project_and_cycle() -> None:
    """v1.1.4: Linear export can explicitly set Project and Cycle to
    group imported stories (TODO-S9-02-LINEAR-PROJECTS)."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "Title,Description,Status,Priority,Labels,Estimate,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs,Project,Cycle\n"
        '"On-call paged","As an On-call...",Todo,1,"bsa-export,invest-pass,level-1",'
        "3,STORY-001,C-003;C-007,NFR-PERF-001,Platform Q2 Roadmap,Cycle 12\n"
    )
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", content
    )
    assert ok, msgs


def test_write_validator_accepts_valid_generic_csv() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "Title,Description,AcceptanceCriteria,Priority,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs,INVESTStatus,A51Ref\n"
        '"On-call paged","As an On-call...","Page fires; <= 240 min",'
        "level-1,STORY-001,C-003;C-007,NFR-PERF-001,pass,\n"
    )
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_generic.csv", content
    )
    assert ok, msgs


# ---- Marker schema sync (phase3.backlog_exported + pipeline.phase3.complete) ----


def test_marker_schema_includes_phase3_backlog_exported() -> None:
    from governance.schemas import loader

    alphabet = loader.marker_id_alphabet()
    assert "phase3.backlog_exported" in alphabet


def test_marker_schema_includes_pipeline_phase3_complete() -> None:
    from governance.schemas import loader

    alphabet = loader.marker_id_alphabet()
    assert "pipeline.phase3.complete" in alphabet


def test_marker_schema_includes_phase3_backlog_stage() -> None:
    from governance.schemas import loader

    schema = loader.load_schema("marker")
    stage_enum = schema["properties"]["stage"]["enum"]
    assert "phase3.backlog" in stage_enum
    assert "phase3.complete" in stage_enum


def test_h_sec_4_binds_phase3_backlog_exported_marker() -> None:
    """Sprint 9 incidental: the two terminal markers don't end in
    `.pass`, so they need explicit EXACT entries in
    `_expected_stage_verdict`. Pin both halves (negative drift +
    positive happy-path)."""
    from governance.schemas.write_validator import validate_canonical_write

    drifted = {
        "marker_id": "phase3.backlog_exported",
        "stage": "stage1",   # wrong
        "verdict": "READY",  # wrong
        "timestamp": "2026-04-22T20:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, _msgs = validate_canonical_write(
        "analysis/runtime/ready/phase3.backlog_exported.json",
        json.dumps(drifted),
    )
    assert not ok

    correct = {
        "marker_id": "phase3.backlog_exported",
        "stage": "phase3.backlog",
        "verdict": "PASS",
        "timestamp": "2026-04-22T20:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/phase3.backlog_exported.json",
        json.dumps(correct),
    )
    assert ok, msgs


def test_h_sec_4_binds_pipeline_phase3_complete_marker() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    drifted = {
        "marker_id": "pipeline.phase3.complete",
        "stage": "pipeline",  # wrong (would need to be phase3.complete)
        "verdict": "PASS",
        "timestamp": "2026-04-22T20:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, _msgs = validate_canonical_write(
        "analysis/runtime/ready/pipeline.phase3.complete.json",
        json.dumps(drifted),
    )
    assert not ok

    correct = {
        "marker_id": "pipeline.phase3.complete",
        "stage": "phase3.complete",
        "verdict": "PASS",
        "timestamp": "2026-04-22T20:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/pipeline.phase3.complete.json",
        json.dumps(correct),
    )
    assert ok, msgs


# ---- v1.1.4 B2: Jira customfields (TODO-S9-01-JIRA-CUSTOMFIELDS) ------


def test_jira_customfield_mapping_optional_none_passes() -> None:
    """customfield_mapping is optional. Pre-v1.1.4 exports without it
    must continue to pass."""
    from governance.schemas.write_validator import validate_canonical_write

    export = _sample_jira_export()
    assert "customfield_mapping" not in export
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(export)
    )
    assert ok, msgs


def test_jira_customfield_mapping_valid_keys_pass() -> None:
    """Operator-supplied customfield_mapping with the 4 recognized BSA
    logical keys (nfr_ids, source_claim_ids, story_id, a51_refs)
    pointing at canonical Jira customfield IDs (customfield_NNNNN)
    passes validation."""
    from governance.schemas.write_validator import validate_canonical_write

    export = _sample_jira_export()
    export["customfield_mapping"] = {
        "nfr_ids": "customfield_10042",
        "source_claim_ids": "customfield_10043",
        "story_id": "customfield_10044",
        "a51_refs": "customfield_10045",
    }
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(export)
    )
    assert ok, msgs


def test_jira_customfield_mapping_unknown_key_blocks_write() -> None:
    """customfield_mapping has additionalProperties:false so a typo
    ('nfr_id' vs 'nfr_ids') surfaces immediately."""
    from governance.schemas.write_validator import validate_canonical_write

    export = _sample_jira_export()
    export["customfield_mapping"] = {"nfr_id": "customfield_10042"}  # typo
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(export)
    )
    assert not ok
    assert any("nfr_id" in m or "additionalProperties" in m or "Additional properties" in m for m in msgs), msgs


def test_jira_customfield_mapping_bad_id_format_blocks_write() -> None:
    """customfield IDs must match the canonical 'customfield_NNNNN' (4-6
    digits) shape — ad-hoc IDs ('cf_42', 'customfield_X') are rejected."""
    from governance.schemas.write_validator import validate_canonical_write

    for bad_id in ("cf_42", "customfield_X", "customfield_", "10042"):
        export = _sample_jira_export()
        export["customfield_mapping"] = {"nfr_ids": bad_id}
        ok, _msgs = validate_canonical_write(
            "analysis/handoff/backlog_export_jira.json", json.dumps(export)
        )
        assert not ok, f"customfield ID {bad_id!r} should be rejected"


# ---- v1.1.4 B2: Linear Project + Cycle (TODO-S9-02-LINEAR-PROJECTS) ----


def test_linear_project_overlong_name_blocks_write() -> None:
    """Project name max length is 80 chars per the schema pattern."""
    from governance.schemas.write_validator import validate_canonical_write

    overlong = "x" * 81
    content = (
        "Title,Description,Status,Priority,Labels,Estimate,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs,Project,Cycle\n"
        '"Page","body",Todo,1,"bsa-export,level-1,invest-pass",'
        f"3,STORY-001,C-003,NFR-PERF-001,{overlong},\n"
    )
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", content
    )
    assert not ok, "Project name > 80 chars must be rejected"


def test_linear_project_bad_chars_blocks_write() -> None:
    """Project name pattern rejects characters outside [A-Za-z0-9 _-]."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "Title,Description,Status,Priority,Labels,Estimate,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs,Project,Cycle\n"
        '"Page","body",Todo,1,"bsa-export,level-1,invest-pass",'
        '3,STORY-001,C-003,NFR-PERF-001,"Project!With!Bangs",\n'
    )
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", content
    )
    assert not ok


# ---- v1.1.4 B2: GitHub Projects v2 (TODO-S9-03-GITHUB-PROJECTS) -------


def _sample_github_csv(
    title: str = "Page on H/Crit",
    body: str = "Body text",
    status: str = "Backlog",
    priority: str = "P1",
    size: str = "M",
    labels: str = "bsa-export,level-1,invest-pass",
    story_id: str = "STORY-001",
    source_claim_ids: str = "C-003",
    related_nfr_ids: str = "NFR-PERF-001",
) -> str:
    header = (
        "Title,Body,Status,Priority,Size,Labels,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs\n"
    )
    row = f'"{title}","{body}",{status},{priority},{size},"{labels}",{story_id},{source_claim_ids},{related_nfr_ids}\n'
    return header + row


def test_github_baseline_row_passes() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_github.csv", _sample_github_csv()
    )
    assert ok, msgs


def test_github_dispatcher_routes_to_correct_schema() -> None:
    from governance.schemas.write_validator import _dispatch

    dispatch = _dispatch("analysis/handoff/backlog_export_github.csv")
    assert dispatch is not None
    schema_name, _fn = dispatch
    assert schema_name == "backlog_export_github"


def test_github_priority_p0_round_trip_passes() -> None:
    """The schema intentionally accepts P0 in the enum so that an
    operator who manually escalates a story to P0 post-import can
    re-export the canonical state without the schema rejecting their
    upgraded priority. The bridge itself never emits P0 (P0 escalation
    is a sponsor decision routed via A51, not a derived export shape)."""
    from governance.schemas.write_validator import validate_canonical_write

    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_github.csv",
        _sample_github_csv(priority="P0"),
    )
    assert ok, msgs


def test_github_priority_invalid_value_blocks_write() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_github.csv",
        _sample_github_csv(priority="P99"),
    )
    assert not ok


def test_github_size_invalid_value_blocks_write() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_github.csv",
        _sample_github_csv(size="HUGE"),
    )
    assert not ok


def test_github_size_empty_string_passes() -> None:
    """Size='' is the explicit 'no hint' value (A70.EstimationHint='unknown')."""
    from governance.schemas.write_validator import validate_canonical_write

    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_github.csv",
        _sample_github_csv(size=""),
    )
    assert ok, msgs


def test_github_labels_missing_invest_blocks_write() -> None:
    """Same labels regex as Linear — invest-N tag required."""
    from governance.schemas.write_validator import validate_canonical_write

    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_github.csv",
        _sample_github_csv(labels="bsa-export,level-1"),
    )
    assert not ok


def test_github_labels_two_invest_tiers_blocks_write() -> None:
    """Negative lookahead: contradictory invest-* duplicates must fail
    (mirrors Linear)."""
    from governance.schemas.write_validator import validate_canonical_write

    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_github.csv",
        _sample_github_csv(labels="bsa-export,level-1,invest-pass,invest-needs-estimation"),
    )
    assert not ok


def test_github_provenance_rule_at_least_one_required() -> None:
    """x-bsa-provenance-rules: at_least_one_of_non_empty SourceClaimIDs
    or RelatedNFRIDs."""
    from governance.schemas.write_validator import validate_canonical_write

    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_github.csv",
        _sample_github_csv(source_claim_ids="", related_nfr_ids=""),
    )
    assert not ok


def test_github_loader_iter_function_present() -> None:
    """v1.1.4 added iter_backlog_export_github_rows to the loader."""
    from governance.schemas import loader
    assert hasattr(loader, "iter_backlog_export_github_rows")


def test_github_known_paths_registered() -> None:
    from governance.schemas.write_validator import list_known_paths
    paths = list_known_paths()
    assert any("backlog_export_github" in p for p in paths)


# ---- v1.1.4 round-1 review: edge-case pins (Codex nice-to-have) -------


def test_jira_customfield_mapping_non_string_value_blocks_write() -> None:
    """customfield_mapping values must be strings (not numbers / objects).
    Pins what runtime already enforces via JSON Schema type:string."""
    from governance.schemas.write_validator import validate_canonical_write

    # Numeric value
    export = _sample_jira_export()
    export["customfield_mapping"] = {"nfr_ids": 10042}  # int, not string
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(export)
    )
    assert not ok, "numeric customfield_mapping value must be rejected"

    # Nested object
    export = _sample_jira_export()
    export["customfield_mapping"] = {"nfr_ids": {"id": "customfield_10042"}}
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_jira.json", json.dumps(export)
    )
    assert not ok, "object customfield_mapping value must be rejected"


def test_linear_project_accepts_real_world_name_with_spaces_and_digits() -> None:
    """Pins what the regex `^[A-Za-z0-9 _\\-]{0,80}$` already accepts —
    'Q2 2026 Roadmap' is a typical Linear project name shape."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "Title,Description,Status,Priority,Labels,Estimate,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs,Project,Cycle\n"
        '"Page","body",Todo,1,"bsa-export,level-1,invest-pass",'
        '3,STORY-001,C-003,NFR-PERF-001,"Q2 2026 Roadmap","Cycle 12"\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_linear.csv", content
    )
    assert ok, msgs


def test_github_labels_duplicate_bsa_export_blocks_write() -> None:
    """Negative lookahead: duplicate bsa-export tags must fail (mirrors
    Linear). Pins the regex's anti-duplicate guard for GitHub."""
    from governance.schemas.write_validator import validate_canonical_write

    ok, _msgs = validate_canonical_write(
        "analysis/handoff/backlog_export_github.csv",
        _sample_github_csv(labels="bsa-export,level-1,invest-pass,bsa-export"),
    )
    assert not ok, "duplicate bsa-export tag in GitHub Labels must be rejected"
