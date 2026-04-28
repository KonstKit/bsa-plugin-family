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
    bsa doctor        Compose all repo validators against the workspace +
                      walk every canonical artifact through the F5 write-
                      validator. Single green/red signal before /bsa-promote.
    bsa materials <src-dir>
                      Convert PDF/DOCX/MD/TXT under <src-dir> into MD
                      files staged under analysis/proposals/stage1/
                      inputs/source_NNN_<slug>.md, plus a DRAFT
                      source_manifest.csv with ReliabilityTier=T5
                      defaults that the user must re-tag during
                      /bsa-stage 1. Default is dry-run; pass --commit
                      to actually write. PDF/DOCX support requires
                      pypdf / python-docx (optional install).

Stdlib-only at module level (PDF/DOCX libs imported lazily inside
the materials subcommand). Python 3.9+.
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

# v1.3.11 — god-module decomposition (closes review finding #4 for
# bsa_cli.py). The materials subcommand (cmd_materials + ~20 helpers
# + 4 classes + canonical-A50 column-order constants) lives in
# `_bsa_cli_materials.py` now. Re-exported here so the dispatcher in
# `main()` below + tests that import via the historical
# `from scripts.bsa_cli import <name>` path continue to work without
# modification. cmd_materials lazy-imports `WorkspaceState` from THIS
# module to avoid a module-load-time circular dep.
from scripts._bsa_cli_materials import (  # noqa: E402, F401  (re-exports)
    ConversionFailed,
    ConversionUnavailable,
    ManifestHeaderDrift,
    SourcePlan,
    _A50_HEADER,
    _A50_HEADER_WITH_EFFECTIVE_DATE,
    _atomic_write_text,
    _bytes_human,
    _check_write_containment,
    _classify,
    _convert_docx,
    _convert_one,
    _convert_pdf,
    _count_kinds,
    _csv_escape,
    _existing_origins,
    _next_source_id,
    _next_unique_slug,
    _plan_conversions,
    _read_staged_provenance,
    _read_text,
    _render_draft_manifest,
    _scan_source_dir,
    _slugify,
    _today_iso,
    _upsert_draft_manifest,
    cmd_materials,
)


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
        Pilot-1-class drifted markers use ``emittedAt`` — we accept either
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
            # Lazy fallback: read cached value. v1.3.6: canon block
            # lives in .claude-plugin/canon_policy.json (extracted
            # from plugin.json). Read the new location first, fall
            # back to legacy plugin.json::canonPolicyVersion for one-
            # version compat. Return UNKNOWN if neither file readable
            # — pre-v1.3.6 the empty-string fallback would silently
            # MATCH (workspace_hash.startswith("") is always True),
            # masking real drift.
            canon_json = _REPO_ROOT / ".claude-plugin" / "canon_policy.json"
            plugin_json = _REPO_ROOT / ".claude-plugin" / "plugin.json"
            repo_hash = ""
            if canon_json.is_file():
                try:
                    cfg = json.loads(canon_json.read_text(encoding="utf-8"))
                    repo_hash = cfg.get("hash_full", "") or ""
                except (json.JSONDecodeError, UnicodeDecodeError):
                    repo_hash = ""
            if not repo_hash and plugin_json.is_file():
                try:
                    cfg = json.loads(plugin_json.read_text(encoding="utf-8"))
                    repo_hash = (
                        cfg.get("canonPolicyVersion", {}).get("hash_full", "")
                        or ""
                    )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    repo_hash = ""
            if not repo_hash:
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


# ---- Doctor: compose all validators ---------------------------------

import os  # noqa: E402  (lazy — only used by cmd_doctor)
import subprocess  # noqa: E402  (lazy — only used by cmd_doctor)


def _run_subprocess_validator(
    plugin_repo: Path, script_rel: str, *args: str
) -> tuple[int, str]:
    """Run a repo validator script in a subprocess; capture both streams.

    Returns (exit_code, combined_text). The validators we orchestrate
    are inconsistent about channels: validate_marker_chain emits per-
    finding detail on stderr and a PASS line on stdout; privacy_scan
    emits a one-line FAIL banner on stderr and the human summary on
    stdout. Concatenate both so we never drop actionable detail — the
    per-stream labels help readers disambiguate noisy output.
    """
    cmd = [sys.executable, str(plugin_repo / script_rel), *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        return 2, f"failed to invoke {script_rel}: {exc}"
    parts: list[str] = []
    if result.stderr.strip():
        parts.append(result.stderr.strip())
    if result.stdout.strip():
        parts.append(result.stdout.strip())
    combined = "\n".join(parts)
    return result.returncode, combined


def _iter_workspace_canonical_files(
    ws: WorkspaceState, strict: bool = False
) -> list[Path]:
    """Yield every canonical-surface file the F5 hook would gate.

    Mirrors the dispatcher patterns in
    governance/schemas/write_validator.py — same paths, glob-walked
    on disk.

    `strict=False` (legacy/default): silently return [] if analysis/
    is missing — convenient for callers that only care about the
    file list and not whether the workspace is intact.
    `strict=True`: raise FileNotFoundError if analysis/ is missing.
    Used by cmd_doctor to distinguish "no canonical files yet" from
    "workspace tree disappeared mid-run" (the second case must
    promote to an ERROR exit; without `strict`, the two states are
    indistinguishable to the caller and we can't avoid a false-clean
    race).
    """
    files: list[Path] = []
    if not ws.analysis.is_dir():
        if strict:
            raise FileNotFoundError(
                f"analysis/ directory missing at {ws.root}"
            )
        return files
    # Markers (main + discovery zones).
    for d in (ws.main_ready, ws.discovery_ready):
        if d.is_dir():
            files.extend(sorted(d.glob("*.json")))
    # Core controls (main + discovery).
    for core in (ws.core_controls, ws.discovery_core_controls):
        if not core.is_dir():
            continue
        files.extend(sorted(core.glob("A48_*.md")))
        for prefix in ("A50_", "A51_", "A58_", "A59_", "A60_", "A62_", "A70_"):
            files.extend(sorted(core.glob(f"{prefix}*.csv")))
    return files


def _validate_one_file(plugin_repo: Path, ws_root: Path, file_path: Path) -> tuple[int, str]:
    """Run governance.schemas.write_validator on one file via the CLI.

    Returns (exit_code, stderr). Exit 0 = pass; 1 = blocked; 2 =
    invocation error. The CLI already emits structured stderr we
    can surface verbatim.
    """
    # The validator wants the path RELATIVE to the workspace root in
    # its dispatcher regex — not the absolute path. Use the workspace-
    # relative form so the dispatcher regex matches as it would at
    # hook time.
    try:
        rel = file_path.relative_to(ws_root).as_posix()
    except ValueError:
        rel = file_path.as_posix()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "governance.schemas.write_validator", rel],
            input=file_path.read_text(encoding="utf-8", errors="replace"),
            capture_output=True,
            text=True,
            cwd=plugin_repo,
            check=False,
        )
    except OSError as exc:
        return 2, f"failed to invoke write_validator: {exc}"
    return proc.returncode, proc.stderr.strip()


def _indent_detail(out: str) -> str:
    """Indent per-line detail under a section header; handle empty."""
    lines = [ln for ln in out.splitlines() if ln]
    return "\n".join(f"      {ln}" for ln in lines) or "      <no detail>"


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run the full validator suite + content walk; print summary.

    Exit codes:
        0 = ALL CLEAN (no findings, no invocation errors).
        1 = at least one validator reported findings (workspace issue).
        2 = at least one validator could not be invoked (environment
            error — e.g., missing script, python abort). Distinct from
            exit 1 so CI / on-call can distinguish "workspace dirty"
            from "doctor itself broken".
    """
    root = Path(args.workspace).resolve()
    ws = WorkspaceState(root)

    if not ws.is_initialized():
        sys.stderr.write(
            f"[bsa doctor] {root} is not a BSA workspace (no analysis/ directory).\n"
            "Run /bsa-start in Claude Code to initialize.\n"
        )
        return 2

    plugin_repo = _REPO_ROOT
    findings_count = 0   # rc == 1 events (workspace-level issues)
    error_count = 0      # rc == 2 events (invocation / environment)
    sections: list[str] = []

    def _section(label: str, rc: int, out: str) -> None:
        """Render one validator section. rc 0 → OK, 1 → FAIL, 2 → ERROR."""
        nonlocal findings_count, error_count
        if rc == 0:
            sections.append(f"  {label}: OK")
        elif rc == 2:
            error_count += 1
            sections.append(f"  {label}: ERROR (validator invocation failed)\n"
                            + _indent_detail(out))
        else:
            findings_count += 1
            sections.append(f"  {label}: FAIL\n" + _indent_detail(out))

    # 1. Marker-chain validator (main + discovery zones).
    for label, zone_dir in (("main", ws.main_ready), ("discovery", ws.discovery_ready)):
        if not zone_dir.is_dir():
            sections.append(f"  marker chain ({label}): SKIP (zone directory absent)")
            continue
        rc, out = _run_subprocess_validator(
            plugin_repo, "scripts/validate_marker_chain.py", str(zone_dir)
        )
        _section(f"marker chain ({label})", rc, out)

    # 2. A51 reconciliation auditor.
    rc, out = _run_subprocess_validator(
        plugin_repo, "scripts/validate_a51_reconciliation.py", str(root)
    )
    _section("A51 reconciliation", rc, out)

    # 3. No-new-stories auditor (only meaningful when A70 exists).
    a70 = ws.core_controls / "A70_story_register.csv"
    if a70.is_file():
        rc, out = _run_subprocess_validator(
            plugin_repo, "scripts/validate_no_new_stories.py", str(root)
        )
        _section("no-new-stories", rc, out)
    else:
        sections.append("  no-new-stories: SKIP (no A70 yet — Phase 3 not run)")

    # 4. Privacy scan.
    #
    # Two correctness traps we've paid for in review:
    #
    # (a) `privacy_scan.py` skips any directory named `analysis` via
    #     DEFAULT_SKIP_DIR_NAMES — so passing `--root <workspace>`
    #     silently scans NOTHING in a normal BSA workspace. We pass
    #     `--root <workspace>/analysis` so the skip list only trims
    #     nested junk (.git, __pycache__, etc.), not the content we
    #     care about.
    #
    # (b) `privacy_scan.py` writes its rendered report to
    #     `<plugin-repo>/docs/privacy_audit.md` by default. When
    #     doctor runs against an EXTERNAL workspace that default
    #     corrupts the plugin repo's own audit file. Route the
    #     report into a temp file — we surface findings via stdout/
    #     stderr only.
    import tempfile  # local — only used by this branch
    analysis_dir = root / "analysis"
    if not analysis_dir.is_dir():
        # is_initialized() already verified analysis/ at entry, so this
        # branch only fires if something tore the tree out mid-run
        # (e.g., concurrent `rm -rf` from another process). That's an
        # environment failure, not a benign skip — classify as ERROR
        # so the overall doctor exits 2 rather than silently
        # under-reporting (a missing analysis/ would also short-circuit
        # the content walk to empty, producing a false-clean summary).
        error_count += 1
        sections.append(
            "  privacy scan: ERROR (analysis/ directory disappeared mid-run; "
            "workspace tree is no longer present)"
        )
    else:
        # tempfile.NamedTemporaryFile can raise OSError (no writable
        # tmp dir, hit FD limit, etc.). If it does, the validator
        # never ran — surface as ERROR so we keep the 0/1/2 contract
        # and CI/on-call can distinguish "doctor environment broken"
        # from "workspace dirty".
        tmp_report: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".md", prefix="bsa_doctor_privacy_", delete=False
            ) as tmp:
                tmp_report = tmp.name
            rc, out = _run_subprocess_validator(
                plugin_repo,
                "scripts/privacy_scan.py",
                "--root",
                str(analysis_dir),
                "--output",
                tmp_report,
            )
        except OSError as exc:
            error_count += 1
            sections.append(
                f"  privacy scan: ERROR (could not allocate temp report: {exc})"
            )
        else:
            _section("privacy scan", rc, out)
        finally:
            if tmp_report is not None:
                try:
                    os.unlink(tmp_report)
                except OSError:
                    pass

    # 5. Content walk: every canonical file through the F5 write-validator.
    #
    # Use _iter_workspace_canonical_files(..., strict=True) so a
    # disappeared analysis/ raises FileNotFoundError rather than
    # short-circuiting to [] (which is indistinguishable from
    # "workspace has no canonical files yet"). The strict=True path
    # collapses what was previously a TOCTOU race between an outer
    # is_dir() check and the helper's inner short-circuit into a
    # single point of detection — the helper itself decides.
    failed_files: list[tuple[str, str]] = []
    error_files: list[tuple[str, str]] = []
    walk_error: bool = False
    try:
        files = _iter_workspace_canonical_files(ws, strict=True)
    except FileNotFoundError as exc:
        walk_error = True
        files = []
        error_count += 1
        sections.append(
            f"  content validation: ERROR ({exc}; workspace tree was "
            f"torn out between privacy scan and content walk)"
        )
    for f in files:
        rc, stderr = _validate_one_file(plugin_repo, root, f)
        if rc == 0:
            continue
        try:
            rel = f.relative_to(root).as_posix()
        except ValueError:
            rel = f.as_posix()
        if rc == 2:
            error_files.append((rel, stderr))
        else:
            failed_files.append((rel, stderr))

    if walk_error:
        # ERROR section already appended above; skip the SKIP/OK/FAIL path.
        pass
    elif not files:
        # Closes the residual TOCTOU window from round-5: the helper
        # does several `is_dir()` / `glob()` probes after its initial
        # `strict=True` guard. If analysis/ disappears DURING those
        # probes, the helper returns []/partial — and we'd otherwise
        # misclassify as a benign SKIP. Final post-enumeration check:
        # if analysis is now gone, surface ERROR instead.
        if not ws.analysis.is_dir():
            error_count += 1
            sections.append(
                "  content validation: ERROR (analysis/ disappeared during "
                "enumeration; canonical-file list may be incomplete)"
            )
        else:
            sections.append("  content validation: SKIP (no canonical files yet)")
    elif not failed_files and not error_files:
        sections.append(f"  content validation: OK ({len(files)} files)")
    else:
        if failed_files:
            findings_count += 1
        if error_files:
            error_count += 1
        # Header reflects HIGHEST severity present:
        #   any errors  → ERROR (regardless of FAILs)
        #   only fails  → FAIL
        # When both classes appear, the per-file `[FAIL]`/`[ERROR]`
        # tags below preserve the breakdown.
        if error_files:
            header_label = "ERROR" if not failed_files else "ERROR (with FAILs)"
        else:
            header_label = "FAIL"
        block = [
            f"  content validation: {header_label} "
            f"({len(failed_files) + len(error_files)} of {len(files)} files flagged)"
        ]
        for rel, stderr in failed_files:
            block.append(f"    - [FAIL]  {rel}")
            for line in (stderr or "<no detail>").splitlines():
                block.append(f"        {line}")
        for rel, stderr in error_files:
            block.append(f"    - [ERROR] {rel}")
            for line in (stderr or "<no detail>").splitlines():
                block.append(f"        {line}")
        sections.append("\n".join(block))

    # ---- Print summary ---------------------------------------------
    print(f"BSA doctor: {root}")
    print()
    for s in sections:
        print(s)
    print()
    if error_count == 0 and findings_count == 0:
        print("Summary: ALL CLEAN. /bsa-promote should pass the hook gates.")
        return 0
    if error_count > 0:
        # Report ERROR shape distinctly so CI can `exit 2` triage.
        bits = []
        if error_count:
            bits.append(f"{error_count} validator(s) failed to execute")
        if findings_count:
            bits.append(f"{findings_count} validator(s) reported findings")
        print(
            f"Summary: {' and '.join(bits)}. Doctor itself encountered an "
            f"environment error — inspect the ERROR section(s) above before "
            f"trusting the rest of the report."
        )
        return 2
    print(
        f"Summary: {findings_count} validator(s) reported findings. "
        "/bsa-promote will likely be blocked. See per-validator detail above."
    )
    return 1



# ---- Main dispatcher ------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="bsa",
        description=(
            "BSA workspace CLI — shell-friendly view of plugin state. "
            "status / next / doctor are read-only; materials writes "
            "to analysis/proposals/stage1/inputs/ (gated by --commit). "
            "All canonical state mutation still goes through Claude "
            "Code slash-commands (/bsa-start, /bsa-stage, /bsa-promote, "
            "etc.)."
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

    p_doctor = subparsers.add_parser(
        "doctor",
        help=(
            "Run all validators against the workspace + walk every "
            "canonical file through the F5 write-validator. Single "
            "green/red signal before /bsa-promote."
        ),
    )
    p_doctor.set_defaults(func=cmd_doctor)

    p_mat = subparsers.add_parser(
        "materials",
        help=(
            "Stage external PDF/DOCX/MD/TXT/XLSX/CSV files into "
            "analysis/proposals/stage1/inputs/ + draft source_manifest.csv. "
            "Default is dry-run; pass --commit to write."
        ),
    )
    p_mat.add_argument(
        "src_dir",
        help=(
            "Directory containing source files to stage. Supported "
            "extensions (v1.4.1): .pdf, .docx, .md/.markdown, .txt, "
            ".xlsx, .csv. Anything else is reported as 'unsupported' "
            "and skipped."
        ),
    )
    p_mat.add_argument(
        "--commit",
        action="store_true",
        help="Actually write files. Without this, prints a preview and exits 0.",
    )
    p_mat.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing source_NNN_*.md files in inputs/.",
    )
    p_mat.add_argument(
        "--recursive",
        action="store_true",
        help="Walk subdirectories of src_dir (default: top-level only).",
    )
    p_mat.add_argument(
        "--max-mb",
        type=float,
        default=25.0,
        help=(
            "Per-file size cap in megabytes. Files above this are "
            "reported as 'too-large' and NOT staged (safety against "
            "accidentally pulling a 200MB scanned PDF or binary blob). "
            "v1.4.1: tunable from CLI (was a hard 25MB constant). "
            "Default: 25.0 MB."
        ),
    )
    p_mat.add_argument(
        "--max-rows-per-table",
        type=int,
        default=5000,
        help=(
            "v1.4.1: row cap for tabular extractors (xlsx + csv). "
            "Sheets / files exceeding this are truncated to the first "
            "N rows with a clear footer note. Default: 5000."
        ),
    )
    p_mat.set_defaults(func=cmd_materials)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
