"""Unit tests for scripts/validate_marker_chain.py (US-S3-05).

The validator treats the committed project_0001 marker set as baseline
and exercises specific failure paths (chain gap, duplicate, bad
timestamp, missing required field, unknown marker_id, hash inconsistency)
by cloning the baseline into tmp_path and mutating it.

Exit codes asserted:
  0 — valid.
  1 — chain finding(s).
  2 — invocation error (missing directory / malformed JSON).

Stdlib-only.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "validate_marker_chain.py"
BASELINE = REPO_ROOT / "fixtures" / "golden" / "project_0001" / "expected_markers"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def clone_markers(tmp_path: Path, name: str = "markers") -> Path:
    dest = tmp_path / name
    shutil.copytree(BASELINE, dest)
    return dest


def test_baseline_fixture_passes() -> None:
    result = run(str(BASELINE))
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_missing_markers_dir_returns_exit_2(tmp_path: Path) -> None:
    result = run(str(tmp_path / "nope"))
    assert result.returncode == 2
    assert "missing-markers-dir" in result.stderr


def test_malformed_marker_json_returns_exit_1(tmp_path: Path) -> None:
    clone = clone_markers(tmp_path)
    (clone / "broken.json").write_text("{ not valid json", encoding="utf-8")
    result = run(str(clone))
    assert result.returncode == 1
    assert "marker-parse" in result.stderr


def test_missing_required_field_returns_exit_1(tmp_path: Path) -> None:
    clone = clone_markers(tmp_path)
    target = clone / "stage3.citation_audit.pass.json"
    data = json.loads(target.read_text())
    data.pop("verdict")
    target.write_text(json.dumps(data), encoding="utf-8")
    result = run(str(clone))
    assert result.returncode == 1
    assert "marker-schema" in result.stderr
    assert "verdict" in result.stderr


def test_chain_gap_stage2_missing_reports_chain_gap(tmp_path: Path) -> None:
    clone = clone_markers(tmp_path)
    (clone / "stage2.context_state.pass.json").unlink()
    result = run(str(clone))
    assert result.returncode == 1
    assert "chain-gap" in result.stderr
    assert "stage2.context_state.pass" in result.stderr


def test_chain_duplicate_reports_chain_duplicate(tmp_path: Path) -> None:
    clone = clone_markers(tmp_path)
    # Copy stage3 marker under a new filename but keep same marker_id.
    original = clone / "stage3.citation_audit.pass.json"
    dup = clone / "stage3.citation_audit.pass.copy.json"
    dup.write_text(original.read_text(), encoding="utf-8")
    result = run(str(clone))
    assert result.returncode == 1
    assert "chain-duplicate" in result.stderr


def test_non_monotonic_timestamp_reports_chain_timestamp(tmp_path: Path) -> None:
    clone = clone_markers(tmp_path)
    # Push stage3 timestamp earlier than stage2.
    target = clone / "stage3.citation_audit.pass.json"
    data = json.loads(target.read_text())
    data["timestamp"] = "2026-01-01T00:00:00Z"
    target.write_text(json.dumps(data), encoding="utf-8")
    result = run(str(clone))
    assert result.returncode == 1
    assert "chain-timestamp" in result.stderr


def test_inconsistent_canon_policy_version_reports_version_inconsistent(tmp_path: Path) -> None:
    clone = clone_markers(tmp_path)
    target = clone / "stage3.citation_audit.pass.json"
    data = json.loads(target.read_text())
    data["canon_policy_version"] = "0.94"  # doesn't match others
    target.write_text(json.dumps(data), encoding="utf-8")
    result = run(str(clone))
    assert result.returncode == 1
    assert "chain-version-inconsistent" in result.stderr


def test_inconsistent_canon_policy_version_hash_reports_hash_inconsistent(tmp_path: Path) -> None:
    clone = clone_markers(tmp_path)
    target = clone / "stage3.citation_audit.pass.json"
    data = json.loads(target.read_text())
    data["canon_policy_version_hash"] = "deadbeef"
    target.write_text(json.dumps(data), encoding="utf-8")
    result = run(str(clone))
    assert result.returncode == 1
    assert "chain-hash-inconsistent" in result.stderr


def test_missing_canon_policy_version_hash_is_tolerated(tmp_path: Path) -> None:
    """Pre-Sprint-3 workspaces may lack the hash field; this must not be a
    finding on its own (missing-hash ≠ chain-hash-inconsistent)."""
    clone = clone_markers(tmp_path)
    target = clone / "stage3.citation_audit.pass.json"
    data = json.loads(target.read_text())
    data.pop("canon_policy_version_hash", None)
    target.write_text(json.dumps(data), encoding="utf-8")
    result = run(str(clone))
    assert result.returncode == 0, result.stderr


def test_unknown_marker_id_reports_chain_unknown_marker(tmp_path: Path) -> None:
    clone = clone_markers(tmp_path)
    target = clone / "weird.json"
    target.write_text(
        json.dumps(
            {
                "marker_id": "stageX.weird",
                "stage": "stageX",
                "verdict": "PASS",
                "canon_policy_version": "0.95",
                "timestamp": "2026-02-25T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    result = run(str(clone))
    assert result.returncode == 1
    assert "chain-unknown-marker" in result.stderr
    assert "stageX.weird" in result.stderr


def test_empty_markers_dir_passes(tmp_path: Path) -> None:
    """Pre-start workspace with no markers is valid (chain is empty)."""
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run(str(empty))
    assert result.returncode == 0


def test_discovery_only_chain_passes(tmp_path: Path) -> None:
    """A discovery-mode workspace with only discovery.* markers and no main
    markers validates cleanly when the discovery chain is a valid prefix."""
    empty = tmp_path / "disco"
    empty.mkdir()
    discovery_markers = [
        ("discovery.d1.ready.json", "discovery.d1.ready", "2026-01-10T09:00:00Z"),
        ("discovery.d2.claims.merged.json", "discovery.d2.claims.merged", "2026-01-11T09:00:00Z"),
        ("discovery.d2.research_quality.pass.json", "discovery.d2.research_quality.pass", "2026-01-11T14:00:00Z"),
    ]
    for fname, mid, ts in discovery_markers:
        (empty / fname).write_text(
            json.dumps(
                {
                    "marker_id": mid,
                    "stage": mid.split(".")[1],
                    "verdict": "PASS" if mid.endswith(".pass") else "READY",
                    "timestamp": ts,
                    "canon_policy_version": "0.95",
                }
            ),
            encoding="utf-8",
        )
    result = run(str(empty))
    assert result.returncode == 0, result.stderr


def test_discovery_chain_gap_reports_chain_gap(tmp_path: Path) -> None:
    """Discovery chain with d3 present but d2 missing → chain-gap."""
    empty = tmp_path / "disco"
    empty.mkdir()
    markers = [
        ("discovery.d1.ready.json", "discovery.d1.ready", "2026-01-10T09:00:00Z"),
        ("discovery.d3.prioritization.pass.json", "discovery.d3.prioritization.pass", "2026-01-13T09:00:00Z"),
    ]
    for fname, mid, ts in markers:
        (empty / fname).write_text(
            json.dumps(
                {
                    "marker_id": mid,
                    "stage": mid.split(".")[1],
                    "verdict": "PASS" if mid.endswith(".pass") else "READY",
                    "timestamp": ts,
                    "canon_policy_version": "0.95",
                }
            ),
            encoding="utf-8",
        )
    result = run(str(empty))
    assert result.returncode == 1
    assert "chain-gap" in result.stderr
    assert "discovery" in result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
