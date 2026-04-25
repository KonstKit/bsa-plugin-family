#!/usr/bin/env python3
"""Triangulation audit for A59 claim register (v1.2.17).

Reads `analysis/canonical/core_controls/A59_claim_register.csv`, joins
A50 (for SourceType + Priority) and A51 (for Severity via
RelatedClaimID), and reports which "important" claims have insufficient
SourceType diversity.

Triggering set (three-branch OR): a claim is in the audit set if ANY of:
  1. Criticality == "level-1" (direct from A59).
  2. ANY linked A51 has Severity in {high, critical} (configurable).
  3. ANY bound A50 source has Priority == "high" (configurable).

`analyst_judgment` claims are always skipped (no source binding by design).

A claim "passes" triangulation if its bound A50 sources span
>= triangulation_min_distinct_sourcetypes distinct SourceType values.
"Independence" is measured by SourceType, not SourceID — three documents
count as one source-type channel.

Contract: skills/bsa-orchestrator/references/triangulation-audit-contract.md.
Tunable: config/tunables.yaml::triangulation_min_distinct_sourcetypes
(numeric only). Severity / Priority branch thresholds are built-in
script defaults (enums — phase_7_lint requires numeric ranges) and
are overridable per-run via `--severity-threshold` / `--priority-
threshold` CLI flags; persistent change requires a code edit + new
release.

Pattern mirrors scripts/freshness_audit.py (v1.2.16):
- Stdlib-only.
- Defensive CSV reads — missing/malformed inputs yield `n/a`.
- Atomic JSON + Markdown writes via tempfile + os.replace.
- Operator-invoked. NOT canonical state. NOT in POLICY_GLOBS.

The audit is non-blocking by default in v1.2.17 (verdicts: `pass` |
`warn` | `n/a`). Mandatory enforcement deferred — see contract's
"Verdict policy" section.

Stdlib-only.

CLI:
  scripts/triangulation_audit.py --workspace <path>
  scripts/triangulation_audit.py --workspace <path> --min-sourcetypes 3
  scripts/triangulation_audit.py --workspace <path> --severity-threshold critical
  scripts/triangulation_audit.py --workspace <path> --priority-threshold medium
  scripts/triangulation_audit.py --workspace <path> --print-only

Exit codes:
  0 — audit completed (any verdict, including warn).
  2 — invocation error (workspace not initialized, malformed flag).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SCHEMA_VERSION = "1.0"
DEFAULT_OUTPUT_DIR = "analysis/canonical/stage7"

A50_REL = "analysis/canonical/core_controls/A50_source_register.csv"
A51_REL = "analysis/canonical/core_controls/A51_issue_route_register.csv"
A59_REL = "analysis/canonical/core_controls/A59_claim_register.csv"

# Defaults.
# - DEFAULT_MIN_DISTINCT_SOURCETYPES mirrors
#   config/tunables.yaml::triangulation_min_distinct_sourcetypes
#   (numeric, lockstep with the contract's "Tunable" table).
# - DEFAULT_SEVERITY_THRESHOLD + DEFAULT_PRIORITY_THRESHOLD are
#   built-in (NOT in tunables.yaml; phase_7_lint requires numeric
#   ranges and these are enums). Overridable per-run via CLI flags
#   `--severity-threshold` / `--priority-threshold`. Persistent
#   change requires a code edit + new release.
DEFAULT_MIN_DISTINCT_SOURCETYPES = 2
DEFAULT_SEVERITY_THRESHOLD = "high"
DEFAULT_PRIORITY_THRESHOLD = "high"

# Severity ordering — A51 enum is closed at low/medium/high/critical
# (per a51.schema.json). Indexes used for >= comparison vs threshold.
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
# Priority ordering — A50 enum is closed at low/medium/high.
_PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2}

# Multi-value FK split — `;` and `/` per v1.2.14 multi-FK contract.
_FK_SPLIT_CHARS = ";/"


# ---- CSV helpers (mirror freshness_audit pattern) -------------------


def _read_csv_rows(path: Path) -> list[dict]:
    """Defensive CSV read — returns [] on missing/malformed."""
    if not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except (OSError, csv.Error):
        return []


def _split_fk_tokens(raw: str) -> list[str]:
    """Split a multi-valued FK cell into trimmed tokens. Handles `;`
    and `/` separators (the v1.2.14 multi-FK contract); empty + all-
    whitespace tokens dropped."""
    if not raw:
        return []
    out: list[str] = []
    token = ""
    for ch in raw:
        if ch in _FK_SPLIT_CHARS:
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


# ---- Index builders -------------------------------------------------


def _build_a50_index(workspace: Path) -> dict[str, dict]:
    """SourceID -> {SourceType, Priority}. Empty dict when A50 absent."""
    rows = _read_csv_rows(workspace / A50_REL)
    out: dict[str, dict] = {}
    for r in rows:
        sid = (r.get("SourceID") or "").strip()
        if not sid:
            continue
        out[sid] = {
            "SourceType": (r.get("SourceType") or "").strip(),
            "Priority": (r.get("Priority") or "").strip(),
        }
    return out


def _build_a51_severity_by_claim(workspace: Path) -> dict[str, list[str]]:
    """ClaimID -> list of A51 Severity values for issues that link to
    that claim via RelatedClaimID. Empty dict when A51 absent. Multi-
    value RelatedClaimID is fanned out per token.

    Severity values are NOT lowercased — A51 schema's enum is closed
    lowercase (`low`/`medium`/`high`/`critical`), and the audit's
    handler reach should match schema reach exactly (lesson from
    v1.2.16 R4/R5). A row with `Severity=High` is schema-invalid and
    should NOT be silently normalized here; if such a row slips past
    promote-gate, this audit treats it as a Severity-not-recognized
    skip rather than masking the upstream bug.
    """
    rows = _read_csv_rows(workspace / A51_REL)
    out: dict[str, list[str]] = {}
    for r in rows:
        severity = (r.get("Severity") or "").strip()
        if severity not in _SEVERITY_RANK:
            continue
        for cid in _split_fk_tokens(r.get("RelatedClaimID") or ""):
            out.setdefault(cid, []).append(severity)
    return out


# ---- Per-claim audit ------------------------------------------------


def _classify_claim(
    row: dict,
    a50_index: dict[str, dict],
    a51_severity_by_claim: dict[str, list[str]],
    severity_threshold_rank: int,
    priority_threshold_rank: int,
) -> dict:
    """Compute the per-claim finding (independent of pass/warn verdict).

    Returns a dict with: claim_id, claim_type, criticality, source_ids,
    distinct_sourcetypes, distinct_sourcetypes_count, trigger_reasons,
    in_triangulation_set, skipped_reason."""
    claim_id = (row.get("ClaimID") or "").strip()
    claim_type = (row.get("ClaimType") or "").strip()
    criticality = (row.get("Criticality") or "").strip()

    source_ids = _split_fk_tokens(row.get("SourceID") or "")

    # Resolve SourceTypes via A50 join (silently skip dangling tokens —
    # F5 hook's x-bsa-foreign-key-refs (v1.2.13) should have rejected
    # them; if they slip through, we don't double-count).
    distinct_sourcetypes_set: set[str] = set()
    for sid in source_ids:
        a50_row = a50_index.get(sid)
        if a50_row is None:
            continue
        st = a50_row["SourceType"]
        if st:
            distinct_sourcetypes_set.add(st)
    distinct_sourcetypes = sorted(distinct_sourcetypes_set)

    # analyst_judgment: always skip (no source binding by design per
    # INV-07 / x-bsa-claim-type-rules). Skip recorded for transparency.
    if claim_type == "analyst_judgment":
        return {
            "claim_id": claim_id,
            "claim_type": claim_type,
            "criticality": criticality,
            "source_ids": source_ids,
            "distinct_sourcetypes": distinct_sourcetypes,
            "distinct_sourcetypes_count": len(distinct_sourcetypes),
            "trigger_reasons": [],
            "in_triangulation_set": False,
            "skipped_reason": "analyst_judgment",
        }

    # Three-branch OR — collect ALL matched reasons (not just first).
    trigger_reasons: list[str] = []

    # Branch 1: Criticality == level-1.
    if criticality == "level-1":
        trigger_reasons.append("criticality_level_1")

    # Branch 2: ANY linked A51 with Severity >= threshold.
    severities = a51_severity_by_claim.get(claim_id, [])
    if any(
        _SEVERITY_RANK[s] >= severity_threshold_rank for s in severities
    ):
        trigger_reasons.append("a51_severity_meets_threshold")

    # Branch 3: ANY bound A50 source with Priority >= threshold.
    priorities = []
    for sid in source_ids:
        a50_row = a50_index.get(sid)
        if a50_row is None:
            continue
        p = a50_row["Priority"]
        if p in _PRIORITY_RANK:
            priorities.append(p)
    if any(
        _PRIORITY_RANK[p] >= priority_threshold_rank for p in priorities
    ):
        trigger_reasons.append("a50_priority_meets_threshold")

    return {
        "claim_id": claim_id,
        "claim_type": claim_type,
        "criticality": criticality,
        "source_ids": source_ids,
        "distinct_sourcetypes": distinct_sourcetypes,
        "distinct_sourcetypes_count": len(distinct_sourcetypes),
        "trigger_reasons": trigger_reasons,
        "in_triangulation_set": bool(trigger_reasons),
        "skipped_reason": None,
    }


def _suggest_a51_for_under_triangulation(
    finding: dict, min_required: int
) -> dict:
    """Build a partial draft A51 row for an under-triangulated claim.

    Mirrors freshness_audit's `<assign-on-create>` placeholder
    convention — operator MUST replace before promoting (placeholder
    intentionally fails A51 pattern by design; A51 ID assignment is
    single-writer to orchestrator per INV-02)."""
    reason_summary = " + ".join(finding["trigger_reasons"]) or "trigger"
    sourcetypes_str = ", ".join(finding["distinct_sourcetypes"]) or "(none)"
    next_action = (
        f"Claim {finding['claim_id']} triggered triangulation "
        f"({reason_summary}) but binds only "
        f"{finding['distinct_sourcetypes_count']} distinct SourceType(s) "
        f"[{sourcetypes_str}] — minimum required is {min_required}. "
        f"Consider corroborating from a different SourceType (e.g., "
        f"code, interview_transcript, screenshot, ticket)."
    )
    return {
        "A51Ref": "<assign-on-create>",
        "IssueType": "uncertainty",
        "Severity": "medium",
        "BlockingStatus": "soft",
        "RaisedByStage": "stage7",
        "RelatedClaimID": finding["claim_id"],
        "RelatedSourceID": ";".join(finding["source_ids"]),
        "NextAction": next_action,
        "ResolutionStatus": "open",
    }


# ---- Snapshot --------------------------------------------------------


def build_snapshot(
    workspace: Path,
    *,
    min_distinct_sourcetypes: int = DEFAULT_MIN_DISTINCT_SOURCETYPES,
    severity_threshold: str = DEFAULT_SEVERITY_THRESHOLD,
    priority_threshold: str = DEFAULT_PRIORITY_THRESHOLD,
) -> dict:
    """Compute full triangulation-audit snapshot dict (schema-conformant)."""
    severity_threshold_rank = _SEVERITY_RANK[severity_threshold]
    priority_threshold_rank = _PRIORITY_RANK[priority_threshold]

    a59_rows = _read_csv_rows(workspace / A59_REL)
    a50_index = _build_a50_index(workspace)
    a51_severity_by_claim = _build_a51_severity_by_claim(workspace)

    findings = [
        _classify_claim(
            r,
            a50_index,
            a51_severity_by_claim,
            severity_threshold_rank,
            priority_threshold_rank,
        )
        for r in a59_rows
    ]

    claims_total = len(findings)
    claims_skipped_aj = sum(
        1 for f in findings if f["skipped_reason"] == "analyst_judgment"
    )
    in_set = [f for f in findings if f["in_triangulation_set"]]
    claims_in_set = len(in_set)
    claims_passing = sum(
        1
        for f in in_set
        if f["distinct_sourcetypes_count"] >= min_distinct_sourcetypes
    )
    under = [
        f
        for f in in_set
        if f["distinct_sourcetypes_count"] < min_distinct_sourcetypes
    ]
    claims_under = len(under)

    # Verdict policy:
    # - n/a: A59 absent OR triangulation set empty.
    # - warn: at least one claim under triangulation.
    # - pass: triangulation set non-empty AND zero under.
    if claims_total == 0 or claims_in_set == 0:
        verdict = "n/a"
    elif claims_under > 0:
        verdict = "warn"
    else:
        verdict = "pass"

    under_payload = []
    for f in under:
        suggested = _suggest_a51_for_under_triangulation(
            f, min_distinct_sourcetypes
        )
        under_payload.append(
            {
                "claim_id": f["claim_id"],
                "criticality": f["criticality"],
                "trigger_reasons": f["trigger_reasons"],
                "source_ids": f["source_ids"],
                "distinct_sourcetypes": f["distinct_sourcetypes"],
                "distinct_sourcetypes_count": f["distinct_sourcetypes_count"],
                "min_required": min_distinct_sourcetypes,
                "suggested_a51": suggested,
            }
        )

    captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at,
        "verdict": verdict,
        "thresholds": {
            "min_distinct_sourcetypes": min_distinct_sourcetypes,
            "severity_threshold": severity_threshold,
            "priority_threshold": priority_threshold,
        },
        "summary": {
            "claims_total": claims_total,
            "claims_in_triangulation_set": claims_in_set,
            "claims_passing": claims_passing,
            "claims_under_triangulation": claims_under,
            "claims_skipped_analyst_judgment": claims_skipped_aj,
        },
        "under_triangulation": under_payload,
    }


# ---- Markdown rendering ---------------------------------------------


def render_markdown(snapshot: dict) -> str:
    """Human-readable triangulation report."""
    s = snapshot["summary"]
    t = snapshot["thresholds"]
    lines = [
        "# Triangulation Audit",
        "",
        f"- captured_at: `{snapshot['captured_at']}`",
        f"- verdict: **{snapshot['verdict']}**",
        "",
        "## Thresholds",
        "",
        f"- min_distinct_sourcetypes: `{t['min_distinct_sourcetypes']}`",
        f"- severity_threshold: `{t['severity_threshold']}`",
        f"- priority_threshold: `{t['priority_threshold']}`",
        "",
        "## Summary",
        "",
        f"- claims_total: {s['claims_total']}",
        f"- claims_in_triangulation_set: {s['claims_in_triangulation_set']}",
        f"- claims_passing: {s['claims_passing']}",
        f"- claims_under_triangulation: {s['claims_under_triangulation']}",
        f"- claims_skipped_analyst_judgment: "
        f"{s['claims_skipped_analyst_judgment']}",
        "",
    ]

    if not snapshot["under_triangulation"]:
        lines.append("No under-triangulated claims.")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Under-triangulated claims")
    lines.append("")
    lines.append(
        "| ClaimID | Criticality | Trigger | SourceTypes | Count / Required |"
    )
    lines.append("| --- | --- | --- | --- | --- |")
    for f in snapshot["under_triangulation"]:
        triggers = " + ".join(f["trigger_reasons"]) or "(none)"
        sts = ", ".join(f["distinct_sourcetypes"]) or "(none)"
        lines.append(
            f"| `{f['claim_id']}` | {f['criticality']} | {triggers} | "
            f"{sts} | {f['distinct_sourcetypes_count']} / {f['min_required']} |"
        )
    lines.append("")

    lines.append("## Suggested A51 routes")
    lines.append("")
    lines.append(
        "These are partial draft routes — the audit does NOT write to A51. "
        "Operator decides whether to raise them. Before promoting, "
        "**replace `<assign-on-create>` in the `A51Ref` field** with the "
        "next free `A51-NNN` identifier (the placeholder intentionally "
        "fails A51 schema pattern validation by design — single-writer "
        "to orchestrator per INV-02)."
    )
    lines.append("")
    for f in snapshot["under_triangulation"]:
        a51 = f["suggested_a51"]
        lines.append(f"### Claim `{f['claim_id']}`")
        lines.append("")
        for k in (
            "A51Ref",
            "IssueType",
            "Severity",
            "BlockingStatus",
            "RaisedByStage",
            "RelatedClaimID",
            "RelatedSourceID",
            "NextAction",
            "ResolutionStatus",
        ):
            lines.append(f"- {k}: `{a51[k]}`")
        lines.append("")
    return "\n".join(lines)


# ---- Atomic write ----------------------------------------------------


def _atomic_write(target_path: Path, body: str | dict) -> None:
    """Atomic JSON or text write (mirrors freshness_audit pattern)."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=".triangulation_audit_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            if isinstance(body, dict):
                json.dump(body, fh, indent=2)
            else:
                fh.write(body)
        os.replace(tmp, target_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---- CLI -------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Triangulation audit over A59 claim register "
            "(v1.2.17, opt-in operator runner)."
        ),
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="BSA workspace root (defaults to cwd).",
    )
    parser.add_argument(
        "--min-sourcetypes",
        type=int,
        default=DEFAULT_MIN_DISTINCT_SOURCETYPES,
        help=(
            f"Minimum distinct SourceTypes for a triggered claim to pass "
            f"(default {DEFAULT_MIN_DISTINCT_SOURCETYPES}). Canonical "
            f"value lives in config/tunables.yaml::"
            f"triangulation_min_distinct_sourcetypes."
        ),
    )
    parser.add_argument(
        "--severity-threshold",
        choices=["high", "critical"],
        default=DEFAULT_SEVERITY_THRESHOLD,
        help=(
            f"Lowest A51 Severity that triggers the Severity branch "
            f"(default {DEFAULT_SEVERITY_THRESHOLD!r}). Built-in script "
            f"default — NOT in config/tunables.yaml (Phase 7 lint "
            f"requires numeric ranges; this is an enum). Persistent "
            f"change requires a code edit + new release."
        ),
    )
    parser.add_argument(
        "--priority-threshold",
        choices=["medium", "high"],
        default=DEFAULT_PRIORITY_THRESHOLD,
        help=(
            f"Lowest A50 Priority that triggers the Priority branch "
            f"(default {DEFAULT_PRIORITY_THRESHOLD!r}). Built-in script "
            f"default — NOT in config/tunables.yaml (Phase 7 lint "
            f"requires numeric ranges; this is an enum). Persistent "
            f"change requires a code edit + new release."
        ),
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help=(
            f"Override JSON marker path (default <workspace>/"
            f"{DEFAULT_OUTPUT_DIR}/triangulation_audit.json)."
        ),
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help=(
            f"Override Markdown report path (default <workspace>/"
            f"{DEFAULT_OUTPUT_DIR}/triangulation_audit.md)."
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

    if args.min_sourcetypes < 2:
        print(
            f"triangulation_audit: --min-sourcetypes must be >= 2, "
            f"got {args.min_sourcetypes}",
            file=sys.stderr,
        )
        return 2

    workspace = args.workspace.resolve()
    if not (workspace / "analysis").is_dir():
        print(
            f"triangulation_audit: workspace {workspace} is not "
            f"initialized (no analysis/ directory). Run /bsa-start first.",
            file=sys.stderr,
        )
        return 2

    snapshot = build_snapshot(
        workspace,
        min_distinct_sourcetypes=args.min_sourcetypes,
        severity_threshold=args.severity_threshold,
        priority_threshold=args.priority_threshold,
    )

    if args.print_only:
        print(json.dumps(snapshot, indent=2))
        return 0

    output_path = args.output_path or (
        workspace / DEFAULT_OUTPUT_DIR / "triangulation_audit.json"
    )
    report_path = args.report_path or (
        workspace / DEFAULT_OUTPUT_DIR / "triangulation_audit.md"
    )

    _atomic_write(output_path, snapshot)
    _atomic_write(report_path, render_markdown(snapshot))

    if not args.quiet:
        s = snapshot["summary"]
        t = snapshot["thresholds"]
        print(
            f"triangulation_audit: wrote {output_path}\n"
            f"  verdict: {snapshot['verdict']}\n"
            f"  thresholds: min_sourcetypes={t['min_distinct_sourcetypes']} "
            f"severity>={t['severity_threshold']} "
            f"priority>={t['priority_threshold']}\n"
            f"  claims: {s['claims_total']} total / "
            f"{s['claims_in_triangulation_set']} in set / "
            f"{s['claims_passing']} passing / "
            f"{s['claims_under_triangulation']} under / "
            f"{s['claims_skipped_analyst_judgment']} analyst-judgment "
            f"(skipped)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
