"""Tests for v1.4.12 hotfix — second-pass audit findings on
v1.4.5..v1.4.7 extractor surface.

Codex audit findings closed:
  MAJOR #1: --max-output-chars cap (pptx/html/eml/msg/image had no
            output safety net — only --max-mb on source bytes).
  MAJOR #2: EML unhandled MIME leaves (S/MIME signatures, text/calendar,
            vcards) silently dropped.
  MAJOR #3: OCR per-page timeout + page cap (was: unbounded subprocess
            time on multi-page TIFFs).
  MINOR #1: HTML Unicode whitespace normalization (NBSP / em-space /
            ZWSP survived; hurt grep consistency).
  MINOR #2: <title><![CDATA[...]]></title> ignored (HTMLParser routes
            to unknown_decl, not handle_data).
  MINOR #3: hash/restage/keep-raw e2e coverage gap for binary-image
            mutation + mixed-format batch.
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import io
import shutil
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


# ---- MAJOR #1: --max-output-chars cap -------------------------------


def test_max_output_chars_truncates_long_body(tmp_path: Path) -> None:
    """A source whose conversion produces more than --max-output-chars
    must be truncated with a clear footer. Exercise via plain markdown
    (uses _read_text → no extractor-specific cap kicks in first)."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    long_body = "x" * 1000
    (src / "huge.md").write_text(long_body, encoding="utf-8")
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--max-output-chars=100",
    )
    assert res.returncode == 0, res.stderr
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    staged = next(inputs.glob("source_*_huge.md"))
    body = staged.read_text(encoding="utf-8")
    # Provenance comment + truncated body + footer.
    assert "max-output-chars" in body
    # Body content is truncated near the cap (allow some room for
    # the provenance comment header).
    assert len(body) < 1000


def test_max_output_chars_default_passes_short_bodies(tmp_path: Path) -> None:
    """Short bodies must NOT trigger truncation footer."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "tiny.md").write_text("short body", encoding="utf-8")
    res = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res.returncode == 0
    staged = next(
        (ws / "analysis/proposals/stage1/inputs").glob("source_*_tiny.md")
    )
    assert "max-output-chars" not in staged.read_text(encoding="utf-8")


# ---- MAJOR #2: EML unhandled MIME leaves ----------------------------


def test_eml_smime_signature_part_appears_under_attachments(
    tmp_path: Path,
) -> None:
    """An S/MIME signature (`application/pkcs7-signature`) must be
    listed under Attachments with a `[signature]` tag — not silently
    dropped from the staged output."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: signed mail\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/signed; boundary="BOUNDARY"\r\n\r\n'
        b"--BOUNDARY\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Real body content.\r\n"
        b"--BOUNDARY\r\n"
        b'Content-Type: application/pkcs7-signature; name="smime.p7s"\r\n'
        b"Content-Transfer-Encoding: base64\r\n\r\n"
        b"MIIDsWQYJKoZIhvcNAQcCoIIDojCCA54CAQ==\r\n"
        b"--BOUNDARY--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    assert "Real body content." in out
    assert "## Attachments" in out
    # signature appears with its tag (could be [signature] or as filename).
    assert "[signature]" in out or "smime.p7s" in out
    assert "pkcs7-signature" in out


def test_eml_text_calendar_part_listed(tmp_path: Path) -> None:
    """A text/calendar invite (ICS attachment) must be recorded."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: meeting invite\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="BOUNDARY"\r\n\r\n'
        b"--BOUNDARY\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"See you at 10am.\r\n"
        b"--BOUNDARY\r\n"
        b'Content-Type: text/calendar; method=REQUEST\r\n\r\n'
        b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"
        b"--BOUNDARY--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    assert "## Attachments" in out
    assert "text/calendar" in out
    assert "[calendar]" in out


# ---- MAJOR #3: OCR timeout + max-pages ------------------------------


def _ensure_pytesseract() -> None:
    try:
        importlib.import_module("pytesseract")
    except ImportError:
        pytest.skip("pytesseract not installed")
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract binary not on PATH")


def test_ocr_max_pages_caps_multipage_tiff(tmp_path: Path) -> None:
    """A multi-page TIFF with N pages > --ocr-max-pages must process
    only the first cap-N pages AND surface a truncation footer."""
    _ensure_pytesseract()
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_image
    finally:
        sys.path.pop(0)
    from PIL import Image, ImageDraw
    p = tmp_path / "scan.tiff"
    pages = []
    for i in range(5):
        img = Image.new("RGB", (200, 80), color="white")
        d = ImageDraw.Draw(img)
        d.text((10, 30), f"P{i}", fill="black")
        pages.append(img)
    pages[0].save(
        str(p), format="TIFF", save_all=True, append_images=pages[1:],
    )
    out = _convert_image(p, ocr_enabled=True, ocr_max_pages=2)
    # Only Page 1 + Page 2 OCR'd; truncation footer for the 3 skipped.
    assert "### Page 1" in out
    assert "### Page 2" in out
    assert "### Page 3" not in out
    assert "OCR truncated" in out
    assert "3 of 5 pages NOT processed" in out


def test_ocr_timeout_param_threaded_through(tmp_path: Path) -> None:
    """--ocr-timeout-sec is passed to pytesseract.image_to_string.
    Functional check via a real call (timeout=60 is plenty for a
    tiny image; we just verify the call doesn't error)."""
    _ensure_pytesseract()
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_image
    finally:
        sys.path.pop(0)
    from PIL import Image, ImageDraw
    p = tmp_path / "img.png"
    img = Image.new("RGB", (200, 80), color="white")
    d = ImageDraw.Draw(img)
    d.text((10, 30), "TEST", fill="black")
    img.save(str(p))
    out = _convert_image(
        p, ocr_enabled=True, ocr_timeout_sec=120,
    )
    assert "lang=eng" in out
    assert "## OCR" in out


# ---- MINOR #1: HTML Unicode whitespace normalization ----------------


def test_html_normalizes_nbsp_and_em_space(tmp_path: Path) -> None:
    """NBSP (U+00A0), em-space (U+2003), ZWSP (U+200B) must be
    normalized — was ASCII-only before v1.4.12 audit."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_html
    finally:
        sys.path.pop(0)
    p = tmp_path / "page.html"
    # NBSP (\xc2\xa0 in utf-8) + em-space (U+2003 = \xe2\x80\x83) +
    # ZWSP (U+200B = \xe2\x80\x8b) between "Hello" and "World".
    p.write_bytes(
        b"<html><body><p>Hello\xc2\xa0\xe2\x80\x83\xe2\x80\x8bWorld</p></body></html>"
    )
    out = _convert_html(p)
    # ZWSP entirely stripped; NBSP + em-space collapsed to single space.
    assert "Hello World" in out, f"got: {out!r}"


# ---- MINOR #2: <title><![CDATA[...]]></title> -----------------------


def test_html_title_cdata_captured(tmp_path: Path) -> None:
    """`<title><![CDATA[Title Text]]></title>` must yield 'Title Text'
    as the H1 (was silently dropped pre-v1.4.12 because HTMLParser
    routes CDATA to unknown_decl, not handle_data)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_html
    finally:
        sys.path.pop(0)
    p = tmp_path / "page.html"
    p.write_text(
        "<html><head><title><![CDATA[CDATA-Title]]></title></head>"
        "<body><p>body</p></body></html>",
        encoding="utf-8",
    )
    out = _convert_html(p)
    assert "# CDATA-Title" in out, f"got: {out!r}"


# ---- MINOR #3: binary-image hash mutation + mixed-format batch ------


def test_restage_changed_detects_binary_image_mutation(
    tmp_path: Path,
) -> None:
    """Image content (binary bytes) MUST trigger restage when
    re-saved with different pixels, even though both files are valid
    PNGs of the same dimensions."""
    _ensure_pytesseract()
    from PIL import Image, ImageDraw
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    img1 = Image.new("RGB", (100, 50), color="white")
    d1 = ImageDraw.Draw(img1)
    d1.text((10, 20), "ONE", fill="black")
    img1.save(str(src / "shot.png"))
    res1 = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res1.returncode == 0
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    with mp.open(newline="") as fh:
        rows_before = list(csv.DictReader(fh))
    hash_before = rows_before[0]["ContentHash"]
    # Mutate image pixels; same dimensions, different content.
    img2 = Image.new("RGB", (100, 50), color="white")
    d2 = ImageDraw.Draw(img2)
    d2.text((10, 20), "TWO", fill="black")
    img2.save(str(src / "shot.png"))
    res2 = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--restage-changed",
    )
    assert res2.returncode == 0
    with mp.open(newline="") as fh:
        rows_after = list(csv.DictReader(fh))
    assert rows_after[0]["ContentHash"] != hash_before
    assert rows_after[0]["SourceID"] == rows_before[0]["SourceID"]


def test_keep_raw_mixed_format_batch(tmp_path: Path) -> None:
    """A mixed batch (md + html + png) with --keep-raw produces raw
    copies with correct extensions for each format."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("text body", encoding="utf-8")
    (src / "page.html").write_text(
        "<html><body><h1>Hi</h1></body></html>", encoding="utf-8",
    )
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")
    Image.new("RGB", (50, 50), color="red").save(str(src / "shot.png"))
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--keep-raw",
    )
    assert res.returncode == 0, res.stderr
    raw_dir = ws / "analysis" / "proposals" / "stage1" / "raw"
    raw_files = sorted(raw_dir.iterdir())
    extensions = {p.suffix for p in raw_files}
    assert ".md" in extensions
    assert ".html" in extensions
    assert ".png" in extensions


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
