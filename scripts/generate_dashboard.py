#!/usr/bin/env python3
"""BSA static-HTML dashboard generator (v1.3.3 — WIP).

Read-only viewer over canonical artifacts + handoff packets + audit
reports + sidecar diagrams + Phase 7 telemetry. Generates static HTML
under `<workspace>/analysis/handoff/dashboard/` (operator-side, NEVER
canonical). Operator opens `dashboard/index.html` in any browser; no
HTTP server, no backend, no canonical writes.

Day 1 scope (this file): CLI surface + skeleton + index page. Subsequent
days flesh out per-artifact pages, audit dashboards, handoff renderers,
contract viewers, sidecar embeds, Phase 7 proposal diff viewer.

Pattern lineage: operator-runner family (v1.2.4 telemetry collector →
v1.2.16 freshness → v1.2.17 triangulation → v1.2.18 miner → v1.2.19
patcher → v1.3.0/1/2 contract exporters → v1.3.3 dashboard).
Stdlib + jinja2 + markdown-it-py. Defensive reads. Atomic writes via
tempfile + os.replace. Operator-invoked. NEVER runs git/commit/push,
NEVER edits canonical state, NEVER modifies source files.

CLI:
  python3 scripts/generate_dashboard.py --workspace <path>
  python3 scripts/generate_dashboard.py --workspace <path> --output-dir <dir>
  python3 scripts/generate_dashboard.py --workspace <path> --filter audits,proposals
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

SCRIPT_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = SCRIPT_DIR / "dashboard"
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"

# Add scripts/ to sys.path so `dashboard` package imports cleanly when
# running from arbitrary cwd.
sys.path.insert(0, str(SCRIPT_DIR))

from dashboard import loaders  # noqa: E402

DEFAULT_OUTPUT_REL = "analysis/handoff/dashboard"
DEFAULT_INDEX_FILENAME = "index.html"
WATCH_POLL_INTERVAL_S = 2.0

# A-table human labels for the index counter grid.
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

# Filter keys recognized by --filter. Empty selector = render everything.
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


# ---- Inventory → template-context shaping --------------------------


def _detect_pipeline_stages(inv: loaders.Inventory) -> list[dict]:
    """Group canonical artifacts by stage via path-substring inspection.
    Returns a list of {name, status, detail} dicts for the index page.

    Status convention: 'present' = any artifact found; 'absent' = none.
    'partial' is reserved for future when we know the stage's full
    expected set per orchestrator workflow contract.
    """
    stages: dict[str, dict[str, int]] = {}
    for a_id, path in inv.a_tables.items():
        if path is None:
            continue
        # Walk up to find a parent matching stage pattern.
        for parent in path.parents:
            name = parent.name
            if name in {"core_controls", "stage1", "stage2", "stage3",
                        "stage4", "stage5", "stage6", "stage7", "stage8"}:
                stages.setdefault(name, {"count": 0})["count"] += 1
                break

    ordering = ("core_controls", "stage1", "stage2", "stage3", "stage4",
                "stage5", "stage6", "stage7", "stage8")
    out: list[dict] = []
    for stage_name in ordering:
        if stage_name in stages:
            count = stages[stage_name]["count"]
            out.append({
                "name": stage_name.replace("_", " "),
                "status": "present",
                "detail": f"{count} artifact{'s' if count != 1 else ''}",
            })
    return out


def _build_index_context(inv: loaders.Inventory) -> dict:
    """Shape the Inventory into the template variables for index.html."""
    pipeline_stages = _detect_pipeline_stages(inv)

    a_table_counts = []
    for a_id, path in inv.a_tables.items():
        a_table_counts.append({
            "id": a_id,
            "label": A_TABLE_LABELS.get(a_id, a_id),
            "count": loaders.count_rows(path) if path else 0,
        })

    audit_verdicts = []
    for audit_id, path in inv.audits.items():
        if path is None:
            continue
        audit_verdicts.append({
            "id": audit_id,
            "label": AUDIT_LABELS.get(audit_id, audit_id),
            "verdict": loaders.detect_audit_verdict(path),
        })

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
        {
            "id": fmt,
            "label": SIDECAR_LABELS.get(fmt, fmt),
            "count": len(files),
        }
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
        "pipeline_stages": pipeline_stages,
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
    root_prefix: str = "",
    static_prefix: str = "static/",
) -> dict:
    """Common context for base.html (nav + header)."""
    return {
        "workspace_path": str(inv.workspace),
        "workspace_name": inv.workspace.name or "(workspace)",
        "active_page": active_page,
        "watch_mode": watch_mode,
        "root_prefix": root_prefix,
        "static_prefix": static_prefix,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "has_artifacts": any(p is not None for p in inv.a_tables.values()),
        "has_audits": any(p is not None for p in inv.audits.values()),
        "has_handoff": any(p is not None for p in inv.handoff.values()),
        "has_contracts": any(
            files.get("spec") is not None for files in inv.contracts.values()
        ),
        "has_sidecars": any(files for files in inv.sidecars.values()),
        "has_phase7": bool(inv.telemetry_runs or inv.proposals),
    }


# ---- Rendering -----------------------------------------------------


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


def _copy_static_assets(output_dir: Path) -> None:
    """Copy bundled CSS + JS into output_dir/static/. Idempotent."""
    target = output_dir / "static"
    target.mkdir(parents=True, exist_ok=True)
    for asset in STATIC_DIR.iterdir():
        if asset.is_file():
            shutil.copy2(asset, target / asset.name)


def render_dashboard(
    workspace: Path,
    output_dir: Path,
    *,
    filter_pages: set[str] | None,
    watch_mode: bool,
    quiet: bool,
) -> dict:
    """Generate the full dashboard HTML bundle. Returns a manifest dict
    listing every page emitted (consumed by --print-only and tests)."""
    env = _make_jinja_env()
    inv = loaders.discover(workspace)

    pages_to_render = filter_pages or set(FILTER_PAGES)
    manifest_pages: list[dict] = []

    # ---- index.html (always rendered if "index" requested) ----
    if "index" in pages_to_render:
        base_ctx = _build_base_context(
            inv, active_page="index", watch_mode=watch_mode,
        )
        index_ctx = _build_index_context(inv)
        ctx = {**base_ctx, **index_ctx}
        html = env.get_template("index.html").render(**ctx)
        target = output_dir / DEFAULT_INDEX_FILENAME
        _atomic_write(target, html)
        manifest_pages.append({
            "page": "index",
            "path": str(target.relative_to(output_dir)),
        })

    # Day 1 stops here. Days 2-5 add: artifacts/*, audits/*, handoff/*,
    # contracts/*, sidecars/*, phase7/*.

    _copy_static_assets(output_dir)

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
        summary = manifest["inventory_summary"]
        print(
            f"dashboard: wrote {len(manifest_pages)} page(s) to "
            f"{output_dir}\n"
            f"  workspace inventory: "
            f"{summary['a_tables_present']} A-tables, "
            f"{summary['audits_present']} audits, "
            f"{summary['handoff_packets']} handoff packets, "
            f"{summary['contract_exports']} contract exports, "
            f"{summary['sidecar_diagrams']} sidecar diagrams, "
            f"{summary['phase7_runs']} telemetry runs, "
            f"{summary['phase7_proposals']} Phase 7 proposals"
        )
        if watch_mode:
            print(
                f"  watch mode: re-rendering on change (poll every "
                f"{WATCH_POLL_INTERVAL_S}s); browser auto-refreshes via "
                f"meta-refresh tag. Ctrl-C to stop."
            )
    return manifest


# ---- Watch mode (polling) ------------------------------------------


def _snapshot_mtimes(workspace: Path) -> dict[str, float]:
    """Walk analysis/ subtree and capture per-file mtimes. Cheap enough
    for typical BSA workspaces (~hundreds of files)."""
    snapshot: dict[str, float] = {}
    analysis_root = workspace / "analysis"
    if not analysis_root.is_dir():
        return snapshot
    for path in analysis_root.rglob("*"):
        if path.is_file():
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
    """Poll workspace mtimes; regenerate when any file changes. Blocks
    until Ctrl-C."""
    last_snapshot = _snapshot_mtimes(workspace)
    if not quiet:
        print(
            f"dashboard: watching {workspace / 'analysis'} "
            f"(poll every {WATCH_POLL_INTERVAL_S}s, Ctrl-C to stop)"
        )
    try:
        while True:
            time.sleep(WATCH_POLL_INTERVAL_S)
            current_snapshot = _snapshot_mtimes(workspace)
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
    """Parse comma-separated --filter value. Validate against
    FILTER_PAGES."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    unknown = [p for p in parts if p not in FILTER_PAGES]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown filter page(s): {sorted(unknown)}; "
            f"valid: {sorted(FILTER_PAGES)}"
        )
    # Always include 'index' so navigation works.
    return set(parts) | {"index"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "BSA static-HTML dashboard generator (v1.3.3 — WIP). "
            "Read-only viewer over canonical artifacts + handoff "
            "packets + audits + sidecars + Phase 7 telemetry. NEVER "
            "modifies canonical state."
        ),
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="BSA workspace root (defaults to cwd).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            f"Override the dashboard output directory (default "
            f"<workspace>/{DEFAULT_OUTPUT_REL}). Implicit-missing path "
            f"is permissive (created on demand); explicit-missing "
            f"path is rejected (operator typo defense, mirrors "
            f"v1.3.x exporter convention)."
        ),
    )
    parser.add_argument(
        "--filter",
        type=_parse_filter,
        default=None,
        help=(
            f"Comma-separated subset of pages to render. Valid keys: "
            f"{','.join(sorted(FILTER_PAGES))}. Default: render all. "
            f"`index` is always included."
        ),
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help=(
            f"Regenerate on every filesystem change in <workspace>/"
            f"analysis/. Polls every {WATCH_POLL_INTERVAL_S}s. Browser "
            f"auto-refreshes via injected meta-refresh tag. Ctrl-C to "
            f"stop."
        ),
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help=(
            "Print the page-render manifest as JSON to stdout instead "
            "of writing files."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-summary log line.",
    )
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
            quiet=args.quiet,
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
