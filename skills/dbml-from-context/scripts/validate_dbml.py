#!/usr/bin/env python3
"""DBML syntax + semantic validator (v1.2.15).

The dbml-from-context sidecar's contract at
``skills/dbml-from-context/references/integration-contract.md`` defines
WHAT a well-formed `.dbml` file looks like. v1.2.11 shipped a minimal
syntax-only validator. v1.2.15 extends it with semantic checks:

Checks (all hard-fail unless `--lenient-types` is passed):
  1. File is valid UTF-8.
  2. Every ``Table <name> { ... }``, ``Enum <name> { ... }``, and
     ``TableGroup <name> { ... }`` block has matching ``{`` / ``}``
     braces (no unbalanced / nested / missing closer).
  3. Every block declares at least one body line (empty braces are
     suspicious — usually indicates a truncated paste).
  4. Every top-level ``Ref:`` statement has the shape
     ``Ref[: <name>]? <from>.<col> (>|-|<) <to>.<col>``.
  5. Every inline column-level ref annotation follows
     ``[ref: (>|-|<) <to_table>.<to_col>]`` shape.
  6. NEW (v1.2.15): every column type is one of:
       * a recognized DBML/SQL base type (integer, varchar, timestamp, etc.);
       * a parameterized form of a recognized type (varchar(255),
         decimal(10,2), char(8));
       * an Enum name declared in this same file.
     Unknown types are rejected unless `--lenient-types` is passed.
  7. NEW (v1.2.15): every ``Ref:`` (top-level OR inline) MUST resolve.
     Both sides of a top-level Ref must point at an existing
     <table>.<column> declared in this file. For inline `[ref: ...]`
     annotations, the target side must resolve. Dangling FKs are
     rejected unconditionally — they're broken regardless of the
     lenient-types flag.

What it still does NOT check (deferred):
  * Cross-file references (``[ref: > other_schema.users.id]`` with a
    database-prefix).
  * Enum-VALUE-binding (whether an inserted value belongs to the
    named enum — DBML doesn't model row data anyway).
  * Triggers / stored procedures / materialized views (out of DBML
    scope per the sidecar contract).
  * Index target resolution (``indexes { (col1, col2) }`` — column
    existence not yet verified; future work).

CLI:
  scripts/validate_dbml.py <path>
  scripts/validate_dbml.py <path> <path> ...
  scripts/validate_dbml.py --lenient-types <path>

Exit codes:
  0 — all files valid.
  1 — one or more files rejected (details on stderr).
  2 — invocation error (no paths, path not found, etc.).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional


# ------------- Block / ref regexes (unchanged from v1.2.11) -------------

# One block-opener per known DBML top-level block kind.
_BLOCK_OPENER_RE = re.compile(
    r"^\s*(?:Project|Table|Enum|TableGroup|Ref)\s+[A-Za-z_][A-Za-z0-9_.]*"
    r"\s*(?:\[[^\]]*\])?\s*\{"
)

# Top-level Ref statement (NOT a Ref block): `Ref: ...` or `Ref <name>: ...`.
# Intentionally tolerant on cardinality / table-qualifier variations.
_TOPLEVEL_REF_STMT_RE = re.compile(
    r"^\s*Ref(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*:\s*"
    r"(?P<from>[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*(?P<dir>[<>-])\s*"
    r"(?P<to>[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)"
)

# Inline column ref annotation: [ref: > users.id]
_INLINE_REF_RE = re.compile(
    r"\[ref\s*:\s*(?P<dir>[<>-])\s*"
    r"(?P<to>[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*\]"
)

# Any `[ref: ...]` fragment — used to detect malformed inline refs.
_ANY_INLINE_REF_RE = re.compile(r"\[ref\s*:[^\]]*\]")


# ------------- v1.2.15: Type validation -------------

# Recognised DBML/SQL type catalog. Key = lowercase type name; value =
# max number of parenthesised parameters allowed (0 = bare only,
# 1 = name OR name(n), 2 = name OR name(n,m)). All types may also
# appear in BARE form (DBML accepts `varchar` without `(255)`).
_DBML_TYPE_CATALOG: dict[str, int] = {
    # Integer family
    "integer": 0, "int": 0, "int2": 0, "int4": 0, "int8": 0,
    "bigint": 0, "smallint": 0, "tinyint": 0, "mediumint": 0,
    "serial": 0, "bigserial": 0, "smallserial": 0,
    # Floating-point
    "real": 0, "float": 1, "float4": 0, "float8": 0, "double": 0,
    "decimal": 2, "numeric": 2,
    "money": 0,
    # Boolean / bit
    "boolean": 0, "bool": 0, "bit": 1, "varbit": 1,
    # String / text
    "text": 0, "tinytext": 0, "mediumtext": 0, "longtext": 0,
    "string": 0,
    "char": 1, "character": 1, "varchar": 1,
    "nchar": 1, "nvarchar": 1, "ntext": 0,  # round-2 Codex: NCHAR family
    "clob": 1, "nclob": 1,                  # round-2 Codex: ANSI lobs
    # Date / time
    "date": 0, "time": 1, "datetime": 1,
    "timestamp": 1, "timestamptz": 1,
    "interval": 1, "year": 0,
    # Binary
    "blob": 0, "tinyblob": 0, "mediumblob": 0, "longblob": 0,
    "bytea": 0, "binary": 1, "varbinary": 1,
    # Structured
    "json": 0, "jsonb": 0, "uuid": 0, "xml": 0,
    # Network
    "inet": 0, "cidr": 0, "macaddr": 0,
    # Spatial / extension types (round-2 Codex: realistic operator input)
    "geometry": 0, "geography": 0, "point": 0, "polygon": 0, "linestring": 0,
    "circle": 0, "box": 0, "path": 0, "line": 0, "lseg": 0,
}

# Multi-word DBML/SQL types (Postgres-flavoured + ANSI). Key = canonical
# lowercased multi-word name; value = max-parameter arity (0 = bare only,
# 1 = name(N) — note that the `(N)` may appear ANYWHERE inside the
# token, e.g., `timestamp(6) with time zone`, not just at the end).
# Round-1 Codex finding (multi-word types missing) + round-2 Codex
# finding (parens-in-the-middle support + ANSI long forms) handled
# here.
_DBML_MULTIWORD_TYPE_CATALOG: dict[str, int] = {
    "double precision": 0,
    "character varying": 1,
    "bit varying": 1,
    "time with time zone": 1,
    "time without time zone": 1,
    "timestamp with time zone": 1,
    "timestamp without time zone": 1,
    "interval year to month": 0,
    "interval day to second": 1,
    "interval year": 0,
    "interval month": 0,
    "interval day": 0,
    "interval hour": 0,
    "interval minute": 0,
    "interval second": 1,
    "national character": 1,           # ANSI alias of nchar
    "national character varying": 1,   # ANSI alias of nvarchar
    "character large object": 1,       # ANSI clob
    "binary large object": 1,          # ANSI blob
    "national character large object": 1,  # ANSI nclob
}

# Single-token type form: <name>[(<params>)]?. Used as a fallback when
# the multi-word splitter doesn't yield a multi-word key.
_TYPE_TOKEN_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\(\s*(?P<params>[0-9]+(?:\s*,\s*[0-9]+)*)\s*\))?$"
)

# In-token `(N)` or `(N,M)` matcher — used by `_extract_params_anywhere`
# so `timestamp(6) with time zone` parses cleanly.
_PARENS_PARAM_RE = re.compile(
    r"\(\s*(?P<params>[0-9]+(?:\s*,\s*[0-9]+)*)\s*\)"
)


def _extract_params_anywhere(token_collapsed_lower: str) -> tuple[str, int, Optional[str]]:
    """Strip the (single) `(N)` / `(N,M)` group out of the token,
    returning the paren-free name (whitespace re-collapsed), parameter
    count, and an optional error message.

    v1.2.15 round-2 Codex fix: lets the classifier accept
    `timestamp(6) with time zone` (params in the middle of a multi-word
    name) without bespoke regex per form.
    v1.2.15 round-3 Codex fix: rejects MULTIPLE parameter groups
    (`numeric(10)(2)`) — those were silently accepted by the round-2
    sum-all-groups implementation.
    """
    matches = list(_PARENS_PARAM_RE.finditer(token_collapsed_lower))
    if len(matches) > 1:
        return "", -1, (
            f"multiple parenthesised parameter groups in type token "
            f"{token_collapsed_lower!r} — DBML/SQL types take at most "
            f"one parameter group"
        )
    n_params = 0 if not matches else len(matches[0].group("params").split(","))
    name_only = _PARENS_PARAM_RE.sub("", token_collapsed_lower)
    name_only = re.sub(r"\s+", " ", name_only).strip()
    return name_only, n_params, None


def _classify_type(type_token: str, enum_names: frozenset[str]) -> tuple[bool, str | None]:
    """Return (is_valid, reason_if_invalid).

    Valid forms:
      * single-word bare type in the catalog (any declared arity)
      * single-word parameterized form within declared arity
      * multi-word type in the multi-word catalog (`double precision`,
        `character varying(255)`, `timestamp with time zone`,
        `timestamp(6) with time zone`)
      * bare type name matching a declared Enum in this file
    """
    norm = type_token.strip()
    if not norm:
        return False, "empty type token"
    norm_collapsed = re.sub(r"\s+", " ", norm).lower()

    # Step 1: extract the (single) `(N)` / `(N,M)` group from the token.
    name_only, n_params, err = _extract_params_anywhere(norm_collapsed)
    if err is not None:
        return False, err
    if not name_only:
        return False, f"unparseable type token {type_token!r}"

    # Step 2: multi-word lookup if the paren-free name has internal
    # whitespace.
    if " " in name_only:
        if name_only in _DBML_MULTIWORD_TYPE_CATALOG:
            max_p = _DBML_MULTIWORD_TYPE_CATALOG[name_only]
            if n_params > max_p:
                return False, (
                    f"type {type_token!r} takes at most {max_p} parameter(s); "
                    f"got {n_params}"
                )
            return True, None
        return False, (
            f"unknown multi-word type {type_token!r} — not in DBML/SQL "
            f"multi-word type catalog and not a declared Enum"
        )

    # Step 3: single-word path.
    name = name_only

    # Enum match (bare only — DBML enums don't take parameters).
    if name in {e.lower() for e in enum_names}:
        if n_params > 0:
            return False, (
                f"enum-typed column {type_token!r} cannot take parameters"
            )
        return True, None

    if name not in _DBML_TYPE_CATALOG:
        return False, (
            f"unknown type {type_token!r} — not in DBML/SQL type catalog "
            f"and not a declared Enum"
        )

    max_params = _DBML_TYPE_CATALOG[name]
    if n_params > max_params:
        return False, (
            f"type {type_token!r} takes at most {max_params} parameter(s); "
            f"got {n_params}"
        )
    return True, None


# ------------- v1.2.15: Structure parsing for FK resolution -------------

# Table block opener: `Table <name> [as alias] [headercolor:...] {`
_TABLE_OPENER_RE = re.compile(
    r"^\s*Table\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?"
    r"\s*(?:\[[^\]]*\])?\s*\{"
)

_ENUM_OPENER_RE = re.compile(
    r"^\s*Enum\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{"
)

# Column line inside a Table block: `<name> <type-part> [<settings>]?`.
# v1.2.15 round-1 Codex fix: type-part is captured TOLERANTLY (any
# non-`[` text, optionally followed by parens with numeric params), so
# multi-word types like `double precision`, `character varying(255)`,
# `timestamp with time zone` land in `table_cols` instead of being
# silently skipped.
_COLUMN_LINE_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s+(?P<type>[^\[\]\{\}]+?)"
    r"(?:\s+(?P<settings>\[.*\]))?\s*$"
)

# Triple-quoted Note opener / closer (DBML multi-line note form).
_TRIPLE_QUOTE = "'''"

# (Round-3 + round-4 Codex fix) — quoted-string stripping is now a
# manual escape-aware scanner (see `_strip_quoted_strings` below); the
# pre-round-4 regex helpers were not escape-safe and have been removed.


def _strip_quoted_strings(line: str) -> str:
    """Replace quoted-string literals with empty-quote placeholders so
    brace/ref scanners don't count their contents.

    v1.2.15 round-4 Codex fix: written as a manual scanner rather than
    naive regex so backslash escapes are honoured — `'O\\'Brien'` is
    one string token, not two. Triple-quote runs win over single
    quotes (greediness)."""
    out: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        if line.startswith(_TRIPLE_QUOTE, i):
            j = line.find(_TRIPLE_QUOTE, i + 3)
            if j == -1:
                # Unclosed triple-quote on this line — strip the rest.
                out.append("''")
                return "".join(out)
            out.append("''")
            i = j + 3
            continue
        ch = line[i]
        if ch in ("'", '"'):
            out.append(ch + ch)  # placeholder of the same quote pair
            quote = ch
            j = i + 1
            while j < n:
                if line[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if line[j] == quote:
                    j += 1
                    break
                j += 1
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_top_level_commas(text: str) -> list[str]:
    """Split a same-line table body on commas that sit OUTSIDE of any
    `(...)` or `[...]` bracket pair AND outside of any quoted string.

    v1.2.15 round-4 Codex fix: naive `body.split(",")` broke
    `numeric(10,2)` and `[not null, ref: > users.id]`.
    v1.2.15 round-5 Codex fix: now also tracks single/double/triple-
    quoted strings (escape-aware). A `]` inside a quoted note value
    no longer decrements `depth_bracket` — `Table demo { name varchar [note: 'hello ] world', not null], age integer }`
    parses correctly.
    """
    parts: list[str] = []
    current: list[str] = []
    depth_paren = 0
    depth_bracket = 0
    in_string = False
    string_quote = ""
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            current.append(ch)
            if ch == "\\" and i + 1 < n:
                current.append(text[i + 1])
                i += 2
                continue
            if ch == string_quote:
                in_string = False
            i += 1
            continue
        # Triple-quote literal (single-line opener+closer, e.g.,
        # `[note: '''short'''], ...`).
        if text.startswith(_TRIPLE_QUOTE, i):
            j = text.find(_TRIPLE_QUOTE, i + 3)
            if j == -1:
                current.append(text[i:])
                i = n
                continue
            current.append(text[i : j + 3])
            i = j + 3
            continue
        if ch in ("'", '"'):
            in_string = True
            string_quote = ch
            current.append(ch)
            i += 1
            continue
        if ch == "(":
            depth_paren += 1
            current.append(ch)
        elif ch == ")":
            depth_paren -= 1
            current.append(ch)
        elif ch == "[":
            depth_bracket += 1
            current.append(ch)
        elif ch == "]":
            depth_bracket -= 1
            current.append(ch)
        elif ch == "," and depth_paren == 0 and depth_bracket == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        parts.append("".join(current))
    return parts


# Parsed-ref records emitted by `_parse_structure` for downstream FK
# resolution. Carrying these (instead of having `_validate_fk_targets`
# re-scan the raw text) means Note/triple-quote bodies can't leak into
# the FK pass — they were already skipped during the structural walk.
# v1.2.15 round-2 Codex fix.
#
#   TopLevelRef: (line, from_table, from_col, to_table, to_col)
#   InlineRef:   (line, in_table, from_col_or_None, to_table, to_col)
TopLevelRef = tuple  # (line, from_table, from_col, to_table, to_col)
InlineRef = tuple    # (line, in_table, from_col_or_None, to_table, to_col)


def _parse_structure(text: str) -> tuple[
    dict[str, list[tuple[int, str, str]]],  # tables: name -> [(line, col_name, col_type)]
    set[str],                                # enums: set of enum names
    list[TopLevelRef],                       # top-level Refs
    list[InlineRef],                         # inline Refs collected during the walk
    list[str],                               # parse warnings (non-fatal)
]:
    """Walk the file once, gathering:
      * tables: ordered list of (line_no, column_name, column_type)
        per table (table-name keyed dict)
      * enums: set of enum names declared at top level
      * top-level `Ref:` statements (only at depth 0 — never inside
        Note bodies / Table bodies)
      * inline `[ref: ...]` annotations attached to a column declaration
        — collected only for lines we treat as REAL column lines, so
        Note/triple-quote bodies can't leak in
      * warnings: parse oddities worth surfacing but not fatal

    The walk is brace-depth-aware. Note: '''...''' bodies AND `Note { ... }`
    blocks are skipped entirely.
    """
    tables: dict[str, list[tuple[int, str, str]]] = {}
    enums: set[str] = set()
    top_level_refs: list[TopLevelRef] = []
    inline_refs: list[InlineRef] = []
    warnings: list[str] = []

    depth = 0
    in_table: str | None = None  # table name when at depth 1 inside a Table block
    in_enum = False
    in_triple_quoted_note = False  # mid-Note: '''multi line''' body
    in_note_block_depth = 0        # >0 ⇒ inside `Note { ... }` block (skip everything)

    for line_no, raw in enumerate(text.splitlines(), start=1):
        # Strip line comments
        line_no_comment = re.sub(r"//.*$", "", raw).rstrip()
        stripped = line_no_comment.strip()
        # Brace-counting must ignore braces inside quoted strings
        # (round-3 Codex fix: `Note { description: 'has { brace }' }`).
        quote_stripped = _strip_quoted_strings(line_no_comment)

        # ---- Triple-quoted Note body (round-1 + round-2 Codex fix) ----
        # While inside `Note: '''...'''`, every line is part of the note
        # body — never parse columns OR refs from it.
        if in_triple_quoted_note:
            if _TRIPLE_QUOTE in line_no_comment:
                in_triple_quoted_note = False
            continue

        # ---- `Note { ... }` block body (round-2 + round-3 Codex fix) ----
        # `Note { ... }` is the block form of Note. Any text inside MUST
        # NOT be parsed as columns or refs. We track its depth separately
        # so the outer brace tracker doesn't muddle table-block vs
        # note-block context.
        if in_note_block_depth > 0:
            delta = quote_stripped.count("{") - quote_stripped.count("}")
            in_note_block_depth += delta
            if in_note_block_depth <= 0:
                in_note_block_depth = 0
            depth += delta
            continue

        if not stripped:
            depth += quote_stripped.count("{") - quote_stripped.count("}")
            continue

        opens = quote_stripped.count("{")
        closes = quote_stripped.count("}")

        if depth == 0:
            tm = _TABLE_OPENER_RE.match(line_no_comment)
            if tm and opens >= 1:
                in_table = tm.group("name")
                tables.setdefault(in_table, [])
                # Same-line body? `Table users { id integer [pk] }` is
                # valid DBML. Round-3 Codex fix: previously the round-2
                # refactor `continue`d before column parsing, so any
                # column on the opener line was lost — and Refs to it
                # then false-positive-failed FK resolution.
                if closes >= 1:
                    body = line_no_comment[
                        line_no_comment.index("{") + 1 : line_no_comment.rindex("}")
                    ].strip()
                    if body:
                        # Round-4 Codex fix: split on commas at depth 0
                        # (outside `(...)` and `[...]`) so `numeric(10,2)`
                        # and `[not null, ref: > users.id]` survive.
                        for fragment in _split_top_level_commas(body):
                            fragment = fragment.strip()
                            if not fragment:
                                continue
                            cm = _COLUMN_LINE_RE.match(fragment)
                            if cm:
                                col_name = cm.group("name")
                                col_type = cm.group("type").strip()
                                tables[in_table].append((line_no, col_name, col_type))
                                for irm in _INLINE_REF_RE.finditer(fragment):
                                    to_table, to_col = irm.group("to").split(".", 1)
                                    inline_refs.append(
                                        (line_no, in_table, col_name, to_table, to_col)
                                    )
                depth += opens - closes
                if depth == 0:
                    in_table = None
                continue
            em = _ENUM_OPENER_RE.match(line_no_comment)
            if em and opens >= 1:
                enums.add(em.group("name"))
                in_enum = True
                depth += opens - closes
                if depth == 0:
                    in_enum = False
                continue
            # Top-level Ref statement (NOT block form).
            if (
                stripped.startswith("Ref")
                and ":" in stripped
                and "{" not in stripped
            ):
                rm = _TOPLEVEL_REF_STMT_RE.match(stripped)
                if rm:
                    from_table, from_col = rm.group("from").split(".", 1)
                    to_table, to_col = rm.group("to").split(".", 1)
                    top_level_refs.append(
                        (line_no, from_table, from_col, to_table, to_col)
                    )
                # Malformed-shape Refs are reported by the syntax pass.
            depth += opens - closes
            continue

        # depth > 0 (inside a block)
        if in_table is not None and depth == 1 and opens == 0 and closes == 0:
            # This is a body line of the current Table block. Try to
            # parse as a column declaration. Skip clearly-non-column
            # lines (indexes block opener, Note: ..., etc.).
            stripped_lower = stripped.lower()
            if stripped_lower.startswith(("indexes", "note:", "note ", "note{")):
                # Detect & latch triple-quoted multi-line note body.
                if (
                    stripped_lower.startswith(("note:", "note "))
                    and _TRIPLE_QUOTE in stripped
                    and stripped.count(_TRIPLE_QUOTE) == 1
                ):
                    in_triple_quoted_note = True
                # Single-line `Note: 'x'` and `Note: '''single line'''`
                # (both `'''` on one line) are harmless — they don't
                # contain inline refs by construction (their content is
                # quoted text, but a defensive operator could still embed
                # `[ref:...]` literally; depth tracker plus skip-this-line
                # handle that case).
            else:
                # Real column line.
                cm = _COLUMN_LINE_RE.match(stripped)
                if cm:
                    col_name = cm.group("name")
                    col_type = cm.group("type").strip()
                    tables[in_table].append((line_no, col_name, col_type))
                    # Inline `[ref:...]` on the SAME line attaches to
                    # this column.
                    for irm in _INLINE_REF_RE.finditer(line_no_comment):
                        to_table, to_col = irm.group("to").split(".", 1)
                        inline_refs.append(
                            (line_no, in_table, col_name, to_table, to_col)
                        )
                else:
                    # Not a real column line — but if the operator wrote
                    # an inline `[ref:...]` here (no leading column id),
                    # surface it via inline_refs with from_col=None so
                    # the FK validator can complain (round-1 Codex fix).
                    for irm in _INLINE_REF_RE.finditer(line_no_comment):
                        to_table, to_col = irm.group("to").split(".", 1)
                        inline_refs.append(
                            (line_no, in_table, None, to_table, to_col)
                        )
        elif (
            in_table is not None
            and depth == 1
            and opens >= 1
            and closes == 0
            and stripped.lower().startswith(("note ", "note{"))
        ):
            # `Note { ... }` block opens here. Skip its body.
            in_note_block_depth = opens

        depth_before = depth
        depth += opens - closes
        # Detect block close back to top level.
        if depth == 0 and depth_before > 0:
            in_table = None
            in_enum = False

    if depth != 0:
        warnings.append(
            f"_parse_structure: brace tracker ended at depth {depth} "
            f"(should be 0); structure model may be incomplete"
        )
    return tables, enums, top_level_refs, inline_refs, warnings


def _validate_types(
    tables: dict[str, list[tuple[int, str, str]]],
    enums: set[str],
    path: Path,
    lenient: bool,
) -> list[str]:
    """For every column, classify the type. Append a violation when
    the type isn't recognised (unless `lenient=True`)."""
    if lenient:
        return []
    violations: list[str] = []
    enum_set = frozenset(enums)
    for table_name, cols in tables.items():
        for line_no, col_name, col_type in cols:
            ok, reason = _classify_type(col_type, enum_set)
            if not ok:
                violations.append(
                    f"{path}:line {line_no}: column "
                    f"{table_name}.{col_name} — {reason}"
                )
    return violations


def _validate_fk_targets(
    tables: dict[str, list[tuple[int, str, str]]],
    top_level_refs: list[TopLevelRef],
    inline_refs: list[InlineRef],
    path: Path,
) -> list[str]:
    """Resolve every parsed Ref (top-level + inline) against the
    table/column inventory. v1.2.15 round-2 Codex fix: refs are
    consumed from `_parse_structure` output (single-pass) instead of
    re-scanning the raw text — that way Note/triple-quote bodies that
    were already filtered during the structural walk can NOT leak
    into the FK pass.
    """
    violations: list[str] = []

    table_cols: dict[str, set[str]] = {
        t: {c for _line, c, _typ in cols} for t, cols in tables.items()
    }

    def _check(line_no: int, side: str, table: str, col: str) -> None:
        if table not in table_cols:
            violations.append(
                f"{path}:line {line_no}: Ref {side} side points at "
                f"unknown table {table!r} (column {col!r})"
            )
            return
        if col not in table_cols[table]:
            violations.append(
                f"{path}:line {line_no}: Ref {side} side points at "
                f"{table}.{col!r}, but table {table!r} has no such column "
                f"(known: {sorted(table_cols[table])})"
            )

    for line_no, from_table, from_col, to_table, to_col in top_level_refs:
        _check(line_no, "from", from_table, from_col)
        _check(line_no, "to", to_table, to_col)

    for line_no, in_table, from_col, to_table, to_col in inline_refs:
        _check(line_no, "to", to_table, to_col)
        if from_col is None:
            violations.append(
                f"{path}:line {line_no}: inline `[ref:...]` annotation "
                f"has no leading column identifier on the same line — "
                f"`[ref:...]` is a column setting and must annotate a "
                f"column declaration"
            )
        elif in_table in table_cols and from_col not in table_cols[in_table]:
            violations.append(
                f"{path}:line {line_no}: inline `[ref:...]` on column "
                f"{in_table}.{from_col!r}, but no such column was parsed "
                f"in {in_table!r} (known: "
                f"{sorted(table_cols.get(in_table, set()))}) — likely a "
                f"syntax variant the structure parser missed"
            )
    return violations


# ------------- File-level entry point -------------


def validate_dbml_file(path: Path, *, lenient_types: bool = False) -> list[str]:
    """Validate one `.dbml` file; return a list of human-readable
    violation strings. Empty list == pass.

    `lenient_types=True` skips type-catalog enforcement (v1.2.15
    introduced strict typing; the flag preserves pre-v1.2.15 behavior
    for legacy `.dbml` that uses custom domain types)."""
    violations: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{path}: cannot read file ({type(exc).__name__}: {exc})"]

    # ---- (v1.2.11 + v1.2.15 round-3) Balanced-brace + non-empty-body check ---
    # Round-3 Codex fix: brace counter must ignore `{` / `}` inside
    # quoted-string literals — otherwise `Note { description: 'has { brace }' }`
    # desyncs the depth tracker.
    depth = 0
    block_start_line = 0  # 1-indexed line where the current open block started
    current_block_has_body = False
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line_orig = raw.strip()
        if not line_orig or line_orig.startswith("//"):
            continue
        line = _strip_quoted_strings(line_orig)
        opens = line.count("{")
        closes = line.count("}")
        if opens and closes and depth == 0:
            first_open = line.index("{")
            last_close = line.rindex("}")
            body = line[first_open + 1:last_close].strip()
            if not body:
                violations.append(
                    f"{path}:line {line_no}: block opens and closes "
                    f"empty on the same line — usually a truncated "
                    f"paste; add body or remove the block"
                )
        elif opens and depth == 0:
            block_start_line = line_no
            current_block_has_body = False
        elif depth > 0 and opens == 0 and closes == 0:
            current_block_has_body = True
        if closes and depth > 0 and depth - closes == 0:
            if not current_block_has_body and opens == 0:
                violations.append(
                    f"{path}:line {line_no}: block opened at line "
                    f"{block_start_line} closes empty — usually a "
                    f"truncated paste; add body or remove the block"
                )
        depth += opens - closes
        if depth < 0:
            violations.append(
                f"{path}:line {line_no}: unbalanced closing brace — "
                f"more `}}` than `{{` at this point"
            )
            return violations
    if depth > 0:
        violations.append(
            f"{path}:line {len(text.splitlines())}: unbalanced opening "
            f"brace — {depth} unclosed block(s)"
        )

    # ---- (v1.2.11) Top-level Ref statement shape ---------------------
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        if line.startswith("Ref") and ":" in line and "{" not in line:
            m = _TOPLEVEL_REF_STMT_RE.match(line)
            if not m:
                violations.append(
                    f"{path}:line {line_no}: malformed top-level Ref "
                    f"statement: {line!r} — expected "
                    f"`Ref[: <name>] <from_table>.<from_col> (<|>|-) "
                    f"<to_table>.<to_col>`"
                )

    # ---- (v1.2.11) Inline ref shape ----------------------------------
    for line_no, raw in enumerate(text.splitlines(), start=1):
        for m in _ANY_INLINE_REF_RE.finditer(raw):
            if not _INLINE_REF_RE.match(m.group(0)):
                violations.append(
                    f"{path}:line {line_no}: malformed inline ref "
                    f"annotation {m.group(0)!r} — expected "
                    f"`[ref: (<|>|-) <to_table>.<to_col>]`"
                )

    # ---- (v1.2.15) Structure parse + semantic checks -----------------
    # Skip semantic checks if syntax already failed — the structure
    # model is unreliable when braces are unbalanced.
    syntax_failed = any(
        "unbalanced" in v or "closes empty" in v or "opens and closes" in v
        for v in violations
    )
    if not syntax_failed:
        tables, enums, top_level_refs, inline_refs, _warnings = _parse_structure(text)
        violations.extend(
            _validate_types(tables, enums, path, lenient=lenient_types)
        )
        violations.extend(
            _validate_fk_targets(tables, top_level_refs, inline_refs, path)
        )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DBML syntax + semantic validator (v1.2.15 dbml-from-context sidecar).",
    )
    parser.add_argument(
        "paths", nargs="*", type=Path,
        help="One or more .dbml paths to validate.",
    )
    parser.add_argument(
        "--lenient-types", action="store_true",
        help="Skip type-catalog enforcement (preserves pre-v1.2.15 behavior). "
             "FK target resolution is always enforced.",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if not args.paths:
        print("validate_dbml: no paths given", file=sys.stderr)
        return 2
    had_errors = False
    for p in args.paths:
        if not p.is_file():
            print(f"validate_dbml: path not found: {p}", file=sys.stderr)
            return 2
        findings = validate_dbml_file(p, lenient_types=args.lenient_types)
        if findings:
            had_errors = True
            for f in findings:
                print(f, file=sys.stderr)
    if had_errors:
        return 1
    print(f"validate_dbml: {len(args.paths)} file(s) validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
