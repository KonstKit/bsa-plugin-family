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


# ---- F1 regression cases (Sprint 5) -----------------------------------
# Pre-F1 the validator hard-coded only the seven audit-pass markers and
# rejected every other marker as `chain-unknown-marker` — including the
# stage-ready, end-state, bridge, and non-go decision markers that are
# all valid per runtime-marker-schema.md. These tests cover the
# Sprint-5 P1 finding #1 (validator alphabet drift).


def _write_marker(path: Path, marker_id: str, stage: str, verdict: str, ts: str) -> None:
    path.write_text(
        json.dumps(
            {
                "marker_id": marker_id,
                "stage": stage,
                "verdict": verdict,
                "timestamp": ts,
                "canon_policy_version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )


def test_stage_ready_markers_accepted_alongside_audit_pass(tmp_path: Path) -> None:
    """Real workspaces emit stage*.ready alongside the audit-pass markers.
    These were previously hard-rejected as chain-unknown-marker."""
    ws = tmp_path / "markers"
    ws.mkdir()
    # Minimal valid main chain: stage1 audit-pass + stage2 ready+pass.
    _write_marker(ws / "stage1.ready.json", "stage1.ready", "stage1", "READY", "2026-04-20T09:00:00Z")
    _write_marker(ws / "stage1.excerpts.merged.json", "stage1.excerpts.merged", "stage1", "MERGED", "2026-04-20T09:30:00Z")
    _write_marker(ws / "stage2.ready.json", "stage2.ready", "stage2", "READY", "2026-04-20T10:00:00Z")
    _write_marker(ws / "stage2.context_state.pass.json", "stage2.context_state.pass", "stage2", "PASS", "2026-04-20T10:30:00Z")
    result = run(str(ws))
    assert result.returncode == 0, (
        f"Validator rejected real-workspace markers (F1 regression).\nstderr={result.stderr}"
    )


def test_handoff_and_pipeline_complete_accepted(tmp_path: Path) -> None:
    """End-state markers (handoff.ready, pipeline.complete) are valid.
    Pre-F1 they were rejected as chain-unknown-marker."""
    ws = tmp_path / "markers"
    ws.mkdir()
    # Full audit-pass chain plus end-state markers.
    chain = [
        ("stage1.excerpts.merged", "stage1", "MERGED", "2026-04-20T09:00:00Z"),
        ("stage2.context_state.pass", "stage2", "PASS", "2026-04-20T10:00:00Z"),
        ("stage3.citation_audit.pass", "stage3", "PASS", "2026-04-20T11:00:00Z"),
        ("stage5.anchor_audit.pass", "stage5", "PASS", "2026-04-20T13:00:00Z"),
        ("stage6.anchor_audit.pass", "stage6", "PASS", "2026-04-20T14:00:00Z"),
        ("stage7.skeptical_review.pass", "stage7", "PASS", "2026-04-20T15:00:00Z"),
        ("stage8.no_new_claims.pass", "stage8", "PASS", "2026-04-20T16:00:00Z"),
        ("handoff.ready", "handoff", "READY", "2026-04-20T16:30:00Z"),
        ("pipeline.complete", "pipeline", "PASS", "2026-04-20T17:00:00Z"),
    ]
    for mid, stage, verdict, ts in chain:
        _write_marker(ws / f"{mid}.json", mid, stage, verdict, ts)
    result = run(str(ws))
    assert result.returncode == 0, (
        f"End-state markers rejected (F1 regression).\nstderr={result.stderr}"
    )


def test_bridge_marker_accepted_in_discovery_chain(tmp_path: Path) -> None:
    """bsa.stage1.entry.enabled is the discovery→main bridge.
    Pre-F1 it was double-rejected (sent to discovery chain by _split_chains
    but discovery sequence had no slot for it)."""
    ws = tmp_path / "markers"
    ws.mkdir()
    # Discovery chain through go + bridge marker.
    chain = [
        ("discovery.d1.ready", "d1", "READY", "2026-04-20T08:00:00Z"),
        ("discovery.d2.claims.merged", "d2", "MERGED", "2026-04-20T08:30:00Z"),
        ("discovery.d2.research_quality.pass", "d2", "PASS", "2026-04-20T08:45:00Z"),
        ("discovery.d3.prioritization.pass", "d3", "PASS", "2026-04-20T09:00:00Z"),
        ("discovery.d4.constraint_audit.pass", "d4", "PASS", "2026-04-20T09:30:00Z"),
        ("discovery.d5.citation_audit.pass", "d5", "PASS", "2026-04-20T09:45:00Z"),
        ("discovery.d5.no_solution_leakage.pass", "d5", "PASS", "2026-04-20T09:50:00Z"),
        ("discovery.exit.pass", "discovery.exit", "PASS", "2026-04-20T10:00:00Z"),
        ("discovery.go", "discovery.exit", "GO", "2026-04-20T10:05:00Z"),
        ("bsa.stage1.entry.enabled", "discovery.bridge", "READY", "2026-04-20T10:06:00Z"),
    ]
    for mid, stage, verdict, ts in chain:
        _write_marker(ws / f"{mid}.json", mid, stage, verdict, ts)
    result = run(str(ws))
    assert result.returncode == 0, (
        f"Bridge marker rejected (F1 double-reject regression).\nstderr={result.stderr}"
    )


def test_alternative_decision_markers_accepted(tmp_path: Path) -> None:
    """discovery.pivot, .more_research, .no_go are valid alternatives to .go.
    Pre-F1 only .go was in the gating sequence; the others were rejected."""
    for decision in ("pivot", "more_research", "no_go"):
        ws = tmp_path / f"markers_{decision}"
        ws.mkdir()
        # Minimal discovery chain ending in the alternative decision.
        chain = [
            ("discovery.d1.ready", "d1", "READY", "2026-04-20T08:00:00Z"),
            (f"discovery.{decision}", "discovery.exit", "READY", "2026-04-20T10:00:00Z"),
        ]
        for mid, stage, verdict, ts in chain:
            _write_marker(ws / f"{mid}.json", mid, stage, verdict, ts)
        result = run(str(ws))
        # Note: chain-gap is expected because the audit-pass sequence is
        # incomplete (we skipped d2-d5). What we're asserting here is the
        # ABSENCE of chain-unknown-marker for the decision marker itself.
        assert "chain-unknown-marker" not in result.stderr, (
            f"discovery.{decision} rejected as unknown (F1 regression).\nstderr={result.stderr}"
        )


def test_truly_unknown_marker_id_still_rejected(tmp_path: Path) -> None:
    """The schema enforcement still rejects ad-hoc / drifted IDs.
    This is the test that should KEEP catching the original problem
    class (e.g., LLM emits 'stage9.synthesize.pass' or camelCase 'marker' field)."""
    ws = tmp_path / "markers"
    ws.mkdir()
    _write_marker(ws / "stage1.ready.json", "stage1.ready", "stage1", "READY", "2026-04-20T09:00:00Z")
    _write_marker(
        ws / "stageX.weird.json",
        "stageX.weird",  # not in schema enum
        "stage1",
        "PASS",
        "2026-04-20T09:30:00Z",
    )
    result = run(str(ws))
    assert result.returncode == 1
    assert "chain-unknown-marker" in result.stderr
    assert "stageX.weird" in result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
