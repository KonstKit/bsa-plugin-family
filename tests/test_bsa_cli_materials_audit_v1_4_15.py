"""Tests for v1.4.15 hotfix — fifth-pass external Codex audit findings
on the `bsa materials` extractor surface.

External Codex R4 review (post-v1.4.14) flagged 3 evidence-loss / cap
findings that the v1.4.14 self-review missed. Each closed by an isolated
patch on `scripts/_bsa_cli_materials.py`.

  P1 #1: forwarded `message/rfc822` containers with NEITHER
         `Content-Disposition: attachment` NOR a filename were
         silently dropped from the pre-scan, so their inner
         text/plain leaked into the OUTER email's body / `other_parts`
         bucket as an `(unnamed text/plain)` row — losing both the
         `message/rfc822` content-type marker and the forwarded-message
         boundary required for evidence binding. Closed by removing the
         `disposition=attachment OR filename present` gate on the
         pre-scan: every multipart `message/rfc822` is now captured as
         a forwarded attachment with the synthetic filename
         `(forwarded message).eml` when none is provided.

  P1 #2: covered by tests/test_bsa_cli_materials_audit_v1_4_15.py
         (CID-image relationship lost). Filed separately; this file
         covers ONLY the rfc822 boundary-loss fix above.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace layout for `bsa materials --commit`
    end-to-end tests. Mirrors the helper in
    `tests/test_bsa_cli_materials_audit_v1_4_14.py`."""
    ws = tmp_path / "ws"
    (ws / "analysis" / "proposals" / "stage1" / "inputs").mkdir(parents=True)
    return ws


def _run_cli(*args: str):
    """Invoke `scripts/bsa_cli.py` as a subprocess with the given
    arguments, returning the `subprocess.CompletedProcess`. Mirrors
    the helper in `tests/test_bsa_cli_materials_audit_v1_4_14.py`."""
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "bsa_cli.py"), *args],
        capture_output=True, text=True, check=False,
    )


def test_eml_rfc822_without_disposition_or_filename_is_captured(
    tmp_path: Path,
) -> None:
    """A `multipart/mixed` host email contains a `message/rfc822`
    forwarded part with NO `Content-Disposition` header and NO
    `name=`/`filename=` parameter. Pre-fix, the pre-scan gate
    (`disposition=attachment OR filename present`) skipped the
    container, the main walk processed its multipart child, and the
    inner text/plain leaked as an `(unnamed text/plain)` other_parts
    row — losing the rfc822 boundary.

    Post-fix, the rfc822 container appears in Attachments with the
    synthetic filename `(forwarded message).eml` and content-type
    `message/rfc822`; the inner body does NOT leak into the outer
    email's body section.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "host.eml"
    # Structure:
    #   host (multipart/mixed)
    #     - text/plain          (host body)
    #     - message/rfc822      <-- NO Content-Disposition, NO filename
    #         inner (multipart/alternative)
    #           - text/plain
    #           - text/html
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: please review\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="OUTER"\r\n\r\n'
        b"--OUTER\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"See the forwarded thread below.\r\n"
        b"--OUTER\r\n"
        b"Content-Type: message/rfc822\r\n\r\n"
        b"From: carol@example.com\r\n"
        b"To: alice@example.com\r\n"
        b"Subject: original thread\r\n"
        b"Date: Tue, 27 Apr 2026 09:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/alternative; boundary="INNER"\r\n\r\n'
        b"--INNER\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Inner forwarded plain body.\r\n"
        b"--INNER\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<html><body><p>Inner forwarded html body.</p></body></html>\r\n"
        b"--INNER--\r\n"
        b"--OUTER--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    # Outer host body preserved.
    assert "See the forwarded thread below." in out
    # Attachments section exists.
    assert "## Attachments" in out, (
        "rfc822 container without disposition/filename was dropped — "
        "Attachments section missing entirely"
    )
    # CRITICAL: rfc822 content-type marker present.
    assert "message/rfc822" in out, (
        "lost message/rfc822 content-type marker — evidence binding "
        "to forwarded-message boundary destroyed"
    )
    # Synthetic filename used (no name/filename in the source).
    assert "(forwarded message).eml" in out, (
        "synthetic filename missing — Attachments row lacks identifier"
    )
    # CRITICAL: inner body did NOT leak into outer body.
    body_section_start = out.index("## Body")
    body_section_end = (
        out.index("## Attachments") if "## Attachments" in out else len(out)
    )
    body_section = out[body_section_start:body_section_end]
    assert "Inner forwarded plain body." not in body_section, (
        f"inner rfc822 text/plain leaked into outer body: {body_section!r}"
    )
    assert "Inner forwarded html body." not in body_section, (
        f"inner rfc822 html body leaked into outer body: {body_section!r}"
    )
    # CRITICAL: no `(unnamed text/plain)` other_parts row pointing at
    # the inner part.
    assert "(unnamed text/plain)" not in out, (
        "inner rfc822 text/plain leaked as (unnamed text/plain) row — "
        "boundary lost"
    )


def test_eml_rfc822_with_filename_only_still_captured(
    tmp_path: Path,
) -> None:
    """Regression sanity: rfc822 with `name=` parameter (the
    pre-fix-supported path) keeps working. Belt-and-suspenders for the
    gate-removal change."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "host.eml"
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: with name\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="O"\r\n\r\n'
        b"--O\r\nContent-Type: text/plain\r\n\r\nhost body\r\n"
        b"--O\r\n"
        b'Content-Type: message/rfc822; name="legacy.eml"\r\n\r\n'
        b"From: x@y\r\nTo: a@b\r\nSubject: legacy\r\n"
        b"MIME-Version: 1.0\r\nContent-Type: text/plain\r\n\r\nlegacy body\r\n"
        b"--O--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    assert "legacy.eml" in out
    assert "message/rfc822" in out
    assert "legacy body" not in out, (
        "rfc822 child leaked into outer body — descendant skip broken"
    )


def test_eml_rfc822_with_attachment_disposition_still_captured(
    tmp_path: Path,
) -> None:
    """Regression sanity: rfc822 with explicit
    `Content-Disposition: attachment` keeps working (pre-fix path)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "host.eml"
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: explicit attach\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="O"\r\n\r\n'
        b"--O\r\nContent-Type: text/plain\r\n\r\nhost body\r\n"
        b"--O\r\n"
        b'Content-Type: message/rfc822\r\n'
        b'Content-Disposition: attachment; filename="explicit.eml"\r\n\r\n'
        b"From: x@y\r\nTo: a@b\r\nSubject: explicit\r\n"
        b"MIME-Version: 1.0\r\nContent-Type: text/plain\r\n\r\nexplicit body\r\n"
        b"--O--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    assert "explicit.eml" in out
    assert "message/rfc822" in out
    assert "explicit body" not in out


# ---- P1 #2: CID image without inline disposition -------------------


def test_eml_cid_image_without_inline_disposition_routes_to_inline_media(
    tmp_path: Path,
) -> None:
    """An HTML-only CID-referenced image part with `Content-ID:` but
    NO `Content-Disposition: inline` MUST be classified as inline
    media (not as a generic `other_parts` row). The rendered
    Attachments line MUST carry the cid value so the HTML→image
    relationship survives staging.

    Pre-fix:
      - The part fell into `other_parts` with tag=`part`.
      - `(unnamed image/png)` row, no cid.
      - HTML body → empty render (cid: reference to a part the
        renderer doesn't resolve) → placeholder.
      - Net effect: evidence loss — analyst can't bind the rendered
        HTML reference to the staged image leaf.

    Post-fix:
      - Part is in `inline_media` with cid="img1".
      - Rendered tag is `[inline cid:img1]`.
      - Filename fallback `(inline image/png)` when no name=.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: cid only\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/related; boundary="BOUNDARY"\r\n\r\n'
        b"--BOUNDARY\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b'<html><body><p>See: <img src="cid:img1"></p></body></html>\r\n'
        b"--BOUNDARY\r\n"
        b"Content-Type: image/png\r\n"
        b"Content-ID: <img1>\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n"
        b"iVBORw0KGgo=\r\n"
        b"--BOUNDARY--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    # CRITICAL: the cid must appear in the rendered tag so the HTML
    # body's `cid:img1` reference can be bound to the staged image
    # leaf during evidence audit.
    assert "[inline cid:img1]" in out, (
        f"cid lost — got output: {out!r}"
    )
    # The image must NOT be a generic `(unnamed ...)` other_parts row.
    assert "(unnamed image/png)" not in out, (
        "CID image was classified as other_parts/(unnamed image/png) — "
        "inline-media routing broken"
    )
    # The synthetic inline-media filename appears since name= is absent.
    assert "(inline image/png)" in out


def test_eml_cid_image_with_filename_no_disposition_keeps_filename(
    tmp_path: Path,
) -> None:
    """Same CID flow but the part also carries a `name=` parameter.
    Filename wins over the synthetic `(inline ...)` fallback; the cid
    still appears in the tag suffix."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    raw = (
        b"From: a@x\r\nTo: b@y\r\nSubject: cid+name\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/related; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/html\r\n\r\n"
        b'<html><body><img src="cid:logo"></body></html>\r\n'
        b"--B\r\n"
        b'Content-Type: image/png; name="logo.png"\r\n'
        b"Content-ID: <logo@host.example>\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n"
        b"iVBORw0KGgo=\r\n"
        b"--B--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    assert "logo.png" in out
    # Angle brackets and surrounding whitespace are stripped per RFC 2045.
    assert "[inline cid:logo@host.example]" in out, (
        f"cid normalization wrong — got: {out!r}"
    )


def test_eml_cid_with_injection_payload_is_sanitized(
    tmp_path: Path,
) -> None:
    """A malicious sender crafts a `Content-ID:` value containing
    newline + `]` characters in an attempt to close the
    `[inline cid:<value>]` tag early and inject spoofed
    `- attacker.bin (...)` rows under the staged Attachments
    section. `_sanitize_cid_for_tag` MUST collapse newlines
    (via `_normalize_email_header_value`) AND strip `[` / `]`
    before the cid is embedded in the markdown tag.

    Codex review of fix #2 round 1 flagged this as REQUEST CHANGES.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    # Content-ID payload tries to break out of the inline tag.
    # NOTE: stdlib email.policy.default may decode RFC 2047 encoded
    # Content-ID values; the literal-bytes path here exercises the
    # raw-input scenario the sanitizer must handle either way.
    raw = (
        b"From: a@x\r\nTo: b@y\r\nSubject: cid injection\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/related; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/html\r\n\r\n"
        b'<html><body><img src="cid:legit"></body></html>\r\n'
        b"--B\r\n"
        b"Content-Type: image/png\r\n"
        b"Content-ID: <legit]\r\n - injected.bin (malware,1) [trail>\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n"
        b"iVBORw0KGgo=\r\n"
        b"--B--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    # CRITICAL invariants:
    # (a) The cid value is contained ENTIRELY inside the inline tag —
    #     no spillover into a separate `- ` row beneath it.
    # (b) No `]` characters survive in the rendered cid (they would
    #     close the markdown tag early).
    # (c) Newlines from the malicious header are collapsed to spaces.
    # (d) The cid IS still rendered (sanitization is not redaction).
    assert "cid:" in out, "cid lost during sanitization"
    inline_lines = [
        line for line in out.splitlines()
        if "[inline cid:" in line
    ]
    assert len(inline_lines) == 1, (
        f"expected exactly one inline-cid row, got {len(inline_lines)}: "
        f"{inline_lines!r}"
    )
    inline_line = inline_lines[0]
    assert inline_line.rstrip().endswith("]"), (
        f"inline-cid row tag did not close cleanly: {inline_line!r}"
    )
    # The cid substring (between `cid:` and the closing `]`) must NOT
    # contain `]`, `[`, or any newline — those are the injection
    # vectors `_sanitize_cid_for_tag` is designed to neutralize.
    cid_idx = inline_line.index("cid:") + len("cid:")
    closing_idx = inline_line.rindex("]")
    cid_in_tag = inline_line[cid_idx:closing_idx]
    assert "]" not in cid_in_tag, (
        f"`]` survived sanitization — could close tag early: "
        f"{cid_in_tag!r}"
    )
    assert "[" not in cid_in_tag, (
        f"`[` survived sanitization — could open spoofed bracket: "
        f"{cid_in_tag!r}"
    )
    assert "\n" not in cid_in_tag and "\r" not in cid_in_tag, (
        f"newline survived sanitization — could spoof a new row: "
        f"{cid_in_tag!r}"
    )
    # (a) — No NEW row starting with `- injected.bin` exists. The
    # whole malicious payload should be inside the single inline_line.
    other_rows = [
        line for line in out.splitlines()
        if line.lstrip().startswith("- injected.bin")
    ]
    assert not other_rows, (
        f"CID injection produced spoofed row(s): {other_rows!r}"
    )


def test_sanitize_cid_for_tag_collapses_unicode_line_separators() -> None:
    """Codex round-2 review of fix #2 flagged that Python's
    `str.splitlines()` honors `\\x85` (NEL), `\\u2028` (LINE
    SEPARATOR), and `\\u2029` (PARAGRAPH SEPARATOR) in addition to
    `\\r\\n`. A naive `re.sub(r"[\\r\\n\\t ]+", ...)` collapses ONLY
    `\\r\\n\\t`, leaving the Unicode separators free to spoof a new
    markdown row when surfaced anywhere downstream that uses
    splitlines (renderers, log viewers, etc.).

    `_sanitize_cid_for_tag` MUST collapse ALL splitlines-recognized
    breaks before bracket-stripping.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _sanitize_cid_for_tag
    finally:
        sys.path.pop(0)
    # Each separator should turn into a single ASCII space; brackets
    # must be stripped; the value must remain non-empty.
    for sep_name, sep in (
        ("CR", "\r"),
        ("LF", "\n"),
        ("CRLF", "\r\n"),
        ("NEL", "\x85"),
        ("LINE_SEPARATOR", " "),
        ("PARAGRAPH_SEPARATOR", " "),
        ("VT", "\v"),
        ("FF", "\f"),
    ):
        cid = f"head{sep}- injected.bin (malware,1)"
        cleaned = _sanitize_cid_for_tag(cid)
        assert "\n" not in cleaned, f"{sep_name}: \\n leaked"
        assert "\r" not in cleaned, f"{sep_name}: \\r leaked"
        assert "\x85" not in cleaned, f"{sep_name}: NEL leaked"
        assert " " not in cleaned, f"{sep_name}: LS leaked"
        assert " " not in cleaned, f"{sep_name}: PS leaked"
        assert "\v" not in cleaned, f"{sep_name}: VT leaked"
        assert "\f" not in cleaned, f"{sep_name}: FF leaked"
        assert "[" not in cleaned and "]" not in cleaned, (
            f"{sep_name}: bracket leaked: {cleaned!r}"
        )
        # Sanity: the head AND payload still appear (just on one line).
        assert "head" in cleaned
        assert "injected.bin" in cleaned


def test_sanitize_cid_for_tag_strips_html_brackets_and_controls() -> None:
    """Codex round-3 review of fix #2 flagged that internal `<` / `>`
    survive sanitization, allowing raw-HTML injection like
    `<li>- injected.bin</li>` in Markdown→HTML pipelines that pass
    through HTML. Also flagged ESC + other C0/C1 controls reaching
    ANSI-aware viewers (`cat`, `tail`) when an analyst inspects the
    staged file. Sanitizer must strip both classes.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _sanitize_cid_for_tag
    finally:
        sys.path.pop(0)
    # HTML-bracket injection.
    cid = "foo</li><li>- injected.bin"
    cleaned = _sanitize_cid_for_tag(cid)
    assert "<" not in cleaned and ">" not in cleaned, (
        f"HTML brackets survived: {cleaned!r}"
    )
    assert "/li" in cleaned, "core payload should still appear"
    # ESC (C0).
    cid_esc = "foo\x1b[31m injected\x1b[0m"
    cleaned = _sanitize_cid_for_tag(cid_esc)
    assert "\x1b" not in cleaned, f"ESC survived: {cleaned!r}"
    # NEL (C1) defensive strip even though splitlines() should catch.
    cleaned = _sanitize_cid_for_tag("foo\x85bar")
    assert "\x85" not in cleaned
    # DEL (0x7F).
    cleaned = _sanitize_cid_for_tag("foo\x7fbar")
    assert "\x7f" not in cleaned
    # NUL — must not produce empty cid; just strip.
    cleaned = _sanitize_cid_for_tag("foo\x00bar")
    assert cleaned == "foobar"


def test_sanitize_cid_for_tag_caps_long_value() -> None:
    """Defense vs. multi-MB synthetic cid: 200-char hard cap."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _sanitize_cid_for_tag
    finally:
        sys.path.pop(0)
    huge = "x" * 50_000
    cleaned = _sanitize_cid_for_tag(huge)
    assert len(cleaned) <= 200


def test_eml_text_part_with_cid_does_not_become_inline_media(
    tmp_path: Path,
) -> None:
    """Boundary check: a text/plain part with Content-ID is still a
    text part (body candidate), NOT routed to inline_media. Prevents
    the new CID-routing rule from cannibalizing legitimate body
    parts that happen to carry an opportunistic Content-ID header.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "msg.eml"
    raw = (
        b"From: a@x\r\nTo: b@y\r\nSubject: text+cid\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/plain; charset=utf-8\r\n"
        b"Content-ID: <body1>\r\n\r\n"
        b"Plain text body with opportunistic CID.\r\n"
        b"--B--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    # Body MUST contain the text — proves it took the body path,
    # not the inline_media path.
    body_section_start = out.index("## Body")
    body_section_end = (
        out.index("## Attachments") if "## Attachments" in out else len(out)
    )
    body_section = out[body_section_start:body_section_end]
    assert "Plain text body with opportunistic CID." in body_section
    # And NO inline-media row was emitted.
    assert "[inline cid:body1]" not in out


# ---- P1 round 4 of fix #3: HTML body evidence-loss + false marker ---


def test_eml_html_body_with_long_style_prefix_renders_visible_body(
    tmp_path: Path,
) -> None:
    """Codex round 4 of fix #3 flagged that the prior round's "cap
    html_body right after get_content()" sliced raw HTML at byte N
    BEFORE `_HTMLToMarkdown` could skip `<script>`/`<style>` content.
    Repro: an HTML email whose first 200 chars are inside `<style>`
    and visible `<body><p>VISIBLE</p>` follows after the cap. Pre-fix
    interim, the cap chopped the html_body at 200, the renderer fed
    only the truncated `<style>` fragment (which it skips entirely)
    and emitted nothing → `(no readable body)` placeholder + a
    cap-footer marker (false evidence loss).

    Post-fix, truncation is tracked at the parser/rendered-output
    level only — the visible body renders correctly.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "style_prefix.eml"
    # First ~200 chars are inside <style> (skipped by _HTMLToMarkdown).
    style_filler = "a" * 200
    html = (
        f"<html><head><style>body {{ {style_filler} }}</style></head>"
        f"<body><p>VISIBLE-PARAGRAPH</p></body></html>"
    )
    raw = (
        b"From: a@x\r\nTo: b@x\r\nSubject: style-prefix\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        + html.encode("utf-8") + b"\r\n"
    )
    p.write_bytes(raw)
    # Cap small enough that pre-fix would have truncated mid-<style>.
    out = _convert_eml(p, max_output_chars=250)
    # CRITICAL: visible body must render even when first ~200 chars
    # of raw HTML are inside <style>.
    assert "VISIBLE-PARAGRAPH" in out, (
        f"visible HTML body lost — got: {out!r}"
    )
    # And we must NOT see the no-readable-body placeholder.
    body_section_start = out.index("## Body")
    body_section_end = (
        out.index("## Attachments") if "## Attachments" in out
        else len(out)
    )
    body_section = out[body_section_start:body_section_end]
    assert "no readable body" not in body_section


def test_eml_multipart_alternative_short_plain_no_false_cap_marker(
    tmp_path: Path,
) -> None:
    """Codex round 4 of fix #3 flagged that an oversized HTML
    alternative in `multipart/alternative` could pre-cap and set
    `body_truncated=True` even though the short text/plain
    alternative was the body actually rendered → false cap marker.

    Post-fix, body_truncated is set only for the body actually
    rendered. A short plain body (selected) + a 1KB html alternative
    (not selected, would have tripped the input cap pre-fix) must
    NOT emit the cap-marker footer.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "alternative.eml"
    huge_html = "<html><body>" + ("X" * 5000) + "</body></html>"
    raw = (
        b"From: a@x\r\nTo: b@x\r\nSubject: multipart alt\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/alternative; boundary="A"\r\n\r\n'
        b"--A\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Short plain body.\r\n"
        b"--A\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        + huge_html.encode("utf-8") + b"\r\n"
        b"--A--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p, max_output_chars=200)
    # CRITICAL: short plain body renders.
    assert "Short plain body." in out
    # CRITICAL: the cap-marker footer MUST NOT appear, because the
    # rendered (plain) body did not actually exceed the cap. The
    # discarded oversized html alternative is irrelevant.
    assert "<!--bsa:cap:applied:v1-->" not in out, (
        f"false cap-marker for unselected oversized html alternative: "
        f"{out!r}"
    )


def test_eml_html_only_truncated_emits_marker_exactly_once(
    tmp_path: Path,
) -> None:
    """When html_body is the SELECTED body and it triggers the
    streaming `_HTMLToMarkdown` cap, exactly ONE `_OUTPUT_CAP_MARKER`
    must appear (the one baked in by `_HTMLToMarkdown.render()`).
    The outer footer-emission MUST NOT add a duplicate marker.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "html_only.eml"
    # Visible HTML body that exceeds the cap when rendered.
    html = (
        "<html><body>"
        + "<p>BIGBODY</p>" * 500
        + "</body></html>"
    )
    raw = (
        b"From: a@x\r\nTo: b@x\r\nSubject: html only\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        + html.encode("utf-8") + b"\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p, max_output_chars=200)
    # Marker is present (truncation occurred).
    assert "<!--bsa:cap:applied:v1-->" in out
    # No duplicate marker.
    marker_count = out.count("<!--bsa:cap:applied:v1-->")
    assert marker_count == 1, (
        f"expected exactly 1 cap-marker, got {marker_count}: {out!r}"
    )


def test_msg_html_body_with_style_prefix_renders_visible_body() -> None:
    """msg-path parity for the eml `<style>` regression."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _render_email_markdown_from_msg
    finally:
        sys.path.pop(0)
    style_filler = "a" * 200
    big_html = (
        f"<html><head><style>body {{ {style_filler} }}</style></head>"
        f"<body><p>VISIBLE-MSG</p></body></html>"
    )

    class _StylePrefixMessage:
        sender = "x@y"
        to = "a@b"
        cc = ""
        subject = "style prefix"
        date = "Wed, 28 Apr 2026 14:00:00 -0500"
        body = ""
        htmlBody = big_html.encode("utf-8")
        attachments = []

        def close(self) -> None:
            pass

    out = _render_email_markdown_from_msg(
        _StylePrefixMessage(), "synthetic.msg", max_output_chars=250,
    )
    assert "VISIBLE-MSG" in out, (
        f"visible msg html body lost — got: {out!r}"
    )


def test_msg_alternative_no_false_cap_marker() -> None:
    """msg-path parity: when `body` (plain) is set and html_body is
    oversized, body_truncated must NOT be set by the html branch
    (false cap marker)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _render_email_markdown_from_msg
    finally:
        sys.path.pop(0)

    class _BothBodiesMessage:
        sender = "x@y"
        to = "a@b"
        cc = ""
        subject = "both bodies"
        date = "Wed, 28 Apr 2026 14:00:00 -0500"
        body = "Short plain body."
        htmlBody = ("<html><body>" + ("X" * 5000) + "</body></html>").encode(
            "utf-8"
        )
        attachments = []

        def close(self) -> None:
            pass

    out = _render_email_markdown_from_msg(
        _BothBodiesMessage(), "synthetic.msg", max_output_chars=200,
    )
    assert "Short plain body." in out
    assert "<!--bsa:cap:applied:v1-->" not in out, (
        f"false cap-marker for unselected oversized htmlBody: {out!r}"
    )


# ---- P1 round 5 of fix #3: <title> bypass of streaming cap ---------


def test_eml_html_oversized_title_keeps_attachments(
    tmp_path: Path,
) -> None:
    """Codex round 5 of fix #3 flagged: `_HTMLToMarkdown` accumulates
    `<title>` outside `_buf_size`, then injects it into `body` after
    streaming cap accounting. A 5KB `<title>` returned oversized
    output WITHOUT `_OUTPUT_CAP_MARKER`; cmd_materials then blind-
    chopped `content[:cap]` and dropped Attachments.

    Repro: an `.eml` with a 5_000-char `<title>` plus a `doc.pdf`
    attachment + cap=200. Pre-fix:
      - `_HTMLToMarkdown.render()` returned ~5KB title-as-H1 + body,
        no marker (because `_truncated` was never set during title
        accumulation).
      - cmd_materials safety net saw `len(content) > cap` AND
        `_OUTPUT_CAP_MARKER not in content` → fell to blind chop:
        `content[:cap]` → discarded `## Attachments` and `doc.pdf`.

    Post-fix, title bytes count against `_buf_size` AND there is a
    final cap-check in `render()` so any oversized output carries
    the marker — letting the safety net preserve attachments.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "huge_title.eml"
    huge_title = "T" * 5000
    html = (
        f"<html><head><title>{huge_title}</title></head>"
        f"<body><p>tiny body</p></body></html>"
    )
    raw = (
        b"From: a@x\r\nTo: b@x\r\n"
        b"Subject: huge title w/ attachment\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        + html.encode("utf-8") + b"\r\n"
        b"--B\r\n"
        b'Content-Type: application/pdf; name="doc.pdf"\r\n'
        b'Content-Disposition: attachment; filename="doc.pdf"\r\n'
        b"Content-Transfer-Encoding: base64\r\n\r\nAA==\r\n"
        b"--B--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p, max_output_chars=200)
    # CRITICAL: cap marker present (set during title accumulation
    # and/or the final-render cap-check).
    assert "<!--bsa:cap:applied:v1-->" in out, (
        f"cap marker missing — title bypassed cap accounting: "
        f"{out!r}"
    )
    # CRITICAL: Attachments section MUST survive — this is what the
    # external review specifically reproduced as broken.
    assert "## Attachments" in out, (
        f"Attachments dropped by safety net blind-chop — "
        f"title bypassed cap marker: {out!r}"
    )
    assert "doc.pdf" in out


def test_html_to_markdown_oversized_title_only_renders_with_marker(
    tmp_path: Path,
) -> None:
    """Direct `_HTMLToMarkdown` test: 5KB `<title>` + cap=200 →
    `render()` output MUST contain `_OUTPUT_CAP_MARKER` so any
    downstream consumer can distinguish a truncated cap-applied
    rendering from arbitrary text."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    huge_title = "T" * 5000
    html = (
        f"<html><head><title>{huge_title}</title></head>"
        f"<body></body></html>"
    )
    h = _HTMLToMarkdown(max_output_chars=200)
    h.feed(html)
    h.close()
    out = h.render()
    assert "<!--bsa:cap:applied:v1-->" in out, (
        f"marker missing for oversized title-only HTML: {out!r}"
    )


def test_html_to_markdown_oversized_title_with_body_h1_preserves_body(
    tmp_path: Path,
) -> None:
    """Codex round 6 of fix #3 flagged that the round-5 attempt
    consumed `_buf_size` budget for title bytes, breaking the
    long-standing invariant "title is suppressed when body has
    `<h1>`" (the h1 + body would still get dropped because
    `_truncated` was set by title accumulation, and `_emit` then
    short-circuited body emission).

    Repro: 5KB `<title>` + `<body><h1>REAL H1</h1><p>VISIBLE BODY</p>`
    + cap=200. Title is NOT injected (h1 present); body must
    render fully (well under cap) WITHOUT a false cap marker.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    huge_title = "T" * 5000
    html = (
        f"<html><head><title>{huge_title}</title></head>"
        f"<body><h1>REAL H1</h1><p>VISIBLE BODY</p></body></html>"
    )
    h = _HTMLToMarkdown(max_output_chars=200)
    h.feed(html)
    h.close()
    out = h.render()
    # CRITICAL: body content survives.
    assert "REAL H1" in out, (
        f"h1 dropped — title accumulator stole budget: {out!r}"
    )
    assert "VISIBLE BODY" in out, (
        f"body content dropped — title accumulator stole budget: "
        f"{out!r}"
    )
    # Title MUST NOT be injected (existing v1.4.5 `_has_h1` gate).
    # Use a substring that would only appear from the title.
    title_substring = "T" * 50
    assert title_substring not in out, (
        f"title injected despite h1 present — _has_h1 gate broken: "
        f"{out!r}"
    )
    # Body fits in 200 chars → no marker (no false truncation).
    assert "<!--bsa:cap:applied:v1-->" not in out, (
        f"false marker: body fit within cap but marker emitted: "
        f"{out!r}"
    )


def test_html_to_markdown_short_title_no_marker(
    tmp_path: Path,
) -> None:
    """Negative case: a small title that fits in the cap MUST NOT
    cause the marker to appear (no false positive)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    html = "<html><head><title>ok</title></head><body><p>x</p></body></html>"
    h = _HTMLToMarkdown(max_output_chars=200)
    h.feed(html)
    h.close()
    out = h.render()
    assert "<!--bsa:cap:applied:v1-->" not in out, (
        f"false marker on within-cap output: {out!r}"
    )
    # Title rendered as H1.
    assert "# ok" in out


# ---- P1 round 7 of fix #3: link-text + pptx title bypasses ----------


def test_html_to_markdown_oversized_link_text_bounded(
    tmp_path: Path,
) -> None:
    """Codex round 7 of fix #3 flagged that `_link_text_buf`
    accumulates outside `_buf_size`, then `_flush_link()` joins the
    full value before `_emit()` can cap it. Same structural bypass
    as the now-fixed `<title>` accumulator. A 5KB `<a>...</a>` body
    would expand the buffer past `_max_output_chars` before the
    flush; the post-conversion safety net would then have to choose
    between blind-chop and preserving the marker.

    Post-fix (rounds 7+8), `_link_text_buf` is bounded against
    `_max_output_chars` during `_on_data` accumulation, AND
    `_flush_link` reserves the markdown anchor overhead `[](href)`
    so the formatted `[text](href)` fits whole within the remaining
    buffer room. Codex round 8 specifically required asserting BOTH
    no long run AND `](href)` shape survival — without the overhead
    reservation, `_emit` would chop the formatted string mid-way
    and drop the closing `](href)`.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    huge = "L" * 5000
    html = f'<html><body><a href="http://e/x">{huge}</a></body></html>'
    h = _HTMLToMarkdown(max_output_chars=200)
    h.feed(html)
    h.close()
    out = h.render()
    # No 1000-char run of L's (accumulation was bounded).
    assert "L" * 1000 not in out, (
        f"link-text buffer accumulated unbounded: {out!r}"
    )
    # CRITICAL (codex round 8): markdown anchor shape survives.
    # The flushed `[text](href)` must keep the closing `](href)`
    # intact. Pre-fix, `_emit` would chop after the cap and drop
    # the closing bracket + href.
    assert "](http://e/x)" in out, (
        f"markdown anchor shape broken — `_flush_link` did not "
        f"reserve overhead: {out!r}"
    )
    # Visible link text is shortened so the formatted link fits.
    # The substring `[L...L](http://e/x)` should appear and end
    # with the closing paren.
    bracket_idx = out.index("](http://e/x)")
    open_idx = out.rindex("[", 0, bracket_idx)
    text_inside = out[open_idx + 1:bracket_idx]
    assert text_inside.startswith("L"), (
        f"link text content lost: {out!r}"
    )


def test_html_to_markdown_link_trim_emits_cap_marker(
    tmp_path: Path,
) -> None:
    """Codex round 9 of fix #3 flagged: when `_flush_link` trims
    visible link text to reserve `](href)` overhead, the trim
    silently dropped characters without setting `_truncated`. Final
    output had the markdown anchor shape but NO `_OUTPUT_CAP_MARKER`
    — defeating both restage-changed cap-bump detection and
    operator-visible truncation signaling.

    Codex repro: `<p>` adds leading whitespace to `_buf_size` (later
    stripped by `render().strip()`), so the `_flush_link` trim
    fits the raw buffer at the cap, but the final-render cap-check
    on the post-strip result doesn't trip.

    Post-fix, any visible-link-text trim sets `_truncated=True`.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    huge = "L" * 5000
    html = f'<p><a href="http://e/x">{huge}</a></p>'
    h = _HTMLToMarkdown(max_output_chars=50)
    h.feed(html)
    h.close()
    out = h.render()
    # Anchor shape preserved (round-8 invariant).
    assert "](http://e/x)" in out
    # CRITICAL (round 9): cap marker MUST be present whenever the
    # link text was trimmed. Without it, the safety net + restage
    # heuristics can't detect the silent truncation.
    assert "<!--bsa:cap:applied:v1-->" in out, (
        f"link-text trim silently dropped chars (no marker): {out!r}"
    )


def test_pptx_oversized_title_placeholder_bounded(
    tmp_path: Path,
) -> None:
    """Codex round 7 of fix #3 flagged that the slide-title
    extraction was `(ti.text_frame.text or "").strip().splitlines()`
    — `text_frame.text` materializes the full title placeholder
    text frame. An adversarial deck with a 200MB title placeholder
    would allocate that string before our slide budget kicks in.

    Post-fix, the first-paragraph runs are streamed with a
    `_PPTX_TITLE_RUN_CAP` (200-char) bound. The first line of the
    bounded result still becomes the H2 title; later text is
    discarded. Output must still render correctly with no error.
    """
    pytest.importorskip("pptx")
    from pptx import Presentation
    from pptx.util import Inches

    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_pptx
    finally:
        sys.path.pop(0)
    p = tmp_path / "huge_title.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])  # title slide
    # Find the title placeholder and stuff it with a huge value.
    title_shape = slide.shapes.title
    title_shape.text_frame.text = "X" * 50_000
    # Add a body shape with normal content.
    body_shape = slide.shapes.add_textbox(
        Inches(1), Inches(2), Inches(8), Inches(2),
    )
    body_shape.text_frame.text = "normal slide body text"
    prs.save(p)

    out = _convert_pptx(p, max_output_chars=5_000)
    # Body content survives.
    assert "normal slide body text" in out
    # Title appears, but only as a bounded H2.
    h2_lines = [
        line for line in out.splitlines()
        if line.startswith("## Slide 1:")
    ]
    assert len(h2_lines) == 1, (
        f"expected exactly one slide-1 H2: {h2_lines!r}"
    )
    h2_line = h2_lines[0]
    # Bounded by `_PPTX_TITLE_RUN_CAP` (200) plus header overhead.
    # The visible title text in the H2 is the first line of the
    # bounded run-pieces — must NOT contain a 1000-char run of X's.
    assert "X" * 1000 not in h2_line, (
        f"title placeholder accumulated unbounded into H2: {h2_line!r}"
    )


# ---- P1+P3 round 10 of fix #3: title-starves-body + exact-cap marker


def test_eml_html_oversized_title_keeps_visible_body_priority(
    tmp_path: Path,
) -> None:
    """Codex round 10 of fix #3 flagged: HTML-only `.eml` with a
    5KB `<title>` plus `<body><p>VISIBLE_BODY</p></body>` and
    `--max-output-chars=100` produces a cap marker and keeps
    `doc.pdf`, but `VISIBLE_BODY` is absent. The previous fix
    bounded the title accumulator to `_max_output_chars`, then
    `render()` prepended the full title and the final-cap chop
    sliced from the FRONT — leaving only title prefix + footer.

    Post-fix, title is dynamically trimmed to fit AFTER body in
    `render()`. Body always gets priority; title only fills
    whatever room remains. The marker still emits when title is
    trimmed (so the cmd_materials safety net preserves the
    Attachments section instead of blind-chopping).
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "title_starves_body.eml"
    huge_title = "T" * 5000
    html = (
        f"<html><head><title>{huge_title}</title></head>"
        f"<body><p>VISIBLE_BODY</p></body></html>"
    )
    raw = (
        b"From: a@x\r\nTo: b@x\r\n"
        b"Subject: title-starves-body\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        + html.encode("utf-8") + b"\r\n"
        b"--B\r\n"
        b'Content-Type: application/pdf; name="doc.pdf"\r\n'
        b'Content-Disposition: attachment; filename="doc.pdf"\r\n'
        b"Content-Transfer-Encoding: base64\r\n\r\nAA==\r\n"
        b"--B--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p, max_output_chars=100)
    # CRITICAL: visible body content survives — no longer starved
    # by the oversized title.
    assert "VISIBLE_BODY" in out, (
        f"visible body lost to oversized title: {out!r}"
    )
    # Cap marker still present (title was trimmed → marker emitted).
    assert "<!--bsa:cap:applied:v1-->" in out
    # Attachments section preserved by virtue of marker presence.
    assert "## Attachments" in out
    assert "doc.pdf" in out


def test_html_to_markdown_exact_cap_body_no_false_marker(
    tmp_path: Path,
) -> None:
    """Codex round 10 of fix #3 [P3]: `_HTMLToMarkdown(max_output_chars=100)`
    on `'A' * 100` (100 visible chars) returned all 100 A's PLUS
    `_OUTPUT_CAP_MARKER` even though no source content was dropped.
    The final cap-check was running on `len(result)` AFTER
    appending the synthetic trailing `\\n`, so 101-char `result`
    > cap=100 falsely fired.

    Post-fix, cap-check uses `len(composed)` BEFORE the trailing
    newline. Exact-cap content emits no false marker.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    h = _HTMLToMarkdown(max_output_chars=100)
    h.feed("A" * 100)
    h.close()
    out = h.render()
    # All 100 A's present.
    assert "A" * 100 in out
    # NO false cap marker — content fit exactly.
    assert "<!--bsa:cap:applied:v1-->" not in out, (
        f"false marker on exact-cap body: {out!r}"
    )


def test_html_to_markdown_one_over_cap_emits_marker(
    tmp_path: Path,
) -> None:
    """Boundary check counterpart to the exact-cap test: 101 chars
    of body content with cap=100 MUST emit the marker (one char of
    visible source IS dropped).
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    h = _HTMLToMarkdown(max_output_chars=100)
    h.feed("A" * 101)
    h.close()
    out = h.render()
    # Marker present — actual source-content truncation occurred.
    assert "<!--bsa:cap:applied:v1-->" in out, (
        f"marker missing on over-cap body: {out!r}"
    )


def test_html_to_markdown_title_accumulator_truncation_emits_marker(
    tmp_path: Path,
) -> None:
    """Codex round 12 of fix #3 [P2]: `_HTML_TITLE_ACCUMULATOR_CAP`
    silently truncates `<title>` to 200 chars in `_on_data()`. With
    `max_output_chars=10000` (cap > body+title), the previous fix
    showed only the first 200 title chars and emitted no marker —
    breaking the cap-aware extractor contract that dropped source
    content must be visible to analysts via `_OUTPUT_CAP_MARKER`.

    Post-fix, the accumulator-truncation flag
    `_title_truncated_at_input` is consulted in `render()` and sets
    `_truncated=True` IF the title is actually injected into output.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    huge_title = "T" * 5000
    html = (
        f"<html><head><title>{huge_title}</title></head>"
        f"<body><p>VISIBLE_BODY</p></body></html>"
    )
    h = _HTMLToMarkdown(max_output_chars=10000)
    h.feed(html)
    h.close()
    out = h.render()
    # Title (truncated to 200 chars) is rendered as H1.
    assert out.startswith("# T"), (
        f"title not injected (truncated): {out!r}"
    )
    # Body is preserved (cap is huge relative to total content).
    assert "VISIBLE_BODY" in out
    # CRITICAL (P2): marker emitted because source title text was
    # dropped by the accumulator cap.
    assert "<!--bsa:cap:applied:v1-->" in out, (
        f"silent title-text drop — marker missing: {out!r}"
    )


def test_html_to_markdown_title_accumulator_truncation_with_h1_no_marker(
    tmp_path: Path,
) -> None:
    """Codex round 12 boundary: when `_has_h1` is True the title is
    NOT injected into output, so the accumulator-truncation drop is
    irrelevant (analyst never sees the title regardless of cap).
    Emitting a marker for a never-rendered title would be misleading.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    huge_title = "T" * 5000
    html = (
        f"<html><head><title>{huge_title}</title></head>"
        f"<body><h1>REAL H1</h1><p>VISIBLE_BODY</p></body></html>"
    )
    h = _HTMLToMarkdown(max_output_chars=10000)
    h.feed(html)
    h.close()
    out = h.render()
    # `<h1>` rendered (suppresses title injection per existing rule).
    assert "REAL H1" in out
    assert "VISIBLE_BODY" in out
    # Title NOT in output.
    assert "T" * 50 not in out
    # NO marker — the truncated title was never going to be shown.
    assert "<!--bsa:cap:applied:v1-->" not in out, (
        f"misleading marker for suppressed title: {out!r}"
    )


def test_html_to_markdown_short_title_no_input_truncation_no_marker(
    tmp_path: Path,
) -> None:
    """Negative case: a short title that fits in the accumulator cap
    MUST NOT trigger the marker (no actual source loss)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    html = (
        "<html><head><title>Short Title</title></head>"
        "<body><p>Short body.</p></body></html>"
    )
    h = _HTMLToMarkdown(max_output_chars=10000)
    h.feed(html)
    h.close()
    out = h.render()
    assert "# Short Title" in out
    assert "Short body." in out
    assert "<!--bsa:cap:applied:v1-->" not in out


def test_html_to_markdown_link_no_href_input_truncation_emits_marker(
    tmp_path: Path,
) -> None:
    """Codex round 13 of fix #3 [P2]: `<a>` without `href` plus
    5KB of text under `max_output_chars=200`. The link-text
    accumulator silently truncated the source to 200 chars; then
    `_flush_link` took the elif-text-only emit branch and never
    set `_truncated`. Net: 200 L's in output, no marker, source
    drop invisible.

    Post-fix, link-text accumulator drops set
    `_link_text_truncated_at_input=True`, and `_flush_link`
    promotes to `_truncated=True` after any actual emit branch.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    huge = "L" * 5000
    html = f"<html><body><a>{huge}</a></body></html>"
    h = _HTMLToMarkdown(max_output_chars=200)
    h.feed(html)
    h.close()
    out = h.render()
    # Some L's are present (truncated text rendered).
    assert "L" * 100 in out
    # CRITICAL: marker emitted because source link-text was dropped.
    assert "<!--bsa:cap:applied:v1-->" in out, (
        f"silent link-text drop — marker missing: {out!r}"
    )


def test_html_to_markdown_link_with_href_input_truncation_emits_marker(
    tmp_path: Path,
) -> None:
    """Same source-drop class but with `href`: link text trimmed
    in `_on_data`, then `_flush_link` emits `[text](href)`. The
    round-9 marker for trim-to-fit-overhead may or may not fire
    depending on buffer state; the round-13 input-truncation flag
    MUST fire regardless because source text was dropped at the
    accumulator level."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    huge = "L" * 5000
    html = f'<html><body><a href="http://e/x">{huge}</a></body></html>'
    h = _HTMLToMarkdown(max_output_chars=200)
    h.feed(html)
    h.close()
    out = h.render()
    assert "](http://e/x)" in out  # round-8 anchor shape preserved
    assert "<!--bsa:cap:applied:v1-->" in out


def test_html_to_markdown_short_link_no_marker(
    tmp_path: Path,
) -> None:
    """Negative case: short link text fits accumulator → no marker
    (no actual source loss)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    html = '<html><body><a href="http://e/x">click</a></body></html>'
    h = _HTMLToMarkdown(max_output_chars=200)
    h.feed(html)
    h.close()
    out = h.render()
    assert "[click](http://e/x)" in out
    assert "<!--bsa:cap:applied:v1-->" not in out


def test_html_to_markdown_no_cap_title_not_silently_truncated(
    tmp_path: Path,
) -> None:
    """Codex round 16 of fix #3 [P3]: when `_HTMLToMarkdown` is
    called with `max_output_chars=None` (helper-mode, e.g. direct
    Python use outside the CLI), the `_HTML_TITLE_ACCUMULATOR_CAP`
    was hard-applied while the marker path was gated on a non-None
    cap. Result: 5KB `<title>` was silently truncated to 200 chars
    with no `_OUTPUT_CAP_MARKER` and no other signal of source loss.

    Post-fix, in no-cap mode the title accumulator is unbounded
    (caller explicitly opted out). The full source title text
    appears in the rendered output.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    huge_title = "T" * 5000
    html = (
        f"<html><head><title>{huge_title}</title></head>"
        f"<body><p>body</p></body></html>"
    )
    h = _HTMLToMarkdown(max_output_chars=None)
    h.feed(html)
    h.close()
    out = h.render()
    # Full source title appears (no silent truncation).
    assert huge_title in out, (
        f"5KB title silently truncated in no-cap mode: out len={len(out)}"
    )
    # No marker (no cap → no truncation contract).
    assert "<!--bsa:cap:applied:v1-->" not in out


def test_html_to_markdown_no_cap_link_text_not_silently_truncated(
    tmp_path: Path,
) -> None:
    """No-cap mode parity for link-text accumulator. Verified via
    direct probe (the link branch was already gated on
    `max_output_chars is not None`); this test pins the contract.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    huge = "L" * 5000
    html = f'<html><body><a href="http://e/x">{huge}</a></body></html>'
    h = _HTMLToMarkdown(max_output_chars=None)
    h.feed(html)
    h.close()
    out = h.render()
    assert huge in out, "5KB link text silently truncated in no-cap mode"
    assert "<!--bsa:cap:applied:v1-->" not in out


def test_convert_pptx_no_cap_title_not_silently_truncated(
    tmp_path: Path,
) -> None:
    """No-cap mode parity for PPTX title placeholder
    (`_PPTX_TITLE_RUN_CAP`). When `_convert_pptx` is called with
    `max_output_chars=None` (helper-mode), the title cap was
    hard-applied while the marker path was gated. A 50KB title
    placeholder rendered as a 200-char H2 with no signal.

    Post-fix, in no-cap mode the title is fully materialized
    (caller explicitly opted out).
    """
    pytest.importorskip("pptx")
    from pptx import Presentation

    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_pptx
    finally:
        sys.path.pop(0)
    p = tmp_path / "no_cap_title.pptx"
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text_frame.text = "Y" * 5000
    prs.save(p)

    out = _convert_pptx(p, max_output_chars=None)
    # First-line of the joined first-paragraph text becomes the H2.
    # In no-cap mode it should contain the full 5KB.
    assert "Y" * 5000 in out, (
        f"PPTX title silently truncated in no-cap mode: out len={len(out)}"
    )
    assert "<!--bsa:cap:applied:v1-->" not in out


def test_pptx_slide1_oversized_title_does_not_stop_slide2(
    tmp_path: Path,
) -> None:
    """Codex round 14 of fix #3 [P2 — PPTX dual-flag split]: the
    round-13 fix set `truncated_during_extraction = True` on title
    source-drop, but that same flag drove the slide-loop break at
    the bottom — so slide 1 with an oversized title silently
    dropped slides 2..N even when the body budget had room.

    Repro: a 2-slide deck where slide 1 has a 50KB title (>
    `_PPTX_TITLE_RUN_CAP=200`) plus tiny body content, and slide 2
    has normal content. With cap=10000 (plenty of room), slide 2
    MUST still appear in the output, AND the cap marker MUST
    still appear (slide 1 title source was dropped).
    """
    pytest.importorskip("pptx")
    from pptx import Presentation
    from pptx.util import Inches

    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_pptx
    finally:
        sys.path.pop(0)
    p = tmp_path / "two_slides.pptx"
    prs = Presentation()
    # Slide 1: oversized title + tiny body.
    s1 = prs.slides.add_slide(prs.slide_layouts[0])
    s1.shapes.title.text_frame.text = "X" * 50_000
    body1 = s1.shapes.add_textbox(
        Inches(1), Inches(2), Inches(8), Inches(2),
    )
    body1.text_frame.text = "tiny body slide 1"
    # Slide 2: normal content.
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    body2 = s2.shapes.add_textbox(
        Inches(1), Inches(1), Inches(8), Inches(4),
    )
    body2.text_frame.text = "SLIDE_TWO_BODY_MARKER"
    prs.save(p)

    out = _convert_pptx(p, max_output_chars=10_000)
    # CRITICAL: slide 2 body content MUST appear — round-13 had a
    # bug where slide 1 title truncation halted the loop early.
    assert "SLIDE_TWO_BODY_MARKER" in out, (
        f"slide 2 dropped because slide 1 title was truncated: "
        f"{out!r}"
    )
    # Slide 1 body still present.
    assert "tiny body slide 1" in out
    # Marker present (slide 1 title source was dropped).
    assert "<!--bsa:cap:applied:v1-->" in out


def test_pptx_oversized_title_emits_cap_marker(
    tmp_path: Path,
) -> None:
    """Codex round 13 of fix #3 [P2 — PPTX parity]: a 50KB title
    placeholder with cap=5000 was clipped to `_PPTX_TITLE_RUN_CAP=200`
    chars in the title-streaming code, but `truncated_during_extraction`
    was never set — no marker, source drop invisible.

    Post-fix, the title-streaming `if room <= 0` and `if len(rt) > room`
    branches both set `truncated_during_extraction = True`.
    """
    pytest.importorskip("pptx")
    from pptx import Presentation
    from pptx.util import Inches

    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_pptx
    finally:
        sys.path.pop(0)
    p = tmp_path / "huge_title_marker.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])  # title slide
    slide.shapes.title.text_frame.text = "X" * 50_000
    body = slide.shapes.add_textbox(
        Inches(1), Inches(2), Inches(8), Inches(2),
    )
    body.text_frame.text = "small body content"
    prs.save(p)

    out = _convert_pptx(p, max_output_chars=5_000)
    # CRITICAL: marker emitted because source title text was dropped.
    assert "<!--bsa:cap:applied:v1-->" in out, (
        f"PPTX title silent drop — marker missing: {out!r}"
    )


def test_eml_html_exact_cap_body_keeps_attachments_via_cli(
    tmp_path: Path,
) -> None:
    """Codex round 11 of fix #3 [end-to-end]: an HTML EML whose body
    is exactly `max_output_chars` chars wide produces NO marker
    from `_HTMLToMarkdown` (correct — no source truncation), but
    `## Attachments` + `doc.pdf` push total content past the cap.
    Pre-fix, the cmd_materials safety net inferred "non-streaming"
    from marker absence and blind-chopped from the front, dropping
    Attachments. Post-fix, the safety net is kind-aware: cap-aware
    kinds (pptx/html/eml/msg) NEVER get blind-chopped — they own
    the marker contract.
    """
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    p = src / "exact_cap.eml"
    # 100 visible chars in the HTML body, exactly at cap.
    # Use bare `<body>` (no `<p>` wrapper) so no leading `\n\n` is
    # emitted into `_buf_size` — the body buffer holds exactly 100
    # `A`s and no streaming truncation occurs.
    visible = "A" * 100
    html = f"<html><body>{visible}</body></html>"
    raw = (
        b"From: a@x\r\nTo: b@x\r\n"
        b"Subject: exact-cap body\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        + html.encode("utf-8") + b"\r\n"
        b"--B\r\n"
        b'Content-Type: application/pdf; name="doc.pdf"\r\n'
        b'Content-Disposition: attachment; filename="doc.pdf"\r\n'
        b"Content-Transfer-Encoding: base64\r\n\r\nAA==\r\n"
        b"--B--\r\n"
    )
    p.write_bytes(raw)
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--max-output-chars=100",
    )
    assert res.returncode == 0, res.stderr
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    staged = next(inputs.glob("source_*_exact_cap.md"))
    body = staged.read_text(encoding="utf-8")
    # CRITICAL: body content survives.
    assert visible in body, (
        f"exact-cap body lost: {body!r}"
    )
    # CRITICAL: Attachments section + doc.pdf survive.
    assert "## Attachments" in body, (
        f"safety-net blind-chop dropped Attachments: {body!r}"
    )
    assert "doc.pdf" in body
    # NO false marker (body fit exactly).
    assert "<!--bsa:cap:applied:v1-->" not in body, (
        f"false marker on exact-cap body via CLI: {body!r}"
    )


def test_pdf_oversized_body_still_blind_chopped(
    tmp_path: Path,
) -> None:
    """Inverse-direction sanity: non-cap-aware kinds (pdf/docx/etc.)
    MUST still get blind-chopped on overflow. Use a fake `.text`
    source (kind="text" — also non-cap-aware) since pypdf is heavy
    to mock; the kind-aware branch covers BOTH cases identically.

    A 500-char text body with cap=100 → safety-net trims with
    canonical footer (the marker IS added).
    """
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    p = src / "long.txt"
    p.write_text("X" * 500, encoding="utf-8")
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--max-output-chars=100",
    )
    assert res.returncode == 0, res.stderr
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    staged = next(inputs.glob("source_*_long.md"))
    body = staged.read_text(encoding="utf-8")
    # Non-cap-aware extractor → safety net adds the marker after
    # blind-chop. Marker MUST be present.
    assert "<!--bsa:cap:applied:v1-->" in body, (
        f"safety-net marker missing for non-cap-aware kind: "
        f"{body!r}"
    )


def test_html_to_markdown_title_fits_with_body_room(
    tmp_path: Path,
) -> None:
    """Negative case for round-10 P1: when title is short and body
    is short, both render together without trimming and without
    a false cap marker."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _HTMLToMarkdown
    finally:
        sys.path.pop(0)
    html = (
        "<html><head><title>Short Title</title></head>"
        "<body><p>Short body content here.</p></body></html>"
    )
    h = _HTMLToMarkdown(max_output_chars=200)
    h.feed(html)
    h.close()
    out = h.render()
    assert "# Short Title" in out
    assert "Short body content here." in out
    assert "<!--bsa:cap:applied:v1-->" not in out


# ---- P2: max-output cap bounds conversion-time memory --------------


def test_pptx_per_paragraph_budget_bounds_in_memory_accumulation(
    tmp_path: Path,
) -> None:
    """v1.4.15 P2 fix: a single PPTX text frame with many large
    paragraphs MUST NOT accumulate the full frame into `body_parts`
    before the slide-chunk cap kicks in. The per-paragraph budget
    should clip mid-shape. We can't assert in-memory size directly
    in pytest, but we CAN assert (a) the staged output is bounded by
    the cap + footer, and (b) the truncation happened during
    extraction (cap-marker present even though the rest of the deck
    was never visited).
    """
    pytest.importorskip("pptx")
    from pptx import Presentation
    from pptx.util import Inches, Pt

    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_pptx
    finally:
        sys.path.pop(0)
    p = tmp_path / "huge_frame.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    tx = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(6))
    tf = tx.text_frame
    # 100 paragraphs of 5000 chars each = 500_000 chars before cap.
    # If the per-paragraph budget works, conversion stops after ~cap.
    tf.text = "A" * 5000
    for _ in range(99):
        para = tf.add_paragraph()
        para.text = "B" * 5000
    # A second slide that should never be reached after cap exhaustion.
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2_tx = s2.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(6))
    s2_tx.text_frame.text = "SHOULD-NOT-APPEAR"
    prs.save(p)

    out = _convert_pptx(p, max_output_chars=10_000)
    # CRITICAL: cap-marker emitted in-line.
    assert "<!--bsa:cap:applied:v1-->" in out
    # Output bounded by cap + small footer overhead. Footer is
    # ~150 chars; add 200 chars of slack.
    assert len(out) <= 10_000 + 250, (
        f"output exceeded cap+footer overhead: got {len(out)} chars"
    )
    # Slide 2 NEVER processed (its content not in the output).
    assert "SHOULD-NOT-APPEAR" not in out


def test_eml_plain_body_capped_after_get_content_keeps_attachments(
    tmp_path: Path,
) -> None:
    """v1.4.15 P2 fix: capping `plain_body` immediately after
    `part.get_content()` — to bound conversion-time memory — must
    set `body_truncated = True` so the cap marker is emitted. Pre-
    fix interim, the early cap silently bypassed the marker, the
    post-conversion safety net then performed a blind
    `content[:max_output_chars]` chop, and the Attachments section
    disappeared.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "huge_body.eml"
    big_body = "Z" * 1000
    raw = (
        b"From: a@x\r\nTo: b@x\r\n"
        b"Subject: huge body w/ attachment\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        + big_body.encode("ascii") + b"\r\n"
        b"--B\r\n"
        b'Content-Type: application/pdf; name="doc.pdf"\r\n'
        b'Content-Disposition: attachment; filename="doc.pdf"\r\n'
        b"Content-Transfer-Encoding: base64\r\n\r\nAA==\r\n"
        b"--B--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p, max_output_chars=200)
    # Cap marker must be present (set during decode-time cap).
    assert "<!--bsa:cap:applied:v1-->" in out, (
        "cap marker missing — body_truncated flag was lost"
    )
    # CRITICAL: Attachments section MUST survive even though body
    # was capped. This is the regression the post-conversion safety
    # net would otherwise cause.
    assert "## Attachments" in out, (
        f"attachments lost after early body cap: {out!r}"
    )
    assert "doc.pdf" in out


def test_eml_html_body_capped_after_get_content_keeps_attachments(
    tmp_path: Path,
) -> None:
    """v1.4.15 P2 fix: same invariant for text/html bodies. Capping
    `html_body` after decode must set `body_truncated` so the
    Attachments section survives the post-conversion safety net.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "huge_html.eml"
    big_html = "<html><body>" + ("X" * 1000) + "</body></html>"
    raw = (
        b"From: a@x\r\nTo: b@x\r\n"
        b"Subject: huge html body w/ attachment\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        + big_html.encode("ascii") + b"\r\n"
        b"--B\r\n"
        b'Content-Type: application/pdf; name="doc.pdf"\r\n'
        b'Content-Disposition: attachment; filename="doc.pdf"\r\n'
        b"Content-Transfer-Encoding: base64\r\n\r\nAA==\r\n"
        b"--B--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p, max_output_chars=300)
    # Codex round 1 of fix #3 flagged that the html-body test should
    # also assert the cap marker (parity with the plain-body test).
    # The marker confirms `body_truncated` was set during the early
    # html_body cap, preventing the post-conversion safety net from
    # performing a blind chop that would drop Attachments.
    assert "<!--bsa:cap:applied:v1-->" in out, (
        "cap marker missing for html-body cap path"
    )
    assert "## Attachments" in out
    assert "doc.pdf" in out


def test_msg_html_body_capped_after_get_keeps_attachments(
    tmp_path: Path, monkeypatch,
) -> None:
    """v1.4.15 P2 fix: codex round 1 of fix #3 flagged that
    `_render_email_markdown_from_msg` did NOT cap `htmlBody` before
    feeding it to `_HTMLToMarkdown`. The fix caps both `body` and
    `htmlBody` immediately after retrieval, sets `body_truncated`,
    AND preserves the Attachments section."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _render_email_markdown_from_msg
    finally:
        sys.path.pop(0)

    big_html = "<html><body>" + ("Y" * 5000) + "</body></html>"

    class _FakeAttachment:
        longFilename = "doc.pdf"
        shortFilename = None
        data = b"PDFDATA"

    class _BigHtmlMessage:
        sender = "x@y"
        to = "a@b"
        cc = ""
        subject = "huge html"
        date = "Wed, 28 Apr 2026 14:00:00 -0500"
        body = ""
        htmlBody = big_html.encode("utf-8")
        attachments = [_FakeAttachment()]

        def close(self) -> None:
            pass

    out = _render_email_markdown_from_msg(
        _BigHtmlMessage(), "synthetic.msg", max_output_chars=200,
    )
    # Cap marker emitted from the early html_body cap.
    assert "<!--bsa:cap:applied:v1-->" in out, (
        "cap marker missing for msg html-body path"
    )
    # Attachments section preserved (no blind-chop regression).
    assert "## Attachments" in out
    assert "doc.pdf" in out


def test_msg_plain_body_capped_after_get_keeps_attachments() -> None:
    """v1.4.15 P2 fix: same invariant for msg `body` (plain text)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _render_email_markdown_from_msg
    finally:
        sys.path.pop(0)

    class _FakeAttachment:
        longFilename = "doc.pdf"
        shortFilename = None
        data = b"PDFDATA"

    class _BigPlainMessage:
        sender = "x@y"
        to = "a@b"
        cc = ""
        subject = "huge plain"
        date = "Wed, 28 Apr 2026 14:00:00 -0500"
        body = "Z" * 5000
        htmlBody = None
        attachments = [_FakeAttachment()]

        def close(self) -> None:
            pass

    out = _render_email_markdown_from_msg(
        _BigPlainMessage(), "synthetic.msg", max_output_chars=200,
    )
    assert "<!--bsa:cap:applied:v1-->" in out
    assert "## Attachments" in out
    assert "doc.pdf" in out


def test_pptx_speaker_notes_capped(tmp_path: Path) -> None:
    """v1.4.15 P2 fix: codex round 1 of fix #3 flagged that
    `notes_tf.text` materialized full speaker notes before the
    slide-chunk cap. The fix caps notes_text against the remaining
    slide budget."""
    pytest.importorskip("pptx")
    from pptx import Presentation
    from pptx.util import Inches

    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_pptx
    finally:
        sys.path.pop(0)

    p = tmp_path / "huge_notes.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    tx = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(2))
    tx.text_frame.text = "small body"
    # Speaker notes is the bulk:
    notes_tf = slide.notes_slide.notes_text_frame
    notes_tf.text = "N" * 50_000
    prs.save(p)

    out = _convert_pptx(p, max_output_chars=2_000)
    # Output bounded by cap + footer overhead.
    assert len(out) <= 2_000 + 250, (
        f"output exceeded cap+footer overhead: {len(out)} chars"
    )
    # Cap marker present (truncation occurred during extraction).
    assert "<!--bsa:cap:applied:v1-->" in out


def test_eml_rfc822_inside_multipart_related_still_captured(
    tmp_path: Path,
) -> None:
    """Coverage-depth: the old gate was justified by `multipart/related`
    inline rfc822 being a "rare but valid" use case the walker was
    asked to leave alone. Post-fix, even that case captures the rfc822
    boundary as an attachment row — the analyst gets the
    `message/rfc822` marker AND the outer html body still renders
    (since multipart/related siblings live OUTSIDE the rfc822 subtree).
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "host.eml"
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: related with quoted forward\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/related; boundary="R"\r\n\r\n'
        b"--R\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        b"<html><body><p>Outer html body.</p></body></html>\r\n"
        b"--R\r\nContent-Type: message/rfc822\r\n\r\n"
        b"From: x@y\r\nTo: a@b\r\nSubject: quoted forward\r\n"
        b"MIME-Version: 1.0\r\nContent-Type: text/plain\r\n\r\n"
        b"Inline-quoted forward body.\r\n"
        b"--R--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    # Outer html body preserved (lives OUTSIDE the rfc822 subtree).
    assert "Outer html body." in out
    # rfc822 boundary captured.
    assert "## Attachments" in out
    assert "message/rfc822" in out
    # Inner forward body must NOT leak into outer body.
    body_section_start = out.index("## Body")
    body_section_end = out.index("## Attachments")
    body_section = out[body_section_start:body_section_end]
    assert "Inline-quoted forward body." not in body_section, (
        "rfc822 inside multipart/related leaked into outer body — "
        "boundary not preserved"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
