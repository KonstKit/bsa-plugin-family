#!/usr/bin/env python3
"""BSA workspace CLI — UX wrapper around the plugin's slash-commands.

The plugin's normal invocation path is Claude Code slash-commands
(`/bsa-start`, `/bsa-stage`, `/bsa-promote`, `/bsa-audit`,
`/bsa-handoff`, `/bsa-status`). That surface is LLM-friendly (the
orchestrator skill reads the command markdown and drives the worker
chain) but shell-unfriendly: state sits across five directories
(``runtime/ready/``, ``canonical/``, ``proposals/``, ``handoff/``,
``views/``); recovering from a hook-blocked write requires reading
stderr + re-checking markers + replaying commands; onboarding a new
engagement means remembering "what's the next command given this
state?".

This CLI is the shell-friendly side. It does NOT replace the
slash-commands — it READS the workspace state and tells you where
you are + what to do next. All actual state mutation still goes
through the orchestrator skill via slash-commands.

Subcommands (this file, v1.0.4 minimal-viable scope):

    bsa status        Current stage + markers + A51 open counts + audit outputs.

Future sprints (Phase 2 of the UX pass):

    bsa next          Suggest the next slash-command given current state.
    bsa doctor        Run all validators (marker chain + reconciliation +
                      no-new-stories + privacy) and aggregate findings.
    bsa materials <src-dir>
                      Convert PDF/DOCX inputs to MD/txt, stage under
                      analysis/proposals/stage1/inputs/ with a draft A50.

Stdlib-only at module level. Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from governance.schemas import loader as _schema_loader  # noqa: E402


# ---- Workspace-state reader ------------------------------------------


class WorkspaceState:
    """Collects and exposes the BSA workspace state as a read-only snapshot.

    The workspace root is the directory containing ``analysis/``. All
    readers degrade gracefully when files are absent — the CLI can be
    run against pre-start, mid-pipeline, and post-handoff workspaces
    and always returns a sensible structure.
    """

    def __init__(self, root: Path):
        self.root = root
        self.analysis = root / "analysis"
        self.core_controls = self.analysis / "canonical" / "core_controls"
        self.discovery_core_controls = self.analysis / "discovery" / "canonical" / "core_controls"
        self.main_ready = self.analysis / "runtime" / "ready"
        self.discovery_ready = self.analysis / "discovery" / "runtime" / "ready"
        self.handoff_dir = self.analysis / "handoff"

    # ---- Existence checks --------------------------------------------

    def is_initialized(self) -> bool:
        """True if /bsa-start has run — analysis/ dir exists."""
        return self.analysis.is_dir()

    # ---- A48 reader --------------------------------------------------

    def a48_fields(self) -> dict[str, str]:
        """Parse A48 via the schema loader; return empty dict if missing."""
        a48 = self.core_controls / "A48_run_context_card.md"
        if not a48.is_file():
            return {}
        try:
            return _schema_loader.parse_a48(a48)
        except Exception:
            return {}

    def current_stage(self) -> str:
        return self.a48_fields().get("CurrentStage", "<unknown>")

    def run_id(self) -> str:
        return self.a48_fields().get("RunID", "<unknown>")

    def mode(self) -> str:
        return self.a48_fields().get("Mode", "<unknown>")

    def canon_policy_version(self) -> str:
        return self.a48_fields().get("CanonPolicyVersion", "<unknown>")

    # ---- Marker readers ---------------------------------------------

    def _read_markers_in(self, marker_dir: Path) -> list[dict]:
        if not marker_dir.is_dir():
            return []
        result: list[dict] = []
        for path in sorted(marker_dir.glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(doc, dict):
                continue
            doc.setdefault("_source_file", path.name)
            result.append(doc)
        return result

    def main_markers(self) -> list[dict]:
        return self._read_markers_in(self.main_ready)

    def discovery_markers(self) -> list[dict]:
        return self._read_markers_in(self.discovery_ready)

    @staticmethod
    def _marker_timestamp(m: dict) -> Optional[str]:
        """Return the marker's emission timestamp, tolerating drift.

        Canonical field is ``timestamp`` (ISO-8601 UTC per marker schema).
        Sysco-style drifted markers use ``emittedAt`` — we accept either
        so recency sorting stays correct even on non-conformant workspaces
        (the user's reason for needing this CLI in the first place).
        """
        ts = m.get("timestamp") or m.get("emittedAt")
        return ts if isinstance(ts, str) and ts else None

    def last_marker(self) -> Optional[dict]:
        """Return the most-recent marker by timestamp across both zones.

        Falls back to sort-order on filename if timestamps are absent.
        """
        all_markers = self.main_markers() + self.discovery_markers()
        if not all_markers:
            return None
        dated = [m for m in all_markers if self._marker_timestamp(m)]
        if dated:
            return max(dated, key=lambda m: self._marker_timestamp(m) or "")
        return all_markers[-1]

    # ---- A51 counters -----------------------------------------------

    def a51_counts(self) -> dict[str, int]:
        """Return counts of A51 rows by BlockingStatus. Zero for missing file."""
        a51 = self.core_controls / "A51_issue_route_register.csv"
        if not a51.is_file():
            return {"total": 0, "hard": 0, "soft": 0, "informational": 0, "open": 0}
        counts = {"total": 0, "hard": 0, "soft": 0, "informational": 0, "open": 0}
        try:
            for row in _schema_loader.iter_csv_rows(a51):
                counts["total"] += 1
                blocking = (row.get("BlockingStatus") or "").strip()
                if blocking in counts:
                    counts[blocking] += 1
                if (row.get("ResolutionStatus") or "").strip() == "open":
                    counts["open"] += 1
        except Exception:
            # Malformed CSV — return a visible signal to the caller rather
            # than silently reporting zeros.
            counts["total"] = -1
        return counts

    # ---- Audit-output presence check --------------------------------

    def audit_outputs(self) -> dict[str, bool]:
        """Check which audit reports have been written (presence only).

        Audit reports land under ``analysis/canonical/stage<N>/`` once
        the stage has been promoted. The presence of the file signals
        the audit has completed + been promoted; the content is
        separate (not read here — keeps the reader O(1) per audit).
        """
        # Mapping: audit name → file path relative to self.analysis.
        # Report filenames pinned by the auditor contract
        # (see skills/bsa-no-new-claims-auditor/references/no-new-claims-contract.md
        # and the migrate_v0_9_to_v1_0 test suite for the other auditors).
        candidates = {
            "citation": "canonical/stage3/citation_audit_report.md",
            "consistency": "canonical/stage3/consistency_audit_report.md",
            "skeptical": "canonical/stage7/skeptical_review_report.md",
            "no_new_claims": "canonical/stage8/no_new_claims_report.md",
            "anchor_stage5": "canonical/stage5/anchor_audit_report.md",
            "anchor_stage6": "canonical/stage6/anchor_audit_report.md",
        }
        return {
            name: (self.analysis / rel).is_file() for name, rel in candidates.items()
        }

    # ---- Canon hash match -------------------------------------------

    def canon_hash_match(self) -> Optional[str]:
        """Compare workspace CanonPolicyVersion vs repo hash. Returns:

        * ``"MATCH"`` — workspace hash equals current repo hash
        * ``"DRIFT"`` — they differ (workspace pre-dates a policy bump
          OR was produced by a different plugin version)
        * ``"UNKNOWN"`` — workspace hash not in semver+hash form
        * ``None`` — workspace not initialized / no A48 hash field
        """
        ver = self.canon_policy_version()
        if "+hash:" not in ver:
            return None if ver == "<unknown>" else "UNKNOWN"
        workspace_hash = ver.split("+hash:", 1)[1]
        try:
            from scripts.compute_canon_hash import compute_canon_hash  # type: ignore
            repo_hash = compute_canon_hash()
        except Exception:
            # Lazy fallback: read cached value from plugin.json.
            plugin_json = _REPO_ROOT / ".claude-plugin" / "plugin.json"
            if not plugin_json.is_file():
                return "UNKNOWN"
            try:
                cfg = json.loads(plugin_json.read_text(encoding="utf-8"))
                repo_hash = cfg.get("canonPolicyVersion", {}).get("hash_full", "")
            except (json.JSONDecodeError, UnicodeDecodeError):
                return "UNKNOWN"
        return "MATCH" if workspace_hash.startswith(repo_hash[: len(workspace_hash)]) else "DRIFT"


# ---- Status command formatter ---------------------------------------


def _format_markers(markers: list[dict], zone_label: str) -> str:
    if not markers:
        return f"  {zone_label}: (none)"
    lines = [f"  {zone_label}:"]
    for m in markers:
        mid = m.get("marker_id") or m.get("marker") or m.get("_source_file", "?")
        verdict = m.get("verdict", "?")
        ts = m.get("timestamp") or m.get("emittedAt", "")
        lines.append(f"    - {mid} ({verdict}){(' @ ' + ts) if ts else ''}")
    return "\n".join(lines)


def cmd_status(args: argparse.Namespace) -> int:
    """Print a compact workspace state summary."""
    root = Path(args.workspace).resolve()
    ws = WorkspaceState(root)

    if not ws.is_initialized():
        sys.stderr.write(
            f"[bsa status] {root} is not a BSA workspace (no analysis/ directory).\n"
            "Run /bsa-start in Claude Code from this directory to initialize.\n"
        )
        return 2

    a48 = ws.a48_fields()
    last = ws.last_marker()
    main_m = ws.main_markers()
    disc_m = ws.discovery_markers()
    a51 = ws.a51_counts()
    audits = ws.audit_outputs()
    hash_state = ws.canon_hash_match()

    print(f"BSA workspace: {root}")
    print(f"Run ID:       {ws.run_id()}")
    print(f"Mode:         {ws.mode()}")
    print(f"Current stage: {ws.current_stage()}")
    print(f"Canon policy: {ws.canon_policy_version()}"
          + (f" [{hash_state}]" if hash_state else ""))
    print()

    if last:
        last_mid = last.get("marker_id") or last.get("marker") or "?"
        last_verdict = last.get("verdict", "?")
        last_ts = last.get("timestamp") or last.get("emittedAt", "")
        print(f"Last marker:  {last_mid} ({last_verdict}){(' @ ' + last_ts) if last_ts else ''}")
    else:
        print("Last marker:  (none)")
    print()

    print("Markers in runtime/ready/:")
    print(_format_markers(main_m, "main"))
    print(_format_markers(disc_m, "discovery"))
    print()

    if a51["total"] == -1:
        print("Open A51 items: <malformed A51 CSV — run `bsa doctor` for details>")
    else:
        print(f"Open A51 items:    {a51['open']} (of {a51['total']} total)")
        print(f"  hard blockers:   {a51['hard']}")
        print(f"  soft:            {a51['soft']}")
        print(f"  informational:   {a51['informational']}")
    print()

    print("Audit-report presence:")
    for name, present in audits.items():
        marker = "PRESENT" if present else "(not yet)"
        print(f"  {name:<20} {marker}")

    return 0


# ---- Main dispatcher ------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="bsa",
        description=(
            "BSA workspace CLI — shell-friendly view of plugin state. "
            "Read-only; does not mutate canonical state. "
            "Use Claude Code slash-commands (/bsa-start, /bsa-stage, etc.) "
            "for state-changing operations."
        ),
    )
    parser.add_argument(
        "--workspace", "-w",
        default=".",
        help="Path to the BSA workspace root (default: current directory).",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    p_status = subparsers.add_parser(
        "status",
        help="Show current workspace state (stage, markers, A51 counts, audits).",
    )
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
