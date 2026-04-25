"""Tests for the DBML validator (v1.2.15).

v1.2.11 shipped a minimal syntax-only validator — balanced braces,
non-empty bodies, malformed Ref shapes. v1.2.15 extends it with
two semantic check classes:

  * Type-catalog enforcement: column types must be a recognised
    DBML/SQL type (or a parameterized form thereof) OR an Enum
    declared in the same file. The `--lenient-types` flag preserves
    the old permissive behavior.
  * FK target resolution: every Ref (top-level + inline) must point
    at an existing <table>.<column>. Dangling FKs are rejected
    unconditionally (no flag to disable).

These tests pin both the syntax-layer scope (carried over from
v1.2.11) and the new semantic checks. The two pre-v1.2.15 tests
that documented the deferral (`test_validator_does_not_check_*`)
have been INVERTED into the corresponding negative tests.
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


# ---- Positive cases (syntax + structure) -------------------------


def test_fixture_dbml_validates_cleanly() -> None:
    """The v1.2.11 fixture's `.dbml` file MUST validate with zero
    findings — it's the golden reference. v1.2.15 regression: the
    fixture uses `integer`, `varchar`, `timestamp`, and the
    `ticket_severity` enum — all of which the new type-catalog +
    enum-resolution paths must accept."""
    findings = validate_dbml.validate_dbml_file(FIXTURE_DBML)
    assert findings == [], (
        f"fixture .dbml rejected by validator: {findings}"
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
        "Table users { id integer }\n"
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


# ---- v1.2.15: Type validation positive ---------------------------


def test_known_base_types_pass(tmp_path: Path) -> None:
    """Standard SQL/DBML base types (no parameters) are accepted."""
    p = tmp_path / "base_types.dbml"
    p.write_text(
        "Table demo {\n"
        "  a integer [pk]\n"
        "  b bigint\n"
        "  c boolean\n"
        "  d text\n"
        "  e date\n"
        "  f timestamp\n"
        "  g uuid\n"
        "  h jsonb\n"
        "  i bytea\n"
        "}\n",
        encoding="utf-8",
    )
    assert validate_dbml.validate_dbml_file(p) == []


def test_parameterized_types_pass(tmp_path: Path) -> None:
    """Parameterized forms within their declared arity pass."""
    p = tmp_path / "param_types.dbml"
    p.write_text(
        "Table demo {\n"
        "  a integer [pk]\n"
        "  b varchar(255)\n"
        "  c char(8)\n"
        "  d decimal(10,2)\n"
        "  e numeric(20,4)\n"
        "  f varbinary(64)\n"
        "}\n",
        encoding="utf-8",
    )
    assert validate_dbml.validate_dbml_file(p) == []


def test_enum_typed_column_passes(tmp_path: Path) -> None:
    """A column whose type matches an Enum declared in the same file."""
    p = tmp_path / "enum_typed.dbml"
    p.write_text(
        "Enum user_role {\n"
        "  admin\n"
        "  member\n"
        "}\n"
        "Table users {\n"
        "  id integer [pk]\n"
        "  role user_role [not null]\n"
        "}\n",
        encoding="utf-8",
    )
    assert validate_dbml.validate_dbml_file(p) == []


# ---- v1.2.15: Type validation negative ---------------------------


def test_unknown_type_rejected(tmp_path: Path) -> None:
    """Type not in the catalog AND not an Enum is rejected.

    INVERSION of the v1.2.11 `test_validator_does_not_check_type_correctness`
    non-goal test — v1.2.15 adds the check the prior test pinned absent."""
    p = tmp_path / "weird_types.dbml"
    p.write_text(
        "Table users {\n"
        "  id frobnicator [pk]\n"
        "  name my_custom_type\n"
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert any("unknown type" in f and "frobnicator" in f for f in findings), (
        f"expected `frobnicator` rejected: {findings}"
    )
    assert any("unknown type" in f and "my_custom_type" in f for f in findings)


def test_too_many_type_parameters_rejected(tmp_path: Path) -> None:
    """`varchar(10,20)` — varchar takes at most 1 parameter."""
    p = tmp_path / "too_many_params.dbml"
    p.write_text(
        "Table demo {\n"
        "  a integer [pk]\n"
        "  b varchar(10, 20)\n"
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert any("varchar" in f and "parameter" in f for f in findings)


def test_lenient_types_flag_allows_arbitrary_types(tmp_path: Path) -> None:
    """`--lenient-types` preserves pre-v1.2.15 permissive behavior for
    legacy `.dbml` that uses custom domain types."""
    p = tmp_path / "weird_types.dbml"
    p.write_text(
        "Table users {\n"
        "  id frobnicator [pk]\n"
        "  name my_custom_type\n"
        "}\n",
        encoding="utf-8",
    )
    # FK pass still runs (no refs here, so no findings).
    findings = validate_dbml.validate_dbml_file(p, lenient_types=True)
    assert findings == [], f"lenient mode rejected weird types: {findings}"


# ---- v1.2.15: FK target resolution -------------------------------


def test_fk_dangling_table_rejected(tmp_path: Path) -> None:
    """Top-level Ref pointing at a non-existent table.

    INVERSION of v1.2.11's `test_validator_does_not_check_fk_target_resolution`."""
    p = tmp_path / "dangling_table.dbml"
    p.write_text(
        "Table orders {\n"
        "  id integer [pk]\n"
        "  user_id integer\n"
        "}\n"
        "Ref: orders.user_id > nonexistent_table.id\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert any(
        "unknown table" in f and "nonexistent_table" in f for f in findings
    ), f"expected dangling-table rejection: {findings}"


def test_fk_dangling_column_rejected(tmp_path: Path) -> None:
    """Ref's target column doesn't exist on the target table."""
    p = tmp_path / "dangling_column.dbml"
    p.write_text(
        "Table users {\n"
        "  id integer [pk]\n"
        "}\n"
        "Table orders {\n"
        "  id integer [pk]\n"
        "  user_id integer\n"
        "}\n"
        "Ref: orders.user_id > users.nope_column\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert any(
        "users.'nope_column'" in f or "no such column" in f for f in findings
    ), f"expected dangling-column rejection: {findings}"


def test_fk_dangling_from_side_rejected(tmp_path: Path) -> None:
    """Ref's `from` side points at non-existent table — also fails."""
    p = tmp_path / "dangling_from.dbml"
    p.write_text(
        "Table users {\n"
        "  id integer [pk]\n"
        "}\n"
        "Ref: nonexistent.col > users.id\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert any(
        "unknown table" in f and "nonexistent" in f for f in findings
    ), f"expected dangling-from-table rejection: {findings}"


def test_inline_ref_dangling_target_rejected(tmp_path: Path) -> None:
    """Inline `[ref: > target.col]` whose target doesn't resolve."""
    p = tmp_path / "inline_dangling.dbml"
    p.write_text(
        "Table orders {\n"
        "  id integer [pk]\n"
        "  user_id integer [ref: > users.id]\n"  # users doesn't exist
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert any(
        "unknown table" in f and "users" in f for f in findings
    ), f"expected inline-FK rejection: {findings}"


def test_fk_resolution_runs_even_with_lenient_types(tmp_path: Path) -> None:
    """`--lenient-types` skips type-catalog enforcement but FK resolution
    is unconditional — dangling refs are always rejected."""
    p = tmp_path / "lenient_types_dangling_fk.dbml"
    p.write_text(
        "Table users {\n"
        "  id integer [pk]\n"
        "  exotic frobnicator\n"  # would fail strict types, ok in lenient
        "}\n"
        "Ref: users.id > nonexistent.col\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p, lenient_types=True)
    # No type findings (frobnicator allowed), but the FK is dangling.
    assert any("unknown table" in f for f in findings), (
        f"lenient mode skipped FK check: {findings}"
    )
    assert not any("frobnicator" in f for f in findings), (
        f"lenient mode flagged custom type: {findings}"
    )


# ---- v1.2.15 round-1 Codex fixes -------------------------------


def test_multi_word_postgres_types_pass(tmp_path: Path) -> None:
    """Round-1 finding #1: pre-fix, `double precision`, `character varying(255)`,
    `timestamp with time zone` etc. fell through both regex paths,
    so type validation silently skipped them AND the columns never
    landed in `table_cols` (breaking FK resolution to those targets)."""
    p = tmp_path / "pg_types.dbml"
    p.write_text(
        "Table events {\n"
        "  id integer [pk]\n"
        "  amount double precision\n"
        "  label character varying(255)\n"
        "  created_at timestamp with time zone\n"
        "  updated_at timestamp without time zone\n"
        "  span interval day to second\n"
        "}\n",
        encoding="utf-8",
    )
    assert validate_dbml.validate_dbml_file(p) == []


def test_multi_word_type_fk_resolves(tmp_path: Path) -> None:
    """Round-1 finding #1 (FK side): a multi-word column type must
    populate table_cols so a Ref to that column resolves."""
    p = tmp_path / "pg_types_fk.dbml"
    p.write_text(
        "Table events {\n"
        "  id integer [pk]\n"
        "  created_at timestamp with time zone\n"
        "}\n"
        "Table audit {\n"
        "  id integer [pk]\n"
        "  observed_at timestamp with time zone\n"
        "  event_id integer\n"
        "}\n"
        "Ref: audit.event_id > events.id\n"
        "Ref: audit.observed_at > events.created_at\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert findings == [], (
        f"multi-word column should resolve as FK target: {findings}"
    )


def test_unknown_multi_word_type_rejected(tmp_path: Path) -> None:
    """Round-1 finding #1 (negative half): a clearly multi-word but
    unknown form (`mystery composite`) is rejected, not skipped."""
    p = tmp_path / "bad_mw.dbml"
    p.write_text(
        "Table demo {\n"
        "  id integer [pk]\n"
        "  custom mystery composite\n"
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert any(
        "unknown multi-word type" in f and "mystery composite" in f
        for f in findings
    ), f"expected multi-word reject: {findings}"


def test_triple_quoted_note_body_does_not_contaminate_columns(tmp_path: Path) -> None:
    """Round-1 finding #2: pre-fix, the body of `Note: '''multi-line'''`
    leaked into column parsing. Lines like `description text` inside
    the note were mis-classified as columns and either failed type
    validation or polluted the FK inventory."""
    p = tmp_path / "note_body.dbml"
    p.write_text(
        "Table users {\n"
        "  id integer [pk]\n"
        "  Note: '''\n"
        "    description text\n"
        "    weird sentence here\n"
        "    table users explanation\n"
        "  '''\n"
        "  email varchar [not null]\n"
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert findings == [], (
        f"triple-quoted Note body should be skipped, got: {findings}"
    )


def test_inline_ref_without_leading_column_rejected(tmp_path: Path) -> None:
    """Round-1 finding #3: pre-fix, an inline `[ref: > users.id]` on
    a line WITHOUT a leading column identifier silently passed.
    DBML inline refs are column SETTINGS — they MUST annotate a
    column declaration."""
    p = tmp_path / "stray_inline_ref.dbml"
    p.write_text(
        "Table users { id integer [pk] }\n"
        "Table orders {\n"
        "  id integer [pk]\n"
        "  [ref: > users.id]\n"  # no leading column identifier
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert any(
        "no leading column identifier" in f for f in findings
    ), f"expected stray-inline-ref reject: {findings}"


# ---- v1.2.15 round-2 Codex fixes -------------------------------


def test_postgres_parens_in_middle_of_multi_word_type_passes(tmp_path: Path) -> None:
    """Round-2 finding #2: pre-fix, `timestamp(6) with time zone` was
    rejected because the multi-word regex only allowed `(N)` at the
    very end of the token. Real Postgres accepts parens anywhere."""
    p = tmp_path / "pg_parens_middle.dbml"
    p.write_text(
        "Table events {\n"
        "  id integer [pk]\n"
        "  ts timestamp(6) with time zone\n"
        "  t  time(3) without time zone\n"
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert findings == [], (
        f"parens-in-middle multi-word should pass: {findings}"
    )


def test_ansi_long_form_types_pass(tmp_path: Path) -> None:
    """Round-2 finding #3: ANSI long forms were missing from the
    catalog. Operators legitimately write these in `.dbml` files
    sourced from RDBMS-canonical DDL."""
    p = tmp_path / "ansi_long.dbml"
    p.write_text(
        "Table demo {\n"
        "  id integer [pk]\n"
        "  a national character(40)\n"
        "  b national character varying(255)\n"
        "  c character large object\n"
        "  d binary large object\n"
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert findings == [], (
        f"ANSI long-form types should pass: {findings}"
    )


def test_geometry_extension_types_pass(tmp_path: Path) -> None:
    """Round-2 finding #3: spatial types (PostGIS family) added to
    the single-word catalog."""
    p = tmp_path / "spatial.dbml"
    p.write_text(
        "Table places {\n"
        "  id integer [pk]\n"
        "  area geometry\n"
        "  region geography\n"
        "  loc point\n"
        "  shape polygon\n"
        "}\n",
        encoding="utf-8",
    )
    assert validate_dbml.validate_dbml_file(p) == []


def test_inline_ref_inside_triple_quoted_note_does_not_false_positive(tmp_path: Path) -> None:
    """Round-2 finding #1: pre-refactor, `_validate_fk_targets`
    re-scanned every line with `_INLINE_REF_RE.finditer`, so a
    `[ref:...]` literal embedded inside a triple-quoted Note body
    triggered a stray-inline-ref violation. Post-refactor, the FK
    pass consumes parsed-refs from `_parse_structure`, which already
    filters out Note bodies."""
    p = tmp_path / "note_with_ref_literal.dbml"
    p.write_text(
        "Table users {\n"
        "  id integer [pk]\n"
        "  Note: '''\n"
        "    Example DBML referenced in this note:\n"
        "      orders.user_id [ref: > users.id]\n"
        "    The above is just illustrative text, not real DBML.\n"
        "  '''\n"
        "  email varchar [not null]\n"
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert findings == [], (
        f"inline-ref literal inside Note body should NOT trigger FK "
        f"violations: {findings}"
    )


def test_inline_ref_inside_note_block_does_not_false_positive(tmp_path: Path) -> None:
    """Round-2 finding #1 (block form): `Note { ... }` block bodies
    must also be skipped by the FK pass."""
    p = tmp_path / "note_block_with_ref_literal.dbml"
    p.write_text(
        "Table users {\n"
        "  id integer [pk]\n"
        "  Note {\n"
        "    description: 'see orders.user_id [ref: > users.id] in DDL'\n"
        "  }\n"
        "  email varchar [not null]\n"
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert findings == [], (
        f"inline-ref literal inside Note block body should NOT trigger FK "
        f"violations: {findings}"
    )


def test_top_level_ref_inside_note_block_does_not_false_positive(tmp_path: Path) -> None:
    """Round-2 finding #1 (top-level Ref form): a `Ref: ...` literal
    inside a top-level note-like context is not a real top-level Ref.
    Pre-refactor, `_validate_fk_targets` re-scanned the raw text and
    triggered FK violations on the literal."""
    # Top-level notes don't exist in DBML's grammar, but operators
    # sometimes scrap-comment in `// Ref: ...` form. Make sure the
    # comment stripper neutralises that.
    p = tmp_path / "comment_with_ref_literal.dbml"
    p.write_text(
        "// Future: Ref: orders.user_id > users.id\n"
        "Table users {\n"
        "  id integer [pk]\n"
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert findings == [], (
        f"`Ref:` literal inside `//` comment should NOT trigger FK "
        f"violations: {findings}"
    )


# ---- v1.2.15 round-3 Codex fixes -------------------------------


def test_same_line_table_body_columns_resolved_for_fk(tmp_path: Path) -> None:
    """Round-3 finding #1: post-round-2 refactor, the `Table users { id integer [pk] }`
    one-line form was lost — `_parse_structure` `continue`d before
    column parsing, so `tables['users'] == []`. Then a Ref to
    `users.id` false-positive-failed FK resolution. Pin both sides:
    the column lands in `table_cols` AND the cross-table Ref resolves."""
    p = tmp_path / "same_line_table.dbml"
    p.write_text(
        "Table users { id integer [pk] }\n"
        "Table orders { id integer [pk], user_id integer }\n"
        "Ref: orders.user_id > users.id\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert findings == [], (
        f"same-line table body must be parsed for FK resolution: {findings}"
    )


def test_same_line_table_body_type_validation_runs(tmp_path: Path) -> None:
    """Round-3 finding #1 (type-validation half): same-line table body
    must reach type validation. A bad type inside `Table demo { bad frobnicator }`
    must surface."""
    p = tmp_path / "same_line_bad_type.dbml"
    p.write_text(
        "Table demo { id integer [pk], bad frobnicator }\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert any(
        "frobnicator" in f for f in findings
    ), f"expected same-line bad type to fail validation: {findings}"


def test_multiple_paren_groups_in_type_rejected(tmp_path: Path) -> None:
    """Round-3 finding #2: `numeric(10)(2)` was silently accepted by
    the round-2 sum-all-groups implementation. Reject it as malformed."""
    p = tmp_path / "multi_paren.dbml"
    p.write_text(
        "Table demo {\n"
        "  id integer [pk]\n"
        "  bad numeric(10)(2)\n"
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert any(
        "multiple parenthesised parameter groups" in f for f in findings
    ), f"expected multi-paren reject: {findings}"


def test_brace_inside_quoted_string_does_not_break_depth_tracker(tmp_path: Path) -> None:
    """Round-3 finding #3: brace counter was quote-blind, so a Note
    block whose body contains literal `{` or `}` inside a quoted
    string desync'd the depth tracker. Strip quotes before counting."""
    p = tmp_path / "braces_in_quotes.dbml"
    p.write_text(
        "Table users {\n"
        "  id integer [pk]\n"
        "  Note { description: 'has { brace } and } more inside' }\n"
        "  email varchar [not null]\n"
        "}\n"
        "Ref: users.id > users.id\n",  # self-ref to verify table_cols built correctly
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert findings == [], (
        f"brace-in-quoted-string should not break depth tracker: {findings}"
    )


# ---- v1.2.15 round-4 Codex fixes -------------------------------


def test_same_line_table_body_with_parameterized_type_passes(tmp_path: Path) -> None:
    """Round-4 finding #1: pre-fix, naive `body.split(',')` broke
    `numeric(10,2)` into two fragments. Pin that the smart splitter
    keeps `(N,M)` whole."""
    p = tmp_path / "same_line_decimal.dbml"
    p.write_text(
        "Table prices { id integer [pk], amount numeric(10,2), tax decimal(8,4) }\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert findings == [], (
        f"same-line `numeric(N,M)` must survive comma split: {findings}"
    )


def test_same_line_table_body_with_settings_comma_passes(tmp_path: Path) -> None:
    """Round-4 finding #1 (settings half): pre-fix,
    `[not null, ref: > users.id]` was split into two pieces, losing
    the inline ref entirely."""
    p = tmp_path / "same_line_settings.dbml"
    p.write_text(
        "Table users { id integer [pk] }\n"
        "Table orders { id integer [pk], user_id integer [not null, ref: > users.id] }\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert findings == [], (
        f"same-line column with `[not null, ref: ...]` setting must "
        f"keep the inline ref intact: {findings}"
    )


def test_strip_quoted_strings_handles_escaped_quote(tmp_path: Path) -> None:
    """Round-4 finding #2: pre-fix `_strip_quoted_strings` used a
    naive regex `'[^']*'` that stopped at the first same-quote even
    when escaped — `'O\\'Brien { brace }'` would leak the trailing
    `Brien { brace }` into the brace counter. Manual scanner honours
    backslash escapes."""
    p = tmp_path / "escaped_quote.dbml"
    p.write_text(
        "Table users {\n"
        "  id integer [pk]\n"
        # Note body with escaped single quote AND brace literal.
        "  Note: 'O\\'Brien { brace } in name'\n"
        "  email varchar\n"
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert findings == [], (
        f"escape-aware quote strip should not desync depth tracker on "
        f"`'O\\'Brien {{ brace }}'`: {findings}"
    )


def test_strip_quoted_strings_unit_escape_aware() -> None:
    """Direct unit on `_strip_quoted_strings` round-4 escape-aware
    behavior — `'O\\'Brien'` is one logical token."""
    out = validate_dbml._strip_quoted_strings("a 'O\\'Brien' b")
    # The single-quoted string should be replaced with `''`, and the
    # outer text `a `, ` b` should remain.
    assert out == "a '' b", f"unexpected escape-strip result: {out!r}"


# ---- v1.2.15 round-5 Codex fix ---------------------------------


def test_same_line_table_body_quoted_setting_with_bracket_passes(tmp_path: Path) -> None:
    """Round-5 finding: pre-fix `_split_top_level_commas` was quote-blind,
    so `]` (or `[`, `(`, `)`) literal INSIDE a quoted setting value
    desync'd the bracket tracker. Pin the symmetric cases."""
    p = tmp_path / "quoted_setting_bracket.dbml"
    p.write_text(
        "Table demo { "
        "name varchar [note: 'hello ] world', not null], "
        "label varchar [note: 'has ( paren', not null], "
        "age integer "
        "}\n",
        encoding="utf-8",
    )
    findings = validate_dbml.validate_dbml_file(p)
    assert findings == [], (
        f"quoted setting with `]` / `(` literal must not split the "
        f"bracket tracker: {findings}"
    )


def test_split_top_level_commas_unit_quote_aware() -> None:
    """Direct unit on `_split_top_level_commas` round-5 quote-awareness."""
    parts = validate_dbml._split_top_level_commas(
        "name varchar [note: 'hi ] x', not null], age integer"
    )
    assert len(parts) == 2, f"expected 2 fragments, got {len(parts)}: {parts}"
    assert "varchar" in parts[0] and "age integer" in parts[1].strip()


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


def test_main_lenient_types_flag_propagates(tmp_path: Path) -> None:
    """CLI `--lenient-types` actually reaches the validator."""
    p = tmp_path / "weird.dbml"
    p.write_text(
        "Table demo {\n"
        "  id frobnicator [pk]\n"
        "}\n",
        encoding="utf-8",
    )
    # Without flag — fails on unknown type.
    assert validate_dbml.main([str(p)]) == 1
    # With flag — passes.
    assert validate_dbml.main(["--lenient-types", str(p)]) == 0
