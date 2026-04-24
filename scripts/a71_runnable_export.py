#!/usr/bin/env python3
"""A71 runnable test export (v1.2.3, Sprint 2 / T3).

Closes TODO-S8-01-RUNNABLE-EXPORT from
skills/bsa-test-scenario-builder/SKILL.md. The A71 register is
already Gherkin-shaped (Given / When / Then), so the export step
is a small generator that materialises A71 rows as runnable test
artifacts in three popular formats:

  cucumber    — Cucumber `.feature` files (one per A70 story).
  pytest-bdd  — Cucumber `.feature` + companion Python `test_*.py`
                with module-level `scenarios("...")` bulk loader +
                per-scenario `@given` / `@when` / `@then` step-stub
                functions whose bodies raise
                `pytest.fail("step not implemented")`.
  jest        — Cucumber `.feature` + companion JS `*.steps.js`
                with jest-cucumber `defineFeature` + per-scenario
                `test()` blocks + `given`/`when`/`then` step bodies
                that throw `Error('step not implemented')`.

Output lands under `analysis/handoff/runnable_tests/<format>/`
per workspace. Path is operator-side derived state (NOT canonical;
NOT F5-validated; safe to delete + regenerate).

Stdlib-only. CLI:

  scripts/a71_runnable_export.py --workspace <path> --format cucumber
  scripts/a71_runnable_export.py --workspace <path> --format pytest-bdd
  scripts/a71_runnable_export.py --workspace <path> --format jest
  scripts/a71_runnable_export.py --workspace <path> --format cucumber \\
      --output-dir custom/path/

Default policy (matches the A71 schema's 5-value AutomationStatus
enum + the SKILL.md contract):
  * `automated` + `partial` rows → exported (both have automation).
  * `manual` + `not-automated` rows → SKIPPED unless
    `--include-manual` (semantically equivalent — no automation).
  * `deferred` rows → SKIPPED unless `--include-deferred`; the A51
    reference is preserved as a `# A51Ref=...` comment line.

Exit codes:
  0 — export completed (zero or more files written).
  2 — invocation error (missing workspace, missing A71, malformed
      CSV, unknown format).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

A71_REL = "analysis/canonical/core_controls/A71_test_scenario_register.csv"
DEFAULT_OUTPUT_REL = "analysis/handoff/runnable_tests"

VALID_FORMATS = ("cucumber", "pytest-bdd", "jest")

# Required A71 columns the exporter touches. Extra columns are
# ignored. Missing columns → exit 2 (header validation).
REQUIRED_COLUMNS = (
    "ScenarioID", "Title", "SourceStoryID", "Given", "When", "Then",
    "Tags", "Priority", "AutomationStatus",
)


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    title: str
    story_id: str
    nfr_id: str
    given: str
    when: str
    then: str
    tags: tuple[str, ...]
    priority: str
    automation_status: str
    a51_ref: str
    notes: str


# ---- Parsing -------------------------------------------------------


def _split_tags(raw: str) -> tuple[str, ...]:
    """Tags column is a comma-separated list (per a71.schema.json
    pattern allows `@<tag>` shapes). Empty values filtered out."""
    return tuple(t.strip() for t in raw.split(",") if t.strip())


def _read_a71(a71_path: Path) -> tuple[list[Scenario], list[str]]:
    """Parse A71. Returns (scenarios, parse_errors). Mirrors the
    fail-CLOSED pattern from promote_strict_preflight: header
    pre-check, per-row defensive read."""
    scenarios: list[Scenario] = []
    parse_errors: list[str] = []
    rel = str(a71_path)
    try:
        with a71_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            missing = [c for c in REQUIRED_COLUMNS if c not in fieldnames]
            if missing:
                parse_errors.append(
                    f"{rel}: header missing required column(s): "
                    f"{', '.join(missing)}. Found: {fieldnames!r}."
                )
                return scenarios, parse_errors
            for idx, row in enumerate(reader, start=2):
                if any(row.get(c) is None for c in REQUIRED_COLUMNS):
                    parse_errors.append(
                        f"{rel}:row {idx}: missing cell(s) for required "
                        f"column(s) (truncated row?)."
                    )
                    continue
                # Defensive: long rows (extra commas) put overflow into
                # `None` key; reject — same fail-CLOSED pattern as
                # promote_strict_preflight.
                if row.get(None):
                    parse_errors.append(
                        f"{rel}:row {idx}: extra cell(s) past last column "
                        f"(unescaped comma in a text field?)."
                    )
                    continue
                scenarios.append(Scenario(
                    scenario_id=row["ScenarioID"].strip(),
                    title=row["Title"].strip(),
                    story_id=row["SourceStoryID"].strip(),
                    nfr_id=(row.get("RelatedNFRID") or "").strip(),
                    given=row["Given"].strip(),
                    when=row["When"].strip(),
                    then=row["Then"].strip(),
                    tags=_split_tags(row["Tags"]),
                    priority=row["Priority"].strip(),
                    automation_status=row["AutomationStatus"].strip(),
                    a51_ref=(row.get("A51Ref") or "").strip(),
                    notes=(row.get("Notes") or "").strip(),
                ))
    except (OSError, csv.Error) as exc:
        parse_errors.append(f"{rel}: could not parse: {type(exc).__name__}: {exc}")
    return scenarios, parse_errors


# ---- Filtering -----------------------------------------------------


def filter_scenarios(
    scenarios: list[Scenario],
    *,
    include_manual: bool, include_deferred: bool,
) -> list[Scenario]:
    """Apply the AutomationStatus inclusion policy.

    A71 schema (governance/schemas/a71.schema.json) defines 5 enum values
    for AutomationStatus: automated, partial, manual, deferred,
    not-automated. v1.2.3 round-1 (Codex CRITICAL): earlier impl only
    handled 3 of the 5 — `partial` + `not-automated` rows silently
    disappeared. Fix: cover all 5 with explicit policy:

      automated     → exported by default (full automation exists).
      partial       → exported by default (some steps automated; the
                      manual portions become stub bodies the operator
                      fills in).
      manual        → SKIPPED unless --include-manual.
      not-automated → SKIPPED unless --include-manual (semantically
                      equivalent: 'no automation'; the `not-automated`
                      label is the explicit-no, `manual` is the
                      manual-runbook variant).
      deferred      → SKIPPED unless --include-deferred (work pending;
                      A51Ref preserved as comment in deferred output).
    """
    out: list[Scenario] = []
    for s in scenarios:
        status = s.automation_status
        if status in ("automated", "partial"):
            out.append(s)
        elif status in ("manual", "not-automated") and include_manual:
            out.append(s)
        elif status == "deferred" and include_deferred:
            out.append(s)
        # else: silently dropped (default policy + non-canonical statuses)
    return out


# ---- Format generators ---------------------------------------------


def _gherkin_scenario_block(s: Scenario, indent: str = "  ") -> str:
    """Render one A71 row as a Gherkin Scenario block. Tags line
    appears above `Scenario:`; the Then-clause is rendered verbatim
    (no auto-splitting on AND — a single A71 row = a single
    semantic Then-assertion)."""
    lines: list[str] = []
    if s.tags:
        lines.append(indent + " ".join(s.tags))
    lines.append(f"{indent}Scenario: {s.scenario_id} — {s.title}")
    lines.append(f"{indent}  Given {s.given}")
    lines.append(f"{indent}  When {s.when}")
    lines.append(f"{indent}  Then {s.then}")
    return "\n".join(lines)


def _feature_body(story_id: str, scenarios: list[Scenario]) -> str:
    """One .feature file per A70 story. Header includes the story
    ID; per-scenario blocks follow. v1.2.3: scenarios with non-
    empty A51Ref get a comment line above the Scenario: line so
    the operator can trace the deferral context."""
    lines = [
        f"# Auto-generated from A71 — do not edit manually.",
        f"# Re-generate via: scripts/a71_runnable_export.py --workspace <ws> --format cucumber",
        "",
        f"Feature: {story_id}",
        f"  Test scenarios for {story_id} (sourced from A71_test_scenario_register.csv)",
        "",
    ]
    for s in scenarios:
        if s.a51_ref:
            lines.append(f"  # A51Ref={s.a51_ref}: {s.notes[:80]}")
        if s.nfr_id:
            lines.append(f"  # RelatedNFRID={s.nfr_id}")
        lines.append(_gherkin_scenario_block(s))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _safe_filename(story_id: str, ext: str) -> str:
    """Convert STORY-001 / STORY-PERF-002 → story_001.feature etc.
    Lowercase + underscore + ext."""
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", story_id).strip("_").lower()
    return f"{safe}.{ext}"


def _python_step_module(story_id: str, scenarios: list[Scenario]) -> str:
    """pytest-bdd companion. Imports the generated .feature file +
    declares stub step functions so the operator gets a runnable
    skeleton + clear `pytest.fail("step not implemented")` markers
    that surface unimplemented work."""
    feature_filename = _safe_filename(story_id, "feature")
    lines = [
        '"""Auto-generated pytest-bdd module from A71. Do not edit manually."""',
        "",
        "import pytest",
        "from pytest_bdd import scenarios, given, when, then",
        "",
        f'scenarios("{feature_filename}")',
        "",
        "# Stub step functions — implement these against your system under test.",
        "# Each parametrised string MUST exactly match the corresponding A71",
        "# Given/When/Then row; re-generation will overwrite this file.",
        "",
    ]
    for s in scenarios:
        for kw, text in (("given", s.given), ("when", s.when), ("then", s.then)):
            decorator_text = text.replace('"', '\\"')
            fn_name = f"_{kw}_{s.scenario_id.lower().replace('-', '_')}"
            lines.extend([
                f'@{kw}("{decorator_text}")',
                f"def {fn_name}():",
                f'    pytest.fail("step not implemented: {kw} for {s.scenario_id}")',
                "",
            ])
    return "\n".join(lines).rstrip() + "\n"


def _jest_step_module(story_id: str, scenarios: list[Scenario]) -> str:
    """jest-cucumber companion. Single defineFeature block per .feature."""
    feature_filename = _safe_filename(story_id, "feature")
    lines = [
        "// Auto-generated jest-cucumber module from A71. Do not edit manually.",
        "",
        "const { defineFeature, loadFeature } = require('jest-cucumber');",
        "",
        f"const feature = loadFeature('./{feature_filename}');",
        "",
        "defineFeature(feature, test => {",
    ]
    for s in scenarios:
        title = s.title.replace("'", "\\'")
        lines.append(f"  test('{s.scenario_id} — {title}', ({{ given, when, then }}) => {{")
        for kw, text in (("given", s.given), ("when", s.when), ("then", s.then)):
            text_escaped = text.replace("'", "\\'")
            lines.append(f"    {kw}('{text_escaped}', () => {{")
            lines.append(f"      throw new Error('step not implemented: {kw} for {s.scenario_id}');")
            lines.append("    });")
        lines.append("  });")
    lines.append("});")
    return "\n".join(lines).rstrip() + "\n"


# ---- Driver --------------------------------------------------------


def _group_by_story(scenarios: list[Scenario]) -> dict[str, list[Scenario]]:
    out: dict[str, list[Scenario]] = {}
    for s in scenarios:
        out.setdefault(s.story_id, []).append(s)
    return out


def export_cucumber(
    output_dir: Path, scenarios: list[Scenario],
) -> list[Path]:
    """Emit one .feature per story. Returns list of written paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for story_id, story_scenarios in sorted(_group_by_story(scenarios).items()):
        target = output_dir / _safe_filename(story_id, "feature")
        target.write_text(_feature_body(story_id, story_scenarios), encoding="utf-8")
        written.append(target)
    return written


def export_pytest_bdd(
    output_dir: Path, scenarios: list[Scenario],
) -> list[Path]:
    """Emit one .feature + one test_<story>.py per story."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for story_id, story_scenarios in sorted(_group_by_story(scenarios).items()):
        feature_path = output_dir / _safe_filename(story_id, "feature")
        feature_path.write_text(_feature_body(story_id, story_scenarios), encoding="utf-8")
        written.append(feature_path)
        py_filename = "test_" + _safe_filename(story_id, "py")
        py_path = output_dir / py_filename
        py_path.write_text(_python_step_module(story_id, story_scenarios), encoding="utf-8")
        written.append(py_path)
    return written


def export_jest(
    output_dir: Path, scenarios: list[Scenario],
) -> list[Path]:
    """Emit one .feature + one <story>.steps.js per story."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for story_id, story_scenarios in sorted(_group_by_story(scenarios).items()):
        feature_path = output_dir / _safe_filename(story_id, "feature")
        feature_path.write_text(_feature_body(story_id, story_scenarios), encoding="utf-8")
        written.append(feature_path)
        js_filename = _safe_filename(story_id, "steps.js")
        js_path = output_dir / js_filename
        js_path.write_text(_jest_step_module(story_id, story_scenarios), encoding="utf-8")
        written.append(js_path)
    return written


# ---- CLI -----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="A71 runnable test export (Cucumber / pytest-bdd / jest)",
    )
    parser.add_argument(
        "--workspace", type=Path, default=Path.cwd(),
        help="BSA workspace root (defaults to cwd)",
    )
    parser.add_argument(
        "--format", required=True, choices=VALID_FORMATS,
        help="Output format",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help=(
            "Override output dir (default: <workspace>/"
            f"{DEFAULT_OUTPUT_REL}/<format>/)."
        ),
    )
    parser.add_argument(
        "--include-manual", action="store_true",
        help="Also export rows with AutomationStatus in {manual, not-automated}.",
    )
    parser.add_argument(
        "--include-deferred", action="store_true",
        help="Also export rows with AutomationStatus=deferred (A51Ref kept as comment).",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-file progress logs.",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    workspace = args.workspace.resolve()
    if not (workspace / "analysis").is_dir():
        print(
            f"a71_runnable_export: workspace {workspace} is not initialized "
            f"(no analysis/ directory). Run /bsa-start first.",
            file=sys.stderr,
        )
        return 2

    a71_path = workspace / A71_REL
    if not a71_path.is_file():
        print(
            f"a71_runnable_export: A71 register not found at {a71_path}. "
            f"Run Phase-3 dev-handoff first.",
            file=sys.stderr,
        )
        return 2

    scenarios, parse_errors = _read_a71(a71_path)
    if parse_errors:
        print(
            "a71_runnable_export: A71 parse errors (fix before retry):",
            file=sys.stderr,
        )
        for e in parse_errors:
            print(f"  {e}", file=sys.stderr)
        return 2

    filtered = filter_scenarios(
        scenarios,
        include_manual=args.include_manual,
        include_deferred=args.include_deferred,
    )

    output_dir = args.output_dir
    if output_dir is None:
        output_dir = workspace / DEFAULT_OUTPUT_REL / args.format

    if args.format == "cucumber":
        written = export_cucumber(output_dir, filtered)
    elif args.format == "pytest-bdd":
        written = export_pytest_bdd(output_dir, filtered)
    else:  # jest
        written = export_jest(output_dir, filtered)

    if not args.quiet:
        print(
            f"a71_runnable_export: format={args.format} "
            f"scenarios_total={len(scenarios)} "
            f"scenarios_exported={len(filtered)} "
            f"files_written={len(written)} "
            f"output_dir={output_dir}",
        )
        for p in written:
            print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
