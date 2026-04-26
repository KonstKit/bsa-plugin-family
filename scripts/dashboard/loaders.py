"""Workspace artifact discovery for the BSA dashboard (v1.3.3 — WIP).

Pure-discovery layer: walks `<workspace>/analysis/canonical/` +
`<workspace>/analysis/handoff/` + `<workspace>/analysis/views/` +
`<workspace>/analysis/telemetry/` and returns a structured inventory of
what exists. Does NOT load row contents — that's renderer-side, on
demand. Discovery is glob-based + filename-pattern routing so it stays
robust to path-convention drift across stages.

Stdlib-only.

Why not delegate fully to `governance/schemas/loader.py::iter_a*_rows`?
Two reasons:
  1. Loader iter_* functions raise on missing files / shape mismatches;
     the dashboard wants to gracefully show "this artifact not present
     yet" without crashing.
  2. The dashboard discovers artifacts across MANY paths (different
     stage subdirs); the loader iter_* functions take an explicit path
     and don't search.

The renderer layer DOES use the loader's iter_* helpers when actually
rendering each artifact's table — defensive read at use-time, not at
discovery-time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# A-table filename patterns. Maps the A-number to a regex that matches
# any filename in `analysis/canonical/**/` claiming to be that table.
# Filename-based routing avoids hardcoding stage paths.
A_TABLE_PATTERNS: dict[str, re.Pattern[str]] = {
    "a50": re.compile(r"^A50_source_register\.csv$"),
    "a51": re.compile(r"^A51_issue_route_register\.csv$"),
    "a58": re.compile(r"^A58_evidence_excerpts\.csv$"),
    "a59": re.compile(r"^A59_claim_register\.csv$"),
    "a60": re.compile(r"^A60_negative_evidence_register\.csv$"),
    "a61": re.compile(r"^A61_anchor_map(?:_candidate)?\.csv$"),
    "a62": re.compile(r"^A62_nfr_register\.csv$"),
    "a70": re.compile(r"^A70_story_register\.csv$"),
    "a71": re.compile(r"^A71_test_scenario_register\.csv$"),
    "a72": re.compile(r"^A72_traceability_matrix\.csv$"),
}

# Audit-report filename patterns (markdown reports). Mapped to a stable
# audit ID used by the renderer for verdict-badge color coding.
AUDIT_PATTERNS: dict[str, re.Pattern[str]] = {
    "freshness": re.compile(r"^freshness_audit_report\.md$"),
    "triangulation": re.compile(r"^triangulation_audit_report\.md$"),
    "anchor": re.compile(r"^anchor_audit_report\.md$"),
    "citation": re.compile(r"^(?:citation|overclaim)_(?:and_overclaim_)?audit_report\.md$"),
    "no_new_claims": re.compile(r"^(?:no_new_claims|handoff_no_new_claims)_report\.md$"),
    "consistency": re.compile(r"^consistency_audit_report\.md$"),
    "prompt_injection": re.compile(r"^prompt_injection_audit_report\.md$"),
    "contradiction_scan": re.compile(r"^contradiction_scan\.md$"),
}

# Handoff packet filename patterns.
HANDOFF_PATTERNS: dict[str, re.Pattern[str]] = {
    "h1": re.compile(r"^H1_(?:exec_brief|.*)\.md$"),
    "h2": re.compile(r"^H2_(?:delivery_packet|.*)\.md$"),
    "h3": re.compile(r"^H3_(?:validation_packet|.*)\.md$"),
    "h4": re.compile(r"^H4_(?:open_items_packet|.*)\.md$"),
}

# Contract export discovery (v1.3.x exporter outputs).
CONTRACT_FORMATS: dict[str, dict[str, re.Pattern[str]]] = {
    "openapi": {
        "spec": re.compile(r"^api\.ya?ml$"),
        "manifest": re.compile(r"^anchor_manifest\.json$"),
    },
    "asyncapi": {
        "spec": re.compile(r"^asyncapi\.ya?ml$"),
        "manifest": re.compile(r"^anchor_manifest\.json$"),
    },
    "proto": {
        "spec": re.compile(r"^services\.proto$"),
        "manifest": re.compile(r"^anchor_manifest\.json$"),
    },
}

# Sidecar discovery (under analysis/views/).
SIDECAR_FORMATS: dict[str, dict[str, re.Pattern[str]]] = {
    "c4": {
        "spec": re.compile(r".*\.puml$"),
        "manifest": re.compile(r"^anchor_manifest\.json$"),
    },
    "bpmn": {
        "spec": re.compile(r".*\.bpmn$"),
        "manifest": re.compile(r"^anchor_manifest\.json$"),
    },
    "dbml": {
        "spec": re.compile(r".*\.dbml$"),
        "manifest": re.compile(r"^anchor_manifest\.json$"),
    },
}


@dataclass
class Inventory:
    """Workspace artifact inventory. Each field is a path or list of
    paths if present, None / empty if absent. Renderer consults this to
    decide which pages to emit + which navigation links to show."""

    workspace: Path
    a_tables: dict[str, Path | None] = field(default_factory=dict)
    audits: dict[str, Path | None] = field(default_factory=dict)
    handoff: dict[str, Path | None] = field(default_factory=dict)
    contracts: dict[str, dict[str, Path | None]] = field(default_factory=dict)
    sidecars: dict[str, list[Path]] = field(default_factory=dict)
    sidecar_manifests: dict[str, Path | None] = field(default_factory=dict)
    telemetry_runs: list[Path] = field(default_factory=list)
    proposals_index: Path | None = None
    proposals: list[Path] = field(default_factory=list)


def _walk_match(
    root: Path,
    patterns: dict[str, re.Pattern[str]],
) -> dict[str, Path | None]:
    """Walk `root` recursively, return first-match per pattern key."""
    result: dict[str, Path | None] = {key: None for key in patterns}
    if not root.is_dir():
        return result
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        for key, rx in patterns.items():
            if result[key] is None and rx.fullmatch(name):
                result[key] = path
    return result


def discover(workspace: Path) -> Inventory:
    """Walk workspace and build a full Inventory. Defensive: missing
    subdirs degrade to empty entries, never raise."""
    inv = Inventory(workspace=workspace)

    canonical_root = workspace / "analysis" / "canonical"
    handoff_root = workspace / "analysis" / "handoff"
    views_root = workspace / "analysis" / "views"
    telemetry_root = workspace / "analysis" / "telemetry"

    # A-tables (canonical CSVs, scattered across stage subdirs).
    inv.a_tables = _walk_match(canonical_root, A_TABLE_PATTERNS)

    # Audit reports (markdown, scattered across stages + handoff).
    inv.audits = {}
    canonical_audits = _walk_match(canonical_root, AUDIT_PATTERNS)
    handoff_audits = _walk_match(handoff_root, AUDIT_PATTERNS)
    for key in AUDIT_PATTERNS:
        # Prefer canonical location; fall back to handoff.
        inv.audits[key] = canonical_audits[key] or handoff_audits[key]

    # Handoff packets (H1-H4 markdown).
    inv.handoff = _walk_match(handoff_root, HANDOFF_PATTERNS)

    # Contract exports (analysis/handoff/contracts/<format>/).
    inv.contracts = {}
    contracts_root = handoff_root / "contracts"
    for fmt, patterns in CONTRACT_FORMATS.items():
        fmt_root = contracts_root / fmt
        inv.contracts[fmt] = _walk_match(fmt_root, patterns)

    # Sidecars (analysis/views/<format>/).
    inv.sidecars = {fmt: [] for fmt in SIDECAR_FORMATS}
    inv.sidecar_manifests = {fmt: None for fmt in SIDECAR_FORMATS}
    for fmt, patterns in SIDECAR_FORMATS.items():
        fmt_root = views_root / fmt
        if not fmt_root.is_dir():
            continue
        spec_rx = patterns["spec"]
        manifest_rx = patterns["manifest"]
        for path in sorted(fmt_root.rglob("*")):
            if not path.is_file():
                continue
            if spec_rx.fullmatch(path.name):
                inv.sidecars[fmt].append(path)
            elif inv.sidecar_manifests[fmt] is None and manifest_rx.fullmatch(path.name):
                inv.sidecar_manifests[fmt] = path

    # Phase 7 telemetry runs (analysis/telemetry/run_*.json).
    if telemetry_root.is_dir():
        inv.telemetry_runs = sorted(telemetry_root.glob("run_*.json"))

    # Phase 7 L2 patcher proposals.
    proposals_root = telemetry_root / "proposals"
    if proposals_root.is_dir():
        index_path = proposals_root / "_index.json"
        if index_path.is_file():
            inv.proposals_index = index_path
        inv.proposals = sorted(proposals_root.glob("*.summary.md"))

    return inv


def count_rows(csv_path: Path) -> int:
    """Cheap CSV row count (header excluded). Returns 0 if file missing."""
    if not csv_path.is_file():
        return 0
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        # Subtract 1 for header. Empty trailing line tolerated.
        return max(0, sum(1 for _ in fh) - 1)


def detect_audit_verdict(md_path: Path) -> str:
    """Quick verdict scan in an audit report's first ~500 chars.
    Returns one of: 'pass', 'warn', 'fail', 'na', 'unknown'."""
    if not md_path or not md_path.is_file():
        return "na"
    head = md_path.read_text(encoding="utf-8", errors="replace")[:500].lower()
    # Order matters: most-severe wins if multiple appear.
    if any(token in head for token in ("verdict: fail", "verdict=fail", "blockers:", "status: fail")):
        return "fail"
    if any(token in head for token in ("verdict: warn", "verdict=warn", "warnings:", "status: warn")):
        return "warn"
    if any(token in head for token in ("verdict: pass", "verdict=pass", "status: pass", "0 findings")):
        return "pass"
    if any(token in head for token in ("verdict: n/a", "status: n/a", "not applicable")):
        return "na"
    return "unknown"
