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


def validate_fixture(fixture_dir: Path) -> FixtureReport:
    report = FixtureReport(fixture_id=fixture_dir.name)

    if not fixture_dir.is_dir():
        report.findings.append(Finding(report.fixture_id, "missing-fixture", f"not a directory: {fixture_dir}"))
        return report

    files = _locate_fixture_files(fixture_dir)
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
