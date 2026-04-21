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

Subcommands (this file, v1.0.4 scope):

    bsa status        Current stage + markers + A51 open counts + audit outputs.
    bsa next          Suggest the next slash-command given current state.

Future (separate commits in the same v1.0.4 release):

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


# ---- Next-step suggester --------------------------------------------

# Per-stage required audit-pass marker set. Mirrors hooks/pre_bash_promote.sh
# so `bsa next` never suggests a /bsa-promote the hook would then block.
# Stage 4 has no audit gate per run-profile-gates.md.
_STAGE_REQUIRED_MARKERS: dict[str, list[str]] = {
    "stage1": ["stage1.excerpts.merged"],
    "stage2": ["stage2.context_state.pass"],
    "stage3": ["stage3.citation_audit.pass"],
    "stage4": [],
    "stage5": ["stage5.anchor_audit.pass"],
    "stage6": ["stage6.anchor_audit.pass"],
    "stage7": ["stage7.skeptical_review.pass"],
    "stage8": ["stage8.no_new_claims.pass"],
    "handoff": ["stage8.no_new_claims.pass"],
    "d1": ["discovery.d1.ready"],
    "d2": ["discovery.d2.claims.merged", "discovery.d2.research_quality.pass"],
    "d3": ["discovery.d3.prioritization.pass"],
    "d4": ["discovery.d4.constraint_audit.pass"],
    "d5": ["discovery.d5.citation_audit.pass", "discovery.d5.no_solution_leakage.pass"],
}


def _collect_marker_ids(ws: WorkspaceState) -> set[str]:
    """Union of all marker_id (or drifted `marker` fallback) values.

    This reads the PAYLOAD. Used for display / debugging only.
    """
    ids: set[str] = set()
    for m in ws.main_markers() + ws.discovery_markers():
        mid = m.get("marker_id") or m.get("marker")
        if isinstance(mid, str) and mid:
            ids.add(mid)
    return ids


def _filenames_in(marker_dir: Path) -> set[str]:
    """Filename stems in one marker directory. Empty set if missing."""
    if not marker_dir.is_dir():
        return set()
    return {path.stem for path in marker_dir.glob("*.json")}


def _collect_marker_filenames(ws: WorkspaceState) -> set[str]:
    """Union of marker filename stems across BOTH ready zones.

    Retained for display and for branches that legitimately span both
    zones (e.g., the bridge marker ``bsa.stage1.entry.enabled`` lives
    in the MAIN zone while the discovery decision markers live in the
    discovery zone — the ``discovery.complete`` branch reads both).
    For per-stage promote-eligibility checks use
    ``_zone_filenames_for_stage(ws, stage)`` instead — it mirrors the
    hook's stage-specific directory lookup.
    """
    return _filenames_in(ws.main_ready) | _filenames_in(ws.discovery_ready)


# Stages whose required-marker set lives in the DISCOVERY zone per
# hooks/pre_bash_promote.sh (stages d1..d5). Every other stage uses
# the main zone.
_DISCOVERY_ZONE_STAGES: frozenset[str] = frozenset({"d1", "d2", "d3", "d4", "d5"})


def _zone_filenames_for_stage(ws: WorkspaceState, stage: str) -> set[str]:
    """Return the filename-stems set the hook would inspect for ``stage``.

    Codex-review round-3 fix: a correctly-named marker placed in the
    wrong zone (e.g., ``discovery.d1.ready.json`` sitting in
    ``analysis/runtime/ready/`` instead of the discovery mirror) must
    not satisfy the CLI's presence check — otherwise ``bsa next``
    green-lights a ``/bsa-promote`` the hook still blocks because the
    hook opens only the stage-specific directory.

    Main-cycle stages (stage1..stage8, handoff) → main zone only.
    Discovery stages (d1..d5) → discovery zone only.
    """
    if stage in _DISCOVERY_ZONE_STAGES:
        return _filenames_in(ws.discovery_ready)
    return _filenames_in(ws.main_ready)


def _d1_has_proposal_output(ws: WorkspaceState) -> bool:
    """True if d1 proposals directory contains actual worker output.

    ``/bsa-start --mode=discovery_then_bsa`` emits
    ``discovery.d1.ready.json`` at init time; that marker alone doesn't
    mean the d1 worker (d0-problem-framer) actually ran. The hook's
    per-stage required-marker table treats the ready marker as
    sufficient for promote, but the documented workflow says the
    operator must first run ``/bsa-stage d1 run``. To distinguish the
    two states without reaching into skill internals, we check whether
    ``analysis/discovery/proposals/d1/`` has any file beyond
    ``.gitkeep`` style placeholders.
    """
    prop_dir = ws.analysis / "discovery" / "proposals" / "d1"
    if not prop_dir.is_dir():
        return False
    for entry in prop_dir.iterdir():
        if entry.name.startswith("."):
            continue  # .gitkeep / hidden files don't count
        if entry.is_file() or (entry.is_dir() and any(entry.iterdir())):
            return True
    return False


def _stage_to_slash_arg(stage: str) -> str:
    """Map A48.CurrentStage → `/bsa-stage <arg>` argument.

    `stage1`..`stage8` → the bare number; `d1`..`d5` → as-is.
    """
    if stage.startswith("stage") and stage[5:].isdigit():
        return stage[5:]
    return stage


def suggest_next(ws: WorkspaceState) -> str:
    """Return a short, actionable next-step recommendation as plain text.

    Decision tree (read-only; never mutates state):

      1. No analysis/ directory → run /bsa-start.
      2. A48 unreadable or missing → reinitialize or inspect the file.
      3. CurrentStage = discovery.complete:
           - main-cycle markers already emitted → point at the current
             main-cycle position (state machine re-entered there)
           - bridge marker present, no main-cycle progress → two-path
             notice (continue vs deliverable)
           - no bridge marker → broken state; refer to /bsa-status
      4. CurrentStage = d1 special case:
           - if proposals/d1/ empty → /bsa-stage d1 run (ready marker
             alone doesn't mean the worker ran)
           - else → /bsa-promote
      5. CurrentStage has a required-marker list:
           - any required marker filename missing → run /bsa-stage <stage> run
           - all required markers present → /bsa-promote (or /bsa-handoff
             when stage8 markers are already promoted).
      6. Stage 4 (no audit gate) → /bsa-promote directly.
      7. CurrentStage = handoff:
           - stage8.no_new_claims.pass missing → go back to stage8
           - handoff.ready present → pipeline complete
           - else → /bsa-handoff

    The required-marker table is shared with hooks/pre_bash_promote.sh
    so `bsa next` never points at a command the hook would block. The
    presence check uses FILENAMES on disk (same as the hook), not
    payload marker_ids, so a misnamed file carrying the expected
    marker_id doesn't produce a false-positive "ready to promote".
    """
    if not ws.is_initialized():
        return (
            "No BSA workspace here yet.\n"
            "Run:\n"
            "  /bsa-start --mode=direct\n"
            "    — for scoped engagements with known sources.\n"
            "  /bsa-start --mode=discovery_then_bsa\n"
            "    — for fuzzy scope / contradicting stakeholders (runs D1-D5 first)."
        )

    stage = ws.current_stage()
    if stage in ("<unknown>", ""):
        return (
            "A48 is missing or unreadable — CurrentStage cannot be determined.\n"
            "  Inspect: analysis/canonical/core_controls/A48_run_context_card.md\n"
            "  If the file is corrupt, the safest recovery is to reinitialize via /bsa-start\n"
            "  in a fresh workspace and re-promote from the last good canonical snapshot."
        )

    # For the ``discovery.complete`` branch below we read BOTH zones
    # because we need to see the bridge marker (main zone) alongside
    # any main-cycle progress markers. For all other stages we use
    # the zone-specific view below at the per-stage checks.
    present_all_zones = _collect_marker_filenames(ws)

    if stage == "discovery.complete":
        has_bridge = "bsa.stage1.entry.enabled" in present_all_zones
        # A main-cycle stage marker means the operator has moved past
        # the bridge gate, even if A48 hasn't been re-written yet.
        has_main_progress = any(m.startswith("stage") for m in present_all_zones)
        if has_main_progress:
            # Find the furthest main-cycle marker present and suggest
            # the next step after it.
            return (
                "A48.CurrentStage=discovery.complete but main-cycle markers are present.\n"
                "The orchestrator is likely in the middle of Stage 1-8 but A48 has not\n"
                "been re-written yet (normal during first-stage promote).\n"
                "  Run: /bsa-status   (inspect the current marker set)\n"
                "  Then: /bsa-promote (if stage1.excerpts.merged is present) or\n"
                "        /bsa-stage 1 run  (if Stage 1 worker has not run yet)."
            )
        if has_bridge:
            return (
                "Discovery complete; bridge marker emitted but main cycle not started.\n"
                "Two valid paths:\n"
                "  (a) Continue to main cycle:\n"
                "        /bsa-stage 1 run\n"
                "  (b) Treat as discovery-only deliverable.\n"
                "      The artifacts under analysis/discovery/canonical/ +\n"
                "      analysis/canonical/core_controls/ are the deliverable; no\n"
                "      further command needed. /bsa-handoff refuses until Stage 1\n"
                "      has been promoted."
            )
        # Without bridge and without main-cycle progress, the workspace
        # is in an inconsistent state — discovery exit was declared but
        # the bridge-marker emission never happened.
        return (
            "A48.CurrentStage=discovery.complete but the bridge marker\n"
            "(bsa.stage1.entry.enabled) is NOT present. Two possibilities:\n"
            "  - discovery.exit did not fire with verdict=GO (inspect\n"
            "    analysis/discovery/runtime/ready/discovery.go.json)\n"
            "  - the bridge marker was rejected by the write hook; check\n"
            "    recent Claude Code stderr for a BLOCKED diagnostic.\n"
            "Safe next step:\n"
            "  /bsa-status   (shows the full marker set + last-promote verdict)"
        )

    required = _STAGE_REQUIRED_MARKERS.get(stage)
    if required is None:
        return (
            f"CurrentStage={stage!r} is not a recognized stage identifier.\n"
            "Valid values: stage1..stage8, handoff, d1..d5, discovery.complete.\n"
            "Inspect analysis/canonical/core_controls/A48_run_context_card.md."
        )

    # Zone-aware presence check: the hook's filename-presence gate
    # only inspects the zone matching the current stage. A correctly-
    # named marker in the wrong zone would NOT satisfy the hook, so
    # it doesn't satisfy bsa next either.
    present_in_zone = _zone_filenames_for_stage(ws, stage)

    # d1 special case: `discovery.d1.ready` is emitted by /bsa-start,
    # not by the d1 worker. Presence alone does NOT mean the worker ran.
    # Distinguish init-state from post-worker-state by peeking at
    # proposals/d1/.
    if stage == "d1" and not _d1_has_proposal_output(ws):
        return (
            "Discovery mode just initialized. `discovery.d1.ready` is emitted\n"
            "by /bsa-start itself; the d0-problem-framer worker has not run\n"
            "yet (no output in analysis/discovery/proposals/d1/).\n"
            "Run:\n"
            "  /bsa-stage d1 run"
        )

    # handoff special case before the generic path — we don't want the
    # missing-marker branch to suggest "/bsa-stage handoff run" (no such
    # command).
    if stage == "handoff":
        if "stage8.no_new_claims.pass" not in present_in_zone:
            return (
                "CurrentStage=handoff but stage8.no_new_claims.pass is NOT present.\n"
                "Stage 8 must promote before handoff. Run:\n"
                "  /bsa-stage 8 run   (re-runs Stage 8 audit chain if needed)\n"
                "  /bsa-promote       (promotes Stage 8 canonical)\n"
                "Then /bsa-handoff."
            )
        if "handoff.ready" in present_in_zone:
            return (
                "handoff.ready marker present — pipeline complete.\n"
                "Artifacts: analysis/handoff/H1..H4 + handoff_manifest.json.\n"
                "Next: paste handoff pack into your delivery channel, or run\n"
                "/bsa-status for the final workspace summary."
            )
        return (
            "Stage 8 promoted; ready to emit H1-H4:\n"
            "  /bsa-handoff"
        )

    if not required:
        # Stage 4 path — no audit gate.
        return (
            f"Stage {stage} has no audit gate. Ready to promote:\n"
            "  /bsa-promote\n"
            "(/bsa-promote --dry-run first to preview the planned writes.)"
        )

    missing = [m for m in required if m not in present_in_zone]
    if missing:
        slash_arg = _stage_to_slash_arg(stage)
        stage_label = f"stage {slash_arg}" if stage.startswith("stage") else f"discovery {stage}"
        missing_display = ", ".join(missing)
        return (
            f"Stage {stage} is in progress. Missing required audit marker(s): {missing_display}.\n"
            f"Run the stage (emits the marker after its audit chain):\n"
            f"  /bsa-stage {slash_arg} run\n"
            f"Or re-run a specific audit if the stage already emitted most markers:\n"
            f"  /bsa-audit <kind>   (see commands/bsa-audit.md for kinds available at {stage_label})"
        )

    # All required markers present (and not d1/handoff which were handled above).
    if stage == "stage8":
        return (
            "Stage 8 gating marker present (stage8.no_new_claims.pass). Ready for handoff:\n"
            "  /bsa-promote      (promotes Stage 8 canonical if not already done)\n"
            "  /bsa-handoff      (emits H1-H4 packets + manifest)\n"
            "Run them in that order. /bsa-handoff refuses if stage8 canonical isn't promoted."
        )
    return (
        f"All {stage} audit markers present. Ready to promote:\n"
        "  /bsa-promote --dry-run    (preview)\n"
        "  /bsa-promote              (apply)\n"
        "After promote, A48.CurrentStage advances; re-run `bsa next` for the next step."
    )


def cmd_next(args: argparse.Namespace) -> int:
    """Print the suggested next slash-command."""
    root = Path(args.workspace).resolve()
    ws = WorkspaceState(root)
    print(suggest_next(ws))
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

    p_next = subparsers.add_parser(
        "next",
        help="Suggest the next slash-command given the current workspace state.",
    )
    p_next.set_defaults(func=cmd_next)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
