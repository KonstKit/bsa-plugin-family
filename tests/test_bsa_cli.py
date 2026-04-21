"""Tests for scripts/bsa_cli.py (v1.0.4 UX wrapper).

Covers:
  - WorkspaceState readers against synthetic + real-fixture workspaces.
  - `bsa status` CLI output shape (not exact formatting — exit code + key
    substrings so the test survives reasonable layout tweaks).
  - Graceful degradation: uninitialized workspace, missing A48, missing
    A51, malformed markers, Sysco-drifted (camelCase-payload) markers.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_SCRIPT = REPO_ROOT / "scripts" / "bsa_cli.py"
BSA_SHELL = REPO_ROOT / "scripts" / "bsa"


# ---- Helpers --------------------------------------------------------


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI_SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def _init_workspace(tmp_path: Path, a48_fields: dict[str, str] | None = None) -> Path:
    """Create a minimal analysis/ layout with an A48 card."""
    analysis = tmp_path / "analysis"
    core = analysis / "canonical" / "core_controls"
    core.mkdir(parents=True)
    (analysis / "runtime" / "ready").mkdir(parents=True)
    (analysis / "discovery" / "runtime" / "ready").mkdir(parents=True)
    fields = a48_fields or {
        "RunID": "test-run-001",
        "Mode": "direct",
        "CurrentStage": "stage1",
        "CanonPolicyVersion": "1.0.0",
    }
    # Bullet-backtick A48 (the format the plugin test suite uses internally).
    lines = ["# A48 Run Context Card", ""]
    for k, v in fields.items():
        lines.append(f"- `{k}`: {v}")
    (core / "A48_run_context_card.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return tmp_path


def _write_marker(workspace: Path, filename: str, payload: dict, discovery: bool = False) -> None:
    subdir = "discovery/runtime/ready" if discovery else "runtime/ready"
    (workspace / "analysis" / subdir / filename).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_a51(workspace: Path, rows: list[dict]) -> None:
    """Write A51 with the canonical column order."""
    core = workspace / "analysis" / "canonical" / "core_controls"
    cols = [
        "A51Ref", "IssueType", "Severity", "BlockingStatus", "RaisedByStage",
        "RelatedSourceID", "RelatedClaimID", "NextAction", "ResolutionStatus",
    ]
    lines = [",".join(cols)]
    for row in rows:
        cells = []
        for c in cols:
            v = row.get(c, "")
            if "," in v or '"' in v:
                cells.append(f'"{v.replace(chr(34), chr(34) * 2)}"')
            else:
                cells.append(v)
        lines.append(",".join(cells))
    (core / "A51_issue_route_register.csv").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


# ---- 1. Uninitialized workspace -------------------------------------


def test_status_uninitialized_workspace_exits_2(tmp_path: Path) -> None:
    result = _run_cli(["-w", str(tmp_path), "status"])
    assert result.returncode == 2
    assert "not a BSA workspace" in result.stderr


def test_status_nonexistent_workspace_exits_2(tmp_path: Path) -> None:
    result = _run_cli(["-w", str(tmp_path / "nope"), "status"])
    assert result.returncode == 2


# ---- 2. Minimal workspace -------------------------------------------


def test_status_minimal_workspace_shows_a48_fields(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path)
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0, result.stderr
    assert "test-run-001" in result.stdout
    assert "direct" in result.stdout
    assert "stage1" in result.stdout
    assert "1.0.0" in result.stdout
    # No markers yet.
    assert "(none)" in result.stdout


def test_status_no_a51_reports_zero_counts(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path)
    result = _run_cli(["-w", str(ws), "status"])
    assert "Open A51 items:    0 (of 0 total)" in result.stdout


# ---- 3. Markers -----------------------------------------------------


def test_status_surfaces_last_marker(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path)
    _write_marker(
        ws,
        "stage3.ready.json",
        {
            "marker_id": "stage3.ready",
            "stage": "stage3",
            "verdict": "READY",
            "timestamp": "2026-04-22T10:15:00Z",
            "canon_policy_version": "1.0.0",
        },
    )
    _write_marker(
        ws,
        "stage3.citation_audit.pass.json",
        {
            "marker_id": "stage3.citation_audit.pass",
            "stage": "stage3",
            "verdict": "PASS",
            "timestamp": "2026-04-22T11:30:00Z",
            "canon_policy_version": "1.0.0",
        },
    )
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    # Most-recent timestamp wins for "last marker".
    assert "stage3.citation_audit.pass" in result.stdout
    # Both markers listed under the main zone.
    assert "stage3.ready" in result.stdout


def test_status_shows_discovery_markers_separately(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path, {
        "RunID": "d-test",
        "Mode": "discovery_then_bsa",
        "CurrentStage": "d2",
        "CanonPolicyVersion": "1.0.0",
    })
    _write_marker(
        ws,
        "discovery.d1.ready.json",
        {
            "marker_id": "discovery.d1.ready",
            "stage": "d1",
            "verdict": "READY",
            "timestamp": "2026-04-22T10:00:00Z",
            "canon_policy_version": "1.0.0",
        },
        discovery=True,
    )
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    assert "discovery:" in result.stdout
    assert "discovery.d1.ready" in result.stdout


# ---- 4. A51 readers -------------------------------------------------


def test_status_a51_counts_by_blocking_status(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path)
    _write_a51(ws, [
        {"A51Ref": "A51-001", "IssueType": "uncertainty", "Severity": "high",
         "BlockingStatus": "hard", "RaisedByStage": "stage1",
         "NextAction": "x", "ResolutionStatus": "open"},
        {"A51Ref": "A51-002", "IssueType": "contradiction", "Severity": "medium",
         "BlockingStatus": "soft", "RaisedByStage": "stage3",
         "NextAction": "y", "ResolutionStatus": "open"},
        {"A51Ref": "A51-003", "IssueType": "missing_source", "Severity": "low",
         "BlockingStatus": "informational", "RaisedByStage": "stage1",
         "NextAction": "z", "ResolutionStatus": "resolved_by_remediation"},
    ])
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    assert "Open A51 items:    2 (of 3 total)" in result.stdout
    assert "hard blockers:   1" in result.stdout
    assert "soft:            1" in result.stdout
    assert "informational:   1" in result.stdout


# ---- 5. Sysco-drifted markers (camelCase) ---------------------------


def test_status_tolerates_camelcase_sysco_markers(tmp_path: Path) -> None:
    """Sysco-engagement markers use `marker`/`emittedAt` instead of
    `marker_id`/`timestamp`. CLI must still read them (fallback
    keys) rather than crash. It's a DIAGNOSTIC tool — refusing to
    open non-conformant workspaces is the wrong call; surfacing the
    drift visibly (verdict='?') is the right one."""
    ws = _init_workspace(tmp_path)
    _write_marker(
        ws,
        "discovery.d1.ready.json",
        {
            "marker": "discovery.d1.ready",
            "runId": "sysco-like",
            "emittedAt": "2026-04-22T09:00:00Z",
            "canonPolicyVersion": "1.0.0",
        },
        discovery=True,
    )
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    # Marker surfaces by filename stem fallback.
    assert "discovery.d1.ready" in result.stdout


def test_status_tolerates_malformed_marker_json(tmp_path: Path) -> None:
    """A malformed JSON marker must not crash the CLI — just skip it."""
    ws = _init_workspace(tmp_path)
    (ws / "analysis" / "runtime" / "ready" / "broken.json").write_text(
        "{ not valid", encoding="utf-8"
    )
    # Also add a valid marker so the output has something to show.
    _write_marker(ws, "stage1.ready.json", {
        "marker_id": "stage1.ready", "stage": "stage1", "verdict": "READY",
        "timestamp": "2026-04-22T10:00:00Z", "canon_policy_version": "1.0.0",
    })
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    assert "stage1.ready" in result.stdout


# ---- 6. Real fixture end-to-end -------------------------------------


def test_status_reads_real_golden_fixture(tmp_path: Path) -> None:
    """Point the CLI at the committed project_0001 fixture via a
    symlink, verify it parses the real A48 / markers / A51."""
    # Some test runners block os.symlink on Windows; check + skip.
    fx = REPO_ROOT / "fixtures" / "golden" / "project_0001" / "expected_outputs"
    try:
        (tmp_path / "analysis").symlink_to(fx)
    except OSError:
        pytest.skip("symlink unsupported on this platform")
    result = _run_cli(["-w", str(tmp_path), "status"])
    assert result.returncode == 0, result.stderr
    assert "fixture-project-0001" in result.stdout
    assert "stage1" in result.stdout
    assert "0.95" in result.stdout


# ---- 7. Shell wrapper smoke -----------------------------------------


def test_bash_wrapper_delegates_to_cli(tmp_path: Path) -> None:
    """The bash wrapper at scripts/bsa should reach the CLI and forward args."""
    ws = _init_workspace(tmp_path)
    result = subprocess.run(
        ["/bin/bash", str(BSA_SHELL), "-w", str(ws), "status"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "test-run-001" in result.stdout


# ---- 8. Codex-surfaced v1.0.4 regression guards ---------------------


def test_bash_wrapper_works_from_symlink_install(tmp_path: Path) -> None:
    """Documented install path: `ln -s /path/to/plugin/scripts/bsa ~/.local/bin/bsa`.
    Codex review surfaced that the pre-fix wrapper used `dirname "$0"`
    without resolving `$0` through symlinks, so the symlinked-in install
    broke: PLUGIN_REPO became the parent of ~/.local/bin instead of the
    plugin repo.
    """
    ws = _init_workspace(tmp_path)
    link_dir = tmp_path / "bin"
    link_dir.mkdir()
    symlink = link_dir / "bsa"
    try:
        symlink.symlink_to(BSA_SHELL)
    except OSError:
        pytest.skip("symlink unsupported on this platform")
    result = subprocess.run(
        ["/bin/bash", str(symlink), "-w", str(ws), "status"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Symlink-install invocation failed — bash wrapper isn't resolving "
        f"$0 through symlinks.\nstderr={result.stderr!r}"
    )
    assert "test-run-001" in result.stdout


def test_status_recognizes_promoted_no_new_claims_report(tmp_path: Path) -> None:
    """Codex review: audit_outputs() looked at
    `stage8/stage8_no_new_claims_report.md` but the canonical filename
    is `stage8/no_new_claims_report.md`. Fixed; this test pins it."""
    ws = _init_workspace(tmp_path, {
        "RunID": "audit-test",
        "Mode": "direct",
        "CurrentStage": "stage8",
        "CanonPolicyVersion": "1.0.0",
    })
    stage8 = ws / "analysis" / "canonical" / "stage8"
    stage8.mkdir(parents=True)
    (stage8 / "no_new_claims_report.md").write_text(
        "# Report content\n", encoding="utf-8"
    )
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    # The line format is "  no_new_claims        PRESENT"
    assert "no_new_claims" in result.stdout
    # PRESENT indicator for this audit specifically (not just any PRESENT).
    assert "no_new_claims        PRESENT" in result.stdout


def test_last_marker_uses_emittedat_for_sysco_markers(tmp_path: Path) -> None:
    """Codex review: `last_marker()` only read `timestamp`. Sysco-style
    drifted markers use `emittedAt`. Fixed to accept either."""
    ws = _init_workspace(tmp_path, {
        "RunID": "emittedat-test",
        "Mode": "discovery_then_bsa",
        "CurrentStage": "d1",
        "CanonPolicyVersion": "1.0.0",
    })
    # Older marker (would be "last" if only timestamp is considered).
    _write_marker(
        ws,
        "discovery.d1.ready.json",
        {
            "marker_id": "discovery.d1.ready",
            "stage": "d1",
            "verdict": "READY",
            "timestamp": "2026-04-22T08:00:00Z",
            "canon_policy_version": "1.0.0",
        },
        discovery=True,
    )
    # Newer Sysco-drifted marker — uses emittedAt instead of timestamp.
    _write_marker(
        ws,
        "discovery.d2.ready.json",
        {
            "marker": "discovery.d2.ready",
            "runId": "x",
            "emittedAt": "2026-04-22T09:00:00Z",
        },
        discovery=True,
    )
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    # The Sysco-drifted d2 marker should win the "Last marker" line
    # because emittedAt 09:00 > timestamp 08:00. Pre-fix, the drifted
    # marker was ignored in recency sorting; conformant d1 marker won.
    last_line = [
        line for line in result.stdout.splitlines() if line.startswith("Last marker:")
    ]
    assert last_line, "Last marker line missing from output"
    assert "discovery.d2.ready" in last_line[0]
