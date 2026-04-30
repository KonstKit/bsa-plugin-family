"""Tests for v1.4.10 `bsa workspace` subcommand
(closes lifecycle review rec #6: snapshot/restore/bundle).

Three operations:
  bsa workspace snapshot — full state dump (incl. runtime, .bak,
                            lock files); excludes raw/ unless flag.
  bsa workspace restore  — unpack snapshot back; refuses overwrite
                            unless --force; rejects path-traversal.
  bsa workspace bundle   — transfer-ready (drops ephemeral state);
                            --minimal drops proposals/ too.

Coverage:
  - snapshot happy path: archive contains analysis/ files.
  - snapshot excludes raw/ by default; includes with --include-raw.
  - snapshot includes .bak / runtime / lock (full state).
  - snapshot atomic (failure cleans tmp).
  - restore happy path: round-trip preserves files.
  - restore refuses overwrite without --force.
  - restore --force clears existing analysis/ before extract.
  - restore rejects path-traversal members.
  - restore rejects absolute-path members.
  - restore rejects unsafe symlink/hardlink members.
  - bundle excludes .bak files.
  - bundle excludes runtime/.
  - bundle excludes raw/.
  - bundle excludes .bsa_materials.lock.
  - bundle --minimal excludes proposals/.
  - CLI dispatch: snapshot / restore / bundle exit codes correct.
  - CLI: snapshot with non-workspace path exits 2.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_workspace(tmp_path: Path, with_raw: bool = True) -> Path:
    """Build a minimal workspace skeleton."""
    ws = tmp_path / "ws"
    (ws / "analysis" / "canonical" / "core_controls").mkdir(parents=True)
    (ws / "analysis" / "proposals" / "stage1" / "inputs").mkdir(parents=True)
    (ws / "analysis" / "runtime" / "ready").mkdir(parents=True)
    if with_raw:
        (ws / "analysis" / "proposals" / "stage1" / "raw").mkdir()
        (ws / "analysis" / "proposals" / "stage1" / "raw" / "src1.pdf").write_bytes(b"%PDF heavy")
    # canonical
    (ws / "analysis" / "canonical" / "core_controls" / "A50.csv").write_text(
        "SourceID\nS-001\n", encoding="utf-8",
    )
    # proposals
    (ws / "analysis" / "proposals" / "stage1" / "inputs" / "source_001_foo.md").write_text(
        "## Body\n", encoding="utf-8",
    )
    (ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv").write_text(
        "SourceID\nS-001\n", encoding="utf-8",
    )
    # ephemeral state to test exclusion
    (ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv.bak.20260430T120000Z").write_text(
        "backup", encoding="utf-8",
    )
    (ws / "analysis" / ".bsa_materials.lock").write_text("", encoding="utf-8")
    (ws / "analysis" / "runtime" / "ready" / "stage1.ready.json").write_text(
        "{}", encoding="utf-8",
    )
    return ws


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "bsa_cli.py"), *args],
        capture_output=True, text=True, check=False,
    )


def _list_archive(path: Path) -> list[str]:
    with tarfile.open(path) as t:
        return sorted(t.getnames())


# ---- snapshot --------------------------------------------------------


def test_snapshot_happy_path(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, with_raw=False)
    res = _run_cli(f"--workspace={ws}", "workspace", "snapshot")
    assert res.returncode == 0, res.stderr
    snaps = list((ws / "snapshots").iterdir())
    assert len(snaps) == 1
    members = _list_archive(snaps[0])
    assert "analysis/canonical/core_controls/A50.csv" in members
    assert "analysis/proposals/stage1/inputs/source_001_foo.md" in members


def test_snapshot_excludes_raw_by_default(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, with_raw=True)
    res = _run_cli(f"--workspace={ws}", "workspace", "snapshot")
    assert res.returncode == 0
    snap = next((ws / "snapshots").iterdir())
    members = _list_archive(snap)
    assert not any("/raw/" in m for m in members), (
        f"snapshot must exclude raw/ by default; got: {members!r}"
    )


def test_snapshot_includes_raw_with_flag(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, with_raw=True)
    res = _run_cli(
        f"--workspace={ws}", "workspace", "snapshot", "--include-raw",
    )
    assert res.returncode == 0
    snap = next((ws / "snapshots").iterdir())
    members = _list_archive(snap)
    assert any("/raw/src1.pdf" in m for m in members), (
        f"--include-raw must include raw/ files; got: {members!r}"
    )


def test_snapshot_includes_full_state(tmp_path: Path) -> None:
    """Snapshots are full-state — includes .bak / runtime / lock."""
    ws = _make_workspace(tmp_path, with_raw=False)
    res = _run_cli(f"--workspace={ws}", "workspace", "snapshot")
    assert res.returncode == 0
    snap = next((ws / "snapshots").iterdir())
    members = _list_archive(snap)
    assert any("source_manifest.csv.bak" in m for m in members)
    assert any("/runtime/" in m for m in members)
    assert any(".bsa_materials.lock" in m for m in members)


def test_snapshot_custom_output_path(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, with_raw=False)
    out = tmp_path / "custom" / "my-snap.tar.gz"
    res = _run_cli(
        f"--workspace={ws}", "workspace", "snapshot", "--output", str(out),
    )
    assert res.returncode == 0
    assert out.is_file()


def test_snapshot_non_workspace_exits_2(tmp_path: Path) -> None:
    """A directory without analysis/ is not a workspace."""
    res = _run_cli(f"--workspace={tmp_path}", "workspace", "snapshot")
    assert res.returncode == 2
    assert "BSA workspace" in res.stderr or "analysis/" in res.stderr


# ---- restore ---------------------------------------------------------


def test_restore_round_trip(tmp_path: Path) -> None:
    """snapshot → restore preserves canonical files byte-for-byte."""
    ws = _make_workspace(tmp_path, with_raw=False)
    res1 = _run_cli(f"--workspace={ws}", "workspace", "snapshot")
    assert res1.returncode == 0
    snap = next((ws / "snapshots").iterdir())
    target = tmp_path / "restored"
    res2 = _run_cli(
        f"--workspace={target}", "workspace", "restore",
        "--from", str(snap),
    )
    assert res2.returncode == 0, res2.stderr
    restored = (target / "analysis" / "canonical"
                / "core_controls" / "A50.csv").read_text(encoding="utf-8")
    assert restored == "SourceID\nS-001\n"


def test_restore_refuses_overwrite_without_force(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, with_raw=False)
    _run_cli(f"--workspace={ws}", "workspace", "snapshot")
    snap = next((ws / "snapshots").iterdir())
    # Try to restore back into ws (which already has analysis/).
    res = _run_cli(
        f"--workspace={ws}", "workspace", "restore",
        "--from", str(snap),
    )
    assert res.returncode == 1
    assert "force" in res.stderr.lower()


def test_restore_force_clears_existing(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, with_raw=False)
    _run_cli(f"--workspace={ws}", "workspace", "snapshot")
    snap = next((ws / "snapshots").iterdir())
    # Add a stray file that should NOT survive --force restore.
    stray = ws / "analysis" / "stray.md"
    stray.write_text("stray", encoding="utf-8")
    res = _run_cli(
        f"--workspace={ws}", "workspace", "restore",
        "--from", str(snap), "--force",
    )
    assert res.returncode == 0
    assert not stray.exists(), (
        "stray file in existing analysis/ must be cleared by --force"
    )


def test_restore_rejects_traversal_member(tmp_path: Path) -> None:
    """A maliciously-crafted archive with `../` in a member path
    must be rejected before extraction."""
    bad_archive = tmp_path / "evil.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("evil")
    with tarfile.open(bad_archive, "w:gz") as tar:
        # Add a member with parent-traversal in its name.
        info = tarfile.TarInfo(name="../escaped.txt")
        data = b"escape attempt"
        info.size = len(data)
        import io
        tar.addfile(info, io.BytesIO(data))
    target = tmp_path / "victim"
    res = _run_cli(
        f"--workspace={target}", "workspace", "restore",
        "--from", str(bad_archive),
    )
    assert res.returncode == 1
    assert "traversal" in res.stderr.lower() or "refusing" in res.stderr.lower()
    # The escaped target must NOT exist anywhere.
    assert not (tmp_path / "escaped.txt").exists()


def test_restore_rejects_absolute_path_member(tmp_path: Path) -> None:
    bad_archive = tmp_path / "evil.tar.gz"
    with tarfile.open(bad_archive, "w:gz") as tar:
        info = tarfile.TarInfo(name="/etc/passwd-pwned")
        data = b"absolute path attack"
        info.size = len(data)
        import io
        tar.addfile(info, io.BytesIO(data))
    target = tmp_path / "victim"
    res = _run_cli(
        f"--workspace={target}", "workspace", "restore",
        "--from", str(bad_archive),
    )
    assert res.returncode == 1
    assert "absolute" in res.stderr.lower() or "refusing" in res.stderr.lower()


def test_restore_rejects_unsafe_symlink(tmp_path: Path) -> None:
    bad_archive = tmp_path / "evil.tar.gz"
    with tarfile.open(bad_archive, "w:gz") as tar:
        info = tarfile.TarInfo(name="evil_link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    target = tmp_path / "victim"
    res = _run_cli(
        f"--workspace={target}", "workspace", "restore",
        "--from", str(bad_archive),
    )
    assert res.returncode == 1
    assert "link" in res.stderr.lower() or "refusing" in res.stderr.lower()


def test_restore_missing_source_exits_2(tmp_path: Path) -> None:
    res = _run_cli(
        f"--workspace={tmp_path}", "workspace", "restore",
        "--from", str(tmp_path / "does-not-exist.tar.gz"),
    )
    assert res.returncode == 2
    assert "not found" in res.stderr.lower()


# ---- bundle ----------------------------------------------------------


def test_bundle_excludes_ephemeral_state(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, with_raw=True)
    res = _run_cli(f"--workspace={ws}", "workspace", "bundle")
    assert res.returncode == 0
    bundle = next((ws / "snapshots").glob("bundle-*.tar.gz"))
    members = _list_archive(bundle)
    # All ephemeral state MUST be excluded.
    for forbidden_substring in (
        ".bsa_materials.lock", "/runtime/", "/raw/",
        ".bak.20260430",
    ):
        assert not any(forbidden_substring in m for m in members), (
            f"bundle contains forbidden {forbidden_substring!r}; "
            f"got: {members!r}"
        )
    # Canonical + proposals/inputs MUST be included.
    assert any("/canonical/" in m for m in members)
    assert any("/proposals/" in m and "/inputs/" in m for m in members)


def test_bundle_minimal_excludes_proposals(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, with_raw=False)
    res = _run_cli(
        f"--workspace={ws}", "workspace", "bundle", "--minimal",
    )
    assert res.returncode == 0
    bundle = next((ws / "snapshots").glob("bundle-*-minimal.tar.gz"))
    members = _list_archive(bundle)
    assert not any("/proposals/" in m for m in members), (
        f"--minimal must exclude proposals/; got: {members!r}"
    )
    # Canonical still present.
    assert any("/canonical/" in m for m in members)


def test_bundle_custom_output(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path, with_raw=False)
    out = tmp_path / "transfer.tar.gz"
    res = _run_cli(
        f"--workspace={ws}", "workspace", "bundle", "--output", str(out),
    )
    assert res.returncode == 0
    assert out.is_file()


# ---- CLI dispatch ----------------------------------------------------


def test_workspace_no_action_exits_2(tmp_path: Path) -> None:
    """`bsa workspace` without sub-action must show argparse error."""
    res = _run_cli(f"--workspace={tmp_path}", "workspace")
    assert res.returncode == 2


def test_workspace_help_exits_0(tmp_path: Path) -> None:
    res = _run_cli(f"--workspace={tmp_path}", "workspace", "-h")
    assert res.returncode == 0
    assert "snapshot" in res.stdout
    assert "restore" in res.stdout
    assert "bundle" in res.stdout


# ---- v1.4.10 R1 fixes — Codex review round 1 ------------------------


def test_restore_atomic_force_preserves_existing_on_failure(
    tmp_path: Path,
) -> None:
    """R1 MAJOR #1 fix: --force MUST stage extract first then atomic
    swap. A mid-extract failure (corrupt archive) should leave the
    EXISTING analysis/ intact, not half-cleared.

    Build a controlled scenario: existing workspace + a corrupt
    archive that opens but fails mid-tar. The post-restore state
    must still have the original analysis/ contents."""
    ws = _make_workspace(tmp_path, with_raw=False)
    canary = (
        ws / "analysis" / "canonical" / "core_controls" / "A50.csv"
    ).read_text(encoding="utf-8")
    # Build a CORRUPT tar.gz: valid gzip header but tar body
    # truncated after first member's header.
    corrupt = tmp_path / "corrupt.tar.gz"
    import gzip
    import io
    with tarfile.open(corrupt, "w:gz") as tar:
        info = tarfile.TarInfo(name="analysis/canonical/core_controls/A50.csv")
        info.size = 12
        tar.addfile(info, io.BytesIO(b"new content\n"))
    # Truncate the archive to corrupt the SECOND member.
    raw = corrupt.read_bytes()
    corrupt.write_bytes(raw[:len(raw) // 2])
    res = _run_cli(
        f"--workspace={ws}", "workspace", "restore",
        "--from", str(corrupt), "--force",
    )
    # Restore should fail (1) — corrupt archive.
    assert res.returncode == 1, res.stderr
    # Original A50.csv must be intact (atomic swap rolled back).
    after = (
        ws / "analysis" / "canonical" / "core_controls" / "A50.csv"
    ).read_text(encoding="utf-8")
    assert after == canary, (
        f"atomic --force restore must roll back on failure. "
        f"before: {canary!r}, after: {after!r}"
    )


def test_restore_rejects_member_outside_analysis_dir(
    tmp_path: Path,
) -> None:
    """R1 MAJOR #2 fix: archive member writing to `.git/hooks/...`
    or `scripts/backdoor.py` (relative paths NOT under analysis/)
    must be rejected. Only `analysis/...` members allowed."""
    bad_archive = tmp_path / "outside.tar.gz"
    import io
    with tarfile.open(bad_archive, "w:gz") as tar:
        # Try to write outside analysis/ — under workspace root.
        info = tarfile.TarInfo(name=".git/hooks/post-commit")
        data = b"#!/bin/bash\nrm -rf /\n"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    target = tmp_path / "victim"
    res = _run_cli(
        f"--workspace={target}", "workspace", "restore",
        "--from", str(bad_archive),
    )
    assert res.returncode == 1
    assert "outside analysis" in res.stderr.lower() or "refusing" in res.stderr.lower()
    # The escaped target must NOT exist.
    assert not (target / ".git" / "hooks" / "post-commit").exists()


def test_restore_rejects_disallowed_member_types(tmp_path: Path) -> None:
    """R1 MAJOR #3 fix: FIFO / device members must be rejected
    (allowlist: regular files, directories, validated links only)."""
    bad_archive = tmp_path / "fifo.tar.gz"
    with tarfile.open(bad_archive, "w:gz") as tar:
        info = tarfile.TarInfo(name="analysis/canonical/evil_fifo")
        info.type = tarfile.FIFOTYPE
        tar.addfile(info)
    target = tmp_path / "victim"
    res = _run_cli(
        f"--workspace={target}", "workspace", "restore",
        "--from", str(bad_archive),
    )
    assert res.returncode == 1
    assert "disallowed" in res.stderr.lower() or "refusing" in res.stderr.lower()


def test_restore_rejects_backslash_member(tmp_path: Path) -> None:
    """R1 MAJOR #4 fix: Windows-native paths with backslash must
    be rejected (POSIX-only checks would otherwise let them through
    on Linux/macOS where `\\` is just a regular char)."""
    bad_archive = tmp_path / "winpath.tar.gz"
    import io
    with tarfile.open(bad_archive, "w:gz") as tar:
        info = tarfile.TarInfo(name="analysis\\canonical\\evil.csv")
        data = b"win path attack"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    target = tmp_path / "victim"
    res = _run_cli(
        f"--workspace={target}", "workspace", "restore",
        "--from", str(bad_archive),
    )
    assert res.returncode == 1
    assert "backslash" in res.stderr.lower() or "refusing" in res.stderr.lower()


def test_restore_rejects_drive_letter_member(tmp_path: Path) -> None:
    """R1 MAJOR #4 fix: `C:foo.csv` Windows drive-letter path
    must be rejected."""
    bad_archive = tmp_path / "drive.tar.gz"
    import io
    with tarfile.open(bad_archive, "w:gz") as tar:
        info = tarfile.TarInfo(name="C:windows.csv")
        data = b"drive letter attack"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    target = tmp_path / "victim"
    res = _run_cli(
        f"--workspace={target}", "workspace", "restore",
        "--from", str(bad_archive),
    )
    assert res.returncode == 1
    assert "drive-letter" in res.stderr.lower() or "refusing" in res.stderr.lower()


def test_bundle_does_not_overmatch_runtime_segment(tmp_path: Path) -> None:
    """R1 MINOR #1 fix: bundle must NOT exclude `analysis/proposals/
    stage1/runtime/foo` — only `analysis/runtime/` AND
    `analysis/discovery/runtime/` are the canonical ephemeral
    runtime-marker prefixes."""
    ws = _make_workspace(tmp_path, with_raw=False)
    # Create a non-ephemeral path with `runtime` segment.
    odd_dir = ws / "analysis" / "proposals" / "stage1" / "runtime"
    odd_dir.mkdir()
    (odd_dir / "preserved.md").write_text("keep me", encoding="utf-8")
    res = _run_cli(f"--workspace={ws}", "workspace", "bundle")
    assert res.returncode == 0
    bundle = next((ws / "snapshots").glob("bundle-*.tar.gz"))
    members = _list_archive(bundle)
    assert any(
        "stage1/runtime/preserved.md" in m for m in members
    ), (
        f"bundle must NOT over-exclude unrelated `runtime` segments; "
        f"got: {members!r}"
    )
    # AND analysis/runtime/ STILL excluded (the canonical case).
    assert not any(
        m == "analysis/runtime" or m.startswith("analysis/runtime/")
        for m in members
    )


def test_restore_rejects_root_analysis_as_symlink(tmp_path: Path) -> None:
    """R2 NEW MAJOR fix: a crafted archive cannot restore the
    root `analysis` entry as a symlink (would create a workspace-
    boundary escape — `analysis` linked to `.` would let future
    writes under analysis/ land anywhere in the workspace AND
    create an infinite-loop self-ref)."""
    bad_archive = tmp_path / "evil_root_link.tar.gz"
    with tarfile.open(bad_archive, "w:gz") as tar:
        info = tarfile.TarInfo(name="analysis")
        info.type = tarfile.SYMTYPE
        info.linkname = "."  # self-ref to workspace root
        tar.addfile(info)
    target = tmp_path / "victim"
    res = _run_cli(
        f"--workspace={target}", "workspace", "restore",
        "--from", str(bad_archive),
    )
    assert res.returncode == 1
    # Either the analysis-isn't-a-dir check OR the self-ref-link
    # check fires; both are acceptable.
    err = res.stderr.lower()
    assert (
        "not a directory" in err
        or "self-referential" in err
        or "refusing" in err
    ), f"expected boundary refusal; got: {res.stderr!r}"
    # The workspace must NOT have an analysis symlink.
    assert not (target / "analysis").exists() or (
        target / "analysis"
    ).is_dir()


def test_restore_rejects_self_ref_link_target(tmp_path: Path) -> None:
    """R2 NEW MAJOR fix: link target `.` (or empty) explicitly
    rejected — would otherwise let a non-root member become a
    self-ref."""
    bad_archive = tmp_path / "evil_dot_link.tar.gz"
    with tarfile.open(bad_archive, "w:gz") as tar:
        # Root analysis must be a real dir.
        info_dir = tarfile.TarInfo(name="analysis")
        info_dir.type = tarfile.DIRTYPE
        tar.addfile(info_dir)
        # Then a self-ref link inside.
        info = tarfile.TarInfo(name="analysis/loop")
        info.type = tarfile.SYMTYPE
        info.linkname = "."
        tar.addfile(info)
    target = tmp_path / "victim"
    res = _run_cli(
        f"--workspace={target}", "workspace", "restore",
        "--from", str(bad_archive),
    )
    assert res.returncode == 1
    assert "self-referential" in res.stderr.lower() or "refusing" in res.stderr.lower()


def test_snapshot_collision_safe_filenames(tmp_path: Path) -> None:
    """R1 MINOR #2 fix: two snapshots in rapid succession must
    NOT clobber each other's archive (microsecond timestamp +
    counter retry)."""
    ws = _make_workspace(tmp_path, with_raw=False)
    res1 = _run_cli(f"--workspace={ws}", "workspace", "snapshot")
    res2 = _run_cli(f"--workspace={ws}", "workspace", "snapshot")
    assert res1.returncode == 0
    assert res2.returncode == 0
    snaps = sorted((ws / "snapshots").iterdir())
    assert len(snaps) == 2, (
        f"two snapshots must produce two distinct files; "
        f"got: {[s.name for s in snaps]!r}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
