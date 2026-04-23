"""Cross-artifact validator regression tests (v1.1.3, B1).

Closes:
  * TODO-S8-01-X-ARTIFACT-NFR-COVERAGE — A71 Then-clause must embed the
    A62 row's literal Target + Metric reference when RelatedNFRID is
    non-empty.
  * TODO-S8-02-X-ARTIFACT-FK — A72 row's StoryID/ClaimID/SourceID must
    resolve in A70/A59/A50, AND the row's ClaimID's own SourceID per
    A59 must equal this row's SourceID (claim_source_consistency).

Both rules were documentary at the schema layer through v1.1.2; v1.1.3
makes them executable at the F5 hook layer via a new
``_SiblingArtifactCache`` plus two new ``_apply_*_rules`` handlers
(``_apply_foreign_key_rules`` + ``_apply_nfr_coverage_rules``).

Tests cover:
  * Positive case (rules satisfied → write passes)
  * FK violation: StoryID / ClaimID / SourceID doesn't resolve
  * claim/source consistency violation
  * NFR-coverage violation: missing literal Target
  * NFR-coverage violation: no Metric reference at all
  * Sibling-artifact missing → clear error (not silent skip)
  * Sibling-cache memoization (only one disk read per sibling per run)
  * Path outside canonical layout → handlers no-op silently
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from governance.schemas.write_validator import (
    _apply_foreign_key_rules,
    _apply_nfr_coverage_rules,
    _resolve_sibling_dir,
    _SiblingArtifactCache,
    validate_canonical_write,
)
from governance.schemas import loader as _schema_loader


# ---- helpers -----------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a real ``analysis/canonical/core_controls/`` tree under
    tmp_path with sibling A50/A59/A62/A70 files populated. Tests then
    write A71/A72 content and assert the cross-artifact rules fire.

    Patches CWD to tmp_path so that the relative paths the validator
    uses to resolve siblings actually point at this tree.
    """
    core = tmp_path / "analysis" / "canonical" / "core_controls"
    core.mkdir(parents=True)

    # A50 (sources)
    _write_csv(core / "A50_source_register.csv",
               ["SourceID", "SourceType", "Title", "Origin", "AccessStatus",
                "ReliabilityTier", "Priority", "Language", "DateOrVersion", "Notes"],
               [
                   ["S-001", "doc", "Source 1", "external", "readable", "T2", "high", "en", "2026-01-01", ""],
                   ["S-002", "doc", "Source 2", "external", "readable", "T2", "high", "en", "2026-01-01", ""],
               ])

    # A59 (claims) — every claim points at exactly one source
    _write_csv(core / "A59_claim_register.csv",
               ["ClaimID", "SourceID", "ExcerptID", "ClaimType", "Statement",
                "JustificationRationale", "A51Ref", "ClaimStrength", "Criticality", "Notes"],
               [
                   ["C-001", "S-001", "E-001", "direct", "Statement one", "", "", "1.0", "high", ""],
                   ["C-002", "S-002", "E-002", "direct", "Statement two", "", "", "1.0", "high", ""],
               ])

    # A62 (NFRs)
    _write_csv(core / "A62_nfr_register.csv",
               ["NFRID", "NFRCategory", "Statement", "SourceClaimIDs", "MeasurabilityType",
                "Metric", "Target", "TestabilityNotes", "Criticality", "A51Ref", "Notes"],
               [
                   ["NFR-PERF-001", "performance", "p95 page latency under load",
                    "C-001", "quantitative", "p95 latency ms", "< 500",
                    "load test 100 rps for 10 min", "high", "", ""],
               ])

    # A70 (stories)
    _write_csv(core / "A70_story_register.csv",
               ["StoryID", "Title", "Persona", "StoryText", "AcceptanceCriteria",
                "SourceClaimIDs", "RelatedNFRIDs", "Priority", "EstimationHint",
                "INVESTStatus", "A51Ref", "Notes"],
               [
                   ["STORY-001", "Story 1", "user", "story text", "criteria",
                    "C-001", "", "high", "M", "pass", "", ""],
                   ["STORY-002", "Story 2", "user", "story text", "criteria",
                    "C-002", "", "medium", "M", "pass", "", ""],
               ])

    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _csv_text(header: list[str], rows: list[list[str]]) -> str:
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


# ---- positive case -----------------------------------------------------


def test_a72_valid_row_passes_fk(workspace: Path) -> None:
    """An A72 row whose StoryID/ClaimID/SourceID all resolve in siblings
    AND whose ClaimID's A59 SourceID matches this row's SourceID passes."""
    content = _csv_text(
        ["TraceID", "StoryID", "ClaimID", "SourceID", "LinkType", "LinkStrength", "A51Ref", "Notes"],
        [["TR-001", "STORY-001", "C-001", "S-001", "direct", "high", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv", content,
    )
    assert ok, f"valid A72 row should pass; got: {msgs}"


def test_a71_valid_row_passes_nfr_coverage(workspace: Path) -> None:
    """An A71 scenario with RelatedNFRID set + Then-clause embedding the
    NFR's literal Target + Metric reference passes."""
    content = _csv_text(
        ["ScenarioID", "Title", "SourceStoryID", "RelatedNFRID", "Given", "When", "Then",
         "Tags", "Priority", "AutomationStatus", "A51Ref", "Notes"],
        [["TS-001", "page latency under load", "STORY-001", "NFR-PERF-001",
          "100 rps load is offered", "the latency probe runs",
          "the page latency p95 is < 500 ms over a 10-minute window",
          "@perf,@nfr", "level-1", "automated", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A71_test_scenario_register.csv", content,
    )
    assert ok, f"valid A71 should pass; got: {msgs}"


# ---- A72 foreign-key violations ----------------------------------------


def test_a72_unresolved_story_id_blocks_write(workspace: Path) -> None:
    content = _csv_text(
        ["TraceID", "StoryID", "ClaimID", "SourceID", "LinkType", "LinkStrength", "A51Ref", "Notes"],
        [["TR-001", "STORY-NOT-EXIST", "C-001", "S-001", "direct", "high", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv", content,
    )
    assert not ok
    assert any("STORY-NOT-EXIST" in m and "A70_story_register.csv" in m for m in msgs), msgs


def test_a72_unresolved_claim_id_blocks_write(workspace: Path) -> None:
    content = _csv_text(
        ["TraceID", "StoryID", "ClaimID", "SourceID", "LinkType", "LinkStrength", "A51Ref", "Notes"],
        [["TR-001", "STORY-001", "C-NOT-EXIST", "S-001", "direct", "high", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv", content,
    )
    assert not ok
    assert any("C-NOT-EXIST" in m and "A59_claim_register.csv" in m for m in msgs), msgs


def test_a72_unresolved_source_id_blocks_write(workspace: Path) -> None:
    content = _csv_text(
        ["TraceID", "StoryID", "ClaimID", "SourceID", "LinkType", "LinkStrength", "A51Ref", "Notes"],
        [["TR-001", "STORY-001", "C-001", "S-NOT-EXIST", "direct", "high", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv", content,
    )
    assert not ok
    assert any("S-NOT-EXIST" in m and "A50_source_register.csv" in m for m in msgs), msgs


def test_a72_claim_source_consistency_violation_blocks_write(workspace: Path) -> None:
    """A59 says C-001 is sourced by S-001; this row claims C-001 + S-002.
    Per claim_source_consistency, the matrix must agree with A59."""
    content = _csv_text(
        ["TraceID", "StoryID", "ClaimID", "SourceID", "LinkType", "LinkStrength", "A51Ref", "Notes"],
        [["TR-001", "STORY-001", "C-001", "S-002", "direct", "high", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv", content,
    )
    assert not ok
    assert any("claim/source consistency" in m and "S-001" in m and "S-002" in m for m in msgs), msgs


def test_a72_a51_routed_row_still_subject_to_fk(workspace: Path) -> None:
    """applies_to_all_rows=true means a51-routed rows are not exempt
    from FK resolution (the A51 routing defers acceptance, not ID
    integrity)."""
    content = _csv_text(
        ["TraceID", "StoryID", "ClaimID", "SourceID", "LinkType", "LinkStrength", "A51Ref", "Notes"],
        [["TR-001", "STORY-NOT-EXIST", "C-001", "S-001", "a51-routed", "low", "A51-001", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv", content,
    )
    assert not ok
    assert any("STORY-NOT-EXIST" in m for m in msgs), msgs


# ---- A71 NFR-coverage violations --------------------------------------


def test_a71_then_missing_literal_target_blocks_write(workspace: Path) -> None:
    """A62 has Target='< 500'; Then-clause says '< 800' — literal mismatch."""
    content = _csv_text(
        ["ScenarioID", "Title", "SourceStoryID", "RelatedNFRID", "Given", "When", "Then",
         "Tags", "Priority", "AutomationStatus", "A51Ref", "Notes"],
        [["TS-001", "weak", "STORY-001", "NFR-PERF-001",
          "load is offered", "probe runs",
          "the page latency p95 is < 800 ms over a 10-minute window",
          "@perf", "level-1", "automated", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A71_test_scenario_register.csv", content,
    )
    assert not ok
    assert any("< 500" in m and "Target" in m for m in msgs), msgs


def test_a71_then_no_metric_reference_blocks_write(workspace: Path) -> None:
    """Then-clause has the literal Target but no Metric word at all
    (e.g., 'the agent gets paged, value is < 500')."""
    content = _csv_text(
        ["ScenarioID", "Title", "SourceStoryID", "RelatedNFRID", "Given", "When", "Then",
         "Tags", "Priority", "AutomationStatus", "A51Ref", "Notes"],
        [["TS-001", "no-metric", "STORY-001", "NFR-PERF-001",
          "load is offered", "probe runs",
          "the agent gets paged when value is < 500",
          "@perf", "level-1", "automated", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A71_test_scenario_register.csv", content,
    )
    assert not ok
    assert any("Metric" in m and "p95 latency ms" in m for m in msgs), msgs


def test_a71_then_unresolved_nfr_id_blocks_write(workspace: Path) -> None:
    content = _csv_text(
        ["ScenarioID", "Title", "SourceStoryID", "RelatedNFRID", "Given", "When", "Then",
         "Tags", "Priority", "AutomationStatus", "A51Ref", "Notes"],
        [["TS-001", "ghost", "STORY-001", "NFR-NOT-EXIST",
          "g", "w", "the page latency p95 is < 500 ms",
          "@perf", "level-1", "automated", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A71_test_scenario_register.csv", content,
    )
    assert not ok
    assert any("NFR-NOT-EXIST" in m and "A62_nfr_register.csv" in m for m in msgs), msgs


def test_a71_blank_related_nfr_id_no_finding(workspace: Path) -> None:
    """Functional scenario (RelatedNFRID empty) is exempt from the rule."""
    content = _csv_text(
        ["ScenarioID", "Title", "SourceStoryID", "RelatedNFRID", "Given", "When", "Then",
         "Tags", "Priority", "AutomationStatus", "A51Ref", "Notes"],
        [["TS-001", "functional", "STORY-001", "",
          "g", "w", "the response says hello",
          "@func", "level-1", "automated", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A71_test_scenario_register.csv", content,
    )
    assert ok, f"functional scenario should pass; got: {msgs}"


# ---- Sibling-cache mechanics ------------------------------------------


def test_sibling_cache_memoizes_reads(tmp_path: Path) -> None:
    core = tmp_path / "analysis" / "canonical" / "core_controls"
    core.mkdir(parents=True)
    _write_csv(core / "A50_source_register.csv",
               ["SourceID", "SourceType", "Title", "Origin", "AccessStatus",
                "ReliabilityTier", "Priority", "Language", "DateOrVersion", "Notes"],
               [["S-001", "doc", "Source", "x", "readable", "T2", "high", "en", "2026", ""]])
    from pathlib import PurePosixPath
    cache = _SiblingArtifactCache(PurePosixPath(str(core)))
    first = cache.load("A50_source_register.csv", "SourceID")
    second = cache.load("A50_source_register.csv", "SourceID")
    assert first is second, "cache must memoize per (filename, key_column)"
    assert "S-001" in first


def test_sibling_cache_returns_none_for_missing_file(tmp_path: Path) -> None:
    core = tmp_path / "analysis" / "canonical" / "core_controls"
    core.mkdir(parents=True)
    from pathlib import PurePosixPath
    cache = _SiblingArtifactCache(PurePosixPath(str(core)))
    result = cache.load("A50_source_register.csv", "SourceID")
    assert result is None, "missing sibling must return None (not crash)"


def test_resolve_sibling_dir_returns_none_for_non_canonical_path() -> None:
    assert _resolve_sibling_dir("foo/bar/baz.csv") is None
    assert _resolve_sibling_dir("not/canonical/dir/A72.csv") is None


def test_resolve_sibling_dir_returns_none_when_dir_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The path fits the layout, but the dir doesn't exist on disk —
    returns None so cross-artifact handlers no-op (test backward-compat)."""
    monkeypatch.chdir(tmp_path)  # no analysis/ subtree
    assert _resolve_sibling_dir("analysis/canonical/core_controls/A72.csv") is None


# ---- Sibling-missing diagnostics --------------------------------------


def test_a72_sibling_a70_missing_emits_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the canonical dir exists but A70 is genuinely missing, the
    handler emits a clear sibling-not-readable violation rather than
    silently skipping."""
    core = tmp_path / "analysis" / "canonical" / "core_controls"
    core.mkdir(parents=True)
    # Create A50 + A59 but NOT A70 — the A72 row's StoryID lookup will
    # have a real layout but a missing sibling file.
    _write_csv(core / "A50_source_register.csv",
               ["SourceID", "SourceType", "Title", "Origin", "AccessStatus",
                "ReliabilityTier", "Priority", "Language", "DateOrVersion", "Notes"],
               [["S-001", "doc", "Source", "x", "readable", "T2", "high", "en", "2026", ""]])
    _write_csv(core / "A59_claim_register.csv",
               ["ClaimID", "SourceID", "ExcerptID", "ClaimType", "Statement",
                "JustificationRationale", "A51Ref", "ClaimStrength", "Criticality", "Notes"],
               [["C-001", "S-001", "E-001", "direct", "x", "", "", "1.0", "high", ""]])
    monkeypatch.chdir(tmp_path)
    content = _csv_text(
        ["TraceID", "StoryID", "ClaimID", "SourceID", "LinkType", "LinkStrength", "A51Ref", "Notes"],
        [["TR-001", "STORY-001", "C-001", "S-001", "direct", "high", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv", content,
    )
    assert not ok
    # The StoryID lookup must surface the missing-sibling diagnostic
    assert any("A70_story_register.csv" in m and "missing or unreadable" in m for m in msgs), msgs


# ---- v1.1.3 round-2 hardening (Codex round-1 findings) -----------------


def test_workspace_cwd_env_anchors_relative_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex round-1 critical bug: when the validator's process CWD is
    NOT the user workspace (production hook runs from PLUGIN_REPO),
    a relative TARGET_PATH would silently miss the real workspace and
    no-op cross-artifact rules. The hook now exports BSA_WORKSPACE_CWD
    pointing at the user shell's CWD; the validator anchors relative
    paths there.

    Reproduces the production scenario:
      * Build a real workspace under tmp_path with sibling A50/A59/A70.
      * Set CWD to a SEPARATE dir (simulates plugin-repo CWD).
      * Set BSA_WORKSPACE_CWD=tmp_path.
      * Pass a relative TARGET_PATH.
      * FK rule must fire; an unresolved StoryID must produce a violation.
    """
    core = tmp_path / "analysis" / "canonical" / "core_controls"
    core.mkdir(parents=True)
    _write_csv(core / "A50_source_register.csv",
               ["SourceID", "SourceType", "Title", "Origin", "AccessStatus",
                "ReliabilityTier", "Priority", "Language", "DateOrVersion", "Notes"],
               [["S-001", "doc", "x", "x", "readable", "T2", "high", "en", "2026", ""]])
    _write_csv(core / "A59_claim_register.csv",
               ["ClaimID", "SourceID", "ExcerptID", "ClaimType", "Statement",
                "JustificationRationale", "A51Ref", "ClaimStrength", "Criticality", "Notes"],
               [["C-001", "S-001", "E-001", "direct", "x", "", "", "1.0", "high", ""]])
    _write_csv(core / "A70_story_register.csv",
               ["StoryID", "Title", "Persona", "StoryText", "AcceptanceCriteria",
                "SourceClaimIDs", "RelatedNFRIDs", "Priority", "EstimationHint",
                "INVESTStatus", "A51Ref", "Notes"],
               [["STORY-001", "x", "u", "x", "x", "C-001", "", "high", "M", "pass", "", ""]])
    # Simulate production: process CWD is a different dir (plugin repo)
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    monkeypatch.setenv("BSA_WORKSPACE_CWD", str(tmp_path))

    content = _csv_text(
        ["TraceID", "StoryID", "ClaimID", "SourceID", "LinkType", "LinkStrength", "A51Ref", "Notes"],
        [["TR-001", "STORY-NOT-EXIST", "C-001", "S-001", "direct", "high", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv", content,
    )
    assert not ok, "FK rule must fire even when validator CWD ≠ workspace CWD"
    assert any("STORY-NOT-EXIST" in m for m in msgs), msgs


def test_workspace_cwd_env_overrides_process_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If BSA_WORKSPACE_CWD points at a real workspace, sibling lookups
    use it even when the process CWD has its own (different) workspace
    tree. This is the definitive precedence pin."""
    real_workspace = tmp_path / "real"
    decoy_workspace = tmp_path / "decoy"
    for ws in (real_workspace, decoy_workspace):
        core = ws / "analysis" / "canonical" / "core_controls"
        core.mkdir(parents=True)
        _write_csv(core / "A50_source_register.csv",
                   ["SourceID", "SourceType", "Title", "Origin", "AccessStatus",
                    "ReliabilityTier", "Priority", "Language", "DateOrVersion", "Notes"],
                   [["S-001", "doc", "x", "x", "readable", "T2", "high", "en", "2026", ""]])
        _write_csv(core / "A59_claim_register.csv",
                   ["ClaimID", "SourceID", "ExcerptID", "ClaimType", "Statement",
                    "JustificationRationale", "A51Ref", "ClaimStrength", "Criticality", "Notes"],
                   [["C-001", "S-001", "E-001", "direct", "x", "", "", "1.0", "high", ""]])
    # Real workspace has STORY-001; decoy has STORY-002 (disjoint sets).
    _write_csv(real_workspace / "analysis/canonical/core_controls/A70_story_register.csv",
               ["StoryID", "Title", "Persona", "StoryText", "AcceptanceCriteria",
                "SourceClaimIDs", "RelatedNFRIDs", "Priority", "EstimationHint",
                "INVESTStatus", "A51Ref", "Notes"],
               [["STORY-001", "x", "u", "x", "x", "C-001", "", "high", "M", "pass", "", ""]])
    _write_csv(decoy_workspace / "analysis/canonical/core_controls/A70_story_register.csv",
               ["StoryID", "Title", "Persona", "StoryText", "AcceptanceCriteria",
                "SourceClaimIDs", "RelatedNFRIDs", "Priority", "EstimationHint",
                "INVESTStatus", "A51Ref", "Notes"],
               [["STORY-002", "x", "u", "x", "x", "C-001", "", "high", "M", "pass", "", ""]])
    monkeypatch.chdir(decoy_workspace)
    monkeypatch.setenv("BSA_WORKSPACE_CWD", str(real_workspace))

    # STORY-001 exists in real_workspace (where BSA_WORKSPACE_CWD points)
    # but NOT in decoy_workspace. Validation must use the env var.
    content = _csv_text(
        ["TraceID", "StoryID", "ClaimID", "SourceID", "LinkType", "LinkStrength", "A51Ref", "Notes"],
        [["TR-001", "STORY-001", "C-001", "S-001", "direct", "high", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv", content,
    )
    assert ok, f"BSA_WORKSPACE_CWD must take precedence over process CWD; got: {msgs}"

    # Sanity-check the inverse: STORY-002 (only in decoy) must FAIL when
    # we're anchored to real_workspace via the env var.
    decoy_content = _csv_text(
        ["TraceID", "StoryID", "ClaimID", "SourceID", "LinkType", "LinkStrength", "A51Ref", "Notes"],
        [["TR-001", "STORY-002", "C-001", "S-001", "direct", "high", "", ""]],
    )
    ok2, msgs2 = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv", decoy_content,
    )
    assert not ok2, "STORY-002 lives only in decoy; BSA_WORKSPACE_CWD anchors elsewhere"
    assert any("STORY-002" in m and "A70_story_register.csv" in m for m in msgs2), msgs2


def test_claim_source_blank_a59_source_blocks_a72_with_source(workspace: Path) -> None:
    """Codex round-1 critical bug: A59.SourceID can legitimately be
    blank (claim is A51-routed). If a matrix row claims a SourceID for
    a sourceless claim, that's a hard contradiction the validator must
    catch — the matrix can't promise a source the register doesn't bind."""
    # Add a sourceless A59 row (A51-routed claim)
    core = workspace / "analysis/canonical/core_controls"
    a59_path = core / "A59_claim_register.csv"
    rows = list(csv.reader(a59_path.read_text().splitlines()))
    rows.append(["C-A51-001", "", "E-X51", "inference", "A51-routed claim",
                 "no direct source", "A51-001", "0.0", "high", ""])
    with a59_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerows(rows)
    content = _csv_text(
        ["TraceID", "StoryID", "ClaimID", "SourceID", "LinkType", "LinkStrength", "A51Ref", "Notes"],
        [["TR-001", "STORY-001", "C-A51-001", "S-001", "direct", "high", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv", content,
    )
    assert not ok
    assert any(
        "claim/source consistency" in m and "C-A51-001" in m and "empty A59.SourceID" in m
        for m in msgs
    ), msgs


def test_claim_source_multi_source_a59_membership_check(workspace: Path) -> None:
    """A59.SourceID is allowed to be multi-source (joined by ';' or '/').
    The matrix row picks ONE of the claim's sources — equality check
    would falsely block this; membership check is the right semantics."""
    core = workspace / "analysis/canonical/core_controls"
    a59_path = core / "A59_claim_register.csv"
    rows = list(csv.reader(a59_path.read_text().splitlines()))
    rows.append(["C-MULTI-001", "S-001;S-002", "E-MULTI-001", "direct",
                 "Multi-sourced claim", "", "", "1.0", "high", ""])
    with a59_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerows(rows)
    # Picking S-001 (one of the two sources) — should pass
    ok_content = _csv_text(
        ["TraceID", "StoryID", "ClaimID", "SourceID", "LinkType", "LinkStrength", "A51Ref", "Notes"],
        [["TR-001", "STORY-001", "C-MULTI-001", "S-001", "direct", "high", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv", ok_content,
    )
    assert ok, f"S-001 ∈ {{S-001, S-002}} membership must pass; got: {msgs}"
    # Picking a source NOT in the multi-source list — should fail
    bad_content = _csv_text(
        ["TraceID", "StoryID", "ClaimID", "SourceID", "LinkType", "LinkStrength", "A51Ref", "Notes"],
        [["TR-001", "STORY-001", "C-MULTI-001", "S-NOT-IN-LIST", "direct", "high", "", ""]],
    )
    # Note: S-NOT-IN-LIST will also fail FK in A50 — we want both
    ok2, msgs2 = validate_canonical_write(
        "analysis/canonical/core_controls/A72_traceability_matrix.csv", bad_content,
    )
    assert not ok2
    # Either FK or claim_source_consistency violation surfaces — check one
    assert any(("S-NOT-IN-LIST" in m) for m in msgs2), msgs2


def test_metric_match_uses_word_boundaries_not_substring(workspace: Path) -> None:
    """Codex round-1 should-fix: 'rate' must not match 'iterate', 'page'
    must not match 'paged'. Word-boundary regex prevents trivial false
    positives that would let aspirational Then-clauses slip past the
    NFR-coverage rule."""
    # Set up an NFR with Metric='rate per minute'
    core = workspace / "analysis/canonical/core_controls"
    a62_path = core / "A62_nfr_register.csv"
    rows = list(csv.reader(a62_path.read_text().splitlines()))
    rows.append(["NFR-RATE-001", "performance", "rate per minute under load",
                 "C-001", "quantitative", "rate per minute", "< 100",
                 "load test", "high", "", ""])
    with a62_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerows(rows)
    # Then-clause uses 'iterate' which CONTAINS 'rate' as a substring
    # but does NOT reference the metric's actual word at a word boundary.
    content = _csv_text(
        ["ScenarioID", "Title", "SourceStoryID", "RelatedNFRID", "Given", "When", "Then",
         "Tags", "Priority", "AutomationStatus", "A51Ref", "Notes"],
        [["TS-001", "wrong-word-match", "STORY-001", "NFR-RATE-001",
          "load is offered", "probe runs",
          "the system iterates over events at < 100",  # 'iterate' ⊃ 'rate' but no boundary
          "@perf", "level-1", "automated", "", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A71_test_scenario_register.csv", content,
    )
    assert not ok, "substring 'rate' inside 'iterate' must NOT satisfy the Metric reference"
    assert any("Metric" in m and "rate per minute" in m for m in msgs), msgs


# ---- A50 / A59 / A62 / A70 themselves are unaffected ------------------


def test_a50_validation_does_not_invoke_cross_artifact_rules(workspace: Path) -> None:
    """Writing A50 itself doesn't trigger FK or NFR-coverage handlers
    because A50 schema declares neither extension. The handlers no-op
    gracefully when the schema doesn't carry the extension key."""
    content = _csv_text(
        ["SourceID", "SourceType", "Title", "Origin", "AccessStatus",
         "ReliabilityTier", "Priority", "Language", "DateOrVersion", "Notes"],
        [["S-999", "doc", "New source", "x", "readable", "T2", "high", "en", "2026", ""]],
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A50_source_register.csv", content,
    )
    assert ok, f"A50 write must pass; got: {msgs}"
