#!/usr/bin/env python3
"""--strict-on-hard-a51 pre-flight check (v1.1.16, Sprint 1 / T6).

Implements the opt-in failure mode spec'd by
`fixtures/golden/adversarial_block_on_contradiction_001/` (v1.1.5).

Default `/bsa-promote` posture is permissive: surface contradictions
as A51 rows, do not block promotion. The strict-mode opt-in flips
the default — any unresolved hard-blocking A51 row blocks promotion
unless explicitly waivered in an H4 packet.

The orchestrator invokes this script via the `pre_bash_promote.sh`
hook BEFORE acquiring the merge lock when the operator passes
`/bsa-promote --strict-on-hard-a51` (or sets
`BSA_STRICT_ON_HARD_A51=1`). Exit 1 with structured BLOCKED stderr
prevents the canonical write.

Stdlib-only.

CLI:
  scripts/promote_strict_preflight.py --workspace <path>

Exit codes:
  0 — pre-flight passes (no hard-blocking unresolved A51, OR all
      such rows are waivered in H4).
  1 — pre-flight blocks (≥1 hard-blocking unresolved A51 with no H4
      waiver). BLOCKED message printed to stderr.
  2 — invocation error (workspace not initialized, A51 file missing,
      malformed CSV, etc.). BLOCKED message NOT printed (different
      failure class — operator misconfiguration, not a real block).

The BLOCKED-message format MUST match the shape pinned by
`tests/test_adversarial_b3_fixtures.py::test_proposed_strict_mode_preflight_blocks_on_open_hard_a51`
so the spec-as-fixture test transitions cleanly from mock to
direct-invocation when this script lands.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

A51_REL_PATHS = (
    "analysis/canonical/core_controls/A51_issue_route_register.csv",
    "analysis/discovery/canonical/core_controls/A51_issue_route_register.csv",
)

# H4 packets live under analysis/handoff/. Any markdown file matching
# H4*.md is inspected for waivers. Pre-handoff promotes have no H4
# packet yet — that's fine, we just have nothing to waiver from.
H4_GLOB = "analysis/handoff/H4*.md"

# Heuristic for the "Decisions Required" waiver section. The H4 spec
# (skills/bsa-handoff-packager/references/h4_spec.md) puts A51Refs
# inside [A51-xxx] brackets in the body of the Decisions Required
# section. We accept either:
#   * `## Decisions Required` (standalone heading)
#   * `## Decisions Required (by severity)` (the project_0001 form)
WAIVER_SECTION_RE = re.compile(
    r"^##\s+Decisions Required\b", re.MULTILINE,
)
A51_REF_IN_WAIVER_RE = re.compile(r"\[(A51-(?:[A-Z]{2,5}-)?[0-9]{3,4})\]")


@dataclass(frozen=True)
class BlockingRow:
    """One A51 row that triggers the strict-mode block."""
    a51_ref: str
    issue_type: str
    severity: str
    next_action: str
    source_path: str  # repo-relative path of the A51 csv where this row lives


def _resolve_a51_paths(workspace: Path) -> list[Path]:
    """Return the A51 CSV paths that exist under the workspace."""
    return [
        p for p in (workspace / rel for rel in A51_REL_PATHS) if p.is_file()
    ]


REQUIRED_A51_COLUMNS = (
    "A51Ref", "IssueType", "Severity", "BlockingStatus",
    "NextAction", "ResolutionStatus",
)


def _read_a51_blockers(a51_path: Path) -> tuple[list[BlockingRow], list[str]]:
    """Parse one A51 CSV; return (blocking_rows, parse_errors).

    Blocking rows: BlockingStatus=hard AND ResolutionStatus=open.
    Parse errors: format violations that prevent classification.

    v1.1.16 round-1 (Codex): earlier version fail-opened on missing
    headers — `csv.DictReader` returns None for absent keys and
    `(row.get(...) or "").strip()` mapped None → "" → row silently
    classified as non-blocking. A blocker with typoed
    `ResolutionStatus` → `Resolution_Status` column would slip
    through strict mode. Now we pre-check the header row for every
    required column AND pre-check row width before per-row
    classification; any violation surfaces as exit-2 parse error
    (the fail-CLOSED default)."""
    blockers: list[BlockingRow] = []
    parse_errors: list[str] = []
    rel = str(a51_path)
    try:
        with a51_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            # Header presence check — fail-closed on typos / missing cols.
            fieldnames = reader.fieldnames or []
            missing_cols = [c for c in REQUIRED_A51_COLUMNS if c not in fieldnames]
            if missing_cols:
                parse_errors.append(
                    f"{rel}: header missing required column(s): "
                    f"{', '.join(missing_cols)}. Found columns: "
                    f"{fieldnames!r}. Fix the header before re-running "
                    f"/bsa-promote --strict-on-hard-a51."
                )
                return blockers, parse_errors
            for idx, row in enumerate(reader, start=2):  # row 1 = header
                # Width check — csv.DictReader silently inserts None for
                # short rows AND puts extras under the `None` key for
                # long rows (unescaped commas, off-by-one cell count).
                # We want to catch BOTH cases and NOT silently classify
                # them as non-blocking.
                #
                # v1.1.16 round-2 (Codex): earlier fix only handled the
                # short-row case (`row.get(c) is None`). Long rows
                # (e.g., unescaped comma in NextAction shifting
                # ResolutionStatus into the overflow) passed through
                # because every named column still got a string value.
                # Fix: also reject any row with content under the `None`
                # key (DictReader's overflow bucket).
                if any(row.get(c) is None for c in REQUIRED_A51_COLUMNS):
                    parse_errors.append(
                        f"{rel}:row {idx}: missing cell(s) for required "
                        f"column(s) (truncated row or extra delimiter). "
                        f"Fix the row before re-running."
                    )
                    continue
                overflow = row.get(None)
                if overflow:
                    parse_errors.append(
                        f"{rel}:row {idx}: extra cell(s) past the last "
                        f"column (unescaped comma in a text field, or "
                        f"off-by-one cell count). Overflow values: "
                        f"{overflow!r}. Quote fields containing commas "
                        f"per RFC 4180 before re-running."
                    )
                    continue
                blocking_status = row["BlockingStatus"].strip()
                resolution_status = row["ResolutionStatus"].strip()
                a51_ref = row["A51Ref"].strip()
                if not a51_ref:
                    parse_errors.append(
                        f"{rel}:row {idx}: empty A51Ref (cannot classify)"
                    )
                    continue
                if blocking_status == "hard" and resolution_status == "open":
                    blockers.append(BlockingRow(
                        a51_ref=a51_ref,
                        issue_type=row["IssueType"].strip(),
                        severity=row["Severity"].strip(),
                        next_action=row["NextAction"].strip(),
                        source_path=rel,
                    ))
    except (OSError, csv.Error) as exc:
        parse_errors.append(f"{rel}: could not parse: {type(exc).__name__}: {exc}")
    return blockers, parse_errors


def _collect_h4_waivers(workspace: Path) -> set[str]:
    """Scan every H4 packet for [A51-xxx] references inside the
    `## Decisions Required` section. Returns the set of waivered
    A51Refs.

    A waiver is operator-attestation that the sponsor has accepted
    the open A51 and approved promotion despite it. The waiver MUST
    appear in `## Decisions Required` specifically — references in
    other H4 sections (Open Items Digest, Suggested Owners, etc.) do
    NOT count as waivers, they're informational.

    Pre-handoff promotes have no H4 packet yet — that's fine, the
    function returns an empty set in that case."""
    waivers: set[str] = set()
    handoff_dir = workspace / "analysis" / "handoff"
    if not handoff_dir.is_dir():
        return waivers
    for h4_path in sorted(handoff_dir.glob("H4*.md")):
        try:
            body = h4_path.read_text(encoding="utf-8")
        except OSError:
            continue
        # Find the Decisions Required section bounds: from the
        # WAIVER_SECTION_RE match through the next `## ` heading
        # (or EOF).
        m = WAIVER_SECTION_RE.search(body)
        if m is None:
            continue
        section_start = m.end()
        next_heading = re.search(r"^## ", body[section_start:], re.MULTILINE)
        section_end = (
            section_start + next_heading.start() if next_heading else len(body)
        )
        section_body = body[section_start:section_end]
        for ref_match in A51_REF_IN_WAIVER_RE.finditer(section_body):
            waivers.add(ref_match.group(1))
    return waivers


def format_blocked_message(blockers: list[BlockingRow]) -> str:
    """Format the BLOCKED message exactly as pinned by
    tests/test_adversarial_b3_fixtures.py::
    test_proposed_strict_mode_preflight_blocks_on_open_hard_a51.

    This format IS the contract — changing it requires updating the
    test in lockstep AND the fixture's audit_expectations.json."""
    lines = [
        f"BLOCKED: /bsa-promote --strict-on-hard-a51 refused canonical "
        f"write — {len(blockers)} unresolved hard-blocking A51 row(s):"
    ]
    for b in blockers:
        # Truncate NextAction to 80 chars for readability; full text
        # remains in the A51 CSV for the operator to read.
        preview = b.next_action[:80] + ("..." if len(b.next_action) > 80 else "")
        lines.append(
            f"  {b.a51_ref} ({b.issue_type}, Severity={b.severity}, "
            f"BlockingStatus=hard, ResolutionStatus=open) — NextAction: "
            f"{preview}"
        )
    return "\n".join(lines) + "\n"


def run_preflight(workspace: Path) -> tuple[int, str]:
    """Returns (exit_code, stderr_text). Caller handles the actual
    sys.exit + sys.stderr.write so this function is pytest-friendly."""
    if not (workspace / "analysis").is_dir():
        return 2, (
            f"[strict-preflight] workspace {workspace} is not initialized "
            f"(no analysis/ directory). Run /bsa-start first.\n"
        )
    a51_paths = _resolve_a51_paths(workspace)
    if not a51_paths:
        # No A51 register exists yet → nothing to block on. Pre-Stage-1
        # promotes legitimately hit this case.
        return 0, ""
    all_blockers: list[BlockingRow] = []
    parse_errors: list[str] = []
    for path in a51_paths:
        blockers, errs = _read_a51_blockers(path)
        all_blockers.extend(blockers)
        parse_errors.extend(errs)
    if parse_errors:
        # Parse errors are operator misconfiguration — distinct from
        # a real block. Exit 2 with the diagnostics.
        return 2, (
            "[strict-preflight] could not classify all A51 rows:\n  "
            + "\n  ".join(parse_errors)
            + "\n"
        )
    if not all_blockers:
        return 0, ""
    waivers = _collect_h4_waivers(workspace)
    unwaivered = [b for b in all_blockers if b.a51_ref not in waivers]
    if not unwaivered:
        # All hard-blockers waivered in H4 → permit promotion.
        return 0, ""
    return 1, format_blocked_message(unwaivered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="--strict-on-hard-a51 pre-flight check for /bsa-promote",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="BSA workspace root (defaults to cwd)",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    exit_code, stderr_text = run_preflight(args.workspace.resolve())
    if stderr_text:
        sys.stderr.write(stderr_text)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
