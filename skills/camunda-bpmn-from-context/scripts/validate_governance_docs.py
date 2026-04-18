#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def _read_text(path):
    return Path(path).read_text(encoding="utf-8")


def _require_contains(name, text, needles, errors):
    lowered = text.lower()
    missing = [needle for needle in needles if needle.lower() not in lowered]
    if missing:
        errors.append(f"{name} missing required markers: {', '.join(missing)}")
        return False
    return True


def _section(name, path, needles):
    return {
        "path": str(path),
        "exists": path.exists(),
        "markers": list(needles),
    }


def _extract_markdown_table_rows(text):
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        rows.append(cells)
    return rows


def _validate_release_phases(text, checks, errors):
    checks["markers"] = [
        "## Phase 0-4 Critical Path",
        "## Phase 5 Deferred Optional Enhancements",
        "## Unified Release Gate",
        "plan_09",
        "deferred optional",
        "plan_14",
        "plan_15",
        "acceptance matrix",
        "manifest schema",
        "preview smoke",
        "governance docs validation",
        "preview_report",
        "typed_issue_targets",
        "usable original fixtures are runtime-tested",
        "partial-DI originals",
    ]
    checks["ok"] = _require_contains("release-phases.md", text, checks["markers"], errors)


def _validate_fr_coverage_map(text, checks, errors):
    checks["markers"] = [
        "## Coverage Table",
        "| FR | Capability | Plan | Primary artifact(s) | Acceptance test(s) |",
        "plan",
        "artifact",
        "acceptance test",
    ]
    markers_ok = _require_contains("fr-coverage-map.md", text, checks["markers"], errors)

    rows = _extract_markdown_table_rows(text)
    fr_rows = []
    for row in rows:
        if not row:
            continue
        candidate = row[0].strip().upper()
        if re.fullmatch(r"FR-0[1-9]", candidate):
            fr_rows.append(row)

    expected = {f"FR-0{index}" for index in range(1, 10)}
    actual = {row[0].strip().upper() for row in fr_rows}
    missing = sorted(expected - actual)
    if missing:
        errors.append(f"fr-coverage-map.md missing FR rows: {', '.join(missing)}")

    malformed_rows = []
    for row in fr_rows:
        if len(row) < 5:
            malformed_rows.append(row[0].strip())
            continue
        if not row[2].strip() or not row[3].strip() or not row[4].strip():
            malformed_rows.append(row[0].strip())
    if malformed_rows:
        errors.append(
            "fr-coverage-map.md has incomplete table rows for: " + ", ".join(sorted(malformed_rows))
        )

    checks["details"] = {
        "fr_rows_detected": sorted(actual),
        "expected_fr_rows": sorted(expected),
    }
    checks["ok"] = markers_ok and not missing and not malformed_rows


def _validate_support_matrix(text, checks, errors):
    checks["markers"] = [
        "## Orchestration Inputs And Hard Exclusions",
        "requested_mode",
        "logic_only",
        "preserve_existing_di",
        "full_relayout",
        "hard exclusions",
        "preserve-only",
        "usable DI",
        "partial DI",
        "native-preserve by default for usable existing DI",
        "partial DI does not imply preserve defaults",
        "simple success requires post-process",
    ]
    checks["ok"] = _require_contains("support-matrix.md", text, checks["markers"], errors)


def _validate_engine_smoke_hooks(text, checks, errors):
    checks["markers"] = [
        "## Unified Release Gate",
        "--gate-profile release_candidate",
        "governance",
        "preview smoke",
        "matrix_summary.json",
    ]
    checks["ok"] = _require_contains("engine-smoke-hooks.md", text, checks["markers"], errors)


def _validate_skill(text, checks, errors):
    checks["markers"] = [
        "references/release-phases.md",
        "references/fr-coverage-map.md",
        "references/support-matrix.md",
    ]
    checks["ok"] = _require_contains("SKILL.md", text, checks["markers"], errors)


def build_checks(docs_root):
    docs_root = Path(docs_root).resolve()
    files = {
        "release_phases": docs_root / "release-phases.md",
        "fr_coverage_map": docs_root / "fr-coverage-map.md",
        "support_matrix": docs_root / "support-matrix.md",
        "engine_smoke_hooks": docs_root / "engine-smoke-hooks.md",
        "skill": docs_root.parent / "SKILL.md",
    }

    checks = {}
    errors = []

    for key, path in files.items():
        exists = path.exists()
        checks[key] = _section(key, path, [])
        checks[key]["exists"] = exists
        if not exists:
            errors.append(f"required governance file missing: {path}")

    if files["release_phases"].exists():
        text = _read_text(files["release_phases"])
        _validate_release_phases(text, checks["release_phases"], errors)
    else:
        checks["release_phases"]["ok"] = False

    if files["fr_coverage_map"].exists():
        text = _read_text(files["fr_coverage_map"])
        _validate_fr_coverage_map(text, checks["fr_coverage_map"], errors)
    else:
        checks["fr_coverage_map"]["ok"] = False

    if files["support_matrix"].exists():
        text = _read_text(files["support_matrix"])
        _validate_support_matrix(text, checks["support_matrix"], errors)
    else:
        checks["support_matrix"]["ok"] = False

    if files["engine_smoke_hooks"].exists():
        text = _read_text(files["engine_smoke_hooks"])
        _validate_engine_smoke_hooks(text, checks["engine_smoke_hooks"], errors)
    else:
        checks["engine_smoke_hooks"]["ok"] = False

    if files["skill"].exists():
        text = _read_text(files["skill"])
        _validate_skill(text, checks["skill"], errors)
    else:
        checks["skill"]["ok"] = False

    ok = not errors and all(item.get("ok") for item in checks.values())
    return {
        "ok": ok,
        "checks": checks,
        "errors": errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate governance docs for the Camunda BPMN skill package.")
    parser.add_argument("--docs-root", required=True, help="Path to the references directory.")
    parser.add_argument(
        "--gate-profile",
        default="pr",
        choices=["pr", "nightly", "release_candidate"],
        help="Acceptance gate profile used for reporting only.",
    )
    args = parser.parse_args(argv)

    result = build_checks(Path(args.docs_root))
    result["docs_root"] = str(Path(args.docs_root).resolve())
    result["gate_profile"] = args.gate_profile
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
