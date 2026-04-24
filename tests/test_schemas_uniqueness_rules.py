"""Tests for the generic ``x-bsa-uniqueness-rules`` extension (v1.2.10).

v1.2.10 generalises the cross-row uniqueness logic that shipped with
A61's ``x-bsa-anchor-binding-rules`` in v1.2.8. Any schema can now
declare:

.. code-block:: json

    "x-bsa-uniqueness-rules": {
        "applies_to_all_rows": true,
        "unique_columns": ["ColumnName1", "ColumnName2"],
        "_comment": "..."
    }

Implementation:
- ``_check_unique_columns(rows, unique_columns, ext_name)`` — shared
  helper that both A61's ``_apply_anchor_binding_rules`` and the new
  ``_apply_uniqueness_rules`` call. The ``ext_name`` arg keeps the
  violation message attributed to the source extension (A61 messages
  still name ``x-bsa-anchor-binding-rules``; generic messages name
  ``x-bsa-uniqueness-rules``).
- ``_apply_uniqueness_rules`` — new cross-row handler wired into
  ``_make_csv_validator._validate`` after the per-row loop. Runs once
  per write. Schemas that don't declare the extension no-op silently.

This test file exercises the generic handler in isolation (with an
in-memory schema shape — no dispatcher-level routing, so it's
independent of which canonical CSVs currently declare the extension).
A future release (v1.2.12+ candidate) that adds the extension to
A50/A58/A59/A60/A62/A70/A71/A72 schemas will add fixture-level
regression tests separately.

Coverage groups:
1. **Happy path + gates** — applies_to_all_rows gate, no-ext no-op,
   empty-rows no-op.
2. **Per-occurrence reporting** — 3-occurrence case yields 2 violations
   (rows 3 + 4 vs row 2), matching the A61 test pattern.
3. **Blank-cell interaction** — blank cells are NOT flagged as
   uniqueness violations (schema-level required check covers them).
4. **Multiple columns** — `unique_columns: [X, Y]` enforces BOTH
   independently; duplicates in X AND in Y surface as separate
   violations.
5. **A61-generic coexistence** — schema with BOTH extensions emits
   violations from BOTH handlers (one from each) for the same
   duplicate column; messages are attributed to their respective
   source extensions.
6. **Violation-message shape** — "line N <col>=<value>: duplicate
   value (first seen on line M) — x-bsa-uniqueness-rules →
   unique_columns" for the generic ext; legacy A61 message shape
   preserved.
7. **Defensive config** — non-list unique_columns, non-string items,
   missing fields all no-op or skip-item without raising.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# jsonschema gate: the tests below don't actually call the schema
# validator — they exercise the Python handler directly. But we keep
# the importorskip guard to match the rest of the schema test
# inventory + future-proof against a refactor that adds schema-path
# checks here.
pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---- Helpers -----------------------------------------------------


def _handler():
    """Lazy-import the handler to avoid import-time coupling."""
    from governance.schemas.write_validator import _apply_uniqueness_rules
    return _apply_uniqueness_rules


def _check():
    from governance.schemas.write_validator import _check_unique_columns
    return _check_unique_columns


def _schema(unique_columns: list[str], applies: bool = True) -> dict:
    """Build an in-memory schema declaring the generic extension."""
    return {
        "x-bsa-uniqueness-rules": {
            "applies_to_all_rows": applies,
            "unique_columns": unique_columns,
        },
    }


# ---- Happy path + gates ------------------------------------------


def test_happy_path_no_duplicates_no_violations() -> None:
    rows = [
        {"ID": "A-001", "Name": "alpha"},
        {"ID": "A-002", "Name": "beta"},
    ]
    assert _handler()(rows, _schema(["ID"]), "fake.csv", None) == []


def test_no_extension_declared_noops() -> None:
    """A schema without ``x-bsa-uniqueness-rules`` MUST no-op. Pins
    the default-off semantic so the generic extension is opt-in
    per-schema."""
    rows = [{"ID": "A-001"}, {"ID": "A-001"}]  # would be a dup if enforced
    assert _handler()(rows, {}, "fake.csv", None) == []


def test_applies_to_all_rows_gate_false_noops() -> None:
    """``applies_to_all_rows: false`` MUST gate the handler off —
    same convention as A72's ``x-bsa-foreign-key-rules``."""
    schema = _schema(["ID"], applies=False)
    rows = [{"ID": "A-001"}, {"ID": "A-001"}]  # dup
    assert _handler()(rows, schema, "fake.csv", None) == []


def test_missing_applies_to_all_rows_noops() -> None:
    """Extension present but without the gate → no-op. Forces
    schemas to explicitly opt in."""
    schema = {"x-bsa-uniqueness-rules": {"unique_columns": ["ID"]}}
    rows = [{"ID": "A-001"}, {"ID": "A-001"}]
    assert _handler()(rows, schema, "fake.csv", None) == []


def test_empty_rows_noops() -> None:
    assert _handler()([], _schema(["ID"]), "fake.csv", None) == []


# ---- Per-occurrence reporting ------------------------------------


def test_three_occurrence_case_emits_two_violations() -> None:
    """Same AnchorID on rows 2, 3, 4 → row 3 and row 4 each
    violate against the row-2 sighting. Matches A61's per-occurrence-
    after-first pattern (pinned there by
    test_executable_anchor_binding_three_duplicates_emits_two_violations)."""
    rows = [
        {"ID": "A-001"},  # row 2
        {"ID": "A-001"},  # row 3 — 1st violation
        {"ID": "A-001"},  # row 4 — 2nd violation
    ]
    violations = _handler()(rows, _schema(["ID"]), "fake.csv", None)
    assert len(violations) == 2, f"expected 2 violations; got: {violations}"
    assert "line 3" in violations[0]
    assert "line 4" in violations[1]
    assert "first seen on line 2" in violations[0]
    assert "first seen on line 2" in violations[1]


def test_violation_message_shape_names_the_generic_extension() -> None:
    """Generic-extension violations MUST name ``x-bsa-uniqueness-rules``
    (so operators know which block to edit) — NOT the A61-specific
    ``x-bsa-anchor-binding-rules`` name."""
    rows = [{"ID": "A-001"}, {"ID": "A-001"}]
    violations = _handler()(rows, _schema(["ID"]), "fake.csv", None)
    assert len(violations) == 1
    assert "x-bsa-uniqueness-rules" in violations[0]
    assert "x-bsa-anchor-binding-rules" not in violations[0]


# ---- Blank-cell interaction --------------------------------------


def test_blank_cells_are_not_flagged_as_duplicates() -> None:
    """Two rows with blank ID are NOT a uniqueness violation —
    schema-level required + minLength check covers the blank case
    separately. This prevents noisy double-reporting on a single
    missing cell."""
    rows = [
        {"ID": ""},  # blank row 2
        {"ID": ""},  # blank row 3
        {"ID": "A-001"},  # valid row 4
        {"ID": "A-001"},  # dup row 5 — THIS one violates
    ]
    violations = _handler()(rows, _schema(["ID"]), "fake.csv", None)
    assert len(violations) == 1, (
        f"expected exactly 1 violation (the A-001 dup); got: {violations}"
    )
    assert "line 5" in violations[0]


def test_whitespace_only_cells_treated_as_blank() -> None:
    """Whitespace-only cells (e.g., "   ") strip to empty and
    shouldn't flag as duplicates of each other."""
    rows = [
        {"ID": "  "},
        {"ID": "   "},
        {"ID": "A-001"},
    ]
    violations = _handler()(rows, _schema(["ID"]), "fake.csv", None)
    assert violations == []


def test_whitespace_padded_value_duplicates_stripped_match() -> None:
    """`'A-001'` vs `'A-001 '` (trailing space) should strip-match
    as duplicates — prevents a trivial-whitespace bypass."""
    rows = [
        {"ID": "A-001"},
        {"ID": " A-001 "},  # stripped == A-001
    ]
    violations = _handler()(rows, _schema(["ID"]), "fake.csv", None)
    assert len(violations) == 1
    assert "A-001" in violations[0]


# ---- Multiple columns --------------------------------------------


def test_multiple_unique_columns_enforced_independently() -> None:
    """`unique_columns: [X, Y]` enforces uniqueness in X AND in Y
    SEPARATELY — a row that's unique in X can still violate in Y."""
    rows = [
        {"X": "x-1", "Y": "y-1"},
        {"X": "x-2", "Y": "y-1"},  # dup in Y
        {"X": "x-1", "Y": "y-2"},  # dup in X
    ]
    violations = _handler()(rows, _schema(["X", "Y"]), "fake.csv", None)
    assert len(violations) == 2
    y_vio = [v for v in violations if "Y=" in v]
    x_vio = [v for v in violations if "X=" in v]
    assert len(y_vio) == 1
    assert len(x_vio) == 1


def test_multiple_columns_order_preserved() -> None:
    """Violations MUST be ordered by (column-index, row-index), not
    arbitrarily — Python dict iteration is insertion-ordered so
    this is naturally true, but pin it so a future list→set
    refactor surfaces."""
    rows = [
        {"X": "x-1", "Y": "y-1"},
        {"X": "x-1", "Y": "y-1"},  # dup in BOTH
    ]
    violations = _handler()(rows, _schema(["X", "Y"]), "fake.csv", None)
    assert len(violations) == 2
    # X comes first in the unique_columns list → its violation first.
    assert "X=" in violations[0]
    assert "Y=" in violations[1]


# ---- A61-generic coexistence -------------------------------------


def test_schema_with_both_extensions_gets_both_violations() -> None:
    """A schema that declares BOTH ``x-bsa-anchor-binding-rules``
    (A61-style) AND the generic ``x-bsa-uniqueness-rules`` should
    fire BOTH handlers on the same duplicate — one violation from
    each, attributed to its source extension. Pins that the two
    handlers are independent + that the dispatcher calls both."""
    from governance.schemas.write_validator import (
        _apply_anchor_binding_rules,
        _apply_uniqueness_rules,
    )
    schema = {
        "x-bsa-anchor-binding-rules": {
            "applies_to_all_rows": True,
            "unique_columns": ["ID"],
        },
        "x-bsa-uniqueness-rules": {
            "applies_to_all_rows": True,
            "unique_columns": ["ID"],
        },
    }
    rows = [{"ID": "A-001"}, {"ID": "A-001"}]
    a61_violations = _apply_anchor_binding_rules(rows, schema, "fake.csv", None)
    generic_violations = _apply_uniqueness_rules(rows, schema, "fake.csv", None)
    assert len(a61_violations) == 1
    assert "x-bsa-anchor-binding-rules" in a61_violations[0]
    assert len(generic_violations) == 1
    assert "x-bsa-uniqueness-rules" in generic_violations[0]


# ---- Defensive config --------------------------------------------


def test_unique_columns_not_a_list_noops() -> None:
    """``unique_columns`` field is a string instead of a list → no-op
    (schema misconfig but don't crash)."""
    schema = {
        "x-bsa-uniqueness-rules": {
            "applies_to_all_rows": True,
            "unique_columns": "ID",  # should be list
        },
    }
    rows = [{"ID": "A"}, {"ID": "A"}]
    assert _handler()(rows, schema, "fake.csv", None) == []


def test_unique_columns_none_noops() -> None:
    schema = {
        "x-bsa-uniqueness-rules": {
            "applies_to_all_rows": True,
            "unique_columns": None,
        },
    }
    rows = [{"ID": "A"}, {"ID": "A"}]
    assert _handler()(rows, schema, "fake.csv", None) == []


def test_non_string_column_items_skipped() -> None:
    """If `unique_columns` list contains non-string items, skip
    those items but still enforce the string entries."""
    schema = {
        "x-bsa-uniqueness-rules": {
            "applies_to_all_rows": True,
            "unique_columns": [123, "ID", None, "", "Name"],
        },
    }
    rows = [
        {"ID": "A-001", "Name": "alpha"},
        {"ID": "A-001", "Name": "beta"},  # dup in ID only
    ]
    violations = _handler()(rows, _schema(["ID", "Name"]), "fake.csv", None)
    # Sanity: pure-string-list path.
    violations_defensive = _handler()(rows, schema, "fake.csv", None)
    assert violations == violations_defensive, (
        "non-string item skipping changed the effective behavior"
    )
    assert len(violations) == 1
    assert "ID" in violations[0]


# ---- _check_unique_columns direct (shared helper) -----------------


def test_check_unique_columns_ext_name_is_attributed() -> None:
    """The shared helper uses whatever ``ext_name`` the caller passes,
    so the message attributes to the caller's extension block.
    Pins A61 stays named ``x-bsa-anchor-binding-rules``; generic
    stays named ``x-bsa-uniqueness-rules``; future extensions name
    themselves."""
    rows = [{"ID": "A"}, {"ID": "A"}]
    for ext_name in (
        "x-bsa-anchor-binding-rules",
        "x-bsa-uniqueness-rules",
        "x-bsa-future-extension",
    ):
        violations = _check()(rows, ["ID"], ext_name)
        assert len(violations) == 1
        assert ext_name in violations[0]


# ---- v1.2.10 round-1 Codex Recommendation #1: validator-level path --
# Pins that `_make_csv_validator._validate` actually calls BOTH
# handlers in the correct order (anchor-binding first, generic
# second) on a single schema declaring both extensions. Pre-this-
# test the handlers were only exercised independently; a wire-up
# regression (e.g., dropping the `_apply_uniqueness_rules` call from
# `_validate`) would still pass the direct-handler tests but break
# this one.


def test_validator_path_invokes_both_handlers_on_schema_with_both_extensions(
    tmp_path: Path, monkeypatch,
) -> None:
    """Simulate a synthetic schema that declares BOTH extensions +
    route a CSV with a duplicate ID through the real `_make_csv_validator`
    path. Expect exactly 2 duplicate-value violations — one from each
    handler — with violations ordered A61-first, generic-second
    (matching the `_validate` call order)."""
    from governance.schemas import write_validator

    # Synthetic schema: not a real canonical artifact, just something
    # the loader can return so _make_csv_validator can route a CSV
    # through the per-row + cross-row machinery.
    synthetic_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["ID", "Name"],
        "properties": {
            "ID": {"type": "string", "minLength": 1},
            "Name": {"type": "string", "minLength": 1},
        },
        "additionalProperties": False,
        "x-bsa-csv-columns-order": {"order": ["ID", "Name"]},
        "x-bsa-anchor-binding-rules": {
            "applies_to_all_rows": True,
            "unique_columns": ["ID"],
        },
        "x-bsa-uniqueness-rules": {
            "applies_to_all_rows": True,
            "unique_columns": ["ID"],
        },
    }

    # Monkeypatch the loader so `_make_csv_validator("synthetic")`
    # resolves to our in-memory schema instead of looking for
    # governance/schemas/synthetic.schema.json.
    monkeypatch.setattr(
        write_validator._loader, "load_schema",
        lambda name: synthetic_schema if name == "synthetic" else (
            _orig_load_schema(name)
        ),
    )
    _orig_load_schema = write_validator._loader.load_schema  # noqa: F841

    validator_fn = write_validator._make_csv_validator("synthetic")
    csv_content = (
        "ID,Name\n"
        "A-001,first\n"
        "A-001,dup\n"
    )
    violations = validator_fn("irrelevant/path.csv", csv_content)
    # Filter to duplicate-value violations (schema-level checks might
    # also fire depending on the row shape).
    dup = [v for v in violations if "duplicate value" in v]
    assert len(dup) == 2, (
        f"expected 2 duplicate-value violations (one per handler); "
        f"got {len(dup)}: {dup}"
    )
    # Order: A61's anchor-binding handler is invoked FIRST in
    # `_validate`, so its violation comes first. Generic second.
    assert "x-bsa-anchor-binding-rules" in dup[0], (
        f"expected A61 handler's violation first; got: {dup[0]}"
    )
    assert "x-bsa-uniqueness-rules" in dup[1], (
        f"expected generic handler's violation second; got: {dup[1]}"
    )


# ---- v1.2.10 round-1 Codex Recommendation #2: delegation pin -------
# The refactor's invariant is that `_apply_anchor_binding_rules` calls
# `_check_unique_columns` — NOT that it re-implements the uniqueness
# logic inline. Without this pin, reverting the refactor to an inline
# block would still pass all behavioral tests (the shared helper is
# tested directly). This spy test fails on any revert that bypasses
# the shared helper.


def test_anchor_binding_delegates_to_check_unique_columns(monkeypatch) -> None:
    """Spy on `_check_unique_columns`; confirm
    `_apply_anchor_binding_rules` calls it with the A61-specific
    ext_name. If a future refactor inlines the uniqueness logic
    again, the call-count assertion fails."""
    from governance.schemas import write_validator

    calls: list[tuple[object, object, str]] = []
    original = write_validator._check_unique_columns

    def spy(rows, unique_columns, ext_name):
        calls.append((rows, unique_columns, ext_name))
        return original(rows, unique_columns, ext_name)

    monkeypatch.setattr(write_validator, "_check_unique_columns", spy)

    schema = {
        "x-bsa-anchor-binding-rules": {
            "applies_to_all_rows": True,
            "unique_columns": ["AnchorID"],
        },
    }
    rows = [
        {"AnchorID": "ANC-A-001", "SourceClaimID": "C-001"},
        {"AnchorID": "ANC-A-001", "SourceClaimID": "C-002"},
    ]
    write_validator._apply_anchor_binding_rules(rows, schema, "fake.csv", None)
    # Exactly one call, with the A61 ext_name.
    assert len(calls) == 1, (
        f"_apply_anchor_binding_rules did not delegate to "
        f"_check_unique_columns (got {len(calls)} calls — expected 1). "
        f"Refactor regressed back to inline uniqueness logic?"
    )
    _rows, _cols, ext_name = calls[0]
    assert ext_name == "x-bsa-anchor-binding-rules", (
        f"delegation used wrong ext_name {ext_name!r}; A61 violations "
        f"would lose their source-extension attribution"
    )


def test_uniqueness_handler_delegates_to_check_unique_columns(monkeypatch) -> None:
    """Same delegation pin for the generic handler — MUST route
    through `_check_unique_columns` with the generic ext_name."""
    from governance.schemas import write_validator

    calls: list[tuple[object, object, str]] = []
    original = write_validator._check_unique_columns

    def spy(rows, unique_columns, ext_name):
        calls.append((rows, unique_columns, ext_name))
        return original(rows, unique_columns, ext_name)

    monkeypatch.setattr(write_validator, "_check_unique_columns", spy)

    schema = {
        "x-bsa-uniqueness-rules": {
            "applies_to_all_rows": True,
            "unique_columns": ["ID"],
        },
    }
    rows = [{"ID": "A-001"}, {"ID": "A-001"}]
    write_validator._apply_uniqueness_rules(rows, schema, "fake.csv", None)
    assert len(calls) == 1
    assert calls[0][2] == "x-bsa-uniqueness-rules"
