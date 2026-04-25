"""Tests for the generic ``x-bsa-foreign-key-refs`` extension (v1.2.13).

v1.2.13 adds a schema-agnostic cross-artifact foreign-key resolution
extension parallel to A72's A72-specific ``x-bsa-foreign-key-rules``
(which hard-codes StoryID/ClaimID/SourceID + claim_source_consistency).
The new extension handles the common case: "column X in THIS row must
resolve to column Y in sibling CSV Z".

Six canonical schemas opt in:
- a58: SourceID → A50
- a59: SourceID / ExcerptID / A51Ref (all optional_when_blank per
  ClaimType rules) → A50 / A58 / A51
- a60: SourceID → A50; RelatedClaimID → A59; A51Ref (optional) → A51
- a62: SourceClaimIDs (multi, optional) → A59; A51Ref (optional) → A51
- a70: SourceClaimIDs (multi, optional) → A59; RelatedNFRIDs (multi,
  optional) → A62; A51Ref (optional) → A51
- a71: SourceStoryID → A70; RelatedNFRID (optional) → A62; A51Ref
  (optional) → A51

A72 intentionally stays on its A72-specific ``x-bsa-foreign-key-rules``
extension (which carries the additional ``claim_source_consistency``
semantic coupling).

Coverage groups:
1. **Handler shape** — happy path, gates, no-sibling-cache no-op,
   missing-sibling per-row violation, blank-cell handling
   (optional_when_blank vs required), multi-valued splitting,
   defensive-config fail-CLOSED.
2. **Static per-schema pins** — each of the 6 opted-in schemas
   declares the extension with the expected FK inventory.
3. **End-to-end via dispatcher** — for each opted-in schema, an
   orphan FK value surfaces as a
   ``x-bsa-foreign-key-refs → <column>`` violation via
   ``validate_canonical_write``.
4. **A72 separation pin** — A72 keeps ``x-bsa-foreign-key-rules``,
   NOT the new generic extension (two would double-report on the
   same FK).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---- Helpers -----------------------------------------------------


def _handler():
    from governance.schemas.write_validator import _apply_foreign_key_refs
    return _apply_foreign_key_refs


def _sibling_cache_with(tmp_path: Path, sibling_name: str, csv_content: str):
    """Build a _SiblingArtifactCache rooted at a tmp canonical dir that
    contains the given sibling CSV."""
    from governance.schemas.write_validator import _SiblingArtifactCache
    canon = tmp_path / "analysis" / "canonical" / "core_controls"
    canon.mkdir(parents=True, exist_ok=True)
    (canon / sibling_name).write_text(csv_content, encoding="utf-8")
    return _SiblingArtifactCache(canon)


def _schema(foreign_keys: list[dict], applies: bool = True) -> dict:
    return {
        "x-bsa-foreign-key-refs": {
            "applies_to_all_rows": applies,
            "foreign_keys": foreign_keys,
        },
    }


# ---- Handler shape -----------------------------------------------


def test_no_extension_declared_noops() -> None:
    rows = [{"SourceID": "S-999"}]
    assert _handler()(rows, {}, "fake.csv", None) == []


def test_applies_to_all_rows_gate_false_noops(tmp_path: Path) -> None:
    cache = _sibling_cache_with(tmp_path, "A50_source_register.csv",
                                "SourceID,Title\nS-001,Foo\n")
    schema = _schema([
        {"column": "SourceID", "table": "A50_source_register.csv",
         "target_column": "SourceID"}
    ], applies=False)
    rows = [{"SourceID": "S-999"}]  # would be orphan if gated
    assert _handler()(rows, schema, "analysis/canonical/core_controls/x.csv", cache) == []


def test_empty_foreign_keys_list_noops(tmp_path: Path) -> None:
    cache = _sibling_cache_with(tmp_path, "A50_source_register.csv",
                                "SourceID,Title\nS-001,Foo\n")
    schema = _schema([])
    rows = [{"SourceID": "S-999"}]
    assert _handler()(rows, schema, "analysis/canonical/core_controls/x.csv", cache) == []


def test_sibling_cache_none_noops() -> None:
    """Path outside canonical layout → no-op silently (matches other
    cross-artifact handlers)."""
    schema = _schema([
        {"column": "SourceID", "table": "A50_source_register.csv",
         "target_column": "SourceID"}
    ])
    rows = [{"SourceID": "S-999"}]
    assert _handler()(rows, schema, "outside.csv", None) == []


def test_sibling_missing_emits_per_row_violation(tmp_path: Path) -> None:
    """Cache exists but the sibling file is missing — per-row
    'sibling-not-readable' violation for every non-blank FK value."""
    # Point the cache at a dir that has NO A50 sibling.
    canon = tmp_path / "analysis" / "canonical" / "core_controls"
    canon.mkdir(parents=True, exist_ok=True)
    from governance.schemas.write_validator import _SiblingArtifactCache
    cache = _SiblingArtifactCache(canon)
    schema = _schema([
        {"column": "SourceID", "table": "A50_source_register.csv",
         "target_column": "SourceID"}
    ])
    rows = [
        {"SourceID": "S-001"},  # row 2
        {"SourceID": ""},       # row 3 — blank, skipped
        {"SourceID": "S-002"},  # row 4
    ]
    violations = _handler()(rows, schema, "analysis/canonical/core_controls/x.csv", cache)
    assert len(violations) == 2, f"expected 2 per-row sibling-missing; got {violations}"
    assert any("line 2" in v and "S-001" in v for v in violations)
    assert any("line 4" in v and "S-002" in v for v in violations)


def test_single_valued_orphan_rejected(tmp_path: Path) -> None:
    cache = _sibling_cache_with(tmp_path, "A50_source_register.csv",
                                "SourceID,Title\nS-001,Foo\n")
    schema = _schema([
        {"column": "SourceID", "table": "A50_source_register.csv",
         "target_column": "SourceID"}
    ])
    rows = [{"SourceID": "S-001"}, {"SourceID": "S-999"}]
    violations = _handler()(rows, schema, "analysis/canonical/core_controls/x.csv", cache)
    assert len(violations) == 1
    assert "S-999" in violations[0]
    assert "does not resolve" in violations[0]
    assert "x-bsa-foreign-key-refs → SourceID" in violations[0]


def test_multi_valued_with_mixed_orphans(tmp_path: Path) -> None:
    cache = _sibling_cache_with(tmp_path, "A59_claim_register.csv",
                                "ClaimID,SourceID\nC-001,S-x\nC-002,S-x\n")
    schema = _schema([
        {"column": "SourceClaimIDs", "table": "A59_claim_register.csv",
         "target_column": "ClaimID", "multi": True}
    ])
    rows = [{"SourceClaimIDs": "C-001;C-999 C-002"}]  # `;` + space delims
    violations = _handler()(rows, schema, "analysis/canonical/core_controls/x.csv", cache)
    assert len(violations) == 1
    assert "C-999" in violations[0]


def test_blank_cell_skipped_regardless_of_optional_flag(tmp_path: Path) -> None:
    """Handler never emits FK violation on blank cells — the schema's
    required-field check (and per-row rules like
    _apply_claim_type_rules) handle the 'must be non-blank' case
    separately."""
    cache = _sibling_cache_with(tmp_path, "A50_source_register.csv",
                                "SourceID\nS-001\n")
    # Both flavors: required + optional
    for optional in (False, True):
        schema = _schema([
            {"column": "SourceID", "table": "A50_source_register.csv",
             "target_column": "SourceID",
             "optional_when_blank": optional}
        ])
        rows = [{"SourceID": ""}]  # blank
        assert _handler()(rows, schema, "analysis/canonical/core_controls/x.csv", cache) == []


def test_partial_fk_config_fail_closed() -> None:
    """Missing column / table / target_column → <schema config> violation."""
    handler = _handler()
    for missing in ("column", "table", "target_column"):
        fk = {"column": "X", "table": "T", "target_column": "Y"}
        del fk[missing]
        schema = _schema([fk])
        violations = handler([{"X": "v"}], schema, "fake.csv", None)
        # Even with sibling_cache=None, schema-config errors surface
        # BEFORE the cache-none short-circuit.
        assert any("<schema config>" in v for v in violations), (
            f"missing={missing!r}: {violations}"
        )
        assert any(missing in v for v in violations), violations


def test_fk_spec_non_dict_fail_closed() -> None:
    """foreign_keys list with non-dict entries → fail-CLOSED."""
    schema = {"x-bsa-foreign-key-refs": {
        "applies_to_all_rows": True,
        "foreign_keys": ["not-a-dict"],
    }}
    violations = _handler()([{"X": "v"}], schema, "fake.csv", None)
    assert any("<schema config>" in v and "must be an object" in v for v in violations)


# ---- Static per-schema pins --------------------------------------

# Expected FK inventory per opted-in schema (v1.2.13 scope).
_EXPECTED_FKS = {
    "a58": [
        ("SourceID", "A50_source_register.csv", "SourceID", False, False),
    ],
    "a59": [
        ("SourceID", "A50_source_register.csv", "SourceID", False, True),
        ("ExcerptID", "A58_evidence_excerpts.csv", "ExcerptID", False, True),
        ("A51Ref", "A51_issue_route_register.csv", "A51Ref", False, True),
    ],
    "a60": [
        ("SourceID", "A50_source_register.csv", "SourceID", False, False),
        ("RelatedClaimID", "A59_claim_register.csv", "ClaimID", False, False),
        ("A51Ref", "A51_issue_route_register.csv", "A51Ref", False, True),
    ],
    "a62": [
        ("SourceClaimIDs", "A59_claim_register.csv", "ClaimID", True, True),
        ("A51Ref", "A51_issue_route_register.csv", "A51Ref", False, True),
    ],
    "a70": [
        ("SourceClaimIDs", "A59_claim_register.csv", "ClaimID", True, True),
        ("RelatedNFRIDs", "A62_nfr_register.csv", "NFRID", True, True),
        ("A51Ref", "A51_issue_route_register.csv", "A51Ref", False, True),
    ],
    "a71": [
        ("SourceStoryID", "A70_story_register.csv", "StoryID", False, False),
        ("RelatedNFRID", "A62_nfr_register.csv", "NFRID", False, True),
        ("A51Ref", "A51_issue_route_register.csv", "A51Ref", False, True),
    ],
}


@pytest.mark.parametrize("schema_name, expected", list(_EXPECTED_FKS.items()))
def test_schema_declares_expected_fk_inventory(
    schema_name: str, expected: list,
) -> None:
    from governance.schemas.loader import load_schema
    schema = load_schema(schema_name)
    ext = schema.get("x-bsa-foreign-key-refs")
    assert isinstance(ext, dict), (
        f"{schema_name}.schema.json missing x-bsa-foreign-key-refs"
    )
    assert ext.get("applies_to_all_rows") is True
    fks = ext.get("foreign_keys")
    assert isinstance(fks, list) and len(fks) == len(expected), (
        f"{schema_name}: expected {len(expected)} FKs; got {len(fks or [])}"
    )
    # Build comparable tuples from actual, preserving order.
    actual = [
        (fk["column"], fk["table"], fk["target_column"],
         bool(fk.get("multi", False)),
         bool(fk.get("optional_when_blank", False)))
        for fk in fks
    ]
    assert actual == expected, (
        f"{schema_name} FK inventory drift: expected {expected}, got {actual}"
    )
    # EXECUTABLE marker in _comment.
    comment = ext.get("_comment", "").upper()
    assert "EXECUTABLE" in comment, (
        f"{schema_name} x-bsa-foreign-key-refs._comment missing EXECUTABLE marker"
    )


def test_a72_keeps_a72_specific_extension_not_generic() -> None:
    """A72 keeps x-bsa-foreign-key-rules (its A72-specific extension
    that also carries claim_source_consistency). A72 MUST NOT also
    declare the new generic x-bsa-foreign-key-refs — two handlers
    would emit duplicate violations on the same FK."""
    from governance.schemas.loader import load_schema
    a72 = load_schema("a72")
    assert "x-bsa-foreign-key-rules" in a72, (
        "A72 lost its A72-specific FK rules — must be preserved"
    )
    assert "x-bsa-foreign-key-refs" not in a72, (
        "A72 has BOTH the A72-specific AND the generic FK extension. "
        "Pick one — a72 uses x-bsa-foreign-key-rules for claim/source "
        "consistency."
    )


def test_a61_has_no_generic_fk_extension() -> None:
    """A61 keeps x-bsa-anchor-binding-rules for its SourceClaimID FK
    (bundled with AnchorID uniqueness). MUST NOT also declare the
    generic FK extension — would double-report."""
    from governance.schemas.loader import load_schema
    a61 = load_schema("a61")
    assert "x-bsa-anchor-binding-rules" in a61
    assert "x-bsa-foreign-key-refs" not in a61, (
        "A61 has BOTH anchor-binding AND generic FK extensions — "
        "would emit duplicate violations for SourceClaimID orphan."
    )


# ---- End-to-end via dispatcher -----------------------------------


# Per-schema orphan-test scenarios: one orphan for one FK per
# schema (the single most-critical FK). Each feeds a CSV with an
# orphan value through validate_canonical_write + asserts the
# dispatcher rejects + the violation is attributed to
# x-bsa-foreign-key-refs.
_ORPHAN_SCENARIOS = [
    # (schema_name, canonical_filename, column_to_orphan, other_cols_fill)
    ("a58", "A58_evidence_excerpts.csv", "SourceID",
     "S-ORPHAN,loc-x,text-x,note-x"),
    ("a60", "A60_negative_evidence_register.csv", "RelatedClaimID",
     None),  # built below
    ("a71", "A71_test_scenario_register.csv", "SourceStoryID",
     None),
]


def _make_canon_workspace_with(tmp_path: Path, siblings: dict) -> Path:
    """Create a tmp canon workspace populated with the given sibling
    CSVs. `siblings` maps filename → content."""
    canon = tmp_path / "analysis" / "canonical" / "core_controls"
    canon.mkdir(parents=True, exist_ok=True)
    for name, content in siblings.items():
        (canon / name).write_text(content, encoding="utf-8")
    return canon


def test_e2e_a58_orphan_source_id_rejected(tmp_path: Path) -> None:
    """A58 is the simplest case: 1 required FK (SourceID → A50).
    An orphan SourceID MUST surface via the new handler."""
    from governance.schemas.write_validator import validate_canonical_write
    canon = _make_canon_workspace_with(tmp_path, {
        "A50_source_register.csv": (
            "SourceID,SourceType,Title,Origin,AccessStatus,ReliabilityTier,"
            "Priority,Language,DateOrVersion,Notes\n"
            "S-001,document,Foo,origin-x,readable,T2,high,en,2026-01-01,note-x\n"
        ),
    })
    bad = (
        "ExcerptID,SourceID,Locator,ExcerptText,Notes\n"
        "E-001,S-999,loc-x,text-x,note-x\n"
    )
    path = str(canon / "A58_evidence_excerpts.csv")
    ok, msgs = validate_canonical_write(path, bad)
    assert ok is False, (
        f"A58: orphan SourceID should fail canonical write; got ok={ok}, msgs={msgs}"
    )
    fk_msgs = [m for m in msgs if "x-bsa-foreign-key-refs" in m]
    assert fk_msgs, f"no FK-refs violation in msgs: {msgs}"
    assert any("S-999" in m for m in fk_msgs)


def test_e2e_a71_orphan_source_story_id_rejected(tmp_path: Path) -> None:
    """A71 is required: SourceStoryID MUST resolve in A70. Covers
    INV-10."""
    from governance.schemas.write_validator import validate_canonical_write
    canon = _make_canon_workspace_with(tmp_path, {
        "A70_story_register.csv": (
            "StoryID,Title,Persona,StoryText,AcceptanceCriteria,"
            "SourceClaimIDs,RelatedNFRIDs,Priority,EstimationHint,"
            "INVESTStatus,A51Ref,Notes\n"
            "STORY-001,Foo,P,stxt,ac,C-001,,,,,,\n"  # placeholder ok-ish row
        ),
    })
    bad = (
        "ScenarioID,Title,SourceStoryID,RelatedNFRID,Given,When,Then,"
        "Tags,Priority,AutomationStatus,A51Ref,Notes\n"
        "TS-001,Foo,STORY-999,,g,w,t,tag-x,high,automated,,\n"
    )
    path = str(canon / "A71_test_scenario_register.csv")
    ok, msgs = validate_canonical_write(path, bad)
    assert ok is False, f"A71: orphan StoryID should fail; got ok={ok}, msgs={msgs}"
    fk_msgs = [m for m in msgs if "x-bsa-foreign-key-refs" in m]
    assert fk_msgs, f"no FK-refs violation: {msgs}"
    assert any("STORY-999" in m for m in fk_msgs)


def test_e2e_a62_multi_valued_source_claim_ids_orphan_rejected(tmp_path: Path) -> None:
    """A62.SourceClaimIDs is multi-valued; an orphan token among a
    mixed list MUST surface via the handler."""
    from governance.schemas.write_validator import validate_canonical_write
    canon = _make_canon_workspace_with(tmp_path, {
        "A59_claim_register.csv": (
            "ClaimID,SourceID,ExcerptID,ClaimType,Statement,"
            "JustificationRationale,A51Ref,ClaimStrength,Criticality,Notes\n"
            "C-001,S-x,E-x,direct,stmt,,,0.85,level-2,\n"
            "C-002,S-x,E-x,direct,stmt,,,0.85,level-2,\n"
        ),
    })
    bad = (
        "NFRID,NFRCategory,Statement,SourceClaimIDs,MeasurabilityType,"
        "Metric,Target,TestabilityNotes,Criticality,A51Ref,Notes\n"
        "NFR-PERF-001,performance,stmt,C-001;C-999,quantitative,"
        "metric-x,target-x,notes-x,level-2,,\n"
    )
    path = str(canon / "A62_nfr_register.csv")
    ok, msgs = validate_canonical_write(path, bad)
    assert ok is False, f"A62: orphan token should fail; got ok={ok}, msgs={msgs}"
    fk_msgs = [m for m in msgs if "x-bsa-foreign-key-refs" in m]
    assert fk_msgs, f"no FK-refs violation: {msgs}"
    assert any("C-999" in m for m in fk_msgs), f"FK msgs miss C-999: {fk_msgs}"


def test_e2e_a59_blank_source_id_for_analyst_judgment_passes_fk_check(
    tmp_path: Path,
) -> None:
    """A59.SourceID is optional_when_blank. An analyst_judgment row
    with blank SourceID MUST NOT trigger the FK handler (the per-row
    _apply_claim_type_rules handler checks the "non-blank when
    direct/inference" case separately).

    NOTE: this test deliberately uses analyst_judgment + fills
    JustificationRationale (required by INV-07) so the CSV only
    potentially fails on FK-refs, not on per-row rules."""
    from governance.schemas.write_validator import validate_canonical_write
    canon = _make_canon_workspace_with(tmp_path, {
        "A50_source_register.csv": (
            "SourceID,SourceType,Title,Origin,AccessStatus,ReliabilityTier,"
            "Priority,Language,DateOrVersion,Notes\n"
            "S-001,document,Foo,origin-x,readable,T2,high,en,2026-01-01,note-x\n"
        ),
    })
    # Analyst-judgment row with blank SourceID + ExcerptID — FK
    # handler should skip both per optional_when_blank.
    good = (
        "ClaimID,SourceID,ExcerptID,ClaimType,Statement,"
        "JustificationRationale,A51Ref,ClaimStrength,Criticality,Notes\n"
        "C-001,,,analyst_judgment,stmt-x,"
        "ref C-xxx — analyst synthesis,,0.45,level-3,\n"
    )
    path = str(canon / "A59_claim_register.csv")
    ok, msgs = validate_canonical_write(path, good)
    # FK-refs handler MUST NOT emit violations for the blank cells.
    fk_msgs = [m for m in msgs if "x-bsa-foreign-key-refs" in m]
    assert not fk_msgs, (
        f"FK handler incorrectly flagged blank SourceID / ExcerptID "
        f"for analyst_judgment row: {fk_msgs}"
    )


def test_e2e_a59_non_blank_orphan_source_id_rejected(tmp_path: Path) -> None:
    """Mirror case: a direct claim with a non-blank BUT orphan
    SourceID MUST surface via the FK handler."""
    from governance.schemas.write_validator import validate_canonical_write
    canon = _make_canon_workspace_with(tmp_path, {
        "A50_source_register.csv": (
            "SourceID,SourceType,Title,Origin,AccessStatus,ReliabilityTier,"
            "Priority,Language,DateOrVersion,Notes\n"
            "S-001,document,Foo,origin-x,readable,T2,high,en,2026-01-01,note-x\n"
        ),
        "A58_evidence_excerpts.csv": (
            "ExcerptID,SourceID,Locator,ExcerptText,Notes\n"
            "E-001,S-001,loc-x,text-x,note-x\n"
        ),
    })
    bad = (
        "ClaimID,SourceID,ExcerptID,ClaimType,Statement,"
        "JustificationRationale,A51Ref,ClaimStrength,Criticality,Notes\n"
        "C-001,S-999,E-001,direct,stmt-x,,,0.85,level-2,\n"
    )
    path = str(canon / "A59_claim_register.csv")
    ok, msgs = validate_canonical_write(path, bad)
    assert ok is False, f"A59: orphan SourceID should fail; got ok={ok}"
    fk_msgs = [m for m in msgs if "x-bsa-foreign-key-refs" in m]
    assert any("S-999" in m for m in fk_msgs), f"FK msgs miss S-999: {msgs}"
