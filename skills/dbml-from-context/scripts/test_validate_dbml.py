"""Tests for the minimal DBML syntax validator (v1.2.11).

The validator at `validate_dbml.py` does NOT attempt full DBML parsing —
it catches gross-structure errors (balanced braces, empty blocks,
malformed Ref statements / inline refs) without requiring the `@dbml/core`
Node package. These tests pin that scope: positive cases for well-formed
.dbml, negative cases for the error classes we DO catch, and a few
explicit non-goals (type correctness, FK target resolution) that we
INTENTIONALLY don't check in v1.2.11.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(SCRIPTS_DIR))
import validate_dbml  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DBML = (
    REPO_ROOT
    / "fixtures"
    / "golden"
    / "project_0004_sidecar_e2e"
    / "expected_outputs"
    / "views"
    / "dbml"
    / "ticket_persistence.dbml"
)


# ---- Positive cases ----------------------------------------------


def test_fixture_dbml_validates_cleanly() -> None:
    """The v1.2.11 fixture's `.dbml` file MUST validate with zero
    findings — it's the golden reference."""
    findings = validate_dbml.validate_dbml_file(FIXTURE_DBML)
    assert findings == [], (
        f"fixture .dbml rejected by minimal validator: {findings}"
    )


def test_minimal_well_formed_dbml_passes(tmp_path: Path) -> None:
    p = tmp_path / "tiny.dbml"
    p.write_text(
        "Table users {\n"
        "  id integer [pk]\n"
        "  username varchar [not null]\n"
        "}\n",
        encoding="utf-8",
    )
    assert validate_dbml.validate_dbml_file(p) == []


def test_dbml_with_top_level_ref_passes(tmp_path: Path) -> None:
    p = tmp_path / "with_ref.dbml"
    p.write_text(
        "Table users {\n"
        "  id integer [pk]\n"
        "}\n"
        "\n"
        "Table orders {\n"
        "  id integer [pk]\n"
        "  user_id integer\n"
        "}\n"
        "\n"
        "Ref: orders.user_id > users.id\n",
        encoding="utf-8",
    )
    assert validate_dbml.validate_dbml_file(p) == []


def test_dbml_with_inline_ref_passes(tmp_path: Path) -> None:
    p = tmp_path / "inline_ref.dbml"
    p.write_text(
        "Table users {\n"
        "  id integer [pk]\n"
        "}\n"
        "\n"
        "Table orders {\n"
        "  id integer [pk]\n"
        "  user_id integer [ref: > users.id]\n"
        "}\n",
        encoding="utf-8",
    )
    assert validate_dbml.validate_dbml_file(p) == []


def test_dbml_with_enum_and_tablegroup_passes(tmp_path: Path) -> None:
    p = tmp_path / "enum_and_group.dbml"
    p.write_text(
        "Enum user_role {\n"
        "  admin\n"
        "  member\n"
        "}\n"
        "\n"
        "Table users {\n"
        "  id integer [pk]\n"
        "  role user_role [not null]\n"
        "}\n"
        "\n"
        "Table roles {\n"
        "  id integer [pk]\n"
        "}\n"
        "\n"
        "TableGroup tenancy {\n"
        "  users\n"
        "  roles\n"
        "}\n",
        encoding="utf-8",
    )
    assert validate_dbml.validate_dbml_file(p) == []


# ---- Negative: unbalanced braces ---------------------------------


def test_unbalanced_closing_brace_rejected(tmp_path: Path) -> None:
    p = tmp_path / "bad_close.dbml"
    p.write_text("Table users {\n  id integer\n}\n}\n", encoding="utf-8")
    findings = validate_dbml.validate_dbml_file(p)
    assert any("unbalanced closing brace" in f for f in findings)


def test_unbalanced_opening_brace_rejected(tmp_path: Path) -> None:
    p = tmp_path / "bad_open.dbml"
    p.write_text("Table users {\n  id integer\n", encoding="utf-8")
    findings = validate_dbml.validate_dbml_file(p)
    assert any("unbalanced opening brace" in f for f in findings)


def test_empty_block_body_rejected(tmp_path: Path) -> None:
    """Multi-line empty block body is suspicious."""
    p = tmp_path / "empty_block.dbml"
    p.write_text("Table users {\n}\n", encoding="utf-8")
    findings = validate_dbml.validate_dbml_file(p)
    assert any("closes empty" in f for f in findings)


def test_same_line_empty_block_body_rejected(tmp_path: Path) -> None:
    """v1.2.11 round-1 Codex regression: `Table users {}` on ONE line
    was silently accepted before the round-1 fix because the empty-
    block check only fired when the closer was on a later line.
    Pin the one-line variant so a future revert surfaces."""
    p = tmp_path / "oneline_empty.dbml"
    p.write_text("Table users {}\n", encoding="utf-8")
    findings = validate_dbml.validate_dbml_file(p)
    assert any("opens and closes" in f and "empty on the same line" in f for f in findings), (
        f"same-line empty block {findings}"
    )


def test_same_line_empty_enum_rejected(tmp_path: Path) -> None:
    """Same-line variant for Enum — should also surface."""
    p = tmp_path / "oneline_empty_enum.dbml"
    p.write_text("Enum user_role {}\n", encoding="utf-8")
    findings = validate_dbml.validate_dbml_file(p)
    assert any("opens and closes" in f and "empty on the same line" in f for f in findings)


def test_same_line_block_with_body_passes(tmp_path: Path) -> None:
    """One-line block WITH body is fine (same-line `Table users { id integer }` is valid DBML)."""
    p = tmp_path / "oneline_with_body.dbml"
    p.write_text("Table users { id integer [pk] }\n", encoding="utf-8")
    assert validate_dbml.validate_dbml_file(p) == []


# ---- Negative: malformed Ref -------------------------------------


def test_malformed_top_level_ref_rejected(tmp_path: Path) -> None:
    """Missing `.column` on one side fails the Ref shape."""
    p = tmp_path / "bad_ref.dbml"
    p.write_text(
        "Table users { id integer }\n"  # body + closer same line → OK
        "Table orders { id integer }\n"
        "Ref: orders.user_id > users\n",  # missing `.column`
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert any("malformed top-level Ref" in f for f in findings)


def test_malformed_inline_ref_rejected(tmp_path: Path) -> None:
    """Inline `[ref: ...]` missing the direction or target fails."""
    p = tmp_path / "bad_inline.dbml"
    p.write_text(
        "Table orders { user_id integer [ref: users.id] }\n",  # missing dir
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert any("malformed inline ref" in f for f in findings)


# ---- Negative: non-UTF-8 -----------------------------------------


def test_non_utf8_rejected(tmp_path: Path) -> None:
    p = tmp_path / "binary.dbml"
    p.write_bytes(b"\xff\xfe\x00\x01 binary garbage")
    findings = validate_dbml.validate_dbml_file(p)
    assert any("cannot read file" in f for f in findings)


# ---- Explicit non-goals (deferred) -------------------------------


def test_validator_does_not_check_type_correctness(tmp_path: Path) -> None:
    """DBML is tolerant of arbitrary type names (`frobnicator`,
    `my_custom_type`) — the validator does NOT flag them. If a future
    release adds type-correctness checks, this test needs update +
    the deferral claim in the validator docstring needs removal."""
    p = tmp_path / "weird_types.dbml"
    p.write_text(
        "Table users {\n"
        "  id frobnicator [pk]\n"
        "  name my_custom_type\n"
        "}\n",
        encoding="utf-8",
    )
    # Well-formed structurally, even if type names are unusual.
    assert validate_dbml.validate_dbml_file(p) == []


def test_validator_does_not_check_fk_target_resolution(tmp_path: Path) -> None:
    """A `Ref:` pointing at a non-existent table is structurally valid
    but semantically broken. v1.2.11 INTENTIONALLY doesn't check FK
    resolution — that's a future release."""
    p = tmp_path / "dangling_fk.dbml"
    p.write_text(
        "Table orders { user_id integer [ref: > nonexistent_table.nope] }\n",
        encoding="utf-8",
    )
    assert validate_dbml.validate_dbml_file(p) == []


# ---- CLI smoke test ----------------------------------------------


def test_main_no_paths_returns_2() -> None:
    assert validate_dbml.main([]) == 2


def test_main_good_file_returns_0(capsys) -> None:
    rc = validate_dbml.main([str(FIXTURE_DBML)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 file(s) validated" in out


def test_main_bad_file_returns_1(tmp_path: Path, capsys) -> None:
    p = tmp_path / "bad.dbml"
    p.write_text("Table users {\n", encoding="utf-8")  # unclosed
    rc = validate_dbml.main([str(p)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unbalanced" in err


def test_main_missing_path_returns_2(capsys) -> None:
    rc = validate_dbml.main(["/does/not/exist.dbml"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "path not found" in err
