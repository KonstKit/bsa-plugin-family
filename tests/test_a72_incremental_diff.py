"""Tests for `scripts/a72_incremental_diff.py` (v1.2.2, T1).

Pins:
  * `_hash_row` is stable across key-order permutations.
  * Diff classifies added / modified / removed / unchanged correctly.
  * Cache round-trips: write → read returns the same hashes.
  * Cache version mismatch → returns empty (forces full rebuild).
  * Cache corruption (malformed JSON, wrong shape) → returns empty.
  * Atomic write: tmpfile in same dir as cache; mv replaces atomically.
  * `compute_diff` walks ALL TRACKED_ARTIFACTS even if some are missing.
  * CLI:
    - `--force-rebuild` exits 1 with full-rebuild signal.
    - `--update-cache` writes the snapshot to disk.
    - `--json` emits parseable JSON.
    - missing workspace exits 2.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "a72_incremental_diff.py"


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location("a72_incremental_diff", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_workspace(tmp_path: Path) -> Path:
    (tmp_path / "analysis" / "canonical" / "core_controls").mkdir(parents=True)
    return tmp_path


def _write_csv(workspace: Path, rel: str, header: list[str], rows: list[list[str]]) -> None:
    target = workspace / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as fh:
        fh.write(",".join(header) + "\n")
        for row in rows:
            fh.write(",".join(row) + "\n")


# ---- _hash_row -----------------------------------------------------


def test_hash_row_is_stable_across_key_order(helper) -> None:
    row1 = {"A": "1", "B": "2", "C": "3"}
    row2 = {"C": "3", "A": "1", "B": "2"}
    assert helper._hash_row(row1) == helper._hash_row(row2)


def test_hash_row_changes_with_value_change(helper) -> None:
    row1 = {"A": "1", "B": "2"}
    row2 = {"A": "1", "B": "9"}
    assert helper._hash_row(row1) != helper._hash_row(row2)


# ---- _read_artifact ------------------------------------------------


def test_read_artifact_skips_empty_id(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_csv(workspace, "analysis/canonical/core_controls/A50_source_register.csv",
               ["SourceID", "Title"], [["", "no id row"], ["S-001", "valid row"]])
    result = helper._read_artifact(
        workspace / "analysis/canonical/core_controls/A50_source_register.csv",
        "SourceID",
    )
    assert "S-001" in result
    assert "" not in result
    assert len(result) == 1


def test_read_artifact_missing_file_returns_empty(helper, tmp_path) -> None:
    assert helper._read_artifact(tmp_path / "nope.csv", "SourceID") == {}


# ---- compute_diff classification -----------------------------------


def test_diff_classifies_added(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_csv(workspace, "analysis/canonical/core_controls/A50_source_register.csv",
               ["SourceID", "Title"], [["S-001", "test"]])
    summary = helper.compute_diff(workspace, prior={})
    assert summary.added == 1
    assert summary.modified == 0
    assert summary.removed == 0
    assert any(r.row_id == "S-001" and r.status == "added" for r in summary.rows)


def test_diff_classifies_modified(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_csv(workspace, "analysis/canonical/core_controls/A50_source_register.csv",
               ["SourceID", "Title"], [["S-001", "new title"]])
    # Prior has same row_id but different hash.
    prior = {"A50": {"S-001": "deadbeef" * 8}}
    summary = helper.compute_diff(workspace, prior=prior)
    assert summary.modified == 1
    assert summary.added == 0
    assert any(
        r.row_id == "S-001" and r.status == "modified"
        and r.old_hash == "deadbeef" * 8
        for r in summary.rows
    )


def test_diff_classifies_removed(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    # File is present but empty (header only).
    _write_csv(workspace, "analysis/canonical/core_controls/A50_source_register.csv",
               ["SourceID", "Title"], [])
    prior = {"A50": {"S-001": "stale_hash"}}
    summary = helper.compute_diff(workspace, prior=prior)
    assert summary.removed == 1
    assert any(r.row_id == "S-001" and r.status == "removed" for r in summary.rows)


def test_diff_classifies_unchanged(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_csv(workspace, "analysis/canonical/core_controls/A50_source_register.csv",
               ["SourceID", "Title"], [["S-001", "test"]])
    # Prior with the SAME hash → unchanged.
    current_hash = helper._hash_row({"SourceID": "S-001", "Title": "test"})
    summary = helper.compute_diff(workspace, prior={"A50": {"S-001": current_hash}})
    assert summary.unchanged == 1
    assert summary.added == 0
    assert not summary.needs_full_rebuild


def test_needs_full_rebuild_false_only_when_zero_changes(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    summary = helper.compute_diff(workspace, prior={})
    assert summary.needs_full_rebuild is False  # nothing in workspace, nothing in prior
    # Add one row.
    _write_csv(workspace, "analysis/canonical/core_controls/A50_source_register.csv",
               ["SourceID", "Title"], [["S-001", "test"]])
    summary = helper.compute_diff(workspace, prior={})
    assert summary.needs_full_rebuild is True


# ---- Cache round-trip ------------------------------------------------


def test_cache_write_and_read_round_trip(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    cache_path = workspace / helper.CACHE_REL
    snapshot = {
        "A50": {"S-001": "h1"},
        "A59": {"C-001": "h2"},
        "A70": {},
        "A62": {},
    }
    helper._write_cache(cache_path, snapshot)
    loaded = helper._load_cache(cache_path)
    assert loaded == snapshot


def test_cache_missing_returns_empty(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    cache_path = workspace / helper.CACHE_REL
    assert helper._load_cache(cache_path) == {}


def test_cache_wrong_version_returns_empty(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    cache_path = workspace / helper.CACHE_REL
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "cache_version": "0.0",  # wrong version
        "row_hashes": {"A50": {"S-001": "h1"}},
    }), encoding="utf-8")
    assert helper._load_cache(cache_path) == {}


def test_cache_malformed_json_returns_empty(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    cache_path = workspace / helper.CACHE_REL
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("not valid json {", encoding="utf-8")
    assert helper._load_cache(cache_path) == {}


def test_cache_top_level_not_dict_returns_empty(helper, tmp_path) -> None:
    """v1.2.2 round-1 (Codex MEDIUM): JSON-valid but top-level
    array/scalar payload must reject the whole cache (force full
    rebuild), NOT silently coerce."""
    workspace = _make_workspace(tmp_path)
    cache_path = workspace / helper.CACHE_REL
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(["this", "is", "a", "list"]), encoding="utf-8")
    assert helper._load_cache(cache_path) == {}


def test_cache_row_hashes_not_dict_returns_empty(helper, tmp_path) -> None:
    """v1.2.2 round-1 (Codex MEDIUM): if `row_hashes` is present but
    not a dict, the whole cache MUST be rejected."""
    workspace = _make_workspace(tmp_path)
    cache_path = workspace / helper.CACHE_REL
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "cache_version": helper.CACHE_VERSION,
        "row_hashes": ["bad", "shape"],  # list, not dict
    }), encoding="utf-8")
    assert helper._load_cache(cache_path) == {}


def test_cache_artifact_subtree_not_dict_returns_empty(helper, tmp_path) -> None:
    """v1.2.2 round-1 (Codex MEDIUM): if a tracked artifact's sub-tree
    exists but isn't a dict (e.g., someone wrote a string), reject
    the WHOLE cache rather than silently zero-out that artifact."""
    workspace = _make_workspace(tmp_path)
    cache_path = workspace / helper.CACHE_REL
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "cache_version": helper.CACHE_VERSION,
        "row_hashes": {
            "A50": "not a dict",  # invalid
            "A59": {"C-001": "valid_hash"},
        },
    }), encoding="utf-8")
    assert helper._load_cache(cache_path) == {}, (
        "schema-invalid sub-tree must reject the WHOLE cache; partial-load "
        "would let `compute_diff` emit `unchanged` for A59 rows from a "
        "broken cache, defeating the fail-CLOSED safety model."
    )


def test_cache_non_string_hash_value_returns_empty(helper, tmp_path) -> None:
    """v1.2.2 round-1 (Codex MEDIUM): mixed-type values inside an
    artifact sub-tree → reject the whole cache."""
    workspace = _make_workspace(tmp_path)
    cache_path = workspace / helper.CACHE_REL
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "cache_version": helper.CACHE_VERSION,
        "row_hashes": {
            "A50": {"S-001": 42},  # int instead of string
        },
    }), encoding="utf-8")
    assert helper._load_cache(cache_path) == {}


def test_cache_missing_artifact_subtree_tolerated(helper, tmp_path) -> None:
    """v1.2.2 round-1 (Codex MEDIUM): an artifact sub-tree that's
    MISSING (vs present-but-invalid) is tolerated — forward-compat
    for caches written before a tracked artifact was added. The
    missing artifact gets an empty {} sub-tree."""
    workspace = _make_workspace(tmp_path)
    cache_path = workspace / helper.CACHE_REL
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "cache_version": helper.CACHE_VERSION,
        "row_hashes": {
            "A50": {"S-001": "valid_hash"},
            # A59, A70, A62 missing — should be tolerated
        },
    }), encoding="utf-8")
    loaded = helper._load_cache(cache_path)
    assert loaded != {}, "missing-but-not-malformed sub-trees should be tolerated"
    assert loaded["A50"] == {"S-001": "valid_hash"}
    for missing in ("A59", "A70", "A62"):
        assert loaded[missing] == {}


def test_cache_atomic_write_uses_tmpfile_same_dir(helper, tmp_path, monkeypatch) -> None:
    """v1.2.2 design: tmpfile MUST be in the same directory as the
    cache file so `os.replace` is atomic (POSIX same-FS rename
    guarantee). Pin: monkeypatch tempfile.mkstemp to record where
    the tmp goes; assert it's under the cache's parent dir."""
    workspace = _make_workspace(tmp_path)
    cache_path = workspace / helper.CACHE_REL
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    recorded_dirs: list[str] = []
    import tempfile as _tf
    real_mkstemp = _tf.mkstemp
    def spy_mkstemp(**kwargs):
        recorded_dirs.append(kwargs.get("dir", ""))
        return real_mkstemp(**kwargs)
    monkeypatch.setattr(_tf, "mkstemp", spy_mkstemp)
    helper._write_cache(cache_path, {"A50": {"S-001": "h1"}})
    assert recorded_dirs, "mkstemp not called"
    # Compare resolved paths to handle macOS /private/var → /var symlink.
    assert Path(recorded_dirs[0]).resolve() == cache_path.parent.resolve(), (
        f"tmpfile in wrong dir: {recorded_dirs[0]} (expected {cache_path.parent})"
    )


# ---- collect_current_hashes ----------------------------------------


def test_collect_walks_all_tracked_artifacts(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_csv(workspace, "analysis/canonical/core_controls/A50_source_register.csv",
               ["SourceID"], [["S-001"]])
    snap = helper.collect_current_hashes(workspace)
    assert set(snap.keys()) == set(helper.TRACKED_ARTIFACTS.keys())
    assert "S-001" in snap["A50"]


# ---- CLI -----------------------------------------------------------


def test_main_returns_2_on_missing_workspace(helper, tmp_path) -> None:
    rc = helper.main(["--workspace", str(tmp_path / "absent")])
    assert rc == 2


def test_main_returns_1_on_force_rebuild(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    rc = helper.main(["--workspace", str(workspace), "--force-rebuild"])
    assert rc == 1


def test_main_update_cache_writes_file(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_csv(workspace, "analysis/canonical/core_controls/A50_source_register.csv",
               ["SourceID"], [["S-001"]])
    cache_path = workspace / helper.CACHE_REL
    assert not cache_path.exists()
    rc = helper.main(["--workspace", str(workspace), "--update-cache"])
    assert rc == 0
    assert cache_path.exists()
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["cache_version"] == helper.CACHE_VERSION
    assert "S-001" in cache["row_hashes"]["A50"]


def test_main_json_flag_emits_parseable_json(helper, tmp_path, capsys) -> None:
    workspace = _make_workspace(tmp_path)
    _write_csv(workspace, "analysis/canonical/core_controls/A50_source_register.csv",
               ["SourceID"], [["S-001"]])
    helper.main(["--workspace", str(workspace), "--json"])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["added"] == 1
    assert parsed["needs_full_rebuild"] is True
    assert any(r["row_id"] == "S-001" for r in parsed["rows"])


def test_main_text_summary_human_readable(helper, tmp_path, capsys) -> None:
    workspace = _make_workspace(tmp_path)
    _write_csv(workspace, "analysis/canonical/core_controls/A50_source_register.csv",
               ["SourceID"], [["S-001"]])
    helper.main(["--workspace", str(workspace)])
    out = capsys.readouterr().out
    assert "A72 Incremental Diff" in out
    assert "added:" in out
    assert "S-001" in out
