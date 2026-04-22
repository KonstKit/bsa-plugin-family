"""Schema-conformance + CSV-row tests for ``governance/schemas/a51.schema.json`` (F4c, Sprint 5).

A51 is the first CSV-backed canonical artifact in the schema set. The
schema describes a single ROW (dict shape), and a generic
``iter_csv_rows`` reader in the loader yields rows. The validator
iterates rows, validating each against the schema; this avoids needing
a tabular-schema dependency (frictionless / pandera) and keeps the
loader stdlib-only.

Five test groups:

1. **Schema meta-validity** (Draft 2020-12).
2. **CSV reader** — column-set assertion, empty file, malformed CSV.
3. **Positive cases** — rows from all four golden fixtures must
   validate; representative hand-built rows for each IssueType +
   ResolutionStatus combination must validate.
4. **Negative cases** — Sysco-style drift (e.g., bare numeric A51Ref
   without category prefix is fine; but bare ``A51-MISS`` without
   numeric suffix or unknown IssueType must fail).
5. **F6 reconciliation seed** — verify the schema enum supports the
   lifecycle states (open / resolved / resolved_by_remediation /
   superseded / wontfix) that F6's reconciliation auditor will key on.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
A51_SCHEMA_PATH = REPO_ROOT / "governance" / "schemas" / "a51.schema.json"
FIXTURES_GLOB = (
    "fixtures/golden/*/expected_outputs/canonical/core_controls/A51_issue_route_register.csv"
)


@pytest.fixture(scope="module")
def a51_schema() -> dict:
    return json.loads(A51_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def a51_validator(a51_schema: dict) -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(a51_schema)


# ---- 1. Schema meta-validity ------------------------------------------


def test_schema_meta_validity(a51_schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(a51_schema)


def test_canonical_column_order_matches_required(a51_schema: dict) -> None:
    """The x-bsa-csv-columns-order extension must be a superset of the
    'required' fields, so the schema's row contract is internally
    consistent (every required field is in the canonical column order)."""
    canonical = set(a51_schema["x-bsa-csv-columns-order"]["order"])
    required = set(a51_schema["required"])
    assert required.issubset(canonical), (
        f"required fields not in canonical column order: {required - canonical}"
    )


# ---- 2. CSV reader ----------------------------------------------------


def test_iter_csv_rows_reads_basic(tmp_path: Path) -> None:
    from governance.schemas.loader import iter_csv_rows

    p = tmp_path / "tiny.csv"
    p.write_text("a,b,c\n1,2,3\n4,5,6\n", encoding="utf-8")
    rows = list(iter_csv_rows(p))
    assert rows == [
        {"a": "1", "b": "2", "c": "3"},
        {"a": "4", "b": "5", "c": "6"},
    ]


def test_iter_csv_rows_handles_quoted_commas(tmp_path: Path) -> None:
    """Quoted-comma values must not split into extra columns."""
    from governance.schemas.loader import iter_csv_rows

    p = tmp_path / "quoted.csv"
    p.write_text(
        'A51Ref,NextAction\n'
        'A51-001,"Confirm the value, then update the report"\n',
        encoding="utf-8",
    )
    rows = list(iter_csv_rows(p))
    assert len(rows) == 1
    assert rows[0]["NextAction"] == "Confirm the value, then update the report"


def test_iter_csv_rows_column_assertion_fires(tmp_path: Path) -> None:
    from governance.schemas.loader import iter_csv_rows

    p = tmp_path / "wrong-cols.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns|unexpected columns"):
        list(iter_csv_rows(p, expected_columns=["a", "b", "c"]))


def test_iter_csv_rows_missing_file(tmp_path: Path) -> None:
    from governance.schemas.loader import iter_csv_rows

    with pytest.raises(FileNotFoundError):
        list(iter_csv_rows(tmp_path / "nope.csv"))


def test_iter_a51_rows_reads_real_fixture() -> None:
    """The committed project_0001 A51 fixture parses cleanly via the
    A51-specific iterator, including the canonical column-order check."""
    from governance.schemas.loader import iter_a51_rows

    fixture = (
        REPO_ROOT
        / "fixtures"
        / "golden"
        / "project_0001"
        / "expected_outputs"
        / "canonical"
        / "core_controls"
        / "A51_issue_route_register.csv"
    )
    rows = list(iter_a51_rows(fixture))
    assert len(rows) >= 1
    assert all("A51Ref" in r for r in rows)


# ---- 3. Positive cases (real fixtures + parametrized rows) -----------


def test_all_golden_fixture_rows_validate(
    a51_validator: "jsonschema.Draft202012Validator",
) -> None:
    from governance.schemas.loader import iter_a51_rows

    failures: list[tuple[Path, int, list[str]]] = []
    for fixture_path in sorted(REPO_ROOT.glob(FIXTURES_GLOB)):
        for idx, row in enumerate(iter_a51_rows(fixture_path), start=2):  # +2 for header
            errors = list(a51_validator.iter_errors(row))
            if errors:
                failures.append((fixture_path, idx, [e.message for e in errors]))
    assert not failures, (
        "Fixture A51 rows failed validation:\n"
        + "\n".join(f"  {p} line {i}: {msgs}" for p, i, msgs in failures)
    )


@pytest.mark.parametrize(
    "row",
    [
        {
            "A51Ref": "A51-001",
            "IssueType": "uncertainty",
            "Severity": "low",
            "BlockingStatus": "informational",
            "RaisedByStage": "stage1",
            "RelatedSourceID": "",
            "RelatedClaimID": "C-005",
            "NextAction": "Confirm the estimate against external data",
            "ResolutionStatus": "open",
        },
        {
            "A51Ref": "A51-INJ-002",
            "IssueType": "boundary_risk",
            "Severity": "medium",
            "BlockingStatus": "soft",
            "RaisedByStage": "stage3",
            "RelatedSourceID": "S-002",
            "RelatedClaimID": "",
            "NextAction": "Quarantine prompt-injection content",
            "ResolutionStatus": "resolved_by_remediation",
        },
        {
            "A51Ref": "A51-CNTR-009",
            "IssueType": "contradiction",
            "Severity": "high",
            "BlockingStatus": "hard",
            "RaisedByStage": "d3",
            "RelatedSourceID": "S-007;S-008",
            "RelatedClaimID": "C-014;C-022",
            "NextAction": "Escalate to product owner for arbitration",
            "ResolutionStatus": "open",
        },
        {
            "A51Ref": "A51-9999",
            "IssueType": "decision_needed",
            "Severity": "low",
            "BlockingStatus": "soft",
            "RaisedByStage": "discovery.complete",
            "RelatedSourceID": "",
            "RelatedClaimID": "",
            "NextAction": "Decide on phase-2 scope",
            "ResolutionStatus": "wontfix",
        },
        {
            # v1.0.4+1 polish: prefixed `discovery.dN` form must validate.
            # Sysco engagement raised hard-block missing-source rows
            # against `discovery.d1` (see Phase-2.5 pilot blocker note in
            # docs/retros/sprint_5_v1_0_4_ux_pass.md). Pre-fix, the bare
            # `d1` was the only legal form and Sysco's rows failed F5.
            "A51Ref": "A51-MISS-001",
            "IssueType": "missing_source",
            "Severity": "high",
            "BlockingStatus": "hard",
            "RaisedByStage": "discovery.d1",
            "RelatedSourceID": "",
            "RelatedClaimID": "MISS-001",
            "NextAction": "Request formal SLA/NFR doc from Ross/JB",
            "ResolutionStatus": "open",
        },
        {
            "A51Ref": "A51-MISS-099",
            "IssueType": "missing_source",
            "Severity": "medium",
            "BlockingStatus": "soft",
            "RaisedByStage": "discovery.d5",
            "RelatedSourceID": "S-099",
            "RelatedClaimID": "",
            "NextAction": "Re-extract from updated source",
            "ResolutionStatus": "open",
        },
    ],
    ids=[
        "minimal-numeric-ref",
        "category-prefix-INJ",
        "category-prefix-CNTR-with-multi-sources",
        "discovery-complete-stage",
        "prefixed-discovery-d1-stage",
        "prefixed-discovery-d5-stage",
    ],
)
def test_representative_rows_validate(
    a51_validator: "jsonschema.Draft202012Validator", row: dict
) -> None:
    errors = list(a51_validator.iter_errors(row))
    assert not errors, [e.message for e in errors]


# ---- 4. Negative cases ------------------------------------------------


def test_schema_rejects_unknown_issue_type(
    a51_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Sysco-style drift would emit ad-hoc IssueType strings (e.g.,
    'policy_violation'); schema must reject."""
    bad = {
        "A51Ref": "A51-001",
        "IssueType": "policy_violation",  # not in enum
        "Severity": "low",
        "BlockingStatus": "soft",
        "RaisedByStage": "stage1",
        "NextAction": "anything",
        "ResolutionStatus": "open",
    }
    errors = list(a51_validator.iter_errors(bad))
    assert errors


def test_schema_rejects_malformed_a51_ref(
    a51_validator: "jsonschema.Draft202012Validator",
) -> None:
    bad = {
        "A51Ref": "A51",  # no numeric suffix
        "IssueType": "uncertainty",
        "Severity": "low",
        "BlockingStatus": "soft",
        "RaisedByStage": "stage1",
        "NextAction": "anything",
        "ResolutionStatus": "open",
    }
    errors = list(a51_validator.iter_errors(bad))
    assert errors


def test_schema_rejects_unknown_resolution_status(
    a51_validator: "jsonschema.Draft202012Validator",
) -> None:
    bad = {
        "A51Ref": "A51-001",
        "IssueType": "uncertainty",
        "Severity": "low",
        "BlockingStatus": "soft",
        "RaisedByStage": "stage1",
        "NextAction": "anything",
        "ResolutionStatus": "in_progress",  # not in enum — F6 will key on this
    }
    errors = list(a51_validator.iter_errors(bad))
    assert errors


def test_schema_rejects_empty_next_action(
    a51_validator: "jsonschema.Draft202012Validator",
) -> None:
    """NextAction must be non-empty even for informational issues."""
    bad = {
        "A51Ref": "A51-001",
        "IssueType": "uncertainty",
        "Severity": "low",
        "BlockingStatus": "informational",
        "RaisedByStage": "stage1",
        "NextAction": "",
        "ResolutionStatus": "open",
    }
    errors = list(a51_validator.iter_errors(bad))
    assert errors


def test_schema_rejects_missing_required(
    a51_validator: "jsonschema.Draft202012Validator",
) -> None:
    bad = {
        "A51Ref": "A51-001",
        "IssueType": "uncertainty",
    }
    errors = list(a51_validator.iter_errors(bad))
    assert errors


# ---- 5. F6 reconciliation lifecycle seed ------------------------------


def test_resolution_status_enum_supports_lifecycle(a51_schema: dict) -> None:
    """F6 (A51 reconciliation auditor) needs the lifecycle states
    enumerated here. Pin the contract so a future refactor that
    accidentally drops one of these values fails this test."""
    enum = set(a51_schema["properties"]["ResolutionStatus"]["enum"])
    required_for_f6 = {
        "open",
        "resolved",
        "resolved_by_remediation",
        "superseded",
        "wontfix",
    }
    missing = required_for_f6 - enum
    assert not missing, f"F6 lifecycle states missing from enum: {sorted(missing)}"
