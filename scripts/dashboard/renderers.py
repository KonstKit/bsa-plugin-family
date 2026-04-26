"""Rendering helpers for the BSA dashboard (v1.3.3 — WIP).

Pure functions that take a path or row list and return template-context
dicts. Heavy lifting (HTML generation) stays in the Jinja templates.

Stdlib + markdown_it_py.
"""

from __future__ import annotations

import csv
import json
import re
import shlex
from pathlib import Path
from typing import Any

# Severity → CSS class mapping for A51 row coloring.
A51_SEVERITY_CLASSES: dict[str, str] = {
    "critical": "row-critical",
    "high": "row-high",
    "medium": "row-medium",
    "low": "row-low",
}

# A51 IssueType → emoji prefix for visual scanning.
A51_ISSUE_TYPE_GLYPH: dict[str, str] = {
    "decision_needed": "?",
    "evidence_gap": "!",
    "fabrication": "x",
    "boundary_disagreement": "<>",
    "scope_disagreement": "<>",
    "inventory_gap": "!",
    "cross_tier_contradiction": "*",
    "link_strength_override": "~",
}

# Columns that should be treated as anchor IDs (clickable cross-refs).
# Format: (a_table_id, column_name) → target_a_table_id_for_link.
ANCHOR_COLUMNS: dict[tuple[str, str], str] = {
    ("a51", "RelatedClaimID"): "a59",
    ("a58", "SourceID"): "a50",
    ("a59", "SourceID"): "a50",
    ("a59", "ExcerptID"): "a58",
    ("a60", "SourceID"): "a50",
    ("a60", "RelatedClaimID"): "a59",
    ("a61", "ClaimID"): "a59",
    ("a61", "A51Ref"): "a51",
    ("a62", "RelatedClaimID"): "a59",
    ("a62", "A51Ref"): "a51",
    ("a70", "SourceClaimIDs"): "a59",
    ("a70", "RelatedNFRIDs"): "a62",
    ("a70", "A51Ref"): "a51",
    ("a71", "RelatedNFRID"): "a62",
    ("a71", "A51Ref"): "a51",
    ("a72", "StoryID"): "a70",
    ("a72", "ClaimID"): "a59",
    ("a72", "SourceID"): "a50",
    ("a72", "A51Ref"): "a51",
}

# Multi-value separators used in canonical CSVs.
MULTI_VALUE_SPLIT_RE = re.compile(r"[;/]")

# Proposal-ID safe-character regex. v1.3.3 R1 lesson #1 reapplied
# (untrusted-input-as-path-component, mirroring v1.2.19 R1-FIX-1):
# `_index.json` is operator-trusted in normal use BUT a maliciously
# crafted entry with `../` or path separators could let the dashboard
# read outside `analysis/telemetry/proposals/` AND write outside
# `output_dir/phase7/`. Validate every proposal_id against this
# pattern BEFORE any path join; skip non-conforming IDs.
_PROPOSAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def is_safe_proposal_id(proposal_id: object) -> bool:
    """True iff `proposal_id` is a string matching the safe-ID regex.
    Caller must use this check BEFORE any path join with proposal_id."""
    return (
        isinstance(proposal_id, str)
        and bool(_PROPOSAL_ID_PATTERN.fullmatch(proposal_id))
    )


# ---- A-table rendering --------------------------------------------


def load_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read CSV and return (headers, rows). Defensive against missing
    files (returns empty)."""
    if not csv_path or not csv_path.is_file():
        return [], []
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        rows = list(reader)
    return headers, rows


def build_artifact_context(
    a_id: str,
    csv_path: Path,
    label: str,
) -> dict[str, Any]:
    """Build template context for one A-table page."""
    headers, rows = load_csv_rows(csv_path)

    # Per-row CSS class for A51 severity coloring.
    row_classes: list[str] = []
    if a_id == "a51":
        for row in rows:
            sev = (row.get("Severity") or "").strip().lower()
            row_classes.append(A51_SEVERITY_CLASSES.get(sev, ""))
    else:
        row_classes = [""] * len(rows)

    # Detect anchor-column links + multi-value cells.
    cell_links: list[list[list[dict[str, str]]]] = []
    for row in rows:
        row_links: list[list[dict[str, str]]] = []
        for col in headers:
            cell = (row.get(col) or "").strip()
            target_table = ANCHOR_COLUMNS.get((a_id, col))
            if target_table and cell:
                values = [v.strip() for v in MULTI_VALUE_SPLIT_RE.split(cell) if v.strip()]
                row_links.append([
                    {
                        "value": v,
                        "href": f"../artifacts/{target_table}.html#row-{v}",
                    }
                    for v in values
                ])
            else:
                row_links.append([])
        cell_links.append(row_links)

    # Primary key column (for #row-<id> anchor on each row).
    pk_col = _detect_primary_key_column(a_id, headers)

    return {
        "a_id": a_id,
        "label": label,
        "csv_path_str": str(csv_path) if csv_path else None,
        "headers": headers,
        "rows": rows,
        "row_classes": row_classes,
        "cell_links": cell_links,
        "pk_col": pk_col,
        "row_count": len(rows),
        "is_a51": a_id == "a51",
    }


def _detect_primary_key_column(a_id: str, headers: list[str]) -> str | None:
    """Per-A-table primary key column for row anchors."""
    pk_map = {
        "a50": "SourceID",
        "a51": "A51Ref",
        "a58": "ExcerptID",
        "a59": "ClaimID",
        "a60": "NegEvID",
        "a61": "AnchorID",
        "a62": "NFRID",
        "a70": "StoryID",
        "a71": "ScenarioID",
        "a72": "TraceID",
    }
    candidate = pk_map.get(a_id)
    if candidate and candidate in headers:
        return candidate
    return None


# ---- Audit MD → HTML rendering -------------------------------------


def md_to_html(md_text: str) -> str:
    """Render Markdown to HTML via markdown-it-py. Returns empty string
    if input is empty."""
    if not md_text:
        return ""
    try:
        from markdown_it import MarkdownIt
    except ImportError as exc:
        raise RuntimeError(
            "markdown-it-py required for skills/dashboard. Install via "
            "`pip install markdown-it-py` (or add to requirements-dev.txt)."
        ) from exc
    md = MarkdownIt("commonmark", {"breaks": False, "html": False})
    md.enable(["table", "strikethrough"])
    return md.render(md_text)


def build_audit_context(
    audit_id: str,
    md_path: Path,
    label: str,
    verdict: str,
) -> dict[str, Any]:
    """Build template context for one audit-report page."""
    if md_path and md_path.is_file():
        md_text = md_path.read_text(encoding="utf-8", errors="replace")
        html_body = md_to_html(md_text)
        source_path = str(md_path)
    else:
        html_body = "<p><em>Audit report not present in this workspace.</em></p>"
        source_path = None
    return {
        "audit_id": audit_id,
        "label": label,
        "verdict": verdict,
        "html_body": html_body,
        "source_path": source_path,
    }


def detect_audit_verdict_robust(md_path: Path | None) -> str:
    """More thorough verdict detection than loaders.detect_audit_verdict.
    Scans the WHOLE file (not just first 500 chars) for verdict markers.
    Returns one of: 'pass', 'warn', 'fail', 'na', 'unknown'."""
    if not md_path or not md_path.is_file():
        return "na"
    text = md_path.read_text(encoding="utf-8", errors="replace").lower()
    # Order: most-severe wins.
    if any(token in text for token in (
        "verdict: fail", "verdict=fail", "verdict**: fail",
        "status: fail", "❌", "blockers: 1", "blockers: 2",
        "blockers: 3", "blockers: 4", "blockers: 5",
    )):
        return "fail"
    if any(token in text for token in (
        "verdict: warn", "verdict=warn", "verdict**: warn",
        "status: warn", "warnings: 1", "warnings: 2",
    )):
        return "warn"
    if any(token in text for token in (
        "verdict: pass", "verdict=pass", "verdict**: pass",
        "status: pass", "0 findings", "0 blockers",
        "no new claims detected", "all sources", "all clean",
    )):
        return "pass"
    if any(token in text for token in (
        "verdict: n/a", "status: n/a", "not applicable",
    )):
        return "na"
    return "unknown"


# ---- Phase 7 proposal rendering ------------------------------------


def load_proposals_index(index_path: Path | None) -> list[dict[str, Any]]:
    """Load proposals _index.json. Returns empty list on missing/malformed."""
    if not index_path or not index_path.is_file():
        return []
    try:
        doc = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    proposals = doc.get("proposals", [])
    if not isinstance(proposals, list):
        return []
    return proposals


def render_unified_diff_html(diff_text: str) -> str:
    """Render a unified-diff text block as HTML with line classes for
    additions / deletions / hunks / context. No external lib — ~30 LOC
    of regex + classification."""
    if not diff_text:
        return ""
    lines_html: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            cls = "diff-meta"
        elif line.startswith("@@"):
            cls = "diff-hunk"
        elif line.startswith("+"):
            cls = "diff-add"
        elif line.startswith("-"):
            cls = "diff-del"
        elif line.startswith("diff "):
            cls = "diff-meta"
        elif line.startswith("index "):
            cls = "diff-meta"
        else:
            cls = "diff-context"
        # Escape HTML-significant characters.
        escaped = (
            line.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        lines_html.append(f'<span class="{cls}">{escaped}</span>')
    return "\n".join(lines_html)


def build_proposal_context(
    proposal_meta: dict[str, Any],
    proposals_root: Path,
) -> dict[str, Any] | None:
    """Per-proposal page context. proposal_meta is one entry from
    _index.json's `proposals` list. Returns None if the entry's
    proposal_id is missing or fails the safe-ID regex (v1.3.3 R1
    lesson #1: validate untrusted input BEFORE path construction)."""
    if not isinstance(proposal_meta, dict):
        return None
    proposal_id = proposal_meta.get("proposal_id") or proposal_meta.get("id")
    if not is_safe_proposal_id(proposal_id):
        return None
    summary_path = proposals_root / f"{proposal_id}.summary.md"
    patch_path = proposals_root / f"{proposal_id}.patch"

    if summary_path.is_file():
        summary_md = summary_path.read_text(encoding="utf-8", errors="replace")
        summary_html = md_to_html(summary_md)
    else:
        summary_html = "<p><em>Summary not present.</em></p>"

    if patch_path.is_file():
        patch_text = patch_path.read_text(encoding="utf-8", errors="replace")
        diff_html = render_unified_diff_html(patch_text)
        # Operator-pasteable command. Patch path is repo-relative.
        # shlex.quote() guards against spaces / shell metacharacters
        # in proposal_id (lesson #4); `--` end-of-options separator
        # already in place guards against leading-hyphen IDs (lesson
        # #5). Both v1.2.19 patcher post-Codex lessons applied here.
        patch_relpath = f"analysis/telemetry/proposals/{proposal_id}.patch"
        apply_command = f"git apply -- {shlex.quote(patch_relpath)}"
    else:
        diff_html = ""
        apply_command = None

    return {
        "proposal_id": proposal_id,
        "meta": proposal_meta,
        "summary_html": summary_html,
        "diff_html": diff_html,
        "apply_command": apply_command,
        "summary_present": summary_path.is_file(),
        "patch_present": patch_path.is_file(),
    }


# ---- Handoff packet rendering --------------------------------------


def build_handoff_context(
    packet_id: str,
    md_path: Path,
    label: str,
) -> dict[str, Any]:
    """Build template context for one H1-H4 packet page."""
    if md_path and md_path.is_file():
        md_text = md_path.read_text(encoding="utf-8", errors="replace")
        html_body = md_to_html(md_text)
        source_path = str(md_path)
    else:
        html_body = "<p><em>Handoff packet not present.</em></p>"
        source_path = None
    return {
        "packet_id": packet_id,
        "label": label,
        "html_body": html_body,
        "source_path": source_path,
    }


# ---- Contract export rendering -------------------------------------


def load_contract_spec(spec_path: Path | None) -> str:
    """Read contract spec file (yaml/proto) as plain text. Returns
    empty string if missing."""
    if not spec_path or not spec_path.is_file():
        return ""
    return spec_path.read_text(encoding="utf-8", errors="replace")


def load_anchor_manifest(manifest_path: Path | None) -> dict[str, Any] | None:
    """Read anchor_manifest.json. Returns None if missing/malformed."""
    if not manifest_path or not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def build_contract_context(
    fmt: str,
    spec_path: Path | None,
    manifest_path: Path | None,
    label: str,
) -> dict[str, Any]:
    """Build template context for a contract export page (OpenAPI /
    AsyncAPI / proto)."""
    spec_text = load_contract_spec(spec_path)
    manifest = load_anchor_manifest(manifest_path)

    # Flatten anchor_map for table display.
    anchor_rows: list[dict[str, Any]] = []
    if manifest and "view_files" in manifest:
        for view_file in manifest["view_files"]:
            for entry in view_file.get("anchor_map", []):
                anchor_rows.append({
                    "view_element_id": entry.get("view_element_id", ""),
                    "view_element_kind": entry.get("view_element_kind", ""),
                    "a61_anchor_id": entry.get("a61_anchor_id", ""),
                    "notes": entry.get("notes", ""),
                })

    unmapped_rows: list[dict[str, Any]] = []
    if manifest and "view_files" in manifest:
        for view_file in manifest["view_files"]:
            for entry in view_file.get("unmapped_anchors", []):
                unmapped_rows.append({
                    "a61_anchor_id": entry.get("a61_anchor_id", ""),
                    "reason": entry.get("reason", ""),
                    "element_id": entry.get("element_id", ""),
                })

    # Language hint for syntax-highlight class name.
    language_map = {"openapi": "yaml", "asyncapi": "yaml", "proto": "protobuf"}

    return {
        "fmt": fmt,
        "label": label,
        "spec_text": spec_text,
        "spec_path": str(spec_path) if spec_path else None,
        "manifest_present": manifest is not None,
        "anchor_rows": anchor_rows,
        "unmapped_rows": unmapped_rows,
        "language": language_map.get(fmt, "text"),
    }


# ---- Sidecar rendering --------------------------------------------


def build_sidecar_context(
    fmt: str,
    spec_paths: list[Path],
    manifest_path: Path | None,
    label: str,
) -> dict[str, Any]:
    """Build template context for sidecar diagrams page (C4 / BPMN /
    DBML). Per locked design (v1.3.3 day 5): show source as code block
    + manifest mapping table. No JS embed (lazy: operator runs proper
    viewer separately — `plantuml file.puml`, etc.)."""
    diagrams: list[dict[str, Any]] = []
    for path in spec_paths:
        diagrams.append({
            "name": path.name,
            "source_path": str(path),
            "content": path.read_text(encoding="utf-8", errors="replace"),
        })

    manifest = load_anchor_manifest(manifest_path)
    anchor_rows: list[dict[str, Any]] = []
    if manifest and "view_files" in manifest:
        for view_file in manifest["view_files"]:
            for entry in view_file.get("anchor_map", []):
                anchor_rows.append({
                    "view_element_id": entry.get("view_element_id", ""),
                    "view_element_kind": entry.get("view_element_kind", ""),
                    "a61_anchor_id": entry.get("a61_anchor_id", ""),
                })

    # Render hint per-format.
    render_hints = {
        "c4": "Render via PlantUML CLI: <code>plantuml &lt;file.puml&gt;</code>",
        "bpmn": "Render via Camunda Modeler or bpmn-js viewer (operator-side).",
        "dbml": "Render via dbdiagram.io (paste source) or DBML CLI.",
    }

    return {
        "fmt": fmt,
        "label": label,
        "diagrams": diagrams,
        "manifest_present": manifest is not None,
        "anchor_rows": anchor_rows,
        "render_hint": render_hints.get(fmt, ""),
    }


# ---- Claim layer (A59 + A50 + A58 join) ----------------------------


def build_claim_layer_context(
    a59_path: Path | None,
    a50_path: Path | None,
    a58_path: Path | None,
) -> dict[str, Any]:
    """Build claim-layer view: per-A59-claim card with bound A50 sources
    + A58 excerpts."""
    _, a59_rows = load_csv_rows(a59_path) if a59_path else ([], [])
    _, a50_rows = load_csv_rows(a50_path) if a50_path else ([], [])
    _, a58_rows = load_csv_rows(a58_path) if a58_path else ([], [])

    a50_by_id = {row.get("SourceID", ""): row for row in a50_rows}
    a58_by_id = {row.get("ExcerptID", ""): row for row in a58_rows}

    claim_cards: list[dict[str, Any]] = []
    for claim in a59_rows:
        source_ids = [
            v.strip() for v in MULTI_VALUE_SPLIT_RE.split(claim.get("SourceID", "") or "")
            if v.strip()
        ]
        excerpt_ids = [
            v.strip() for v in MULTI_VALUE_SPLIT_RE.split(claim.get("ExcerptID", "") or "")
            if v.strip()
        ]
        bound_sources = [a50_by_id.get(sid) for sid in source_ids if sid in a50_by_id]
        bound_excerpts = [a58_by_id.get(eid) for eid in excerpt_ids if eid in a58_by_id]
        claim_cards.append({
            "claim": claim,
            "bound_sources": bound_sources,
            "bound_excerpts": bound_excerpts,
        })

    return {
        "claim_cards": claim_cards,
        "claim_count": len(claim_cards),
    }


# ---- Traceability matrix (A72) -------------------------------------


def build_traceability_context(a72_path: Path | None) -> dict[str, Any]:
    """Build traceability view from A72. Renders as Mermaid flowchart
    (Story→Claim→Source) PLUS nested HTML table grouped by StoryID
    (fallback for when JS is disabled). v1.3.5 enhancement."""
    _, a72_rows = load_csv_rows(a72_path) if a72_path else ([], [])

    by_story: dict[str, list[dict[str, str]]] = {}
    for row in a72_rows:
        story_id = (row.get("StoryID") or "").strip() or "(unspecified)"
        by_story.setdefault(story_id, []).append(row)

    grouped = [
        {
            "story_id": story_id,
            "rows": rows,
            "row_count": len(rows),
        }
        for story_id, rows in sorted(by_story.items())
    ]

    mermaid_source = _build_traceability_mermaid(a72_rows)

    return {
        "grouped": grouped,
        "story_count": len(grouped),
        "trace_count": len(a72_rows),
        "mermaid_source": mermaid_source,
        "mermaid_node_count": _count_mermaid_nodes(a72_rows),
    }


# Mermaid identifier sanitizer — Mermaid node IDs match `[A-Za-z0-9_]+`
# and cannot start with reserved words. Replace anything else with `_`.
_MERMAID_ID_SAFE = re.compile(r"[^A-Za-z0-9_]")


def _mermaid_node_id(prefix: str, raw: str) -> str:
    """Produce a Mermaid-safe node id like `s_STORY_001`."""
    sanitized = _MERMAID_ID_SAFE.sub("_", raw or "unknown")
    return f"{prefix}_{sanitized}"


def _build_traceability_mermaid(a72_rows: list[dict[str, str]]) -> str:
    """Build Mermaid flowchart source from A72 rows.

    Three node tiers (left → right):
      Story (s_*)  →  Claim (c_*)  →  Source (src_*)

    Multi-value StoryID/ClaimID/SourceID cells (`;`/`/`-joined per
    canonical CSV convention) fan out into multiple edges.

    Returns the full `flowchart LR ... ` source. Empty input → empty
    flowchart with a placeholder note (still valid Mermaid)."""
    if not a72_rows:
        return "flowchart LR\n    empty[\"No A72 rows\"]\n"

    nodes: dict[str, str] = {}  # node_id → label
    edges: set[tuple[str, str]] = set()

    for row in a72_rows:
        story_ids = [
            v.strip() for v in MULTI_VALUE_SPLIT_RE.split(row.get("StoryID", "") or "")
            if v.strip()
        ] or ["(unspecified)"]
        claim_ids = [
            v.strip() for v in MULTI_VALUE_SPLIT_RE.split(row.get("ClaimID", "") or "")
            if v.strip()
        ] or ["(unspecified)"]
        source_ids = [
            v.strip() for v in MULTI_VALUE_SPLIT_RE.split(row.get("SourceID", "") or "")
            if v.strip()
        ] or ["(unspecified)"]

        for sid in story_ids:
            sid_node = _mermaid_node_id("s", sid)
            nodes[sid_node] = sid
            for cid in claim_ids:
                cid_node = _mermaid_node_id("c", cid)
                nodes[cid_node] = cid
                edges.add((sid_node, cid_node))
                for srcid in source_ids:
                    srcid_node = _mermaid_node_id("src", srcid)
                    nodes[srcid_node] = srcid
                    edges.add((cid_node, srcid_node))

    lines = ["flowchart LR"]
    # Style classes per tier.
    lines.append("    classDef story fill:#dbeafe,stroke:#2563eb,color:#1e40af")
    lines.append("    classDef claim fill:#dcfce7,stroke:#16a34a,color:#14532d")
    lines.append("    classDef source fill:#fef3c7,stroke:#d97706,color:#78350f")
    for node_id, label in nodes.items():
        # Mermaid label syntax: `id["label text"]`. Escape quotes in label.
        safe_label = label.replace('"', '&quot;')
        lines.append(f'    {node_id}["{safe_label}"]')
        if node_id.startswith("s_"):
            lines.append(f"    class {node_id} story")
        elif node_id.startswith("c_"):
            lines.append(f"    class {node_id} claim")
        elif node_id.startswith("src_"):
            lines.append(f"    class {node_id} source")
    for src, dst in sorted(edges):
        lines.append(f"    {src} --> {dst}")
    return "\n".join(lines) + "\n"


def _count_mermaid_nodes(a72_rows: list[dict[str, str]]) -> int:
    """Distinct Story/Claim/Source IDs across all rows. Cheap upper
    bound for UX warning ('large graph; rendering may be slow')."""
    ids: set[str] = set()
    for row in a72_rows:
        for col in ("StoryID", "ClaimID", "SourceID"):
            cell = row.get(col, "") or ""
            for v in MULTI_VALUE_SPLIT_RE.split(cell):
                v = v.strip()
                if v:
                    ids.add(v)
    return len(ids)
