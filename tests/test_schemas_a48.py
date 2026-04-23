"""Schema-conformance + parser tests for ``governance/schemas/a48.schema.json`` (F4, Sprint 5).

Two layers:

1. **Parser** (``parse_a48``) — handles the three on-disk shapes
   (bullet-backtick, bullet-bold, table). Covers the real fixture A48
   (table format), the test-helper A48 (bullet-backtick), and a
   Pilot-1-class A48 (bullet-bold + nested children).
2. **Schema** — validates the parsed dict against
   ``governance/schemas/a48.schema.json``. Includes the same
   negative-regression-guard pattern as the marker schema tests
   (Pilot-1-class content that would mismatch).

Plus the CLI smoke test for the ``a48-field`` subcommand that
``hooks/pre_bash_promote.sh`` will invoke after the F2 fix lands.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
A48_SCHEMA_PATH = REPO_ROOT / "governance" / "schemas" / "a48.schema.json"
FIXTURE_A48 = (
    REPO_ROOT
    / "fixtures"
    / "golden"
    / "project_0001"
    / "expected_outputs"
    / "canonical"
    / "core_controls"
    / "A48_run_context_card.md"
)


@pytest.fixture(scope="module")
def a48_schema() -> dict:
    return json.loads(A48_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def a48_validator(a48_schema: dict) -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(a48_schema)


# ---- Parser tests -----------------------------------------------------


def test_parser_handles_bullet_backtick(tmp_path: Path) -> None:
    """Format used by tests/test_plugin_hooks.py::_init_workspace."""
    from governance.schemas.loader import parse_a48

    p = tmp_path / "A48_run_context_card.md"
    p.write_text(
        "# A48 Run Context Card\n\n"
        "- `RunID`: test-run\n"
        "- `Mode`: direct\n"
        "- `CurrentStage`: stage3\n"
        "- `CanonPolicyVersion`: 1.0.0-rc1+hash:test\n",
        encoding="utf-8",
    )
    fields = parse_a48(p)
    assert fields["RunID"] == "test-run"
    assert fields["Mode"] == "direct"
    assert fields["CurrentStage"] == "stage3"
    assert fields["CanonPolicyVersion"] == "1.0.0-rc1+hash:test"


def test_parser_handles_bullet_bold(tmp_path: Path) -> None:
    """Format used by the Pilot-1 engagement A48 (bold field labels + nested children)."""
    from governance.schemas.loader import parse_a48

    p = tmp_path / "A48_run_context_card.md"
    p.write_text(
        "# A48 Run Context Card\n\n"
        "- **RunID**: PILOT1-OD-DISC-20260420-001\n"
        "- **Mode**: `discovery_then_bsa`\n"
        "- **CurrentStage**: `discovery.complete`\n"
        "- **CanonPolicyVersion**: 1.0.0\n"
        "- **InScope**:\n"
        "  - First in-scope item.\n"
        "  - Second in-scope item.\n"
        "\n"
        "- **OutOfScope**: out of scope summary line\n",
        encoding="utf-8",
    )
    fields = parse_a48(p)
    assert fields["RunID"] == "PILOT1-OD-DISC-20260420-001"
    assert fields["Mode"] == "discovery_then_bsa"
    assert fields["CurrentStage"] == "discovery.complete"
    assert fields["CanonPolicyVersion"] == "1.0.0"
    assert fields["InScope"] == "First in-scope item.; Second in-scope item."
    assert fields["OutOfScope"] == "out of scope summary line"


def test_parser_handles_table_format(tmp_path: Path) -> None:
    """Format used by the project_0001 golden fixture — the format that
    the original pre_bash_promote.sh grep silently failed on (P1 finding
    F2 motivator)."""
    from governance.schemas.loader import parse_a48

    p = tmp_path / "A48_run_context_card.md"
    p.write_text(
        "# A48 Run Context Card\n\n"
        "| Field | Value |\n"
        "|---|---|\n"
        "| RunID | fixture-project-0001 |\n"
        "| Mode | direct |\n"
        "| CurrentStage | stage1 |\n"
        "| CanonPolicyVersion | 0.95 |\n",
        encoding="utf-8",
    )
    fields = parse_a48(p)
    assert fields["RunID"] == "fixture-project-0001"
    assert fields["Mode"] == "direct"
    assert fields["CurrentStage"] == "stage1"
    assert fields["CanonPolicyVersion"] == "0.95"


def test_parser_handles_real_fixture() -> None:
    """The committed project_0001 fixture A48 must parse cleanly."""
    from governance.schemas.loader import parse_a48

    fields = parse_a48(FIXTURE_A48)
    assert fields["RunID"] == "fixture-project-0001"
    assert fields["Mode"] == "direct"
    assert fields["CurrentStage"] == "stage1"
    assert fields["CanonPolicyVersion"] == "0.95"
    assert fields["SelectedPath"] == "process"


def test_parser_raises_on_missing_file(tmp_path: Path) -> None:
    from governance.schemas.loader import parse_a48

    with pytest.raises(FileNotFoundError):
        parse_a48(tmp_path / "does-not-exist.md")


def test_parser_returns_empty_for_no_fields(tmp_path: Path) -> None:
    """File exists but has no recognisable A48 fields → empty dict."""
    from governance.schemas.loader import parse_a48

    p = tmp_path / "A48_run_context_card.md"
    p.write_text("# Some unrelated heading\n\nJust prose text here.\n", encoding="utf-8")
    fields = parse_a48(p)
    assert fields == {}


# ---- Schema validation -----------------------------------------------


def test_schema_meta_validity(a48_schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(a48_schema)


def test_schema_accepts_real_fixture(
    a48_validator: "jsonschema.Draft202012Validator",
) -> None:
    from governance.schemas.loader import parse_a48

    fields = parse_a48(FIXTURE_A48)
    errors = list(a48_validator.iter_errors(fields))
    assert not errors, [e.message for e in errors]


def test_schema_accepts_discovery_complete_state(
    a48_validator: "jsonschema.Draft202012Validator",
) -> None:
    """The Pilot-1 engagement reached CurrentStage=discovery.complete; schema must allow."""
    fields = {
        "RunID": "PILOT1-OD-DISC-20260420-001",
        "Mode": "discovery_then_bsa",
        "CurrentStage": "discovery.complete",
        "CanonPolicyVersion": "1.0.0",
    }
    errors = list(a48_validator.iter_errors(fields))
    assert not errors, [e.message for e in errors]


def test_schema_rejects_unknown_mode(
    a48_validator: "jsonschema.Draft202012Validator",
) -> None:
    fields = {
        "RunID": "x",
        "Mode": "wild_mode",
        "CurrentStage": "stage1",
        "CanonPolicyVersion": "1.0.0",
    }
    errors = list(a48_validator.iter_errors(fields))
    assert errors


def test_schema_rejects_unknown_current_stage(
    a48_validator: "jsonschema.Draft202012Validator",
) -> None:
    fields = {
        "RunID": "x",
        "Mode": "direct",
        "CurrentStage": "stage42",
        "CanonPolicyVersion": "1.0.0",
    }
    errors = list(a48_validator.iter_errors(fields))
    assert errors


def test_schema_rejects_missing_required(
    a48_validator: "jsonschema.Draft202012Validator",
) -> None:
    fields = {"RunID": "x", "Mode": "direct"}
    errors = list(a48_validator.iter_errors(fields))
    assert errors
    err_text = " ".join(e.message for e in errors)
    assert "CurrentStage" in err_text or "CanonPolicyVersion" in err_text


def test_schema_rejects_bad_canon_version(
    a48_validator: "jsonschema.Draft202012Validator",
) -> None:
    fields = {
        "RunID": "x",
        "Mode": "direct",
        "CurrentStage": "stage1",
        "CanonPolicyVersion": "version one",
    }
    errors = list(a48_validator.iter_errors(fields))
    assert errors


# ---- CLI tests (used by hooks/pre_bash_promote.sh after F2) ----------


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "governance.schemas.loader", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_cli_a48_field_extracts_current_stage_from_table(tmp_path: Path) -> None:
    p = tmp_path / "A48_run_context_card.md"
    p.write_text(
        "# A48 Run Context Card\n\n"
        "| Field | Value |\n"
        "|---|---|\n"
        "| RunID | x |\n"
        "| Mode | direct |\n"
        "| CurrentStage | stage5 |\n"
        "| CanonPolicyVersion | 1.0.0 |\n",
        encoding="utf-8",
    )
    result = _run_cli(["a48-field", str(p), "CurrentStage"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "stage5"


def test_cli_a48_field_extracts_current_stage_from_bullet_bold(tmp_path: Path) -> None:
    p = tmp_path / "A48_run_context_card.md"
    p.write_text(
        "# A48 Run Context Card\n\n"
        "- **RunID**: x\n"
        "- **Mode**: direct\n"
        "- **CurrentStage**: stage7\n"
        "- **CanonPolicyVersion**: 1.0.0\n",
        encoding="utf-8",
    )
    result = _run_cli(["a48-field", str(p), "CurrentStage"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "stage7"


def test_cli_a48_field_missing_field_exits_2(tmp_path: Path) -> None:
    p = tmp_path / "A48_run_context_card.md"
    p.write_text("- `RunID`: x\n", encoding="utf-8")
    result = _run_cli(["a48-field", str(p), "CurrentStage"])
    assert result.returncode == 2
    assert "does not declare field" in result.stderr


def test_cli_a48_field_missing_file_exits_2(tmp_path: Path) -> None:
    result = _run_cli(["a48-field", str(tmp_path / "nope.md"), "CurrentStage"])
    assert result.returncode == 2


def test_cli_unknown_subcommand_exits_2() -> None:
    result = _run_cli(["nonsense"])
    assert result.returncode == 2
    assert "unknown subcommand" in result.stderr
