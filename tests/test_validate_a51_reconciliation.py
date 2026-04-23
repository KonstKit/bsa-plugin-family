"""Unit tests for scripts/validate_a51_reconciliation.py (F6, Sprint 5).

Five test groups:

1. **Empty workspace** — no A51 + no markers → clean.
2. **Clean reconciliation** — A51 entries are open, nothing in markers
   declares them resolved → clean.
3. **The  Pilot-1 regression case** — A51 row is `open` in canonical, but
   discovery.go.json precondition list declares it
   resolved_by_remediation → A51_RECONCILE_GAP.
4. **Ghost reference** — marker declares an A51Ref resolved but that
   A51Ref doesn't exist in the canonical register → A51_RECONCILE_GHOST.
5. **CLI smoke** — script exit codes + stderr shape.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "validate_a51_reconciliation.py"


def _make_workspace(
    tmp_path: Path,
    a51_rows: list[dict] | None = None,
    main_markers: dict[str, dict] | None = None,
    discovery_markers: dict[str, dict] | None = None,
    handoff_files: dict[str, str] | None = None,
) -> Path:
    """Create a synthetic workspace with the given A51 rows + markers."""
    a51_dir = tmp_path / "analysis" / "canonical" / "core_controls"
    a51_dir.mkdir(parents=True)
    rows = a51_rows or []
    headers = [
        "A51Ref",
        "IssueType",
        "Severity",
        "BlockingStatus",
        "RaisedByStage",
        "RelatedSourceID",
        "RelatedClaimID",
        "NextAction",
        "ResolutionStatus",
    ]
    csv_lines = [",".join(headers)]
    for row in rows:
        csv_lines.append(",".join(row.get(h, "") for h in headers))
    (a51_dir / "A51_issue_route_register.csv").write_text(
        "\n".join(csv_lines) + "\n", encoding="utf-8"
    )
    main_dir = tmp_path / "analysis" / "runtime" / "ready"
    main_dir.mkdir(parents=True)
    for fname, payload in (main_markers or {}).items():
        (main_dir / fname).write_text(json.dumps(payload), encoding="utf-8")
    disc_dir = tmp_path / "analysis" / "discovery" / "runtime" / "ready"
    disc_dir.mkdir(parents=True)
    for fname, payload in (discovery_markers or {}).items():
        (disc_dir / fname).write_text(json.dumps(payload), encoding="utf-8")
    handoff_dir = tmp_path / "analysis" / "handoff"
    handoff_dir.mkdir(parents=True)
    for fname, content in (handoff_files or {}).items():
        (handoff_dir / fname).write_text(content, encoding="utf-8")
    return tmp_path


def _run(workspace: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(workspace)],
        capture_output=True,
        text=True,
    )


# ---- 1. Empty / minimal workspace ------------------------------------


def test_empty_workspace_returns_ok(tmp_path: Path) -> None:
    """Workspace with no canonical A51 and no markers → clean."""
    ws = _make_workspace(tmp_path)
    result = _run(ws)
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_no_analysis_directory_exits_2(tmp_path: Path) -> None:
    result = _run(tmp_path)  # tmp_path has no analysis/ subdir
    assert result.returncode == 2
    assert "no analysis/" in result.stderr


# ---- 2. Clean reconciliation ------------------------------------------


def test_open_a51_with_no_resolved_mention_passes(tmp_path: Path) -> None:
    """A51 has open rows; markers exist but don't mention them as resolved → clean."""
    ws = _make_workspace(
        tmp_path,
        a51_rows=[
            {
                "A51Ref": "A51-001",
                "IssueType": "uncertainty",
                "Severity": "low",
                "BlockingStatus": "informational",
                "RaisedByStage": "stage1",
                "NextAction": "Confirm later",
                "ResolutionStatus": "open",
            },
        ],
        main_markers={
            "stage1.ready.json": {
                "marker_id": "stage1.ready",
                "stage": "stage1",
                "verdict": "READY",
                "timestamp": "2026-04-21T10:00:00Z",
                "canon_policy_version": "1.0.0",
                "notes": "Workspace initialized; A51-001 noted but pending.",
            }
        },
    )
    result = _run(ws)
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_resolved_a51_with_resolved_mention_passes(tmp_path: Path) -> None:
    """A51 row is correctly marked resolved_by_remediation; marker says
    same → clean."""
    ws = _make_workspace(
        tmp_path,
        a51_rows=[
            {
                "A51Ref": "A51-MISS-010",
                "IssueType": "missing_source",
                "Severity": "high",
                "BlockingStatus": "hard",
                "RaisedByStage": "discovery.exit",
                "NextAction": "Re-extract PDF",
                "ResolutionStatus": "resolved_by_remediation",
            },
        ],
        discovery_markers={
            "discovery.go.json": {
                "marker_id": "discovery.go",
                "stage": "discovery.exit",
                "verdict": "GO",
                "timestamp": "2026-04-21T10:00:00Z",
                "canon_policy_version": "1.0.0",
                "preconditions": [
                    "A51-MISS-010 was resolved_by_remediation via PDF re-extraction.",
                ],
            }
        },
    )
    result = _run(ws)
    assert result.returncode == 0


# ---- 3. The  Pilot-1 regression case (THE main F6 test) ----------------


def test_pilot1_reconcile_gap_detected(tmp_path: Path) -> None:
    """Direct replay of the Pilot-1 engagement gap. discovery.go.json
    precondition #4 declares A51-MISS-010/011 as resolved_by_remediation
    but the canonical A51 register still has them as open. Auditor MUST
    surface A51_RECONCILE_GAP for both."""
    ws = _make_workspace(
        tmp_path,
        a51_rows=[
            {
                "A51Ref": "A51-MISS-010",
                "IssueType": "missing_source",
                "Severity": "high",
                "BlockingStatus": "hard",
                "RaisedByStage": "discovery.exit",
                "NextAction": "Install poppler-utils or obtain MD transcripts",
                "ResolutionStatus": "open",  # ← still open in register
            },
            {
                "A51Ref": "A51-MISS-011",
                "IssueType": "missing_source",
                "Severity": "high",
                "BlockingStatus": "hard",
                "RaisedByStage": "discovery.exit",
                "NextAction": "Re-extract DOCX via python-docx",
                "ResolutionStatus": "open",  # ← still open in register
            },
        ],
        discovery_markers={
            "discovery.go.json": {
                "marker_id": "discovery.go",
                "stage": "discovery.exit",
                "verdict": "GO",
                "timestamp": "2026-04-21T10:00:00Z",
                "canon_policy_version": "1.0.0",
                "preconditions": [
                    "Reclassify register-hygiene: A51-MISS-010/011 → "
                    "resolved_by_remediation (already done via PDF extraction; "
                    "canonical rewrite pending).",
                ],
            }
        },
    )
    result = _run(ws)
    assert result.returncode == 1, (
        f"Pilot-1-class gap NOT detected.\nstderr={result.stderr}"
    )
    assert "A51_RECONCILE_GAP" in result.stderr
    assert "A51-MISS-010" in result.stderr
    assert "A51-MISS-011" in result.stderr
    assert "discovery.go.json" in result.stderr


def test_handoff_packet_resolved_mention_also_caught(tmp_path: Path) -> None:
    """Same pattern but the resolved-mention is in H4_open_items_packet.md."""
    ws = _make_workspace(
        tmp_path,
        a51_rows=[
            {
                "A51Ref": "A51-CNTR-003",
                "IssueType": "contradiction",
                "Severity": "high",
                "BlockingStatus": "hard",
                "RaisedByStage": "stage7",
                "NextAction": "Escalate to PO",
                "ResolutionStatus": "open",
            },
        ],
        handoff_files={
            "H4_open_items_packet.md": (
                "# Open Items\n\n"
                "## Items closed in this iteration\n\n"
                "- A51-CNTR-003 — contradiction resolved by Chandamma sign-off "
                "on auth-flow ownership.\n"
            ),
        },
    )
    result = _run(ws)
    assert result.returncode == 1
    assert "A51_RECONCILE_GAP" in result.stderr
    assert "A51-CNTR-003" in result.stderr
    assert "H4_open_items_packet.md" in result.stderr


def test_proximity_window_avoids_unrelated_text(tmp_path: Path) -> None:
    """A resolution-intent word far away from an A51Ref must NOT trigger.
    Otherwise we'd false-positive whenever a marker happened to mention
    'closed' anywhere alongside any A51Ref."""
    # Put 'resolved' >200 chars away from the A51Ref → should NOT trigger.
    far_text = "x" * 250
    ws = _make_workspace(
        tmp_path,
        a51_rows=[
            {
                "A51Ref": "A51-001",
                "IssueType": "uncertainty",
                "Severity": "low",
                "BlockingStatus": "informational",
                "RaisedByStage": "stage1",
                "NextAction": "Note",
                "ResolutionStatus": "open",
            },
        ],
        main_markers={
            "stage1.ready.json": {
                "marker_id": "stage1.ready",
                "stage": "stage1",
                "verdict": "READY",
                "timestamp": "2026-04-21T10:00:00Z",
                "canon_policy_version": "1.0.0",
                "notes": "A51-001 needs review. " + far_text + " The earlier topic was resolved in a different ticket.",
            }
        },
    )
    result = _run(ws)
    assert result.returncode == 0, (
        f"Proximity window failed; far-away 'resolved' triggered false positive.\n"
        f"stderr={result.stderr}"
    )


# ---- 4. Ghost reference -----------------------------------------------


def test_ghost_a51_reference_caught(tmp_path: Path) -> None:
    """An A51Ref claimed-resolved in markers but absent from the
    canonical register → A51_RECONCILE_GHOST."""
    ws = _make_workspace(
        tmp_path,
        a51_rows=[],  # empty register
        main_markers={
            "stage3.citation_audit.pass.json": {
                "marker_id": "stage3.citation_audit.pass",
                "stage": "stage3",
                "verdict": "PASS",
                "timestamp": "2026-04-21T10:00:00Z",
                "canon_policy_version": "1.0.0",
                "notes": "A51-XYZ-042 was resolved during stage 3.",
            }
        },
    )
    result = _run(ws)
    assert result.returncode == 1
    assert "A51_RECONCILE_GHOST" in result.stderr
    assert "A51-XYZ-042" in result.stderr


# ---- 5. Multiple gaps in one workspace -------------------------------


def test_multiple_gaps_aggregated(tmp_path: Path) -> None:
    ws = _make_workspace(
        tmp_path,
        a51_rows=[
            {
                "A51Ref": "A51-001",
                "IssueType": "uncertainty",
                "Severity": "low",
                "BlockingStatus": "informational",
                "RaisedByStage": "stage1",
                "NextAction": "Note",
                "ResolutionStatus": "open",
            },
            {
                "A51Ref": "A51-002",
                "IssueType": "decision_needed",
                "Severity": "medium",
                "BlockingStatus": "soft",
                "RaisedByStage": "stage3",
                "NextAction": "Decide",
                "ResolutionStatus": "open",
            },
        ],
        discovery_markers={
            "discovery.go.json": {
                "marker_id": "discovery.go",
                "stage": "discovery.exit",
                "verdict": "GO",
                "timestamp": "2026-04-21T10:00:00Z",
                "canon_policy_version": "1.0.0",
                "preconditions": [
                    "A51-001 resolved by extra source.",
                    "A51-002 closed via product decision.",
                ],
            }
        },
    )
    result = _run(ws)
    assert result.returncode == 1
    assert result.stderr.count("A51_RECONCILE_GAP") == 2
