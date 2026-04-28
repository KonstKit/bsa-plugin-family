"""Tests for v1.4.1 bsa materials xlsx/csv extractors + --max-mb override.

Closes the call-data staging gap (xlsx + csv). Pre-v1.4.1 `bsa materials`
classified xlsx/csv as `unsupported` and the operator had to pre-
convert externally. v1.4.1 adds `_convert_xlsx` (openpyxl) +
`_convert_csv` (stdlib) + raises the per-file size cap from a hard
constant to a CLI-overridable `--max-mb` flag.

Coverage:
  - Extension map includes xlsx + csv.
  - _convert_xlsx happy path (single sheet, header + data rows).
  - _convert_xlsx multi-sheet handling.
  - _convert_xlsx skips hidden sheets.
  - _convert_xlsx truncates oversized sheets with a footer note.
  - _convert_csv happy path (header + data rows).
  - _convert_csv truncates oversized files with a footer note.
  - _convert_csv encoding fallback (latin-1 when not UTF-8).
  - _render_markdown_table escapes pipe characters.
  - _render_markdown_table pads ragged rows to header width.
  - cmd_materials honors --max-mb override (large file no longer too-big).
  - cmd_materials honors --max-rows-per-table override (truncation respects it).
"""

from __future__ import annotations

import csv
import io
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---- Extension map -----------------------------------------------------


def test_extension_map_includes_xlsx_and_csv() -> None:
    from scripts._bsa_cli_materials import _EXT_TO_KIND
    assert _EXT_TO_KIND.get(".xlsx") == "xlsx"
    assert _EXT_TO_KIND.get(".csv") == "csv"


# ---- _convert_xlsx -----------------------------------------------------


def _make_xlsx(tmp_path: Path, sheets: dict[str, list[list[str]]]) -> Path:
    """Create a real .xlsx file with the given sheets dict (name → rows)."""
    from openpyxl import Workbook
    wb = Workbook()
    # Drop the default sheet, replace with caller's set.
    wb.remove(wb.active)
    for sheet_name, rows in sheets.items():
        ws = wb.create_sheet(sheet_name)
        for row in rows:
            ws.append(row)
    p = tmp_path / "test.xlsx"
    wb.save(str(p))
    return p


def test_convert_xlsx_happy_path(tmp_path: Path) -> None:
    from scripts._bsa_cli_materials import _convert_xlsx
    p = _make_xlsx(tmp_path, {
        "Sheet1": [
            ["Name", "Priority", "Notes"],
            ["Order Inquiry", "1", "Top priority"],
            ["Delivery Status", "2", ""],
        ],
    })
    out = _convert_xlsx(p)
    assert "## Sheet: Sheet1" in out
    assert "| Name | Priority | Notes |" in out
    assert "| Order Inquiry | 1 | Top priority |" in out
    # Empty cell rendered as em-dash.
    assert "| Delivery Status | 2 | — |" in out


def test_convert_xlsx_multi_sheet(tmp_path: Path) -> None:
    from scripts._bsa_cli_materials import _convert_xlsx
    p = _make_xlsx(tmp_path, {
        "First": [["A", "B"], ["1", "2"]],
        "Second": [["X", "Y"], ["foo", "bar"]],
    })
    out = _convert_xlsx(p)
    assert "## Sheet: First" in out
    assert "## Sheet: Second" in out
    # Order preserved.
    assert out.index("## Sheet: First") < out.index("## Sheet: Second")


def test_convert_xlsx_skips_hidden_sheets(tmp_path: Path) -> None:
    from openpyxl import Workbook
    from scripts._bsa_cli_materials import _convert_xlsx
    wb = Workbook()
    wb.remove(wb.active)
    visible = wb.create_sheet("Visible")
    visible.append(["A", "B"])
    visible.append(["1", "2"])
    hidden = wb.create_sheet("Secret")
    hidden.sheet_state = "hidden"
    hidden.append(["should", "not", "appear"])
    p = tmp_path / "test_hidden.xlsx"
    wb.save(str(p))
    out = _convert_xlsx(p)
    assert "## Sheet: Visible" in out
    assert "## Sheet: Secret" not in out
    assert "should" not in out


def test_convert_xlsx_truncates_with_footer(tmp_path: Path) -> None:
    from scripts._bsa_cli_materials import _convert_xlsx
    rows = [["col1", "col2"]] + [[f"r{i}", "v"] for i in range(50)]
    p = _make_xlsx(tmp_path, {"Big": rows})
    out = _convert_xlsx(p, max_rows_per_table=10)
    # Header + 9 data rows shown (header counted in cap).
    # Truncation footer must be present.
    assert "truncated" in out
    assert "10" in out  # cap value
    assert "51" in out  # total row count (header + 50 data)


def test_convert_xlsx_unavailable_when_openpyxl_missing(monkeypatch, tmp_path: Path) -> None:
    """If openpyxl is not importable, ConversionUnavailable is raised."""
    from scripts._bsa_cli_materials import _convert_xlsx, ConversionUnavailable
    # Block openpyxl import by stubbing builtins.__import__.
    import builtins
    real_import = builtins.__import__

    def stub_import(name, *args, **kwargs):
        if name == "openpyxl":
            raise ImportError("simulated missing openpyxl")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", stub_import)
    # Path doesn't matter — we fail at import time before touching disk.
    with pytest.raises(ConversionUnavailable, match="openpyxl"):
        _convert_xlsx(tmp_path / "anything.xlsx")


# ---- _convert_csv ------------------------------------------------------


def test_convert_csv_happy_path(tmp_path: Path) -> None:
    from scripts._bsa_cli_materials import _convert_csv
    p = tmp_path / "test.csv"
    p.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\n", encoding="utf-8")
    out = _convert_csv(p)
    assert "| name | age | city |" in out
    assert "| Alice | 30 | NYC |" in out
    assert "| Bob | 25 | LA |" in out


def test_convert_csv_truncates_with_footer(tmp_path: Path) -> None:
    from scripts._bsa_cli_materials import _convert_csv
    rows = ["col1,col2"] + [f"row{i},v" for i in range(50)]
    p = tmp_path / "big.csv"
    p.write_text("\n".join(rows), encoding="utf-8")
    out = _convert_csv(p, max_rows=10)
    assert "truncated" in out
    assert "10" in out
    assert "50" in out


def test_convert_csv_encoding_fallback(tmp_path: Path) -> None:
    """Latin-1 file (not valid UTF-8) reads via fallback + footer note."""
    from scripts._bsa_cli_materials import _convert_csv
    p = tmp_path / "latin.csv"
    # 0xe9 is "é" in latin-1 but invalid UTF-8 lead byte.
    raw = b"name,note\nCaf\xe9,coffee shop\n"
    p.write_bytes(raw)
    out = _convert_csv(p)
    assert "Caf" in out
    assert "latin-1 fallback" in out


def test_convert_csv_handles_quoted_commas(tmp_path: Path) -> None:
    """RFC4180 quoted commas/newlines must not split fields."""
    from scripts._bsa_cli_materials import _convert_csv
    p = tmp_path / "quoted.csv"
    p.write_text(
        'name,note\n"Smith, Jr.","says ""hi""\n"\n',
        encoding="utf-8",
    )
    out = _convert_csv(p)
    assert "Smith, Jr." in out


def test_convert_csv_empty_file(tmp_path: Path) -> None:
    from scripts._bsa_cli_materials import _convert_csv
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    out = _convert_csv(p)
    assert "empty" in out


def test_convert_csv_late_invalid_utf8_falls_back_to_latin1(tmp_path: Path) -> None:
    """v1.4.1 R2 fix (Codex MAJOR): pre-fix the encoding probe read
    only 4 KB; CSVs with invalid UTF-8 bytes appearing AFTER that
    boundary slipped past the probe + crashed mid-iteration without
    fallback. Post-fix: streaming try/retry — UTF-8 attempt fails
    fast on any invalid byte, retry with latin-1 from scratch.

    Test writes ~6 KB of valid UTF-8 + a latin-1 byte at offset 5000
    (well past the 4 KB probe boundary)."""
    from scripts._bsa_cli_materials import _convert_csv
    p = tmp_path / "late_invalid.csv"
    # Build content: header + ~5 KB of ASCII rows + 1 row with a
    # latin-1 byte (0xe9 = "é") + more rows.
    header = b"name,note\n"
    pre = b"".join(
        f"row{i},filler-text-to-pad-past-4KB-probe-boundary\n".encode("ascii")
        for i in range(150)  # ~5500 bytes
    )
    bad_row = b"Caf\xe9,latin-1-encoded-cafe-name-after-5000-bytes\n"
    post = b"row_after,more-data\n"
    p.write_bytes(header + pre + bad_row + post)
    assert p.stat().st_size > 5000, "test fixture too small to trigger the regression"
    out = _convert_csv(p)
    assert "latin-1 fallback" in out, (
        "fallback footer note missing — encoding-fallback path didn't fire"
    )
    assert "Caf" in out, "latin-1 row not in output — fallback didn't decode it"
    assert "row_after" in out, "rows after the bad byte missing — iteration didn't recover"


def test_convert_csv_streams_does_not_load_full_file(tmp_path: Path) -> None:
    """v1.4.1 R1 fix: CSV reader streams. Pre-fix used read_text +
    list(reader) — a 30MB CSV expanded to 100-200MB Python objects
    in RAM before the cap kicked in. Post-fix iterates lazily and
    keeps only header + max_rows in memory, counting the rest.

    Verify by writing a CSV with 1M data rows + asking for only 5,
    measuring peak `rows_kept` size INDIRECTLY via the truncation
    footer (which must report `1000000 total` regardless of cap).
    Sized small enough that the test stays fast (~1.5 sec on stock
    laptop) but big enough to demonstrate the streaming win — pre-
    fix would have allocated ~150MB on this input."""
    p = tmp_path / "big.csv"
    rows_to_write = 100_000  # smaller than 1M but still meaningful
    with p.open("w", encoding="utf-8") as fh:
        fh.write("col1,col2\n")
        for i in range(rows_to_write):
            fh.write(f"r{i},v\n")
    from scripts._bsa_cli_materials import _convert_csv
    # Track tracemalloc PEAK allocation during the conversion call.
    # v1.4.2 R2 fix (Codex MAJOR on the test itself): pre-fix used
    # `take_snapshot()` AFTER the call, which only sees still-live
    # allocations — a transient full-file buffer freed before the
    # snapshot would silently pass. `get_traced_memory()[1]` returns
    # the PEAK allocation since `tracemalloc.start()`, which catches
    # transient allocations.
    import tracemalloc
    tracemalloc.start()
    out = _convert_csv(p, max_rows=5)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    # Footer reports the full row count.
    assert f"{rows_to_write} total" in out
    # Only first 5 data rows materialized in the output.
    assert "| r0 | v |" in out
    assert "| r4 | v |" in out
    assert "| r5 | v |" not in out
    # RAM check: PEAK allocation should be << what the full
    # file would cost. The CSV file on disk is ~1MB; the full-
    # buffer-and-list approach would peak at ~5-10MB. Streaming
    # should peak at <1MB (just the header + 5 kept rows + the
    # tracemalloc machinery itself).
    peak_kb = peak / 1024
    file_size_kb = p.stat().st_size / 1024
    assert peak_kb < file_size_kb, (
        f"streaming reader allocated {peak_kb:.0f} KB PEAK — "
        f"more than the full {file_size_kb:.0f} KB file. The streaming "
        f"R1 fix has regressed; reader is materializing the whole file."
    )


def test_render_markdown_table_preserves_literal_br(tmp_path: Path) -> None:
    """v1.4.1 R1 fix: a cell containing literal `<br>` text must be
    distinguishable from a cell with a real newline (which we collapse
    to `<br>`). Pre-fix both rendered as identical `<br>` — fidelity
    loss. Post-fix: angle-brackets entity-escaped before newline
    collapse, so literal `<br>` becomes `&lt;br&gt;` and only the
    injected `<br>` (from \\n) stays as a literal tag."""
    from scripts._bsa_cli_materials import _render_markdown_table
    rows = [
        ["col1", "col2"],
        ["actual\nnewline", "literal <br> tag"],
    ]
    out = _render_markdown_table(rows)
    # Real newline → literal <br> in output.
    assert "actual<br>newline" in out
    # Literal <br> in source → entity-escaped (so distinguishable).
    assert "&lt;br&gt;" in out
    # And the entity escape didn't accidentally also catch the
    # injected <br> from newline collapse.
    assert "actual&lt;br&gt;newline" not in out


def test_render_markdown_table_preserves_other_html_brackets() -> None:
    """Companion to the <br> test: any `<...>` content (not just
    <br>) gets entity-escaped, so source fidelity is preserved
    regardless of the specific tag the cell contains."""
    from scripts._bsa_cli_materials import _render_markdown_table
    rows = [
        ["html", "math"],
        ["<bold>text</bold>", "x < y > z"],
    ]
    out = _render_markdown_table(rows)
    assert "&lt;bold&gt;text&lt;/bold&gt;" in out
    assert "x &lt; y &gt; z" in out


# ---- _render_markdown_table -------------------------------------------


def test_render_markdown_table_escapes_pipes() -> None:
    from scripts._bsa_cli_materials import _render_markdown_table
    rows = [["col1", "col2"], ["foo|bar", "baz"]]
    out = _render_markdown_table(rows)
    assert "foo\\|bar" in out
    assert "| baz |" in out


def test_render_markdown_table_pads_ragged_rows() -> None:
    """Header has 3 columns; row with 1 cell gets padded."""
    from scripts._bsa_cli_materials import _render_markdown_table
    rows = [["a", "b", "c"], ["x"]]
    out = _render_markdown_table(rows)
    lines = out.splitlines()
    # Last line should have 3 cells (one filled, two padded with em-dash).
    assert lines[-1].count("|") == 4  # 3 cells = 4 separators
    assert "—" in lines[-1]


def test_render_markdown_table_empty_rows() -> None:
    from scripts._bsa_cli_materials import _render_markdown_table
    assert _render_markdown_table([]) == ""


# ---- cmd_materials CLI integration ------------------------------------


def _make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "analysis").mkdir(parents=True)
    return ws


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "bsa_cli.py"), *args],
        capture_output=True, text=True, check=False,
    )


def test_cli_materials_xlsx_dry_run_lists_xlsx_as_supported(tmp_path: Path) -> None:
    """End-to-end: a directory with an xlsx file shows up as 'XLSX: 1'
    in the dry-run preview, NOT as 'unsupported'."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    p = _make_xlsx(src, {"Data": [["a", "b"], ["1", "2"]]})
    res = _run_cli(f"--workspace={ws}", "materials", str(src))
    assert res.returncode == 0, f"dry-run failed: {res.stderr}"
    assert "XLSX: 1" in res.stdout
    assert "unsupported" not in res.stdout.lower() or "0 unsupported" in res.stdout


def test_cli_materials_csv_commit_writes_markdown_table(tmp_path: Path) -> None:
    """End-to-end: a csv source committed via --commit lands as a .md
    file with the markdown table body."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    csv_path = src / "data.csv"
    csv_path.write_text("name,priority\nFoo,1\nBar,2\n", encoding="utf-8")
    res = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res.returncode == 0, f"commit failed: {res.stderr}"
    inputs_dir = ws / "analysis" / "proposals" / "stage1" / "inputs"
    md_files = list(inputs_dir.glob("source_001_*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text(encoding="utf-8")
    assert "| name | priority |" in content
    assert "| Foo | 1 |" in content


def test_cli_materials_max_mb_raises_cap(tmp_path: Path) -> None:
    """A large file (40 MB) is too-large at default 25MB cap but
    in-bounds at --max-mb=50."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    big = src / "big.csv"
    # Write ~30 MB of CSV (header + many rows).
    with big.open("w", encoding="utf-8") as fh:
        fh.write("col1,col2\n")
        for i in range(800_000):  # ~30 MB
            fh.write(f"row_{i},value_with_filler_text_xyzabc123\n")
    size_mb = big.stat().st_size / 1024 / 1024
    assert size_mb > 25, f"test file only {size_mb:.1f} MB — bump the row count"

    # Default cap: too-large.
    res = _run_cli(f"--workspace={ws}", "materials", str(src))
    assert "too-large" in res.stdout.lower() or "Too large" in res.stdout

    # Raised cap: shows up in plan as XLSX/CSV (truncated to row cap).
    res2 = _run_cli(
        f"--workspace={ws}", "materials", str(src), "--max-mb=50",
        "--max-rows-per-table=10",
    )
    assert res2.returncode == 0, f"--max-mb=50 dry-run failed: {res2.stderr}"
    assert "CSV: 1" in res2.stdout


def test_cli_materials_max_rows_per_table_truncates(tmp_path: Path) -> None:
    """--max-rows-per-table=N caps the rendered table at N rows;
    truncation footer mentions the cap value."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    csv_path = src / "rows.csv"
    rows = ["col1,col2"] + [f"r{i},v" for i in range(100)]
    csv_path.write_text("\n".join(rows), encoding="utf-8")
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src), "--commit",
        "--max-rows-per-table=20",
    )
    assert res.returncode == 0, f"commit failed: {res.stderr}"
    inputs_dir = ws / "analysis" / "proposals" / "stage1" / "inputs"
    md_files = list(inputs_dir.glob("source_001_*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text(encoding="utf-8")
    assert "truncated" in content
    assert "20" in content


# ---- v1.4.2: tsv + json + graphql ------------------------------------


def test_extension_map_includes_tsv_json_graphql() -> None:
    from scripts._bsa_cli_materials import _EXT_TO_KIND
    assert _EXT_TO_KIND.get(".tsv") == "tsv"
    assert _EXT_TO_KIND.get(".json") == "json"
    # graphql classifies as text (SDL is human-readable).
    assert _EXT_TO_KIND.get(".graphql") == "text"


def test_convert_tsv_happy_path(tmp_path: Path) -> None:
    """TSV reuses the csv streaming reader with delimiter='\\t'.
    Same markdown-table output, same encoding-fallback contract."""
    from scripts._bsa_cli_materials import _convert_tsv
    p = tmp_path / "test.tsv"
    p.write_text("col1\tcol2\nfoo\tbar\nbaz\tqux\n", encoding="utf-8")
    out = _convert_tsv(p)
    assert "| col1 | col2 |" in out
    assert "| foo | bar |" in out
    assert "| baz | qux |" in out


def test_convert_tsv_truncation_footer_says_tsv(tmp_path: Path) -> None:
    """When tsv truncates, the footer should reflect tsv (not csv)
    in the diagnostic message — operator wouldn't expect the wrong
    format name in their feedback."""
    from scripts._bsa_cli_materials import _convert_tsv
    rows = ["a\tb"] + [f"r{i}\tv" for i in range(50)]
    p = tmp_path / "big.tsv"
    p.write_text("\n".join(rows), encoding="utf-8")
    out = _convert_tsv(p, max_rows=5)
    assert "truncated" in out
    assert "5" in out
    assert "50" in out


def test_convert_tsv_streaming_does_not_load_full_file(tmp_path: Path) -> None:
    """Streaming property inherits from _convert_csv refactor."""
    from scripts._bsa_cli_materials import _convert_tsv
    p = tmp_path / "big.tsv"
    rows_to_write = 50_000
    with p.open("w", encoding="utf-8") as fh:
        fh.write("c1\tc2\n")
        for i in range(rows_to_write):
            fh.write(f"r{i}\tv\n")
    out = _convert_tsv(p, max_rows=5)
    assert f"{rows_to_write} total" in out
    assert "| r0 | v |" in out
    assert "| r5 | v |" not in out


def test_convert_json_object_root(tmp_path: Path) -> None:
    """Top-level object: structure summary lists keys; body is the
    pretty-printed json wrapped in a code fence."""
    from scripts._bsa_cli_materials import _convert_json
    p = tmp_path / "obj.json"
    p.write_text('{"name": "alice", "age": 30, "tags": ["a", "b"]}', encoding="utf-8")
    out = _convert_json(p)
    assert "## Structure summary" in out
    assert "top-level type: object" in out
    assert "'name'" in out
    assert "'age'" in out
    assert "'tags'" in out
    # Body is in a ```json``` fence.
    assert "```json" in out
    assert '"alice"' in out


def test_convert_json_array_root(tmp_path: Path) -> None:
    """Top-level array: structure summary reports item count + first-
    item key sample (when items are dicts)."""
    from scripts._bsa_cli_materials import _convert_json
    p = tmp_path / "arr.json"
    p.write_text(
        '[{"id": 1, "label": "x"}, {"id": 2, "label": "y"}, {"id": 3, "label": "z"}]',
        encoding="utf-8",
    )
    out = _convert_json(p)
    assert "top-level type: array" in out
    assert "top-level items (count: 3)" in out
    assert "'id'" in out
    assert "'label'" in out


def test_convert_json_truncation_footer(tmp_path: Path) -> None:
    """A large json body gets truncated to max_chars with a footer
    pointing at --max-json-chars."""
    from scripts._bsa_cli_materials import _convert_json
    p = tmp_path / "big.json"
    big_obj = {"items": [{"id": i, "data": "x" * 100} for i in range(500)]}
    import json as _json
    p.write_text(_json.dumps(big_obj), encoding="utf-8")
    out = _convert_json(p, max_chars=500)
    assert "truncated" in out
    assert "max-json-chars" in out


def test_convert_json_malformed_raises_conversion_failed(tmp_path: Path) -> None:
    """Malformed JSON should NOT be silently accepted — operator
    must fix the source before pipeline ingest. ConversionFailed."""
    from scripts._bsa_cli_materials import _convert_json, ConversionFailed
    p = tmp_path / "bad.json"
    p.write_text("{not valid json: at all", encoding="utf-8")
    with pytest.raises(ConversionFailed, match="json parse failed"):
        _convert_json(p)


def test_convert_json_empty_file(tmp_path: Path) -> None:
    from scripts._bsa_cli_materials import _convert_json
    p = tmp_path / "empty.json"
    p.write_text("", encoding="utf-8")
    out = _convert_json(p)
    assert "empty" in out


def test_convert_json_streams_does_not_materialize_full_body(tmp_path: Path) -> None:
    """v1.4.2 R1 fix (Codex MAJOR): pre-fix `_json.dumps(...)` built
    the entire pretty-printed string in memory before truncation
    fired. A 50 MB minified json → ~200 MB Python string allocation
    even when `--max-json-chars=10000` was set. Post-fix uses
    `JSONEncoder.iterencode` and stops accumulating once max_chars
    is hit.

    The doc tree itself is still in memory (json doesn't have a
    streaming PARSER in stdlib — adding ijson would be a heavy dep
    and is out of scope). So the win is on the OUTPUT side: pre-fix
    PEAK was `doc_tree + FULL_pretty_body` (~3-5× file size); post-
    fix PEAK is `doc_tree + max_chars` (cap typically 200KB; here
    500B). Test compares PEAK allocation (not live snapshot — peak
    catches transient allocations the snapshot would miss; v1.4.2
    R2 fix per Codex MAJOR finding on the test itself)."""
    from scripts._bsa_cli_materials import _convert_json
    import json as _json
    import tracemalloc

    p = tmp_path / "big.json"
    big = {"items": [{"id": i, "data": "x" * 200} for i in range(5000)]}
    p.write_text(_json.dumps(big), encoding="utf-8")

    # Simulate the pre-fix pattern: read + parse + FULL dumps.
    # tracemalloc.get_traced_memory() returns (current, peak). We
    # take peak so a transient full-body allocation doesn't get
    # masked by the GC freeing it before snapshot.
    tracemalloc.start()
    text = p.read_text(encoding="utf-8")
    doc = _json.loads(text)
    full_body = _json.dumps(doc, indent=2, ensure_ascii=False)
    _, pre_fix_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    pre_fix_peak_kb = pre_fix_peak / 1024
    full_body_kb = len(full_body) / 1024

    # Post-fix pattern: convert with tiny cap (500 chars).
    tracemalloc.start()
    out = _convert_json(p, max_chars=500)
    _, post_fix_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    post_fix_peak_kb = post_fix_peak / 1024

    # Output is bounded by max_chars (+ markdown overhead).
    assert "truncated" in out
    assert "max-json-chars" in out

    # Streaming win: post-fix PEAK should be LOWER than pre-fix
    # PEAK by at least the full pretty-body size (we no longer
    # allocate that string at all). Headroom factor: 0.5× of
    # full-body size — robust against tracemalloc variance.
    expected_savings_kb = full_body_kb * 0.5
    actual_savings_kb = pre_fix_peak_kb - post_fix_peak_kb
    assert actual_savings_kb > expected_savings_kb, (
        f"streaming json reader saved only {actual_savings_kb:.0f} KB "
        f"of PEAK allocation vs the pre-fix dumps pattern "
        f"(expected > {expected_savings_kb:.0f} KB = 50% of full body "
        f"{full_body_kb:.0f} KB). "
        f"pre_peak={pre_fix_peak_kb:.0f}KB post_peak={post_fix_peak_kb:.0f}KB. "
        f"Encoder may be transiently buffering the full document."
    )


def test_convert_json_array_of_scalars_emits_sample(tmp_path: Path) -> None:
    """v1.4.2 R1 fix (Codex MINOR): pre-fix arrays of scalars (e.g.
    `[1, 2, 3]`) got count-only summaries. Post-fix: scalar items
    sample reports type + value preview."""
    from scripts._bsa_cli_materials import _convert_json
    p = tmp_path / "scalars.json"
    p.write_text("[1, 2, 3, 4, 5]", encoding="utf-8")
    out = _convert_json(p)
    assert "top-level type: array" in out
    assert "top-level items (count: 5)" in out
    assert "first-item type: int" in out
    assert "value preview: 1" in out


def test_convert_json_array_of_arrays_emits_sample(tmp_path: Path) -> None:
    """v1.4.2 R1 fix (Codex MINOR): array-of-arrays sample reports
    inner length so operator knows the matrix shape without scrolling."""
    from scripts._bsa_cli_materials import _convert_json
    p = tmp_path / "matrix.json"
    p.write_text('[[1, 2, 3], [4, 5, 6], [7, 8, 9]]', encoding="utf-8")
    out = _convert_json(p)
    assert "first-item type: array (length: 3)" in out


def test_convert_json_array_of_strings_emits_sample(tmp_path: Path) -> None:
    """Companion: array of strings (event labels, tags, etc.)."""
    from scripts._bsa_cli_materials import _convert_json
    p = tmp_path / "tags.json"
    p.write_text('["tag1", "tag2", "tag3"]', encoding="utf-8")
    out = _convert_json(p)
    assert "first-item type: str" in out
    assert "tag1" in out


def test_convert_json_scalar_root(tmp_path: Path) -> None:
    """Scalar at the root (string / number / null) — summary should
    report the type + a value preview."""
    from scripts._bsa_cli_materials import _convert_json
    p = tmp_path / "scalar.json"
    p.write_text('"just a string at root"', encoding="utf-8")
    out = _convert_json(p)
    assert "top-level type: str" in out
    assert "value preview" in out
    assert "just a string at root" in out


def test_cli_materials_tsv_dry_run_lists_tsv_as_supported(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    p = src / "data.tsv"
    p.write_text("a\tb\n1\t2\n", encoding="utf-8")
    res = _run_cli(f"--workspace={ws}", "materials", str(src))
    assert res.returncode == 0, f"dry-run failed: {res.stderr}"
    assert "TSV: 1" in res.stdout


def test_cli_materials_json_commit_writes_summary_plus_body(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    p = src / "data.json"
    p.write_text('{"k": "v"}', encoding="utf-8")
    res = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res.returncode == 0, f"commit failed: {res.stderr}"
    inputs_dir = ws / "analysis" / "proposals" / "stage1" / "inputs"
    md = list(inputs_dir.glob("source_001_*.md"))[0]
    content = md.read_text(encoding="utf-8")
    assert "Structure summary" in content
    assert "top-level type: object" in content
    assert "```json" in content
    assert '"k": "v"' in content


def test_cli_materials_graphql_classifies_as_text(tmp_path: Path) -> None:
    """GraphQL SDL is human-readable; classified as text kind, no
    special converter, just verbatim read like .md/.txt."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    p = src / "schema.graphql"
    p.write_text("type Query {\n  hello: String\n}\n", encoding="utf-8")
    res = _run_cli(f"--workspace={ws}", "materials", str(src), "--commit")
    assert res.returncode == 0
    assert "TXT/MD: 1" in res.stdout
    inputs_dir = ws / "analysis" / "proposals" / "stage1" / "inputs"
    md = list(inputs_dir.glob("source_001_*.md"))[0]
    content = md.read_text(encoding="utf-8")
    # Verbatim (not wrapped in code fence — analyst can grep claims).
    assert "type Query" in content
    assert "hello: String" in content


def test_cli_materials_max_json_chars_caps_body(tmp_path: Path) -> None:
    """--max-json-chars override caps the json body length."""
    ws = _make_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    p = src / "big.json"
    p.write_text('{"big": "' + "x" * 5000 + '"}', encoding="utf-8")
    res = _run_cli(
        f"--workspace={ws}", "materials", str(src), "--commit",
        "--max-json-chars=500",
    )
    assert res.returncode == 0, f"commit failed: {res.stderr}"
    inputs_dir = ws / "analysis" / "proposals" / "stage1" / "inputs"
    md = list(inputs_dir.glob("source_001_*.md"))[0]
    content = md.read_text(encoding="utf-8")
    assert "truncated" in content
    assert "max-json-chars" in content


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
