#!/usr/bin/env python3
"""Freshness audit for A50 source register (v1.2.16).

Reads `analysis/canonical/core_controls/A50_source_register.csv`,
inspects each row's optional `EffectiveDate` field, and reports which
sources are stale relative to the configured threshold. Optionally
joins A59 to surface which claims depend on stale sources.

Contract: skills/bsa-orchestrator/references/freshness-audit-contract.md.
Tunable: config/tunables.yaml::freshness_threshold_days (default 180).

Pattern mirrors scripts/phase_7_telemetry_collector.py (v1.2.4):
- Stdlib-only.
- Defensive CSV reads — missing/malformed inputs yield `n/a`, never
  fail the build.
- Atomic JSON write via tempfile + os.replace.
- Operator-invoked. NOT canonical state. NOT in POLICY_GLOBS.

The audit is non-blocking by default in v1.2.16 (verdicts: `pass` |
`warn` | `n/a`). Mandatory enforcement is intentionally deferred — see
the contract's "Gate behavior" section.

Stdlib-only.

CLI:
  scripts/freshness_audit.py --workspace <path>
  scripts/freshness_audit.py --workspace <path> --threshold-days 90
  scripts/freshness_audit.py --workspace <path> --print-only
  scripts/freshness_audit.py --workspace <path> --today 2026-04-25

Exit codes:
  0 — audit completed (any verdict, including warn).
  2 — invocation error (workspace not initialized, malformed --today,
      malformed --threshold-days, etc.).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

SCHEMA_VERSION = "1.0"
DEFAULT_THRESHOLD_DAYS = 180
DEFAULT_OUTPUT_DIR = "analysis/canonical/stage1"

A50_REL = "analysis/canonical/core_controls/A50_source_register.csv"
A59_REL = "analysis/canonical/core_controls/A59_claim_register.csv"

# A59 SourceID may carry semicolon- or slash-joined tokens (per v1.2.14
# multi-FK contract). Splitting on either preserves the dependent-claim
# fan-out for stale-source impact reporting.
_SOURCEID_SPLIT_CHARS = ";/"


# ---- CSV helpers -----------------------------------------------------


def _read_csv_rows(path: Path) -> list[dict]:
    """Defensive CSV read — returns [] if missing/malformed."""
    if not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except (OSError, csv.Error):
        return []


def _split_source_ids(raw: str) -> list[str]:
    """Split a multi-valued SourceID cell into individual tokens."""
    if not raw:
        return []
    out: list[str] = []
    token = ""
    for ch in raw:
        if ch in _SOURCEID_SPLIT_CHARS:
            t = token.strip()
            if t:
                out.append(t)
            token = ""
        else:
            token += ch
    t = token.strip()
    if t:
        out.append(t)
    return out


# ---- EffectiveDate parsing ------------------------------------------


def _parse_effective_date(raw: str | None) -> tuple[date | None, str]:
    """Return (parsed_date, status).

    status ∈ {"ok", "unknown", "missing", "malformed"}.
    - "ok": parsed_date is a real date.
    - "unknown": literal sentinel (operator says "cannot assess").
    - "missing": empty / whitespace / None — pre-v1.2.16 row.
    - "malformed": present but not YYYY-MM-DD.
    """
    if raw is None:
        return None, "missing"
    s = raw.strip()
    if not s:
        return None, "missing"
    if s.lower() == "unknown":
        return None, "unknown"
    try:
        # strptime accepts e.g. "2024-2-3" via leading-zero leniency on
        # some platforms. Lock to strict YYYY-MM-DD by length-checking.
        if len(s) != 10 or s[4] != "-" or s[7] != "-":
            return None, "malformed"
        parsed = datetime.strptime(s, "%Y-%m-%d").date()
        return parsed, "ok"
    except ValueError:
        return None, "malformed"


# ---- Dependents map (A59 join) --------------------------------------


def _compute_dependents_map(workspace: Path) -> dict[str, list[str]]:
    """Return SourceID → list of ClaimID for all A59 claims that bind
    that SourceID. Supports multi-valued SourceID cells (`S-001;S-002`).
    Returns {} when A59 is absent or empty."""
    rows = _read_csv_rows(workspace / A59_REL)
    out: dict[str, list[str]] = {}
    for r in rows:
        claim_id = (r.get("ClaimID") or "").strip()
        if not claim_id:
            continue
        for src_id in _split_source_ids(r.get("SourceID") or ""):
            out.setdefault(src_id, []).append(claim_id)
    return out


# ---- Audit -----------------------------------------------------------


def _audit_row(
    row: dict,
    today_utc: date,
    threshold_days: int,
    dependents_map: dict[str, list[str]],
) -> dict:
    """Audit one A50 row → row-level finding dict."""
    source_id = (row.get("SourceID") or "").strip()
    raw_effective = row.get("EffectiveDate")
    parsed, parse_status = _parse_effective_date(raw_effective)

    if parse_status == "ok":
        assert parsed is not None  # narrow for type-checkers
        age_days = (today_utc - parsed).days
        if age_days < 0:
            # Future-dated EffectiveDate — treat as fresh but flag.
            status = "fresh"
            note = "future_dated"
        elif age_days <= threshold_days:
            status = "fresh"
            note = ""
        else:
            status = "stale"
            note = ""
    else:
        # missing / unknown / malformed → n/a
        status = "n/a"
        note = parse_status
        age_days = None

    dependent_claims = dependents_map.get(source_id, [])

    return {
        "source_id": source_id,
        "effective_date": (
            parsed.isoformat() if parsed is not None else None
        ),
        "raw_effective_date": raw_effective,
        "parse_status": parse_status,
        "age_days": age_days,
        "status": status,
        "note": note,
        "dependent_claim_count": len(dependent_claims),
        "dependent_claim_ids": dependent_claims,
    }


def _suggest_a51_for_stale(finding: dict) -> dict | None:
    """Build a partial draft A51 row for a stale source with dependents.

    Returns None when there are no dependents (no need to route).

    The returned dict is a **partial** row — `A51Ref` is left as the
    placeholder string `"<assign-on-create>"` because the audit cannot
    pick a stable A51 identifier without scanning the existing register
    (and even then, ID assignment is single-writer to the orchestrator
    per INV-02). The operator MUST replace the placeholder with the
    next free A51-NNN identifier before copying the row into A51.
    Validating the row against `governance/schemas/a51.schema.json` will
    fail until the placeholder is resolved — by design, this prevents
    accidental verbatim copy."""
    if finding["dependent_claim_count"] == 0:
        return None
    return {
        "A51Ref": "<assign-on-create>",
        "IssueType": "boundary_risk",
        "Severity": "medium",
        "BlockingStatus": "soft",
        "RaisedByStage": "stage1",
        "RelatedSourceID": finding["source_id"],
        "RelatedClaimID": ";".join(finding["dependent_claim_ids"]),
        "NextAction": (
            f"Source {finding['source_id']} EffectiveDate "
            f"{finding['effective_date']} exceeds freshness threshold "
            f"(age {finding['age_days']} days). Review whether "
            f"{finding['dependent_claim_count']} dependent claim(s) "
            f"still hold."
        ),
        "ResolutionStatus": "open",
    }


def build_snapshot(
    workspace: Path,
    threshold_days: int,
    today_utc: date | None = None,
) -> dict:
    """Compute full freshness-audit snapshot dict (schema-conformant)."""
    if today_utc is None:
        today_utc = datetime.now(tz=timezone.utc).date()

    rows = _read_csv_rows(workspace / A50_REL)
    dependents_map = _compute_dependents_map(workspace)

    findings = [
        _audit_row(r, today_utc, threshold_days, dependents_map)
        for r in rows
    ]

    rows_total = len(findings)
    rows_with_effective_date = sum(
        1 for f in findings if f["parse_status"] == "ok"
    )
    rows_fresh = sum(1 for f in findings if f["status"] == "fresh")
    rows_stale = sum(1 for f in findings if f["status"] == "stale")
    rows_na = sum(1 for f in findings if f["status"] == "n/a")
    stale_rows_with_dependents = sum(
        1
        for f in findings
        if f["status"] == "stale" and f["dependent_claim_count"] > 0
    )

    # Verdict policy:
    # - n/a: no A50 OR no parseable EffectiveDate at all.
    # - warn: at least one stale + at least one dependent claim.
    # - pass: any other case (zero stale, OR stale-without-dependents).
    if rows_total == 0 or rows_with_effective_date == 0:
        verdict = "n/a"
    elif stale_rows_with_dependents > 0:
        verdict = "warn"
    else:
        verdict = "pass"

    stale_rows_payload = []
    for f in findings:
        if f["status"] != "stale":
            continue
        suggested = _suggest_a51_for_stale(f)
        stale_rows_payload.append(
            {
                "source_id": f["source_id"],
                "effective_date": f["effective_date"],
                "age_days": f["age_days"],
                "dependent_claim_count": f["dependent_claim_count"],
                "dependent_claim_ids": f["dependent_claim_ids"],
                "suggested_a51": suggested,
            }
        )

    captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at,
        "verdict": verdict,
        "threshold_days": threshold_days,
        "today_utc": today_utc.isoformat(),
        "summary": {
            "rows_total": rows_total,
            "rows_with_effective_date": rows_with_effective_date,
            "rows_fresh": rows_fresh,
            "rows_stale": rows_stale,
            "rows_na": rows_na,
            "stale_rows_with_dependent_claims": stale_rows_with_dependents,
        },
        "stale_rows": stale_rows_payload,
    }


# ---- Markdown rendering ---------------------------------------------


def render_markdown(snapshot: dict) -> str:
    """Human-readable freshness report."""
    s = snapshot["summary"]
    lines = [
        "# Freshness Audit",
        "",
        f"- captured_at: `{snapshot['captured_at']}`",
        f"- today_utc: `{snapshot['today_utc']}`",
        f"- threshold_days: `{snapshot['threshold_days']}`",
        f"- verdict: **{snapshot['verdict']}**",
        "",
        "## Summary",
        "",
        f"- rows_total: {s['rows_total']}",
        f"- rows_with_effective_date: {s['rows_with_effective_date']}",
        f"- rows_fresh: {s['rows_fresh']}",
        f"- rows_stale: {s['rows_stale']}",
        f"- rows_na: {s['rows_na']}",
        f"- stale_rows_with_dependent_claims: "
        f"{s['stale_rows_with_dependent_claims']}",
        "",
    ]

    if not snapshot["stale_rows"]:
        lines.append("No stale rows.")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Stale rows")
    lines.append("")
    lines.append(
        "| SourceID | EffectiveDate | Age (days) | Dependent claims |"
    )
    lines.append(
        "| --- | --- | --- | --- |"
    )
    for sr in snapshot["stale_rows"]:
        lines.append(
            f"| `{sr['source_id']}` | {sr['effective_date']} | "
            f"{sr['age_days']} | {sr['dependent_claim_count']} |"
        )
    lines.append("")

    suggestions = [
        sr for sr in snapshot["stale_rows"] if sr["suggested_a51"]
    ]
    if suggestions:
        lines.append("## Suggested A51 routes")
        lines.append("")
        lines.append(
            "These are partial draft routes — the audit does NOT write to "
            "A51. Operator decides whether to raise them. Before promoting, "
            "**replace `<assign-on-create>` in the `A51Ref` field** with the "
            "next free `A51-NNN` identifier (the placeholder intentionally "
            "fails A51 schema pattern validation by design — see contract "
            "section 'Marker schema')."
        )
        lines.append("")
        for sr in suggestions:
            a51 = sr["suggested_a51"]
            lines.append(f"### Source `{sr['source_id']}`")
            lines.append("")
            for k in (
                "A51Ref",
                "IssueType",
                "Severity",
                "BlockingStatus",
                "RaisedByStage",
                "RelatedSourceID",
                "RelatedClaimID",
                "NextAction",
                "ResolutionStatus",
            ):
                lines.append(f"- {k}: `{a51[k]}`")
            lines.append("")
    return "\n".join(lines)


# ---- Atomic write ----------------------------------------------------


def write_marker(target_path: Path, snapshot: dict) -> None:
    """Atomic JSON write (mirrors phase_7_telemetry_collector pattern)."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=".freshness_audit_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2)
        os.replace(tmp, target_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_report_md(target_path: Path, body: str) -> None:
    """Atomic Markdown write."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=".freshness_audit_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, target_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---- CLI -------------------------------------------------------------


def _parse_today_arg(s: str) -> date:
    parsed, status = _parse_effective_date(s)
    if status != "ok" or parsed is None:
        raise argparse.ArgumentTypeError(
            f"--today expects YYYY-MM-DD, got {s!r} ({status})"
        )
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Freshness audit over A50_source_register.csv "
            "(v1.2.16, opt-in operator runner)."
        ),
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="BSA workspace root (defaults to cwd).",
    )
    parser.add_argument(
        "--threshold-days",
        type=int,
        default=DEFAULT_THRESHOLD_DAYS,
        help=(
            f"Override the freshness threshold in days "
            f"(default {DEFAULT_THRESHOLD_DAYS}). Canonical value lives "
            f"in config/tunables.yaml::freshness_threshold_days."
        ),
    )
    parser.add_argument(
        "--today",
        type=_parse_today_arg,
        default=None,
        help=(
            "Override today's UTC date (YYYY-MM-DD). Test-only knob; "
            "production runs should let the audit pick "
            "datetime.now(tz=UTC).date()."
        ),
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help=(
            "Override JSON marker path "
            "(default <workspace>/"
            f"{DEFAULT_OUTPUT_DIR}/freshness_audit.json)."
        ),
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help=(
            "Override Markdown report path "
            "(default <workspace>/"
            f"{DEFAULT_OUTPUT_DIR}/freshness_audit.md)."
        ),
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print snapshot to stdout instead of writing.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-summary log line.",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.threshold_days < 1:
        print(
            f"freshness_audit: --threshold-days must be >= 1, "
            f"got {args.threshold_days}",
            file=sys.stderr,
        )
        return 2

    workspace = args.workspace.resolve()
    if not (workspace / "analysis").is_dir():
        print(
            f"freshness_audit: workspace {workspace} is not initialized "
            f"(no analysis/ directory). Run /bsa-start first.",
            file=sys.stderr,
        )
        return 2

    snapshot = build_snapshot(
        workspace,
        threshold_days=args.threshold_days,
        today_utc=args.today,
    )

    if args.print_only:
        print(json.dumps(snapshot, indent=2))
        return 0

    output_path = args.output_path or (
        workspace / DEFAULT_OUTPUT_DIR / "freshness_audit.json"
    )
    report_path = args.report_path or (
        workspace / DEFAULT_OUTPUT_DIR / "freshness_audit.md"
    )

    write_marker(output_path, snapshot)
    write_report_md(report_path, render_markdown(snapshot))

    if not args.quiet:
        s = snapshot["summary"]
        print(
            f"freshness_audit: wrote {output_path}\n"
            f"  verdict: {snapshot['verdict']}\n"
            f"  threshold_days: {snapshot['threshold_days']}\n"
            f"  rows: {s['rows_total']} total / "
            f"{s['rows_with_effective_date']} with EffectiveDate / "
            f"{s['rows_fresh']} fresh / {s['rows_stale']} stale / "
            f"{s['rows_na']} n/a"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
