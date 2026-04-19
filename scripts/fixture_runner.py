#!/usr/bin/env python3
"""Golden-fixture runner for BSA plugin family (US-S05-01).

Two modes:

  --mode=validate  — check fixture-internal invariants without touching
                     the on-disk state. Verifies:
                       * A59 ClaimType enum closed to {direct, inference,
                         analyst_judgment} (INV-07)
                       * Every A59 row has SourceID+ExcerptID OR A51Ref
                         (evidence-binding; INV-01)
                       * analyst_judgment rows carry non-empty
                         justification_rationale referencing >=1 ClaimID
                       * Every A58 ExcerptID referenced by A59 exists
                       * Every A60 RelatedClaimID points at an A59 row
                       * A51 rows have IssueType, Severity, BlockingStatus
                       * Marker JSONs have canon_policy_version + verdict
                       * fixture_metadata.json carries required keys

  --mode=compare   — regenerates nothing; re-reads committed fixture state
                     and diffs against a cached snapshot captured at the
                     start of the run. Catches in-place mutation during
                     test execution. (Sprint 4.5 will extend this mode to
                     compare against live-pipeline regenerated outputs.)

Exit codes:
  0 — all requested modes pass for all selected fixtures
  1 — at least one fixture finding
  2 — invocation error (missing fixture dir, malformed JSON/CSV, bad CLI)

Stdlib-only. csv module handles quoting rules per RFC 4180.

Usage:
  scripts/fixture_runner.py                     # validate all fixtures
  scripts/fixture_runner.py --fixture project_0001
  scripts/fixture_runner.py --mode=compare
  scripts/fixture_runner.py --all --mode=validate
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ALLOWED_CLAIM_TYPES = frozenset({"direct", "inference", "analyst_judgment"})
CLAIMID_REF_RE = re.compile(r"\bC-\d+\b")
# Match locator forms "file.md:L12" or "file.md:L12-L16". Anything else
# surfaces as a finding so future fixtures cannot quietly drift.
LOCATOR_RE = re.compile(r"^(?P<file>[^:]+):L(?P<start>\d+)(?:-L(?P<end>\d+))?$")

# Stage 2 shape contract (from bsa-context-framer/references/context-state-contract.md
# + bsa-orchestrator/references/stage2-runtime-contract.md; both must stay in lockstep).
STAGE2_CONTEXT_STATE_REQUIRED_HEADERS = (
    "## Problem Or Objective",
    "## Scope Boundary",
    "## Context Mode",
    "## Stakeholders",
    "## Constraints",
    "## Dependencies",
    "## Open Uncertainties",
)
STAGE2_SYSTEM_CONTEXT_REQUIRED_HEADERS = (
    "## System Boundary",
    "## Neighboring Systems",
    "## Interface Obligations",
    "## Context Triggers",
)
STAGE2_STAKEHOLDER_COLUMNS = (
    "stakeholder_id", "stakeholder_name", "authority_level",
    "decision_scope", "linked_a51_refs",
)
STAGE2_CONSTRAINTS_COLUMNS = (
    "constraint_id", "dependency_id", "source_ref",
    "escalation_target", "linked_a51_refs",
)
STAGE2_SUMMARY_REQUIRED_FIELDS = (
    "stage_id", "summary_version", "context_mode",
    "stakeholder_count", "constraint_count", "dependency_count",
    "seed_source", "stage1_digest", "stage2_seed_digest",
    "methodology_digest", "contract_version", "stale_if",
    "linked_a51_count", "required_headers_present",
)


@dataclass
class Finding:
    fixture_id: str
    code: str
    message: str

    def format(self) -> str:
        return f"{self.fixture_id}: [{self.code}] {self.message}"


@dataclass
class FixtureReport:
    fixture_id: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader]


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _locate_fixture_files(fixture_dir: Path) -> dict[str, Path]:
    canonical_root = fixture_dir / "expected_outputs" / "canonical" / "core_controls"
    markers_root = fixture_dir / "expected_markers"
    return {
        "a50": canonical_root / "A50_source_register.csv",
        "a51": canonical_root / "A51_issue_route_register.csv",
        "a58": canonical_root / "A58_evidence_excerpts.csv",
        "a59": canonical_root / "A59_claim_register.csv",
        "a60": canonical_root / "A60_negative_evidence_register.csv",
        "audit_expectations": fixture_dir / "audit_expectations.json",
        "fixture_metadata": fixture_dir / "fixture_metadata.json",
        "markers_dir": markers_root,
    }


PREP_SHELL_AUTHORING_MODE = "synthetic_representative_prep"
PREP_SHELL_METADATA_REQUIRED = (
    "fixture_id", "canon_policy_version", "authoring_mode",
    "scenario_tags", "plugin_version", "captured_at",
    "model_used", "model_version_hash",
)


def _validate_prep_shell(
    fixture_dir: Path,
    metadata: dict,
    report: "FixtureReport",
) -> "FixtureReport":
    """Validate a prep-shell fixture (US-S2-03).

    Prep shells intentionally ship without expected_outputs/: they provide
    only fixture_metadata.json (declaring authoring_mode = synthetic_
    representative_prep), README.md, and one or more sanitized inputs/
    files. Sprint 4.5 US-S45-01 then populates expected_outputs/.
    """
    for required in PREP_SHELL_METADATA_REQUIRED:
        if required not in metadata:
            report.findings.append(Finding(
                report.fixture_id, "metadata-field",
                f"prep shell fixture_metadata.json: missing '{required}'",
            ))
    if metadata.get("fixture_id") and metadata["fixture_id"] != fixture_dir.name:
        report.findings.append(Finding(
            report.fixture_id, "metadata-id-mismatch",
            f"fixture_metadata.fixture_id '{metadata.get('fixture_id')}' "
            f"!= directory '{fixture_dir.name}'",
        ))
    tags = metadata.get("scenario_tags")
    if not isinstance(tags, list) or not tags:
        report.findings.append(Finding(
            report.fixture_id, "metadata-scenario-tags",
            "prep shell scenario_tags must be a non-empty list",
        ))

    readme = fixture_dir / "README.md"
    if not readme.is_file():
        report.findings.append(Finding(
            report.fixture_id, "missing-file",
            "prep shell requires README.md",
        ))

    inputs = fixture_dir / "inputs"
    if not inputs.is_dir():
        report.findings.append(Finding(
            report.fixture_id, "missing-file",
            "prep shell requires inputs/ directory",
        ))
    else:
        input_files = [p for p in inputs.iterdir() if p.is_file()]
        if not input_files:
            report.findings.append(Finding(
                report.fixture_id, "missing-file",
                "prep shell requires at least one file under inputs/",
            ))

    return report


def validate_fixture(fixture_dir: Path) -> FixtureReport:
    report = FixtureReport(fixture_id=fixture_dir.name)

    if not fixture_dir.is_dir():
        report.findings.append(Finding(report.fixture_id, "missing-fixture", f"not a directory: {fixture_dir}"))
        return report

    files = _locate_fixture_files(fixture_dir)

    # Peek at fixture_metadata.json to detect prep-shell fixtures (US-S2-03).
    # Prep shells validate only the skeleton (metadata + README + inputs),
    # not the full claim layer, since they intentionally ship without
    # expected_outputs/ yet. Keep this check BEFORE the required-files sweep
    # so prep shells do not trigger missing-file findings on CSVs they
    # legitimately lack.
    if files["fixture_metadata"].is_file():
        try:
            metadata_peek = _read_json(files["fixture_metadata"])
        except (json.JSONDecodeError, UnicodeDecodeError):
            metadata_peek = None
        if (
            isinstance(metadata_peek, dict)
            and metadata_peek.get("authoring_mode") == PREP_SHELL_AUTHORING_MODE
        ):
            return _validate_prep_shell(fixture_dir, metadata_peek, report)

    for key in ("a50", "a51", "a58", "a59", "a60", "audit_expectations", "fixture_metadata"):
        if not files[key].is_file():
            report.findings.append(Finding(
                report.fixture_id, "missing-file",
                f"required fixture file missing: {files[key].name}",
            ))
    if report.findings:
        return report

    try:
        a58_rows = _read_csv_rows(files["a58"])
        a59_rows = _read_csv_rows(files["a59"])
        a60_rows = _read_csv_rows(files["a60"])
        a51_rows = _read_csv_rows(files["a51"])
        metadata = _read_json(files["fixture_metadata"])
        expectations = _read_json(files["audit_expectations"])
    except (csv.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        report.findings.append(Finding(report.fixture_id, "parse-error", f"cannot parse fixture file: {exc}"))
        return report

    excerpt_ids = {row.get("ExcerptID") for row in a58_rows if row.get("ExcerptID")}
    claim_ids = {row.get("ClaimID") for row in a59_rows if row.get("ClaimID")}
    a51_refs = {row.get("A51Ref") for row in a51_rows if row.get("A51Ref")}

    # ---- A58 locator existence + range validation -----------------
    inputs_dir = fixture_dir / "inputs"
    try:
        inputs_dir_resolved = inputs_dir.resolve()
    except (OSError, RuntimeError) as exc:
        report.findings.append(Finding(
            report.fixture_id, "locator-read-error",
            f"cannot resolve inputs/ directory: {exc}",
        ))
        inputs_dir_resolved = None
    for i, row in enumerate(a58_rows):
        row_label = row.get("ExcerptID") or f"row[{i}]"
        locator = row.get("Locator") or ""
        m = LOCATOR_RE.match(locator)
        if not m:
            report.findings.append(Finding(
                report.fixture_id, "locator-shape",
                f"A58 {row_label}: Locator '{locator}' does not match "
                f"'<file>:L<start>' or '<file>:L<start>-L<end>'",
            ))
            continue
        raw_rel = m.group("file")
        loc_file = inputs_dir / raw_rel
        # Containment check: resolved locator must live under inputs/.
        # Prevents traversal bypass via locators like '../fixture_metadata.json:L1'.
        if inputs_dir_resolved is not None:
            try:
                loc_file_resolved = loc_file.resolve()
            except (OSError, RuntimeError) as exc:
                report.findings.append(Finding(
                    report.fixture_id, "locator-read-error",
                    f"A58 {row_label}: cannot resolve locator path: {exc}",
                ))
                continue
            try:
                loc_file_resolved.relative_to(inputs_dir_resolved)
            except ValueError:
                report.findings.append(Finding(
                    report.fixture_id, "locator-escapes-inputs",
                    f"A58 {row_label}: Locator file '{raw_rel}' escapes inputs/",
                ))
                continue
        if not loc_file.is_file():
            report.findings.append(Finding(
                report.fixture_id, "locator-file-missing",
                f"A58 {row_label}: Locator file '{raw_rel}' not found under inputs/",
            ))
            continue
        try:
            line_count = sum(1 for _ in loc_file.open("r", encoding="utf-8", errors="replace"))
        except OSError as exc:
            report.findings.append(Finding(
                report.fixture_id, "locator-read-error",
                f"A58 {row_label}: cannot read locator file: {exc}",
            ))
            continue
        start = int(m.group("start"))
        end = int(m.group("end")) if m.group("end") else start
        if start < 1 or end > line_count or start > end:
            report.findings.append(Finding(
                report.fixture_id, "locator-out-of-range",
                f"A58 {row_label}: Locator range L{start}-L{end} outside "
                f"file length {line_count} of '{m.group('file')}'",
            ))

    # ---- A59 invariants ---------------------------------------------
    for i, row in enumerate(a59_rows):
        row_label = row.get("ClaimID") or f"row[{i}]"
        ctype = row.get("ClaimType") or ""
        if ctype not in ALLOWED_CLAIM_TYPES:
            report.findings.append(Finding(
                report.fixture_id, "claim-type-closed",
                f"A59 {row_label}: ClaimType '{ctype}' not in {sorted(ALLOWED_CLAIM_TYPES)} (INV-07)",
            ))
            continue

        has_source_excerpt = bool(row.get("SourceID")) and bool(row.get("ExcerptID"))
        a51ref = row.get("A51Ref") or ""

        # INV-01 evidence-binding applies to EVERY row regardless of ClaimType.
        # A row must have SourceID+ExcerptID OR A51Ref. The analyst_judgment
        # class does not exempt a row from governance tracking — it just
        # adds the JustificationRationale+upstream requirement on top.
        if not has_source_excerpt and not a51ref:
            report.findings.append(Finding(
                report.fixture_id, "evidence-binding",
                f"A59 {row_label}: requires SourceID+ExcerptID OR A51Ref (INV-01)",
            ))
        if row.get("ExcerptID") and row["ExcerptID"] not in excerpt_ids:
            report.findings.append(Finding(
                report.fixture_id, "excerpt-not-found",
                f"A59 {row_label}: ExcerptID '{row['ExcerptID']}' not in A58",
            ))

        if ctype == "analyst_judgment":
            justification = row.get("JustificationRationale") or ""
            if not justification.strip():
                report.findings.append(Finding(
                    report.fixture_id, "judgment-missing-justification",
                    f"A59 {row_label}: analyst_judgment requires non-empty JustificationRationale",
                ))
                continue
            upstream_refs = CLAIMID_REF_RE.findall(justification)
            own_id = row.get("ClaimID") or ""
            # Self-references do not satisfy the upstream-claim requirement.
            non_self_refs = [r for r in upstream_refs if r != own_id]
            if not non_self_refs:
                report.findings.append(Finding(
                    report.fixture_id, "judgment-missing-upstream-claim",
                    f"A59 {row_label}: analyst_judgment JustificationRationale "
                    f"must reference >=1 upstream ClaimID different from {own_id or 'self'}",
                ))
            else:
                missing_up = [r for r in non_self_refs if r not in claim_ids]
                if missing_up:
                    report.findings.append(Finding(
                        report.fixture_id, "judgment-upstream-not-found",
                        f"A59 {row_label}: upstream ClaimID(s) not in A59: {missing_up}",
                    ))

        if a51ref and a51ref not in a51_refs:
            report.findings.append(Finding(
                report.fixture_id, "a51-ref-not-found",
                f"A59 {row_label}: A51Ref '{a51ref}' not in A51",
            ))

    # ---- A60 invariants ---------------------------------------------
    for i, row in enumerate(a60_rows):
        row_label = row.get("NegEvID") or f"row[{i}]"
        rel = row.get("RelatedClaimID") or ""
        if rel and rel not in claim_ids:
            report.findings.append(Finding(
                report.fixture_id, "a60-claim-not-found",
                f"A60 {row_label}: RelatedClaimID '{rel}' not in A59",
            ))

    # ---- A51 invariants ---------------------------------------------
    for i, row in enumerate(a51_rows):
        row_label = row.get("A51Ref") or f"row[{i}]"
        for required in ("IssueType", "Severity", "BlockingStatus"):
            if not (row.get(required) or "").strip():
                report.findings.append(Finding(
                    report.fixture_id, "a51-missing-field",
                    f"A51 {row_label}: missing '{required}'",
                ))

    # ---- Stage 2 shape (optional per fixture) ----------------------
    stage2_dir = fixture_dir / "expected_outputs" / "canonical" / "stage2"
    if stage2_dir.is_dir():
        stage2_required_files = {
            "context_state_frame.md": STAGE2_CONTEXT_STATE_REQUIRED_HEADERS,
            "system_context_seed.md": STAGE2_SYSTEM_CONTEXT_REQUIRED_HEADERS,
        }
        for filename, required_headers in stage2_required_files.items():
            fpath = stage2_dir / filename
            if not fpath.is_file():
                report.findings.append(Finding(
                    report.fixture_id, "stage2-missing-file",
                    f"Stage 2 expected output missing: {filename}",
                ))
                continue
            try:
                text = fpath.read_text(encoding="utf-8")
            except OSError as exc:
                report.findings.append(Finding(
                    report.fixture_id, "stage2-read-error",
                    f"Stage 2 {filename}: {exc}",
                ))
                continue
            for header in required_headers:
                if header not in text:
                    report.findings.append(Finding(
                        report.fixture_id, "stage2-missing-header",
                        f"Stage 2 {filename}: required header missing: {header!r}",
                    ))

        for filename, required_cols in (
            ("stakeholder_authority_map.md", STAGE2_STAKEHOLDER_COLUMNS),
            ("constraints_dependencies_route.md", STAGE2_CONSTRAINTS_COLUMNS),
        ):
            fpath = stage2_dir / filename
            if not fpath.is_file():
                report.findings.append(Finding(
                    report.fixture_id, "stage2-missing-file",
                    f"Stage 2 expected output missing: {filename}",
                ))
                continue
            try:
                text = fpath.read_text(encoding="utf-8")
            except OSError as exc:
                report.findings.append(Finding(
                    report.fixture_id, "stage2-read-error",
                    f"Stage 2 {filename}: {exc}",
                ))
                continue
            for col in required_cols:
                if col not in text:
                    report.findings.append(Finding(
                        report.fixture_id, "stage2-missing-column",
                        f"Stage 2 {filename}: required column missing: {col!r}",
                    ))

        summary_path = stage2_dir / "stage2_summary.json"
        if not summary_path.is_file():
            report.findings.append(Finding(
                report.fixture_id, "stage2-missing-file",
                "Stage 2 expected output missing: stage2_summary.json",
            ))
        else:
            try:
                summary_data = _read_json(summary_path)
            except json.JSONDecodeError as exc:
                report.findings.append(Finding(
                    report.fixture_id, "stage2-summary-parse",
                    f"stage2_summary.json: invalid JSON: {exc}",
                ))
                summary_data = None
            if isinstance(summary_data, dict):
                for field_name in STAGE2_SUMMARY_REQUIRED_FIELDS:
                    if field_name not in summary_data:
                        report.findings.append(Finding(
                            report.fixture_id, "stage2-summary-field",
                            f"stage2_summary.json: missing required field '{field_name}'",
                        ))
                if summary_data.get("stage_id") not in (None, "stage2"):
                    report.findings.append(Finding(
                        report.fixture_id, "stage2-summary-stage-id",
                        f"stage2_summary.json: stage_id must be 'stage2', got "
                        f"{summary_data.get('stage_id')!r}",
                    ))
                cm = summary_data.get("context_mode")
                if cm is not None and cm not in ("direct", "discovery_then_bsa"):
                    report.findings.append(Finding(
                        report.fixture_id, "stage2-summary-context-mode",
                        f"stage2_summary.json: context_mode must be 'direct' or "
                        f"'discovery_then_bsa', got {cm!r}",
                    ))
            elif summary_data is not None:
                report.findings.append(Finding(
                    report.fixture_id, "stage2-summary-shape",
                    "stage2_summary.json: top-level must be a JSON object",
                ))

    # ---- Markers ----------------------------------------------------
    markers_dir = files["markers_dir"]
    if not markers_dir.is_dir():
        report.findings.append(Finding(
            report.fixture_id, "missing-markers-dir",
            f"expected_markers/ directory not present",
        ))
    else:
        marker_files = sorted(markers_dir.glob("*.json"))
        if not marker_files:
            report.findings.append(Finding(
                report.fixture_id, "no-markers",
                "expected_markers/ contains no *.json files",
            ))
        for mp in marker_files:
            try:
                data = _read_json(mp)
            except json.JSONDecodeError as exc:
                report.findings.append(Finding(
                    report.fixture_id, "marker-parse",
                    f"marker {mp.name}: invalid JSON: {exc}",
                ))
                continue
            if not isinstance(data, dict):
                report.findings.append(Finding(
                    report.fixture_id, "marker-shape",
                    f"marker {mp.name}: top-level must be object",
                ))
                continue
            for required in ("marker_id", "stage", "verdict", "canon_policy_version"):
                if required not in data:
                    report.findings.append(Finding(
                        report.fixture_id, "marker-field",
                        f"marker {mp.name}: missing '{required}'",
                    ))

    # ---- fixture_metadata ------------------------------------------
    if isinstance(metadata, dict):
        # model_version_hash is required by US-S05-01 AC-5 even when the
        # authoring mode is 'synthetic_representative' (value is then
        # a literal placeholder string such as 'n/a (synthetic fixture)',
        # but the field itself must be present so live-run fixtures in
        # Sprint 4.5 cannot silently drop it).
        for required in (
            "fixture_id", "canon_policy_version", "plugin_version",
            "model_used", "model_version_hash", "captured_at",
        ):
            if required not in metadata:
                report.findings.append(Finding(
                    report.fixture_id, "metadata-field",
                    f"fixture_metadata.json: missing '{required}'",
                ))
        if metadata.get("fixture_id") and metadata["fixture_id"] != fixture_dir.name:
            report.findings.append(Finding(
                report.fixture_id, "metadata-id-mismatch",
                f"fixture_metadata.fixture_id '{metadata.get('fixture_id')}' != directory '{fixture_dir.name}'",
            ))
    else:
        report.findings.append(Finding(
            report.fixture_id, "metadata-shape",
            "fixture_metadata.json: top-level must be an object",
        ))

    # ---- audit_expectations --------------------------------------
    if isinstance(expectations, dict):
        if expectations.get("fixture_id") and expectations["fixture_id"] != fixture_dir.name:
            report.findings.append(Finding(
                report.fixture_id, "expectations-id-mismatch",
                f"audit_expectations.fixture_id mismatch",
            ))
    else:
        report.findings.append(Finding(
            report.fixture_id, "expectations-shape",
            "audit_expectations.json: top-level must be an object",
        ))

    return report


def _hash_dir(path: Path) -> dict[str, str]:
    """Return relative-path -> sha256 for every file under path (stable ordering)."""
    digests: dict[str, str] = {}
    for p in sorted(path.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(path).as_posix()
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        digests[rel] = h
    return digests


def compare_fixture(fixture_dir: Path) -> FixtureReport:
    """In Phase 0, compare-mode verifies in-run stability: hash the fixture,
    then re-read its on-disk state via validate_fixture (which must not
    mutate), then hash again and diff. Any diff surfaces as a finding."""
    report = FixtureReport(fixture_id=fixture_dir.name)
    if not fixture_dir.is_dir():
        report.findings.append(Finding(report.fixture_id, "missing-fixture", f"not a directory: {fixture_dir}"))
        return report

    before = _hash_dir(fixture_dir)
    validate_fixture(fixture_dir)  # discard result; we only care about side-effect absence
    after = _hash_dir(fixture_dir)

    for rel in sorted(set(before.keys()) | set(after.keys())):
        if before.get(rel) != after.get(rel):
            report.findings.append(Finding(
                report.fixture_id, "compare-drift",
                f"file changed during fixture read: {rel}",
            ))
    return report


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="BSA golden-fixture runner (US-S05-01).")
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=repo_root / "fixtures" / "golden",
        help="Root directory of golden fixtures.",
    )
    parser.add_argument("--fixture", type=str, default=None, help="Run only the named fixture (e.g. project_0001).")
    parser.add_argument("--all", action="store_true", help="Run every fixture under fixtures-dir (default behaviour).")
    parser.add_argument(
        "--mode",
        choices=["validate", "compare", "both"],
        default="validate",
        help="Selected run mode.",
    )
    args = parser.parse_args(argv)

    if not args.fixtures_dir.is_dir():
        print(f"ERROR: fixtures directory not found: {args.fixtures_dir}", file=sys.stderr)
        return 2

    if args.fixture:
        targets = [args.fixtures_dir / args.fixture]
        if not targets[0].is_dir():
            print(f"ERROR: fixture not found: {targets[0]}", file=sys.stderr)
            return 2
    else:
        targets = sorted([p for p in args.fixtures_dir.iterdir() if p.is_dir()])
        if not targets:
            print(f"ERROR: no fixtures under {args.fixtures_dir}", file=sys.stderr)
            return 2

    reports: list[FixtureReport] = []
    for fx in targets:
        if args.mode in ("validate", "both"):
            reports.append(validate_fixture(fx))
        if args.mode in ("compare", "both"):
            reports.append(compare_fixture(fx))

    total_findings = sum(len(r.findings) for r in reports)
    for r in reports:
        if r.passed:
            print(f"PASS {r.fixture_id}")
        else:
            for f in r.findings:
                print(f.format(), file=sys.stderr)

    print(
        f"Fixture runner: {len(targets)} fixture(s) × mode={args.mode} — "
        f"{total_findings} finding(s) total.",
        file=sys.stderr if total_findings else sys.stdout,
    )

    return 0 if total_findings == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
