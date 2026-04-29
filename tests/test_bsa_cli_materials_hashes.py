"""Tests for v1.4.4 bsa materials content-hash columns + raw retention
(closes lifecycle review rec #2: detect content drift; recover originals).

New surface:
  ContentHash / OriginalBytes / OriginalMtimeUtc — 3 optional columns
  in source_manifest.csv (third accepted A50 header variant).

  --restage-changed   re-extract files whose hash drifted vs manifest;
                      skip unchanged. Existing SourceID preserved.

  --keep-raw          copy original bytes to <stage1>/raw/ next to the
                      staged .md (analysts can refer back; recreate can
                      backfill hash columns from raw/).

Coverage:
  - _compute_content_hash (known input → known sha256).
  - _file_metadata returns (hash, size, mtime) tuple.
  - new manifests (--commit) emit the WITH_HASHES header by default.
  - existing manifests with old shape are appended in their existing shape.
  - _verify_manifest accepts the WITH_HASHES header variant.
  - --restage-changed: unchanged file skipped (logged "unchanged").
  - --restage-changed: changed file re-extracted, SourceID preserved.
  - --restage-changed: missing hash in manifest forces re-extract.
  - --keep-raw: copies original to <stage1>/raw/source_NNN_<slug>.<ext>.
  - --keep-raw: idempotent (same hash → skip the copy).
  - --keep-raw: original extension is preserved.
  - _recreate_manifest: backfills hashes from raw/ when present.
  - _recreate_manifest: leaves hash cells empty when no raw/.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "analysis" / "proposals" / "stage1" / "inputs").mkdir(parents=True)
    return ws


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "bsa_cli.py"), *args],
        capture_output=True, text=True, check=False,
    )


# ---- helpers --------------------------------------------------------


def test_compute_content_hash_matches_hashlib(tmp_path: Path) -> None:
    """The streaming sha256 helper produces the same digest as a
    one-shot hashlib.sha256 call on the same bytes."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _compute_content_hash
    finally:
        sys.path.pop(0)
    body = b"hello world\n" * 1000  # 12 KB — spans the chunk boundary
    p = tmp_path / "blob"
    p.write_bytes(body)
    assert _compute_content_hash(p) == hashlib.sha256(body).hexdigest()


def test_file_metadata_returns_tuple(tmp_path: Path) -> None:
    """_file_metadata returns (sha256_hex, size_bytes, mtime_iso_utc)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _file_metadata
    finally:
        sys.path.pop(0)
    p = tmp_path / "x.txt"
    p.write_text("abc", encoding="utf-8")
    h, size, mtime = _file_metadata(p)
    assert h == hashlib.sha256(b"abc").hexdigest()
    assert size == 3
    # ISO-8601 UTC with second precision, "Z" suffix.
    assert len(mtime) == 20 and mtime.endswith("Z")


# ---- manifest header / schema integration ---------------------------


def test_new_manifest_emits_with_hashes_header(tmp_path: Path) -> None:
    """A fresh `bsa materials --commit` writes a manifest with the
    WITH_HASHES header by default (v1.4.4 default schema)."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("# Doc body", encoding="utf-8")
    res = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res.returncode == 0, res.stderr
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    body = mp.read_text(encoding="utf-8")
    header = body.splitlines()[0]
    assert "ContentHash" in header
    assert "OriginalBytes" in header
    assert "OriginalMtimeUtc" in header


def test_new_manifest_populates_hash_for_each_row(tmp_path: Path) -> None:
    """Every row written by `--commit` must carry a non-empty
    ContentHash matching the source bytes."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    body = "# Doc body content\n"
    (src / "doc.md").write_text(body, encoding="utf-8")
    res = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res.returncode == 0
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    with mp.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["ContentHash"] == hashlib.sha256(
        body.encode("utf-8")
    ).hexdigest()
    assert rows[0]["OriginalBytes"] == str(len(body.encode("utf-8")))
    assert rows[0]["OriginalMtimeUtc"].endswith("Z")


def test_verify_accepts_with_hashes_header(tmp_path: Path) -> None:
    """--verify-manifest must accept the new WITH_HASHES header
    without flagging it as drift."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("body", encoding="utf-8")
    _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    res = _run_cli(f"--workspace={ws}", "materials", "--verify-manifest")
    assert res.returncode == 0, (
        f"verify must accept WITH_HASHES header; "
        f"stdout={res.stdout!r} stderr={res.stderr!r}"
    )
    assert "CLEAN" in res.stdout


def test_existing_manifest_old_shape_preserved_on_append(
    tmp_path: Path,
) -> None:
    """An existing manifest with the original (no-EffectiveDate, no-
    hashes) header must NOT be promoted to the new shape on append.
    Operator opt-in to schema upgrade is preserved."""
    ws = _make_workspace(tmp_path)
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    legacy_header = (
        "SourceID,SourceType,Title,Origin,AccessStatus,"
        "ReliabilityTier,Priority,Language,DateOrVersion,Notes\n"
    )
    legacy_row = (
        'S-001,document,old,prior/old.md,readable,'
        'T3,medium,en,2026-01-01,"hand-edited"\n'
    )
    mp.write_text(legacy_header + legacy_row, encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "new.md").write_text("body", encoding="utf-8")
    res = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res.returncode == 0, res.stderr
    body = mp.read_text(encoding="utf-8")
    assert body.startswith(legacy_header.rstrip("\n"))
    assert "ContentHash" not in body.splitlines()[0]


# ---- --restage-changed -----------------------------------------------


def test_restage_changed_skips_unchanged_file(tmp_path: Path) -> None:
    """A second --restage-changed pass over the SAME file (same bytes)
    must skip with 'unchanged' reason and exit 0 without emitting a
    new manifest row."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("stable body", encoding="utf-8")
    # First pass: normal stage with hashes.
    res1 = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res1.returncode == 0
    # Second pass: --restage-changed should detect identical hash.
    res2 = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--restage-changed",
    )
    assert res2.returncode == 0, res2.stderr
    assert "unchanged" in res2.stdout.lower()
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    with mp.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1, (
        f"second pass must not duplicate row; got {len(rows)} rows"
    )


def test_restage_changed_reextracts_changed_file(tmp_path: Path) -> None:
    """When the source bytes differ from the manifest's stored hash,
    --restage-changed must re-extract in place: preserve SourceID,
    update the hash row, overwrite the staged .md."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("original", encoding="utf-8")
    res1 = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res1.returncode == 0
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    with mp.open(newline="") as fh:
        rows_before = list(csv.DictReader(fh))
    sid_before = rows_before[0]["SourceID"]
    hash_before = rows_before[0]["ContentHash"]
    # Mutate the source.
    (src / "doc.md").write_text("mutated body content", encoding="utf-8")
    res2 = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--restage-changed",
    )
    assert res2.returncode == 0, res2.stderr
    with mp.open(newline="") as fh:
        rows_after = list(csv.DictReader(fh))
    assert len(rows_after) == 1
    assert rows_after[0]["SourceID"] == sid_before, (
        "SourceID must be preserved across restage"
    )
    assert rows_after[0]["ContentHash"] != hash_before, (
        "ContentHash must reflect the new source bytes"
    )
    expected = hashlib.sha256(b"mutated body content").hexdigest()
    assert rows_after[0]["ContentHash"] == expected


def test_restage_changed_legacy_manifest_with_no_hash_force_reextract(
    tmp_path: Path,
) -> None:
    """When a legacy manifest has no ContentHash for an Origin,
    --restage-changed conservatively re-extracts (operator can't
    confirm sameness without a baseline hash)."""
    ws = _make_workspace(tmp_path)
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    # Legacy manifest header WITHOUT hash columns.
    mp.write_text(
        "SourceID,SourceType,Title,Origin,AccessStatus,"
        "ReliabilityTier,Priority,Language,DateOrVersion,Notes\n"
        "S-001,document,doc,doc.md,readable,T3,medium,en,"
        "2026-01-01,legacy\n",
        encoding="utf-8",
    )
    # Place a matching staged file (so plan_conversions sees an existing
    # source_001_*.md and won't allocate S-002 for the same Origin).
    (inputs / "source_001_doc.md").write_text(
        "<!-- bsa materials: staged from doc.md (kind=text); "
        "SourceID=S-001 -->\n\n# legacy body",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("now changed body", encoding="utf-8")
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--restage-changed",
    )
    assert res.returncode == 0, res.stderr
    # Verify the staged file body now reflects the new content.
    staged = (inputs / "source_001_doc.md").read_text(encoding="utf-8")
    assert "now changed body" in staged


# ---- --keep-raw -----------------------------------------------------


def test_keep_raw_copies_original_to_raw_dir(tmp_path: Path) -> None:
    """--keep-raw mirrors the original src bytes into
    <stage1>/raw/source_NNN_<slug>.<original-ext>."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    body = b"## raw retention test\n\n* bullet"
    (src / "doc.md").write_bytes(body)
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--keep-raw",
    )
    assert res.returncode == 0, res.stderr
    raw_dir = ws / "analysis" / "proposals" / "stage1" / "raw"
    raw_files = list(raw_dir.glob("source_*_*.md"))
    assert len(raw_files) == 1
    assert raw_files[0].read_bytes() == body
    assert raw_files[0].suffix == ".md"  # original ext


def test_keep_raw_preserves_binary_extension_and_bytes(tmp_path: Path) -> None:
    """--keep-raw must preserve binary content byte-for-byte and use
    the ORIGINAL extension (not .md)."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    # Write a tiny "binary" file (using .txt to avoid pdf parsing).
    body = bytes(range(256))
    (src / "blob.txt").write_bytes(body)
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--keep-raw",
    )
    assert res.returncode == 0
    raw_dir = ws / "analysis" / "proposals" / "stage1" / "raw"
    raw_files = list(raw_dir.glob("source_*_*.txt"))
    assert len(raw_files) == 1
    assert raw_files[0].read_bytes() == body


def test_keep_raw_idempotent_skips_existing_match(tmp_path: Path) -> None:
    """A second --keep-raw run on the same source must not re-copy
    when the existing raw/ file has matching hash (idempotent)."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("stable body", encoding="utf-8")
    res1 = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--keep-raw",
    )
    assert res1.returncode == 0
    raw_dir = ws / "analysis" / "proposals" / "stage1" / "raw"
    raw_file = next(raw_dir.iterdir())
    mtime_before = raw_file.stat().st_mtime
    # Second pass under --restage-changed should detect unchanged AND
    # not touch the raw file (skip-unchanged short-circuits before the
    # writer reaches keep_raw).
    res2 = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--restage-changed", "--keep-raw",
    )
    assert res2.returncode == 0
    assert raw_file.stat().st_mtime == mtime_before


# ---- _recreate_manifest backfill from raw/ ---------------------------


def test_recreate_manifest_populates_hashes_from_raw(tmp_path: Path) -> None:
    """When raw/ contains the original source for a SID, recreate
    must populate the hash columns from those bytes."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    body = "raw-recovery body content\n"
    (src / "doc.md").write_text(body, encoding="utf-8")
    # Stage with --keep-raw so raw/ exists.
    _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--keep-raw",
    )
    # Now recreate the manifest from scratch.
    res = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res.returncode == 0, res.stderr
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    with mp.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    expected_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert rows[0]["ContentHash"] == expected_hash, (
        "recreate must backfill ContentHash from raw/ when present"
    )
    assert rows[0]["OriginalBytes"] == str(len(body.encode("utf-8")))


def test_recreate_manifest_leaves_hashes_empty_without_raw(
    tmp_path: Path,
) -> None:
    """When no raw/ retention happened, recreate emits the new
    header but leaves hash cells empty (operator can backfill via
    --restage-changed --keep-raw later)."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("no raw", encoding="utf-8")
    # Stage WITHOUT --keep-raw.
    _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    # Delete the manifest to simulate a recovery scenario.
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    mp.unlink()
    res = _run_cli(f"--workspace={ws}", "materials", "--recreate-manifest")
    assert res.returncode == 0, res.stderr
    with mp.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["ContentHash"] == "", (
        "recreate without raw/ must leave ContentHash empty"
    )


# ---- A50 schema integration -----------------------------------------


# ---- v1.4.4 R1 fixes — Codex review round 1 -------------------------


def test_restage_preserves_operator_curated_fields(tmp_path: Path) -> None:
    """R1 MAJOR #1 fix: restage must NOT clobber operator-edited
    cells (ReliabilityTier, Priority, EffectiveDate, Notes, ...).
    Only the source-derived columns + hash trio update."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("original body", encoding="utf-8")
    res1 = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res1.returncode == 0
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    # Operator edits the manifest row by hand: T2 reliability,
    # high priority, custom notes, an EffectiveDate.
    with mp.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
        fieldnames = list(csv.DictReader(open(mp)).fieldnames)
    assert len(rows) == 1
    rows[0]["ReliabilityTier"] = "T2"
    rows[0]["Priority"] = "high"
    rows[0]["EffectiveDate"] = "2025-12-01"
    rows[0]["Notes"] = "operator-curated review note"
    with mp.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)
    # Mutate the source so restage triggers in-place update.
    (src / "doc.md").write_text("mutated body content", encoding="utf-8")
    res2 = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--restage-changed",
    )
    assert res2.returncode == 0, res2.stderr
    with mp.open(newline="") as fh:
        rows_after = list(csv.DictReader(fh))
    assert len(rows_after) == 1
    # Operator cells must survive.
    assert rows_after[0]["ReliabilityTier"] == "T2"
    assert rows_after[0]["Priority"] == "high"
    assert rows_after[0]["EffectiveDate"] == "2025-12-01"
    assert rows_after[0]["Notes"] == "operator-curated review note"
    # Hash trio must reflect the new bytes.
    expected = hashlib.sha256(b"mutated body content").hexdigest()
    assert rows_after[0]["ContentHash"] == expected


def test_restage_handles_quoted_sourceid_correctly(tmp_path: Path) -> None:
    """R1 MAJOR #2 fix: when an existing manifest stored SourceID
    with quoting (csv.QUOTE_ALL or operator hand-edit), the restage
    SID lookup MUST still find it. The previous regex-based row
    matcher returned None for `"S-007",...` lines."""
    ws = _make_workspace(tmp_path)
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    # Author the manifest with QUOTE_ALL so SourceID is wrapped in
    # double quotes; the row reader must handle this.
    with mp.open("w", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)
        writer.writerow([
            "SourceID", "SourceType", "Title", "Origin", "AccessStatus",
            "ReliabilityTier", "Priority", "Language", "DateOrVersion",
            "EffectiveDate", "ContentHash", "OriginalBytes",
            "OriginalMtimeUtc", "Notes",
        ])
        writer.writerow([
            "S-001", "document", "doc", "doc.md", "readable",
            "T3", "medium", "en", "2026-01-01",
            "", "deadbeef" * 8, "10",
            "2026-01-01T00:00:00Z", "operator note",
        ])
    (inputs / "source_001_doc.md").write_text(
        "<!-- bsa materials: staged from doc.md (kind=text); "
        "SourceID=S-001 -->\n\n# legacy",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("changed", encoding="utf-8")
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--restage-changed",
    )
    assert res.returncode == 0, res.stderr
    # The row was found and updated; "operator note" must survive.
    with mp.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["SourceID"] == "S-001"
    assert rows[0]["Notes"] == "operator note"
    expected = hashlib.sha256(b"changed").hexdigest()
    assert rows[0]["ContentHash"] == expected


def test_keep_raw_refuses_symlinked_raw_dir(tmp_path: Path) -> None:
    """R1 MAJOR #3 fix: `<stage1>/raw/` must not be a symlink. A
    symlinked raw/ would let `--keep-raw` write outside the
    workspace. Defense-in-depth (matches the inputs/ + manifest
    containment surface added in v1.4.3)."""
    ws = _make_workspace(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (ws / "analysis" / "proposals" / "stage1" / "raw").symlink_to(elsewhere)
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("body", encoding="utf-8")
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--keep-raw",
    )
    # Staging itself succeeds (raw retention is best-effort), but
    # stderr must carry the symlink refusal so the operator notices.
    assert "symlink" in res.stderr.lower() or "raw" in res.stderr.lower()
    # The raw symlink target must NOT have been written into.
    assert not list(elsewhere.iterdir()), (
        f"refused-write must not leak into {elsewhere}"
    )


def test_dry_run_suggested_command_preserves_flags(tmp_path: Path) -> None:
    """R1 MINOR #1 fix: dry-run's 'Suggested next' must include
    --restage-changed and --keep-raw if they were passed."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("body", encoding="utf-8")
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--restage-changed", "--keep-raw",
    )
    assert res.returncode == 0
    assert "Suggested next:" in res.stdout
    assert "--restage-changed" in res.stdout
    assert "--keep-raw" in res.stdout


def test_keep_raw_copy2_preserves_source_mtime(tmp_path: Path) -> None:
    """R1 MINOR #2 fix: `--keep-raw` must use shutil.copy2 (preserves
    stat metadata including mtime). Without this, a later
    --recreate-manifest would backfill OriginalMtimeUtc as the copy
    time, not the source's actual mtime."""
    import os
    import time
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    f = src / "doc.md"
    f.write_text("body", encoding="utf-8")
    # Set source mtime to a known past time (epoch 1700000000 =
    # 2023-11-14T22:13:20Z) so we can detect non-preservation.
    past_mtime = 1700000000.0
    os.utime(f, (past_mtime, past_mtime))
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--keep-raw",
    )
    assert res.returncode == 0
    raw_files = list(
        (ws / "analysis" / "proposals" / "stage1" / "raw").iterdir()
    )
    assert len(raw_files) == 1
    # Permit small drift due to filesystem mtime precision.
    raw_mtime = raw_files[0].stat().st_mtime
    assert abs(raw_mtime - past_mtime) < 2, (
        f"copy2 must preserve source mtime; "
        f"raw_mtime={raw_mtime}, past_mtime={past_mtime}"
    )


# ---- v1.4.4 R2 fixes — Codex review round 2 -------------------------


def test_upsert_handles_quoted_hash_header_correctly(tmp_path: Path) -> None:
    """R2 NEW MAJOR #1 fix: when the existing manifest header is
    quoted (`"SourceID","SourceType",...,"OriginalMtimeUtc","Notes"`),
    `_upsert_draft_manifest` must csv-parse the header to detect the
    WITH_HASHES shape — otherwise appended new rows would land with
    base-shape (column count mismatch under a hash-shape header)."""
    ws = _make_workspace(tmp_path)
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    # Author the manifest with QUOTE_ALL on the WITH_HASHES shape.
    cols = [
        "SourceID", "SourceType", "Title", "Origin", "AccessStatus",
        "ReliabilityTier", "Priority", "Language", "DateOrVersion",
        "EffectiveDate", "ContentHash", "OriginalBytes",
        "OriginalMtimeUtc", "Notes",
    ]
    with mp.open("w", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)
        writer.writerow(cols)
        writer.writerow([
            "S-001", "document", "old", "old.md", "readable",
            "T3", "medium", "en", "2026-01-01",
            "", "abc" + "0" * 61, "5",
            "2026-01-01T00:00:00Z", "old note",
        ])
    (inputs / "source_001_old.md").write_text(
        "<!-- bsa materials: staged from old.md (kind=text); "
        "SourceID=S-001 -->\n\n# old",
        encoding="utf-8",
    )
    # Now stage a NEW source — the appended row must carry all 14
    # columns (matching the existing hash-shape header).
    src = tmp_path / "src"
    src.mkdir()
    (src / "fresh.md").write_text("new body", encoding="utf-8")
    res = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res.returncode == 0, res.stderr
    with mp.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    new_row = next(r for r in rows if r["SourceID"] == "S-002")
    # All hash columns present (not empty for the source-derived ones).
    assert new_row["ContentHash"] == hashlib.sha256(b"new body").hexdigest()
    assert new_row["OriginalBytes"] == "8"


def test_restage_rollback_unlinks_absent_targets(tmp_path: Path) -> None:
    """R2 NEW MAJOR #2 fix: when restage creates a NEW staged file
    (operator deleted the staged input but kept the manifest row),
    a manifest-write failure must UNLINK that file — leaving the
    new file behind would create a hash mismatch with the
    untouched manifest row."""
    import os
    ws = _make_workspace(tmp_path)
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("body v1", encoding="utf-8")
    # First stage to populate manifest + staged file.
    res1 = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res1.returncode == 0
    staged = inputs / "source_001_doc.md"
    assert staged.exists()
    # Operator deletes the staged file (simulating accidental rm)
    # but keeps the manifest row.
    staged.unlink()
    # Mutate src so restage will trigger.
    (src / "doc.md").write_text("body v2 changed", encoding="utf-8")
    # Make manifest read-only to force the manifest write to fail
    # at the os.replace step (not the read step — file is still
    # readable). This will make _atomic_write_text raise OSError
    # AFTER the staged file write.
    os.chmod(mp, 0o444)
    # Set parent to read-only too so os.replace can't even create
    # the tempfile in the parent dir.
    parent = mp.parent
    orig_parent_mode = parent.stat().st_mode
    os.chmod(parent, 0o555)
    try:
        res2 = _run_cli(
            f"--workspace={ws}", "materials", str(src),
            "--commit", "--restage-changed",
        )
    finally:
        os.chmod(parent, orig_parent_mode)
        os.chmod(mp, 0o644)
    # Manifest write should have failed (exit 2) AND the brand-new
    # restage staged file should have been unlinked (was absent
    # before; rollback preserves "absent" state).
    assert res2.returncode == 2
    assert not staged.exists(), (
        f"absent-before restage target must be unlinked on rollback; "
        f"stderr: {res2.stderr}"
    )


def test_a50_schema_lists_new_optional_columns() -> None:
    """The 3 new columns must appear in optional_order so the
    F5 hook validator accepts manifests carrying them."""
    schema_path = REPO_ROOT / "governance" / "schemas" / "a50.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    optional = schema["x-bsa-csv-columns-order"]["optional_order"]
    for col in ("ContentHash", "OriginalBytes", "OriginalMtimeUtc"):
        assert col in optional, f"{col!r} missing from a50 optional_order"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
