"""Unit tests for scripts/migrate_v0.9_to_v1.0.py (US-S2-02 part 2/3).

Covers:
- Fresh workspace with legacy files → planned renames + dry-run + apply
- Partial workspace (some mappings absent) → tolerated
- Target-conflict (both legacy and canonical present) → exit 1, no apply
- Idempotent re-run (second apply is no-op)
- Missing workspace → exit 2
- Migration log schema conformance
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "migrate_v0.9_to_v1.0.py"


def run_migration(workspace: Path, apply: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), f"--workspace={workspace}"]
    if apply:
        cmd.append("--apply")
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def read_log(workspace: Path) -> list[dict]:
    log = workspace / "runtime" / "migration_log_v0.9_to_v1.0.jsonl"
    if not log.exists():
        return []
    records = []
    for line in log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def make_legacy_workspace(tmp_path: Path, mappings: list[tuple[str, str]]) -> Path:
    """Create a workspace with the given (rel_dir, legacy_filename) pairs populated."""
    ws = tmp_path / "analysis"
    ws.mkdir()
    for rel_dir, fname in mappings:
        d = ws / rel_dir
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_text(f"legacy content for {fname}\n", encoding="utf-8")
    return ws


def test_dry_run_reports_planned_renames_no_changes(tmp_path: Path) -> None:
    ws = make_legacy_workspace(tmp_path, [
        ("discovery/runtime/ready", "discovery.d5.no_new_facts.pass.json"),
        ("canonical/stage8", "no_new_facts_report.md"),
        ("proposals/stage7_8/handoff", "handoff_no_new_facts_report.md"),
    ])
    result = run_migration(ws, apply=False)
    assert result.returncode == 0, result.stderr
    assert "dry-run" in result.stdout
    # Legacy files still present
    assert (ws / "discovery/runtime/ready/discovery.d5.no_new_facts.pass.json").exists()
    assert (ws / "canonical/stage8/no_new_facts_report.md").exists()
    # Canonical files NOT created by dry-run
    assert not (ws / "discovery/runtime/ready/discovery.d5.no_new_claims.pass.json").exists()
    # Log records written
    records = read_log(ws)
    assert any(r["mode"] == "renamed" and r["dry_run"] is True for r in records)


def test_apply_mode_actually_renames(tmp_path: Path) -> None:
    ws = make_legacy_workspace(tmp_path, [
        ("canonical/stage8", "no_new_facts_report.md"),
        ("proposals/stage7_8/handoff", "handoff_no_new_facts_report.md"),
    ])
    result = run_migration(ws, apply=True)
    assert result.returncode == 0, result.stderr
    assert "applied" in result.stdout
    # Legacy files GONE, canonical files present
    assert not (ws / "canonical/stage8/no_new_facts_report.md").exists()
    assert (ws / "canonical/stage8/no_new_claims_report.md").exists()
    assert not (ws / "proposals/stage7_8/handoff/handoff_no_new_facts_report.md").exists()
    assert (ws / "proposals/stage7_8/handoff/handoff_no_new_claims_report.md").exists()


def test_partial_workspace_tolerated(tmp_path: Path) -> None:
    """A workspace missing some mappings is not an error."""
    ws = make_legacy_workspace(tmp_path, [
        ("canonical/stage8", "no_new_facts_report.md"),
    ])
    result = run_migration(ws, apply=True)
    assert result.returncode == 0, result.stderr
    records = read_log(ws)
    renamed = [r for r in records if r["mode"] == "renamed"]
    skipped = [r for r in records if r["mode"] == "skipped"]
    assert len(renamed) == 1
    assert len(skipped) >= 1  # at least one mapping is parent-dir-absent


def test_target_conflict_halts_migration(tmp_path: Path) -> None:
    """When both legacy and canonical files exist, abort with exit 1 and no renames."""
    ws = make_legacy_workspace(tmp_path, [
        ("canonical/stage8", "no_new_facts_report.md"),
    ])
    # Also place the canonical target — creates a conflict
    (ws / "canonical/stage8/no_new_claims_report.md").write_text("already migrated\n", encoding="utf-8")
    # Another legit rename that SHOULD have worked, just to verify it's blocked too
    (ws / "proposals/stage7_8/handoff").mkdir(parents=True, exist_ok=True)
    (ws / "proposals/stage7_8/handoff/handoff_no_new_facts_report.md").write_text("legacy\n", encoding="utf-8")

    result = run_migration(ws, apply=True)
    assert result.returncode == 1
    assert "conflict" in result.stderr.lower()
    # Legacy files preserved (no partial migration)
    assert (ws / "canonical/stage8/no_new_facts_report.md").exists()
    assert (ws / "canonical/stage8/no_new_claims_report.md").exists()
    assert (ws / "proposals/stage7_8/handoff/handoff_no_new_facts_report.md").exists()
    # Error record in log
    records = read_log(ws)
    assert any(r["mode"] == "error" and r.get("reason") == "target-conflict" for r in records)


def test_idempotent_second_run(tmp_path: Path) -> None:
    """Apply twice; second run renames zero files. Tightened per round-1
    codex feedback: compare before/after log snapshots so we inspect
    only records appended by the second run."""
    ws = make_legacy_workspace(tmp_path, [
        ("canonical/stage8", "no_new_facts_report.md"),
        ("proposals/stage7_8/handoff", "handoff_no_new_facts_report.md"),
    ])
    first = run_migration(ws, apply=True)
    assert first.returncode == 0
    first_records = read_log(ws)
    first_count = len(first_records)
    # Confirm first run actually renamed (sanity check)
    assert any(r["mode"] == "renamed" and r["dry_run"] is False for r in first_records)

    second = run_migration(ws, apply=True)
    assert second.returncode == 0
    all_records = read_log(ws)
    # Slice to ONLY the records appended by the second run
    second_run_records = all_records[first_count:]
    assert second_run_records, "second run must still log something"
    # Every second-run record for the previously-renamed mappings must be
    # a skip (source-missing) — zero actual renames.
    assert all(r["mode"] != "renamed" for r in second_run_records), (
        f"expected zero 'renamed' in second run, got: "
        f"{[r for r in second_run_records if r['mode'] == 'renamed']}"
    )
    # And the skips for the previously-renamed mappings must carry
    # reason=source-missing (not parent-dir-absent), confirming the
    # migration already happened.
    renamed_mapping_ids = {r["mapping_id"] for r in first_records if r["mode"] == "renamed"}
    for mid in renamed_mapping_ids:
        matching = [
            r for r in second_run_records
            if r["mapping_id"] == mid and r["mode"] == "skipped"
        ]
        assert matching, f"expected skipped records for mapping {mid} in second run"
        assert all(r["reason"] == "source-missing" for r in matching), (
            f"expected reason=source-missing, got: {matching}"
        )


def test_discovery_d5_mappings_covered(tmp_path: Path) -> None:
    """Round-1 codex rec: explicit coverage for mapping_id 5 (canonical D5)
    and mapping_id 6 (proposal-layer D5)."""
    ws = make_legacy_workspace(tmp_path, [
        ("discovery/canonical/d5", "discovery_no_new_facts_report.md"),
        ("discovery/proposals/d5", "discovery_no_new_facts_report.md"),
    ])
    result = run_migration(ws, apply=True)
    assert result.returncode == 0, result.stderr
    assert (ws / "discovery/canonical/d5/discovery_no_new_claims_report.md").exists()
    assert (ws / "discovery/proposals/d5/discovery_no_new_claims_report.md").exists()
    records = read_log(ws)
    renamed_ids = {r["mapping_id"] for r in records if r["mode"] == "renamed"}
    assert 5 in renamed_ids
    assert 6 in renamed_ids


def test_nested_workspace_layout(tmp_path: Path) -> None:
    """Round-1 codex rec: workspace with non-canonical nested layout
    (e.g., parent project directory containing analysis/ subdirs) still
    matches rename patterns via suffix matching."""
    ws = tmp_path / "some_project" / "run_42" / "analysis"
    legacy = ws / "canonical/stage8/no_new_facts_report.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("nested legacy\n", encoding="utf-8")
    result = run_migration(ws, apply=True)
    assert result.returncode == 0, result.stderr
    canonical = ws / "canonical/stage8/no_new_claims_report.md"
    assert canonical.exists()
    assert not legacy.exists()


def test_missing_workspace_exit_2(tmp_path: Path) -> None:
    result = run_migration(tmp_path / "nope")
    assert result.returncode == 2
    assert "does not exist" in result.stderr


def test_workspace_is_file_not_dir_exit_2(tmp_path: Path) -> None:
    f = tmp_path / "not-a-dir"
    f.write_text("x", encoding="utf-8")
    result = run_migration(f)
    assert result.returncode == 2


def test_readonly_workspace_fails_log_dir_mkdir_with_exit_2(tmp_path: Path) -> None:
    """Round-1 codex critical: readonly workspace (dir exists but is not
    writable) must fail cleanly via apply_migration's log_dir.mkdir guard.
    Exit 2, no traceback."""
    import os
    ws = tmp_path / "ro_ws"
    ws.mkdir()
    (ws / "canonical/stage8").mkdir(parents=True)
    (ws / "canonical/stage8/no_new_facts_report.md").write_text("x", encoding="utf-8")
    try:
        os.chmod(ws, 0o555)
        result = run_migration(ws, apply=True)
    finally:
        os.chmod(ws, 0o755)
    assert result.returncode == 2, (
        f"expected exit 2 on read-only workspace, got {result.returncode}. "
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "ERROR" in result.stderr
    assert "Traceback" not in result.stderr


def test_unreachable_parent_workspace_exit_2_no_traceback(tmp_path: Path) -> None:
    """Round-2 codex: main() preflight must survive a workspace whose
    parent directory is not traversable (chmod 0o000). The exists()/
    is_dir() checks can raise PermissionError on such paths; main()
    must translate that to exit 2 without a traceback."""
    import os
    locked_parent = tmp_path / "locked_parent"
    locked_parent.mkdir()
    ws = locked_parent / "ws"
    ws.mkdir()
    (ws / "canonical/stage8").mkdir(parents=True)
    (ws / "canonical/stage8/no_new_facts_report.md").write_text("x", encoding="utf-8")
    try:
        os.chmod(locked_parent, 0o000)  # no read, no write, no exec
        result = run_migration(ws, apply=True)
    finally:
        os.chmod(locked_parent, 0o755)  # restore so pytest tmp cleanup succeeds
    # Two acceptable paths: (a) preflight raises PermissionError -> main()
    # guard returns 2; (b) preflight silently returns False (some OSes
    # allow stat via open dir handle) -> "does not exist" exit 2.
    # Either way, exit 2 + no traceback + ERROR line is the contract.
    assert result.returncode == 2, (
        f"expected exit 2 on unreachable-parent workspace, got {result.returncode}. "
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "ERROR" in result.stderr
    assert "Traceback" not in result.stderr


def test_log_schema_has_required_fields(tmp_path: Path) -> None:
    ws = make_legacy_workspace(tmp_path, [
        ("canonical/stage8", "no_new_facts_report.md"),
    ])
    run_migration(ws, apply=True)
    records = read_log(ws)
    assert records, "log must contain records"
    for r in records:
        assert r["migration"] == "v0.9_to_v1.0"
        assert "timestamp" in r
        assert "mapping_id" in r
        assert "from_path" in r
        assert "to_path" in r
        assert r["mode"] in ("renamed", "skipped", "error")
        assert "dry_run" in r


def test_discovery_marker_rename(tmp_path: Path) -> None:
    """Discovery D5 no-new-claims marker rename covered."""
    ws = make_legacy_workspace(tmp_path, [
        ("discovery/runtime/ready", "discovery.d5.no_new_facts.pass.json"),
    ])
    # Seed with a real-looking marker JSON to prove rename is filename-only
    (ws / "discovery/runtime/ready/discovery.d5.no_new_facts.pass.json").write_text(
        json.dumps({"marker_id": "discovery.d5.no_new_facts.pass", "verdict": "PASS"}),
        encoding="utf-8",
    )
    result = run_migration(ws, apply=True)
    assert result.returncode == 0
    canonical = ws / "discovery/runtime/ready/discovery.d5.no_new_claims.pass.json"
    assert canonical.exists()
    # Body preserved as-is (the tool is filename-only)
    data = json.loads(canonical.read_text(encoding="utf-8"))
    assert data["marker_id"] == "discovery.d5.no_new_facts.pass"  # body unchanged


def test_proposal_layer_also_renamed(tmp_path: Path) -> None:
    """Both canonical and proposal-layer Stage 8 report patterns are covered."""
    ws = make_legacy_workspace(tmp_path, [
        ("canonical/stage8", "no_new_facts_report.md"),
        ("proposals/stage7_8/stage8", "no_new_facts_report.md"),
    ])
    result = run_migration(ws, apply=True)
    assert result.returncode == 0
    assert (ws / "canonical/stage8/no_new_claims_report.md").exists()
    assert (ws / "proposals/stage7_8/stage8/no_new_claims_report.md").exists()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
