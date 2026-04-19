#!/usr/bin/env python3
"""Inventory audit report for skills/.

US-S0-04 (Sprint 0) part 1: generates docs/inventory_audit.md listing
every skill under skills/ with structural health classification. Enables
Phase 1 planning to see at a glance which skills are stable, which carry
TODO/FIXME risk, which are orphan, and which are outright broken.

Classification axes (per skill):
  status            stable | flaky | broken | orphan
  has_references    count of references/*.md files
  has_scripts       bool — scripts/ directory present and non-empty
  has_tests         bool — tests/ dir OR scripts/test_*.py present
  has_fixtures      bool — fixtures/ OR scripts/fixtures/ OR assets/ present
  validation_binding  list of SCN-/CHK-/ART-VAL- IDs extracted from SKILL.md
  notes             short auto-generated justification

Status rules:
  broken  — structural validator fails (validate_skill_structure imported
            as library); or SKILL.md missing entirely
  orphan  — no references/ directory AND no scripts/ AND SKILL.md < 500 chars
  flaky   — SKILL.md or any references/*.md contains FIXME|XXX|TODO|HACK
            markers indicating in-flight work
  stable  — none of the above

Output: docs/inventory_audit.md (overwritten on each run, deterministic).

Usage:
  scripts/inventory_audit.py [--skills-dir=<path>] [--output=<path>]

Exit codes:
  0 — report generated successfully
  1 — at least one skill classified as `broken`
  2 — invocation error
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from validate_skill_structure import validate_skill  # noqa: E402

# Match concrete validation-binding IDs only, never trailing-dash wildcards
# like "SCN-DISC15-001-" or "SCN-*" placeholders. Requires at least one
# token after each dash and each token to contain at least one char.
SCN_PATTERN = re.compile(
    r"\b(?:SCN|CHK|ART-VAL)(?:-[A-Z0-9]+)+(?![A-Z0-9-])"
)
FLAKY_MARKERS = ("FIXME", "XXX", "HACK", "TODO")

STATUS_STABLE = "stable"
STATUS_FLAKY = "flaky"
STATUS_BROKEN = "broken"
STATUS_ORPHAN = "orphan"


@dataclass
class SkillInventory:
    name: str
    path: Path
    status: str
    has_references: int
    has_scripts: bool
    has_tests: bool
    has_fixtures: bool
    validation_binding: list[str]
    notes: str
    validator_findings: list[str] = field(default_factory=list)


def _count_references(skill_dir: Path) -> int:
    refs_dir = skill_dir / "references"
    if not refs_dir.is_dir():
        return 0
    return len(list(refs_dir.glob("*.md")))


def _has_scripts(skill_dir: Path) -> bool:
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return False
    return any(scripts_dir.iterdir())


def _has_tests(skill_dir: Path) -> bool:
    if (skill_dir / "tests").is_dir():
        return True
    scripts_dir = skill_dir / "scripts"
    if scripts_dir.is_dir():
        if list(scripts_dir.glob("test_*.py")):
            return True
    if (skill_dir / "evals").is_dir():
        return True
    return False


def _has_fixtures(skill_dir: Path) -> bool:
    if (skill_dir / "fixtures").is_dir():
        return True
    if (skill_dir / "scripts" / "fixtures").is_dir():
        return True
    if (skill_dir / "assets").is_dir():
        return True
    return False


def _extract_validation_bindings(skill_md_path: Path) -> list[str]:
    if not skill_md_path.is_file():
        return []
    text = skill_md_path.read_text(encoding="utf-8", errors="replace")
    return sorted(set(SCN_PATTERN.findall(text)))


def _detect_flaky_markers(skill_dir: Path) -> list[str]:
    hits: list[str] = []
    candidates = [skill_dir / "SKILL.md"]
    refs_dir = skill_dir / "references"
    if refs_dir.is_dir():
        candidates.extend(refs_dir.glob("*.md"))
    for file_path in candidates:
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for marker in FLAKY_MARKERS:
            if re.search(rf"\b{marker}\b", text):
                hits.append(f"{file_path.relative_to(skill_dir)}:{marker}")
                break
    return hits


def classify(skill_dir: Path) -> SkillInventory:
    name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"

    validator_findings: list[str] = []
    if skill_md.is_file():
        report = validate_skill(skill_md)
        validator_findings = [f.format() for f in report.findings]

    has_refs = _count_references(skill_dir)
    has_scripts = _has_scripts(skill_dir)
    has_tests = _has_tests(skill_dir)
    has_fixtures = _has_fixtures(skill_dir)
    bindings = _extract_validation_bindings(skill_md)
    flaky_hits = _detect_flaky_markers(skill_dir)

    if not skill_md.is_file():
        status = STATUS_BROKEN
        notes = "SKILL.md missing."
    elif validator_findings:
        status = STATUS_BROKEN
        notes = f"structural validator: {len(validator_findings)} finding(s)"
    else:
        skill_md_size = skill_md.stat().st_size
        orphan_candidate = has_refs == 0 and not has_scripts and skill_md_size < 500
        if orphan_candidate:
            status = STATUS_ORPHAN
            notes = "No references/, no scripts/, SKILL.md under 500 bytes."
        elif flaky_hits:
            status = STATUS_FLAKY
            notes = f"in-flight markers: {', '.join(flaky_hits[:3])}"
        else:
            status = STATUS_STABLE
            parts = []
            if has_refs:
                parts.append(f"{has_refs} refs")
            if has_scripts:
                parts.append("scripts")
            if has_tests:
                parts.append("tests")
            if has_fixtures:
                parts.append("fixtures")
            if bindings:
                parts.append(f"{len(bindings)} SCN binding(s)")
            notes = "; ".join(parts) if parts else "SKILL.md only, no supporting assets"

    return SkillInventory(
        name=name,
        path=skill_dir,
        status=status,
        has_references=has_refs,
        has_scripts=has_scripts,
        has_tests=has_tests,
        has_fixtures=has_fixtures,
        validation_binding=bindings,
        notes=notes,
        validator_findings=validator_findings,
    )


def render_report(inventories: list[SkillInventory]) -> str:
    by_status: dict[str, list[SkillInventory]] = {
        STATUS_STABLE: [],
        STATUS_FLAKY: [],
        STATUS_ORPHAN: [],
        STATUS_BROKEN: [],
    }
    for inv in inventories:
        by_status[inv.status].append(inv)

    lines: list[str] = []
    lines.append("# Skill Inventory Audit")
    lines.append("")
    lines.append(
        "Auto-generated by `scripts/inventory_audit.py` (US-S0-04). "
        "Do not edit by hand — re-run the script after changes."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Status | Count | Interpretation |")
    lines.append("|---|---|---|")
    lines.append(
        f"| stable | {len(by_status[STATUS_STABLE])} | "
        "Structural validator passes, no in-flight markers, has supporting assets |"
    )
    lines.append(
        f"| flaky | {len(by_status[STATUS_FLAKY])} | "
        "FIXME/XXX/HACK/TODO present in SKILL.md or references/ |"
    )
    lines.append(
        f"| orphan | {len(by_status[STATUS_ORPHAN])} | "
        "No references/, no scripts/, SKILL.md under 500 bytes |"
    )
    lines.append(
        f"| broken | {len(by_status[STATUS_BROKEN])} | "
        "Validator finding or SKILL.md missing — blocks further Sprint work |"
    )
    lines.append("")

    lines.append("## Per-skill table")
    lines.append("")
    lines.append("| Skill | Status | Refs | Scripts | Tests | Fixtures | Bindings | Notes |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for inv in sorted(inventories, key=lambda x: (x.status != STATUS_BROKEN, x.name)):
        bindings = ", ".join(inv.validation_binding) if inv.validation_binding else "—"
        if len(bindings) > 60:
            bindings = bindings[:57] + "..."
        lines.append(
            f"| {inv.name} | {inv.status} | {inv.has_references} | "
            f"{'✓' if inv.has_scripts else '—'} | "
            f"{'✓' if inv.has_tests else '—'} | "
            f"{'✓' if inv.has_fixtures else '—'} | "
            f"{bindings} | {inv.notes} |"
        )
    lines.append("")

    if by_status[STATUS_BROKEN]:
        lines.append("## Broken skill details")
        lines.append("")
        for inv in by_status[STATUS_BROKEN]:
            lines.append(f"### {inv.name}")
            lines.append("")
            if inv.validator_findings:
                lines.append("Validator findings:")
                lines.append("")
                for finding in inv.validator_findings:
                    lines.append(f"- `{finding}`")
                lines.append("")

    if by_status[STATUS_FLAKY]:
        lines.append("## Flaky skill details (in-flight markers)")
        lines.append("")
        for inv in by_status[STATUS_FLAKY]:
            lines.append(f"- **{inv.name}** — {inv.notes}")
        lines.append("")

    if by_status[STATUS_ORPHAN]:
        lines.append("## Orphan skill details")
        lines.append("")
        for inv in by_status[STATUS_ORPHAN]:
            lines.append(f"- **{inv.name}** — {inv.notes}")
        lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Skill inventory audit (US-S0-04).")
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "skills",
        help="Root skills directory (default: <repo>/skills).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "docs" / "inventory_audit.md",
        help="Output report path (default: <repo>/docs/inventory_audit.md).",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Also print report to stdout.",
    )
    args = parser.parse_args(argv)

    if not args.skills_dir.is_dir():
        print(f"ERROR: skills directory not found: {args.skills_dir}", file=sys.stderr)
        return 2

    skill_dirs = sorted([p for p in args.skills_dir.iterdir() if p.is_dir()])
    if not skill_dirs:
        print(f"ERROR: no skill directories under {args.skills_dir}", file=sys.stderr)
        return 2

    inventories = [classify(d) for d in skill_dirs]
    report = render_report(inventories)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")

    broken = [i for i in inventories if i.status == STATUS_BROKEN]
    flaky = [i for i in inventories if i.status == STATUS_FLAKY]
    orphan = [i for i in inventories if i.status == STATUS_ORPHAN]

    print(
        f"Inventory audit: {len(inventories)} skills — "
        f"{len(inventories) - len(broken) - len(flaky) - len(orphan)} stable, "
        f"{len(flaky)} flaky, {len(orphan)} orphan, {len(broken)} broken. "
        f"Report: {args.output}"
    )
    if args.stdout:
        print(report)

    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
