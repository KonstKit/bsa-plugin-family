"""Tests for v1.4.14 hotfix — fourth-pass external Codex audit findings.

External Codex R3 review (post-v1.4.13) flagged 2 MAJOR that the v1.4.13
self-review missed. Both closed in this hotfix.

  MAJOR #1: `_OUTPUT_CAP_FOOTER_RE` is unanchored — a document that merely
            QUOTES the footer text would (a) bypass the post-conversion
            safety net and (b) force false cap-based restages. Closed by
            adding a structural HTML-comment marker (`_OUTPUT_CAP_MARKER`)
            that real document text won't contain; detection now requires
            BOTH the marker AND the parseable cap value. Same fix applied
            to OCR-page cap footer (`_OCR_PAGE_CAP_MARKER`).

  MAJOR #2: forwarded-email pre-scan didn't skip `message/rfc822` containers
            already inside a captured forwarded attachment — nested forwards
            (forward-of-a-forward) surfaced as a SECOND top-level attachment
            row, breaking hierarchy and double-counting evidence. Closed by
            adding `if id(container) in forwarded_descendants: continue` at
            the top of the pre-scan loop. msg.walk() is depth-first parents-
            before-children, so the outer rfc822 is processed first and adds
            its inner rfc822 (and that inner's descendants) to the skip set
            in the same iteration.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "analysis" / "proposals" / "stage1" / "inputs").mkdir(parents=True)
    return ws


def _run_cli(*args: str):
    import subprocess
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "bsa_cli.py"), *args],
        capture_output=True, text=True, check=False,
    )


# ---- MAJOR #1: footer false-positive on quoted text -----------------


def test_md_quoting_footer_text_is_NOT_treated_as_cap_applied(
    tmp_path: Path,
) -> None:
    """A `.md` source documenting `bsa materials` truncation behavior
    contains the footer TEXT but NOT the structural HTML-comment
    marker. The post-conversion safety net must NOT skip the trim
    just because the source quotes the footer."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _OUTPUT_CAP_MARKER
    finally:
        sys.path.pop(0)
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    # Body that QUOTES the human-readable footer text but lacks the
    # structural marker — should be treated as ordinary content. Pad
    # to exceed the cap so the safety-net branch is exercised.
    quoted_footer = (
        "_[bsa materials: body truncated at 5,000,000 chars by "
        "--max-output-chars; raise the cap (default 5_000_000) OR "
        "pre-trim the source]_"
    )
    body = quoted_footer + "\n\n" + ("PADDING_LINE\n" * 200)
    (src / "doc.md").write_text(body, encoding="utf-8")
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--max-output-chars=200",
    )
    assert res.returncode == 0, res.stderr
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    staged = next(inputs.glob("source_*_doc.md"))
    out = staged.read_text(encoding="utf-8")
    # The structural marker MUST be present in the staged output
    # (post-conversion safety net applied trim + footer because the
    # quoted text didn't carry the marker). Pre-fix, the safety net
    # would have been fooled by the quoted footer, skipped trim, and
    # the marker would NOT be in the staged file.
    assert _OUTPUT_CAP_MARKER in out, (
        f"safety-net trim was skipped because of quoted footer text; "
        f"marker should now be present after the genuine post-trim. "
        f"out (first 500): {out[:500]!r}"
    )
    # Also: the staged body length is bounded by cap + footer overhead.
    assert len(out) < 1500


def test_restage_unchanged_doc_quoting_footer_does_not_force_restage(
    tmp_path: Path,
) -> None:
    """An UNCHANGED source whose body merely quotes the footer string
    must NOT trigger cap-based restage on subsequent runs. Pre-fix,
    the unanchored regex would parse a "prior cap" out of the quoted
    text and false-trigger restage on every run."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    quoted_footer = (
        "Note: when I run with --max-output-chars=100, output gets "
        "footer like _[bsa materials: body truncated at 100 chars "
        "by --max-output-chars; raise the cap]_."
    )
    (src / "notes.md").write_text(quoted_footer, encoding="utf-8")
    # Initial stage with a HIGH cap so no real truncation happens.
    res1 = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--max-output-chars=10000",
    )
    assert res1.returncode == 0
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    staged = next(inputs.glob("source_*_notes.md"))
    mtime_before = staged.stat().st_mtime
    # Re-stage with a HIGHER cap. Source unchanged. Pre-fix bug: the
    # planner would parse "100" out of the quoted text as the prior
    # cap, see new cap > 100, and force-restage. Post-fix: the marker
    # check fails (the quoted text doesn't carry HTML-comment marker)
    # so the planner correctly skips restage.
    res2 = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--restage-changed", "--max-output-chars=20000",
    )
    assert res2.returncode == 0
    assert staged.stat().st_mtime == mtime_before, (
        "unchanged source quoting footer text was incorrectly restaged"
    )


def test_real_truncation_still_carries_marker(tmp_path: Path) -> None:
    """Sanity check: when truncation IS legitimate, the marker is
    written to the staged file. Without this, the v1.4.13 cap-aware
    behavior breaks (post-trim AND restage become no-ops)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _OUTPUT_CAP_MARKER
    finally:
        sys.path.pop(0)
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "big.md").write_text("X" * 5000, encoding="utf-8")
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src),
        "--commit", "--max-output-chars=200",
    )
    assert res.returncode == 0
    staged = next(
        (ws / "analysis/proposals/stage1/inputs").glob("source_*_big.md")
    )
    out = staged.read_text(encoding="utf-8")
    assert _OUTPUT_CAP_MARKER in out, "marker missing from real truncation"
    assert "max-output-chars" in out


# ---- MAJOR #2: nested forwarded rfc822 hierarchy --------------------


def test_eml_nested_rfc822_does_not_flatten_into_top_level(
    tmp_path: Path,
) -> None:
    """A forward-of-a-forward (rfc822 attachment whose inner email
    itself carries another rfc822 attachment) must produce EXACTLY
    ONE top-level Attachments row for the OUTER forwarded.eml. The
    nested inner attachment is folded into the outer's serialized
    payload (the size column reflects it). Pre-fix, msg.walk()
    surfaced the nested rfc822 as a SECOND top-level attachment,
    double-counting evidence and breaking hierarchy."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "host.eml"
    # Structure:
    #   host (multipart/mixed)
    #     - text/plain (host body)
    #     - message/rfc822 (forwarded.eml; attachment)
    #         outer-fwd (multipart/mixed)
    #           - text/plain (outer-fwd body)
    #           - message/rfc822 (nested.eml; attachment)
    #               nested-fwd (text/plain)
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
        b'Content-Type: multipart/mixed; boundary="INNER"\r\n\r\n'
        b"--INNER\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Outer forward body.\r\n"
        b"--INNER\r\n"
        b'Content-Type: message/rfc822; name="nested.eml"\r\n'
        b'Content-Disposition: attachment; filename="nested.eml"\r\n\r\n'
        b"From: dave@example.com\r\n"
        b"To: carol@example.com\r\n"
        b"Subject: original original\r\n"
        b"Date: Mon, 26 Apr 2026 09:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Deeply nested body.\r\n"
        b"--INNER--\r\n"
        b"--OUTER--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    # Outer host body preserved.
    assert "Forwarding the FYI thread below." in out
    # Attachments section exists.
    assert "## Attachments" in out
    # CRITICAL: the OUTER `forwarded.eml` is listed as top-level
    # attachment (with message/rfc822 type).
    assert "forwarded.eml" in out
    assert "message/rfc822" in out
    # CRITICAL: the NESTED `nested.eml` is NOT a top-level
    # Attachments row. Pre-fix, both forwarded.eml AND nested.eml
    # appeared at the same indentation level.
    assert "nested.eml" not in out, (
        "nested rfc822 attachment was flattened into top-level "
        "Attachments — hierarchy broken"
    )
    # CRITICAL: deeply-nested body must NOT leak into the OUTER
    # email's body (would mean we walked into the rfc822 subtree).
    assert "Deeply nested body." not in out
    assert "Outer forward body." not in out
    # Sanity: exactly ONE rfc822 row in Attachments.
    rfc822_rows = [
        line for line in out.splitlines()
        if "message/rfc822" in line
    ]
    assert len(rfc822_rows) == 1, (
        f"expected exactly 1 rfc822 attachment row, got {len(rfc822_rows)}: "
        f"{rfc822_rows}"
    )


def test_eml_two_separate_rfc822_attachments_both_listed(
    tmp_path: Path,
) -> None:
    """Inverse-direction sanity: TWO sibling rfc822 attachments at
    the SAME level must both be recorded. The nested-skip fix must
    NOT accidentally suppress legitimate sibling forwards."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts._bsa_cli_materials import _convert_eml
    finally:
        sys.path.pop(0)
    p = tmp_path / "host.eml"
    raw = (
        b"From: a@x\r\nTo: b@x\r\nSubject: two forwards\r\n"
        b"Date: Wed, 28 Apr 2026 14:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Two forwards attached.\r\n"
        b"--B\r\n"
        b'Content-Type: message/rfc822; name="fwd1.eml"\r\n'
        b'Content-Disposition: attachment; filename="fwd1.eml"\r\n\r\n'
        b"From: x@y\r\nTo: a@x\r\nSubject: first\r\n"
        b"Date: Tue, 27 Apr 2026 09:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\nContent-Type: text/plain\r\n\r\nfirst body\r\n"
        b"--B\r\n"
        b'Content-Type: message/rfc822; name="fwd2.eml"\r\n'
        b'Content-Disposition: attachment; filename="fwd2.eml"\r\n\r\n'
        b"From: x@y\r\nTo: a@x\r\nSubject: second\r\n"
        b"Date: Tue, 27 Apr 2026 10:00:00 -0500\r\n"
        b"MIME-Version: 1.0\r\nContent-Type: text/plain\r\n\r\nsecond body\r\n"
        b"--B--\r\n"
    )
    p.write_bytes(raw)
    out = _convert_eml(p)
    assert "fwd1.eml" in out
    assert "fwd2.eml" in out
    # Body of inner emails must NOT leak.
    assert "first body" not in out
    assert "second body" not in out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
