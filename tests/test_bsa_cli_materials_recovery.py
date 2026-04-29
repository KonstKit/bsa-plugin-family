"""Tests for v1.4.3 bsa materials manifest-maintenance modes
(closes lifecycle review rec #1: recovery for partial-write states).

Three new flags + one confirm flag:
  --verify-manifest   read-only diagnostic
  --recreate-manifest rebuild from provenance comments
  --prune-orphans     delete orphan inputs
  --yes               required for destructive operations

Coverage:
  - verify on a clean workspace -> CLEAN, exit 0.
  - verify with orphan manifest row (manifest references missing file)
    -> drift, exit 1, names the orphan row.
  - verify with orphan input file (file with no manifest row)
    -> drift, exit 1, names the orphan file.
  - verify with header drift (non-canonical column order)
    -> drift, exit 1, surfaces structural finding.
  - verify with missing manifest -> drift, exit 1, every input file orphaned.
  - verify on uninitialized workspace -> exit 2.
  - recreate-manifest happy path: rebuilds from provenance,
    backs up prior manifest atomically.
  - recreate-manifest skips files without provenance comments.
  - recreate-manifest fails-loud if backup write fails.
  - prune-orphans dry-run (no --yes): lists orphans, doesn't delete.
  - prune-orphans --yes: actually deletes orphan files.
  - prune-orphans refuses when structural drift present
    (header drift / manifest missing).
  - prune-orphans on clean workspace: CLEAN, exit 0, nothing deleted.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "analysis" / "proposals" / "stage1" / "inputs").mkdir(parents=True)
    return ws


def _write_staged_input(
    ws: Path, source_id: str, slug: str,
    *, origin: str = "src/foo.pdf", kind: str = "pdf",
) -> Path:
    """Write a staged input file with the v1.4.x provenance comment."""
    inputs_dir = ws / "analysis" / "proposals" / "stage1" / "inputs"
    sid_num = source_id.removeprefix("S-")
    p = inputs_dir / f"source_{sid_num}_{slug}.md"
    p.write_text(
        f"<!-- bsa materials: staged from {origin} (kind={kind}); "
        f"SourceID={source_id} -->\n\n## Body\n\nContent of {slug}\n",
        encoding="utf-8",
    )
    return p


_A50_HEADER_LINE = (
    "SourceID,SourceType,Title,Origin,AccessStatus,"
    "ReliabilityTier,Priority,Language,DateOrVersion,Notes"
)


def _write_manifest(ws: Path, rows: list[dict]) -> Path:
    """Write a source_manifest.csv with the canonical A50 header + given rows."""
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    cols = _A50_HEADER_LINE.split(",")
    lines = [_A50_HEADER_LINE]
    for r in rows:
        lines.append(",".join(r.get(c, "") for c in cols))
    mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mp


def _baseline_row(source_id: str, origin: str = "src/foo.pdf") -> dict:
    return {
        "SourceID": source_id,
        "SourceType": "document",
        "Title": "Foo",
        "Origin": origin,
        "AccessStatus": "readable",
        "ReliabilityTier": "T5",
        "Priority": "medium",
        "Language": "en",
        "DateOrVersion": "2026-04-28",
        "Notes": "",
    }


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "bsa_cli.py"), *args],
        capture_output=True, text=True, check=False,
    )


# ---- --verify-manifest ----------------------------------------------


def test_verify_clean_workspace_exits_0(tmp_path: Path) -> None:
    """Manifest matches inputs/ exactly + header is canonical -> CLEAN."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    _write_manifest(ws, [_baseline_row("S-001")])
    res = _run_cli(f"--workspace={ws}", "materials", "--verify-manifest")
    assert res.returncode == 0, f"clean workspace failed: {res.stdout}\n{res.stderr}"
    assert "CLEAN" in res.stdout


def test_verify_orphan_manifest_row_exits_1(tmp_path: Path) -> None:
    """Manifest mentions S-002 but only S-001 exists in inputs/."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    _write_manifest(ws, [
        _baseline_row("S-001"),
        _baseline_row("S-002", origin="src/missing.pdf"),
    ])
    res = _run_cli(f"--workspace={ws}", "materials", "--verify-manifest")
    assert res.returncode == 1
    assert "Orphan manifest rows" in res.stdout
    assert "S-002" in res.stdout
    assert "missing.pdf" in res.stdout


def test_verify_orphan_input_file_exits_1(tmp_path: Path) -> None:
    """Inputs/ has S-002 but manifest doesn't mention it."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    _write_staged_input(ws, "S-002", "bar")
    _write_manifest(ws, [_baseline_row("S-001")])
    res = _run_cli(f"--workspace={ws}", "materials", "--verify-manifest")
    assert res.returncode == 1
    assert "Orphan input files" in res.stdout
    assert "source_002_bar.md" in res.stdout


def test_verify_header_drift_exits_1(tmp_path: Path) -> None:
    """Manifest header columns don't match canonical A50 shape."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    mp.write_text(
        "WrongHeader,DriftedColumn,Order\nS-001,x,y\n",
        encoding="utf-8",
    )
    res = _run_cli(f"--workspace={ws}", "materials", "--verify-manifest")
    assert res.returncode == 1
    assert "header drifts" in res.stdout
    assert "Structural findings" in res.stdout


def test_verify_missing_manifest_exits_1(tmp_path: Path) -> None:
    """Inputs/ has files but no manifest at all."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    _write_staged_input(ws, "S-002", "bar")
    res = _run_cli(f"--workspace={ws}", "materials", "--verify-manifest")
    assert res.returncode == 1
    assert "manifest missing" in res.stdout
    # Both files reported as orphan.
    assert "source_001_foo.md" in res.stdout
    assert "source_002_bar.md" in res.stdout


def test_verify_uninitialized_workspace_exits_2(tmp_path: Path) -> None:
    """No analysis/ dir at all -> workspace not initialized."""
    res = _run_cli(f"--workspace={tmp_path}", "materials", "--verify-manifest")
    assert res.returncode == 2


# ---- --recreate-manifest --------------------------------------------


def test_recreate_rebuilds_from_provenance(tmp_path: Path) -> None:
    """Walk inputs/, read provenance, rebuild manifest."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo", origin="data/foo.pdf", kind="pdf")
    _write_staged_input(ws, "S-002", "bar", origin="data/bar.docx", kind="docx")
    _write_staged_input(ws, "S-003", "baz_call", origin="calls/baz.md", kind="text")
    res = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res.returncode == 0, f"recreate failed: {res.stderr}"
    assert "recreated manifest with 3 row" in res.stdout
    # Verify the manifest is well-formed.
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    assert mp.exists()
    with mp.open() as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) == 3
    sids = {r["SourceID"] for r in rows}
    assert sids == {"S-001", "S-002", "S-003"}
    # Origin reconstructed from provenance.
    origins = {r["Origin"] for r in rows}
    assert "data/foo.pdf" in origins
    # Then verify-manifest should pass.
    verify = _run_cli(f"--workspace={ws}", "materials", "--verify-manifest")
    assert verify.returncode == 0


def test_recreate_backs_up_prior_manifest(tmp_path: Path) -> None:
    """Existing manifest backed up to source_manifest.csv.bak.<ts>."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    _write_manifest(ws, [_baseline_row("S-001", origin="src/old.pdf")])
    res = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res.returncode == 0
    assert "backed up to source_manifest.csv.bak" in res.stdout
    # Backup file exists.
    backups = list(
        (ws / "analysis" / "proposals" / "stage1").glob("source_manifest.csv.bak.*")
    )
    assert len(backups) == 1, f"expected 1 backup, got {[b.name for b in backups]}"
    # Backup preserves the prior content.
    backup_content = backups[0].read_text(encoding="utf-8")
    assert "src/old.pdf" in backup_content


def test_recreate_skips_files_without_provenance(tmp_path: Path) -> None:
    """A file without the bsa-materials provenance comment is skipped."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    # Manually-authored file with no provenance comment.
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    (inputs / "source_002_handcrafted.md").write_text(
        "## Hand-edited\n\nNo provenance.\n", encoding="utf-8"
    )
    res = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res.returncode == 0
    # 1 row recreated (S-001), 1 skipped (S-002).
    assert "recreated manifest with 1 row" in res.stdout
    assert "SKIPPED 1 file" in res.stdout
    assert "source_002_handcrafted.md" in res.stdout


# ---- --prune-orphans ------------------------------------------------


def test_prune_dry_run_lists_without_deleting(tmp_path: Path) -> None:
    """No --yes: just list, don't delete."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    _write_staged_input(ws, "S-002", "orphan")
    _write_manifest(ws, [_baseline_row("S-001")])
    res = _run_cli(f"--workspace={ws}", "materials", "--prune-orphans")
    assert res.returncode == 0, f"dry-run prune failed: {res.stderr}"
    assert "DRY RUN" in res.stdout
    assert "source_002_orphan.md" in res.stdout
    # File still exists.
    assert (
        ws / "analysis" / "proposals" / "stage1" / "inputs" / "source_002_orphan.md"
    ).exists()


def test_prune_yes_actually_deletes(tmp_path: Path) -> None:
    """--yes: orphan files deleted from disk."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    _write_staged_input(ws, "S-002", "orphan_a")
    _write_staged_input(ws, "S-003", "orphan_b")
    _write_manifest(ws, [_baseline_row("S-001")])
    res = _run_cli(f"--workspace={ws}", "materials", "--prune-orphans", "--yes")
    assert res.returncode == 0
    assert "Deleted 2 orphan input file" in res.stdout
    # Orphans gone.
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    assert not (inputs / "source_002_orphan_a.md").exists()
    assert not (inputs / "source_003_orphan_b.md").exists()
    # S-001 (manifest-mentioned) preserved.
    assert (inputs / "source_001_foo.md").exists()


def test_prune_clean_workspace_exits_0_nothing_deleted(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    _write_manifest(ws, [_baseline_row("S-001")])
    res = _run_cli(f"--workspace={ws}", "materials", "--prune-orphans")
    assert res.returncode == 0
    assert "CLEAN" in res.stdout
    # Yes-mode still does nothing on clean.
    res2 = _run_cli(f"--workspace={ws}", "materials", "--prune-orphans", "--yes")
    assert res2.returncode == 0
    assert "CLEAN" in res2.stdout


def test_prune_refuses_when_header_drift(tmp_path: Path) -> None:
    """If structural drift is present, prune refuses — operator must
    --recreate-manifest first."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    _write_staged_input(ws, "S-002", "orphan")
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    mp.write_text(
        "WrongHeader,DriftedColumn\nS-001,x\n",
        encoding="utf-8",
    )
    res = _run_cli(f"--workspace={ws}", "materials", "--prune-orphans", "--yes")
    assert res.returncode == 2
    assert "refusing to prune" in res.stderr
    # Both files still exist (no deletion happened).
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    assert (inputs / "source_001_foo.md").exists()
    assert (inputs / "source_002_orphan.md").exists()


def test_prune_refuses_when_manifest_missing(tmp_path: Path) -> None:
    """No manifest at all is structural drift — refuse to prune."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    res = _run_cli(f"--workspace={ws}", "materials", "--prune-orphans", "--yes")
    assert res.returncode == 2
    assert "refusing to prune" in res.stderr


# ---- mutual exclusion + missing src_dir -----------------------------


def test_staging_mode_requires_src_dir(tmp_path: Path) -> None:
    """No src_dir + no manifest-maintenance flag = error."""
    ws = _make_workspace(tmp_path)
    res = _run_cli(f"--workspace={ws}", "materials")
    assert res.returncode == 2
    assert "src_dir is required" in res.stderr


def test_verify_and_recreate_mutually_exclusive(tmp_path: Path) -> None:
    """argparse enforces mutual exclusion of the 3 manifest-mode flags."""
    ws = _make_workspace(tmp_path)
    res = _run_cli(
        f"--workspace={ws}", "materials",
        "--verify-manifest", "--recreate-manifest",
    )
    # argparse exits 2 with a usage error.
    assert res.returncode == 2
    assert "not allowed with argument" in res.stderr or "mutually exclusive" in res.stderr


# ---- v1.4.3 R1 fixes — Codex review round 1 -------------------------


def test_recreate_refuses_when_inputs_dir_is_symlink(tmp_path: Path) -> None:
    """CRITICAL fix: recreate must reject a symlinked inputs/ chain
    so a malicious or accidental symlink can't redirect manifest
    writes outside the workspace."""
    ws = _make_workspace(tmp_path)
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # Replace real inputs/ with a symlink to elsewhere/.
    inputs.rmdir()
    inputs.symlink_to(elsewhere)
    res = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res.returncode == 2
    assert "symlink" in res.stderr.lower() or "containment" in res.stderr.lower()


def test_prune_refuses_when_inputs_dir_is_symlink(tmp_path: Path) -> None:
    """CRITICAL fix: prune must reject a symlinked inputs/ chain
    so --prune-orphans --yes can't unlink files outside the workspace."""
    ws = _make_workspace(tmp_path)
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    inputs.rmdir()
    inputs.symlink_to(elsewhere)
    res = _run_cli(
        f"--workspace={ws}", "materials", "--prune-orphans", "--yes",
    )
    assert res.returncode == 2
    assert "symlink" in res.stderr.lower() or "containment" in res.stderr.lower()


def test_prune_refuses_symlink_input_file(tmp_path: Path) -> None:
    """CRITICAL fix (defense-in-depth): prune must refuse to unlink
    a symlink even if the inputs/ dir itself is a real directory.
    A same-name symlinked source_NNN_*.md could otherwise redirect
    the unlink to /etc/passwd."""
    ws = _make_workspace(tmp_path)
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    target = tmp_path / "outside.txt"
    target.write_text("not the manifest's target")
    sym = inputs / "source_042_evil.md"
    sym.symlink_to(target)
    # Manifest empty -> the symlink is detected as orphan.
    _write_manifest(ws, [])
    res = _run_cli(
        f"--workspace={ws}", "materials", "--prune-orphans", "--yes",
    )
    assert res.returncode == 2
    assert "symlink" in res.stderr.lower()
    # Target outside workspace must remain intact.
    assert target.exists()


def test_recreate_backup_uses_microsecond_unique_name(tmp_path: Path) -> None:
    """MAJOR #1 fix: backup file name must include microseconds (or
    counter) so two same-second recreate calls don't clobber each
    other's backup."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    _write_manifest(ws, [_baseline_row("S-001")])
    # First recreate.
    res1 = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res1.returncode == 0, res1.stderr
    # Immediate second recreate: should ALSO succeed and produce a
    # second, distinct backup file.
    res2 = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res2.returncode == 0, res2.stderr
    backups = sorted(
        (ws / "analysis" / "proposals" / "stage1").glob(
            "source_manifest.csv.bak.*"
        )
    )
    assert len(backups) >= 2, (
        f"expected >=2 backups, got {len(backups)}: "
        f"{[b.name for b in backups]}"
    )


def test_recreate_skips_when_provenance_sid_mismatches_filename(
    tmp_path: Path,
) -> None:
    """MAJOR #4 fix: a renamed file (filename SID != provenance SID)
    must be skipped, not silently rebuilt with the wrong SID.

    Scenario: someone copied source_007_*.md and saved it as
    source_042_*.md without re-staging. The provenance comment
    inside still says SourceID=S-007. Recreate must not emit a
    row with SID=S-042 + Origin from S-007's source path."""
    ws = _make_workspace(tmp_path)
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    p = inputs / "source_042_renamed.md"
    p.write_text(
        "<!-- bsa materials: staged from src/foo.pdf (kind=pdf); "
        "SourceID=S-007 -->\n\n## Body\n",
        encoding="utf-8",
    )
    res = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res.returncode == 0
    assert "SID mismatch" in res.stdout or "mismatch" in res.stdout.lower()
    # Manifest should have 0 rows under the data section.
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    body = mp.read_text(encoding="utf-8")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected header-only manifest, got: {lines}"


def test_recreate_anchors_provenance_at_start(tmp_path: Path) -> None:
    """MAJOR #4 fix: provenance comment must appear at the start
    of the file (allowing only leading whitespace/BOM). A binary
    blob whose middle bytes happen to match must NOT recreate a row."""
    ws = _make_workspace(tmp_path)
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    p = inputs / "source_007_garbage.md"
    # 200 bytes of non-comment garbage, then a valid-looking
    # provenance comment in the middle.
    body = (
        "x" * 200
        + "<!-- bsa materials: staged from src/foo.pdf (kind=pdf); "
        + "SourceID=S-007 -->\n\n## Body\n"
    )
    p.write_text(body, encoding="utf-8")
    res = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res.returncode == 0
    # File should be skipped (no provenance at start).
    assert "SKIPPED" in res.stdout or "skipped" in res.stdout.lower()
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    body_out = mp.read_text(encoding="utf-8")
    assert "S-007" not in body_out


def test_recreate_skips_unknown_kind(tmp_path: Path) -> None:
    """MAJOR #4 fix: unknown kind values in provenance are rejected
    (operator must re-stage). Without this, a tampered file could
    set kind=evil and confuse downstream type heuristics."""
    ws = _make_workspace(tmp_path)
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    p = inputs / "source_007_weird.md"
    p.write_text(
        "<!-- bsa materials: staged from src/foo.evil (kind=evil); "
        "SourceID=S-007 -->\n\n## Body\n",
        encoding="utf-8",
    )
    res = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res.returncode == 0
    assert "unknown kind" in res.stdout.lower() or "skipped" in res.stdout.lower()
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    assert "S-007" not in mp.read_text(encoding="utf-8")


def test_verify_accepts_utf8_bom_header(tmp_path: Path) -> None:
    """MINOR #1 fix: a UTF-8 BOM at the start of the manifest must
    not be reported as header drift. (Spreadsheet tools sometimes
    re-save manifests with a BOM.)"""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    bom_body = "﻿" + _A50_HEADER_LINE + "\n" + ",".join(
        _baseline_row("S-001").get(c, "")
        for c in _A50_HEADER_LINE.split(",")
    ) + "\n"
    mp.write_text(bom_body, encoding="utf-8")
    res = _run_cli(f"--workspace={ws}", "materials", "--verify-manifest")
    assert res.returncode == 0, (
        f"BOM header should be accepted; got: stdout={res.stdout!r} "
        f"stderr={res.stderr!r}"
    )
    assert "CLEAN" in res.stdout


def test_verify_handles_5_digit_source_id(tmp_path: Path) -> None:
    """MINOR #2 fix: a 5-digit SourceID (S-10000+) must be matched
    by the verify regex. Original \\d{3,4} would have ignored it,
    masking orphan detection on very large engagements."""
    ws = _make_workspace(tmp_path)
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    p = inputs / "source_10000_huge.md"
    p.write_text(
        "<!-- bsa materials: staged from src/big.pdf (kind=pdf); "
        "SourceID=S-10000 -->\n\n## Body\n",
        encoding="utf-8",
    )
    # Manifest empty -> file is orphan.
    _write_manifest(ws, [])
    res = _run_cli(f"--workspace={ws}", "materials", "--verify-manifest")
    assert res.returncode == 1
    assert "source_10000_huge.md" in res.stdout, (
        f"5-digit SID file should be detected as orphan; "
        f"stdout: {res.stdout}"
    )


def test_yes_without_prune_warns(tmp_path: Path) -> None:
    """MINOR #3 fix: --yes without --prune-orphans must emit a
    stderr warning so operators know the flag was ignored
    (typo-detection)."""
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    _write_manifest(ws, [_baseline_row("S-001")])
    res = _run_cli(
        f"--workspace={ws}", "materials", "--verify-manifest", "--yes",
    )
    assert res.returncode == 0
    assert "--yes" in res.stderr and "prune-orphans" in res.stderr


def test_recreate_handles_utf8_multibyte_at_head_boundary(
    tmp_path: Path,
) -> None:
    """R3 NEW MAJOR fix: a valid staged file whose first 512 bytes
    end mid-multibyte (e.g., the last byte is the start of a 3-byte
    Cyrillic char) MUST still be processed correctly. Strict-decode
    of a flat byte slice would have raised UnicodeDecodeError; the
    IncrementalDecoder fix buffers the trailing partial sequence."""
    ws = _make_workspace(tmp_path)
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    p = inputs / "source_007_cyrillic.md"
    # Provenance comment is short ASCII, then a long Cyrillic body
    # that pushes past the 512-byte head window. The multibyte char
    # at the boundary must not break decode.
    body = (
        "<!-- bsa materials: staged from src/foo.pdf (kind=pdf); "
        "SourceID=S-007 -->\n\n## Body\n\n"
        + ("привет " * 100)  # ≈1400 bytes of Cyrillic
    )
    p.write_text(body, encoding="utf-8")
    res = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res.returncode == 0, (
        f"recreate must accept a valid file even when the 512-byte "
        f"head ends mid-multibyte; stderr: {res.stderr}"
    )
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    assert "S-007" in mp.read_text(encoding="utf-8"), (
        f"valid staged file should produce a manifest row; "
        f"stdout: {res.stdout}"
    )


def test_recreate_skips_binary_prefix_files(tmp_path: Path) -> None:
    """R2 NEW MAJOR fix: a file whose first bytes are non-UTF-8
    binary garbage MUST be skipped, even if a later region of the
    head contains a literal `<!-- bsa materials: ... -->` comment.
    The earlier `errors="ignore"` decode would silently drop the
    invalid bytes and let the anchored `.match` succeed."""
    ws = _make_workspace(tmp_path)
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    p = inputs / "source_007_binary.md"
    body = (
        b"\x80\x81\x82\xff"  # invalid UTF-8 leading bytes
        + b"<!-- bsa materials: staged from src/foo.pdf (kind=pdf); "
        + b"SourceID=S-007 -->\n\n## Body\n"
    )
    p.write_bytes(body)
    res = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res.returncode == 0
    # File should be skipped (decode failed -> no provenance).
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    assert "S-007" not in mp.read_text(encoding="utf-8")


def test_recreate_refuses_when_workspace_uninitialized(tmp_path: Path) -> None:
    """R2 NEW MINOR fix: the materials lock must not auto-create
    stage1/. If the workspace isn't fully initialized, recreate
    should refuse cleanly instead of leaving a sentinel behind."""
    ws = tmp_path / "ws"
    ws.mkdir()
    # No analysis/ at all — `WorkspaceState.is_initialized()` rejects
    # this with exit 2 BEFORE we reach the lock helper, but
    # still verifies the cleanup contract.
    res = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res.returncode == 2
    assert not (ws / "analysis").exists(), (
        "uninitialized workspace must not be modified by --recreate-manifest"
    )


def test_lock_blocks_concurrent_recreate(tmp_path: Path) -> None:
    """MAJOR #2 fix: while a `_materials_lock` is held by another
    process, --recreate-manifest must refuse with a clear error
    instead of racing on the backup file."""
    import fcntl
    import os
    ws = _make_workspace(tmp_path)
    _write_staged_input(ws, "S-001", "foo")
    _write_manifest(ws, [_baseline_row("S-001")])
    # v1.4.3 R2 fix: lock now lives under analysis/ (not stage1/) so
    # we don't auto-create stage1 just for a sentinel file.
    lock_path = ws / "analysis" / ".bsa_materials.lock"
    # Acquire the lock from this test process.
    fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Now try the CLI — should fail to acquire and report it.
        res = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
        assert res.returncode == 2
        assert "lock" in res.stderr.lower() or "in progress" in res.stderr.lower()
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
