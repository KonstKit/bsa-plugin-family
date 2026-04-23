"""Tests for `scripts/phase_7_lint.py` + `config/tunables.yaml`
(v1.1.14, Section D — Phase 7 self-improvement loop foundation).

Pins the contract documented in `docs/phase_7_design.md`:

  * The committed `config/tunables.yaml` lints clean (catches drift if
    a tunable's source-line value changes without updating tunables.yaml).
  * Each per-entry check rule (C1..C8) actually triggers on its
    intended failure mode (drift, fake invariant link, missing skill,
    bad change_class, IMMUTABLE_CONFLICT, POLICY_GLOBS violation,
    bad allowed_range, current value out of range).
  * The unique-id check (C4) catches duplicate IDs across entries.
  * The POLICY_GLOBS reader stays in lockstep with
    `scripts/compute_canon_hash.py` (tolerates both tuple + list
    literal forms).

Plus a doc-presence pin for `docs/phase_7_design.md` (catches
accidental rename / removal).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LINT_PATH = REPO_ROOT / "scripts" / "phase_7_lint.py"
TUNABLES_PATH = REPO_ROOT / "config" / "tunables.yaml"
DESIGN_DOC = REPO_ROOT / "docs" / "phase_7_design.md"


@pytest.fixture(scope="module")
def lint():
    """Load `scripts/phase_7_lint.py` as a module (per the security_audit
    pattern other tests in this repo use)."""
    spec = importlib.util.spec_from_file_location("phase_7_lint", LINT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def yaml_module():
    return pytest.importorskip("yaml")


# ---- Committed-state pins -------------------------------------------


def test_committed_tunables_lints_clean(lint) -> None:
    """The committed config/tunables.yaml MUST pass all 8 checks. If
    this fails, run `python3 scripts/phase_7_lint.py` to see findings."""
    passed, findings = lint.run_lint()
    assert passed, "tunables.yaml has lint findings:\n" + "\n".join(
        f"  {f.format()}" for f in findings
    )


def test_design_doc_exists_and_has_required_sections() -> None:
    """v1.1.14 added docs/phase_7_design.md. Pin its presence + the
    section headers other docs reference (per docs/faq.md +
    governance/immutable_invariants.md cross-references)."""
    assert DESIGN_DOC.is_file()
    body = DESIGN_DOC.read_text(encoding="utf-8")
    for header in (
        "# Phase 7 Self-Improvement Loop",
        "## Tunable inventory",
        "## IMMUTABLE_CONFLICT detection",
        "## Safety contract",
    ):
        assert header in body, f"design doc missing section: {header}"


def test_committed_tunables_has_at_least_one_entry_per_change_class(
    lint, yaml_module
) -> None:
    """Pins that the committed inventory exercises BOTH change_classes
    — catches the case where someone accidentally collapses everything
    to L2_proposal_only (which would make Phase 7 L1 vacuous)."""
    doc = yaml_module.safe_load(TUNABLES_PATH.read_text(encoding="utf-8"))
    classes = {e["change_class"] for e in doc["tunables"]}
    assert "L1_auto_tunable" in classes, (
        "committed tunables.yaml has NO L1_auto_tunable entries — "
        "Phase 7 L1 would be vacuous"
    )
    assert "L2_proposal_only" in classes, (
        "committed tunables.yaml has NO L2_proposal_only entries — "
        "the safety contract was loosened"
    )


def test_committed_tunables_has_at_least_one_invariant_link(
    lint, yaml_module
) -> None:
    """Pins that at least one tunable carries a linked_invariants entry
    — catches the case where the cross-reference contract is silently
    broken (e.g., immutable_invariants.md gets renamed without updating
    tunables.yaml)."""
    doc = yaml_module.safe_load(TUNABLES_PATH.read_text(encoding="utf-8"))
    has_link = any(
        e.get("linked_invariants") for e in doc["tunables"]
    )
    assert has_link, (
        "committed tunables.yaml has NO linked_invariants — "
        "the cross-reference between tunables + invariants is gone"
    )


# ---- Per-check unit coverage (synthetic broken examples) -----------


def _baseline_entry() -> dict:
    """A minimal valid tunable entry, used as a base for synthetic
    broken-example tests."""
    return {
        "id": "test_tunable_xyz",
        "current_value": "0.50",
        "allowed_range": [0.40, 0.60],
        "owner_skill": "governance",
        "source_file": "scripts/perf_bench.py",  # contains REGRESSION_THRESHOLD
        "source_line": 83,
        "linked_invariants": [],
        "change_class": "L2_proposal_only",
        "rationale": "test only",
    }


def test_C1_drift_detected(lint, tmp_path) -> None:
    """If source_file:source_line does NOT contain current_value, C1 fires."""
    findings: list = []
    entry = _baseline_entry()
    entry["current_value"] = "999.99"  # not in scripts/perf_bench.py:83
    lint.check_source_line_matches(entry, findings)
    assert any(f.code == "C1_VALUE_DRIFT" for f in findings)


def test_C1_missing_source_file(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["source_file"] = "this/path/does/not/exist.py"
    lint.check_source_line_matches(entry, findings)
    assert any(f.code == "C1_NO_SOURCE_FILE" for f in findings)


def test_C1_line_out_of_range(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["source_line"] = 999_999  # past EOF
    lint.check_source_line_matches(entry, findings)
    assert any(f.code == "C1_LINE_OUT_OF_RANGE" for f in findings)


def test_C2_invariant_format_invalid(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["linked_invariants"] = ["INV-XX"]  # not in INV-01..INV-10
    lint.check_invariants_exist(entry, valid_inv_ids=set(), findings=findings)
    assert any(f.code == "C2_INVARIANT_BAD_FORMAT" for f in findings)


def test_C2_invariant_not_declared(lint) -> None:
    """A well-formed but absent INV (e.g., INV-09 in a hypothetical state
    where invariants.md only declares INV-01) must trigger
    C2_INVARIANT_NOT_DECLARED. Note: the lint's INV_ID_RE intentionally
    only allows INV-01..INV-10 (the current immutable-invariants set);
    INV-99 would trigger C2_INVARIANT_BAD_FORMAT, not the not-declared
    check."""
    findings: list = []
    entry = _baseline_entry()
    entry["linked_invariants"] = ["INV-09"]  # well-formed shape, but
    # we pass an empty valid set to simulate "invariants.md doesn't
    # declare INV-09" — exercises the second arm of check_invariants_exist.
    lint.check_invariants_exist(entry, valid_inv_ids={"INV-01"}, findings=findings)
    assert any(f.code == "C2_INVARIANT_NOT_DECLARED" for f in findings)


def test_C3_skill_missing(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["owner_skill"] = "bsa-nonexistent-skill"
    lint.check_owner_skill_exists(entry, findings)
    assert any(f.code == "C3_SKILL_MISSING" for f in findings)


def test_C3_sidecar_missing(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["owner_skill"] = "sidecar:nonexistent"
    lint.check_owner_skill_exists(entry, findings)
    assert any(f.code == "C3_SIDECAR_MISSING" for f in findings)


def test_C4_duplicate_id(lint) -> None:
    findings: list = []
    entries = [_baseline_entry(), _baseline_entry()]  # both have id 'test_tunable_xyz'
    lint.check_unique_ids(entries, findings)
    assert any(f.code == "C4_DUPLICATE_ID" for f in findings)


def test_C5_immutable_conflict_fires_on_l1_with_invariants(lint) -> None:
    """Headline Phase 7 safety rule: L1_auto_tunable + linked_invariants
    is forbidden by the design contract."""
    findings: list = []
    entry = _baseline_entry()
    entry["change_class"] = "L1_auto_tunable"
    entry["linked_invariants"] = ["INV-01"]
    lint.check_immutable_conflict(entry, findings)
    assert any(f.code == "C5_IMMUTABLE_CONFLICT" for f in findings)


def test_C5_immutable_conflict_silent_on_l2(lint) -> None:
    """L2_proposal_only with linked_invariants is fine — L2 always
    requires analyst sign-off, so invariant-touching is allowed."""
    findings: list = []
    entry = _baseline_entry()
    entry["change_class"] = "L2_proposal_only"
    entry["linked_invariants"] = ["INV-01"]
    lint.check_immutable_conflict(entry, findings)
    assert not any(f.code == "C5_IMMUTABLE_CONFLICT" for f in findings)


def test_C5_immutable_conflict_silent_on_l1_no_invariants(lint) -> None:
    """L1_auto_tunable with empty linked_invariants is fine — that's
    the safe path the design contract intends for true layout/UX
    tunables (no governance interaction)."""
    findings: list = []
    entry = _baseline_entry()
    entry["change_class"] = "L1_auto_tunable"
    entry["linked_invariants"] = []
    lint.check_immutable_conflict(entry, findings)
    assert not any(f.code == "C5_IMMUTABLE_CONFLICT" for f in findings)


def test_C6_l1_in_policy_globs_fires(lint) -> None:
    """L1_auto_tunable + source_file in POLICY_GLOBS = hard fail.
    Auto-merging a value inside canonical state would silently bump
    the canon hash — breaks the two-semver discipline."""
    findings: list = []
    entry = _baseline_entry()
    entry["change_class"] = "L1_auto_tunable"
    # immutable_invariants.md IS in POLICY_GLOBS per scripts/compute_canon_hash.py
    entry["source_file"] = "governance/immutable_invariants.md"
    lint.check_policy_globs_neutrality(
        entry,
        policy_globs=["governance/immutable_invariants.md"],
        findings=findings,
    )
    assert any(f.code == "C6_POLICY_GLOB_VIOLATION" for f in findings)


def test_C6_l2_in_policy_globs_silent(lint) -> None:
    """L2_proposal_only entries MAY live in POLICY_GLOBS — the analyst-
    sign-off step naturally includes a manifest version bump + canon-
    hash refresh, so the two-semver discipline stays intact. The
    committed tunables.yaml exercises this path (tier_weight_T*,
    KPI targets — all L2_proposal_only inside POLICY_GLOBS)."""
    findings: list = []
    entry = _baseline_entry()
    entry["change_class"] = "L2_proposal_only"
    entry["source_file"] = "governance/immutable_invariants.md"
    lint.check_policy_globs_neutrality(
        entry,
        policy_globs=["governance/immutable_invariants.md"],
        findings=findings,
    )
    assert not findings, (
        "L2 in POLICY_GLOBS must NOT trigger C6 — analyst sign-off "
        "covers the canon-hash bump."
    )


def test_C6_policy_glob_safe_path(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["source_file"] = "scripts/perf_bench.py"  # NOT in POLICY_GLOBS
    lint.check_policy_globs_neutrality(
        entry,
        policy_globs=["governance/immutable_invariants.md"],
        findings=findings,
    )
    assert not findings


def test_C7_change_class_unknown(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["change_class"] = "L0_yolo"  # not in allowed set
    lint.check_change_class(entry, findings)
    assert any(f.code == "C7_CHANGE_CLASS_UNKNOWN" for f in findings)


def test_C8_range_inverted(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["allowed_range"] = [1.0, 0.5]  # min > max
    lint.check_allowed_range(entry, findings)
    assert any(f.code == "C8_RANGE_INVERTED" for f in findings)


def test_C8_current_out_of_range(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["current_value"] = "5.0"  # outside [0.40, 0.60]
    lint.check_allowed_range(entry, findings)
    assert any(f.code == "C8_CURRENT_OUT_OF_RANGE" for f in findings)


def test_C8_range_malformed_length(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["allowed_range"] = [0.5]  # only one element
    lint.check_allowed_range(entry, findings)
    assert any(f.code == "C8_RANGE_MALFORMED" for f in findings)


def test_C8_range_non_numeric(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["allowed_range"] = ["low", "high"]  # strings, not numbers
    lint.check_allowed_range(entry, findings)
    assert any(f.code == "C8_RANGE_NON_NUMERIC" for f in findings)


# ---- POLICY_GLOBS reader contract -------------------------------------


def test_read_policy_globs_returns_nonempty(lint) -> None:
    """Smoke: the reader actually finds POLICY_GLOBS in the canon-hash
    script. If this fails, scripts/compute_canon_hash.py was refactored
    and scripts/phase_7_lint.py needs updating in lockstep."""
    globs = lint._read_policy_globs()
    assert globs, "POLICY_GLOBS came back empty"
    # Sanity: canon-hash script must include immutable_invariants.md
    # (the foundation governance file).
    assert "governance/immutable_invariants.md" in globs


def test_read_policy_globs_handles_list_literal(lint, tmp_path, monkeypatch) -> None:
    """v1.1.14 round-1 (Codex): the AST reader claims to handle BOTH
    tuple `(...)` and list `[...]` literal forms — the canon-hash
    script currently uses tuple, but a future refactor to list (e.g.,
    if maintainers want to mutate POLICY_GLOBS at import time) must
    not silently break the lint.

    Synthesise a tiny script with `POLICY_GLOBS = [...]` and verify
    the reader recognises it. Uses monkeypatch to redirect REPO_ROOT
    so the synthetic script is read instead of the real one."""
    fake_canon = tmp_path / "scripts" / "compute_canon_hash.py"
    fake_canon.parent.mkdir(parents=True, exist_ok=True)
    fake_canon.write_text(
        '"""Synthetic canon-hash script for phase_7_lint testing."""\n'
        'POLICY_GLOBS = [\n'
        '    # Comment with embedded ( and ) and ] chars to fool a regex reader.\n'
        '    "alpha/file.md",\n'
        '    "beta/file.md",\n'
        ']\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(lint, "REPO_ROOT", tmp_path)
    globs = lint._read_policy_globs()
    assert globs == ["alpha/file.md", "beta/file.md"], (
        f"AST reader should handle list-literal POLICY_GLOBS too "
        f"(round-1 contract); got {globs!r}"
    )


def test_read_policy_globs_handles_tuple_literal(lint, tmp_path, monkeypatch) -> None:
    """Mirror of the list test for the tuple literal form — pins both
    sides of the AST reader's documented promise."""
    fake_canon = tmp_path / "scripts" / "compute_canon_hash.py"
    fake_canon.parent.mkdir(parents=True, exist_ok=True)
    fake_canon.write_text(
        'POLICY_GLOBS: tuple[str, ...] = (\n'
        '    # Embedded ( ) ] chars to fool a regex reader.\n'
        '    "x.md",\n'
        '    "y.md",\n'
        ')\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(lint, "REPO_ROOT", tmp_path)
    globs = lint._read_policy_globs()
    assert globs == ["x.md", "y.md"]


def test_read_invariant_ids_only_counts_declarations(lint, tmp_path, monkeypatch) -> None:
    """v1.1.14 round-1 (Codex blocker): _read_invariant_ids() previously
    regexed every INV-XX mention, which let prose references like
    'see INV-09 below' satisfy C2 even if the actual declaration was
    gone. Now we parse only `### INV-XX:` headers."""
    fake_inv = tmp_path / "governance" / "immutable_invariants.md"
    fake_inv.parent.mkdir(parents=True, exist_ok=True)
    fake_inv.write_text(
        "# Immutable Invariants\n"
        "\n"
        "Historical note: INV-09 was removed in v0.5 (no longer authoritative).\n"
        "\n"
        "### INV-01: Evidence-binding\n"
        "...body...\n"
        "\n"
        "### INV-02: Single-writer canonical\n"
        "...body...\n"
        "\n"
        "Some prose references INV-99 just to talk about it.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(lint, "INVARIANTS_PATH", fake_inv)
    ids = lint._read_invariant_ids()
    assert ids == {"INV-01", "INV-02"}, (
        f"only h2/h3 headers should count as declarations; "
        f"prose mentions of INV-09 + INV-99 must NOT slip in. Got {ids!r}"
    )


# ---- _parse_numeric edge cases ---------------------------------------


def test_parse_numeric_handles_gte_prefix(lint) -> None:
    assert lint._parse_numeric(">= 0.75") == 0.75
    assert lint._parse_numeric("≥ 0.90") == 0.90


def test_parse_numeric_handles_bare_number(lint) -> None:
    assert lint._parse_numeric("1.00") == 1.00
    assert lint._parse_numeric("120") == 120.0


def test_parse_numeric_returns_none_for_enum(lint) -> None:
    assert lint._parse_numeric("L1_auto_tunable") is None
