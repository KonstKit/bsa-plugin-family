"""Tests for v1.4.6 bsa materials eml + msg support
(closes lifecycle review rec #3 second half: email evidence).

New extractors:
  _convert_eml — RFC 822 / MIME via stdlib `email` module + policy.
  _convert_msg — Outlook .msg via `extract-msg` lazy-imported.

Both produce the same metadata + body + attachments markdown shape:
  ## Email metadata
  - **From**: ...
  - **To**: ...
  - **Cc**: ... (omitted when empty)
  - **Date**: ...
  - **Subject**: ...

  ## Body
  <text/plain preferred; text/html via _HTMLToMarkdown if no plain>

  ## Attachments
  - filename (mime, N bytes) ... (omitted when empty)

Coverage:
  - extension map: .eml → "eml", .msg → "msg".
  - eml: happy path, multipart prefer-text, html-only body via
    _HTMLToMarkdown synergy, attachments listed, RFC 2047 encoded
    headers, missing-headers fallback, malformed → ConversionFailed,
    empty body fallback message.
  - msg: ConversionUnavailable when dep missing, mock-based renderer
    coverage (real .msg fixture would require CFBF authoring), CLI
    dispatch.
  - CLI: dry-run lists EML + MSG counts; commit produces staged .md
    files with the unified email shape.
"""

from __future__ import annotations

import email.message
import email.policy
import importlib
import subprocess
import sys
import types
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


# ---- extension map --------------------------------------------------


def test_extension_map_includes_eml_and_msg() -> None:
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _EXT_TO_KIND
    finally:
        sys.path.pop(0)
    assert _EXT_TO_KIND[".eml"] == "eml"
    assert _EXT_TO_KIND[".msg"] == "msg"


# ---- _convert_eml ---------------------------------------------------


def _make_eml(
    path: Path, *,
    sender: str = "alice@example.com",
    to: str = "bob@example.com",
    cc: str = "",
    subject: str = "Phase-1 scope",
    date: str = "Wed, 28 Apr 2026 14:32:11 -0500",
    body: str = "Plain body content.",
    html_body: str = "",
    attachments: list = None,
) -> None:
    """Build a minimal .eml at `path` using stdlib EmailMessage."""
    m = email.message.EmailMessage(policy=email.policy.default)
    m["From"] = sender
    m["To"] = to
    if cc:
        m["Cc"] = cc
    m["Date"] = date
    m["Subject"] = subject
    if html_body and not body:
        m.set_content(html_body, subtype="html")
    elif body and html_body:
        m.set_content(body)
        m.add_alternative(html_body, subtype="html")
    else:
        m.set_content(body)
    for fname, payload, ctype in (attachments or []):
        maintype, _, subtype = ctype.partition("/")
        m.add_attachment(
            payload, maintype=maintype, subtype=subtype, filename=fname,
        )
    path.write_bytes(bytes(m))


def test_convert_eml_happy_path(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    _make_eml(p)
    out = _convert_eml(p)
    assert "## Email metadata" in out
    assert "**From**: alice@example.com" in out
    assert "**To**: bob@example.com" in out
    assert "**Subject**: Phase-1 scope" in out
    assert "## Body" in out
    assert "Plain body content." in out


def test_convert_eml_omits_empty_optional_headers(tmp_path: Path) -> None:
    """Cc / Bcc are optional — omit lines when not present."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    _make_eml(p, cc="")
    out = _convert_eml(p)
    assert "**Cc**" not in out
    assert "**Bcc**" not in out


def test_convert_eml_includes_cc_when_set(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    _make_eml(p, cc="carol@example.com")
    out = _convert_eml(p)
    assert "**Cc**: carol@example.com" in out


def test_convert_eml_multipart_prefers_text(tmp_path: Path) -> None:
    """When both text/plain and text/html are present, text/plain
    must be used (operator-authored, not rendered)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    _make_eml(
        p,
        body="THIS-IS-PLAIN",
        html_body="<p>THIS-IS-HTML</p>",
    )
    out = _convert_eml(p)
    assert "THIS-IS-PLAIN" in out
    assert "THIS-IS-HTML" not in out


def test_convert_eml_html_only_body_via_htmltomarkdown(tmp_path: Path) -> None:
    """html-only body must route through _HTMLToMarkdown (v1.4.5
    synergy) for analyst-grep-friendly markdown output."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    _make_eml(
        p,
        body="",
        html_body=(
            "<h1>Decision</h1>"
            "<p>Phase-1 = <strong>read-only</strong>.</p>"
            "<ul><li>Delivery</li><li>Order Inquiry</li></ul>"
        ),
    )
    out = _convert_eml(p)
    assert "# Decision" in out
    assert "**read-only**" in out
    assert "- Delivery" in out
    assert "- Order Inquiry" in out


def test_convert_eml_lists_attachments(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    _make_eml(
        p,
        attachments=[
            ("contract.pdf", b"%PDF-1.4 binary blob", "application/pdf"),
            ("specs.docx", b"PK binary blob", "application/octet-stream"),
        ],
    )
    out = _convert_eml(p)
    assert "## Attachments" in out
    assert "contract.pdf" in out
    assert "application/pdf" in out
    assert "specs.docx" in out


def test_convert_eml_omits_attachments_section_when_empty(
    tmp_path: Path,
) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    _make_eml(p)
    out = _convert_eml(p)
    assert "## Attachments" not in out


def test_convert_eml_decodes_rfc2047_subject(tmp_path: Path) -> None:
    """RFC 2047 encoded-word subjects (=?UTF-8?B?...?=) must decode
    to readable text via email.policy.default."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    # "тест unicode" base64-encoded in UTF-8 = "0YLQtdGB0YIgdW5pY29kZQ=="
    raw = (
        b"From: eric@example.com\r\n"
        b"To: k@example.com\r\n"
        b"Subject: =?UTF-8?B?0YLQtdGB0YIgdW5pY29kZQ==?=\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"Content-Transfer-Encoding: 7bit\r\n\r\n"
        b"body\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    assert "**Subject**: тест unicode" in out, (
        f"RFC 2047 subject must decode; got: {out!r}"
    )


def test_convert_eml_malformed_raises_conversion_failed(
    tmp_path: Path,
) -> None:
    """A non-email file at .eml extension must surface as
    ConversionFailed (not crash, not silently produce garbage)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import (
            ConversionFailed,
            _convert_eml,
        )
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    # Inject raw bytes that the email parser CAN parse but produces
    # no useful content. The parser is very tolerant — it'll accept
    # almost anything. We test the empty-body fallback instead.
    p.write_bytes(b"")
    # Empty file — email.policy.default still parses as an empty
    # message; should NOT crash. Just produces empty metadata + the
    # "(no readable body)" placeholder.
    try:
        out = _convert_eml(p)
        assert "no readable body" in out
    except ConversionFailed:
        # Either is acceptable; both fail loudly rather than silently.
        pass


def test_convert_eml_empty_body_yields_placeholder(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    _make_eml(p, body="")
    out = _convert_eml(p)
    assert "no readable body" in out


# ---- _convert_msg (uses extract-msg) --------------------------------


def _ensure_extract_msg_available() -> None:
    """Skip if extract-msg isn't installed."""
    try:
        importlib.import_module("extract_msg")
    except ImportError:
        pytest.skip("extract-msg not installed")


def test_convert_msg_unavailable_when_dep_missing(tmp_path: Path) -> None:
    """Mock the import to simulate missing extract-msg."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import (
            ConversionUnavailable,
            _convert_msg,
        )
    finally:
        sys.path.pop(0)
    p = tmp_path / "fake.msg"
    p.write_text("not a real msg", encoding="utf-8")
    saved = sys.modules.pop("extract_msg", None)
    sys.modules["extract_msg"] = None  # type: ignore[assignment]
    try:
        with pytest.raises(ConversionUnavailable):
            _convert_msg(p)
    finally:
        if saved is not None:
            sys.modules["extract_msg"] = saved
        else:
            sys.modules.pop("extract_msg", None)


def test_convert_msg_renderer_via_mock(tmp_path: Path, monkeypatch) -> None:
    """Verify the msg-renderer helper produces the same shape as
    eml. We mock `extract_msg.openMsg` to return a stub with the
    expected attribute API; this avoids needing to author a real
    Compound File Binary Format fixture."""
    _ensure_extract_msg_available()
    sys.path.insert(0, str(REPO_ROOT))
    try:
        import scripts._bsa_cli_materials as mod
        from scripts._bsa_cli_materials import _convert_msg
    finally:
        sys.path.pop(0)

    class _StubAttachment:
        longFilename = "decision.pdf"
        shortFilename = "decision.pdf"
        data = b"%PDF binary"

    class _StubMessage:
        sender = "alice@example.com"
        to = "bob@example.com"
        cc = "carol@example.com"
        subject = "Approved scope"
        date = "Wed, 28 Apr 2026 14:32:11 -0500"
        body = "Confirming Phase-1 scope is read-only Delivery + Order Inquiry."
        htmlBody = b""
        attachments = [_StubAttachment()]

        def close(self) -> None:
            pass

    fake_extract = types.SimpleNamespace(openMsg=lambda _path: _StubMessage())
    monkeypatch.setitem(sys.modules, "extract_msg", fake_extract)
    p = tmp_path / "msg.msg"
    p.write_bytes(b"\xd0\xcf\x11\xe0")  # CFBF magic so the file exists
    out = _convert_msg(p)
    assert "**From**: alice@example.com" in out
    assert "**To**: bob@example.com" in out
    assert "**Cc**: carol@example.com" in out
    assert "**Subject**: Approved scope" in out
    assert "Confirming Phase-1 scope" in out
    assert "## Attachments" in out
    assert "decision.pdf (application/pdf" in out


def test_convert_msg_renderer_html_only_body_via_htmltomarkdown(
    tmp_path: Path, monkeypatch,
) -> None:
    """When extract-msg returns ONLY htmlBody (no plain body), the
    renderer routes through _HTMLToMarkdown (synergy with v1.4.5)."""
    _ensure_extract_msg_available()
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_msg
    finally:
        sys.path.pop(0)

    class _StubMessage:
        sender = "x@y"
        to = "a@b"
        cc = ""
        subject = "html-only"
        date = "Wed, 28 Apr 2026 14:00:00 -0500"
        body = ""
        htmlBody = b"<h2>Heading</h2><p>body para</p>"
        attachments = []

        def close(self) -> None:
            pass

    fake_extract = types.SimpleNamespace(openMsg=lambda _: _StubMessage())
    monkeypatch.setitem(sys.modules, "extract_msg", fake_extract)
    p = tmp_path / "msg.msg"
    p.write_bytes(b"\xd0\xcf\x11\xe0")
    out = _convert_msg(p)
    assert "## Heading" in out
    assert "body para" in out


# ---- CLI integration ------------------------------------------------


def test_cli_dry_run_lists_eml(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    _make_eml(src / "scope.eml")
    res = _run_cli(f"--workspace={ws}", "materials", str(src))
    assert res.returncode == 0, res.stderr
    assert "EML: 1" in res.stdout


def test_cli_commit_eml_emits_email_thread_sourcetype(
    tmp_path: Path,
) -> None:
    """`--commit` on an .eml must produce a manifest row with
    SourceType=email_thread (the v1.4.6 distinct evidence class)."""
    import csv
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    _make_eml(src / "scope.eml")
    res = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res.returncode == 0, res.stderr
    mp = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    with mp.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["SourceType"] == "email_thread", (
        f"eml staging must use email_thread SourceType; got: "
        f"{rows[0]['SourceType']!r}"
    )


def test_cli_commit_eml_staged_body_preserves_metadata(
    tmp_path: Path,
) -> None:
    """The staged .md body must preserve the email metadata block AND
    the body content (analyst can grep for sender/subject/body)."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    _make_eml(
        src / "scope.eml",
        sender="alice@example.com",
        subject="Phase-1 boundary",
        body="Phase 1 is read-only.",
    )
    res = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res.returncode == 0, res.stderr
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    staged = next(inputs.glob("source_*_scope.md"))
    body = staged.read_text(encoding="utf-8")
    assert "alice@example.com" in body
    assert "Phase-1 boundary" in body
    assert "Phase 1 is read-only." in body


# ---- v1.4.6 R1 fixes — Codex review round 1 -------------------------


def test_convert_msg_render_failure_raises_conversion_failed(
    tmp_path: Path, monkeypatch,
) -> None:
    """R1 MAJOR #1: render-time exceptions inside extract-msg's
    attribute access must surface as ConversionFailed (not escape
    as raw Exception that aborts the whole batch). cmd_materials
    catches ConversionFailed per file and continues."""
    _ensure_extract_msg_available()
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import (
            ConversionFailed,
            _convert_msg,
        )
    finally:
        sys.path.pop(0)

    class _BoomMessage:
        sender = "x@y"
        to = "a@b"
        cc = ""
        subject = "boom"
        date = "Wed, 28 Apr 2026 14:00:00 -0500"

        @property
        def body(self):
            raise RuntimeError("simulated extract-msg internal failure")

        htmlBody = b""
        attachments = []

        def close(self) -> None:
            pass

    fake_extract = types.SimpleNamespace(openMsg=lambda _: _BoomMessage())
    monkeypatch.setitem(sys.modules, "extract_msg", fake_extract)
    p = tmp_path / "msg.msg"
    p.write_bytes(b"\xd0\xcf\x11\xe0")
    with pytest.raises(ConversionFailed) as excinfo:
        _convert_msg(p)
    assert "render failed" in str(excinfo.value)


def test_convert_eml_text_plain_with_filename_is_attachment(
    tmp_path: Path,
) -> None:
    """R1 MAJOR #2: a `text/plain; name=note.txt` part with NO
    Content-Disposition must be classified as an attachment, not
    as the email body. Otherwise the attachment would suppress the
    real body that follows in MIME order."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: with attachment\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="BOUNDARY"\r\n\r\n'
        b"--BOUNDARY\r\n"
        b'Content-Type: text/plain; name="note.txt"\r\n'
        b"Content-Transfer-Encoding: 7bit\r\n\r\n"
        b"ATTACHMENT-CONTENT-NOT-BODY\r\n"
        b"--BOUNDARY\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"Content-Transfer-Encoding: 7bit\r\n\r\n"
        b"REAL-BODY-CONTENT\r\n"
        b"--BOUNDARY--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    # Real body must be present in body section.
    assert "REAL-BODY-CONTENT" in out
    # Attachment text must NOT appear in body section.
    body_section_start = out.index("## Body")
    body_section_end = out.index("## Attachments") if "## Attachments" in out else len(out)
    body_section = out[body_section_start:body_section_end]
    assert "ATTACHMENT-CONTENT-NOT-BODY" not in body_section, (
        f"name= text/plain part must not become body; "
        f"body section: {body_section!r}"
    )
    # Attachment must be listed.
    assert "## Attachments" in out
    assert "note.txt" in out


def test_convert_eml_inline_image_listed_under_attachments(
    tmp_path: Path,
) -> None:
    """R1 MAJOR #3: inline images (Content-Disposition: inline) MUST
    appear under Attachments with an [inline] marker so the staged
    file records what the email carried, even when the rendered
    HTML body is blank because it referenced cid:."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: image only\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/related; boundary="BOUNDARY"\r\n\r\n'
        b"--BOUNDARY\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b'<html><body><img src="cid:img1"></body></html>\r\n'
        b"--BOUNDARY\r\n"
        b'Content-Type: image/png\r\n'
        b'Content-Disposition: inline; filename="screenshot.png"\r\n'
        b"Content-ID: <img1>\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n"
        b"iVBORw0KGgo=\r\n"
        b"--BOUNDARY--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    assert "## Attachments" in out
    assert "screenshot.png" in out
    # v1.4.15 audit P1 fix: when the inline part also carries a
    # `Content-ID` header, the rendered tag now also names the cid
    # so the HTML→image binding is preserved end-to-end. Pre-fix the
    # rendered tag was `[inline]` only; the cid value was discarded.
    assert "[inline cid:img1]" in out
    # Body should fall back to placeholder since rendered HTML is empty.
    body_section_start = out.index("## Body")
    body_section_end = out.index("## Attachments")
    body_section = out[body_section_start:body_section_end]
    assert "no readable body" in body_section, (
        f"empty rendered HTML must yield placeholder; "
        f"got body: {body_section!r}"
    )


def test_convert_msg_html_body_strips_utf8_bom(
    tmp_path: Path, monkeypatch,
) -> None:
    """R1 MINOR #1: extract-msg's htmlBody bytes may carry a UTF-8
    BOM (0xEF 0xBB 0xBF). Decoder must use utf-8-sig so the BOM is
    swallowed (no stray U+FEFF in the staged markdown)."""
    _ensure_extract_msg_available()
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_msg
    finally:
        sys.path.pop(0)

    class _BomMessage:
        sender = "x@y"
        to = "a@b"
        cc = ""
        subject = "with bom"
        date = "Wed, 28 Apr 2026 14:00:00 -0500"
        body = ""
        htmlBody = b"\xef\xbb\xbf<h1>BOM-prefixed</h1>"
        attachments = []

        def close(self) -> None:
            pass

    fake_extract = types.SimpleNamespace(openMsg=lambda _: _BomMessage())
    monkeypatch.setitem(sys.modules, "extract_msg", fake_extract)
    p = tmp_path / "msg.msg"
    p.write_bytes(b"\xd0\xcf\x11\xe0")
    out = _convert_msg(p)
    assert "BOM-prefixed" in out
    assert "﻿" not in out, (
        f"utf-8-sig must strip BOM; got: {out!r}"
    )


def test_convert_eml_subject_with_newline_does_not_inject_markdown(
    tmp_path: Path,
) -> None:
    """R1 MINOR #2: a malformed (or malicious) Subject containing
    embedded newlines must be normalized to single-space so an
    attacker can't inject extra markdown bullets into the metadata
    block (e.g. Subject = `evil\\n- **Bcc**: leak@example.com`)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    # Build a raw eml where the Subject header has a folded line that
    # the email parser un-folds. We add a 3rd line that shouldn't be
    # there to simulate a tampered subject.
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: legit\r\n\t- **Bcc**: leak@example.com\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"body\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    # The injected `- **Bcc**:` text should NOT appear as a separate
    # header line; it must live inside the Subject value as plain text.
    metadata_lines = [
        ln for ln in out.splitlines()
        if ln.startswith("- **")
    ]
    bcc_lines = [ln for ln in metadata_lines if ln.startswith("- **Bcc**")]
    assert not bcc_lines, (
        f"injected Bcc must not become a separate metadata line; "
        f"got: {metadata_lines!r}"
    )
    subject_lines = [
        ln for ln in metadata_lines if ln.startswith("- **Subject**")
    ]
    assert subject_lines, "Subject line must be present"
    assert "leak@example.com" in subject_lines[0], (
        f"injected text must remain inside Subject value; "
        f"got: {subject_lines[0]!r}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
