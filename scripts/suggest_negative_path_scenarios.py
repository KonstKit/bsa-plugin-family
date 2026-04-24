#!/usr/bin/env python3
"""Negative-path scenario suggestion helper (v1.2.5, T4).

Closes TODO-S8-01-NEGATIVE-PATH-HEURISTICS from
skills/bsa-test-scenario-builder/SKILL.md. The skill's documented
contract (line 14) says: "Add scenarios for boundary conditions /
negative paths when the criterion implies them (e.g., a 'within
60s' criterion implies both an 'exactly at SLA' scenario and a
'past SLA' rollover scenario)." Pre-v1.2.5 this was operator-
manual; v1.2.5 ships a deterministic helper that scans A70
AcceptanceCriteria text for measurable language + emits
suggestions the operator can copy-paste into A71.

Three pattern classes detected (per the SKILL.md TODO description):

  TEMPORAL  — "within X seconds/minutes/hours/days/business days"
              → suggest:
                a) "exactly at SLA" scenario (X passes)
                b) "just past SLA" negative-path scenario (X+1 fails)

  BOUNDARY  — "at least N", "at most N", "no more than N",
              "no fewer than N", "exactly N"
              → suggest:
                a) "at boundary" scenario (=N passes/fails per pattern)
                b) "off-by-one" negative-path scenario

  COMPARISON — "more than M", "less than M", "greater than M",
              "fewer than M", "≥ X", "≤ X", ">= X", "<= X"
              → suggest:
                a) "exactly M" boundary scenario
                b) "M ± 1" negative-path scenario

Output: a markdown suggestion report at
`analysis/handoff/negative_path_suggestions.md` (NOT canonical;
operator copies relevant suggestions into A71 manually). The
helper deliberately does NOT auto-emit A71 rows — A71 row authoring
needs human judgment about what's actually testable in the system
under test, what's already covered by adjacent scenarios, etc.

Stdlib-only.

CLI:
  scripts/suggest_negative_path_scenarios.py --workspace <path>
  scripts/suggest_negative_path_scenarios.py --workspace <path> \\
      --output-path custom/path/suggestions.md
  scripts/suggest_negative_path_scenarios.py --workspace <path> \\
      --json   # machine-readable output for downstream tooling

Exit codes:
  0 — suggestions emitted (zero or more; zero is a clean PASS).
  2 — invocation error (missing workspace, missing A70, malformed
      CSV, etc.).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

A70_REL = "analysis/canonical/core_controls/A70_story_register.csv"
DEFAULT_OUTPUT_REL = "analysis/handoff/negative_path_suggestions.md"


# ---- Pattern definitions -------------------------------------------
#
# Each pattern compiles to a regex that captures (a) the kind of
# measurable phrase + (b) the numeric quantity. Patterns are ordered:
# more-specific first (so "no more than N" doesn't double-match as
# both BOUNDARY and COMPARISON). Case-insensitive throughout.


@dataclass(frozen=True)
class PatternMatch:
    """One measurable phrase detected in an acceptance criterion."""
    pattern_class: str  # "temporal" | "boundary" | "comparison"
    phrase: str         # the exact substring matched
    quantity: str       # the numeric value (string — preserves units)
    unit: str = ""      # for temporal — "seconds", "minutes", etc.
    suggestion: str = "" # human-readable suggestion text


# Temporal: "within 60 seconds", "within 5 minutes", "within 1 hour", etc.
# Captures: <quantity> <unit>. Plural / singular both supported.
TEMPORAL_RE = re.compile(
    r"\bwithin\s+(\d+(?:\.\d+)?)\s*(seconds?|minutes?|hours?|days?"
    r"|business\s+days?|business\s+hours?|ms|s|m|h|d)\b",
    re.IGNORECASE,
)

# Boundary: "at least 5", "at most 10", "no more than 100",
# "no fewer than 3", "exactly 7".
BOUNDARY_RE = re.compile(
    r"\b(at\s+least|at\s+most|no\s+more\s+than|no\s+fewer\s+than|exactly)"
    r"\s+(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)

# Comparison: "more than 5", "less than 10", "greater than 3",
# "fewer than 100", ">= 80", "<= 50", "≥ 80", "≤ 50".
# NB: must NOT double-match the BOUNDARY phrases above (handled in
# detect_patterns via covered-range overlap check, not via leading
# `\b` — `\b` does NOT anchor before non-word symbols like `>=`).
COMPARISON_RE = re.compile(
    r"(?:\b(more\s+than|less\s+than|greater\s+than|fewer\s+than|"
    r"larger\s+than|smaller\s+than)\s+(\d+(?:\.\d+)?)\b"
    r"|"
    r"(?:>=|<=|≥|≤|>|<)\s*(\d+(?:\.\d+)?)\b)",
    re.IGNORECASE,
)


# ---- Suggestion generation -----------------------------------------


def _temporal_suggestion(qty: str, unit: str) -> str:
    return (
        f"Within-{qty}{unit}: cover BOTH (a) 'exactly at SLA' "
        f"({qty}{unit} elapsed → still passes) AND (b) 'just past SLA' "
        f"({qty}+1{unit} elapsed → fails). Operator may add explicit "
        f"`just before SLA' (qty-1{unit}) if useful."
    )


_INT_SHAPED_RE = re.compile(r"^(\d+)(?:\.0+)?$")


def _off_by_one(qty: str, direction: int) -> str:
    """Render a numerically-correct off-by-one example.

    Integer-shaped `qty` (digits only, or digits followed by ``.0+``
    — e.g. `5`, `5.0`, `100`, `9007199254740993`) → literal integer
    ±1, computed lexically with :class:`int` so arbitrarily-large
    quantities don't lose precision through ``float``.

    Decimal-shaped `qty` (e.g. `99.9`, `0.5`) → symbolic ``qty ± ε``
    so the operator picks an SLA-appropriate epsilon per their
    domain (`99.8` for `99.9 - ε`, `0.4` for `0.5 - ε`).
    Round-trip through ``float`` would give numerically-wrong
    arithmetic examples here (`int(float("99.9")) - 1 == 98`).

    Round-2 Codex review note: an earlier draft used
    ``int(float(qty))`` for the integer-shape detect step. Even
    though the regex bounds qty to ``\\d+(?:\\.\\d+)?``, the
    ``float`` round-trip silently loses precision past 2**53, so
    `9007199254740993` came back as `9007199254740991` for "just
    below". We detect integer shape lexically now to avoid that
    class of bug entirely.
    """
    sign = "+" if direction > 0 else "-"
    m = _INT_SHAPED_RE.match(qty)
    if m:
        return f"{int(m.group(1)) + direction}"
    return f"{qty} {sign} \u03b5"  # ε


def _boundary_suggestion(operator: str, qty: str) -> str:
    op = operator.strip().lower().replace("  ", " ")
    minus = _off_by_one(qty, -1)
    plus = _off_by_one(qty, +1)
    if op == "at least":
        return (
            f"At-least-{qty}: cover (a) at boundary (={qty} → passes) "
            f"AND (b) just below ({minus} → fails)."
        )
    if op == "at most":
        return (
            f"At-most-{qty}: cover (a) at boundary (={qty} → passes) "
            f"AND (b) just above ({plus} → fails)."
        )
    if op == "no more than":
        return (
            f"No-more-than-{qty}: same as at-most-{qty}: cover at "
            f"boundary AND just above ({plus}) negative path."
        )
    if op == "no fewer than":
        return (
            f"No-fewer-than-{qty}: same as at-least-{qty}: cover at "
            f"boundary AND just below ({minus}) negative path."
        )
    if op == "exactly":
        return (
            f"Exactly-{qty}: cover (a) ={qty} (passes) AND BOTH (b) "
            f"{minus} AND (c) {plus} (both fail). Two negative-path "
            f"scenarios; both off-by-one directions matter."
        )
    return f"Boundary phrase '{operator} {qty}': add boundary + off-by-one scenarios."


def _comparison_suggestion(phrase: str, qty: str) -> str:
    return (
        f"Comparison-{phrase}-{qty}: cover (a) at-boundary-exact "
        f"(={qty}) AND (b) ±1 negative path on the failing side. "
        f"Operator: pick the direction the comparison forbids "
        f"(e.g., 'more than 5' forbids ≤5 — add =5 + =4 negative scenarios)."
    )


def detect_patterns(text: str) -> list[PatternMatch]:
    """Scan one acceptance-criterion text for all 3 pattern classes.
    Returns matches in source order. Pattern classes are evaluated
    most-specific first (TEMPORAL → BOUNDARY → COMPARISON); a later
    candidate whose span overlaps an already-claimed range is
    discarded. This is what prevents 'no more than 50' (BOUNDARY)
    from also emitting 'more than 50' (COMPARISON)."""
    matches: list[PatternMatch] = []
    covered: list[tuple[int, int]] = []

    def _overlaps(span: tuple[int, int]) -> bool:
        s, e = span
        return any(cs < e and s < ce for cs, ce in covered)

    # TEMPORAL first (longest, most specific).
    for m in TEMPORAL_RE.finditer(text):
        span = m.span()
        if _overlaps(span):
            continue
        covered.append(span)
        qty = m.group(1)
        unit = m.group(2)
        matches.append(PatternMatch(
            pattern_class="temporal",
            phrase=m.group(0),
            quantity=qty,
            unit=unit,
            suggestion=_temporal_suggestion(qty, " " + unit if unit else ""),
        ))
    # BOUNDARY next — claims spans like 'no more than 50' BEFORE
    # COMPARISON gets to scan, which is the key anti-double-match
    # invariant. (Test pins this; do not reorder.)
    for m in BOUNDARY_RE.finditer(text):
        span = m.span()
        if _overlaps(span):
            continue
        covered.append(span)
        operator = m.group(1)
        qty = m.group(2)
        matches.append(PatternMatch(
            pattern_class="boundary",
            phrase=m.group(0),
            quantity=qty,
            suggestion=_boundary_suggestion(operator, qty),
        ))
    # COMPARISON last; overlap check skips substrings already claimed
    # by BOUNDARY (e.g., 'more than 50' inside 'no more than 50').
    for m in COMPARISON_RE.finditer(text):
        span = m.span()
        if _overlaps(span):
            continue
        covered.append(span)
        # Word form: group(1) = phrase, group(2) = qty.
        # Symbolic form: group(3) = qty (symbol is in m.group(0)).
        if m.group(1):
            phrase = m.group(1).strip().lower()
            qty = m.group(2)
        else:
            phrase = m.group(0).split()[0]  # the symbol token
            qty = m.group(3)
        matches.append(PatternMatch(
            pattern_class="comparison",
            phrase=m.group(0),
            quantity=qty,
            suggestion=_comparison_suggestion(phrase, qty),
        ))
    # Sort by source order for deterministic output.
    matches.sort(key=lambda x: text.find(x.phrase))
    return matches


# ---- A70 parsing ---------------------------------------------------


@dataclass
class StorySuggestion:
    story_id: str
    title: str
    acceptance_criteria: str
    matches: list[PatternMatch] = field(default_factory=list)


REQUIRED_A70_COLUMNS = ("StoryID", "Title", "AcceptanceCriteria")


def _read_a70(a70_path: Path) -> tuple[list[StorySuggestion], list[str]]:
    stories: list[StorySuggestion] = []
    parse_errors: list[str] = []
    rel = str(a70_path)
    try:
        with a70_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            missing = [c for c in REQUIRED_A70_COLUMNS if c not in fieldnames]
            if missing:
                parse_errors.append(
                    f"{rel}: header missing required column(s): "
                    f"{', '.join(missing)}. Found: {fieldnames!r}."
                )
                return stories, parse_errors
            for idx, row in enumerate(reader, start=2):
                # Truncated row: csv.DictReader fills missing cells with None.
                if any(row.get(c) is None for c in REQUIRED_A70_COLUMNS):
                    parse_errors.append(
                        f"{rel}:row {idx}: missing cell(s) for required "
                        f"column(s) (truncated row?)."
                    )
                    continue
                # Extra-field overflow: long rows (unescaped comma in a text
                # field) put the overflow under the magic `None` key. Reject —
                # same fail-CLOSED pattern as a71_runnable_export.py /
                # promote_strict_preflight.
                if row.get(None):
                    parse_errors.append(
                        f"{rel}:row {idx}: extra cell(s) past last column "
                        f"(unescaped comma in a text field?)."
                    )
                    continue
                # Blank-after-strip required cells are also fail-CLOSED:
                # a story row with no StoryID / Title / AC is malformed
                # input, not "we just have no measurable language".
                stripped = {c: (row.get(c) or "").strip()
                            for c in REQUIRED_A70_COLUMNS}
                blanks = [c for c, v in stripped.items() if not v]
                if blanks:
                    parse_errors.append(
                        f"{rel}:row {idx}: blank required cell(s): "
                        f"{', '.join(blanks)}."
                    )
                    continue
                ac_text = stripped["AcceptanceCriteria"]
                stories.append(StorySuggestion(
                    story_id=stripped["StoryID"],
                    title=stripped["Title"],
                    acceptance_criteria=ac_text,
                    matches=detect_patterns(ac_text),
                ))
    except (OSError, csv.Error) as exc:
        parse_errors.append(f"{rel}: parse error: {type(exc).__name__}: {exc}")
    return stories, parse_errors


# ---- Reporting -----------------------------------------------------


def _md_escape_inline(text: str) -> str:
    """Escape user-supplied text for safe inline use inside markdown.

    A70 cells can legitimately contain backticks (e.g., literal API
    paths), pipe chars (`|` — risky inside table-like rendering),
    and hard newlines (which would split a single bullet across two
    list items in many renderers). This helper normalises those
    without dropping content. Backslashes are escaped by adding a
    leading backslash; newlines collapse to a single space.
    """
    if not text:
        return ""
    # Collapse hard newlines first so renderers don't break the bullet.
    out = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    # Escape backslashes first (so we don't double-escape later).
    out = out.replace("\\", "\\\\")
    # Markdown inline metacharacters — escape conservatively.
    for ch in ("`", "*", "_", "|", "<", ">", "[", "]"):
        out = out.replace(ch, f"\\{ch}")
    return out


def format_markdown_report(stories: list[StorySuggestion]) -> str:
    lines: list[str] = [
        "# Negative-Path Scenario Suggestions",
        "",
        "Auto-generated by `scripts/suggest_negative_path_scenarios.py`",
        "(v1.2.5, T4). Operator review required — these are SUGGESTIONS, "
        "not auto-emitted A71 rows.",
        "",
        "Per `skills/bsa-test-scenario-builder/SKILL.md` line 14, every",
        "acceptance criterion with measurable language SHOULD have an",
        "explicit boundary scenario AND a negative-path (off-by-one)",
        "scenario. This report scans A70 AcceptanceCriteria text for",
        "three pattern classes (temporal / boundary / comparison) and",
        "lists per-story suggestions the operator can copy-paste",
        "into A71_test_scenario_register.csv (after editing for the",
        "actual system under test).",
        "",
    ]

    total_matches = sum(len(s.matches) for s in stories)
    stories_with_matches = sum(1 for s in stories if s.matches)
    lines.extend([
        "## Summary",
        "",
        f"- Stories scanned: **{len(stories)}**",
        f"- Stories with measurable language: **{stories_with_matches}**",
        f"- Total suggestions: **{total_matches}**",
        "",
    ])

    if not total_matches:
        lines.append("No measurable language detected in any A70 acceptance criterion. ")
        lines.append("Either the stories are non-numeric (qualitative) or the patterns ")
        lines.append("missed the syntax — operator should review manually.")
        return "\n".join(lines) + "\n"

    lines.append("## Per-story suggestions")
    lines.append("")
    for s in stories:
        if not s.matches:
            continue
        lines.append(f"### {_md_escape_inline(s.story_id)} \u2014 {_md_escape_inline(s.title)}")
        lines.append("")
        ac_excerpt = s.acceptance_criteria[:200]
        lines.append(f"_Acceptance criteria_: {_md_escape_inline(ac_excerpt)}")
        if len(s.acceptance_criteria) > 200:
            lines.append("(truncated)")
        lines.append("")
        for m in s.matches:
            phrase_md = _md_escape_inline(m.phrase)
            qty_md = _md_escape_inline(m.quantity)
            unit_md = _md_escape_inline(m.unit) if m.unit else ""
            lines.append(
                f"- **[{m.pattern_class.upper()}]** matched "
                f"`{phrase_md}` (qty={qty_md}"
                f"{', unit=' + unit_md if unit_md else ''}):"
            )
            # Suggestion text is generated by us, not user-supplied — safe
            # to emit verbatim. (It contains qty values that came from the
            # user, but those are already substring-equal to the matched
            # numeric token, which is regex-bounded to digits/dots.)
            lines.append(f"  - {m.suggestion}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_json_report(stories: list[StorySuggestion]) -> str:
    return json.dumps({
        "stories_scanned": len(stories),
        "stories_with_matches": sum(1 for s in stories if s.matches),
        "total_matches": sum(len(s.matches) for s in stories),
        "stories": [
            {
                "story_id": s.story_id,
                "title": s.title,
                "matches": [
                    {
                        "pattern_class": m.pattern_class,
                        "phrase": m.phrase,
                        "quantity": m.quantity,
                        "unit": m.unit,
                        "suggestion": m.suggestion,
                    }
                    for m in s.matches
                ],
            }
            for s in stories
        ],
    }, indent=2)


# ---- CLI -----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Suggest negative-path A71 scenarios from A70 acceptance criteria",
    )
    parser.add_argument(
        "--workspace", type=Path, default=Path.cwd(),
        help="BSA workspace root (defaults to cwd)",
    )
    parser.add_argument(
        "--output-path", type=Path, default=None,
        help=f"Override output path (default: <workspace>/{DEFAULT_OUTPUT_REL}).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of markdown.",
    )
    parser.add_argument(
        "--print-only", action="store_true",
        help="Print to stdout instead of writing to disk.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-story progress logs.",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    workspace = args.workspace.resolve()
    if not (workspace / "analysis").is_dir():
        print(
            f"suggest_negative_path_scenarios: workspace {workspace} is not "
            f"initialized (no analysis/ directory). Run /bsa-start first.",
            file=sys.stderr,
        )
        return 2
    a70_path = workspace / A70_REL
    if not a70_path.is_file():
        print(
            f"suggest_negative_path_scenarios: A70 register not found at "
            f"{a70_path}. Run Phase-3 dev-handoff first.",
            file=sys.stderr,
        )
        return 2

    stories, parse_errors = _read_a70(a70_path)
    if parse_errors:
        print(
            "suggest_negative_path_scenarios: A70 parse errors (fix before retry):",
            file=sys.stderr,
        )
        for e in parse_errors:
            print(f"  {e}", file=sys.stderr)
        return 2

    body = format_json_report(stories) if args.json else format_markdown_report(stories)

    if args.print_only:
        print(body)
        return 0

    output_path = args.output_path
    if output_path is None:
        output_path = workspace / DEFAULT_OUTPUT_REL
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(body, encoding="utf-8")

    if not args.quiet:
        total = sum(len(s.matches) for s in stories)
        with_matches = sum(1 for s in stories if s.matches)
        print(
            f"suggest_negative_path_scenarios: scanned {len(stories)} "
            f"stories; {with_matches} have measurable language; "
            f"{total} suggestions emitted to {output_path}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
