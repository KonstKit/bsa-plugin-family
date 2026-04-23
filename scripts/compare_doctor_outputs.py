#!/usr/bin/env python3
"""Compare two `bsa doctor` outputs and report which sections changed
status (Section K prep, v1.1.15). Stdlib-only.

Operator workflow (per docs/pilot_2nd_pass_runbook.md):

  1. Capture baseline:    `bsa doctor > pre.txt`  (BEFORE any migration).
  2. Apply migrations:    `python3 scripts/migrate_v1.0_to_v1.1.py ...`
  3. Apply manual fixes:  per the runbook decision trees.
  4. Capture post:        `bsa doctor > post.txt`
  5. Compare:             `python3 scripts/compare_doctor_outputs.py pre.txt post.txt`

The comparison classifies each section as:

  * **CLOSED**    — was FAIL/ERROR in pre, OK in post (migration worked).
  * **NEW**       — was OK/SKIP in pre, FAIL/ERROR in post (regression).
  * **PERSISTED** — was FAIL/ERROR in both (migration didn't fix it).
  * **STILL_OK**  — was OK/SKIP in both (no change).
  * **CHANGED**   — same non-OK status both sides but detail content
                    changed (e.g., went from 5 findings to 3 — partial
                    progress).

Exit codes:
  0 — comparison ran successfully (regardless of outcome counts).
  1 — at least one section is NEW (regression detected; warrants
      operator attention before declaring the migration a success).
  2 — invocation error (file missing, malformed input, etc.).

CLI:
  scripts/compare_doctor_outputs.py pre.txt post.txt           # text report
  scripts/compare_doctor_outputs.py pre.txt post.txt --json    # machine
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Doctor's section-line shape (per scripts/bsa_cli.py::_section):
#   "  marker chain (main): OK"
#   "  marker chain (main): FAIL\n      <indented detail>"        ← 6-space (_indent_detail)
#   "  marker chain (main): ERROR (validator invocation failed)\n      <detail>"
#   "  no-new-stories: SKIP (no A70 yet — Phase 3 not run)"
#   "  content validation: FAIL (3 of 22 files flagged)\n"        ← special block uses
#   "    - [FAIL]  analysis/canonical/...\n"                       ← 4-space + 8-space
#   "        marker[0]: missing 'verdict'\n"                       ← directly (per
#                                                                    bsa_cli.py:929-931)
# Section header is always exactly 2-space indented; detail can be 3+ space
# indented under it. The collector picks up anything indented 3+ spaces so
# both the standard 6-space form AND the content-validation 4-space + 8-space
# form land in the section's detail (round-1 fix: was 6-space-only and would
# misclassify file-list changes as PERSISTED).
SECTION_RE = re.compile(
    r"^  (?P<label>[a-zA-Z0-9 .,\-/_:()]+?): "
    r"(?P<status>OK|FAIL|ERROR|SKIP)"
    r"(?P<rest>.*)$"
)
DETAIL_INDENT_MIN = 3  # spaces; section header uses exactly 2

NORMAL_STATUSES = frozenset({"OK", "SKIP"})  # "non-FAIL" buckets
PROBLEM_STATUSES = frozenset({"FAIL", "ERROR"})


# ---- Parsing ----------------------------------------------------------


@dataclass(frozen=True)
class Section:
    """One parsed section from a doctor run."""
    label: str
    status: str
    detail: str  # multiline, may be ""

    @property
    def is_problem(self) -> bool:
        return self.status in PROBLEM_STATUSES


def parse_doctor_output(body: str) -> dict[str, Section]:
    """Parse a `bsa doctor` capture into a {label: Section} mapping.

    Tolerates:
      * Lines that don't match SECTION_RE (header, summary, blanks) —
        silently skipped.
      * Multi-line detail bodies indented with DETAIL_INDENT (6 spaces).
      * Trailing content on the status line itself (e.g.,
        `content validation: FAIL (3 of 22 files)` — the "(3 of 22 files)"
        part is captured into the detail so a pre→post change in the
        finding count is classified as CHANGED, not PERSISTED).

    Returns dict keyed by section label so two captures can be matched
    pairwise. If the same label appears twice (shouldn't happen in
    well-formed doctor output), the last occurrence wins."""
    out: dict[str, Section] = {}
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        m = SECTION_RE.match(lines[i])
        if m is None:
            i += 1
            continue
        label = m.group("label").strip()
        status = m.group("status")
        rest = m.group("rest").strip()  # trailing on same line, e.g. "(3 of 22 files)"
        # Collect detail lines (anything indented 3+ spaces under the section).
        # The section header uses exactly 2-space indent; detail uses 4 / 6 / 8
        # depending on which validator emitted it. We strip leading whitespace
        # uniformly so the same detail across two captures compares equal even
        # if a future doctor refactor re-indents.
        detail_lines: list[str] = []
        if rest:
            detail_lines.append(rest)
        j = i + 1
        while j < len(lines):
            ln = lines[j]
            if not ln.strip():
                # Blank line — break unless the NEXT line is also detail-indented.
                # This catches the case where a section's detail spans paragraphs.
                if j + 1 < len(lines) and _line_indent(lines[j + 1]) >= DETAIL_INDENT_MIN:
                    j += 1
                    continue
                break
            if _line_indent(ln) < DETAIL_INDENT_MIN:
                # Section header (2-space) or other non-detail line — done.
                break
            detail_lines.append(ln.strip())
            j += 1
        out[label] = Section(
            label=label, status=status, detail="\n".join(detail_lines),
        )
        i = j
    return out


def _line_indent(line: str) -> int:
    """Number of leading space characters on `line`. Tabs are not used in
    doctor output — if they ever appear, the count treats them as 1 char
    each (caller decides whether that's the right semantic)."""
    return len(line) - len(line.lstrip(" "))


# ---- Comparison -------------------------------------------------------


@dataclass(frozen=True)
class SectionDelta:
    """One section's pre→post delta."""
    label: str
    classification: str  # CLOSED / NEW / PERSISTED / STILL_OK / CHANGED / DROPPED / ADDED
    pre_status: str | None  # None if section appeared only in post
    post_status: str | None  # None if section appeared only in pre
    detail_changed: bool


def compare(
    pre: dict[str, Section], post: dict[str, Section],
) -> list[SectionDelta]:
    """Compute per-section deltas. Sections present in only one side
    are classified DROPPED (only-pre) or ADDED (only-post) to surface
    label drift (e.g., the operator ran doctor with a different mode
    that emits a different section label set)."""
    out: list[SectionDelta] = []
    all_labels = sorted(set(pre) | set(post))
    for label in all_labels:
        p = pre.get(label)
        q = post.get(label)
        if p is None:
            out.append(SectionDelta(
                label=label, classification="ADDED",
                pre_status=None,
                post_status=q.status if q else None,
                detail_changed=False,
            ))
            continue
        if q is None:
            out.append(SectionDelta(
                label=label, classification="DROPPED",
                pre_status=p.status, post_status=None,
                detail_changed=False,
            ))
            continue
        # Both present.
        detail_changed = (p.detail != q.detail)
        if p.is_problem and not q.is_problem:
            classification = "CLOSED"
        elif not p.is_problem and q.is_problem:
            classification = "NEW"
        elif p.is_problem and q.is_problem:
            if p.status != q.status:
                # E.g., FAIL → ERROR or ERROR → FAIL — same problem
                # bucket but different validator outcome.
                classification = "CHANGED"
            elif detail_changed:
                # Same status, different findings count → operator made
                # partial progress (e.g., closed 2 of 5 A51 rows).
                classification = "CHANGED"
            else:
                classification = "PERSISTED"
        else:
            classification = "STILL_OK"
        out.append(SectionDelta(
            label=label, classification=classification,
            pre_status=p.status, post_status=q.status,
            detail_changed=detail_changed,
        ))
    return out


# ---- Reporting --------------------------------------------------------


CLASSIFICATION_ORDER = (
    "CLOSED", "NEW", "PERSISTED", "CHANGED", "ADDED", "DROPPED", "STILL_OK",
)


def format_text_report(deltas: list[SectionDelta]) -> str:
    """Operator-facing text report. Groups sections by classification."""
    counts: dict[str, list[SectionDelta]] = {c: [] for c in CLASSIFICATION_ORDER}
    for d in deltas:
        counts[d.classification].append(d)
    lines: list[str] = []
    lines.append(f"# Doctor output comparison ({len(deltas)} sections)")
    lines.append("")
    lines.append("## Summary")
    for c in CLASSIFICATION_ORDER:
        n = len(counts[c])
        if n:
            lines.append(f"  {c:10}  {n:3}")
    if any(counts[c] for c in ("NEW", "PERSISTED", "CHANGED", "ADDED", "DROPPED")):
        lines.append("")
        lines.append("## Sections needing attention")
        for c in ("NEW", "PERSISTED", "CHANGED", "ADDED", "DROPPED"):
            for d in counts[c]:
                pre = d.pre_status or "-"
                post = d.post_status or "-"
                lines.append(f"  [{c}] {d.label} ({pre} → {post})")
    closed = counts["CLOSED"]
    if closed:
        lines.append("")
        lines.append("## Sections closed by the migration (good news)")
        for d in closed:
            lines.append(f"  [CLOSED] {d.label} ({d.pre_status} → {d.post_status})")
    return "\n".join(lines) + "\n"


def format_json_report(deltas: list[SectionDelta]) -> str:
    return json.dumps(
        [
            {
                "label": d.label,
                "classification": d.classification,
                "pre_status": d.pre_status,
                "post_status": d.post_status,
                "detail_changed": d.detail_changed,
            }
            for d in deltas
        ],
        indent=2,
    )


# ---- CLI --------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two `bsa doctor` outputs (pre/post migration)",
    )
    parser.add_argument("pre", type=Path, help="Doctor output captured BEFORE the migration")
    parser.add_argument("post", type=Path, help="Doctor output captured AFTER the migration")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    for label, path in (("pre", args.pre), ("post", args.post)):
        if not path.is_file():
            print(
                f"compare_doctor_outputs: {label} file does not exist: {path}",
                file=sys.stderr,
            )
            return 2
    try:
        pre_body = args.pre.read_text(encoding="utf-8")
        post_body = args.post.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"compare_doctor_outputs: could not read input: {exc}", file=sys.stderr)
        return 2
    pre = parse_doctor_output(pre_body)
    post = parse_doctor_output(post_body)
    # v1.1.15 round-1 fix (Codex): malformed-input check used to only
    # fire when BOTH sides were empty. That meant if one side was
    # malformed (e.g., truncated capture) and the other was healthy,
    # the helper silently reported every section as DROPPED/ADDED —
    # actively misleading the operator. Now: if EITHER side parses
    # empty, exit 2 (invocation error).
    for label, parsed, source in (
        ("pre", pre, args.pre), ("post", post, args.post),
    ):
        if not parsed:
            print(
                f"compare_doctor_outputs: {label} input ({source}) "
                f"contained no recognisable doctor section. Did you "
                f"capture the actual doctor output (not, e.g., the "
                f"doctor command line)?",
                file=sys.stderr,
            )
            return 2
    deltas = compare(pre, post)
    if args.json:
        print(format_json_report(deltas))
    else:
        print(format_text_report(deltas))
    # Exit 1 if any NEW (regression) sections — alerts the operator
    # that the migration introduced a new problem.
    if any(d.classification == "NEW" for d in deltas):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
