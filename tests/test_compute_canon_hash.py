"""Tests for scripts/compute_canon_hash.py (US-S3-04).

Verifies:
1. The current repo produces a deterministic 64-char hex hash.
2. Running the script twice on the same tree gives the same answer
   (determinism).
3. Mutating a policy file changes the hash (sensitivity).
4. Mutating a NON-policy file does not change the hash (scope).
5. --diff-against correctly reports CHANGED vs UNCHANGED.
6. --full mode emits per-file breakdown lines.
7. Script exits 2 when a policy file is missing.

Stdlib-only.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "compute_canon_hash.py"


def run_script(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd or REPO_ROOT,
    )


def test_current_repo_hash_is_deterministic_64_hex() -> None:
    result = run_script()
    assert result.returncode == 0, result.stderr
    hash1 = result.stdout.strip().split("\n")[0]
    assert len(hash1) == 64
    assert all(c in "0123456789abcdef" for c in hash1)
    # Run again and expect exact match.
    result2 = run_script()
    assert result2.stdout.strip().split("\n")[0] == hash1


def test_policy_file_mutation_changes_hash(tmp_path: Path) -> None:
    """Copy repo to tmp, mutate a policy file, compare hashes."""
    clone = tmp_path / "repo_clone"
    shutil.copytree(REPO_ROOT, clone, symlinks=True)
    before = run_script("--repo-root", str(clone)).stdout.strip()
    # Mutate a policy file: append a harmless blank line to immutable_invariants.
    invar = clone / "governance" / "immutable_invariants.md"
    invar.write_text(invar.read_text() + "\n\n<!-- test mutation -->\n", encoding="utf-8")
    after = run_script("--repo-root", str(clone)).stdout.strip()
    assert before != after, "policy-file mutation must change the hash"


def test_non_policy_file_mutation_does_not_change_hash(tmp_path: Path) -> None:
    """Copy repo to tmp, mutate a file NOT in POLICY_GLOBS, verify hash stays."""
    clone = tmp_path / "repo_clone2"
    shutil.copytree(REPO_ROOT, clone, symlinks=True)
    before = run_script("--repo-root", str(clone)).stdout.strip()
    # README is not a policy file.
    readme = clone / "README.md"
    readme.write_text(readme.read_text() + "\n<!-- harmless -->\n", encoding="utf-8")
    after = run_script("--repo-root", str(clone)).stdout.strip()
    assert before == after, "non-policy mutation should not change the hash"


def test_diff_against_reports_unchanged_for_same_tree() -> None:
    current = run_script().stdout.strip().split("\n")[0]
    result = run_script("--diff-against", current)
    assert result.returncode == 0
    out = result.stdout.strip().split("\n")
    assert out[0] == current
    assert out[1] == "UNCHANGED"


def test_diff_against_reports_changed_for_different_hash() -> None:
    # Pass a hash that cannot match the current repo.
    result = run_script("--diff-against", "deadbeef" * 8)
    assert result.returncode == 0
    out = result.stdout.strip().split("\n")
    assert out[1] == "CHANGED"


def test_diff_against_accepts_short_prefix() -> None:
    """A 6+ char prefix is accepted as short-hash form."""
    current = run_script().stdout.strip().split("\n")[0]
    prefix = current[:8]
    result = run_script("--diff-against", prefix)
    assert result.returncode == 0
    assert result.stdout.strip().split("\n")[1] == "UNCHANGED"


def test_diff_against_rejects_non_hex() -> None:
    result = run_script("--diff-against", "not-a-hash")
    assert result.returncode == 2
    assert "hex hash" in result.stderr


def test_full_mode_emits_per_file_breakdown() -> None:
    result = run_script("--full")
    assert result.returncode == 0
    lines = result.stdout.strip().split("\n")
    # First line = aggregate hash. Second line = "--- per-file breakdown ---".
    # Remaining lines = "<sha256>  <rel-path>".
    assert len(lines[0]) == 64
    assert "breakdown" in lines[1]
    body = [ln for ln in lines[2:] if ln.strip()]
    assert len(body) >= 20, "expected many policy files in breakdown"
    for ln in body:
        parts = ln.split("  ", 1)
        assert len(parts) == 2
        file_hash, rel = parts
        assert len(file_hash) == 64
        # Per-file breakdown paths must be POSIX-style relative paths inside the repo.
        assert not rel.startswith("/")
        assert (REPO_ROOT / rel).is_file(), f"breakdown references missing file: {rel}"


def test_script_exits_2_on_missing_policy_file(tmp_path: Path) -> None:
    """Copy only a subset of the tree so one policy file is missing."""
    clone = tmp_path / "partial_repo"
    clone.mkdir()
    # Intentionally do not copy governance/
    shutil.copytree(REPO_ROOT / "skills", clone / "skills")
    shutil.copytree(REPO_ROOT / "docs", clone / "docs")
    result = run_script("--repo-root", str(clone))
    assert result.returncode == 2
    assert "policy file missing" in result.stderr
    assert "governance/immutable_invariants.md" in result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
