#!/usr/bin/env python3
"""Minimal DBML syntax validator (v1.2.11).

The dbml-from-context sidecar's contract at
``skills/dbml-from-context/references/integration-contract.md`` defines
WHAT a well-formed `.dbml` file looks like. This script provides a
MINIMUM-VIABLE syntax pass — enough to catch the most common hand-
authoring errors without depending on a full DBML parser (which would
require the ``@dbml/core`` Node package).

Checks (all hard-fail):
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

What it does NOT check (deferred):
  * DBML-level type correctness (e.g., whether ``varchar`` is
    a valid DBML type — DBML is liberal here).
  * FK target resolution (whether ``users.id`` exists when
    ``Ref: orders.user_id > users.id`` is declared).
  * Enum-value referenced from a column actually belongs to the
    named enum.
  * Cross-file references (DBML supports ``[ref: > other_schema.users.id]``
    with a database-prefix; not modelled here).

A future release can bring in a full DBML parser + richer validation.
v1.2.11's role is to catch gross-structure errors at the CI layer and
provide a foundation for the sidecar's test inventory.

CLI:
  scripts/validate_dbml.py <path>
  scripts/validate_dbml.py <path> <path> ...

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


def validate_dbml_file(path: Path) -> list[str]:
    """Validate one `.dbml` file; return a list of human-readable
    violation strings. Empty list == pass."""
    violations: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{path}: cannot read file ({type(exc).__name__}: {exc})"]

    # ---- Balanced-brace + non-empty-body check ---------------
    depth = 0
    block_start_line = 0  # 1-indexed line where the current open block started
    current_block_has_body = False
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("//"):
            # Empty or comment lines don't count as body content but
            # also don't affect balance.
            continue
        opens = line.count("{")
        closes = line.count("}")
        # Same-line empty-block check: `Table users {}` opens + closes
        # in one line with no body between them. Catch this BEFORE the
        # multi-line check so a truncated one-line paste surfaces
        # (Codex v1.2.11 round-1 under-match critical).
        if opens and closes and depth == 0:
            # Strip everything between the first `{` and the last `}`
            # inclusive to inspect the body on this same line.
            first_open = line.index("{")
            last_close = line.rindex("}")
            body = line[first_open + 1:last_close].strip()
            if not body:
                violations.append(
                    f"{path}:line {line_no}: block opens and closes "
                    f"empty on the same line — usually a truncated "
                    f"paste; add body or remove the block"
                )
            # Depth nets to 0 on this line regardless; no need to set
            # block_start_line or current_block_has_body.
        elif opens and depth == 0:
            block_start_line = line_no
            current_block_has_body = False
        elif depth > 0 and opens == 0 and closes == 0:
            # Body content inside an open block.
            current_block_has_body = True
        if closes and depth > 0 and depth - closes == 0:
            # Block closing — was there any body?
            if not current_block_has_body and opens == 0:
                # Block opened on earlier line with no body on any
                # intervening line — empty block body.
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
            return violations  # can't reliably continue after imbalance
    if depth > 0:
        violations.append(
            f"{path}:line {len(text.splitlines())}: unbalanced opening "
            f"brace — {depth} unclosed block(s)"
        )

    # ---- Top-level Ref statement shape ---------------------
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        # Only top-level lines (not inside braces) — crude but
        # effective for this syntax-check layer.
        if line.startswith("Ref") and ":" in line and "{" not in line:
            m = _TOPLEVEL_REF_STMT_RE.match(line)
            if not m:
                violations.append(
                    f"{path}:line {line_no}: malformed top-level Ref "
                    f"statement: {line!r} — expected "
                    f"`Ref[: <name>] <from_table>.<from_col> (<|>|-) "
                    f"<to_table>.<to_col>`"
                )

    # ---- Inline ref shape ----------------------------------
    for line_no, raw in enumerate(text.splitlines(), start=1):
        for m in _ANY_INLINE_REF_RE.finditer(raw):
            if not _INLINE_REF_RE.match(m.group(0)):
                violations.append(
                    f"{path}:line {line_no}: malformed inline ref "
                    f"annotation {m.group(0)!r} — expected "
                    f"`[ref: (<|>|-) <to_table>.<to_col>]`"
                )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Minimal DBML syntax validator (v1.2.11 dbml-from-context sidecar).",
    )
    parser.add_argument(
        "paths", nargs="*", type=Path,
        help="One or more .dbml paths to validate.",
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
        findings = validate_dbml_file(p)
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
