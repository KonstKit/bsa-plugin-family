#!/usr/bin/env python3
"""A51 reconciliation auditor (F6, Sprint 5).

Detects the class of governance drift first observed in the Pilot-1
engagement: a marker payload (most often discovery.go.json) or a
handoff packet declares an A51 row to be remediated / resolved /
closed, while the canonical A51_issue_route_register.csv still holds
that same row as ``ResolutionStatus = open``.

Concretely, the Pilot-1 automated_results carried this preconditions
list inside discovery.go.json:

    "Reclassify register-hygiene: A51-MISS-010/011 →
     resolved_by_remediation (already done via PDF extraction;
     canonical rewrite pending)."

…while the canonical A51 register still listed A51-MISS-010 and
A51-MISS-011 with ResolutionStatus=open. Downstream consumers reading
the canonical register would treat those issues as live blockers; a
reader of discovery.go.json would treat them as resolved. Two sources
of truth disagreeing about the same lifecycle state.

This auditor flags every such disagreement as ``A51_RECONCILE_GAP``.

Inputs:
    - analysis/canonical/core_controls/A51_issue_route_register.csv
      (canonical register; the resolution-of-record).
    - analysis/runtime/ready/*.json + analysis/discovery/runtime/ready/*.json
      (marker payloads — scanned for A51Ref tokens in any string field).
    - analysis/handoff/H4_open_items_packet.md (handoff free text;
      same scan).

Output:
    Findings on stderr, one per gap. Exit 0 if no gaps, 1 if gaps,
    2 on invocation error.

CLI:
    scripts/validate_a51_reconciliation.py <workspace_root>

Stdlib-only at module level. ``governance.schemas.loader`` is imported
for the canonical A51 row reader.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from governance.schemas import loader as _schema_loader  # noqa: E402

# A51Ref token shape — accepts both A51-NNN and A51-XXX-NNN. Same
# pattern fragment as in the A51 schema, used here for free-text
# scanning rather than structured-field validation. The trailing
# `(?:/[0-9]{3,4})*` captures the operator-shorthand "A51-MISS-010/011"
# form for two-or-more sibling refs in one token.
_A51_REF_RE = re.compile(
    r"\bA51-(?:[A-Z]{2,5}-)?[0-9]{3,4}(?:/[0-9]{3,4})*\b"
)
# Helper to split the prefix off a matched ref so shorthand siblings
# can inherit it (parses 'A51-MISS-010' → 'A51-MISS-').
_A51_PREFIX_SPLIT_RE = re.compile(r"^(A51-(?:[A-Z]{2,5}-)?)[0-9]{3,4}$")


def _expand_a51_match(match_text: str) -> list[str]:
    """Expand 'A51-MISS-010/011/012' into ['A51-MISS-010', 'A51-MISS-011',
    'A51-MISS-012']. A bare 'A51-001' returns ['A51-001'].
    """
    parts = match_text.split("/")
    refs = [parts[0]]
    if len(parts) > 1:
        prefix_match = _A51_PREFIX_SPLIT_RE.match(parts[0])
        if prefix_match:
            prefix = prefix_match.group(1)
            for num in parts[1:]:
                refs.append(prefix + num)
    return refs

# Words near an A51Ref that signal the source-of-truth claim is
# "resolved/remediated/closed/done". Word-boundary matched, case
# insensitive. Tuned for the kind of free-text precondition lists that
# discovery.go.json carries.
_RESOLVED_INTENT_WORDS: tuple[str, ...] = (
    "resolved",
    "resolved_by_remediation",
    "remediated",
    "closed",
    "fixed",
    "completed",
    "done",
    "obsolete",
    "superseded",
)
_RESOLVED_INTENT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _RESOLVED_INTENT_WORDS) + r")\b",
    re.IGNORECASE,
)

# How close the resolution-intent word must be to the A51Ref to count
# as referring to it. 200 chars covers a single sentence or list item;
# wider would over-match across unrelated bullets.
_PROXIMITY_WINDOW = 200


@dataclass
class Finding:
    code: str
    a51_ref: str
    canonical_status: str
    declared_resolved_in: list[str]

    def format(self) -> str:
        sources = ", ".join(self.declared_resolved_in)
        return (
            f"[{self.code}] {self.a51_ref}: canonical ResolutionStatus="
            f"{self.canonical_status!r} but declared resolved/remediated in: {sources}"
        )


@dataclass
class Report:
    findings: list[Finding]

    @property
    def ok(self) -> bool:
        return not self.findings


def _load_canonical_resolution_status(workspace: Path) -> dict[str, str]:
    """Read A51 register, return {A51Ref: ResolutionStatus}."""
    a51_path = (
        workspace / "analysis" / "canonical" / "core_controls" / "A51_issue_route_register.csv"
    )
    if not a51_path.is_file():
        return {}
    return {
        row["A51Ref"]: row.get("ResolutionStatus", "")
        for row in _schema_loader.iter_a51_rows(a51_path)
    }


def _scan_text_for_resolved_a51_refs(text: str) -> set[str]:
    """Find A51Refs that appear within _PROXIMITY_WINDOW chars of a
    resolution-intent word. Returns the set of A51Refs claimed-resolved
    in this text.
    """
    refs: set[str] = set()
    intent_spans = [m.span() for m in _RESOLVED_INTENT_RE.finditer(text)]
    if not intent_spans:
        return refs
    for ref_match in _A51_REF_RE.finditer(text):
        ref_start, ref_end = ref_match.span()
        for intent_start, intent_end in intent_spans:
            # Distance is min over both directions.
            distance = max(0, max(ref_start, intent_start) - min(ref_end, intent_end))
            if distance <= _PROXIMITY_WINDOW:
                # Expand A51-MISS-010/011 shorthand into both refs.
                refs.update(_expand_a51_match(ref_match.group(0)))
                break
    return refs


def _scan_marker_files(workspace: Path) -> dict[str, list[str]]:
    """Scan marker JSON files for declared-resolved A51Refs.

    Returns {A51Ref: [source_file_relpath, ...]}.
    """
    declared: dict[str, list[str]] = {}
    marker_dirs = [
        workspace / "analysis" / "runtime" / "ready",
        workspace / "analysis" / "discovery" / "runtime" / "ready",
    ]
    for marker_dir in marker_dirs:
        if not marker_dir.is_dir():
            continue
        for marker_path in sorted(marker_dir.glob("*.json")):
            try:
                payload = json.loads(marker_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            # Flatten the JSON to a single text blob so the proximity
            # scan can see resolution-intent words next to A51Refs even
            # when they live in nested arrays / objects.
            blob = json.dumps(payload, ensure_ascii=False)
            for ref in _scan_text_for_resolved_a51_refs(blob):
                declared.setdefault(ref, []).append(
                    marker_path.relative_to(workspace).as_posix()
                )
    return declared


def _scan_handoff_packets(workspace: Path) -> dict[str, list[str]]:
    """Scan H1-H4 handoff packets for declared-resolved A51Refs."""
    declared: dict[str, list[str]] = {}
    handoff_dir = workspace / "analysis" / "handoff"
    if not handoff_dir.is_dir():
        return declared
    for md_path in sorted(handoff_dir.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for ref in _scan_text_for_resolved_a51_refs(text):
            declared.setdefault(ref, []).append(
                md_path.relative_to(workspace).as_posix()
            )
    return declared


def audit_workspace(workspace: Path) -> Report:
    """Run reconciliation audit. Returns a Report with any findings."""
    canonical = _load_canonical_resolution_status(workspace)
    declared_in_markers = _scan_marker_files(workspace)
    declared_in_handoff = _scan_handoff_packets(workspace)
    # Merge declared-resolved sources per A51Ref.
    declared: dict[str, list[str]] = {}
    for source_map in (declared_in_markers, declared_in_handoff):
        for ref, locations in source_map.items():
            declared.setdefault(ref, []).extend(locations)
    findings: list[Finding] = []
    for ref, locations in sorted(declared.items()):
        canonical_status = canonical.get(ref)
        if canonical_status is None:
            # A51Ref appears as resolved in markers/handoff but doesn't
            # exist in the canonical register at all → also a gap, but
            # of a different shape (ghost reference).
            findings.append(
                Finding(
                    code="A51_RECONCILE_GHOST",
                    a51_ref=ref,
                    canonical_status="<not in register>",
                    declared_resolved_in=sorted(set(locations)),
                )
            )
            continue
        if canonical_status == "open":
            findings.append(
                Finding(
                    code="A51_RECONCILE_GAP",
                    a51_ref=ref,
                    canonical_status=canonical_status,
                    declared_resolved_in=sorted(set(locations)),
                )
            )
    return Report(findings=findings)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="A51 reconciliation auditor (Sprint 5 F6)."
    )
    parser.add_argument(
        "workspace",
        type=Path,
        help="Workspace root (the directory containing analysis/).",
    )
    args = parser.parse_args(argv)

    if not (args.workspace / "analysis").is_dir():
        print(
            f"[A51-reconciliation] error: no analysis/ subdirectory at {args.workspace}",
            file=sys.stderr,
        )
        return 2

    report = audit_workspace(args.workspace)
    for f in report.findings:
        print(f.format(), file=sys.stderr)
    if report.ok:
        print(f"OK: A51 reconciliation clean ({args.workspace})")
        return 0
    print(
        f"\nFAIL: {len(report.findings)} A51 reconciliation finding(s) — "
        f"canonical A51_issue_route_register.csv ResolutionStatus disagrees with "
        f"marker / handoff declarations. Either update the canonical register "
        f"(set ResolutionStatus to resolved / resolved_by_remediation / "
        f"superseded / wontfix as appropriate) or remove the resolved/closed "
        f"language from the upstream payload.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
