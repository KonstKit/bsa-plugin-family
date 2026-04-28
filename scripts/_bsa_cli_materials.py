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
import io
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


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
    used: set[int] = set()
    src_pat = re.compile(r"^source_(\d{3,4})_")
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
        sid_pat = re.compile(r"^S-(\d{3,4})\b")
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


def _plan_conversions(
    src_files: list[Path],
    inputs_dir: Path,
    manifest_path: Path,
    src_dir_root: Path,
    force: bool,
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
    # Slug→existing-path map for the slug-backstop: if the manifest
    # was deleted but old `source_NNN_<slug>.md` files remain, we
    # MUST detect those by slug. Round-2 fix: when the slug matches,
    # consult the file's provenance comment to disambiguate "same
    # source, truly already staged" from "different source that
    # happens to slug-collide" (slug truncation at 40 chars or
    # heavy non-ASCII normalization can produce collisions).
    existing_by_slug: dict[str, Path] = {}
    if inputs_dir.is_dir():
        slug_pat = re.compile(r"^source_\d{3,4}_(.+)\.md$")
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
) -> str:
    """Render a draft source_manifest.csv. ReliabilityTier defaults to
    T5 (most cautious) — the user MUST re-tag during /bsa-stage 1
    review. Notes column flags this clearly so the worker sees it.

    v1.2.16: when ``include_effective_date=True`` the rendered rows
    carry an empty ``EffectiveDate`` cell (and the header includes the
    column) so an append into an existing manifest that has already
    been backfilled with the v1.2.16 optional column doesn't
    misalign. The empty cell reads as 'n/a' in freshness_audit per
    the optional_order extension contract."""
    base = [
        "SourceID", "SourceType", "Title", "Origin", "AccessStatus",
        "ReliabilityTier", "Priority", "Language", "DateOrVersion",
    ]
    cols = base + (["EffectiveDate"] if include_effective_date else []) + ["Notes"]
    out = [",".join(cols)]
    today = _today_iso()
    for p in plans:
        if p.skipped_reason is not None:
            continue
        # SourceType heuristic: "interview" anywhere in the slug → interview_transcript.
        slug_lower = p.target.stem.lower()
        if "interview" in slug_lower or "transcript" in slug_lower:
            stype = "interview_transcript"
        elif p.kind in ("pdf", "docx"):
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
        row = base_row + ([""] if include_effective_date else []) + [_csv_escape(notes)]
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


def cmd_materials(args: argparse.Namespace) -> int:
    """Stage PDF/DOCX/MD/TXT inputs into analysis/proposals/stage1/inputs/.

    Default is dry-run — prints what would be done. --commit performs
    writes. --force overwrites existing target files. --recursive
    walks subdirectories.

    Exit codes:
        0 = preview rendered (dry-run) OR all writes succeeded.
        1 = at least one file failed to convert (per-file
            ConversionFailed — corrupt PDF, encrypted DOCX, etc.) OR
            optional library missing for at least one file
            (ConversionUnavailable). Both surface in the summary
            with per-file detail; ConversionUnavailable additionally
            prints a `pip install ...` hint.
        2 = invocation / structural error: bad src dir, uninitialized
            workspace, EMPTY src dir, OR an existing source_manifest.csv
            whose header has drifted away from the canonical A50
            column order (we refuse to append unsafe rows).
    """
    # v1.3.11 split: WorkspaceState lives in bsa_cli.py; lazy import
    # avoids module-load-time circular dep.
    from scripts.bsa_cli import WorkspaceState  # lazy

    root = Path(args.workspace).resolve()
    ws = WorkspaceState(root)
    src_dir = Path(args.src_dir).resolve()

    if not src_dir.is_dir():
        sys.stderr.write(
            f"[bsa materials] source directory not found: {src_dir}\n"
        )
        return 2
    if not ws.is_initialized():
        sys.stderr.write(
            f"[bsa materials] {root} is not a BSA workspace "
            "(no analysis/ directory). Run /bsa-start in Claude "
            "Code first.\n"
        )
        return 2

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
    plans = _plan_conversions(
        supported, inputs_dir, manifest_path, src_dir, force=bool(args.force)
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
            print("Suggested next:")
            print(f"  bsa --workspace {root} materials {src_dir} --commit")
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
        existing_header = existing_lines[0].strip() if existing_lines else ""
        if existing_header not in (_A50_HEADER, _A50_HEADER_WITH_EFFECTIVE_DATE):
            sys.stderr.write(
                f"[bsa materials] existing source_manifest.csv has a non-canonical header.\n"
                f"  Expected: {_A50_HEADER}\n"
                f"        OR: {_A50_HEADER_WITH_EFFECTIVE_DATE}\n"
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
    max_rows_per_table = int(getattr(args, "max_rows_per_table", 5000))
    max_json_chars = int(getattr(args, "max_json_chars", 200_000))
    inputs_dir.mkdir(parents=True, exist_ok=True)
    written: list[SourcePlan] = []
    failed: list[tuple[SourcePlan, str]] = []
    unavailable_seen: set[str] = set()
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
        try:
            p.target.write_text(body, encoding="utf-8")
            written.append(p)
        except OSError as exc:
            failed.append((p, f"write failed: {exc}"))

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
            orphans = ", ".join(p.target.name for p in written)
            sys.stderr.write(
                f"[bsa materials] WROTE {len(written)} input file(s) "
                f"successfully, but the manifest write FAILED: {exc}\n"
                f"  The manifest at {manifest_path} is UNCHANGED (atomic\n"
                f"  write protects against partial-corruption); the new\n"
                f"  inputs are ORPHANED. The slug-collision backstop\n"
                f"  would skip these files on a plain re-run, so the\n"
                f"  manifest would not get the rows for them. To recover:\n"
                f"\n"
                f"    1. Fix the underlying problem (permissions, disk\n"
                f"       space, conflicting path).\n"
                f"    2. Delete the orphaned input file(s):\n"
                f"         {orphans}\n"
                f"    3. Re-run `bsa materials --commit` from scratch.\n"
            )
            print()
            print(f"Wrote {len(written)} file(s) under {inputs_dir}")
            print(
                f"Manifest: UNCHANGED ({exc}) — atomic write rolled back; "
                f"see stderr for orphan-input recovery."
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
    raise ConversionFailed(f"unknown kind {p.kind!r} for {p.src.name}")


def _count_kinds(plans: list[SourcePlan]) -> str:
    """Render 'PDF: 3, DOCX: 1, TXT/MD: 2, XLSX: 4, CSV: 7, TSV: 1, JSON: 5'
    for the preview header (v1.4.1: xlsx + csv added; v1.4.2: tsv +
    json added; graphql falls under TXT/MD via the text kind)."""
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
        existing = manifest_path.read_text(encoding="utf-8")
        existing_header = (existing.splitlines() or [""])[0].strip()
        # v1.2.16: align new rows to the existing header's shape.
        # Pre-flight already validated the header is one of the two
        # accepted shapes (_A50_HEADER or _A50_HEADER_WITH_EFFECTIVE_DATE);
        # we just need to mirror that shape so column counts match.
        include_eff = existing_header == _A50_HEADER_WITH_EFFECTIVE_DATE
        new_rows = _render_draft_manifest(
            written, src_dir_root, include_effective_date=include_eff,
        )
        # Drop the header from new_rows (line 0).
        new_body_lines = new_rows.splitlines()[1:]
        merged = existing.rstrip("\n") + "\n" + "\n".join(new_body_lines) + "\n"
        _atomic_write_text(manifest_path, merged)
        return f"appended {len(written)} draft row(s) to existing manifest"
    new_rows = _render_draft_manifest(written, src_dir_root)
    _atomic_write_text(manifest_path, new_rows)
    return f"created with {len(written)} draft row(s)"
