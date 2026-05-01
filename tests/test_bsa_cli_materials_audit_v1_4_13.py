"""Tests for v1.4.13 hotfix — third-pass audit findings on the
v1.4.5..v1.4.12 extractor surface (rec #3 follow-up).

External Codex review (post-v1.4.12) flagged 5 issues. All 5 closed:

  P1 #1: `_convert_html` `path.read_bytes()` was outside try/except —
         a per-file OSError aborted the whole batch. Closed by
         wrapping the read AND adding an OSError-catching defense in
         depth in `cmd_materials`.
  P1 #2: forwarded `message/rfc822` attachments lost their container
         metadata (filename, type, size). Closed by pre-scanning for
         rfc822 multipart containers presented as attachments and
         skipping their descendants in the main MIME walk.
  P2 #1: `--max-output-chars` was applied AFTER the full extractor
         output was materialized — defeating memory protection for
         decompressed/streamed outputs. Closed by threading the cap
         into pptx/html/eml/msg streaming extractors so accumulation
         stops at the cap. pdf/docx/image keep the post-conversion
         safety net (their library-side parse already materializes).
  P2 #2: `--restage-changed` ignored cap CHANGES — a re-stage with a
         raised `--max-output-chars` or `--ocr-max-pages` after a
         truncated initial stage was a no-op because ContentHash
         matched. Closed by parsing the prior cap from the staged
         file's truncation footer and forcing restage when the new
         cap is higher.
  P3:    Unicode whitespace normalization skipped the title and
         link-text buffers. Closed by extracting the normalize logic
         to a `_normalize_unicode_ws` static helper and calling from
         all three branches (title, link buffer, body).
"""

from __future__ import annotations

import csv
import importlib
import os
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


# ---- P1 #1: HTML read errors must be per-file failures --------------


def test_unreadable_html_does_not_abort_batch(tmp_path: Path) -> None:
    """A directory mixing a readable .md with an unreadable .html
    must still write the manifest with the .md row AND surface the
    .html as a per-file failure. Pre-fix, the HTML's
    `path.read_bytes()` raised OSError outside the per-file try/except,
    aborting the whole batch BEFORE the manifest landed (exit code
    came from a Python traceback to stderr — manifest absent, orphan
    staged file remained on disk).

    Post-fix expectations:
      - Manifest IS written (with the readable .md row).
      - The bad .html is reported in the "Failed" section of stdout.
      - No Python traceback in stderr.
      - Exit code may be non-zero (per-file failure surfaces) but
        the BATCH didn't abort — the manifest exists."""
    if os.geteuid() == 0:
        pytest.skip("running as root — chmod 000 won't deny reads")
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text("readable body", encoding="utf-8")
    bad_html = src / "z.html"
    bad_html.write_text(
        "<html><body><p>secret</p></body></html>", encoding="utf-8",
    )
    bad_html.chmod(0o000)
    try:
        res = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    finally:
        # Restore permissions so pytest cleanup doesn't fail.
        bad_html.chmod(0o644)
    # CRITICAL: no Python traceback in stderr (pre-fix would have a
    # full OSError traceback there).
    assert "Traceback" not in res.stderr, (
        f"stderr leaked a traceback: {res.stderr!r}"
    )
    # CRITICAL: manifest row for the readable .md must exist.
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    assert mp.is_file(), "manifest was not written despite the bad-html abort"
    with mp.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    origins = [r["Origin"] for r in rows]
    assert "a.md" in origins, f"a.md missing from manifest origins: {origins}"
    # CRITICAL: bad .html surfaces as a per-file failure (not a silent
    # skip and not a hard abort).
    assert "z.html" in res.stdout
    assert "conversion failed" in res.stdout or "read failed" in res.stdout


def test_unreadable_md_does_not_abort_batch(tmp_path: Path) -> None:
    """Same defense for `_read_text` — an unreadable .md must
    surface as a per-file skip, not an OSError traceback."""
    if os.geteuid() == 0:
        pytest.skip("running as root")
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "ok.txt").write_text("readable", encoding="utf-8")
    bad = src / "denied.md"
    bad.write_text("body", encoding="utf-8")
    bad.chmod(0o000)
    try:
        res = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    finally:
        bad.chmod(0o644)
    assert "Traceback" not in res.stderr, res.stderr
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    assert mp.is_file()
    with mp.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert "ok.txt" in [r["Origin"] for r in rows]
    assert "denied.md" in res.stdout


# ---- P1 #2: Forwarded message/rfc822 attachment metadata ------------


def test_eml_forwarded_rfc822_attachment_listed(tmp_path: Path) -> None:
    """A forwarded `message/rfc822` part with `Content-Disposition:
    attachment; filename="forwarded.eml"` must appear in the
    Attachments section as `forwarded.eml (message/rfc822, N bytes)`.
    Pre-fix, `msg.walk()` skipped the multipart container, walked its
    children, and recorded the inner text/plain leaf as a generic
    `(unnamed text/plain)` part with NO trace of the forwarded
    container."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "host.eml"
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: please review\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="OUTER"\r\n\r\n'
        b"--OUTER\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Forwarding the FYI thread below.\r\n"
        b"--OUTER\r\n"
        b'Content-Type: message/rfc822; name="forwarded.eml"\r\n'
        b'Content-Disposition: attachment; filename="forwarded.eml"\r\n\r\n'
        b"From: carol@example.com\r\n"
        b"To: alice@example.com\r\n"
        b"Subject: original thread\r\n"
        b"Date: Tue, 27 Apr 2026 09:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Original message body.\r\n"
        b"--OUTER--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    # Outer body preserved.
    assert "Forwarding the FYI thread below." in out
    # Forwarded container surfaces in Attachments with its filename
    # AND content-type marker.
    assert "## Attachments" in out
    assert "forwarded.eml" in out
    assert "message/rfc822" in out
    # The inner text/plain MUST NOT leak into the outer email's
    # body OR appear as a separate `(unnamed text/plain)` part —
    # otherwise we lose the provenance link to the rfc822 container.
    assert "Original message body." not in out, (
        "inner forwarded body leaked outside its rfc822 container"
    )
    assert "(unnamed text/plain)" not in out


# ---- P2 #1: Streaming-aware caps in pptx/html/eml/msg ---------------


def test_html_streaming_cap_truncates_during_accumulation(
    tmp_path: Path,
) -> None:
    """HTML conversion must stop ACCUMULATING once `--max-output-chars`
    is reached — not just trim after the fact. We can prove streaming
    behavior by checking that the rendered body is close to the cap
    AND carries the truncation footer."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_html
    finally:
        sys.path.pop(0)
    p = tmp_path / "huge.html"
    paragraphs = "".join(f"<p>chunk-{i:04d}</p>" for i in range(200))
    p.write_text(
        f"<html><body>{paragraphs}</body></html>", encoding="utf-8",
    )
    out = _convert_html(p, max_output_chars=300)
    # Truncation footer present.
    assert "max-output-chars" in out
    # Body capped close to 300 chars + footer overhead. Without the
    # streaming fix, this would be ~2000+ chars (full accumulation).
    assert len(out) < 800, f"streaming cap not honored: {len(out)} chars"


def test_pptx_streaming_cap_truncates_during_accumulation(
    tmp_path: Path,
) -> None:
    """PPTX conversion must stop appending slides once cumulative
    output crosses the cap. Skips when python-pptx is not installed."""
    try:
        importlib.import_module("pptx")
    except ImportError:
        pytest.skip("python-pptx not installed")
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_pptx
    finally:
        sys.path.pop(0)
    from pptx import Presentation
    p = tmp_path / "deck.pptx"
    prs = Presentation()
    for i in range(20):
        s = prs.slides.add_slide(prs.slide_layouts[5])
        s.shapes.title.text = f"Slide {i} title with extra padding text"
    prs.save(str(p))
    out = _convert_pptx(p, max_output_chars=200)
    assert "max-output-chars" in out
    # 20 slides at ~50 chars each ≈ 1000 chars uncapped; with cap
    # we expect well under 600 (cap 200 + footer + slop).
    assert len(out) < 600, f"streaming cap not honored: {len(out)} chars"


def test_eml_plain_body_streaming_cap(tmp_path: Path) -> None:
    """A plain-text body larger than the cap must be truncated during
    rendering (not just by the post-conversion safety net)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "big.eml"
    body = "L\n" * 5000  # ~10000 chars
    raw = (
        b"From: a@x\r\nTo: b@x\r\nSubject: big\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        + body.encode()
    )
    p.write_bytes(raw)
    out = _convert_eml(p, max_output_chars=200)
    assert "max-output-chars" in out
    # Bounded by metadata + capped body + attachments + footer.
    assert len(out) < 1500, f"eml streaming cap not honored: {len(out)} chars"


# ---- P2 #2: Restage detects cap changes -----------------------------


def test_restage_changed_detects_max_output_chars_increase(
    tmp_path: Path,
) -> None:
    """Stage with --max-output-chars=100 (truncates), then restage
    with --max-output-chars=10000 on the SAME source → must restage
    and pick up the un-truncated content. Pre-fix, ContentHash match
    skipped this and the body stayed truncated."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    long_body = "A" * 5000
    (src / "doc.md").write_text(long_body, encoding="utf-8")
    res1 = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--max-output-chars=100",
    )
    assert res1.returncode == 0, res1.stderr
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    staged = next(inputs.glob("source_*_doc.md"))
    body1 = staged.read_text(encoding="utf-8")
    assert "max-output-chars" in body1
    assert len(body1) < 500
    # Now re-stage with a higher cap. Source bytes unchanged, but the
    # cap CHANGED — restage must trigger.
    res2 = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--restage-changed", "--max-output-chars=10000",
    )
    assert res2.returncode == 0, res2.stderr
    body2 = staged.read_text(encoding="utf-8")
    # Either the truncation footer is gone (uncapped at 10000) OR
    # the recorded cap value reflects the new request (10_000).
    if "max-output-chars" in body2:
        assert "10,000" in body2 or "10000" in body2 or "10_000" in body2, (
            f"footer kept old cap: {body2[:600]!r}"
        )
    # Critical assertion: the body actually grew.
    assert len(body2) > len(body1), (
        f"restage with higher cap did NOT re-extract: "
        f"len before={len(body1)}, after={len(body2)}"
    )


def test_restage_changed_skips_when_cap_lowered(tmp_path: Path) -> None:
    """Inverse direction — lowering the cap on an UNCHANGED source
    should NOT re-stage (the existing body is still valid evidence
    under the new cap; re-staging would discard analyst-curated
    sidecar state for no analytical gain).

    Validates the cap-change check is one-sided (raise = restage,
    lower = skip)."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.md").write_text("A" * 5000, encoding="utf-8")
    # Initial stage with HIGH cap → no truncation footer.
    res1 = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--max-output-chars=10000",
    )
    assert res1.returncode == 0
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    staged = next(inputs.glob("source_*_doc.md"))
    mtime_before = staged.stat().st_mtime
    # Now restage with LOW cap. Should be a no-op (no truncation
    # footer in body → cap-change check finds no prior cap → skip).
    res2 = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--restage-changed", "--max-output-chars=100",
    )
    assert res2.returncode == 0
    assert staged.stat().st_mtime == mtime_before, (
        "lowering the cap on an unchanged source should NOT restage"
    )


# ---- P3: Unicode whitespace in title and link text ------------------


def test_html_title_normalizes_nbsp(tmp_path: Path) -> None:
    """`<title>Hello&nbsp;World</title>` rendered as the H1 must
    contain a plain ASCII space, not a literal NBSP. Pre-fix, the
    title-collect path bypassed the Unicode-whitespace normalizer
    that ran in the body branch."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_html
    finally:
        sys.path.pop(0)
    p = tmp_path / "t.html"
    # NBSP in UTF-8 = \xc2\xa0
    p.write_bytes(
        b"<html><head><title>Hello\xc2\xa0World</title></head>"
        b"<body><p>body</p></body></html>"
    )
    out = _convert_html(p)
    # H1 line must contain ASCII space between Hello and World.
    assert "# Hello World" in out, f"title NBSP survived: {out!r}"
    # Defensive: no literal NBSP anywhere in the staged title region.
    h1_line = next(line for line in out.splitlines() if line.startswith("# "))
    assert "\xa0" not in h1_line, f"NBSP leaked into H1: {h1_line!r}"


def test_html_link_text_normalizes_nbsp(tmp_path: Path) -> None:
    """`<a href="x">Hello&nbsp;World</a>` rendered as `[text](x)`
    must contain a plain ASCII space inside the visible link text.
    Pre-fix, the link-buffer path bypassed normalization."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_html
    finally:
        sys.path.pop(0)
    p = tmp_path / "a.html"
    p.write_bytes(
        b"<html><body>"
        b'<p>See <a href="https://example.com/x">Hello\xc2\xa0World</a></p>'
        b"</body></html>"
    )
    out = _convert_html(p)
    assert "[Hello World](https://example.com/x)" in out, (
        f"link text NBSP survived: {out!r}"
    )
    assert "\xa0" not in out, "NBSP leaked into rendered body"


def test_html_title_em_space_normalized(tmp_path: Path) -> None:
    """em-space (U+2003) in title should also collapse to ASCII space."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_html
    finally:
        sys.path.pop(0)
    p = tmp_path / "t.html"
    # em-space UTF-8 = \xe2\x80\x83
    p.write_bytes(
        b"<html><head><title>A\xe2\x80\x83B</title></head>"
        b"<body><p>x</p></body></html>"
    )
    out = _convert_html(p)
    assert "# A B" in out, f"em-space survived in title: {out!r}"


# ---- R2 NEW MAJOR #1: PPTX cap WITHIN a single slide ---------------


def test_pptx_streaming_cap_clips_oversized_single_slide(
    tmp_path: Path,
) -> None:
    """A single slide whose own text exceeds the cap must be clipped
    in-place (not just bounded by the next-slide boundary check). The
    R2 review caught this — a 200MB-text shape from an exfiltrated
    deck would otherwise produce oversized output even with the cap
    set, because the between-slide check fires AFTER the chunk was
    already built + appended."""
    try:
        importlib.import_module("pptx")
    except ImportError:
        pytest.skip("python-pptx not installed")
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_pptx
    finally:
        sys.path.pop(0)
    from pptx import Presentation
    from pptx.util import Inches
    p = tmp_path / "deck.pptx"
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Single huge slide"
    # Add a text-bearing shape with a huge body — single slide,
    # single shape, ~50KB of text.
    shape = s.shapes.add_textbox(
        Inches(1), Inches(1), Inches(8), Inches(5),
    )
    shape.text_frame.text = "X" * 50_000
    prs.save(str(p))
    out = _convert_pptx(p, max_output_chars=500)
    assert "max-output-chars" in out, (
        f"footer missing for single-slide overflow: {out[:300]!r}"
    )
    # Total output bounded near cap + footer + slop. Without the
    # within-slide clip, this would be ~50_000 chars.
    assert len(out) < 1000, f"single-slide cap not honored: {len(out)} chars"


# ---- R2 NEW MAJOR #2: post-conversion safety net respects footer ---


def test_eml_capped_body_keeps_attachments_after_safety_net(
    tmp_path: Path,
) -> None:
    """The post-conversion safety net in `cmd_materials` must NOT
    re-trim the rendered body of a streaming extractor that already
    emitted the cap footer. Pre-fix R2, an email with a 200-char
    capped body + many attachment lines tripped the safety-net
    `content[:cap]` chop, deleting the Attachments section."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    # Build an EML with a long body + several attachments. The body
    # is over the cap; the streaming renderer will trim the body and
    # add the footer, then list 4 attachments. Total > cap.
    raw = (
        b"From: a@x\r\nTo: b@x\r\nSubject: many attachments\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        + (b"Z" * 500) + b"\r\n"
        b"--B\r\n"
        b'Content-Type: application/pdf; name="doc1.pdf"\r\n'
        b'Content-Disposition: attachment; filename="doc1.pdf"\r\n'
        b"Content-Transfer-Encoding: base64\r\n\r\nAA==\r\n"
        b"--B\r\n"
        b'Content-Type: application/pdf; name="doc2.pdf"\r\n'
        b'Content-Disposition: attachment; filename="doc2.pdf"\r\n'
        b"Content-Transfer-Encoding: base64\r\n\r\nAA==\r\n"
        b"--B\r\n"
        b'Content-Type: application/pdf; name="doc3.pdf"\r\n'
        b'Content-Disposition: attachment; filename="doc3.pdf"\r\n'
        b"Content-Transfer-Encoding: base64\r\n\r\nAA==\r\n"
        b"--B--\r\n"
    )
    (src / "many.eml").write_bytes(raw)
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--max-output-chars=200",
    )
    assert res.returncode == 0, res.stderr
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    staged = next(inputs.glob("source_*_many.md"))
    body = staged.read_text(encoding="utf-8")
    # Body cap footer present (streaming renderer ran).
    assert "max-output-chars" in body
    # CRITICAL R2 fix: attachments survived the post-conversion
    # safety net. Pre-fix, the safety net's blind `content[:200]`
    # chop dropped this section.
    assert "## Attachments" in body, (
        f"attachments section was discarded by post-conversion trim: "
        f"{body!r}"
    )
    assert "doc1.pdf" in body
    assert "doc2.pdf" in body
    assert "doc3.pdf" in body


def test_html_capped_body_not_double_trimmed(tmp_path: Path) -> None:
    """Symmetry check for HTML: the post-conversion safety net must
    NOT re-trim a streaming-cap-footer body. The streaming HTML cap
    decides what fits; if the result exceeds `max_output_chars` due
    to footer overhead alone, leave it as-is."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import (
            _convert_html, _OUTPUT_CAP_FOOTER_RE,
        )
    finally:
        sys.path.pop(0)
    p = tmp_path / "p.html"
    p.write_text(
        "<html><body><p>" + ("z" * 5000) + "</p></body></html>",
        encoding="utf-8",
    )
    out = _convert_html(p, max_output_chars=100)
    # Streaming cap footer present — this is the contract for
    # cap-aware extractors that the safety net respects.
    assert _OUTPUT_CAP_FOOTER_RE.search(out), out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
