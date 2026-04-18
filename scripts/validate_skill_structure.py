#!/usr/bin/env python3
"""Structural linter for SKILL.md files.

US-S0-02 (Sprint 0): validates per-skill frontmatter and reference
links to catch structural drift before it reaches main.

Checks performed per SKILL.md:
  1. Frontmatter block present and parseable (--- ... --- at top).
  2. Required frontmatter fields: name, description.
  3. `name` matches the containing directory (catches rename drift).
  4. Every relative markdown link [text](path) into references/*.md,
     scripts/*.{py,sh}, assets/*, tests/*.py, or evals/*.sh resolves
     to an existing file.

Out of scope (by design):
  - Content quality of referenced files (separate validators)
  - Cross-skill links (handled by routing validator, Sprint 0.5)
  - External URLs (http/https) — not structural drift
  - SKILL.md body semantics — not a structural concern

Usage:
  scripts/validate_skill_structure.py <SKILL.md> [<SKILL.md> ...]
  scripts/validate_skill_structure.py skills/*/SKILL.md

Exit codes:
  0 — all files pass
  1 — at least one file has structural findings
  2 — invocation error (no files provided, file not found, etc.)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
FRONTMATTER_LINE_RE = re.compile(r"^(?P<key>[A-Za-z_][\w-]*)\s*:\s*(?P<value>.*)$")

REQUIRED_FRONTMATTER_FIELDS = ("name", "description")

RELATIVE_LINK_PREFIXES = (
    "references/",
    "scripts/",
    "assets/",
    "tests/",
    "evals/",
)


@dataclass
class Finding:
    """A single structural problem."""

    skill_path: Path
    code: str
    message: str

    def format(self) -> str:
        return f"{self.skill_path}: [{self.code}] {self.message}"


@dataclass
class SkillReport:
    skill_path: Path
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings


def parse_frontmatter(text: str) -> tuple[dict[str, str] | None, str]:
    """Extract frontmatter key/value pairs + reason if parse fails.

    Returns (fields, error_message). If frontmatter is well-formed,
    error_message == ''. If malformed, fields is None.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, "missing or malformed frontmatter block (expected '---' fence at start of file)"
    body = match.group(1)
    fields: dict[str, str] = {}
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        m = FRONTMATTER_LINE_RE.match(line)
        if not m:
            continue
        key = m.group("key")
        value = m.group("value").strip()
        # Unquote single- OR double-quoted scalar values.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
            value = value[1:-1]
        fields[key] = value
    return fields, ""


def extract_markdown_links(text: str) -> list[tuple[str, str]]:
    """Return list of (link_text, target) for markdown links in text.

    Hand-written scanner (not a regex) to correctly handle common CommonMark
    variants the simple regex version missed:
      - [text](dest "title")     — double-quoted title
      - [text](dest 'title')     — single-quoted title
      - [text](dest (title))     — parenthesized title
      - [text](path(with)parens) — balanced parens inside destination

    Only extracts destination (dest); title is discarded. Reference-style
    links ([text][ref]) and autolinks (<url>) are intentionally ignored —
    they are not used in structural SKILL.md references.
    """
    results: list[tuple[str, str]] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "[":
            i += 1
            continue
        # Find matching ]. Disallow nested [ ] for simplicity; SKILL.md
        # structural references never need nested brackets.
        j = text.find("]", i + 1)
        if j == -1:
            break
        if j + 1 >= n or text[j + 1] != "(":
            i = j + 1
            continue
        link_text = text[i + 1 : j]
        # Scan inside (...) with balanced-paren awareness.
        k = j + 2
        depth = 1
        while k < n and depth > 0:
            ch = text[k]
            if ch == "(":
                depth += 1
                k += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
                k += 1
            else:
                k += 1
        if depth != 0:
            # Unbalanced; give up on this candidate, advance past [.
            i = i + 1
            continue
        inside = text[j + 2 : k]
        dest = _extract_link_destination(inside)
        if dest:
            results.append((link_text, dest))
        i = k + 1
    return results


def _extract_link_destination(inside: str) -> str:
    """Extract destination portion from the inside of a markdown link's parens.

    CommonMark destination grammar (simplified): the destination is the
    first run of non-whitespace characters. An optional title may follow
    after whitespace in "...", '...', or (...). We return only destination.
    Balanced parens inside an unbracketed destination are permitted.
    """
    inside = inside.strip()
    if not inside:
        return ""
    # Angle-bracket form <url> — rare in structural refs, but handle:
    if inside.startswith("<"):
        close = inside.find(">")
        return inside[1:close] if close != -1 else ""
    # Walk until first whitespace not inside balanced parens.
    depth = 0
    end = len(inside)
    for idx, ch in enumerate(inside):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch.isspace() and depth == 0:
            end = idx
            break
    return inside[:end]


def should_check_target(target: str) -> bool:
    """Decide if a link target is a structural reference we must resolve."""
    if target.startswith(("http://", "https://", "mailto:")):
        return False
    if target.startswith("#"):
        return False
    if target.startswith("/"):
        return False
    if ":" in target.split("/", 1)[0]:
        return False
    return target.startswith(RELATIVE_LINK_PREFIXES)


def validate_skill(skill_md_path: Path) -> SkillReport:
    report = SkillReport(skill_path=skill_md_path)

    if not skill_md_path.is_file():
        report.findings.append(Finding(skill_md_path, "not-a-file", "SKILL.md not found"))
        return report

    text = skill_md_path.read_text(encoding="utf-8")

    fields, err = parse_frontmatter(text)
    if fields is None:
        report.findings.append(Finding(skill_md_path, "frontmatter-missing", err))
        return report

    for required in REQUIRED_FRONTMATTER_FIELDS:
        if required not in fields or not fields[required]:
            report.findings.append(
                Finding(
                    skill_md_path,
                    "frontmatter-field-missing",
                    f"missing required frontmatter field: {required}",
                )
            )

    if "name" in fields and fields["name"]:
        expected_name = skill_md_path.parent.name
        declared_name = fields["name"]
        if declared_name != expected_name:
            report.findings.append(
                Finding(
                    skill_md_path,
                    "name-directory-mismatch",
                    f"frontmatter name='{declared_name}' does not match directory '{expected_name}'",
                )
            )

    skill_root = skill_md_path.parent
    try:
        skill_root_resolved = skill_root.resolve()
    except (OSError, RuntimeError) as exc:
        report.findings.append(
            Finding(
                skill_md_path,
                "resolve-error",
                f"cannot resolve skill root: {exc}",
            )
        )
        return report

    for _text, target in extract_markdown_links(text):
        if not should_check_target(target):
            continue
        clean_target = target.split("#", 1)[0]
        try:
            candidate = (skill_root / clean_target).resolve()
        except (OSError, RuntimeError) as exc:
            report.findings.append(
                Finding(
                    skill_md_path,
                    "resolve-error",
                    f"cannot resolve link target '{target}': {exc}",
                )
            )
            continue
        try:
            candidate.relative_to(skill_root_resolved)
        except ValueError:
            report.findings.append(
                Finding(
                    skill_md_path,
                    "link-escapes-skill",
                    f"link target escapes skill root: {target}",
                )
            )
            continue
        if not candidate.exists():
            report.findings.append(
                Finding(
                    skill_md_path,
                    "broken-reference",
                    f"broken reference: skills/{skill_root.name}/{clean_target}",
                )
            )

    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Structural validator for SKILL.md files (US-S0-02).",
    )
    parser.add_argument(
        "skill_files",
        nargs="+",
        help="Paths to SKILL.md files. Supports shell globbing (e.g. skills/*/SKILL.md).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-file PASS lines; only print findings and summary.",
    )
    args = parser.parse_args(argv)

    paths = [Path(p) for p in args.skill_files]
    missing = [p for p in paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"ERROR: file does not exist: {p}", file=sys.stderr)
        return 2

    reports = [validate_skill(p) for p in paths]

    total_findings = 0
    for report in reports:
        if report.passed:
            if not args.quiet:
                print(f"PASS {report.skill_path}")
        else:
            for finding in report.findings:
                print(finding.format(), file=sys.stderr)
                total_findings += 1

    failed_count = sum(1 for r in reports if not r.passed)
    print(
        f"Summary: {len(reports) - failed_count}/{len(reports)} passed, "
        f"{failed_count} failed, {total_findings} findings total.",
        file=sys.stderr if failed_count else sys.stdout,
    )

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
