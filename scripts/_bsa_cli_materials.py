"""Materials subcommand for `bsa` CLI (v1.3.11 split).

Extracted from `scripts/bsa_cli.py` in v1.3.11 — the second half of the
god-module decomposition (v1.3.9 + v1.3.10 carved write_validator.py;
v1.3.11 starts on bsa_cli.py). The materials subcommand stages PDF /
DOCX / MD / TXT inputs from an external source directory into
`analysis/proposals/stage1/inputs/`, plus emits a draft
`source_manifest.csv` with `ReliabilityTier=T5` defaults the operator
re-tags during `/bsa-stage 1` review.

Public surface (re-exported from `bsa_cli.py` for backward compat):

  * `cmd_materials(args)` — argparse subcommand handler.
  * `ConversionUnavailable` — optional dependency missing (pypdf /
    python-docx).
  * `ConversionFailed` — installed but failed on a specific file.
  * `ManifestHeaderDrift` — existing manifest header mismatches
    canonical A50 column order.
  * `SourcePlan` — dataclass for one planned conversion.
  * `_atomic_write_text(path, content)` — tempfile + os.replace
    atomic write helper (also used directly by tests).
  * `_convert_pdf(path)` / `_convert_docx(path)` — extractors.
  * `_A50_HEADER` / `_A50_HEADER_WITH_EFFECTIVE_DATE` — canonical
    column-order constants.
  * Plus the helper surface (`_slugify`, `_next_source_id`,
    `_scan_source_dir`, `_check_write_containment`,
    `_plan_conversions`, `_render_draft_manifest`,
    `_upsert_draft_manifest`, etc.) — kept private but re-exported
    so existing test imports continue to resolve.

Dependencies:
  * Stdlib only at module level. PDF/DOCX libraries (`pypdf`,
    `python-docx`) imported lazily inside the converter functions.
  * `WorkspaceState` is lazy-imported inside `cmd_materials` to
    avoid a module-load-time circular import with `bsa_cli.py`.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


# Extension classification — lower-case ext (with dot) → kind. `kind`
# decides which converter we route to. Kept narrow on purpose; new
# formats are an explicit follow-up, not a silent best-effort.
# v1.4.1 adds xlsx + csv (closes the call-data staging gap — call
# data tables are typically xlsx/csv, and pre-v1.4.1 they were
# silently classified as `unsupported`).
# v1.4.2 adds json + tsv + graphql:
#   - json: structured data dumps (e.g., voicescribe traces, explorer
#     payloads). Pretty-printed in a code fence with a structure
#     summary header so analysts can grep claims without parsing.
#   - tsv: tab-separated tables (process_steps_flat etc.). Reuses the
#     csv extractor with a tab delimiter — same streaming + truncation
#     + encoding-fallback semantics.
#   - graphql: SDL text; classified as `text` because the syntax is
#     human-readable and analyst-grep-friendly without conversion.
_EXT_TO_KIND: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "text",
    ".markdown": "text",
    ".txt": "text",
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".json": "json",
    ".tsv": "tsv",
    ".graphql": "text",
    # v1.4.5 (closes lifecycle review rec #3 first half):
    #   - pptx: presentations are common deliverables for stakeholder
    #     reviews, customer pitches, and architecture walkthroughs.
    #     python-pptx lazy-imported (matches the pdf/docx pattern).
    #   - html / htm: web-exported documentation, one-page customer
    #     portals, exported confluence pages. stdlib html.parser only
    #     (no new dep) — extracts headings/paragraphs/lists/links into
    #     analyst-grep-friendly markdown.
    ".pptx": "pptx",
    ".html": "html",
    ".htm": "html",
    # v1.4.6 (closes lifecycle review rec #3 second half): email
    # evidence is a primary BSA source class (stakeholder approvals,
    # requirement clarifications, A51 origin, vendor SLA threads).
    #   - eml: RFC 822 / MIME — stdlib `email` only.
    #   - msg: Outlook proprietary CFBF — `extract-msg` lazy-imported.
    # Both extractors share the same output shape (metadata block +
    # body + attachments list) so downstream tooling sees one schema
    # regardless of which client exported the email.
    ".eml": "eml",
    ".msg": "msg",
}

# Per-file safety caps. The user is pointing this at arbitrary
# external content — we want to catch mistakes (a 200 MB scanned PDF,
# a directory of binary blobs) before they consume tens of seconds
# of subprocess time. v1.4.1 makes the cap CLI-overridable via
# `--max-mb=<N>` so an operator with a known-good 50MB call-data
# table can stage it explicitly without editing the source.
_DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB

# v1.4.1: row caps for tabular extractors. Without a cap, a 1M-row
# CSV would expand to a 100MB markdown file — eats LLM context with
# no analytical value. The cap is high enough that real interview
# transcripts + scope spreadsheets land in full, low enough that a
# raw call-event log gets truncated with a clear "[truncated]" note
# the operator can act on (sample the file, summarize externally,
# or raise the cap). Tunable via `--max-rows-per-table=<N>`.
_DEFAULT_MAX_ROWS_PER_TABLE = 5000


class ConversionUnavailable(RuntimeError):
    """Raised when the optional library for a format is not installed."""


class ConversionFailed(RuntimeError):
    """Raised when the optional library is installed but conversion fails
    on this specific file (corrupt PDF, encrypted DOCX, etc.)."""


@dataclass
class SourcePlan:
    """One planned conversion. Holds what we'd do at --commit time."""
    src: Path                 # original file path
    kind: str                 # "pdf" | "docx" | "text"
    target: Path              # workspace-relative destination
    source_id: str            # "S-001" etc.
    origin_rel: str = ""      # canonical Origin recorded in BOTH the
                              # manifest CSV row AND the provenance
                              # comment at the top of the staged file.
                              # Round-3 fix: previously basename was
                              # written into the comment while the
                              # manifest used the relative path —
                              # disambiguation false-skipped distinct
                              # `team_a/foo.md` vs `team_b/foo.md`.
    skipped_reason: Optional[str] = None  # set when --commit would skip
    # v1.4.4 (closes lifecycle review rec #2): content-hash columns.
    # Populated lazily on --commit; absent on dry-run plans. Skipped
    # plans (already-staged duplicates) leave these as None.
    content_hash: Optional[str] = None         # sha256 hex digest
    original_bytes: Optional[int] = None       # raw byte length
    original_mtime_utc: Optional[str] = None   # ISO-8601 UTC second
    # v1.4.4 --restage-changed: True when this plan replaces a row
    # already in the manifest (by Origin lookup). source_id is set to
    # the EXISTING SID; target overwrites the existing staged file.
    # The writer updates the manifest row in place rather than
    # appending a fresh row.
    restage: bool = False


def _slugify(name: str, max_len: int = 40) -> str:
    """Turn a filename stem into a stable lowercase snake_case slug.

    Caller is expected to pass the stem (or a free-form title);
    we do NOT strip a trailing extension here, because Path.stem
    only chops the LAST dotted segment — applying it twice eats
    legitimate version markers like `v4.2` (becomes `v4`).

    Examples:
        "Procurement Policy v4.2"          -> "procurement_policy_v4_2"
        "PM Interview — Alex (final)"     -> "pm_interview_alex_final"
        "Стандарт Доставки"                -> "src_<hash>" (no ASCII)
    Non-ASCII is dropped (re.ASCII flag); if nothing usable remains
    we fall back to a hash so we never emit an empty stem.
    """
    # Lowercase + replace any non-alnum run with a single underscore.
    out = re.sub(r"[^a-z0-9]+", "_", name.lower(), flags=re.ASCII)
    out = out.strip("_")
    if not out:
        # Last-resort: derive a stable token from the original name
        # so we don't collide on multiple "untitled" inputs.
        import hashlib
        return "src_" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return out[:max_len].rstrip("_") or "src"


def _next_source_id(inputs_dir: Path, manifest_path: Path) -> int:
    """Return the next free source ordinal (1-based).

    Looks at:
      - existing source_NNN_*.md files in inputs/
      - existing rows in source_manifest.csv (if any)
    and returns max(existing) + 1, or 1 if none.
    """
    # v1.4.3 R2 fix: \d{3,} (was \d{3,4}) so 5+ digit SourceIDs are
    # consistently handled by both staging and recovery paths.
    used: set[int] = set()
    src_pat = re.compile(r"^source_(\d{3,})_")
    if inputs_dir.is_dir():
        for f in inputs_dir.iterdir():
            m = src_pat.match(f.name)
            if m:
                used.add(int(m.group(1)))
    if manifest_path.is_file():
        # Cheap parse — first column is SourceID like "S-001".
        try:
            text = manifest_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        sid_pat = re.compile(r"^S-(\d{3,})\b")
        for line in text.splitlines():
            m = sid_pat.match(line.strip())
            if m:
                used.add(int(m.group(1)))
    return (max(used) + 1) if used else 1


def _convert_pdf(path: Path) -> str:
    """Extract text from a PDF using pypdf. Raises ConversionUnavailable
    if pypdf is not installed; ConversionFailed on per-file errors."""
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ConversionUnavailable(
            "pypdf not installed. Install with `pip install pypdf` "
            "to convert PDFs (or convert them externally and re-run "
            "with .md / .txt files)."
        ) from exc
    try:
        reader = pypdf.PdfReader(str(path))
        if reader.is_encrypted:
            # Try empty password — common for "view-protected" PDFs.
            try:
                reader.decrypt("")
            except Exception:
                raise ConversionFailed(
                    f"PDF is encrypted: {path.name}. Decrypt externally before re-staging."
                )
        chunks: list[str] = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as page_exc:  # pragma: no cover — pypdf-internal
                text = f"[bsa-materials: page {i} extraction failed: {page_exc}]"
            chunks.append(f"## Page {i}\n\n{text.strip()}\n")
        return "\n".join(chunks).strip() + "\n"
    except ConversionFailed:
        raise
    except Exception as exc:
        raise ConversionFailed(f"pypdf failed on {path.name}: {exc}") from exc


def _convert_docx(path: Path) -> str:
    """Extract text from a DOCX using python-docx. Same error contract
    as _convert_pdf."""
    try:
        import docx  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ConversionUnavailable(
            "python-docx not installed. Install with `pip install "
            "python-docx` to convert DOCX (or convert externally to MD)."
        ) from exc
    try:
        doc = docx.Document(str(path))
    except Exception as exc:
        raise ConversionFailed(f"python-docx failed on {path.name}: {exc}") from exc
    # Walk paragraphs + tables in document order. python-docx doesn't
    # expose a direct "iterate body in order" API; we use the
    # underlying XML element ordering for stability.
    from docx.oxml.ns import qn  # type: ignore[import-not-found]
    body = doc.element.body
    parts: list[str] = []
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            # Match by element identity; expensive but doc.paragraphs
            # is short for typical interview transcripts.
            for p in doc.paragraphs:
                if p._element is child:  # type: ignore[attr-defined]
                    text = p.text.strip()
                    if text:
                        parts.append(text)
                    break
        elif child.tag == qn("w:tbl"):
            for table in doc.tables:
                if table._element is child:  # type: ignore[attr-defined]
                    for row in table.rows:
                        cells = [c.text.strip() for c in row.cells]
                        parts.append(" | ".join(cells))
                    parts.append("")  # blank line after table
                    break
    return "\n\n".join(parts).strip() + "\n"


def _convert_pptx(path: Path) -> str:
    """Extract text from a PPTX deck using python-pptx.

    v1.4.5 (closes lifecycle review rec #3 first half). Output shape:
    one H2 per VISIBLE slide ("## Slide N: <title>"), followed by
    paragraph text from each text-bearing shape, followed by a
    "Speaker notes" H3 if the slide carries notes. Tables in slides
    render as " | " separated rows (matches the docx convention).

    Skips slides marked hidden (`<p:sld show='0'>`); operator can
    override by un-hiding in PowerPoint and re-staging.

    `python-pptx` lazy-imported (matches pdf/docx pattern). Raises
    `ConversionUnavailable` if the dep is missing; `ConversionFailed`
    on per-file errors (corrupt zip, encrypted, etc.).
    """
    try:
        from pptx import Presentation  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ConversionUnavailable(
            "python-pptx not installed. Install with `pip install "
            "python-pptx` to convert PPTX (or convert externally to PDF "
            "and re-stage)."
        ) from exc
    try:
        prs = Presentation(str(path))
    except Exception as exc:
        raise ConversionFailed(
            f"python-pptx failed on {path.name}: {exc}"
        ) from exc

    chunks: list[str] = []
    visible_idx = 0
    for raw_idx, slide in enumerate(prs.slides, start=1):
        # Skip hidden slides — `<p:sld show="0">` in OOXML.
        # `slide.element.attrib` is a dict-like; default-visible if
        # attr absent. v1.4.5 R1 MAJOR #1 fix: OOXML booleans accept
        # `0`/`1`/`false`/`true` (case-insensitive). Earlier code
        # only matched `"0"` exactly, leaving `show="false"` decks
        # leaking intentionally-hidden slides into staging.
        try:
            show_attr = (slide.element.attrib.get("show", "1") or "").lower()
            if show_attr in ("0", "false"):
                continue
        except Exception:
            pass  # attribute access shouldn't fail; defensive only
        visible_idx += 1
        # Title heuristic: first shape that has a non-empty text
        # AND looks like a title placeholder.
        title = ""
        try:
            ti = slide.shapes.title  # may return None
            if ti is not None and ti.has_text_frame:
                title = (ti.text_frame.text or "").strip().splitlines()[0:1]
                title = title[0] if title else ""
        except Exception:
            pass
        header_line = (
            f"## Slide {visible_idx}: {title}" if title
            else f"## Slide {visible_idx}"
        )
        body_parts: list[str] = []
        for shape in slide.shapes:
            # Skip the title shape we already used.
            try:
                if shape == slide.shapes.title:
                    continue
            except Exception:
                pass
            # Tables: render as pipe-separated rows.
            # v1.4.5 R1 MINOR #6 fix: preserve intra-cell linebreaks
            # via `<br>` rather than collapsing them to spaces — keeps
            # multi-line bullet lists / paragraph breaks inside table
            # cells visible to downstream analysts.
            if getattr(shape, "has_table", False):
                try:
                    for row in shape.table.rows:
                        cells = [
                            (cell.text or "").strip().replace("\n", "<br>")
                            for cell in row.cells
                        ]
                        body_parts.append(" | ".join(cells))
                    body_parts.append("")
                except Exception:
                    pass
                continue
            # Text-bearing shapes.
            if getattr(shape, "has_text_frame", False):
                try:
                    for para in shape.text_frame.paragraphs:
                        text = "".join(run.text for run in para.runs).strip()
                        if text:
                            body_parts.append(text)
                except Exception:
                    pass
        # Speaker notes (notes_slide may be absent on some decks).
        notes_text = ""
        try:
            if slide.has_notes_slide:
                notes_tf = slide.notes_slide.notes_text_frame
                if notes_tf is not None:
                    notes_text = (notes_tf.text or "").strip()
        except Exception:
            pass
        slide_section = [header_line]
        if body_parts:
            slide_section.append("")
            slide_section.extend(body_parts)
        if notes_text:
            slide_section.append("")
            slide_section.append("### Speaker notes")
            slide_section.append("")
            slide_section.append(notes_text)
        chunks.append("\n".join(slide_section))
    if not chunks:
        # All slides hidden OR empty deck — emit a single line so the
        # staged file isn't 0 bytes (downstream tools that read the
        # provenance comment expect SOME body).
        return "_(no visible slides)_\n"
    return "\n\n".join(chunks).strip() + "\n"


def _convert_html(path: Path) -> str:
    """Convert an HTML / HTM file to analyst-grep-friendly markdown.

    v1.4.5 (closes lifecycle review rec #3 first half). Stdlib only
    — no BeautifulSoup, no lxml. Uses `html.parser.HTMLParser` +
    `html.unescape` for entity decoding. Encoding fallback
    (utf-8 → latin-1) matches the csv extractor.

    Conversion rules:
      * `<script>`, `<style>` content stripped entirely.
      * `<h1>`-`<h6>` → markdown `#`-`######` headers (blank lines
        around).
      * `<p>`, `<div>`, `<br>` → paragraph breaks.
      * `<li>` → `- ` bullets (also `<ol>` items, simple flat list).
      * `<a href="X">text</a>` → `[text](X)`.
      * `<strong>`/`<b>` → `**text**`; `<em>`/`<i>` → `*text*`.
      * `<code>` → `` `text` ``; `<pre>` → fenced ```` ``` ```` block.
      * `<title>` → first H1 if no other H1 in body.
      * Other tags stripped, content preserved.
      * Whitespace normalized (multiple blank lines collapsed to one).

    No size cap beyond `--max-mb` — operator's responsibility to
    pre-trim mega-pages.
    """
    # v1.4.5 R1 MAJOR #2 fix: charset detection chain.
    #   (1) UTF-8 / UTF-16 BOM if present.
    #   (2) `<meta charset="X">` or
    #       `<meta http-equiv="Content-Type" content="...; charset=X">`
    #       sniffed from the first 1024 bytes (HTML5 prologue).
    #   (3) utf-8 strict.
    #   (4) cp1252 (Windows-1252) — covers smart quotes / em-dash /
    #       trademark glyphs that latin-1 silently turns into control
    #       characters. cp1252 is a strict superset of latin-1 for
    #       most byte values; safer fallback for legacy web exports.
    #   (5) latin-1 — final no-fail fallback.
    raw_bytes = path.read_bytes()
    text: Optional[str] = None
    sniffed_codec: Optional[str] = None
    # (1) BOM sniff.
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        sniffed_codec = "utf-8-sig"
    elif raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
        sniffed_codec = "utf-16"
    # (2) <meta charset=...> sniff over first 1024 bytes via latin-1
    # (which can decode any byte) so the regex finds ASCII tag content.
    if sniffed_codec is None:
        prologue = raw_bytes[:1024].decode("latin-1", errors="ignore").lower()
        m = re.search(r'<meta[^>]+charset=["\']?([\w\-]+)', prologue)
        if m:
            sniffed_codec = m.group(1)
    if sniffed_codec is not None:
        try:
            text = raw_bytes.decode(sniffed_codec)
        except (UnicodeDecodeError, LookupError):
            text = None  # fall through to ordered fallback chain
    if text is None:
        for codec in ("utf-8", "cp1252", "latin-1"):
            try:
                text = raw_bytes.decode(codec)
                break
            except UnicodeDecodeError:
                continue
    if text is None:
        raise ConversionFailed(
            f"could not decode {path.name} as utf-8 / cp1252 / "
            f"latin-1; pre-convert externally before re-staging"
        )
    parser = _HTMLToMarkdown()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:
        raise ConversionFailed(
            f"html.parser failed on {path.name}: {exc}"
        ) from exc
    return parser.render()


class _HTMLToMarkdown:
    """Stdlib-only HTML → markdown converter for `_convert_html`.

    Push-based (HTMLParser-driven). Maintains a small state machine
    for the active context (skip-script, in-pre, in-link, list-depth).
    Output is built up in `_buf` then post-processed (whitespace
    collapse, title-injection) by `render()`.

    Not a fully-spec-compliant converter — covers the 80% of HTML
    shapes that appear in real analyst inputs (Confluence exports,
    one-page customer portals, MDN-style docs). Unsupported edge
    cases (deeply nested tables, custom elements, MathML) degrade
    gracefully to text-with-stripped-tags."""

    # Block-level tags get a blank-line break after their close tag.
    _BLOCK_TAGS = frozenset({
        "p", "div", "section", "article", "header", "footer", "nav",
        "main", "blockquote", "table", "tr",
    })
    # Headings — `_HEADING_TAGS[tag]` = level (1..6).
    _HEADING_TAGS = {f"h{i}": i for i in range(1, 7)}
    # Inline emphasis tags.
    _EMPHASIS_OPEN = {"strong": "**", "b": "**", "em": "*", "i": "*"}
    _CODE_OPEN = {"code": "`"}

    def __init__(self) -> None:
        from html.parser import HTMLParser  # lazy
        self._buf: list[str] = []
        self._skip_depth = 0       # >0 inside <script> / <style>
        self._in_pre = 0           # >0 inside <pre>
        self._link_href: Optional[str] = None
        self._link_text_buf: Optional[list[str]] = None
        self._list_stack: list[str] = []  # 'ul' | 'ol'
        self._title_text: Optional[str] = None
        self._in_title = 0
        self._has_h1 = False
        self._heading_level = 0    # >0 while inside hN

        # Subclass HTMLParser via a lightweight inner class so we
        # don't need a separate top-level class for the parser's
        # callbacks (cleaner module surface).
        outer = self

        class _Parser(HTMLParser):
            def handle_starttag(_self, tag: str, attrs: list) -> None:
                outer._on_start(tag, dict(attrs))

            def handle_endtag(_self, tag: str) -> None:
                outer._on_end(tag)

            def handle_startendtag(_self, tag: str, attrs: list) -> None:
                # Self-closing tags: <br/>, <hr/>, <img/>.
                outer._on_start(tag, dict(attrs))
                outer._on_end(tag)

            def handle_data(_self, data: str) -> None:
                outer._on_data(data)

            def handle_entityref(_self, name: str) -> None:
                import html as _html_lib
                outer._on_data(_html_lib.unescape(f"&{name};"))

            def handle_charref(_self, name: str) -> None:
                import html as _html_lib
                outer._on_data(_html_lib.unescape(f"&#{name};"))

        self._parser = _Parser(convert_charrefs=True)

    # Forward a couple of HTMLParser methods so the caller doesn't
    # need to know the inner-class wiring.
    def feed(self, text: str) -> None:
        self._parser.feed(text)

    def close(self) -> None:
        self._parser.close()

    # ---- internal state machine -----------------------------------

    def _on_start(self, tag: str, attrs: dict) -> None:
        tag = tag.lower()
        if tag in ("script", "style"):
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return
        if tag == "title":
            self._in_title += 1
            return
        # v1.4.5 R1 MINOR #5 fix: ignore inline-tag markup while we're
        # inside <title>. Otherwise <title>A <b>B</b> C</title> would
        # leak `**...**` into _buf and fragment the title text.
        if self._in_title > 0:
            return
        # v1.4.5 R1 MINOR #4 fix: a block-level tag (heading, p,
        # div, ...) inside <a> is rare-but-valid HTML5. Flush the
        # link first so the heading markup lands at body level
        # rather than inside [text](href). We close the link with
        # whatever text we collected so far (may be empty), then
        # fall through to normal block handling.
        if (
            self._link_text_buf is not None
            and (tag in self._HEADING_TAGS
                 or tag in self._BLOCK_TAGS
                 or tag == "pre"
                 or tag == "li"
                 or tag in ("ul", "ol"))
        ):
            # v1.4.5 R2 NEW MINOR fix: drop_empty=True so an empty
            # link buf (heading-text hasn't accumulated yet) doesn't
            # leak a stray `<href>` before the block-level markup.
            self._flush_link(drop_empty=True)
        if tag == "pre":
            self._in_pre += 1
            self._buf.append("\n\n```\n")
            return
        if tag == "br":
            self._buf.append("\n")
            return
        if tag in self._HEADING_TAGS:
            level = self._HEADING_TAGS[tag]
            if level == 1:
                self._has_h1 = True
            self._buf.append("\n\n" + "#" * level + " ")
            self._heading_level = level
            return
        if tag in ("ul", "ol"):
            self._list_stack.append(tag)
            self._buf.append("\n")
            return
        if tag == "li":
            self._buf.append("\n- ")
            return
        if tag == "a":
            self._link_href = attrs.get("href") or ""
            self._link_text_buf = []
            return
        if tag in self._EMPHASIS_OPEN and self._heading_level == 0:
            self._buf.append(self._EMPHASIS_OPEN[tag])
            return
        if tag in self._CODE_OPEN and self._in_pre == 0:
            self._buf.append(self._CODE_OPEN[tag])
            return
        if tag in self._BLOCK_TAGS:
            self._buf.append("\n\n")
            return
        # Unknown / inline / structural tag → no markup; data passes
        # through.

    def _flush_link(self, *, drop_empty: bool = False) -> None:
        """v1.4.5 R1 MINOR #4 helper: emit the currently-open link
        markup to _buf and reset the collection state. Called when
        a block tag opens inside <a> (drop_empty=True so we don't
        emit a stray `<href>` BEFORE the heading text has been
        collected — that text is about to land at body level under
        the heading marker), OR on </a> (drop_empty=False, preserves
        the legacy `<href>` for href-only-no-text anchors).

        Idempotent — no-op if no link is currently open."""
        if self._link_text_buf is None:
            return
        text = "".join(self._link_text_buf).strip()
        href = self._link_href or ""
        if text and href:
            self._buf.append(f"[{text}]({href})")
        elif text:
            self._buf.append(text)
        elif href and not drop_empty:
            self._buf.append(f"<{href}>")
        # drop_empty=True + (no text) + (any href) → emit nothing.
        # The block tag's content lands at body level immediately
        # after this flush.
        self._link_href = None
        self._link_text_buf = None

    def _on_end(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("script", "style"):
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if self._skip_depth > 0:
            return
        if tag == "title":
            if self._in_title > 0:
                self._in_title -= 1
            return
        # v1.4.5 R1 MINOR #5 fix: same gate as _on_start — close-tags
        # inside <title> must not emit body-level markup.
        if self._in_title > 0:
            return
        if tag == "pre":
            if self._in_pre > 0:
                self._in_pre -= 1
                self._buf.append("\n```\n\n")
            return
        if tag in self._HEADING_TAGS:
            self._buf.append("\n")
            self._heading_level = 0
            return
        if tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self._buf.append("\n")
            return
        if tag == "li":
            return
        if tag == "a":
            self._flush_link()
            return
        if tag in self._EMPHASIS_OPEN and self._heading_level == 0:
            self._buf.append(self._EMPHASIS_OPEN[tag])
            return
        if tag in self._CODE_OPEN and self._in_pre == 0:
            self._buf.append(self._CODE_OPEN[tag])
            return
        if tag in self._BLOCK_TAGS:
            self._buf.append("\n\n")
            return

    def _on_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title > 0:
            # v1.4.5 R1 MINOR #5 fix: concat raw (don't strip per
            # fragment) so inter-tag whitespace is preserved
            # (`<title>A <b>B</b> C</title>` → "A B C", not "AB C").
            # render() does the final whitespace-normalize + strip.
            if self._title_text is None:
                self._title_text = data
            else:
                self._title_text = self._title_text + data
            return
        if self._in_pre > 0:
            self._buf.append(data)
            return
        # Capture link text into a sub-buffer so we can render
        # `[text](href)` on </a>.
        if self._link_text_buf is not None:
            self._link_text_buf.append(data)
            return
        # Collapse whitespace within text runs (multiple spaces /
        # tabs / newlines → single space). Markdown structure relies
        # on the explicit `\n` injections from tag handlers.
        normalized = re.sub(r"[ \t\r\n]+", " ", data)
        if normalized.strip():
            self._buf.append(normalized)
        elif self._buf and not self._buf[-1].endswith((" ", "\n")):
            # Preserve a single space between adjacent inline runs.
            self._buf.append(" ")

    def render(self) -> str:
        body = "".join(self._buf)
        # Inject <title> as H1 if no <h1> present in body.
        # v1.4.5 R1 MINOR #5 fix: normalize collected title here so
        # inter-tag whitespace is preserved across fragment boundaries
        # but multi-space runs collapse to single space (clean H1).
        if self._title_text and not self._has_h1:
            normalized_title = re.sub(
                r"[ \t\r\n]+", " ", self._title_text
            ).strip()
            if normalized_title:
                body = f"# {normalized_title}\n\n" + body
        # Collapse runs of 3+ blank lines down to a single blank line
        # (markdown convention — paragraph break is exactly one blank).
        body = re.sub(r"\n{3,}", "\n\n", body)
        # Strip leading/trailing whitespace; ensure trailing newline.
        return body.strip() + "\n"


def _convert_eml(path: Path) -> str:
    """Convert an .eml (RFC 822 / MIME) email into the unified
    bsa-materials email markdown shape.

    v1.4.6 (closes lifecycle review rec #3 second half). Stdlib only
    (`email` + `email.policy.default` for MIME header decoding).

    Output:
      ## Email metadata
      - **From**: ...
      - **To**: ...
      - **Cc**: ... (omitted when empty)
      - **Date**: ...
      - **Subject**: ...

      ## Body
      <text/plain part if present, else text/html via _HTMLToMarkdown>

      ## Attachments
      - filename (mime-type, N bytes)
      - ... (omitted entirely when no attachments)

    Body part selection: prefer text/plain (operator-authored), fall
    back to text/html (rendered). Other body types degrade to a
    `[unsupported body content-type: X]` placeholder so the row in
    the manifest still has a meaningful body excerpt.

    Headers are decoded via `email.policy.default` which handles
    RFC 2047 `=?UTF-8?B?...?=` / `=?ISO-8859-1?Q?...?=` encoded-word
    syntax. Date is preserved as the raw header (no normalization)
    so freshness_audit can parse it via dateutil if installed.

    Attachments are LISTED ONLY (filename + content-type + size).
    The bytes are NOT extracted — operator opts in by manually
    extracting via their email client if the attachment IS the
    evidence. Default-off matches --keep-raw's storage discipline."""
    import email as _email_mod
    from email.policy import default as _email_policy
    try:
        with path.open("rb") as fh:
            msg = _email_mod.message_from_binary_file(
                fh, policy=_email_policy
            )
    except Exception as exc:
        raise ConversionFailed(
            f"email parser failed on {path.name}: {exc}"
        ) from exc
    return _render_email_markdown(msg, path.name)


def _convert_msg(path: Path) -> str:
    """Convert an Outlook .msg (Compound File Binary Format) email
    into the unified bsa-materials email markdown shape.

    v1.4.6. `extract-msg` lazy-imported (matches pdf/docx/pptx
    pattern); raises `ConversionUnavailable` when missing.

    Re-uses the same metadata/body/attachments output shape as
    `_convert_eml` so downstream tooling sees ONE schema regardless
    of which client exported the email. Body part selection prefers
    plain over html (matches eml convention)."""
    try:
        import extract_msg  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ConversionUnavailable(
            "extract-msg not installed. Install with `pip install "
            "extract-msg` to convert Outlook .msg files (or convert "
            "externally to .eml via your mail client and re-stage)."
        ) from exc
    try:
        msg = extract_msg.openMsg(str(path))
    except Exception as exc:
        raise ConversionFailed(
            f"extract-msg failed on {path.name}: {exc}"
        ) from exc
    # Build a minimal dict-shape compatible with _render_email_markdown's
    # consumer interface (header lookup + body part walk). We adapt
    # extract-msg's distinct attribute API to the email-module shape
    # so a single renderer covers both formats.
    # v1.4.6 R1 MAJOR #1 fix: wrap render-time exceptions so a
    # malformed .msg surfaces as ConversionFailed (matching the
    # cmd_materials per-file failure path) instead of escaping as
    # an arbitrary exception that aborts the whole batch.
    try:
        try:
            out = _render_email_markdown_from_msg(msg, path.name)
        except Exception as exc:
            raise ConversionFailed(
                f"extract-msg render failed on {path.name}: {exc}"
            ) from exc
    finally:
        try:
            msg.close()
        except Exception:
            pass
    return out


def _normalize_email_header_value(value: str) -> str:
    """Header / filename variant — collapses ALL line-breaks AND
    runs of whitespace into a single space. Used for `**From**:` etc.
    + attachment filenames where a multi-line value would spoof
    markdown structure."""
    if not value:
        return ""
    cleaned = re.sub(r"[\r\n\t ]+", " ", value)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _render_email_markdown(msg, source_name: str) -> str:
    """Shared renderer for stdlib `email.Message`. Returns the
    metadata + body + attachments markdown block."""
    parts: list[str] = ["## Email metadata", ""]
    # Stdlib email.policy.default returns Header objects whose str()
    # gives the decoded text. Empty header → empty string.
    header_lines: list[tuple[str, str]] = []
    for label, hdr in (
        ("From", "From"), ("To", "To"), ("Cc", "Cc"),
        ("Bcc", "Bcc"), ("Date", "Date"), ("Subject", "Subject"),
    ):
        raw = msg.get(hdr)
        if raw is None:
            continue
        text = _normalize_email_header_value(str(raw).strip())
        if text:
            header_lines.append((label, text))
    if not header_lines:
        # Defensive — at minimum we want SOMETHING in the metadata
        # block so downstream evidence-binding has anchors.
        header_lines.append(
            ("Source", _normalize_email_header_value(source_name))
        )
    for label, text in header_lines:
        parts.append(f"- **{label}**: {text}")
    parts.append("")

    # Body — walk MIME parts, prefer text/plain.
    plain_body: Optional[str] = None
    html_body: Optional[str] = None
    # v1.4.6 R1 MAJOR #3 tracking: list inline images (Content-
    # Disposition: inline + filename) so an image-only email's
    # staged body still records WHAT was attached, even if the
    # rendered HTML body collapses to nothing.
    attachments: list[tuple[str, str, int]] = []  # (filename, ctype, size)
    inline_media: list[tuple[str, str, int]] = []  # same shape
    for part in msg.walk():
        ctype = part.get_content_type()
        # Skip multipart containers (no leaf content).
        if part.is_multipart():
            continue
        disp = (part.get_content_disposition() or "").lower()
        fname = part.get_filename()
        # v1.4.6 R1 MAJOR #2 fix: a part with a filename + no
        # explicit "inline" disposition is an attachment regardless
        # of content-type. Real-world MIME like
        # `Content-Type: text/plain; name=note.txt` (no Content-
        # Disposition header) would otherwise be misclassified as
        # the email body, suppressing the actual body that follows.
        is_attachment = (
            disp == "attachment"
            or (fname and disp != "inline")
        )
        if is_attachment:
            try:
                payload = part.get_payload(decode=True) or b""
            except Exception:
                payload = b""
            attachments.append((fname or "(unnamed)", ctype, len(payload)))
            continue
        # v1.4.6 R1 MAJOR #3: inline media (image/*, application/*
        # with disposition=inline) tracked separately so they
        # appear in the attachments section with an [inline] marker.
        if disp == "inline" and not ctype.startswith("text/"):
            try:
                payload = part.get_payload(decode=True) or b""
            except Exception:
                payload = b""
            inline_media.append(
                (fname or f"(inline {ctype})", ctype, len(payload))
            )
            continue
        # Inline body parts (text/plain or text/html, no filename).
        if ctype == "text/plain" and plain_body is None:
            try:
                plain_body = part.get_content()
            except Exception:
                # Fallback for malformed MIME — get raw payload.
                payload = part.get_payload(decode=True) or b""
                plain_body = payload.decode("utf-8", errors="replace")
        elif ctype == "text/html" and html_body is None:
            try:
                html_body = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True) or b""
                html_body = payload.decode("utf-8", errors="replace")

    parts.append("## Body")
    parts.append("")
    rendered: Optional[str] = None
    if plain_body is not None and plain_body.strip():
        rendered = plain_body.rstrip()
    elif html_body is not None and html_body.strip():
        # v1.4.6 SYNERGY with v1.4.5: route html-body emails through
        # the same _HTMLToMarkdown converter the html extractor uses.
        # Single conversion path = consistent output regardless of
        # whether the analyst stages a standalone .html OR an email
        # with html body.
        h = _HTMLToMarkdown()
        h.feed(html_body)
        h.close()
        rendered_html = h.render().rstrip()
        # v1.4.6 R1 MAJOR #3 fix: if HTML rendered to empty (e.g.,
        # body was only `<img src="cid:...">`), fall through to the
        # placeholder so the staged file makes the empty-body
        # situation explicit. Inline media list (below) records
        # what WAS in the email even though the body collapsed.
        if rendered_html.strip():
            rendered = rendered_html
    if rendered is not None:
        parts.append(rendered)
    else:
        parts.append("_(no readable body — encrypted, malformed, or "
                     "empty multipart)_")
    parts.append("")

    # v1.4.6 R1 MAJOR #3 fix: combine attachments + inline_media into
    # a single Attachments section so an inline-image-only email
    # always has a record of WHAT it carried (4-tuple includes
    # is_inline flag for the [inline] marker).
    attach_rows: list[tuple[str, str, int, bool]] = [
        (fname, ctype, size, False) for fname, ctype, size in attachments
    ] + [
        (fname, ctype, size, True) for fname, ctype, size in inline_media
    ]
    if attach_rows:
        parts.append("## Attachments")
        parts.append("")
        for fname, ctype, size, is_inline in attach_rows:
            inline_tag = " [inline]" if is_inline else ""
            safe_fname = _normalize_email_header_value(fname)
            parts.append(
                f"- {safe_fname} ({ctype}, {size} bytes){inline_tag}"
            )
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _render_email_markdown_from_msg(msg, source_name: str) -> str:
    """Shared renderer for `extract_msg.Message`. Adapts the distinct
    attribute API to the same metadata/body/attachments output shape
    `_render_email_markdown` produces for stdlib email.Message."""
    parts: list[str] = ["## Email metadata", ""]
    header_lines: list[tuple[str, str]] = []
    for label, getter in (
        ("From", "sender"), ("To", "to"), ("Cc", "cc"),
        ("Date", "date"), ("Subject", "subject"),
    ):
        raw = getattr(msg, getter, None)
        if raw is None:
            continue
        # v1.4.6 R1 MINOR #2 fix: normalize embedded newlines /
        # tabs to single space so a malicious header can't spoof
        # extra markdown bullets/headings into the staged block.
        text = _normalize_email_header_value(str(raw).strip())
        if text:
            header_lines.append((label, text))
    if not header_lines:
        header_lines.append(
            ("Source", _normalize_email_header_value(source_name))
        )
    for label, text in header_lines:
        parts.append(f"- **{label}**: {text}")
    parts.append("")

    parts.append("## Body")
    parts.append("")
    body = (getattr(msg, "body", "") or "").strip()
    # v1.4.6 R1 MINOR #1 fix: utf-8-sig swallows a leading BOM.
    # extract-msg's htmlBody is documented as Optional[bytes]; some
    # Outlook versions emit a UTF-8 BOM at the top of the html part.
    # Without -sig, the BOM survives as a stray U+FEFF in the staged
    # markdown.
    html_body = (getattr(msg, "htmlBody", None) or b"")
    if isinstance(html_body, bytes):
        try:
            html_body = html_body.decode("utf-8-sig")
        except UnicodeDecodeError:
            html_body = html_body.decode("latin-1", errors="replace")
    if body:
        parts.append(body.rstrip())
    elif html_body and html_body.strip():
        h = _HTMLToMarkdown()
        h.feed(html_body)
        h.close()
        rendered_html = h.render().rstrip()
        # v1.4.6 R1 MAJOR #3 parity: empty-render → placeholder.
        if rendered_html.strip():
            parts.append(rendered_html)
        else:
            parts.append("_(no readable body — encrypted, malformed, or "
                         "empty)_")
    else:
        parts.append("_(no readable body — encrypted, malformed, or "
                     "empty)_")
    parts.append("")

    attachments = list(getattr(msg, "attachments", []) or [])
    if attachments:
        parts.append("## Attachments")
        parts.append("")
        for att in attachments:
            fname = (
                getattr(att, "longFilename", None)
                or getattr(att, "shortFilename", None)
                or "(unnamed)"
            )
            data = getattr(att, "data", b"") or b""
            size = len(data) if isinstance(data, (bytes, bytearray)) else 0
            # extract-msg attachments don't carry MIME content-type
            # directly; we synthesize from the file extension.
            ext = ""
            if fname and "." in fname:
                ext = fname.rsplit(".", 1)[-1].lower()
            ctype_guess = {
                "pdf": "application/pdf",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "gif": "image/gif",
                "txt": "text/plain",
                "csv": "text/csv",
            }.get(ext, "application/octet-stream")
            safe_fname = _normalize_email_header_value(fname)
            parts.append(f"- {safe_fname} ({ctype_guess}, {size} bytes)")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _read_text(path: Path) -> str:
    """Read MD/TXT verbatim with a tolerant encoding fallback."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Fall back to latin-1 so we never crash on byte-stream input.
        return path.read_text(encoding="latin-1")


def _convert_xlsx(path: Path, max_rows_per_table: int = _DEFAULT_MAX_ROWS_PER_TABLE) -> str:
    """Extract every sheet from an XLSX as a markdown table.

    v1.4.1 (closes the call-data staging gap). One H2 per sheet; rows
    rendered as pipe-delimited markdown with the first row treated as
    the header. Empty cells become `—` so the column count stays
    aligned. When a sheet exceeds `max_rows_per_table`, the tail is
    dropped with a `[truncated: N rows shown of M total]` footer so
    the operator knows to either raise the cap or sample the source.

    Same error contract as `_convert_pdf` / `_convert_docx`:
    `ConversionUnavailable` if openpyxl is not installed,
    `ConversionFailed` for per-file errors (corrupt workbook, etc.).

    Skips:
      * Hidden sheets (`sheet_state in {hidden, veryHidden}`) —
        spreadsheet authors typically use these for staging /
        scratch and the content rarely belongs in the analytical
        record. Visible flag carries provenance intent.
      * Empty rows at the END of a sheet (openpyxl reports the
        full max_row even when most rows are blank — typical
        artifact of "I clicked row 1000 once" workbooks).
    """
    try:
        from openpyxl import load_workbook  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ConversionUnavailable(
            "openpyxl not installed. Install with `pip install openpyxl` "
            "to convert XLSX (or convert externally to CSV / MD)."
        ) from exc
    try:
        wb = load_workbook(str(path), read_only=True, data_only=True)
    except Exception as exc:
        raise ConversionFailed(f"openpyxl failed on {path.name}: {exc}") from exc
    parts: list[str] = []
    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            if getattr(ws, "sheet_state", "visible") != "visible":
                continue  # skip hidden / veryHidden
            # Materialize rows to find the real last-non-empty row.
            rows: list[list[str]] = []
            for raw_row in ws.iter_rows(values_only=True):
                row = [
                    "" if cell is None else str(cell).strip()
                    for cell in raw_row
                ]
                rows.append(row)
            # Trim trailing all-blank rows.
            while rows and all(not c for c in rows[-1]):
                rows.pop()
            if not rows:
                continue  # empty sheet — skip
            total_rows = len(rows)
            truncated = False
            if total_rows > max_rows_per_table:
                rows = rows[:max_rows_per_table]
                truncated = True
            parts.append(f"## Sheet: {sheet_name}\n")
            parts.append(_render_markdown_table(rows))
            if truncated:
                parts.append(
                    f"\n_[truncated: showing first {max_rows_per_table} "
                    f"row(s) of {total_rows} total; raise "
                    f"`--max-rows-per-table` or sample externally to see more]_\n"
                )
            parts.append("")
    finally:
        wb.close()
    if not parts:
        return "_[xlsx had no visible sheets with content]_\n"
    return "\n".join(parts).strip() + "\n"


def _convert_csv(path: Path, max_rows: int = _DEFAULT_MAX_ROWS_PER_TABLE) -> str:
    """Extract a CSV as a single markdown table — STREAMING.

    v1.4.1 (closes the call-data staging gap). Delimiter `,`. See
    `_convert_delimited_table` for the shared streaming + encoding-
    fallback + truncation implementation."""
    return _convert_delimited_table(path, max_rows=max_rows, delimiter=",", label="csv")


def _convert_tsv(path: Path, max_rows: int = _DEFAULT_MAX_ROWS_PER_TABLE) -> str:
    """Extract a TSV (tab-separated values) as a single markdown table.

    v1.4.2 (closes the call-data tsv gap — `process_steps_flat.tsv`
    etc.). Same streaming + encoding-fallback + truncation semantics
    as `_convert_csv`; only the delimiter differs (`\\t` vs `,`)."""
    return _convert_delimited_table(path, max_rows=max_rows, delimiter="\t", label="tsv")


def _convert_delimited_table(
    path: Path,
    *,
    max_rows: int,
    delimiter: str,
    label: str,
) -> str:
    """Shared streaming reader for csv (delimiter=`,`) and tsv
    (delimiter=`\\t`).

    v1.4.1 R1 fix: STREAMING. Initial v1.4.1 implementation used
    `path.read_text()` + `list(reader)` which materialized the
    entire file in RAM before applying `max_rows`. A 30MB call-data
    table would then expand to 100-200MB Python objects (string
    overhead) and stall the staging step. Post-fix: open the file
    handle, iterate rows lazily, keep only the header + first
    `max_rows` data rows in memory, count the rest without
    storing. Truncation footer reports the EXACT total row count.

    v1.4.1 R2 fix: encoding fallback is a streaming try/retry over
    `("utf-8", "latin-1")`. UTF-8 attempt fails fast on any invalid
    byte mid-stream; on failure, accumulators (header, rows_kept,
    total_data_rows) are reset and retry runs with latin-1 (which
    maps every byte 0-255 and cannot raise UnicodeDecodeError).

    Stdlib `csv` only (no pandas dep). Honors RFC4180 quoting.
    `label` controls the label that appears in error messages /
    truncation footer (e.g., "csv" vs "tsv")."""
    import csv as _csv

    # Encoding fallback: try UTF-8 first, fall back to latin-1 on
    # UnicodeDecodeError ANYWHERE in the stream. v1.4.1 R2 fix
    # (Codex MAJOR): the previous implementation probed only the
    # first 4 KB and chose encoding from that probe; CSVs whose
    # first invalid UTF-8 byte appeared after byte 4096 then
    # crashed with UnicodeDecodeError mid-iteration — no fallback
    # because the probe had already passed. Post-fix: streaming
    # try/retry pattern. UTF-8 attempt fails fast on invalid byte
    # (mid-stream); on failure we restart the iteration with
    # latin-1 (which maps every byte 0-255, so it cannot raise
    # UnicodeDecodeError). The retry costs one extra full file
    # read in the rare invalid-UTF-8 case; the common UTF-8 case
    # pays no extra cost.
    header: list[str] | None = None
    rows_kept: list[list[str]] = []
    total_data_rows = 0
    encoding_used = "utf-8"
    for encoding in ("utf-8", "latin-1"):
        # Reset accumulators on retry.
        header = None
        rows_kept = []
        total_data_rows = 0
        try:
            with path.open(encoding=encoding, newline="") as fh:
                reader = _csv.reader(fh, delimiter=delimiter)
                for i, raw_row in enumerate(reader):
                    row = [
                        ("" if c is None else str(c).strip())
                        for c in raw_row
                    ]
                    if i == 0:
                        header = row
                        continue
                    total_data_rows += 1
                    if len(rows_kept) < max_rows:
                        rows_kept.append(row)
                    # else: continue counting but don't store (RAM cap).
            encoding_used = encoding
            break  # made it through without UnicodeDecodeError
        except UnicodeDecodeError:
            if encoding == "latin-1":
                # Latin-1 maps every byte; this branch should be
                # unreachable. If we hit it, the file is genuinely
                # corrupted at the OS level (read returned data
                # that wasn't a byte stream — extremely unusual).
                raise ConversionFailed(
                    f"{label} encoding fallback exhausted for {path.name}: "
                    f"both UTF-8 and latin-1 raised UnicodeDecodeError "
                    f"(possible filesystem-level corruption)"
                )
            # else: try latin-1 next iteration
            continue
        except _csv.Error as exc:
            raise ConversionFailed(
                f"{label} parse failed on {path.name}: {exc}"
            ) from exc
        except OSError as exc:
            raise ConversionFailed(
                f"{label} read failed on {path.name}: {exc}"
            ) from exc

    if header is None:
        return f"_[{label} was empty]_\n"

    # Normalize column count against header (defensive against
    # ragged rows). Only the rows we KEPT need normalization.
    header_len = len(header)
    normalized: list[list[str]] = [header]
    for row in rows_kept:
        if len(row) < header_len:
            row = row + [""] * (header_len - len(row))
        # else: keep ragged extras; markdown render aligns off but
        # operator sees the data.
        normalized.append(row)

    body = _render_markdown_table(normalized)
    parts = [body]
    if encoding_used != "utf-8":
        parts.append(
            f"\n_[note: read with {encoding_used} fallback — original "
            f"file is not valid UTF-8]_\n"
        )
    truncated = total_data_rows > max_rows
    if truncated:
        parts.append(
            f"\n_[truncated: showing first {max_rows} data row(s) of "
            f"{total_data_rows} total; raise `--max-rows-per-table` or "
            f"sample externally to see more]_\n"
        )
    return "\n".join(parts).strip() + "\n"


def _convert_json(path: Path, max_chars: int = 200_000) -> str:
    """Extract a JSON file as a structure summary + pretty-printed body.

    v1.4.2 (closes the json gap — voicescribe traces, explorer
    payloads, process-graph dumps). Output shape:

        ## Structure summary
        - top-level type: object
        - top-level keys (count: N): key1, key2, key3, ...
        OR
        - top-level type: array
        - top-level items (count: N)

        ```json
        { ...pretty-printed with indent=2... }
        ```

    The structure summary helps an analyst grep for relevant top-
    level keys before diving into the full body. The body is wrapped
    in a ```json``` code fence so markdown renderers display it as
    literal JSON without trying to interpret special chars.

    Truncation: if the pretty-printed body exceeds `max_chars`, the
    body is cut off at that boundary with a `[truncated]` footer
    note pointing at `--max-json-chars` as the operator's lever.
    Default cap = 200_000 chars (~200 KB pretty-printed body) —
    enough for typical voicescribe traces / explorer payloads;
    big enough that operators won't hit it by accident, small enough
    that a 50MB minified json doesn't expand to a 500MB md file.

    Stdlib `json` only. Honors UTF-8 by default; on UnicodeDecodeError
    falls back to latin-1 (matches csv/tsv contract). On JSON parse
    failure, raises ConversionFailed (not a "graceful degradation"
    case — a malformed json file SHOULD surface as a failed staging
    so the operator fixes it before the pipeline ingests garbage).
    """
    import json as _json

    encoding_used = "utf-8"
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
        encoding_used = "latin-1"
    except OSError as exc:
        raise ConversionFailed(f"json read failed on {path.name}: {exc}") from exc

    if not text.strip():
        return "_[json was empty]_\n"

    try:
        doc = _json.loads(text)
    except _json.JSONDecodeError as exc:
        raise ConversionFailed(
            f"json parse failed on {path.name}: {exc}"
        ) from exc

    # Structure summary — operator-grep hint before the body.
    summary_lines: list[str] = ["## Structure summary", ""]
    if isinstance(doc, dict):
        keys = list(doc.keys())
        summary_lines.append(f"- top-level type: object")
        # Cap displayed key list at 50 to keep the summary readable;
        # the count tells the analyst there's more if any.
        shown = keys[:50]
        suffix = f" (showing first 50 of {len(keys)})" if len(keys) > 50 else ""
        summary_lines.append(
            f"- top-level keys (count: {len(keys)}){suffix}: "
            + ", ".join(repr(k) for k in shown)
        )
    elif isinstance(doc, list):
        summary_lines.append(f"- top-level type: array")
        summary_lines.append(f"- top-level items (count: {len(doc)})")
        # Sample the first item — shape depends on its type.
        # v1.4.2 R1 fix (Codex MINOR): pre-fix only emitted a sample
        # when the first item was a dict; arrays of scalars (e.g.
        # `[1, 2, 3]` event timestamps) and arrays of arrays (e.g.
        # `[[a, b], [c, d]]` adjacency-matrix style) got count-only
        # summaries. Operator grepping for "what's in this array"
        # had to scroll into the body. Now sample EVERY non-empty
        # array: dict → first 20 keys, list → length, scalar →
        # type + value preview.
        if doc:
            first = doc[0]
            if isinstance(first, dict):
                sample_keys = list(first.keys())[:20]
                summary_lines.append(
                    f"- first-item keys (sample): "
                    + ", ".join(repr(k) for k in sample_keys)
                )
            elif isinstance(first, list):
                summary_lines.append(
                    f"- first-item type: array (length: {len(first)})"
                )
            else:
                summary_lines.append(
                    f"- first-item type: {type(first).__name__}, "
                    f"value preview: {repr(first)[:100]}"
                )
    else:
        # Scalar (string, number, bool, null) at the root.
        summary_lines.append(f"- top-level type: {type(doc).__name__}")
        summary_lines.append(f"- value preview: {repr(doc)[:200]}")

    summary = "\n".join(summary_lines) + "\n"

    # Pretty-printed body wrapped in a ```json``` fence — STREAMING.
    # v1.4.2 R1 fix (Codex MAJOR): pre-fix `_json.dumps(...)` built
    # the FULL pretty-printed string in memory (e.g., a 50 MB minified
    # json → ~200 MB Python string overhead) BEFORE the truncation
    # check fired. The advertised --max-json-chars safety guarantee
    # was false: it bounded the OUTPUT but not the peak ALLOCATION.
    # Post-fix: iterencode chunks lazily, accumulate until max_chars
    # is reached, stop. Memory peak now bounded by max_chars + one
    # chunk's size (typically a few KB). The encoder still walks the
    # full doc tree, but doesn't allocate the rendered string for
    # the parts past the cap.
    encoder = _json.JSONEncoder(indent=2, ensure_ascii=False)
    body_chunks: list[str] = []
    total_len = 0
    truncated = False
    for chunk in encoder.iterencode(doc):
        chunk_len = len(chunk)
        if total_len + chunk_len > max_chars:
            # Partial chunk: take just enough to hit the cap exactly.
            remaining = max_chars - total_len
            if remaining > 0:
                body_chunks.append(chunk[:remaining])
            truncated = True
            break
        body_chunks.append(chunk)
        total_len += chunk_len
    body = "".join(body_chunks)
    fenced = "```json\n" + body + "\n```\n"

    parts = [summary, fenced]
    if encoding_used != "utf-8":
        parts.append(
            f"\n_[note: read with {encoding_used} fallback — original "
            f"file is not valid UTF-8]_\n"
        )
    if truncated:
        parts.append(
            f"\n_[truncated: showing first {max_chars} chars of the "
            f"pretty-printed body; raise `--max-json-chars` or sample "
            f"externally to see more]_\n"
        )
    return "\n".join(parts).strip() + "\n"


def _render_markdown_table(rows: list[list[str]]) -> str:
    """Render a list-of-rows (first row is header) as a pipe-delimited
    markdown table. Empty cells become `—` for visual alignment;
    pipe characters in cells are escaped to `\\|` so they don't break
    the table parser. Newlines collapsed to `<br>` (markdown tables
    can't span multiple lines).

    v1.4.1 R1 fix (Codex MINOR): preserve cells that contain LITERAL
    `<br>` text. Naive `.replace("\\n", "<br>")` would make literal
    source `<br>` indistinguishable from injected line-break tags
    after staging — fidelity loss against the operator's intent.
    Pre-escape `<` and `>` to `&lt;` / `&gt;` BEFORE the newline
    collapse so source angle-brackets become entity-encoded text
    (still readable; preserved literally) and our injected `<br>`
    stays the only literal `<br>` in the output.

    Preserves original column count even on ragged rows by padding /
    letting overflow.
    """
    if not rows:
        return ""

    def _escape_cell(c: str) -> str:
        # Order matters: escape angle-brackets BEFORE injecting <br>,
        # otherwise the injected <br> would itself get escaped.
        out = (
            c.replace("|", "\\|")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace("\n", "<br>")
        )
        return out if out else "—"

    header = rows[0]
    width = len(header)
    out: list[str] = []
    out.append("| " + " | ".join(_escape_cell(c) for c in header) + " |")
    out.append("|" + "|".join(["---"] * width) + "|")
    for row in rows[1:]:
        # Truncate or pad to match header width.
        if len(row) < width:
            row = row + [""] * (width - len(row))
        elif len(row) > width:
            row = row[:width]
        out.append("| " + " | ".join(_escape_cell(c) for c in row) + " |")
    return "\n".join(out)


def _classify(path: Path) -> Optional[str]:
    """Return kind ('pdf' | 'docx' | 'text') or None if unsupported."""
    return _EXT_TO_KIND.get(path.suffix.lower())


def _scan_source_dir(
    src_dir: Path, recursive: bool,
    max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
) -> tuple[list[Path], list[Path], list[Path]]:
    """Walk src_dir; return (supported, skipped_unsupported, skipped_too_big).

    Sorted for deterministic ordering. Hidden files / dirs (leading
    dot) are skipped — we don't want .DS_Store or .git to land in
    inputs/. Symlinked directories are NEVER followed (Codex round-1
    HIGH: a `src/a -> ../src` loop would recurse forever and could
    escape the requested src tree). Symlinked FILES are honored
    because users legitimately drop `ln -s ~/Drive/foo.pdf src/`
    when staging from a synced cloud folder.

    v1.4.1: `max_file_bytes` is now a CLI-overridable parameter
    (was a hard `_DEFAULT_MAX_FILE_BYTES` constant). Caller threads
    `args.max_mb * 1024 * 1024` from `cmd_materials`.
    """
    supported: list[Path] = []
    unsupported: list[Path] = []
    too_big: list[Path] = []

    def _walk(d: Path) -> None:
        for entry in sorted(d.iterdir(), key=lambda p: p.name):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                if recursive and not entry.is_symlink():
                    _walk(entry)
                continue
            if not entry.is_file():
                continue
            try:
                size = entry.stat().st_size
            except OSError:
                continue
            if size > max_file_bytes:
                too_big.append(entry)
                continue
            kind = _classify(entry)
            if kind is None:
                unsupported.append(entry)
            else:
                supported.append(entry)

    if src_dir.is_dir():
        _walk(src_dir)
    return supported, unsupported, too_big


def _check_write_containment(
    stage1_dir: Path, inputs_dir: Path, manifest_path: Path
) -> Optional[str]:
    """Verify the planned write surface is inside the workspace tree.

    Returns None if safe; an error message string otherwise. The caller
    surfaces that as exit-code-2 + stderr.

    Specifically, refuses to proceed if:
      (1) Any of `analysis/`, `proposals/`, `stage1/`, `inputs/` is a
          symlink — even if its target is currently inside the
          workspace, a future symlink swap would silently redirect
          writes. Defense in depth.
      (2) The resolved staging dir does not start with the resolved
          workspace root — e.g., `analysis/ -> /tmp/elsewhere`.
    """
    # (1) Walk up the parents from inputs_dir to the workspace root,
    # checking each is a real directory (not a symlink).
    suspicious_links: list[Path] = []
    chain = [inputs_dir, stage1_dir, stage1_dir.parent, stage1_dir.parent.parent]
    # chain = [inputs/, stage1/, proposals/, analysis/]
    for p in chain:
        if p.is_symlink():
            suspicious_links.append(p)
    if suspicious_links:
        names = ", ".join(str(s) for s in suspicious_links)
        return (
            f"refusing to write: workspace path contains symlink(s) — "
            f"{names}. Re-create as a real directory (mkdir) to use "
            f"`bsa materials --commit`."
        )
    # (2) Resolve the staging dir IF it exists; if not, resolve its
    # nearest existing parent to confirm the eventual mkdir lands
    # inside the workspace.
    workspace_root = stage1_dir.parent.parent.parent  # analysis/'s parent
    workspace_resolved = workspace_root.resolve()
    # Pick the first existing ancestor; resolve() on a non-existent
    # path is fine on POSIX but the symlink check above handles the
    # interesting cases. We just need a sanity check here.
    probe = stage1_dir
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        probe_resolved = probe.resolve()
    except OSError as exc:
        return f"failed to resolve staging path {probe}: {exc}"
    try:
        probe_resolved.relative_to(workspace_resolved)
    except ValueError:
        return (
            f"refusing to write: resolved staging path {probe_resolved} "
            f"escapes workspace root {workspace_resolved}. Likely a "
            f"symlinked directory pointing outside the workspace."
        )
    return None


# Provenance comment we embed at the top of every staged input file.
# Lets us recover the original Origin name from a staged file's
# content alone (manifest-deleted recovery + slug-collision
# disambiguation). Format intentionally narrow so the regex below
# matches exactly.
_PROVENANCE_COMMENT_RE = re.compile(
    r"<!-- bsa materials: staged from (?P<orig>.+?) "
    r"\(kind=(?P<kind>[a-z]+)\); SourceID=(?P<sid>[A-Z0-9\-]+) -->"
)


def _read_staged_provenance(staged_md: Path) -> Optional[str]:
    """Return the original `Origin` recorded in the provenance comment
    at the top of a staged input file, or None if absent / unreadable.
    Used to disambiguate slug collisions: if two source files
    produce the same slug (e.g., 40-char truncation), we look at the
    existing staged file's provenance to decide whether the current
    src is the SAME source (truly already staged → skip) or a
    DIFFERENT source that happens to slug-collide (allocate a fresh
    slug variant → no false-positive skip)."""
    try:
        head = staged_md.read_text(encoding="utf-8", errors="ignore")[:512]
    except OSError:
        return None
    m = _PROVENANCE_COMMENT_RE.search(head)
    return m.group("orig") if m else None


def _existing_origins(manifest_path: Path) -> set[str]:
    """Return the set of `Origin` values already recorded in
    source_manifest.csv. Used to detect "this source was already
    staged in a prior run" and skip it on re-invocation, so
    `bsa materials <same-dir>` is idempotent.

    We parse with the stdlib csv module to handle quoted Origin
    values correctly (the manifest is RFC4180-shaped per the
    A50 schema's column order)."""
    if not manifest_path.is_file():
        return set()
    import csv
    out: set[str] = set()
    try:
        with manifest_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                origin = (row.get("Origin") or "").strip()
                if origin:
                    out.add(origin)
    except (OSError, csv.Error):
        pass
    return out


def _existing_origin_index(manifest_path: Path) -> dict[str, dict[str, str]]:
    """Map Origin → {SourceID, ContentHash, OriginalBytes,
    OriginalMtimeUtc, slug} for every row in the manifest. Used by
    `_plan_conversions` in --restage-changed mode to look up an
    existing row's SID + stored hash without re-reading the manifest.

    Tolerant of missing optional columns (manifests authored before
    v1.4.4 simply yield empty hash fields). Tolerant of read errors
    (returns empty dict). The slug field is derived from the staged
    file's name so callers can locate the existing target without
    re-running _slugify (which can drift if the slug-derivation
    algorithm changes between versions)."""
    out: dict[str, dict[str, str]] = {}
    if not manifest_path.is_file():
        return out
    import csv as _csv
    try:
        with manifest_path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as fh:
            reader = _csv.DictReader(fh)
            for row in reader:
                origin = (row.get("Origin") or "").strip()
                sid = (row.get("SourceID") or "").strip()
                if not origin or not sid:
                    continue
                out[origin] = {
                    "SourceID": sid,
                    "ContentHash": (row.get("ContentHash") or "").strip(),
                    "OriginalBytes": (row.get("OriginalBytes") or "").strip(),
                    "OriginalMtimeUtc": (row.get("OriginalMtimeUtc") or "").strip(),
                }
    except (OSError, _csv.Error):
        pass
    # Augment with slug-from-disk so caller can locate the existing
    # target without re-running _slugify (slug algorithm may drift
    # between plugin versions; we trust on-disk shape).
    inputs_dir = manifest_path.parent / "inputs"
    if inputs_dir.is_dir():
        slug_pat = re.compile(r"^source_(\d{3,})_(.+)\.md$")
        sid_to_slug: dict[str, str] = {}
        for f in inputs_dir.iterdir():
            m = slug_pat.match(f.name)
            if m and f.is_file():
                sid_to_slug[f"S-{m.group(1)}"] = m.group(2)
        for entry in out.values():
            entry["slug"] = sid_to_slug.get(entry["SourceID"], "")
    return out


def _plan_conversions(
    src_files: list[Path],
    inputs_dir: Path,
    manifest_path: Path,
    src_dir_root: Path,
    force: bool,
    *,
    restage_changed: bool = False,
) -> list[SourcePlan]:
    """Build a list of SourcePlan, assigning fresh source IDs.

    Idempotency is enforced TWO ways (both gated by --force):
      1. Origin-based: if the source file's path-relative-to-src_dir
         already appears as an Origin in source_manifest.csv, skip.
         This is the primary check — re-running `bsa materials` on
         the same input directory must NOT duplicate-stage files.
      2. Target-based: if the would-be target file
         (source_NNN_<slug>.md) already exists in inputs/, skip.
         Catches the edge case where the manifest was deleted but
         input files remain.
    """
    plans: list[SourcePlan] = []
    next_id = _next_source_id(inputs_dir, manifest_path)
    already_staged = _existing_origins(manifest_path)
    # v1.4.4 --restage-changed: load Origin → {SID, ContentHash, slug}
    # so we can look up the existing row + decide skip-vs-restage based
    # on hash comparison.
    origin_index: dict[str, dict[str, str]] = (
        _existing_origin_index(manifest_path) if restage_changed else {}
    )
    # Slug→existing-path map for the slug-backstop: if the manifest
    # was deleted but old `source_NNN_<slug>.md` files remain, we
    # MUST detect those by slug. Round-2 fix: when the slug matches,
    # consult the file's provenance comment to disambiguate "same
    # source, truly already staged" from "different source that
    # happens to slug-collide" (slug truncation at 40 chars or
    # heavy non-ASCII normalization can produce collisions).
    existing_by_slug: dict[str, Path] = {}
    if inputs_dir.is_dir():
        # v1.4.3 R2 fix: \d{3,} for consistency with staging/recovery.
        slug_pat = re.compile(r"^source_\d{3,}_(.+)\.md$")
        for f in inputs_dir.iterdir():
            m = slug_pat.match(f.name)
            if m:
                existing_by_slug.setdefault(m.group(1), f)
    # Reserve in-batch slugs so two src files in the SAME run don't
    # both try to claim source_NNN_<slug>.md (they'd race + clobber).
    reserved_slugs: set[str] = set(existing_by_slug.keys())
    for src in src_files:
        kind = _classify(src) or "text"
        slug = _slugify(src.stem)
        # Compute the same Origin string the manifest writer would
        # produce, for the idempotency comparison.
        try:
            origin_rel = str(src.relative_to(src_dir_root))
        except ValueError:
            origin_rel = str(src)

        # --- Primary idempotency check: Origin in manifest. -----------
        if origin_rel in already_staged and not force:
            # v1.4.4: in --restage-changed mode, this is the BRANCH
            # POINT — compare current src hash to manifest's stored
            # hash. Same hash → skipped(unchanged). Different hash →
            # restage with the existing SID + target slug.
            if restage_changed and origin_rel in origin_index:
                existing = origin_index[origin_rel]
                stored_hash = existing.get("ContentHash") or ""
                try:
                    current_hash, current_size, current_mtime = (
                        _file_metadata(src)
                    )
                except OSError as exc:
                    plans.append(SourcePlan(
                        src=src, kind=kind, target=inputs_dir / "_unreadable",
                        source_id=existing.get("SourceID", "S-???"),
                        origin_rel=origin_rel,
                        skipped_reason=f"unreadable for hash compare: {exc}",
                    ))
                    continue
                if stored_hash and stored_hash == current_hash:
                    # Unchanged — skip cleanly. Use existing SID +
                    # slug to keep the displayed plan readable.
                    existing_slug = existing.get("slug") or slug
                    sid = existing["SourceID"]
                    sid_digits = sid.removeprefix("S-")
                    target = (
                        inputs_dir
                        / f"source_{sid_digits}_{existing_slug}.md"
                    )
                    plans.append(SourcePlan(
                        src=src, kind=kind, target=target, source_id=sid,
                        origin_rel=origin_rel,
                        skipped_reason=(
                            "unchanged (ContentHash matches manifest); "
                            "skipping under --restage-changed"
                        ),
                        content_hash=current_hash,
                        original_bytes=current_size,
                        original_mtime_utc=current_mtime,
                    ))
                    continue
                # Different hash (OR no stored hash to compare against)
                # → re-stage. Use existing SID + slug; overwrite target.
                existing_slug = existing.get("slug") or slug
                sid = existing["SourceID"]
                sid_digits = sid.removeprefix("S-")
                target = (
                    inputs_dir
                    / f"source_{sid_digits}_{existing_slug}.md"
                )
                plans.append(SourcePlan(
                    src=src, kind=kind, target=target, source_id=sid,
                    origin_rel=origin_rel,
                    skipped_reason=None,
                    restage=True,
                    content_hash=current_hash,
                    original_bytes=current_size,
                    original_mtime_utc=current_mtime,
                ))
                continue
            # Default behavior (no restage-changed): skip with message.
            sid_num = next_id
            sid = f"S-{sid_num:03d}"
            target_name = f"source_{sid_num:03d}_{slug}.md"
            target = inputs_dir / target_name
            plans.append(SourcePlan(
                src=src, kind=kind, target=target, source_id=sid,
                origin_rel=origin_rel,
                skipped_reason=(
                    f"already staged in source_manifest.csv "
                    f"(Origin={origin_rel!r}); pass --force to re-stage"
                ),
            ))
            continue

        # --- Slug-backstop with provenance disambiguation. ------------
        # If the slug already exists on disk, look at the existing
        # file's provenance comment to decide:
        #   - same Origin → truly already staged, skip (no false-pos)
        #   - different Origin → slug collision, allocate alt slug
        # Provenance is the canonical Origin (relative path), NOT
        # basename — round-3 fix: comparing basenames false-skipped
        # distinct nested files like team_a/foo.md vs team_b/foo.md.
        if slug in existing_by_slug and not force:
            existing_file = existing_by_slug[slug]
            existing_origin = _read_staged_provenance(existing_file)
            if existing_origin is not None and existing_origin == origin_rel:
                sid_num = next_id
                sid = f"S-{sid_num:03d}"
                target_name = f"source_{sid_num:03d}_{slug}.md"
                target = inputs_dir / target_name
                plans.append(SourcePlan(
                    src=src, kind=kind, target=target, source_id=sid,
                    origin_rel=origin_rel,
                    skipped_reason=(
                        f"input file with the same slug already staged at "
                        f"{existing_file.name} (provenance match); pass "
                        f"--force to re-stage"
                    ),
                ))
                continue
            # Slug collision but DIFFERENT source (or no provenance
            # to verify) → allocate a unique slug rather than silently
            # skip. Overwrite-safe: never touches the existing file.
            slug = _next_unique_slug(slug, reserved_slugs, src.stem)

        sid_num = next_id
        sid = f"S-{sid_num:03d}"
        target_name = f"source_{sid_num:03d}_{slug}.md"
        target = inputs_dir / target_name

        # --- Final backstop: exact target path collision (manifest +
        # slug both clean, but we're about to overwrite an in-tree file)
        if target.exists() and not force:
            plans.append(SourcePlan(
                src=src, kind=kind, target=target, source_id=sid,
                origin_rel=origin_rel,
                skipped_reason=(
                    f"target exists ({target.name}); pass --force to overwrite"
                ),
            ))
            continue

        plans.append(SourcePlan(
            src=src, kind=kind, target=target, source_id=sid,
            origin_rel=origin_rel, skipped_reason=None,
        ))
        reserved_slugs.add(slug)
        next_id += 1  # only burn an ID for plans we'll actually write
    return plans


def _next_unique_slug(base: str, reserved: set[str], stem: str) -> str:
    """Return `base` if free, else `base_<6char-hash>` based on the
    original stem (stable per-source). Guarantees uniqueness within
    the run AND independent of insertion order."""
    if base not in reserved:
        return base
    import hashlib
    suffix = hashlib.sha1(stem.encode("utf-8")).hexdigest()[:6]
    candidate = f"{base[:33]}_{suffix}"  # 33 + 1 + 6 = 40-char ceiling
    # In the unlikely event that the hashed slug also collides
    # (would require two files with identical stems and identical
    # 40-char base slugs — practically impossible), append a counter.
    n = 1
    final = candidate
    while final in reserved:
        n += 1
        final = f"{candidate}_{n}"
    return final


def _render_draft_manifest(
    plans: list[SourcePlan],
    src_dir_root: Path,
    *,
    include_effective_date: bool = False,
    include_hashes: bool = False,
) -> str:
    """Render a draft source_manifest.csv. ReliabilityTier defaults to
    T5 (most cautious) — the user MUST re-tag during /bsa-stage 1
    review. Notes column flags this clearly so the worker sees it.

    v1.2.16: when ``include_effective_date=True`` the rendered rows
    carry an empty ``EffectiveDate`` cell (and the header includes the
    column) so an append into an existing manifest that has already
    been backfilled with the v1.2.16 optional column doesn't
    misalign. The empty cell reads as 'n/a' in freshness_audit per
    the optional_order extension contract.

    v1.4.4: when ``include_hashes=True`` the rendered rows carry
    ``ContentHash`` (sha256 hex), ``OriginalBytes`` (raw size), and
    ``OriginalMtimeUtc`` (ISO-8601 UTC second) AFTER ``EffectiveDate``.
    Hashes are sourced from ``SourcePlan.content_hash`` etc., which
    cmd_materials populates per file at --commit time. Plans without
    populated hash fields fall back to empty cells — operator can
    re-stage with --restage-changed to backfill. ``include_hashes``
    implies ``include_effective_date`` (the new variant always carries
    EffectiveDate)."""
    if include_hashes:
        include_effective_date = True  # the hash header always carries EffectiveDate
    base = [
        "SourceID", "SourceType", "Title", "Origin", "AccessStatus",
        "ReliabilityTier", "Priority", "Language", "DateOrVersion",
    ]
    cols = base + (["EffectiveDate"] if include_effective_date else [])
    cols += (
        ["ContentHash", "OriginalBytes", "OriginalMtimeUtc"]
        if include_hashes else []
    )
    cols += ["Notes"]
    out = [",".join(cols)]
    today = _today_iso()
    for p in plans:
        if p.skipped_reason is not None:
            continue
        # SourceType heuristic: "interview" anywhere in the slug → interview_transcript.
        # v1.4.5: pptx → document (presentations); html → process_note
        # (web exports / Confluence pages tend to be procedural).
        # v1.4.6: eml/msg → email_thread (distinct evidence class —
        # stakeholder approvals, requirement clarifications, etc.).
        slug_lower = p.target.stem.lower()
        if "interview" in slug_lower or "transcript" in slug_lower:
            stype = "interview_transcript"
        elif p.kind in ("eml", "msg"):
            stype = "email_thread"
        elif p.kind in ("pdf", "docx", "pptx"):
            stype = "document"
        else:
            stype = "process_note"
        title = _csv_escape(p.src.stem)
        # Origin is canonical: same string used by both the manifest
        # row AND the staged file's provenance comment (see
        # _plan_conversions). origin_rel is set in the planner; we
        # only fall back to absolute path if planning code didn't
        # populate it (defensive — current callers always do).
        origin = _csv_escape(p.origin_rel or str(p.src))
        notes = (
            "auto-staged by `bsa materials`; ReliabilityTier defaulted to "
            "T5 — re-tag based on epistemic proximity per "
            "skills/bsa-evidence-intake/references/reliability_tier_spec.md "
            "before /bsa-promote"
        )
        base_row = [
            p.source_id, stype, title, origin, "readable",
            "T5", "medium", "en", today,
        ]
        # v1.2.16: empty EffectiveDate cell when the existing manifest
        # already carries the column. Operator backfills the value
        # row-by-row at the same review pass that retags ReliabilityTier.
        row = base_row + ([""] if include_effective_date else [])
        # v1.4.4: hash columns. Empty when the plan didn't populate
        # them (dry-run, skipped, or pre-v1.4.4 caller).
        if include_hashes:
            row += [
                p.content_hash or "",
                str(p.original_bytes) if p.original_bytes is not None else "",
                p.original_mtime_utc or "",
            ]
        row += [_csv_escape(notes)]
        out.append(",".join(row))
    return "\n".join(out) + "\n"


def _csv_escape(value: str) -> str:
    """Minimal RFC4180 CSV escape. We control the input shape so don't
    need a full csv.writer roundtrip."""
    if any(ch in value for ch in (",", '"', "\n", "\r")):
        return '"' + value.replace('"', '""') + '"'
    return value


def _today_iso() -> str:
    """ISO date for DateOrVersion column."""
    from datetime import date
    return date.today().isoformat()


def _bytes_human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 ** 2:.1f} MB"


# v1.4.4 (closes lifecycle review rec #2). Content hashing helpers.
# Streaming sha256 + (size, mtime) bundle so we can:
#   1. Detect when a re-staged source has changed (--restage-changed).
#   2. Persist a manifest row that downstream stages can audit against
#      the actual bytes (was the source modified after stage 1 froze
#      the manifest? — answers a long-standing audit question).
#   3. Optionally retain the original (pre-conversion) bytes under
#      analysis/proposals/stage1/raw/ via --keep-raw for reproducible
#      re-extraction.
def _compute_content_hash(path: Path, *, chunk_size: int = 65536) -> str:
    """Streaming sha256 hex digest of `path`. Reads in 64 KB chunks
    so we don't load 100+ MB call-data files into RAM. Raises OSError
    on read failure (caller decides how to surface).

    v1.4.4 R1 MINOR #3 caveat: if the source file is being actively
    modified during this read (a writer process appending or
    truncating), the digest reflects the partial mid-write byte
    state, NOT a coherent snapshot. The CLI's contract assumes the
    operator does not edit src/ during `bsa materials --commit`;
    this is documented in the user-facing command help. For stronger
    guarantees use `--keep-raw` and hash the raw/ copy after the fact."""
    import hashlib  # local — only used here
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_metadata(path: Path) -> tuple[str, int, str]:
    """Return (sha256_hex, size_bytes, mtime_utc_iso_seconds) for a
    file path. mtime is rounded to the nearest second (UTC) — gives
    a stable representation across filesystems with sub-second mtime
    precision (most modern FS) AND those that don't (FAT32, some
    NFS shares). ISO-8601 'Z' suffix for UTC clarity."""
    from datetime import datetime, timezone
    st = path.stat()
    mtime_utc = datetime.fromtimestamp(
        st.st_mtime, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _compute_content_hash(path), st.st_size, mtime_utc


@contextlib.contextmanager
def _materials_lock(workspace: Path) -> Iterator[None]:
    """Process-level advisory lock for destructive `bsa materials`
    operations (recreate, prune).

    v1.4.3 (Codex R1 MAJOR #2 + #3 fix). Two concurrent
    `--recreate-manifest` calls would otherwise:
      (a) both back up the SAME prior manifest into different backup
          files, then race on the final replace — overwritten content
          may not be in EITHER backup.
      (b) `--prune-orphans` could verify (no drift), then a parallel
          `--recreate-manifest` lands a fresh row right BEFORE the
          unlink loop, deleting an input that's no longer an orphan.

    Implementation: `fcntl.flock(LOCK_EX | LOCK_NB)` on
    `<workspace>/analysis/.bsa_materials.lock`. POSIX-only — Windows
    is not a supported platform for this plugin (hooks layer assumes
    bash). Lock is non-blocking: if held by another process, raises
    `ConversionFailed` with a clear message instead of hanging.

    v1.4.3 R2 fix: lock lives under `analysis/` (guaranteed to exist
    by `WorkspaceState.is_initialized()` check upstream) rather than
    auto-creating `stage1/` for a sentinel file. Avoids leaving
    half-bootstrapped workspaces behind on a failed maintenance call.

    Lock file is created on first use and never deleted (low-cost
    sentinel; deleting it would race with concurrent flock acquisition
    on the deleted inode)."""
    import fcntl as _fcntl  # POSIX-only; lazy import for clarity
    analysis_dir = workspace / "analysis"
    if not analysis_dir.is_dir():
        raise ConversionFailed(
            f"cannot acquire materials lock: workspace not initialized "
            f"({analysis_dir} missing). Run /bsa-start first."
        )
    lock_path = analysis_dir / ".bsa_materials.lock"
    fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            raise ConversionFailed(
                f"another `bsa materials` operation is in progress "
                f"(lock held on {lock_path}). Wait for it to finish "
                f"or remove the lock file if you're sure no other "
                f"process is running."
            ) from exc
        try:
            yield
        finally:
            try:
                _fcntl.flock(fd, _fcntl.LOCK_UN)
            except OSError:
                pass  # best-effort unlock
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _verify_manifest(workspace: Path) -> tuple[list[str], list[str], list[str]]:
    """Cross-check source_manifest.csv against actual files in inputs/.

    v1.4.3 (closes lifecycle review rec #1: recovery for partial-write
    states). Returns (orphan_manifest_rows, orphan_input_files,
    other_findings):

      * `orphan_manifest_rows` — list of `SourceID:Origin` strings for
        manifest rows whose corresponding `source_NNN_<slug>.md` file
        does NOT exist in inputs/. Common cause: input file was
        manually deleted but the manifest row stayed.
      * `orphan_input_files` — list of input filenames present in
        inputs/ but with no corresponding manifest row. Common cause:
        prior `--commit` failed AT the manifest write, leaving input
        files orphaned (the v1.0.4 partial-failure case the historical
        UX-pass retro flagged).
      * `other_findings` — schema-level drift (missing manifest,
        manifest-not-a-file, header drift from canonical A50 shape).
        Operator must address these before --recreate / --prune can
        be safely invoked.

    Pure read-only: never mutates workspace state."""
    findings_other: list[str] = []
    orphan_rows: list[str] = []
    orphan_files: list[str] = []
    stage1 = workspace / "analysis" / "proposals" / "stage1"
    inputs_dir = stage1 / "inputs"
    manifest = stage1 / "source_manifest.csv"

    if not inputs_dir.is_dir():
        findings_other.append(
            f"inputs directory missing: {inputs_dir} — workspace not "
            f"initialized OR `bsa materials --commit` has never run"
        )
        return orphan_rows, orphan_files, findings_other

    # Walk inputs/ — collect every source_NNN_*.md file present.
    # v1.4.3 Codex R1 MINOR #2 fix: \d{3,} (was \d{3,4}) so 5+ digit
    # SourceIDs (a hypothetical 10000+ source engagement) are still
    # detected. Staging path uses :03d minimum width with no upper cap.
    on_disk: dict[str, Path] = {}  # filename → Path
    src_pat = re.compile(r"^source_\d{3,}_.+\.md$")
    for entry in inputs_dir.iterdir():
        if entry.is_file() and src_pat.match(entry.name):
            on_disk[entry.name] = entry

    if not manifest.exists():
        # No manifest at all — every input file is an orphan.
        orphan_files.extend(sorted(on_disk.keys()))
        findings_other.append(
            f"manifest missing: {manifest} — every input file is "
            f"orphaned (use --recreate-manifest to rebuild from "
            f"provenance comments)"
        )
        return orphan_rows, orphan_files, findings_other

    if not manifest.is_file():
        findings_other.append(
            f"manifest path exists but is not a regular file: "
            f"{manifest} (directory? device?). Operator must clean "
            f"up the path manually before --verify can give a verdict"
        )
        return orphan_rows, orphan_files, findings_other

    # Read manifest rows. Use stdlib csv to honor RFC4180 quoting
    # (some Origin values contain commas/quotes from path names).
    # v1.4.3 Codex R1 MINOR #1 fix: utf-8-sig swallows a leading BOM
    # silently. A spreadsheet-tool round-trip can re-save the manifest
    # with `﻿` prefix; without -sig, the first column name was
    # `﻿SourceID` and the entire manifest looked like header drift.
    import csv as _csv
    try:
        with manifest.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = _csv.DictReader(fh)
            header_fields = reader.fieldnames or []
            if not header_fields:
                findings_other.append(
                    f"manifest is empty (no header row): {manifest}"
                )
                return orphan_rows, orphan_files, findings_other
            # Header drift check — must match A50 shape (one of three
            # accepted variants: base, +EffectiveDate v1.2.16,
            # +ContentHash v1.4.4).
            header_str = ",".join(header_fields).strip()
            if header_str not in _ACCEPTED_A50_HEADERS:
                findings_other.append(
                    f"manifest header drifts from canonical A50 shape "
                    f"(expected one of: {_A50_HEADER!r} | "
                    f"{_A50_HEADER_WITH_EFFECTIVE_DATE!r} | "
                    f"{_A50_HEADER_WITH_HASHES!r}; "
                    f"found {header_str!r})"
                )
                return orphan_rows, orphan_files, findings_other
            # Build the SourceID → expected-filename-prefix map.
            # Manifest row's SourceID is `S-NNN`; the staged file is
            # `source_NNN_<slug>.md`. We can't reconstruct the slug
            # without the manifest's Title-derived stem, so we look
            # for ANY file matching `source_NNN_*.md`.
            # v1.4.3 Codex R1 MINOR #2 fix: \d{3,} matches 5+ digit
            # SourceIDs.
            sid_pat = re.compile(r"^S-(\d{3,})$")
            seen_sids_on_disk: set[str] = set()
            for fname in on_disk:
                m = re.match(r"^source_(\d{3,})_.+\.md$", fname)
                if m:
                    seen_sids_on_disk.add(f"S-{m.group(1)}")
            sids_in_manifest: set[str] = set()
            for row in reader:
                sid = (row.get("SourceID") or "").strip()
                origin = (row.get("Origin") or "").strip()
                if not sid:
                    continue  # malformed row; ignore
                m = sid_pat.match(sid)
                if not m:
                    findings_other.append(
                        f"manifest row has malformed SourceID {sid!r} "
                        f"(expected `S-NNN` pattern)"
                    )
                    continue
                sids_in_manifest.add(sid)
                if sid not in seen_sids_on_disk:
                    orphan_rows.append(f"{sid}:{origin}")
            # Reverse-direction check: every on-disk file must have
            # a row in the manifest. We collected sids_in_manifest in
            # the same pass above to avoid a second file read.
            file_pat = re.compile(r"^source_(\d{3,})_.+\.md$")
            for fname in sorted(on_disk):
                m = file_pat.match(fname)
                if not m:
                    continue
                sid = f"S-{m.group(1)}"
                if sid not in sids_in_manifest:
                    orphan_files.append(fname)
    except (OSError, _csv.Error) as exc:
        findings_other.append(
            f"manifest read failed: {manifest} — {exc}"
        )

    return orphan_rows, orphan_files, findings_other


def _recreate_manifest(workspace: Path) -> str:
    """Rebuild `source_manifest.csv` from provenance comments in
    staged input files.

    v1.4.3 (closes lifecycle review rec #1). Walks
    `analysis/proposals/stage1/inputs/`, reads the
    `<!-- bsa materials: staged from <Origin> (kind=<k>); SourceID=<sid> -->`
    provenance comment from each `source_NNN_<slug>.md`, and
    reconstructs a manifest row with reasonable T5 ReliabilityTier
    + today's DateOrVersion. Files without a provenance comment are
    skipped with a stderr warning (operator can re-stage them via
    `bsa materials <src> --commit --force`).

    Existing manifest is BACKED UP to
    `source_manifest.csv.bak.<UTC-timestamp>` before overwrite —
    operators always have a recoverable prior state. Backup is
    atomic (tempfile + os.replace per `_atomic_write_text`).

    Returns a one-line status string. Raises ConversionFailed on
    catastrophic write failure (orphan-input safety: if write fails,
    the prior backup is intact)."""
    stage1 = workspace / "analysis" / "proposals" / "stage1"
    inputs_dir = stage1 / "inputs"
    manifest = stage1 / "source_manifest.csv"

    if not inputs_dir.is_dir():
        raise ConversionFailed(
            f"inputs directory missing: {inputs_dir} — cannot recreate"
        )

    # Walk inputs/ in deterministic order.
    # v1.4.3 Codex R1 MINOR #2 fix: \d{3,} (5+ digit SourceIDs).
    src_pat = re.compile(r"^source_(\d{3,})_.+\.md$")
    rows_to_emit: list[dict[str, str]] = []
    skipped_no_provenance: list[str] = []
    skipped_sid_mismatch: list[str] = []
    today = _today_iso()
    # Known kinds the staging path emits today. v1.4.3 Codex R1 MAJOR
    # #4 fix: validate kind so a corrupted/renamed file doesn't slip
    # in with `kind=evil` and confuse downstream type heuristics.
    # v1.4.5 adds pptx + html. v1.4.6 adds eml + msg (email evidence).
    _known_kinds = {
        "pdf", "docx", "text", "xlsx", "csv", "tsv", "json",
        "pptx", "html", "eml", "msg",
    }

    for entry in sorted(inputs_dir.iterdir(), key=lambda p: p.name):
        if not entry.is_file():
            continue
        m = src_pat.match(entry.name)
        if not m:
            continue
        sid = f"S-{m.group(1)}"
        # Read provenance to recover Origin + kind.
        # v1.4.3 R2 fix: read BYTES first, strip only the explicit
        # UTF-8 BOM at the byte level, THEN decode strictly. The
        # earlier `errors="ignore"` would silently drop invalid bytes,
        # letting a corrupt-prefix file's later text fool the anchored
        # `.match`. Strict decode + explicit BOM strip = no foot-gun.
        # v1.4.3 R3 fix: a flat `bytes[:512].decode("utf-8")` could
        # split a valid multibyte UTF-8 sequence at the boundary,
        # causing legitimate staged files to fail strict decode.
        # Use `codecs.IncrementalDecoder` with `final=False` so an
        # incomplete trailing sequence at the artificial head boundary
        # is buffered (and effectively dropped) rather than raised.
        # Invalid mid-stream bytes still raise UnicodeDecodeError →
        # skip, preserving the R2 foot-gun fix.
        import codecs as _codecs
        try:
            raw_head = entry.read_bytes()[:512]
        except OSError:
            skipped_no_provenance.append(entry.name)
            continue
        if raw_head.startswith(b"\xef\xbb\xbf"):
            raw_head = raw_head[3:]
        decoder = _codecs.getincrementaldecoder("utf-8")(errors="strict")
        try:
            head = decoder.decode(raw_head, final=False)
        except UnicodeDecodeError:
            skipped_no_provenance.append(entry.name)
            continue
        # v1.4.3 Codex R1 MAJOR #4 fix: anchor at start of file (use
        # `match`, not `search`). Allow only ASCII whitespace before
        # the comment (BOM was already stripped at byte level above).
        # A binary blob whose middle bytes happened to match the
        # regex would otherwise be accepted; that's the "renamed
        # file kept its old comment" foot-gun the reviewer flagged.
        prov_match = _PROVENANCE_COMMENT_RE.match(head.lstrip(" \t\r\n"))
        if not prov_match:
            skipped_no_provenance.append(entry.name)
            continue
        # v1.4.3 Codex R1 MAJOR #4 fix: validate the parsed SID
        # matches the filename-derived SID. Without this, a renamed
        # file (e.g., source_042_rename.md whose body still has
        # SourceID=S-007) would emit a row with the WRONG SourceID
        # for downstream evidence binding.
        prov_sid = prov_match.group("sid")
        if prov_sid != sid:
            skipped_sid_mismatch.append(
                f"{entry.name} (filename SID={sid}, "
                f"provenance SID={prov_sid})"
            )
            continue
        origin = prov_match.group("orig")
        kind = prov_match.group("kind")
        # Validate kind. Unknown kind = treat as no-provenance and
        # let the operator re-stage explicitly.
        if kind not in _known_kinds:
            skipped_no_provenance.append(
                f"{entry.name} (unknown kind={kind!r})"
            )
            continue
        # SourceType heuristic mirrors _render_draft_manifest.
        # v1.4.5 keeps pptx in the "document" bucket; html lands as
        # process_note (web exports are typically procedural docs).
        # v1.4.6: eml/msg → email_thread (matches the staging path).
        slug_lower = entry.stem.lower()
        if "interview" in slug_lower or "transcript" in slug_lower:
            stype = "interview_transcript"
        elif kind in ("eml", "msg"):
            stype = "email_thread"
        elif kind in ("pdf", "docx", "pptx"):
            stype = "document"
        elif kind in ("xlsx", "csv", "tsv", "json", "html"):
            stype = "process_note"  # tabular / structured data / web export
        else:
            stype = "process_note"
        title = entry.stem.split("_", 2)[-1] if "_" in entry.stem else entry.stem
        # v1.4.4: if --keep-raw was used during original staging, the
        # source bytes live at <stage1>/raw/source_NNN_<slug>.<ext>.
        # Try to recover hash + size + mtime so the recreated manifest
        # matches what a fresh staging run would have produced.
        # Otherwise leave the hash columns empty (operator can backfill
        # via `bsa materials <src> --restage-changed --keep-raw`).
        raw_dir = inputs_dir.parent / "raw"
        content_hash = ""
        original_bytes_str = ""
        original_mtime = ""
        if raw_dir.is_dir():
            # Match by SourceID prefix — slug + extension may vary
            # (the ORIGINAL extension is what we kept, not .md).
            raw_candidates = sorted(
                raw_dir.glob(f"source_{m.group(1)}_*"),
            )
            # Filter out subdirs / unexpected paths.
            raw_candidates = [c for c in raw_candidates if c.is_file()]
            if len(raw_candidates) == 1:
                try:
                    rh, rb, rmt = _file_metadata(raw_candidates[0])
                    content_hash = rh
                    original_bytes_str = str(rb)
                    original_mtime = rmt
                except OSError:
                    pass  # leave empty; operator can re-stage
        rows_to_emit.append({
            "SourceID": sid,
            "SourceType": stype,
            "Title": _csv_escape(title),
            "Origin": _csv_escape(origin),
            "AccessStatus": "readable",
            "ReliabilityTier": "T5",
            "Priority": "medium",
            "Language": "en",
            "DateOrVersion": today,
            "EffectiveDate": "",
            "ContentHash": content_hash,
            "OriginalBytes": original_bytes_str,
            "OriginalMtimeUtc": original_mtime,
            "Notes": _csv_escape(
                "auto-recreated by `bsa materials --recreate-manifest`; "
                "ReliabilityTier defaulted to T5 — re-tag based on epistemic "
                "proximity per skills/bsa-evidence-intake/references/"
                "reliability_tier_spec.md before /bsa-promote"
            ),
        })

    # Backup existing manifest before overwrite.
    # v1.4.3 Codex R1 MAJOR #1 fix: include microseconds AND use
    # O_EXCL with collision-retry. Without this, two recreate calls
    # within the same UTC second would clobber each other's backup,
    # losing the prior manifest state the feature promises to preserve.
    backup_msg = ""
    if manifest.is_file():
        from datetime import datetime as _dt
        base_ts = _dt.utcnow().strftime("%Y%m%dT%H%M%S_%fZ")
        manifest_bytes = manifest.read_bytes()
        backup_path: Optional[Path] = None
        # Try the base name first; if it exists (extreme race), append
        # a counter suffix until we find a free name. O_EXCL ensures
        # we never silently overwrite. Bound the retry loop so a
        # filesystem permission misconfig doesn't hang us forever.
        for attempt in range(64):
            candidate_name = (
                f"source_manifest.csv.bak.{base_ts}"
                if attempt == 0
                else f"source_manifest.csv.bak.{base_ts}_{attempt}"
            )
            candidate = manifest.parent / candidate_name
            try:
                fd = os.open(
                    str(candidate),
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o644,
                )
            except FileExistsError:
                continue  # bump counter
            except OSError as exc:
                raise ConversionFailed(
                    f"cannot back up existing manifest before recreate "
                    f"({manifest} → {candidate}): {exc}. Refusing to "
                    f"overwrite without a recoverable backup"
                ) from exc
            try:
                with os.fdopen(fd, "wb") as bh:
                    bh.write(manifest_bytes)
            except OSError as exc:
                # Cleanup partially-written backup so the next attempt
                # gets a clean slate.
                with contextlib.suppress(OSError):
                    candidate.unlink()
                raise ConversionFailed(
                    f"cannot write backup body ({candidate}): {exc}. "
                    f"Refusing to overwrite manifest without a "
                    f"recoverable backup"
                ) from exc
            backup_path = candidate
            break
        if backup_path is None:
            raise ConversionFailed(
                f"could not allocate a unique backup name for "
                f"{manifest} after 64 attempts (filesystem clock or "
                f"permission anomaly)"
            )
        backup_msg = f" (prior manifest backed up to {backup_path.name})"

    # Render new manifest body.
    # v1.4.4: emit the WITH_HASHES variant by default so future
    # tooling sees the new schema; cells are empty when raw/ wasn't
    # retained (back-fill path documented above).
    cols = [
        "SourceID", "SourceType", "Title", "Origin", "AccessStatus",
        "ReliabilityTier", "Priority", "Language", "DateOrVersion",
        "EffectiveDate",
        "ContentHash", "OriginalBytes", "OriginalMtimeUtc",
        "Notes",
    ]
    out_lines = [",".join(cols)]
    for row in rows_to_emit:
        out_lines.append(",".join(row[c] for c in cols))
    new_body = "\n".join(out_lines) + "\n"
    _atomic_write_text(manifest, new_body)

    skipped_note = ""
    if skipped_no_provenance:
        skipped_note = (
            f"; SKIPPED {len(skipped_no_provenance)} file(s) with no "
            f"provenance comment (re-stage via `bsa materials <src> "
            f"--commit --force` to add them): "
            f"{', '.join(skipped_no_provenance[:5])}"
            f"{' ...' if len(skipped_no_provenance) > 5 else ''}"
        )
    sid_mismatch_note = ""
    if skipped_sid_mismatch:
        # v1.4.3 Codex R1 MAJOR #4 fix: surface SID-mismatch
        # explicitly so the operator knows the file was renamed and
        # needs manual review (re-stage OR rename back).
        sid_mismatch_note = (
            f"; SKIPPED {len(skipped_sid_mismatch)} file(s) with SID "
            f"mismatch between filename and provenance (likely "
            f"renamed; restore original name OR re-stage explicitly): "
            f"{'; '.join(skipped_sid_mismatch[:5])}"
            f"{' ...' if len(skipped_sid_mismatch) > 5 else ''}"
        )
    return (
        f"recreated manifest with {len(rows_to_emit)} row(s){backup_msg}"
        f"{skipped_note}{sid_mismatch_note}"
    )


def _prune_orphans(workspace: Path, *, confirmed: bool) -> tuple[list[str], list[str]]:
    """Delete input files that have no corresponding manifest row.

    v1.4.3 (closes lifecycle review rec #1). Refuses to delete unless
    `confirmed=True` (caller passes via `--yes` CLI flag). Pure
    deletion — does NOT touch the manifest. Pair with
    `--recreate-manifest` if the orphan set is large enough that
    re-staging is the cleaner recovery path.

    Returns (deleted_filenames, would_delete_filenames):
      * `deleted_filenames` is non-empty only when confirmed=True
        AND the deletion succeeded.
      * `would_delete_filenames` is the dry-run list (always
        populated; matches the orphan-input set from
        `_verify_manifest`).

    Raises ConversionFailed on workspace-shape errors or on
    catastrophic per-file deletion failure."""
    _, orphan_files, other_findings = _verify_manifest(workspace)
    if other_findings:
        # Don't prune in the presence of structural drift — operator
        # must address those first via --recreate-manifest or manual
        # repair. Refuse safely.
        raise ConversionFailed(
            f"refusing to prune in the presence of structural manifest "
            f"drift: {'; '.join(other_findings)}"
        )

    would_delete = list(orphan_files)
    deleted: list[str] = []
    if not confirmed:
        return deleted, would_delete

    # v1.4.3 Codex R1 CRITICAL fix: defense-in-depth path validation.
    # Even though the caller (cmd_materials) runs _check_write_containment
    # first, we re-validate inside the destructive function so a future
    # caller that forgets the containment check can't make us unlink
    # outside the workspace. Resolve the inputs dir ONCE, then verify
    # each target's resolved path stays under it AND is not itself a
    # symlink (a same-name symlink could redirect outside between
    # verify and unlink).
    inputs_dir = workspace / "analysis" / "proposals" / "stage1" / "inputs"
    try:
        inputs_resolved = inputs_dir.resolve(strict=True)
    except OSError as exc:
        raise ConversionFailed(
            f"refusing to prune: cannot resolve inputs dir "
            f"{inputs_dir} ({exc})"
        ) from exc
    for fname in would_delete:
        target = inputs_dir / fname
        # Reject symlink targets (a malicious or accidental symlink
        # named source_NNN_*.md could point at /etc/passwd).
        if target.is_symlink():
            raise ConversionFailed(
                f"refusing to prune {fname}: target is a symlink "
                f"({target.readlink()}). Manual cleanup required."
            )
        # Re-resolve the parent only (we just rejected the leaf as a
        # symlink) to ensure the full resolved path stays under the
        # resolved inputs dir.
        try:
            resolved_parent = target.parent.resolve(strict=True)
        except OSError as exc:
            raise ConversionFailed(
                f"refusing to prune {fname}: cannot resolve parent "
                f"({exc})"
            ) from exc
        if resolved_parent != inputs_resolved:
            raise ConversionFailed(
                f"refusing to prune {fname}: resolved parent "
                f"{resolved_parent} escapes inputs dir "
                f"{inputs_resolved}"
            )
        try:
            target.unlink()
            deleted.append(fname)
        except OSError as exc:
            raise ConversionFailed(
                f"prune failed at {fname}: {exc} ({len(deleted)} file(s) "
                f"already deleted before this point — partial state)"
            ) from exc
    return deleted, would_delete


def cmd_materials(args: argparse.Namespace) -> int:
    """Stage PDF/DOCX/MD/TXT/XLSX/CSV/TSV/JSON/GraphQL inputs into
    analysis/proposals/stage1/inputs/, OR run a manifest-maintenance
    operation against the workspace.

    Two operating modes:

    1. **Staging mode** (default) — requires `src_dir` positional:
       Default is dry-run — prints what would be done. --commit performs
       writes. --force overwrites existing target files. --recursive
       walks subdirectories.

    2. **Manifest-maintenance mode** (v1.4.3+) — `src_dir` is OPTIONAL,
       triggered by one of:
       * `--verify-manifest` — cross-check manifest vs inputs/, report
         drift (orphan rows, orphan files, header drift). Read-only.
       * `--recreate-manifest` — rebuild manifest from provenance
         comments in staged files. Backs up prior manifest to
         `source_manifest.csv.bak.<timestamp>`.
       * `--prune-orphans` — delete input files with no manifest row.
         Requires `--yes` to confirm (destructive).

    Exit codes:
        0 = staging preview / staging success / verify-clean / recreate
            success / prune success.
        1 = staging per-file failure (ConversionFailed /
            ConversionUnavailable) OR verify-manifest found drift.
        2 = invocation / structural error: bad src dir, uninitialized
            workspace, EMPTY src dir, header drift, prune-without-yes.
    """
    # v1.3.11 split: WorkspaceState lives in bsa_cli.py; lazy import
    # avoids module-load-time circular dep.
    from scripts.bsa_cli import WorkspaceState  # lazy

    root = Path(args.workspace).resolve()
    ws = WorkspaceState(root)

    if not ws.is_initialized():
        sys.stderr.write(
            f"[bsa materials] {root} is not a BSA workspace "
            "(no analysis/ directory). Run /bsa-start in Claude "
            "Code first.\n"
        )
        return 2

    # ---- v1.4.3: manifest-maintenance modes -------------------------
    # These run BEFORE the src_dir check because they don't need one.
    # Mutual exclusion enforced at argparse layer.
    verify_mode = bool(getattr(args, "verify_manifest", False))
    recreate_mode = bool(getattr(args, "recreate_manifest", False))
    prune_mode = bool(getattr(args, "prune_orphans", False))
    yes_flag = bool(getattr(args, "yes", False))

    # v1.4.3 Codex R1 MINOR #3 fix: warn loudly when --yes is set
    # without --prune-orphans (the only flag that currently consults
    # it). Otherwise typos like `--verify-manifest --yes` would
    # silently succeed, masking operator intent.
    if yes_flag and not prune_mode:
        sys.stderr.write(
            "[bsa materials] --yes is currently only consulted by "
            "--prune-orphans; ignoring (no destructive op selected).\n"
        )

    # v1.4.3 Codex R1 CRITICAL fix: maintenance modes that read OR
    # mutate the workspace must run the same containment check as
    # staging mode. Without this, a symlinked analysis/proposals/
    # stage1/inputs/ would let `--prune-orphans --yes` follow the
    # symlink and unlink files outside the workspace.
    if verify_mode or recreate_mode or prune_mode:
        stage1_dir = ws.analysis / "proposals" / "stage1"
        inputs_dir = stage1_dir / "inputs"
        manifest_path = stage1_dir / "source_manifest.csv"
        contain_error = _check_write_containment(
            stage1_dir, inputs_dir, manifest_path
        )
        if contain_error is not None:
            sys.stderr.write(f"[bsa materials] {contain_error}\n")
            return 2

    if verify_mode:
        orphan_rows, orphan_files, other_findings = _verify_manifest(root)
        print(f"BSA materials --verify-manifest: {root}")
        print()
        if other_findings:
            print(f"Structural findings ({len(other_findings)}):")
            for f in other_findings:
                print(f"  - {f}")
            print()
        if orphan_rows:
            print(f"Orphan manifest rows ({len(orphan_rows)} — manifest "
                  f"references file that doesn't exist):")
            for r in orphan_rows[:20]:
                print(f"  - {r}")
            if len(orphan_rows) > 20:
                print(f"  ... and {len(orphan_rows) - 20} more")
            print()
        if orphan_files:
            print(f"Orphan input files ({len(orphan_files)} — file in "
                  f"inputs/ has no manifest row):")
            for f in orphan_files[:20]:
                print(f"  - {f}")
            if len(orphan_files) > 20:
                print(f"  ... and {len(orphan_files) - 20} more")
            print()
        if not (orphan_rows or orphan_files or other_findings):
            print("CLEAN: every manifest row has a corresponding "
                  "input file, every input file has a manifest row, "
                  "header matches canonical A50 shape.")
            return 0
        # Drift detected — operator's call whether to recreate / prune.
        print("Recovery options:")
        if other_findings:
            print(
                "  - Resolve structural findings first (manual repair "
                "OR --recreate-manifest if header drift)."
            )
        if orphan_rows:
            print(
                "  - For orphan manifest rows: re-stage the missing "
                "source files (`bsa materials <src> --commit --force`) "
                "OR remove the rows manually."
            )
        if orphan_files:
            print(
                "  - For orphan input files: `bsa materials "
                "--prune-orphans --yes` to delete them, OR "
                "`bsa materials --recreate-manifest` to rebuild the "
                "manifest from their provenance comments."
            )
        return 1

    if recreate_mode:
        # v1.4.3 Codex R1 MAJOR #2 fix: serialize destructive ops via
        # an advisory file lock so two parallel `--recreate-manifest`
        # calls don't race on the backup-then-replace dance.
        try:
            with _materials_lock(root):
                msg = _recreate_manifest(root)
        except ConversionFailed as exc:
            sys.stderr.write(f"[bsa materials --recreate-manifest] {exc}\n")
            return 2
        print(f"BSA materials --recreate-manifest: {root}")
        print(f"  {msg}")
        return 0

    if prune_mode:
        # v1.4.3 Codex R1 MAJOR #3 fix: hold the materials lock for
        # the entire verify+delete window so a concurrent recreate
        # can't make a file non-orphan between our verify and our
        # unlink.
        try:
            with _materials_lock(root):
                deleted, would_delete = _prune_orphans(
                    root, confirmed=yes_flag
                )
        except ConversionFailed as exc:
            sys.stderr.write(f"[bsa materials --prune-orphans] {exc}\n")
            return 2
        print(f"BSA materials --prune-orphans: {root}")
        print()
        if not would_delete:
            print("CLEAN: no orphan input files to prune.")
            return 0
        if not yes_flag:
            print(f"DRY RUN — would delete {len(would_delete)} orphan "
                  f"file(s) (re-run with --yes to actually delete):")
            for f in would_delete[:20]:
                print(f"  - {f}")
            if len(would_delete) > 20:
                print(f"  ... and {len(would_delete) - 20} more")
            return 0
        print(f"Deleted {len(deleted)} orphan input file(s):")
        for f in deleted[:20]:
            print(f"  - {f}")
        if len(deleted) > 20:
            print(f"  ... and {len(deleted) - 20} more")
        return 0

    # ---- Staging mode (existing behavior) ---------------------------
    if not getattr(args, "src_dir", None):
        sys.stderr.write(
            "[bsa materials] src_dir is required for staging mode. "
            "Pass a directory path, OR use one of the manifest-"
            "maintenance modes: --verify-manifest, --recreate-"
            "manifest, --prune-orphans.\n"
        )
        return 2

    src_dir = Path(args.src_dir).resolve()

    if not src_dir.is_dir():
        sys.stderr.write(
            f"[bsa materials] source directory not found: {src_dir}\n"
        )
        return 2
    # workspace-initialization check moved to top of cmd_materials in
    # v1.4.3 (so manifest-maintenance modes also benefit from the
    # check). Removing the duplicate here.

    # Write containment (Codex round-1 HIGH): RESOLVE the staging dir
    # and refuse to proceed if any of inputs/, source_manifest.csv,
    # or any planned target file would land OUTSIDE the resolved
    # `<workspace>/analysis/proposals/stage1/` subtree. Without this,
    # a symlinked `analysis/`, `proposals/`, `stage1/`, or `inputs/`
    # would let `--commit` write into arbitrary filesystem locations
    # under the user's account.
    stage1_dir = (ws.analysis / "proposals" / "stage1")
    inputs_dir = stage1_dir / "inputs"
    manifest_path = stage1_dir / "source_manifest.csv"

    contain_error = _check_write_containment(stage1_dir, inputs_dir, manifest_path)
    if contain_error is not None:
        sys.stderr.write(f"[bsa materials] {contain_error}\n")
        return 2

    # 1. Walk source dir. v1.4.1: --max-mb CLI override; defaults to
    # 25.0 MB when arg is absent (back-compat with pre-v1.4.1 callers).
    max_mb = float(getattr(args, "max_mb", 25.0))
    max_file_bytes = int(max_mb * 1024 * 1024)
    supported, unsupported, too_big = _scan_source_dir(
        src_dir, recursive=bool(args.recursive),
        max_file_bytes=max_file_bytes,
    )
    if not supported and not unsupported and not too_big:
        sys.stderr.write(
            f"[bsa materials] no files found under {src_dir} "
            f"(recursive={bool(args.recursive)}). "
            f"Supported extensions: {sorted(_EXT_TO_KIND)}.\n"
        )
        return 2

    # 2. Plan conversions (assigns IDs, flags target collisions).
    # v1.4.4: --restage-changed compares src content-hash against the
    # manifest's stored ContentHash; matched → skip-unchanged,
    # mismatched → restage with EXISTING SourceID (in-place row update).
    restage_changed_mode = bool(getattr(args, "restage_changed", False))
    plans = _plan_conversions(
        supported, inputs_dir, manifest_path, src_dir,
        force=bool(args.force),
        restage_changed=restage_changed_mode,
    )

    # 3. Render preview.
    print(f"BSA materials: {src_dir} → {inputs_dir}")
    print()
    print(f"Found {len(supported)} convertible file(s)"
          f" ({_count_kinds(plans)})"
          f"; {len(unsupported)} unsupported, {len(too_big)} too-large")
    print()
    if plans:
        print("Plan:")
        for p in plans:
            mark = " (SKIP)" if p.skipped_reason else ""
            # For skipped plans the SourceID we'd assign is moot
            # (we won't write the manifest row). Show "(existing)"
            # to avoid the visual confusion of multiple skipped
            # entries all sharing the same provisional ID.
            sid_label = "(existing)" if p.skipped_reason else p.source_id
            print(f"  [{sid_label}] {p.src.name:<40s} → {p.target.name}{mark}")
            if p.skipped_reason:
                print(f"           reason: {p.skipped_reason}")
    if unsupported:
        print()
        print("Unsupported (not staged):")
        for f in unsupported[:10]:
            print(f"  - {f.name}  ({f.suffix or 'no-ext'})")
        if len(unsupported) > 10:
            print(f"  ... and {len(unsupported) - 10} more")
    if too_big:
        print()
        print(
            f"Too large (> {_bytes_human(max_file_bytes)}; not staged — "
            f"raise --max-mb to include):"
        )
        for f in too_big:
            print(f"  - {f.name}  ({_bytes_human(f.stat().st_size)})")

    print()
    if not args.commit:
        print("DRY RUN. Re-run with --commit to actually write files + draft manifest.")
        if any(not p.skipped_reason for p in plans):
            # v1.4.4 R1 MINOR #1 fix: include flags so the suggested
            # command preserves the operator's intent. Otherwise
            # copy-paste of the suggestion silently downgrades from
            # `--restage-changed` / `--keep-raw` mode to plain commit.
            extras: list[str] = []
            if restage_changed_mode:
                extras.append("--restage-changed")
            if bool(getattr(args, "keep_raw", False)):
                extras.append("--keep-raw")
            if bool(args.recursive):
                extras.append("--recursive")
            if bool(args.force):
                extras.append("--force")
            extras_str = (" " + " ".join(extras)) if extras else ""
            print("Suggested next:")
            print(f"  bsa --workspace {root} materials {src_dir} --commit{extras_str}")
        return 0

    # PRE-FLIGHT: header-drift check + leaf-symlink check.
    # Round-2 fix: do these BEFORE any file writes so we never leave
    # a half-committed state (input files written + manifest unwritable).
    # Round-3 fix: catch the "manifest_path is a directory / device /
    # other non-file" case BEFORE writing inputs. Without this, the
    # commit phase could orphan input files when the post-write
    # manifest update failed late.
    if manifest_path.exists() and not manifest_path.is_file():
        sys.stderr.write(
            f"[bsa materials] {manifest_path} exists but is not a regular "
            f"file (directory? device? socket?). Refuse to write — clean "
            f"up the path manually before re-running.\n"
        )
        return 2
    if manifest_path.is_file():
        # Round-6 fix: previously _atomic_write_text would silently
        # overwrite a read-only manifest because os.replace inspects
        # the parent directory's permission, not the file's. The
        # user explicitly chose to chmod the manifest read-only —
        # honor that intent before we plan any writes.
        if not os.access(manifest_path, os.W_OK):
            sys.stderr.write(
                f"[bsa materials] existing source_manifest.csv is not "
                f"writable ({manifest_path}). The atomic-write path "
                f"would otherwise replace it via os.replace, bypassing "
                f"the file's mode bits. If you want to update it, run "
                f"`chmod u+w {manifest_path}` first.\n"
            )
            return 2
        try:
            existing_text = manifest_path.read_text(encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(
                f"[bsa materials] cannot read existing manifest {manifest_path}: {exc}\n"
            )
            return 2
        existing_lines = existing_text.splitlines()
        # v1.4.4: strip a leading UTF-8 BOM the same way utf-8-sig
        # would; the body decode here uses plain utf-8 (legacy code
        # path) so we normalize the first line manually for the
        # header comparison.
        first_line = existing_lines[0] if existing_lines else ""
        if first_line.startswith("﻿"):
            first_line = first_line.lstrip("﻿")
        # v1.4.4 R1 MAJOR #2 fix: parse via csv so a quoted header
        # (`"SourceID","SourceType",...` from a QUOTE_ALL writer or
        # spreadsheet round-trip) normalizes to the bare-comma form
        # before the header-set comparison.
        import csv as _csv
        try:
            parsed_header_fields = next(
                _csv.reader(io.StringIO(first_line))
            )
            existing_header = ",".join(parsed_header_fields).strip()
        except (StopIteration, _csv.Error):
            existing_header = first_line.strip()
        if existing_header not in _ACCEPTED_A50_HEADERS:
            sys.stderr.write(
                f"[bsa materials] existing source_manifest.csv has a non-canonical header.\n"
                f"  Expected: {_A50_HEADER}\n"
                f"        OR: {_A50_HEADER_WITH_EFFECTIVE_DATE}\n"
                f"        OR: {_A50_HEADER_WITH_HASHES}\n"
                f"  Found:    {existing_header or '(empty)'}\n"
                f"Refuse to append — column misalignment would corrupt the register.\n"
                f"Recovery options:\n"
                f"  (a) restore the canonical A50 column order in the manifest manually, OR\n"
                f"  (b) delete the manifest AND the input files in {inputs_dir} \n"
                f"      (or pass --force on the next run to bypass slug-skip), then re-run.\n"
            )
            return 2
    if manifest_path.is_symlink():
        sys.stderr.write(
            f"[bsa materials] refusing to write: {manifest_path} is a symlink. "
            f"Replace with a real file before running --commit.\n"
        )
        return 2
    # Per-target leaf-symlink check.
    for p in plans:
        if p.skipped_reason is not None:
            continue
        if p.target.is_symlink():
            sys.stderr.write(
                f"[bsa materials] refusing to write: {p.target} is a symlink. "
                f"Replace with a real file or delete it before --commit.\n"
            )
            return 2

    # 4. Commit phase: convert + write each file. Track failures.
    # v1.4.1: thread --max-rows-per-table into the tabular extractors.
    # v1.4.4: thread --keep-raw flag into the writer loop (raw bytes
    # retention next to the staged .md).
    max_rows_per_table = int(getattr(args, "max_rows_per_table", 5000))
    max_json_chars = int(getattr(args, "max_json_chars", 200_000))
    keep_raw_flag = bool(getattr(args, "keep_raw", False))
    inputs_dir.mkdir(parents=True, exist_ok=True)
    written: list[SourcePlan] = []
    failed: list[tuple[SourcePlan, str]] = []
    unavailable_seen: set[str] = set()
    # v1.4.4 R1 MAJOR #4 fix: snapshot existing staged-file bytes for
    # restage plans BEFORE we overwrite them. On manifest-write
    # failure we restore from this map so the staged file + manifest
    # remain consistent (both old → manifest still reflects the file).
    # v1.4.4 R2 NEW MAJOR fix: also track restage SIDs whose target
    # did NOT exist before the write (operator deleted the staged
    # file but kept the manifest row → restage creates a fresh
    # staged file). On manifest-write failure these get UNLINKED
    # rather than restored (no prior state to restore TO).
    restage_snapshots: dict[str, bytes] = {}
    restage_absent_targets: set[str] = set()
    for p in plans:
        if p.skipped_reason is not None:
            continue
        try:
            content = _convert_one(
                p,
                max_rows_per_table=max_rows_per_table,
                max_json_chars=max_json_chars,
            )
        except ConversionUnavailable as exc:
            unavailable_seen.add(p.kind)
            failed.append((p, f"unavailable: {exc}"))
            continue
        except ConversionFailed as exc:
            failed.append((p, f"conversion failed: {exc}"))
            continue
        # Wrap each converted file with a small header so downstream
        # consumers (and humans diffing inputs/) can trace provenance
        # without grepping the manifest.
        # Provenance comment uses the canonical Origin (relative
        # path under src_dir_root) so disambiguation in
        # _plan_conversions can compare apples-to-apples with the
        # manifest's Origin column. Round-3 fix.
        body = (
            f"<!-- bsa materials: staged from {p.origin_rel} "
            f"(kind={p.kind}); SourceID={p.source_id} -->\n\n"
            + content
        )
        # v1.4.4 R1 MAJOR #4 fix: for restage plans, snapshot the
        # existing staged-file bytes BEFORE overwrite so we can
        # restore on a subsequent manifest-write failure (the
        # mixed-state recovery path uses these to roll back).
        # v1.4.4 R2 NEW MAJOR fix: distinguish "had-prior-bytes"
        # (snapshot path) from "target absent" (unlink path) so we
        # don't leave a brand-new file behind when manifest fails.
        if p.restage:
            if p.target.is_file():
                try:
                    restage_snapshots[p.source_id] = p.target.read_bytes()
                except OSError:
                    # Best-effort — if we can't snapshot, the rollback
                    # path will simply skip restore and emit a clearer
                    # mixed-state stderr message.
                    pass
            else:
                restage_absent_targets.add(p.source_id)
        try:
            p.target.write_text(body, encoding="utf-8")
        except OSError as exc:
            failed.append((p, f"write failed: {exc}"))
            continue
        # v1.4.4: compute hash + size + mtime AFTER successful write.
        # For restage plans these were already populated in
        # _plan_conversions (we needed them for the compare); for
        # fresh plans we populate them now from the original src.
        if p.content_hash is None or p.original_bytes is None:
            try:
                ch, ob, om = _file_metadata(p.src)
                p.content_hash = ch
                p.original_bytes = ob
                p.original_mtime_utc = om
            except OSError as exc:
                # Hash failure is non-fatal — staged file is on disk
                # already; manifest row will land with empty hash
                # cells (operator can re-stage with --restage-changed
                # later to backfill).
                sys.stderr.write(
                    f"[bsa materials] WARN hash compute failed for "
                    f"{p.src.name}: {exc} (manifest row will have "
                    f"empty ContentHash)\n"
                )
        # v1.4.4 --keep-raw: preserve a byte-perfect copy of the
        # original under <stage1>/raw/source_NNN_<slug>.<ext>. Pure
        # additive — never touches inputs/, manifest, or canonical
        # state. Idempotent: if a raw file already exists with the
        # same hash, skip the copy.
        # v1.4.4 R1 MAJOR #3 fix: containment defense — refuse if
        # raw/ OR the leaf raw_target is a symlink (a malicious
        # symlink would let a copy land outside the workspace).
        # Resolve raw_target.parent and verify it stays under the
        # resolved raw_dir. The same defense pattern _prune_orphans
        # uses in v1.4.3.
        if keep_raw_flag:
            raw_dir = stage1_dir / "raw"
            try:
                raw_dir.mkdir(parents=True, exist_ok=True)
                if raw_dir.is_symlink():
                    raise OSError(
                        f"refusing to write: raw/ is a symlink "
                        f"({raw_dir.readlink()}). Re-create as a real "
                        f"directory before re-running."
                    )
                raw_dir_resolved = raw_dir.resolve(strict=True)
                sid_digits = p.source_id.removeprefix("S-")
                # Match the staged-file slug for sortability AND
                # keep the ORIGINAL extension so the operator can
                # round-trip via the original tooling.
                raw_target = raw_dir / (
                    f"source_{sid_digits}_{p.target.stem.split('_', 2)[-1]}"
                    f"{p.src.suffix}"
                )
                if raw_target.is_symlink():
                    raise OSError(
                        f"refusing to write: raw target is a symlink "
                        f"({raw_target.readlink()}). Manual cleanup "
                        f"required."
                    )
                # Defense-in-depth: confirm resolved parent is the
                # resolved raw_dir (catches a same-name symlink in a
                # subpath that wasn't caught by the leaf check above).
                resolved_parent = raw_target.parent.resolve(strict=True)
                if resolved_parent != raw_dir_resolved:
                    raise OSError(
                        f"refusing to write: raw target's resolved "
                        f"parent {resolved_parent} escapes raw dir "
                        f"{raw_dir_resolved}"
                    )
                if raw_target.is_file() and p.content_hash:
                    try:
                        existing_hash = _compute_content_hash(raw_target)
                        if existing_hash == p.content_hash:
                            written.append(p)
                            continue  # idempotent skip
                    except OSError:
                        pass  # fall through to overwrite
                # v1.4.4 R1 MINOR #2 fix: copy2 (not copyfile) so
                # OriginalMtimeUtc backfilled later by recreate
                # reflects the SOURCE's mtime, not the copy time.
                shutil.copy2(p.src, raw_target)
            except OSError as exc:
                # raw retention is best-effort; the manifest row +
                # staged input file are already written. Surface a
                # WARN and keep going (don't fail the whole batch).
                sys.stderr.write(
                    f"[bsa materials] WARN --keep-raw copy failed for "
                    f"{p.src.name}: {exc}\n"
                )
        written.append(p)

    # 5. Write draft manifest (only for files we successfully wrote).
    # Header drift was already caught in the pre-flight; here we
    # only need to append/create. We STILL wrap in try/except OSError
    # because between the pre-flight check and this write, anything
    # external (chmod, rm + replace with directory, fs full) could
    # have changed the path's writability. If the manifest write
    # fails, we surface the orphan-input state clearly so the user
    # can either fix the manifest manually OR delete the input
    # files and re-run.
    manifest_action = "skipped (no successful writes)"
    if written:
        try:
            manifest_action = _upsert_draft_manifest(
                manifest_path, written, src_dir
            )
        except OSError as exc:
            # Round-4 fix: previously the recovery guidance suggested
            # "fix the underlying issue and re-run" — but a plain
            # re-run would slug-match the orphaned inputs, set
            # written=[] (because all plans become skipped), and
            # never write the manifest. Net: the user thinks they
            # recovered but the orphan persists. Honest guidance is
            # the only correct fix without a dedicated --recreate-
            # manifest flow (deferred polish).
            #
            # Round-5 fix: _atomic_write_text guarantees that a
            # failed manifest write leaves the ORIGINAL manifest
            # untouched (write to tempfile + os.replace; failure
            # before replace = original safe). So the user's
            # workspace is in one of two clean states:
            #   - manifest absent + new orphaned inputs (first-write fail)
            #   - manifest unchanged + new orphaned inputs (append fail)
            # No corrupted-manifest state.
            # v1.4.4 R1 MAJOR #4 fix: restage plans + new plans land
            # in DIFFERENT recovery situations. Restage plans
            # OVERWROTE an existing staged file whose manifest row
            # is now stale; rollback the file to its snapshot so
            # the manifest's hash + body match again. New plans are
            # orphaned files (no manifest row at all) — same recovery
            # guidance as before.
            restage_failures: list[SourcePlan] = []
            new_failures: list[SourcePlan] = []
            for p in written:
                if p.restage:
                    restage_failures.append(p)
                else:
                    new_failures.append(p)
            # Best-effort restore of restage targets.
            # v1.4.4 R2 NEW MAJOR fix: three sub-cases
            #   (a) had-prior-bytes (snapshot present) → restore
            #   (b) target absent before write          → unlink
            #   (c) snapshot read failed earlier        → unrestorable
            restored_count = 0
            unlinked_count = 0
            unrestorable: list[str] = []
            for p in restage_failures:
                if p.source_id in restage_absent_targets:
                    # The new file was created from scratch (no prior
                    # state). Manifest is unchanged → unlinking the
                    # new file leaves both file AND manifest in their
                    # pre-restage state (file absent, manifest row
                    # untouched).
                    try:
                        p.target.unlink()
                        unlinked_count += 1
                    except OSError:
                        unrestorable.append(p.target.name)
                    continue
                snapshot = restage_snapshots.get(p.source_id)
                if snapshot is None:
                    unrestorable.append(p.target.name)
                    continue
                try:
                    p.target.write_bytes(snapshot)
                    restored_count += 1
                except OSError:
                    unrestorable.append(p.target.name)
            orphans = ", ".join(p.target.name for p in new_failures)
            msg_parts: list[str] = [
                f"[bsa materials] manifest write FAILED: {exc}\n",
                f"  The manifest at {manifest_path} is UNCHANGED (atomic\n",
                f"  write protects against partial-corruption).\n",
            ]
            if restage_failures:
                msg_parts.append(
                    f"  RESTAGE rollback: {restored_count} restored from "
                    f"snapshot, {unlinked_count} unlinked (no prior state); "
                    f"manifest + filesystem are consistent for these.\n"
                )
                if unrestorable:
                    msg_parts.append(
                        f"  WARNING: could not roll back: {', '.join(unrestorable)}\n"
                        f"    These files contain NEW content but the\n"
                        f"    manifest's hash row still references the\n"
                        f"    PRIOR bytes (or the file was created and\n"
                        f"    couldn't be unlinked). Re-run `bsa materials\n"
                        f"    <src> --commit --restage-changed` after\n"
                        f"    fixing the underlying problem; the restage\n"
                        f"    will re-detect the mismatch and converge.\n"
                    )
            if new_failures:
                msg_parts.append(
                    f"  ORPHANED new inputs ({len(new_failures)}): the\n"
                    f"  slug-collision backstop would skip these files on\n"
                    f"  a plain re-run. To recover:\n"
                    f"    1. Fix the underlying problem.\n"
                    f"    2. Delete the orphaned input file(s):\n"
                    f"         {orphans}\n"
                    f"    3. Re-run `bsa materials --commit` from scratch.\n"
                )
            sys.stderr.write("".join(msg_parts))
            print()
            print(f"Wrote {len(written)} file(s) under {inputs_dir}")
            print(
                f"Manifest: UNCHANGED ({exc}) — atomic write rolled back; "
                f"see stderr for recovery."
            )
            return 2

    # 6. Summary.
    print()
    print(f"Wrote {len(written)} file(s) under {inputs_dir}")
    print(f"Manifest: {manifest_path} — {manifest_action}")
    if failed:
        print()
        print(f"Failed ({len(failed)}):")
        for p, reason in failed:
            print(f"  - [{p.source_id}] {p.src.name}: {reason}")
        if unavailable_seen:
            print()
            print(
                "Hint: install optional dependencies for these formats:"
            )
            if "pdf" in unavailable_seen:
                print("  pip install pypdf")
            if "docx" in unavailable_seen:
                print("  pip install python-docx")
        return 1

    print()
    print("Next steps:")
    print(f"  1. Review {manifest_path.name} — re-tag any ReliabilityTier")
    print(f"     entries that should be T1-T4 instead of the T5 default.")
    print(f"  2. /bsa-stage 1   in Claude Code to run evidence-intake.")
    return 0


def _convert_one(
    p: SourcePlan,
    max_rows_per_table: int = _DEFAULT_MAX_ROWS_PER_TABLE,
    max_json_chars: int = 200_000,
) -> str:
    """Dispatch by kind. Pure helper for cmd_materials.

    v1.4.1 adds xlsx + csv routing.
    v1.4.2 adds tsv + json routing (graphql goes through `text`).
    v1.4.5 adds pptx + html routing.

    `max_rows_per_table` propagates the operator's --max-rows-per-table
    choice into tabular extractors (xlsx, csv, tsv).
    `max_json_chars` propagates --max-json-chars into the json
    pretty-printer body cap. Non-applicable kinds ignore the flags."""
    if p.kind == "pdf":
        return _convert_pdf(p.src)
    if p.kind == "docx":
        return _convert_docx(p.src)
    if p.kind == "text":
        return _read_text(p.src)
    if p.kind == "xlsx":
        return _convert_xlsx(p.src, max_rows_per_table=max_rows_per_table)
    if p.kind == "csv":
        return _convert_csv(p.src, max_rows=max_rows_per_table)
    if p.kind == "tsv":
        return _convert_tsv(p.src, max_rows=max_rows_per_table)
    if p.kind == "json":
        return _convert_json(p.src, max_chars=max_json_chars)
    if p.kind == "pptx":
        return _convert_pptx(p.src)
    if p.kind == "html":
        return _convert_html(p.src)
    if p.kind == "eml":
        return _convert_eml(p.src)
    if p.kind == "msg":
        return _convert_msg(p.src)
    raise ConversionFailed(f"unknown kind {p.kind!r} for {p.src.name}")


def _count_kinds(plans: list[SourcePlan]) -> str:
    """Render 'PDF: 3, DOCX: 1, TXT/MD: 2, XLSX: 4, CSV: 7, TSV: 1, JSON: 5'
    for the preview header (v1.4.1: xlsx + csv added; v1.4.2: tsv +
    json added; graphql falls under TXT/MD via the text kind;
    v1.4.5 adds pptx + html)."""
    counts: dict[str, int] = {}
    for p in plans:
        if p.skipped_reason is not None:
            continue
        counts[p.kind] = counts.get(p.kind, 0) + 1
    if not counts:
        return "all skipped"
    return ", ".join(
        f"{label}: {counts[k]}"
        for k, label in (
            ("pdf", "PDF"), ("docx", "DOCX"), ("text", "TXT/MD"),
            ("xlsx", "XLSX"), ("csv", "CSV"),
            ("tsv", "TSV"), ("json", "JSON"),
            ("pptx", "PPTX"), ("html", "HTML"),
            ("eml", "EML"), ("msg", "MSG"),
        )
        if k in counts
    )


# Canonical A50 column order. MUST match _render_draft_manifest's row
# emission AND governance/schemas/a50.schema.json
# x-bsa-csv-columns-order.order. Header validation in _upsert_draft_manifest
# uses this as the must-equal set for safe append, OR the v1.2.16
# extended variant with EffectiveDate inserted between DateOrVersion
# and Notes (sourced from x-bsa-csv-columns-order.optional_order).
_A50_HEADER = (
    "SourceID,SourceType,Title,Origin,AccessStatus,"
    "ReliabilityTier,Priority,Language,DateOrVersion,Notes"
)
_A50_HEADER_WITH_EFFECTIVE_DATE = (
    "SourceID,SourceType,Title,Origin,AccessStatus,"
    "ReliabilityTier,Priority,Language,DateOrVersion,EffectiveDate,Notes"
)
# v1.4.4 (closes lifecycle review rec #2): the hash variant extends the
# EffectiveDate variant with three append-only columns. Downstream
# csv.DictReader consumers ignore unknown fields, so existing tooling
# remains compatible. Column placement chosen so existing slice-based
# parsers (none in this codebase, but defensive) that read columns by
# index up to "EffectiveDate" continue to work.
_A50_HEADER_WITH_HASHES = (
    "SourceID,SourceType,Title,Origin,AccessStatus,"
    "ReliabilityTier,Priority,Language,DateOrVersion,EffectiveDate,"
    "ContentHash,OriginalBytes,OriginalMtimeUtc,Notes"
)
# Single source of truth for "any header we accept on read".
_ACCEPTED_A50_HEADERS = (
    _A50_HEADER,
    _A50_HEADER_WITH_EFFECTIVE_DATE,
    _A50_HEADER_WITH_HASHES,
)


class ManifestHeaderDrift(RuntimeError):
    """Raised by _upsert_draft_manifest when an existing manifest has
    a header that doesn't match _A50_HEADER. Appending under a drifted
    header would yield structurally broken rows — caller must fail
    loudly so the user can fix the manifest manually."""


def _atomic_write_text(path: Path, content: str) -> None:
    """Write `content` to `path` atomically via temp-file + rename.

    Round-5 fix: `Path.write_text` is NOT atomic — a mid-write
    OSError (disk full, NFS hiccup, etc.) leaves the destination
    truncated/corrupted. POSIX rename(2) on the same filesystem
    IS atomic; we write to a sibling tempfile then rename over
    the destination. If anything fails before the rename, the
    original `path` is untouched and the tempfile is best-effort
    cleaned up.

    Round-6 fix: `os.replace` swaps the inode wholesale. Without
    explicit metadata copy, the new file inherits the tempfile's
    mode (typically 0600 from mkstemp) — losing the original's
    mode bits / ACL. We `os.chmod()` the tempfile to match the
    original's mode BEFORE the replace, so the user's permission
    intent (e.g., 0644 for a manifest committed to git, 0664 for
    group-shared workspace) survives the atomic update. We do NOT
    preserve uid/gid (would require root in most cases).
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    # Capture original mode if the destination already exists — we
    # restore it on the tempfile before replace so the new inode
    # carries the same permission bits.
    orig_mode: Optional[int] = None
    try:
        orig_mode = path.stat().st_mode & 0o7777
    except OSError:
        pass  # file doesn't exist yet; new mode = umask default
    # Use mkstemp in the SAME directory so the rename is same-filesystem
    # (atomic). Default tempdir would be `/tmp` and rename across mounts
    # falls back to copy + unlink — not atomic.
    import tempfile  # local — only used here
    fd, tmp_name = tempfile.mkstemp(
        dir=str(parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        if orig_mode is not None:
            try:
                os.chmod(tmp_name, orig_mode)
            except OSError:
                pass  # best-effort; chmod failure is not write failure
        # os.replace is the documented atomic-on-same-fs primitive
        # (and works on Windows too — beats Path.rename which has
        # different cross-platform semantics).
        os.replace(tmp_name, str(path))
    except OSError:
        # Best-effort cleanup; re-raise to caller.
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _upsert_draft_manifest(
    manifest_path: Path, written: list[SourcePlan], src_dir_root: Path
) -> str:
    """Append new draft rows to an existing source_manifest.csv (or
    create fresh). Returns a one-line description of what happened
    for the summary line.

    Pre-condition (verified by cmd_materials pre-flight, NOT
    re-checked here to keep the function single-responsibility):
    if manifest_path exists, its header matches _A50_HEADER. The
    pre-flight ensures we never reach this function with a drifted
    manifest, so we can safely append without re-validating.

    Atomicity (round-5 fix): the actual file replacement uses
    `_atomic_write_text` (tempfile + os.replace), so a mid-write
    OSError leaves the original manifest untouched rather than
    truncated.
    """
    if manifest_path.is_file():
        # v1.4.4: utf-8-sig swallows any BOM the spreadsheet round-trip
        # introduced — same robustness fix _verify_manifest got in
        # v1.4.3 R1. Without -sig, a BOM-prefixed manifest's first
        # column reads as "﻿SourceID" and the header check fails.
        existing = manifest_path.read_text(encoding="utf-8-sig")
        existing_lines = existing.splitlines()
        # v1.4.4 R2 NEW MAJOR fix: csv-parse the header here too.
        # Pre-flight normalizes quoting before its set check, but
        # this function did `existing_lines[0].strip()` which left
        # quoted headers (`"SourceID","SourceType",...`) intact. The
        # quoted form is NOT in _ACCEPTED_A50_HEADERS, so include_eff
        # / include_hashes both evaluated False → appended rows had
        # base-shape (no EffectiveDate / hashes) under a quoted-hash-
        # shape header → column count mismatch on every row.
        import csv as _csv  # lazy
        first_line = existing_lines[0] if existing_lines else ""
        try:
            parsed_fields = next(_csv.reader(io.StringIO(first_line)))
            existing_header = ",".join(parsed_fields).strip()
        except (StopIteration, _csv.Error):
            existing_header = first_line.strip()
        # v1.2.16 / v1.4.4: align new rows to the existing header's
        # shape. Pre-flight already validated the header is one of the
        # three accepted shapes; we just need to mirror that shape so
        # column counts match.
        include_eff = existing_header in (
            _A50_HEADER_WITH_EFFECTIVE_DATE, _A50_HEADER_WITH_HASHES,
        )
        include_hashes = existing_header == _A50_HEADER_WITH_HASHES
        # v1.4.4 --restage-changed: split written into restage (in-
        # place SID replacement) + new (append). Restaged rows REPLACE
        # the existing line for that SID; new rows append at the end.
        restage_plans = [p for p in written if p.restage]
        new_plans = [p for p in written if not p.restage]
        if restage_plans:
            # v1.4.4 R1 MAJOR #2 fix: parse via stdlib csv so a
            # quoted SourceID (`"S-007"`) is matched correctly.
            # Previous regex `^([^,\"]+)` left quoted cells unmatched
            # AND the loop reported "updated N rows" anyway — silent
            # data loss masked as success. We now fail loudly when
            # any restage SID can't be located.
            #
            # v1.4.4 R1 MAJOR #1 fix: preserve every operator-curated
            # cell (ReliabilityTier, Priority, EffectiveDate, Notes,
            # ...). Only the hash trio + Title + Origin + SourceType
            # are source-derived; everything else stays as the
            # operator left it after the stage-1 review pass.
            import csv as _csv  # lazy
            sid_to_plan: dict[str, SourcePlan] = {
                p.source_id: p for p in restage_plans
            }
            try:
                src_reader = _csv.DictReader(io.StringIO(existing))
                src_fieldnames = src_reader.fieldnames or []
                src_rows = list(src_reader)
            except _csv.Error as exc:
                raise OSError(
                    f"cannot parse existing manifest as CSV: {exc}"
                ) from exc
            updated_sids: set[str] = set()
            today = _today_iso()
            for row in src_rows:
                sid = (row.get("SourceID") or "").strip()
                if sid not in sid_to_plan:
                    continue
                plan = sid_to_plan[sid]
                # Re-derive ONLY source-derived columns. Title +
                # Origin can change if the file was renamed under
                # src_dir; SourceType heuristic re-runs against the
                # new staged-file slug.
                # v1.4.5 R1 MAJOR #3 fix: include `pptx` in the
                # `document` bucket so a restaged PPTX row keeps its
                # SourceType (was incorrectly demoted to `process_note`
                # because the v1.4.5 kind addition wasn't threaded
                # through this code path).
                # v1.4.6: same fix forward for eml/msg → email_thread.
                slug_lower = plan.target.stem.lower()
                if "interview" in slug_lower or "transcript" in slug_lower:
                    stype = "interview_transcript"
                elif plan.kind in ("eml", "msg"):
                    stype = "email_thread"
                elif plan.kind in ("pdf", "docx", "pptx"):
                    stype = "document"
                else:
                    stype = "process_note"
                row["SourceType"] = stype
                row["Title"] = plan.src.stem
                row["Origin"] = plan.origin_rel or str(plan.src)
                # Hash trio — always overwrite (this is the whole
                # point of restage). Empty string when plan didn't
                # populate (e.g., src unreadable mid-flight).
                if "ContentHash" in src_fieldnames:
                    row["ContentHash"] = plan.content_hash or ""
                if "OriginalBytes" in src_fieldnames:
                    row["OriginalBytes"] = (
                        str(plan.original_bytes)
                        if plan.original_bytes is not None else ""
                    )
                if "OriginalMtimeUtc" in src_fieldnames:
                    row["OriginalMtimeUtc"] = plan.original_mtime_utc or ""
                # DateOrVersion: bump to today so freshness_audit
                # reflects the restage event. Operator can override
                # in the same review pass that re-tags reliability.
                row["DateOrVersion"] = today
                updated_sids.add(sid)
            missing_sids = set(sid_to_plan.keys()) - updated_sids
            if missing_sids:
                raise OSError(
                    f"restage targets not found in manifest: "
                    f"{sorted(missing_sids)}. Manifest update aborted "
                    f"to prevent silent data loss; the staged input "
                    f"file(s) on disk may already reflect the new "
                    f"content. Re-run after manually adding rows for "
                    f"the missing SourceID(s)."
                )
            # v1.4.4 R2 NEW MINOR fix: contract is "row VALUES are
            # preserved; quoting style is normalized to QUOTE_MINIMAL".
            # Cosmetic QUOTE_ALL from a spreadsheet round-trip becomes
            # minimal-quoted (only cells containing comma / quote /
            # newline get quoted) on restage rewrite. Cells with
            # operator-meaningful quoting (commas inside Notes, etc.)
            # still get correctly quoted by QUOTE_MINIMAL — only the
            # cosmetic "everything quoted for safety" gets lost.
            buf = io.StringIO()
            writer = _csv.DictWriter(
                buf, fieldnames=src_fieldnames,
                quoting=_csv.QUOTE_MINIMAL,
            )
            writer.writeheader()
            writer.writerows(src_rows)
            merged = buf.getvalue()
        else:
            merged = existing.rstrip("\n") + "\n"
        if new_plans:
            new_rows = _render_draft_manifest(
                new_plans, src_dir_root,
                include_effective_date=include_eff,
                include_hashes=include_hashes,
            )
            # Drop the header from new_rows (line 0).
            new_body_lines = new_rows.splitlines()[1:]
            if not merged.endswith("\n"):
                merged = merged + "\n"
            merged = merged + "\n".join(new_body_lines) + "\n"
        _atomic_write_text(manifest_path, merged)
        action_parts: list[str] = []
        if restage_plans:
            action_parts.append(f"updated {len(restage_plans)} restaged row(s)")
        if new_plans:
            action_parts.append(f"appended {len(new_plans)} new draft row(s)")
        return "; ".join(action_parts) or "manifest unchanged"
    # v1.4.4: new manifests get hash columns by DEFAULT — operators
    # creating a fresh workspace today benefit from content-change
    # detection without an opt-in flag. Existing manifests keep their
    # shape (handled above).
    new_rows = _render_draft_manifest(
        written, src_dir_root, include_hashes=True,
    )
    _atomic_write_text(manifest_path, new_rows)
    return f"created with {len(written)} draft row(s)"
