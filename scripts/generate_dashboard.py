#!/usr/bin/env python3
"""BSA static-HTML dashboard generator (v1.3.3).

Read-only viewer over canonical artifacts + handoff packets + audit
reports + sidecar diagrams + Phase 7 telemetry. Generates static HTML
under `<workspace>/analysis/handoff/dashboard/` (operator-side, NEVER
canonical). Operator opens `dashboard/index.html` in any browser; no
HTTP server, no backend, no canonical writes.

Pattern lineage: operator-runner family (v1.2.4 telemetry collector →
v1.2.16 freshness → v1.2.17 triangulation → v1.2.18 miner → v1.2.19
patcher → v1.3.0/1/2 contract exporters → v1.3.3 dashboard).
Stdlib + jinja2 + markdown-it-py. Defensive reads. Atomic writes via
tempfile + os.replace. Operator-invoked. NEVER runs git/commit/push,
NEVER edits canonical state, NEVER modifies source files.

CLI:
  python3 scripts/generate_dashboard.py --workspace <path>
  python3 scripts/generate_dashboard.py --workspace <path> --output-dir <dir>
  python3 scripts/generate_dashboard.py --workspace <path> --filter audits,phase7
  python3 scripts/generate_dashboard.py --workspace <path> --watch
  python3 scripts/generate_dashboard.py --workspace <path> --print-only
  python3 scripts/generate_dashboard.py --workspace <path> --quiet

Exit codes:
  0 — bundle generated.
  2 — invocation error.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = SCRIPT_DIR / "dashboard"
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"

# Add scripts/ to sys.path so `dashboard` package imports cleanly when
# running from arbitrary cwd.
sys.path.insert(0, str(SCRIPT_DIR))

from dashboard import loaders, renderers  # noqa: E402

DEFAULT_OUTPUT_REL = "analysis/handoff/dashboard"
DEFAULT_INDEX_FILENAME = "index.html"
WATCH_POLL_INTERVAL_S = 2.0

A_TABLE_LABELS: dict[str, str] = {
    "a50": "sources",
    "a51": "issue routes",
    "a58": "evidence excerpts",
    "a59": "claims",
    "a60": "neg evidence",
    "a61": "anchors",
    "a62": "NFRs",
    "a70": "stories",
    "a71": "scenarios",
    "a72": "trace links",
}

AUDIT_LABELS: dict[str, str] = {
    "freshness": "Freshness audit",
    "triangulation": "Triangulation audit",
    "anchor": "Anchor audit",
    "citation": "Citation / overclaim audit",
    "no_new_claims": "No-new-claims report",
    "consistency": "Consistency audit",
    "prompt_injection": "Prompt-injection audit",
    "contradiction_scan": "Contradiction scan",
}

HANDOFF_LABELS: dict[str, str] = {
    "h1": "H1 — Exec Brief",
    "h2": "H2 — Delivery Packet",
    "h3": "H3 — Validation Packet",
    "h4": "H4 — Open Items Packet",
}

CONTRACT_LABELS: dict[str, str] = {
    "openapi": "OpenAPI 3.1 (REST)",
    "asyncapi": "AsyncAPI 3.0 (events)",
    "proto": "proto3 (gRPC)",
}

SIDECAR_LABELS: dict[str, str] = {
    "c4": "C4 — PlantUML",
    "bpmn": "BPMN — Camunda",
    "dbml": "DBML — relational",
}

FILTER_PAGES: tuple[str, ...] = (
    "index",
    "artifacts",
    "audits",
    "handoff",
    "contracts",
    "sidecars",
    "phase7",
)


# ---- Atomic writes -------------------------------------------------


def _atomic_write(target_path: Path, body: str) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=".dashboard_",
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


def _maybe_write(target_path: Path, body: str, *, dry_run: bool) -> None:
    """Write atomically unless dry_run is True. v1.3.3 R1 fix #2:
    --print-only must NOT touch the filesystem; pre-R1 the writes
    happened before the print_only branch."""
    if dry_run:
        return
    _atomic_write(target_path, body)


# ---- Inventory → template-context shaping --------------------------


_STAGE_NAMES = frozenset({
    "core_controls", "stage1", "stage2", "stage3", "stage4",
    "stage5", "stage6", "stage7", "stage8",
})


def _detect_pipeline_stages(inv: loaders.Inventory) -> list[dict]:
    """Group canonical artifacts by stage subdirectory name."""
    stages: dict[str, int] = {}
    for path in inv.a_tables.values():
        if path is None:
            continue
        for parent in path.parents:
            if parent.name in _STAGE_NAMES:
                stages[parent.name] = stages.get(parent.name, 0) + 1
                break
    ordering = ("core_controls", "stage1", "stage2", "stage3", "stage4",
                "stage5", "stage6", "stage7", "stage8")
    return [
        {
            "name": name.replace("_", " "),
            "status": "present",
            "detail": (
                f"{stages[name]} artifact"
                f"{'s' if stages[name] != 1 else ''}"
            ),
        }
        for name in ordering
        if name in stages
    ]


def _build_index_context(inv: loaders.Inventory) -> dict:
    """Top-level index.html context."""
    a_table_counts = [
        {
            "id": a_id,
            "label": A_TABLE_LABELS.get(a_id, a_id),
            "count": loaders.count_rows(path) if path else 0,
        }
        for a_id, path in inv.a_tables.items()
    ]
    audit_verdicts = [
        {
            "id": audit_id,
            "label": AUDIT_LABELS.get(audit_id, audit_id),
            "verdict": renderers.detect_audit_verdict_robust(path),
        }
        for audit_id, path in inv.audits.items()
        if path is not None
    ]
    handoff_packets = [
        {"id": packet_id, "label": HANDOFF_LABELS.get(packet_id, packet_id)}
        for packet_id, path in inv.handoff.items()
        if path is not None
    ]
    contract_exports = [
        {"id": fmt, "label": CONTRACT_LABELS.get(fmt, fmt)}
        for fmt, files in inv.contracts.items()
        if files.get("spec") is not None
    ]
    sidecar_diagrams = [
        {"id": fmt, "label": SIDECAR_LABELS.get(fmt, fmt), "count": len(files)}
        for fmt, files in inv.sidecars.items()
        if files
    ]
    phase7_summary = None
    if inv.telemetry_runs or inv.proposals:
        phase7_summary = {
            "runs": len(inv.telemetry_runs),
            "proposals": len(inv.proposals),
        }
    return {
        "pipeline_stages": _detect_pipeline_stages(inv),
        "a_table_counts": a_table_counts,
        "audit_verdicts": audit_verdicts,
        "handoff_packets": handoff_packets,
        "contract_exports": contract_exports,
        "sidecar_diagrams": sidecar_diagrams,
        "phase7_summary": phase7_summary,
    }


def _build_base_context(
    inv: loaders.Inventory,
    *,
    active_page: str,
    watch_mode: bool,
    depth: int,
    rendered_sections: set[str] | None = None,
) -> dict:
    """Common context for base.html. `depth` = how many `..` to prepend
    to root_prefix and static_prefix (0 for top-level index, 1 for
    pages in subfolders like artifacts/a50.html).

    v1.3.3 R1 fix #3: nav-link `has_X` flags are gated by BOTH (a) the
    inventory has artifacts of type X AND (b) section X was actually
    rendered in this run. Pre-R1 nav links pointed to ungenerated
    pages when --filter excluded a section, producing 404s. Pass
    `rendered_sections=None` to skip the gate (for example, when
    rendering index.html during a full --filter index-only run from
    a fresh workspace where you want to see what's available even
    though it wasn't rendered)."""
    inv_has = {
        "artifacts": any(p is not None for p in inv.a_tables.values()),
        "audits": any(p is not None for p in inv.audits.values()),
        "handoff": any(p is not None for p in inv.handoff.values()),
        "contracts": any(
            files.get("spec") is not None for files in inv.contracts.values()
        ),
        "sidecars": any(files for files in inv.sidecars.values()),
        "phase7": bool(inv.telemetry_runs or inv.proposals),
    }
    if rendered_sections is None:
        gated = inv_has
    else:
        gated = {
            section: present and (section in rendered_sections)
            for section, present in inv_has.items()
        }
    root_prefix = "../" * depth
    static_prefix = root_prefix + "static/"
    return {
        "workspace_path": str(inv.workspace),
        "workspace_name": inv.workspace.name or "(workspace)",
        "active_page": active_page,
        "watch_mode": watch_mode,
        "root_prefix": root_prefix,
        "static_prefix": static_prefix,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "has_artifacts": gated["artifacts"],
        "has_audits": gated["audits"],
        "has_handoff": gated["handoff"],
        "has_contracts": gated["contracts"],
        "has_sidecars": gated["sidecars"],
        "has_phase7": gated["phase7"],
    }


# ---- Per-page rendering -------------------------------------------


def _render_index(env, inv, output_dir, *, watch_mode, dry_run, rendered_sections):
    base = _build_base_context(
        inv, active_page="index", watch_mode=watch_mode, depth=0,
        rendered_sections=rendered_sections,
    )
    ctx = {**base, **_build_index_context(inv)}
    html = env.get_template("index.html").render(**ctx)
    target = output_dir / DEFAULT_INDEX_FILENAME
    _maybe_write(target, html, dry_run=dry_run)
    return [{"page": "index", "path": str(target.relative_to(output_dir))}]


def _render_artifacts(env, inv, output_dir, *, watch_mode, dry_run, rendered_sections):
    """Render artifacts/index.html + 10 per-A-table pages + claim layer
    + traceability."""
    pages: list[dict] = []
    base = _build_base_context(
        inv, active_page="artifacts", watch_mode=watch_mode, depth=1,
        rendered_sections=rendered_sections,
    )

    # Cross-cutting view availability flags.
    has_claim_layer = inv.a_tables.get("a59") is not None
    has_traceability = inv.a_tables.get("a72") is not None

    # artifacts/index.html
    a_table_counts = [
        {
            "id": a_id,
            "label": A_TABLE_LABELS.get(a_id, a_id),
            "count": loaders.count_rows(path) if path else 0,
        }
        for a_id, path in inv.a_tables.items()
    ]
    ctx = {
        **base,
        "a_table_counts": a_table_counts,
        "has_claim_layer": has_claim_layer,
        "has_traceability": has_traceability,
    }
    html = env.get_template("artifacts_index.html").render(**ctx)
    target = output_dir / "artifacts" / "index.html"
    _maybe_write(target, html, dry_run=dry_run)
    pages.append({"page": "artifacts/index", "path": str(target.relative_to(output_dir))})

    # Per-A-table pages.
    for a_id, csv_path in inv.a_tables.items():
        artifact_ctx = renderers.build_artifact_context(
            a_id=a_id,
            csv_path=csv_path,
            label=A_TABLE_LABELS.get(a_id, a_id),
        )
        ctx = {**base, **artifact_ctx}
        html = env.get_template("artifact_table.html").render(**ctx)
        target = output_dir / "artifacts" / f"{a_id}.html"
        _maybe_write(target, html, dry_run=dry_run)
        pages.append({"page": f"artifacts/{a_id}", "path": str(target.relative_to(output_dir))})

    # Claim layer view.
    if has_claim_layer:
        cl_ctx = renderers.build_claim_layer_context(
            a59_path=inv.a_tables.get("a59"),
            a50_path=inv.a_tables.get("a50"),
            a58_path=inv.a_tables.get("a58"),
        )
        ctx = {**base, **cl_ctx}
        html = env.get_template("claim_layer.html").render(**ctx)
        target = output_dir / "artifacts" / "claim_layer.html"
        _maybe_write(target, html, dry_run=dry_run)
        pages.append({"page": "artifacts/claim_layer", "path": str(target.relative_to(output_dir))})

    # Traceability matrix view.
    if has_traceability:
        tr_ctx = renderers.build_traceability_context(inv.a_tables.get("a72"))
        ctx = {**base, **tr_ctx}
        html = env.get_template("traceability.html").render(**ctx)
        target = output_dir / "artifacts" / "traceability.html"
        _maybe_write(target, html, dry_run=dry_run)
        pages.append({"page": "artifacts/traceability", "path": str(target.relative_to(output_dir))})

    return pages


def _render_audits(env, inv, output_dir, *, watch_mode, dry_run, rendered_sections):
    pages: list[dict] = []
    base = _build_base_context(
        inv, active_page="audits", watch_mode=watch_mode, depth=1,
        rendered_sections=rendered_sections,
    )

    audit_verdicts = [
        {
            "id": audit_id,
            "label": AUDIT_LABELS.get(audit_id, audit_id),
            "verdict": renderers.detect_audit_verdict_robust(path),
            "path": path,
        }
        for audit_id, path in inv.audits.items()
        if path is not None
    ]

    ctx = {**base, "audit_verdicts": audit_verdicts}
    html = env.get_template("audits_index.html").render(**ctx)
    target = output_dir / "audits" / "index.html"
    _maybe_write(target, html, dry_run=dry_run)
    pages.append({"page": "audits/index", "path": str(target.relative_to(output_dir))})

    for entry in audit_verdicts:
        audit_ctx = renderers.build_audit_context(
            audit_id=entry["id"],
            md_path=entry["path"],
            label=entry["label"],
            verdict=entry["verdict"],
        )
        ctx = {**base, **audit_ctx}
        html = env.get_template("audit_view.html").render(**ctx)
        target = output_dir / "audits" / f"{entry['id']}.html"
        _maybe_write(target, html, dry_run=dry_run)
        pages.append({"page": f"audits/{entry['id']}", "path": str(target.relative_to(output_dir))})

    return pages


def _render_handoff(env, inv, output_dir, *, watch_mode, dry_run, rendered_sections):
    pages: list[dict] = []
    base = _build_base_context(
        inv, active_page="handoff", watch_mode=watch_mode, depth=1,
        rendered_sections=rendered_sections,
    )

    handoff_packets = [
        {"id": pid, "label": HANDOFF_LABELS.get(pid, pid), "path": path}
        for pid, path in inv.handoff.items()
        if path is not None
    ]
    ctx = {**base, "handoff_packets": handoff_packets}
    html = env.get_template("handoff_index.html").render(**ctx)
    target = output_dir / "handoff" / "index.html"
    _maybe_write(target, html, dry_run=dry_run)
    pages.append({"page": "handoff/index", "path": str(target.relative_to(output_dir))})

    for entry in handoff_packets:
        h_ctx = renderers.build_handoff_context(
            packet_id=entry["id"],
            md_path=entry["path"],
            label=entry["label"],
        )
        ctx = {**base, **h_ctx}
        html = env.get_template("handoff_view.html").render(**ctx)
        target = output_dir / "handoff" / f"{entry['id']}.html"
        _maybe_write(target, html, dry_run=dry_run)
        pages.append({"page": f"handoff/{entry['id']}", "path": str(target.relative_to(output_dir))})

    return pages


def _render_contracts(env, inv, output_dir, *, watch_mode, dry_run, rendered_sections):
    pages: list[dict] = []
    base = _build_base_context(
        inv, active_page="contracts", watch_mode=watch_mode, depth=1,
        rendered_sections=rendered_sections,
    )

    contract_exports = [
        {"id": fmt, "label": CONTRACT_LABELS.get(fmt, fmt)}
        for fmt, files in inv.contracts.items()
        if files.get("spec") is not None
    ]
    ctx = {**base, "contract_exports": contract_exports}
    html = env.get_template("contracts_index.html").render(**ctx)
    target = output_dir / "contracts" / "index.html"
    _maybe_write(target, html, dry_run=dry_run)
    pages.append({"page": "contracts/index", "path": str(target.relative_to(output_dir))})

    for fmt, files in inv.contracts.items():
        if files.get("spec") is None:
            continue
        c_ctx = renderers.build_contract_context(
            fmt=fmt,
            spec_path=files.get("spec"),
            manifest_path=files.get("manifest"),
            label=CONTRACT_LABELS.get(fmt, fmt),
        )
        ctx = {**base, **c_ctx}
        html = env.get_template("contract_view.html").render(**ctx)
        target = output_dir / "contracts" / f"{fmt}.html"
        _maybe_write(target, html, dry_run=dry_run)
        pages.append({"page": f"contracts/{fmt}", "path": str(target.relative_to(output_dir))})

    return pages


def _render_sidecars(env, inv, output_dir, *, watch_mode, dry_run, rendered_sections):
    pages: list[dict] = []
    base = _build_base_context(
        inv, active_page="sidecars", watch_mode=watch_mode, depth=1,
        rendered_sections=rendered_sections,
    )

    sidecar_diagrams = [
        {"id": fmt, "label": SIDECAR_LABELS.get(fmt, fmt), "count": len(files)}
        for fmt, files in inv.sidecars.items()
        if files
    ]
    ctx = {**base, "sidecar_diagrams": sidecar_diagrams}
    html = env.get_template("sidecars_index.html").render(**ctx)
    target = output_dir / "sidecars" / "index.html"
    _maybe_write(target, html, dry_run=dry_run)
    pages.append({"page": "sidecars/index", "path": str(target.relative_to(output_dir))})

    for fmt, spec_paths in inv.sidecars.items():
        if not spec_paths:
            continue
        s_ctx = renderers.build_sidecar_context(
            fmt=fmt,
            spec_paths=spec_paths,
            manifest_path=inv.sidecar_manifests.get(fmt),
            label=SIDECAR_LABELS.get(fmt, fmt),
        )
        ctx = {**base, **s_ctx}
        html = env.get_template("sidecar_view.html").render(**ctx)
        target = output_dir / "sidecars" / f"{fmt}.html"
        _maybe_write(target, html, dry_run=dry_run)
        pages.append({"page": f"sidecars/{fmt}", "path": str(target.relative_to(output_dir))})

    return pages


def _render_phase7(env, inv, output_dir, *, watch_mode, dry_run, rendered_sections):
    pages: list[dict] = []
    base = _build_base_context(
        inv, active_page="phase7", watch_mode=watch_mode, depth=1,
        rendered_sections=rendered_sections,
    )

    proposals_meta = renderers.load_proposals_index(inv.proposals_index)
    # v1.3.3 R2 fix: filter proposals_meta to safe-ID entries BEFORE
    # passing to the index template so we don't render dead links to
    # proposal_<id>.html pages that the per-proposal loop will skip
    # (R1 fix #1 silently skips unsafe IDs at detail-page level; R2
    # extends the filter upstream so the index also stays consistent).
    # Also normalize `id` → `proposal_id` so the template can rely on
    # a single key (Phase 7 patcher emits `proposal_id` but defensive
    # against operator-edited _index.json using `id` shorthand).
    safe_proposals_meta = []
    for p in proposals_meta:
        if not isinstance(p, dict):
            continue
        pid = p.get("proposal_id") or p.get("id")
        if not renderers.is_safe_proposal_id(pid):
            continue
        normalized = dict(p)
        normalized["proposal_id"] = pid
        safe_proposals_meta.append(normalized)
    telemetry_runs_meta = [
        {"name": p.name, "path": str(p)} for p in inv.telemetry_runs
    ]
    ctx = {
        **base,
        "proposals": safe_proposals_meta,
        "telemetry_runs": telemetry_runs_meta,
        "telemetry_run_count": len(telemetry_runs_meta),
    }
    html = env.get_template("phase7_index.html").render(**ctx)
    target = output_dir / "phase7" / "index.html"
    _maybe_write(target, html, dry_run=dry_run)
    pages.append({"page": "phase7/index", "path": str(target.relative_to(output_dir))})

    if inv.proposals_index:
        proposals_root = inv.proposals_index.parent
        # Use the same safe-filtered list the index renders from (R2
        # consistency fix); detail-page validation in
        # build_proposal_context is preserved as defense-in-depth.
        for proposal_meta in safe_proposals_meta:
            p_ctx = renderers.build_proposal_context(
                proposal_meta=proposal_meta,
                proposals_root=proposals_root,
            )
            # v1.3.3 R1 fix #1: build_proposal_context returns None
            # when proposal_id fails the safe-ID regex (untrusted-
            # input-as-path-component defense). Skip such entries
            # silently; they would otherwise let a crafted _index.json
            # escape proposals_root or output_dir/phase7/.
            if p_ctx is None:
                continue
            ctx = {**base, **p_ctx}
            html = env.get_template("proposal_view.html").render(**ctx)
            pid = p_ctx["proposal_id"]
            target = output_dir / "phase7" / f"proposal_{pid}.html"
            _maybe_write(target, html, dry_run=dry_run)
            pages.append({
                "page": f"phase7/proposal_{pid}",
                "path": str(target.relative_to(output_dir)),
            })

    return pages


# ---- Static asset copy + main render --------------------------------


def _make_jinja_env():
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except ImportError as exc:
        raise RuntimeError(
            "Jinja2 required for skills/dashboard. Install via "
            "`pip install jinja2` (or add to requirements-dev.txt)."
        ) from exc
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )


def _copy_static_assets(output_dir: Path, *, dry_run: bool) -> None:
    """Copy bundled CSS + JS into output_dir/static/. Idempotent.
    No-op when dry_run is True (v1.3.3 R1 fix #2)."""
    if dry_run:
        return
    target = output_dir / "static"
    target.mkdir(parents=True, exist_ok=True)
    for asset in STATIC_DIR.iterdir():
        if asset.is_file():
            shutil.copy2(asset, target / asset.name)


_RENDERER_DISPATCH = {
    "index": _render_index,
    "artifacts": _render_artifacts,
    "audits": _render_audits,
    "handoff": _render_handoff,
    "contracts": _render_contracts,
    "sidecars": _render_sidecars,
    "phase7": _render_phase7,
}


def render_dashboard(
    workspace: Path,
    output_dir: Path,
    *,
    filter_pages: set[str] | None,
    watch_mode: bool,
    quiet: bool,
    dry_run: bool = False,
) -> dict:
    """Generate the full dashboard HTML bundle. Returns a manifest dict
    listing every page emitted. When `dry_run` is True (driven by
    `--print-only`), the manifest is computed without touching the
    filesystem (v1.3.3 R1 fix #2)."""
    env = _make_jinja_env()
    inv = loaders.discover(workspace)

    pages_to_render = filter_pages or set(FILTER_PAGES)
    manifest_pages: list[dict] = []

    # Section visibility = inventory has artifacts AND filter requests
    # the section. Compute this BEFORE rendering so we can pass the
    # set to base_context for nav-link gating (v1.3.3 R1 fix #3).
    section_visibility = {
        "artifacts": any(p is not None for p in inv.a_tables.values()),
        "audits": any(p is not None for p in inv.audits.values()),
        "handoff": any(p is not None for p in inv.handoff.values()),
        "contracts": any(
            files.get("spec") is not None for files in inv.contracts.values()
        ),
        "sidecars": any(files for files in inv.sidecars.values()),
        "phase7": bool(inv.telemetry_runs or inv.proposals_index),
    }
    rendered_sections = {
        section for section, visible in section_visibility.items()
        if section in pages_to_render and visible
    }
    # `index` is always rendered (FILTER_PAGES enforcer keeps it in
    # the set even if operator passes --filter audits etc.). Add it
    # to rendered_sections so nav can show the Overview link.
    rendered_sections.add("index")

    # Always render index.
    if "index" in pages_to_render:
        manifest_pages.extend(_render_index(
            env, inv, output_dir,
            watch_mode=watch_mode, dry_run=dry_run,
            rendered_sections=rendered_sections,
        ))

    for section in section_visibility:
        if section in rendered_sections and section != "index":
            manifest_pages.extend(
                _RENDERER_DISPATCH[section](
                    env, inv, output_dir,
                    watch_mode=watch_mode, dry_run=dry_run,
                    rendered_sections=rendered_sections,
                )
            )

    _copy_static_assets(output_dir, dry_run=dry_run)

    manifest = {
        "manifest_version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "workspace": str(workspace),
        "output_dir": str(output_dir),
        "watch_mode": watch_mode,
        "filter_pages": sorted(pages_to_render),
        "pages": manifest_pages,
        "inventory_summary": {
            "a_tables_present": sum(
                1 for p in inv.a_tables.values() if p is not None
            ),
            "audits_present": sum(
                1 for p in inv.audits.values() if p is not None
            ),
            "handoff_packets": sum(
                1 for p in inv.handoff.values() if p is not None
            ),
            "contract_exports": sum(
                1 for files in inv.contracts.values()
                if files.get("spec") is not None
            ),
            "sidecar_diagrams": sum(
                len(files) for files in inv.sidecars.values()
            ),
            "phase7_runs": len(inv.telemetry_runs),
            "phase7_proposals": len(inv.proposals),
        },
    }

    if not quiet:
        s = manifest["inventory_summary"]
        print(
            f"dashboard: wrote {len(manifest_pages)} page(s) to "
            f"{output_dir}\n"
            f"  workspace inventory: "
            f"{s['a_tables_present']} A-tables, "
            f"{s['audits_present']} audits, "
            f"{s['handoff_packets']} handoff packets, "
            f"{s['contract_exports']} contract exports, "
            f"{s['sidecar_diagrams']} sidecar diagrams, "
            f"{s['phase7_runs']} telemetry runs, "
            f"{s['phase7_proposals']} Phase 7 proposals"
        )
        if watch_mode:
            print(
                f"  watch mode: re-rendering on change (poll every "
                f"{WATCH_POLL_INTERVAL_S}s); browser auto-refreshes "
                f"via meta-refresh tag. Ctrl-C to stop."
            )
    return manifest


# ---- Watch mode (polling) ------------------------------------------


def _snapshot_mtimes(
    workspace: Path,
    output_dir: Path,
) -> dict[str, float]:
    """Walk analysis/ subtree and capture per-file mtimes. v1.3.3 R1
    fix #4: exclude any file under the resolved `output_dir` (not a
    hardcoded `dashboard` segment) to avoid the watch loop snapshotting
    its own outputs and re-rendering forever when `--output-dir` is
    overridden."""
    snapshot: dict[str, float] = {}
    analysis_root = workspace / "analysis"
    if not analysis_root.is_dir():
        return snapshot
    output_dir_resolved = output_dir.resolve()
    for path in analysis_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        # Skip files inside the actual output_dir (feedback-loop guard).
        try:
            resolved.relative_to(output_dir_resolved)
            continue
        except ValueError:
            pass
        try:
            snapshot[str(path)] = path.stat().st_mtime
        except OSError:
            continue
    return snapshot


def _watch_loop(
    workspace: Path,
    output_dir: Path,
    *,
    filter_pages: set[str] | None,
    quiet: bool,
) -> int:
    """Poll workspace mtimes; regenerate when any file changes."""
    last_snapshot = _snapshot_mtimes(workspace, output_dir)
    if not quiet:
        print(
            f"dashboard: watching {workspace / 'analysis'} "
            f"(poll every {WATCH_POLL_INTERVAL_S}s, Ctrl-C to stop)"
        )
    try:
        while True:
            time.sleep(WATCH_POLL_INTERVAL_S)
            current_snapshot = _snapshot_mtimes(workspace, output_dir)
            if current_snapshot != last_snapshot:
                changed = sum(
                    1 for k, v in current_snapshot.items()
                    if last_snapshot.get(k) != v
                )
                removed = sum(
                    1 for k in last_snapshot if k not in current_snapshot
                )
                if not quiet:
                    print(
                        f"[{time.strftime('%H:%M:%S')}] regenerating "
                        f"({changed} changed, {removed} removed)"
                    )
                render_dashboard(
                    workspace=workspace,
                    output_dir=output_dir,
                    filter_pages=filter_pages,
                    watch_mode=True,
                    quiet=quiet,
                )
                last_snapshot = current_snapshot
    except KeyboardInterrupt:
        if not quiet:
            print("\ndashboard: watch stopped.")
        return 0


# ---- CLI -----------------------------------------------------------


def _parse_filter(value: str) -> set[str]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    unknown = [p for p in parts if p not in FILTER_PAGES]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown filter page(s): {sorted(unknown)}; "
            f"valid: {sorted(FILTER_PAGES)}"
        )
    return set(parts) | {"index"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "BSA static-HTML dashboard generator (v1.3.3). Read-only "
            "viewer over canonical artifacts + handoff packets + "
            "audits + sidecars + Phase 7 telemetry. NEVER modifies "
            "canonical state."
        ),
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd(),
                        help="BSA workspace root (defaults to cwd).")
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help=(
            f"Override the dashboard output directory (default "
            f"<workspace>/{DEFAULT_OUTPUT_REL}). Implicit-missing "
            f"path is permissive; explicit-missing path is rejected."
        ),
    )
    parser.add_argument(
        "--filter", type=_parse_filter, default=None,
        help=(
            f"Comma-separated subset of pages to render. Valid keys: "
            f"{','.join(sorted(FILTER_PAGES))}. Default: render all. "
            f"`index` is always included."
        ),
    )
    parser.add_argument(
        "--watch", action="store_true",
        help=(
            f"Regenerate on every change in <workspace>/analysis/. "
            f"Polls every {WATCH_POLL_INTERVAL_S}s. Browser "
            f"auto-refreshes via meta-refresh tag. Ctrl-C to stop."
        ),
    )
    parser.add_argument(
        "--print-only", action="store_true",
        help=(
            "Print the page-render manifest as JSON to stdout instead "
            "of writing files."
        ),
    )
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress per-summary log line.")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    workspace = args.workspace.resolve()
    if not (workspace / "analysis").is_dir():
        print(
            f"dashboard: workspace {workspace} has no analysis/ "
            f"subdirectory. Pass --workspace pointing at a BSA "
            f"workspace root.",
            file=sys.stderr,
        )
        return 2

    if args.output_dir is None:
        output_dir = workspace / DEFAULT_OUTPUT_REL
    else:
        output_dir = args.output_dir.resolve()
        if not output_dir.is_dir():
            print(
                f"dashboard: --output-dir {output_dir} does not exist "
                f"or is not a directory. (An implicit workspace-derived "
                f"output dir that doesn't exist yet is permissive; an "
                f"explicit path that doesn't exist is a typo and "
                f"rejected.)",
                file=sys.stderr,
            )
            return 2

    try:
        manifest = render_dashboard(
            workspace=workspace,
            output_dir=output_dir,
            filter_pages=args.filter,
            watch_mode=args.watch,
            # v1.3.3 R1 fix #2: --print-only forces quiet for the
            # human summary so stdout stays valid JSON, AND threads
            # `dry_run=True` so no files get written.
            quiet=args.quiet or args.print_only,
            dry_run=args.print_only,
        )
    except RuntimeError as exc:
        print(f"dashboard: {exc}", file=sys.stderr)
        return 2

    if args.print_only:
        print(json.dumps(manifest, indent=2))
        return 0

    if args.watch:
        return _watch_loop(
            workspace=workspace,
            output_dir=output_dir,
            filter_pages=args.filter,
            quiet=args.quiet,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
