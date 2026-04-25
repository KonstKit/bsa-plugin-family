"""Tests for `scripts/triangulation_audit.py` (v1.2.17).

Covers:
  * Pure unit: FK token splitter (semicolon/slash/mixed/whitespace).
  * Three-branch OR: Criticality / A51.Severity / A50.Priority.
  * Triggering set composition + analyst_judgment skip.
  * Pass/warn/n/a verdict policy.
  * Multi-value SourceID + RelatedClaimID join.
  * Tunable (`triangulation_min_distinct_sourcetypes`) + CLI-only branch
    threshold overrides (`--severity-threshold`, `--priority-threshold`).
  * Dangling FK silent-skip (per F5 hook contract).
  * Empty A50 / A51 — branch deactivation (Criticality still works).
  * CLI: --print-only / --min-sourcetypes / --severity-threshold /
    --priority-threshold / --workspace / error paths.
  * Markdown rendering: under-triangulation table + A51 placeholder.
  * Atomic writes (file written, no .tmp leftovers).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "triangulation_audit.py"
A50_REL = "analysis/canonical/core_controls/A50_source_register.csv"
A51_REL = "analysis/canonical/core_controls/A51_issue_route_register.csv"
A59_REL = "analysis/canonical/core_controls/A59_claim_register.csv"


# ---- Module loader --------------------------------------------------


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location(
        "triangulation_audit", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- CSV writer helpers ---------------------------------------------

A50_HEADER = (
    "SourceID,SourceType,Title,Origin,AccessStatus,ReliabilityTier,"
    "Priority,Language,DateOrVersion,Notes\n"
)
A51_HEADER = (
    "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
    "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
)
A59_HEADER = (
    "ClaimID,SourceID,ExcerptID,ClaimType,Statement,"
    "JustificationRationale,A51Ref,ClaimStrength,Criticality,Notes\n"
)


def _write_csv(path: Path, header: str, rows: list[dict]) -> None:
    cols = header.strip().split(",")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(header)
        for r in rows:
            fh.write(",".join(r.get(c, "") for c in cols) + "\n")


def _write_a50(workspace: Path, rows: list[dict]) -> None:
    _write_csv(workspace / A50_REL, A50_HEADER, rows)


def _write_a51(workspace: Path, rows: list[dict]) -> None:
    _write_csv(workspace / A51_REL, A51_HEADER, rows)


def _write_a59(workspace: Path, rows: list[dict]) -> None:
    _write_csv(workspace / A59_REL, A59_HEADER, rows)


def _make_workspace(tmp_path: Path) -> Path:
    (tmp_path / "analysis").mkdir(exist_ok=True)
    return tmp_path


def _row_a50(
    sid: str, *, source_type: str = "document", priority: str = "medium"
) -> dict:
    return {
        "SourceID": sid,
        "SourceType": source_type,
        "Title": f"Source {sid}",
        "Origin": "test",
        "AccessStatus": "readable",
        "ReliabilityTier": "T2",
        "Priority": priority,
        "Language": "en",
        "DateOrVersion": "v1",
        "Notes": "",
    }


def _row_a51(
    a51_ref: str,
    *,
    severity: str = "medium",
    related_claim: str = "",
) -> dict:
    return {
        "A51Ref": a51_ref,
        "IssueType": "uncertainty",
        "Severity": severity,
        "BlockingStatus": "soft",
        "RaisedByStage": "stage1",
        "RelatedSourceID": "",
        "RelatedClaimID": related_claim,
        "NextAction": "test",
        "ResolutionStatus": "open",
    }


def _row_a59(
    claim_id: str,
    *,
    source_id: str = "",
    claim_type: str = "direct",
    criticality: str = "level-2",
) -> dict:
    return {
        "ClaimID": claim_id,
        "SourceID": source_id,
        "ExcerptID": "E-001" if source_id else "",
        "ClaimType": claim_type,
        "Statement": "test",
        "JustificationRationale": (
            "ref C-100" if claim_type == "analyst_judgment" else ""
        ),
        "A51Ref": "",
        "ClaimStrength": "0.85" if claim_type != "analyst_judgment" else "",
        "Criticality": criticality,
        "Notes": "",
    }


# ---- Pure unit: FK token splitter -----------------------------------


def test_split_fk_tokens_semicolon(helper) -> None:
    assert helper._split_fk_tokens("S-001;S-002") == ["S-001", "S-002"]


def test_split_fk_tokens_slash(helper) -> None:
    assert helper._split_fk_tokens("S-001/S-002") == ["S-001", "S-002"]


def test_split_fk_tokens_mixed(helper) -> None:
    assert helper._split_fk_tokens("S-001;S-002/S-003") == [
        "S-001", "S-002", "S-003",
    ]


def test_split_fk_tokens_whitespace_padded(helper) -> None:
    assert helper._split_fk_tokens(" S-001 ; S-002 ") == ["S-001", "S-002"]


def test_split_fk_tokens_empty(helper) -> None:
    assert helper._split_fk_tokens("") == []


def test_split_fk_tokens_only_separators(helper) -> None:
    assert helper._split_fk_tokens(";/;/") == []


# ---- Branch 1: Criticality ------------------------------------------


def test_criticality_level_1_triggers_audit(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001", source_type="document")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-1"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 1
    assert snap["under_triangulation"][0]["trigger_reasons"] == [
        "criticality_level_1"
    ]


def test_criticality_level_2_does_not_trigger(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["verdict"] == "n/a"
    assert snap["summary"]["claims_in_triangulation_set"] == 0


def test_criticality_level_3_does_not_trigger(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-3"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 0


# ---- Branch 2: A51 Severity -----------------------------------------


def test_a51_severity_high_triggers(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001")])
    _write_a51(workspace, [_row_a51("A51-001", severity="high", related_claim="C-001")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 1
    assert "a51_severity_meets_threshold" in snap["under_triangulation"][0]["trigger_reasons"]


def test_a51_severity_critical_triggers(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001")])
    _write_a51(workspace, [_row_a51("A51-001", severity="critical", related_claim="C-001")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 1


def test_a51_severity_medium_does_not_trigger(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001")])
    _write_a51(workspace, [_row_a51("A51-001", severity="medium", related_claim="C-001")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 0


def test_a51_severity_low_does_not_trigger(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001")])
    _write_a51(workspace, [_row_a51("A51-001", severity="low", related_claim="C-001")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 0


def test_a51_severity_threshold_critical_skips_high(helper, tmp_path) -> None:
    """Tighten threshold to `critical` → high-only A51 should not trigger."""
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001")])
    _write_a51(workspace, [_row_a51("A51-001", severity="high", related_claim="C-001")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace, severity_threshold="critical")
    assert snap["summary"]["claims_in_triangulation_set"] == 0


def test_a51_multi_value_related_claim_id_fans_out(helper, tmp_path) -> None:
    """One A51 row covering multiple claims via `;`-joined RelatedClaimID."""
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001")])
    _write_a51(workspace, [
        _row_a51("A51-001", severity="high", related_claim="C-001;C-002"),
    ])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
        _row_a59("C-002", source_id="S-001", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 2


def test_a51_capitalized_severity_does_not_normalize(helper, tmp_path) -> None:
    """Pin: handler reach == schema reach (v1.2.16 R4/R5 lesson). A51
    schema's Severity enum is closed lowercase. A row with `High`
    capitalized is schema-invalid; the audit MUST NOT silently
    lowercase-normalize it (that would mask the upstream bug). Skip
    and proceed."""
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001")])
    _write_a51(workspace, [_row_a51("A51-001", severity="High", related_claim="C-001")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 0


def test_a51_unknown_severity_value_is_skipped(helper, tmp_path) -> None:
    """A51 with an out-of-enum Severity (defensive — schema usually
    catches this) — handler must skip without raising."""
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001")])
    _write_a51(workspace, [_row_a51("A51-001", severity="unknown", related_claim="C-001")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 0


# ---- Branch 3: A50 Priority -----------------------------------------


def test_a50_priority_high_triggers(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001", priority="high")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 1
    assert "a50_priority_meets_threshold" in snap["under_triangulation"][0]["trigger_reasons"]


def test_a50_priority_medium_does_not_trigger_default(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001", priority="medium")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 0


def test_a50_priority_threshold_medium_includes_medium(helper, tmp_path) -> None:
    """Lowering threshold to `medium` → medium A50 triggers."""
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001", priority="medium")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace, priority_threshold="medium")
    assert snap["summary"]["claims_in_triangulation_set"] == 1


def test_a50_priority_any_source_high_triggers(helper, tmp_path) -> None:
    """If ANY of multi-source claim's A50 rows has high Priority — trigger."""
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [
        _row_a50("S-001", priority="low"),
        _row_a50("S-002", priority="high"),
    ])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001;S-002", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 1


# ---- Three branches: OR composition + multi-reason ------------------


def test_all_three_branches_simultaneously(helper, tmp_path) -> None:
    """Level-1 + high A51 + high A50 — all 3 trigger reasons recorded."""
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001", priority="high")])
    _write_a51(workspace, [_row_a51("A51-001", severity="high", related_claim="C-001")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-1"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 1
    reasons = snap["under_triangulation"][0]["trigger_reasons"]
    assert "criticality_level_1" in reasons
    assert "a51_severity_meets_threshold" in reasons
    assert "a50_priority_meets_threshold" in reasons
    assert len(reasons) == 3


# ---- analyst_judgment always skipped --------------------------------


def test_analyst_judgment_skipped_even_if_level_1(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a59(workspace, [
        _row_a59(
            "C-001",
            source_id="",
            claim_type="analyst_judgment",
            criticality="level-1",
        ),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["verdict"] == "n/a"
    assert snap["summary"]["claims_skipped_analyst_judgment"] == 1
    assert snap["summary"]["claims_in_triangulation_set"] == 0


def test_analyst_judgment_skipped_even_with_high_severity_a51(
    helper, tmp_path
) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a51(workspace, [_row_a51("A51-001", severity="critical", related_claim="C-001")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="", claim_type="analyst_judgment"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_skipped_analyst_judgment"] == 1
    assert snap["summary"]["claims_in_triangulation_set"] == 0


# ---- Pass / warn / n/a verdict policy -------------------------------


def test_verdict_na_when_a59_absent(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    snap = helper.build_snapshot(workspace)
    assert snap["verdict"] == "n/a"
    assert snap["summary"]["claims_total"] == 0


def test_verdict_na_when_no_claims_in_set(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001", priority="low")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-3"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["verdict"] == "n/a"


def test_verdict_pass_when_triggered_claim_passes(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [
        _row_a50("S-001", source_type="document"),
        _row_a50("S-002", source_type="code"),
    ])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001;S-002", criticality="level-1"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["verdict"] == "pass"
    assert snap["summary"]["claims_passing"] == 1
    assert snap["summary"]["claims_under_triangulation"] == 0


def test_verdict_warn_when_triggered_claim_under(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001", source_type="document")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-1"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["verdict"] == "warn"
    assert snap["summary"]["claims_under_triangulation"] == 1
    finding = snap["under_triangulation"][0]
    assert finding["distinct_sourcetypes_count"] == 1
    assert finding["min_required"] == 2


def test_verdict_warn_mixed_pass_and_under(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [
        _row_a50("S-001", source_type="document"),
        _row_a50("S-002", source_type="code"),
        _row_a50("S-003", source_type="document"),
    ])
    _write_a59(workspace, [
        # Passes — 2 distinct types.
        _row_a59("C-001", source_id="S-001;S-002", criticality="level-1"),
        # Under — 1 distinct type only.
        _row_a59("C-002", source_id="S-001;S-003", criticality="level-1"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["verdict"] == "warn"
    assert snap["summary"]["claims_passing"] == 1
    assert snap["summary"]["claims_under_triangulation"] == 1


# ---- SourceType independence ----------------------------------------


def test_two_same_sourcetypes_count_as_one(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [
        _row_a50("S-001", source_type="document"),
        _row_a50("S-002", source_type="document"),
    ])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001;S-002", criticality="level-1"),
    ])
    snap = helper.build_snapshot(workspace)
    finding = snap["under_triangulation"][0]
    assert finding["distinct_sourcetypes_count"] == 1
    assert finding["distinct_sourcetypes"] == ["document"]


def test_three_distinct_sourcetypes_passes_min_2(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [
        _row_a50("S-001", source_type="document"),
        _row_a50("S-002", source_type="code"),
        _row_a50("S-003", source_type="interview_transcript"),
    ])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001;S-002;S-003", criticality="level-1"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["verdict"] == "pass"


def test_three_distinct_sourcetypes_fails_min_3_when_two(helper, tmp_path) -> None:
    """Tighten min to 3 — 2 distinct types now under-triangulates."""
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [
        _row_a50("S-001", source_type="document"),
        _row_a50("S-002", source_type="code"),
    ])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001;S-002", criticality="level-1"),
    ])
    snap = helper.build_snapshot(workspace, min_distinct_sourcetypes=3)
    assert snap["verdict"] == "warn"
    finding = snap["under_triangulation"][0]
    assert finding["distinct_sourcetypes_count"] == 2
    assert finding["min_required"] == 3


# ---- Dangling FK + missing sources ----------------------------------


def test_dangling_sourceid_silently_skipped(helper, tmp_path) -> None:
    """Per F5 hook contract (x-bsa-foreign-key-refs v1.2.13), dangling
    SourceID shouldn't slip through canonical promotion. If it does,
    audit silently skips the dangling token rather than crashing."""
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [
        _row_a50("S-001", source_type="document"),
        # S-002 deliberately absent.
    ])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001;S-002", criticality="level-1"),
    ])
    snap = helper.build_snapshot(workspace)
    finding = snap["under_triangulation"][0]
    # Only S-001's `document` resolved; S-002 dangling and skipped.
    assert finding["distinct_sourcetypes"] == ["document"]
    assert finding["distinct_sourcetypes_count"] == 1


def test_a50_missing_priority_branch_inactive_criticality_still_works(
    helper, tmp_path
) -> None:
    """A50 absent → Priority branch can't fire AND SourceTypes can't
    resolve → triggered level-1 claim has 0 distinct types → under."""
    workspace = _make_workspace(tmp_path)
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-1"),
    ])
    snap = helper.build_snapshot(workspace)
    assert snap["summary"]["claims_in_triangulation_set"] == 1
    assert snap["verdict"] == "warn"
    finding = snap["under_triangulation"][0]
    assert finding["distinct_sourcetypes_count"] == 0


def test_a51_missing_severity_branch_inactive(helper, tmp_path) -> None:
    """A51 absent → only Criticality + Priority branches can fire."""
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    snap = helper.build_snapshot(workspace)
    # No level-1, no high priority, A51 missing → set empty → n/a.
    assert snap["verdict"] == "n/a"


# ---- Suggested A51 placeholder --------------------------------------


def test_suggested_a51_carries_placeholder_and_required_fields(
    helper, tmp_path
) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001", source_type="document")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-1"),
    ])
    snap = helper.build_snapshot(workspace)
    a51 = snap["under_triangulation"][0]["suggested_a51"]
    assert a51["A51Ref"] == "<assign-on-create>"
    a51_required = {
        "A51Ref", "IssueType", "Severity", "BlockingStatus",
        "RaisedByStage", "NextAction", "ResolutionStatus",
    }
    assert a51_required <= set(a51.keys())
    assert a51["RelatedClaimID"] == "C-001"
    assert "S-001" in a51["RelatedSourceID"]


# ---- CLI ------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_print_only_does_not_write(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [
        _row_a50("S-001", source_type="document"),
        _row_a50("S-002", source_type="code"),
    ])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001;S-002", criticality="level-1"),
    ])
    result = _run_cli("--workspace", str(workspace), "--print-only")
    assert result.returncode == 0
    snap = json.loads(result.stdout)
    assert snap["verdict"] == "pass"
    assert not (workspace / "analysis/canonical/stage7/triangulation_audit.json").exists()


def test_cli_writes_marker_and_report(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [
        _row_a50("S-001", source_type="document"),
        _row_a50("S-002", source_type="code"),
    ])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001;S-002", criticality="level-1"),
    ])
    result = _run_cli("--workspace", str(workspace), "--quiet")
    assert result.returncode == 0
    marker = workspace / "analysis/canonical/stage7/triangulation_audit.json"
    report = workspace / "analysis/canonical/stage7/triangulation_audit.md"
    assert marker.exists()
    assert report.exists()
    snap = json.loads(marker.read_text(encoding="utf-8"))
    assert snap["verdict"] == "pass"
    md = report.read_text(encoding="utf-8")
    assert "# Triangulation Audit" in md


def test_cli_min_sourcetypes_override(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [
        _row_a50("S-001", source_type="document"),
        _row_a50("S-002", source_type="code"),
    ])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001;S-002", criticality="level-1"),
    ])
    r_strict = _run_cli(
        "--workspace", str(workspace),
        "--min-sourcetypes", "3",
        "--print-only",
    )
    snap = json.loads(r_strict.stdout)
    assert snap["verdict"] == "warn"


def test_cli_severity_threshold_critical(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001")])
    _write_a51(workspace, [_row_a51("A51-001", severity="high", related_claim="C-001")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    r = _run_cli(
        "--workspace", str(workspace),
        "--severity-threshold", "critical",
        "--print-only",
    )
    snap = json.loads(r.stdout)
    assert snap["summary"]["claims_in_triangulation_set"] == 0


def test_cli_priority_threshold_medium(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001", priority="medium")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-2"),
    ])
    r = _run_cli(
        "--workspace", str(workspace),
        "--priority-threshold", "medium",
        "--print-only",
    )
    snap = json.loads(r.stdout)
    assert snap["summary"]["claims_in_triangulation_set"] == 1


def test_cli_workspace_not_initialized_returns_2(tmp_path) -> None:
    result = _run_cli("--workspace", str(tmp_path), "--print-only")
    assert result.returncode == 2
    assert "not initialized" in result.stderr


def test_cli_invalid_min_sourcetypes_returns_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(workspace),
        "--min-sourcetypes", "1",
        "--print-only",
    )
    assert result.returncode == 2


def test_cli_invalid_severity_threshold_returns_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(workspace),
        "--severity-threshold", "low",  # not in choices
        "--print-only",
    )
    assert result.returncode == 2


def test_cli_invalid_priority_threshold_returns_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(workspace),
        "--priority-threshold", "low",  # not in choices
        "--print-only",
    )
    assert result.returncode == 2


# ---- Markdown rendering ---------------------------------------------


def test_markdown_renders_under_triangulation_table(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001", source_type="document")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-1"),
    ])
    snap = helper.build_snapshot(workspace)
    md = helper.render_markdown(snap)
    assert "## Under-triangulated claims" in md
    assert "`C-001`" in md
    assert "## Suggested A51 routes" in md
    assert "`<assign-on-create>`" in md
    assert "replace" in md.lower()


def test_markdown_no_under_section_when_clean(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [
        _row_a50("S-001", source_type="document"),
        _row_a50("S-002", source_type="code"),
    ])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001;S-002", criticality="level-1"),
    ])
    snap = helper.build_snapshot(workspace)
    md = helper.render_markdown(snap)
    assert "No under-triangulated claims." in md
    assert "## Under-triangulated claims" not in md


# ---- Atomic write hygiene -------------------------------------------


def test_no_tmp_files_left_after_write(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001", source_type="document")])
    _write_a59(workspace, [
        _row_a59("C-001", source_id="S-001", criticality="level-1"),
    ])
    result = _run_cli("--workspace", str(workspace), "--quiet")
    assert result.returncode == 0
    out_dir = workspace / "analysis/canonical/stage7"
    leftovers = [
        p.name for p in out_dir.iterdir()
        if p.name.startswith(".triangulation_audit_")
    ]
    assert leftovers == [], f"tempfile leftovers: {leftovers}"
