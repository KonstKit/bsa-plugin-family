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


# ---- Materials: stage external sources into proposals/stage1/inputs/ ---

import re  # noqa: E402  (lazy — only used by cmd_materials)
import shutil  # noqa: E402  (lazy — only used by cmd_materials)
from dataclasses import dataclass  # noqa: E402

# Extension classification — lower-case ext (with dot) → kind. `kind`
# decides which converter we route to. Kept narrow on purpose; new
# formats are an explicit follow-up, not a silent best-effort.
_EXT_TO_KIND: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "text",
    ".markdown": "text",
    ".txt": "text",
}

# Per-file safety caps. The user is pointing this at arbitrary
# external content — we want to catch mistakes (a 200 MB scanned PDF,
# a directory of binary blobs) before they consume tens of seconds
# of subprocess time. Tunable via flags.
_DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB


class ConversionUnavailable(RuntimeError):
    """Raised when the optional library for a format is not installed."""


class ConversionFailed(RuntimeError):
    """Raised when the optional library is installed but conversion fails
    on this specific file (corrupt PDF, encrypted DOCX, etc.)."""


@dataclass
class SourcePlan:
    """One planned conversion. Holds what we'd do at --commit time."""
    src: Path                 # original file path
    kind: str                 # "pdf" | "docx" | "text"
    target: Path              # workspace-relative destination
    source_id: str            # "S-001" etc.
    origin_rel: str = ""      # canonical Origin recorded in BOTH the
                              # manifest CSV row AND the provenance
                              # comment at the top of the staged file.
                              # Round-3 fix: previously basename was
                              # written into the comment while the
                              # manifest used the relative path —
                              # disambiguation false-skipped distinct
                              # `team_a/foo.md` vs `team_b/foo.md`.
    skipped_reason: Optional[str] = None  # set when --commit would skip


def _slugify(name: str, max_len: int = 40) -> str:
    """Turn a filename stem into a stable lowercase snake_case slug.

    Caller is expected to pass the stem (or a free-form title);
    we do NOT strip a trailing extension here, because Path.stem
    only chops the LAST dotted segment — applying it twice eats
    legitimate version markers like `v4.2` (becomes `v4`).

    Examples:
        "Procurement Policy v4.2"          -> "procurement_policy_v4_2"
        "PM Interview — Alex (final)"     -> "pm_interview_alex_final"
        "Стандарт Доставки"                -> "src_<hash>" (no ASCII)
    Non-ASCII is dropped (re.ASCII flag); if nothing usable remains
    we fall back to a hash so we never emit an empty stem.
    """
    # Lowercase + replace any non-alnum run with a single underscore.
    out = re.sub(r"[^a-z0-9]+", "_", name.lower(), flags=re.ASCII)
    out = out.strip("_")
    if not out:
        # Last-resort: derive a stable token from the original name
        # so we don't collide on multiple "untitled" inputs.
        import hashlib
        return "src_" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return out[:max_len].rstrip("_") or "src"


def _next_source_id(inputs_dir: Path, manifest_path: Path) -> int:
    """Return the next free source ordinal (1-based).

    Looks at:
      - existing source_NNN_*.md files in inputs/
      - existing rows in source_manifest.csv (if any)
    and returns max(existing) + 1, or 1 if none.
    """
    used: set[int] = set()
    src_pat = re.compile(r"^source_(\d{3,4})_")
    if inputs_dir.is_dir():
        for f in inputs_dir.iterdir():
            m = src_pat.match(f.name)
            if m:
                used.add(int(m.group(1)))
    if manifest_path.is_file():
        # Cheap parse — first column is SourceID like "S-001".
        try:
            text = manifest_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        sid_pat = re.compile(r"^S-(\d{3,4})\b")
        for line in text.splitlines():
            m = sid_pat.match(line.strip())
            if m:
                used.add(int(m.group(1)))
    return (max(used) + 1) if used else 1


def _convert_pdf(path: Path) -> str:
    """Extract text from a PDF using pypdf. Raises ConversionUnavailable
    if pypdf is not installed; ConversionFailed on per-file errors."""
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ConversionUnavailable(
            "pypdf not installed. Install with `pip install pypdf` "
            "to convert PDFs (or convert them externally and re-run "
            "with .md / .txt files)."
        ) from exc
    try:
        reader = pypdf.PdfReader(str(path))
        if reader.is_encrypted:
            # Try empty password — common for "view-protected" PDFs.
            try:
                reader.decrypt("")
            except Exception:
                raise ConversionFailed(
                    f"PDF is encrypted: {path.name}. Decrypt externally before re-staging."
                )
        chunks: list[str] = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as page_exc:  # pragma: no cover — pypdf-internal
                text = f"[bsa-materials: page {i} extraction failed: {page_exc}]"
            chunks.append(f"## Page {i}\n\n{text.strip()}\n")
        return "\n".join(chunks).strip() + "\n"
    except ConversionFailed:
        raise
    except Exception as exc:
        raise ConversionFailed(f"pypdf failed on {path.name}: {exc}") from exc


def _convert_docx(path: Path) -> str:
    """Extract text from a DOCX using python-docx. Same error contract
    as _convert_pdf."""
    try:
        import docx  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ConversionUnavailable(
            "python-docx not installed. Install with `pip install "
            "python-docx` to convert DOCX (or convert externally to MD)."
        ) from exc
    try:
        doc = docx.Document(str(path))
    except Exception as exc:
        raise ConversionFailed(f"python-docx failed on {path.name}: {exc}") from exc
    # Walk paragraphs + tables in document order. python-docx doesn't
    # expose a direct "iterate body in order" API; we use the
    # underlying XML element ordering for stability.
    from docx.oxml.ns import qn  # type: ignore[import-not-found]
    body = doc.element.body
    parts: list[str] = []
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            # Match by element identity; expensive but doc.paragraphs
            # is short for typical interview transcripts.
            for p in doc.paragraphs:
                if p._element is child:  # type: ignore[attr-defined]
                    text = p.text.strip()
                    if text:
                        parts.append(text)
                    break
        elif child.tag == qn("w:tbl"):
            for table in doc.tables:
                if table._element is child:  # type: ignore[attr-defined]
                    for row in table.rows:
                        cells = [c.text.strip() for c in row.cells]
                        parts.append(" | ".join(cells))
                    parts.append("")  # blank line after table
                    break
    return "\n\n".join(parts).strip() + "\n"


def _read_text(path: Path) -> str:
    """Read MD/TXT verbatim with a tolerant encoding fallback."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Fall back to latin-1 so we never crash on byte-stream input.
        return path.read_text(encoding="latin-1")


def _classify(path: Path) -> Optional[str]:
    """Return kind ('pdf' | 'docx' | 'text') or None if unsupported."""
    return _EXT_TO_KIND.get(path.suffix.lower())


def _scan_source_dir(
    src_dir: Path, recursive: bool
) -> tuple[list[Path], list[Path], list[Path]]:
    """Walk src_dir; return (supported, skipped_unsupported, skipped_too_big).

    Sorted for deterministic ordering. Hidden files / dirs (leading
    dot) are skipped — we don't want .DS_Store or .git to land in
    inputs/. Symlinked directories are NEVER followed (Codex round-1
    HIGH: a `src/a -> ../src` loop would recurse forever and could
    escape the requested src tree). Symlinked FILES are honored
    because users legitimately drop `ln -s ~/Drive/foo.pdf src/`
    when staging from a synced cloud folder.
    """
    supported: list[Path] = []
    unsupported: list[Path] = []
    too_big: list[Path] = []

    def _walk(d: Path) -> None:
        for entry in sorted(d.iterdir(), key=lambda p: p.name):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                if recursive and not entry.is_symlink():
                    _walk(entry)
                continue
            if not entry.is_file():
                continue
            try:
                size = entry.stat().st_size
            except OSError:
                continue
            if size > _DEFAULT_MAX_FILE_BYTES:
                too_big.append(entry)
                continue
            kind = _classify(entry)
            if kind is None:
                unsupported.append(entry)
            else:
                supported.append(entry)

    if src_dir.is_dir():
        _walk(src_dir)
    return supported, unsupported, too_big


def _check_write_containment(
    stage1_dir: Path, inputs_dir: Path, manifest_path: Path
) -> Optional[str]:
    """Verify the planned write surface is inside the workspace tree.

    Returns None if safe; an error message string otherwise. The caller
    surfaces that as exit-code-2 + stderr.

    Specifically, refuses to proceed if:
      (1) Any of `analysis/`, `proposals/`, `stage1/`, `inputs/` is a
          symlink — even if its target is currently inside the
          workspace, a future symlink swap would silently redirect
          writes. Defense in depth.
      (2) The resolved staging dir does not start with the resolved
          workspace root — e.g., `analysis/ -> /tmp/elsewhere`.
    """
    # (1) Walk up the parents from inputs_dir to the workspace root,
    # checking each is a real directory (not a symlink).
    suspicious_links: list[Path] = []
    chain = [inputs_dir, stage1_dir, stage1_dir.parent, stage1_dir.parent.parent]
    # chain = [inputs/, stage1/, proposals/, analysis/]
    for p in chain:
        if p.is_symlink():
            suspicious_links.append(p)
    if suspicious_links:
        names = ", ".join(str(s) for s in suspicious_links)
        return (
            f"refusing to write: workspace path contains symlink(s) — "
            f"{names}. Re-create as a real directory (mkdir) to use "
            f"`bsa materials --commit`."
        )
    # (2) Resolve the staging dir IF it exists; if not, resolve its
    # nearest existing parent to confirm the eventual mkdir lands
    # inside the workspace.
    workspace_root = stage1_dir.parent.parent.parent  # analysis/'s parent
    workspace_resolved = workspace_root.resolve()
    # Pick the first existing ancestor; resolve() on a non-existent
    # path is fine on POSIX but the symlink check above handles the
    # interesting cases. We just need a sanity check here.
    probe = stage1_dir
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        probe_resolved = probe.resolve()
    except OSError as exc:
        return f"failed to resolve staging path {probe}: {exc}"
    try:
        probe_resolved.relative_to(workspace_resolved)
    except ValueError:
        return (
            f"refusing to write: resolved staging path {probe_resolved} "
            f"escapes workspace root {workspace_resolved}. Likely a "
            f"symlinked directory pointing outside the workspace."
        )
    return None


# Provenance comment we embed at the top of every staged input file.
# Lets us recover the original Origin name from a staged file's
# content alone (manifest-deleted recovery + slug-collision
# disambiguation). Format intentionally narrow so the regex below
# matches exactly.
_PROVENANCE_COMMENT_RE = re.compile(
    r"<!-- bsa materials: staged from (?P<orig>.+?) "
    r"\(kind=(?P<kind>[a-z]+)\); SourceID=(?P<sid>[A-Z0-9\-]+) -->"
)


def _read_staged_provenance(staged_md: Path) -> Optional[str]:
    """Return the original `Origin` recorded in the provenance comment
    at the top of a staged input file, or None if absent / unreadable.
    Used to disambiguate slug collisions: if two source files
    produce the same slug (e.g., 40-char truncation), we look at the
    existing staged file's provenance to decide whether the current
    src is the SAME source (truly already staged → skip) or a
    DIFFERENT source that happens to slug-collide (allocate a fresh
    slug variant → no false-positive skip)."""
    try:
        head = staged_md.read_text(encoding="utf-8", errors="ignore")[:512]
    except OSError:
        return None
    m = _PROVENANCE_COMMENT_RE.search(head)
    return m.group("orig") if m else None


def _existing_origins(manifest_path: Path) -> set[str]:
    """Return the set of `Origin` values already recorded in
    source_manifest.csv. Used to detect "this source was already
    staged in a prior run" and skip it on re-invocation, so
    `bsa materials <same-dir>` is idempotent.

    We parse with the stdlib csv module to handle quoted Origin
    values correctly (the manifest is RFC4180-shaped per the
    A50 schema's column order)."""
    if not manifest_path.is_file():
        return set()
    import csv
    out: set[str] = set()
    try:
        with manifest_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                origin = (row.get("Origin") or "").strip()
                if origin:
                    out.add(origin)
    except (OSError, csv.Error):
        pass
    return out


def _plan_conversions(
    src_files: list[Path],
    inputs_dir: Path,
    manifest_path: Path,
    src_dir_root: Path,
    force: bool,
) -> list[SourcePlan]:
    """Build a list of SourcePlan, assigning fresh source IDs.

    Idempotency is enforced TWO ways (both gated by --force):
      1. Origin-based: if the source file's path-relative-to-src_dir
         already appears as an Origin in source_manifest.csv, skip.
         This is the primary check — re-running `bsa materials` on
         the same input directory must NOT duplicate-stage files.
      2. Target-based: if the would-be target file
         (source_NNN_<slug>.md) already exists in inputs/, skip.
         Catches the edge case where the manifest was deleted but
         input files remain.
    """
    plans: list[SourcePlan] = []
    next_id = _next_source_id(inputs_dir, manifest_path)
    already_staged = _existing_origins(manifest_path)
    # Slug→existing-path map for the slug-backstop: if the manifest
    # was deleted but old `source_NNN_<slug>.md` files remain, we
    # MUST detect those by slug. Round-2 fix: when the slug matches,
    # consult the file's provenance comment to disambiguate "same
    # source, truly already staged" from "different source that
    # happens to slug-collide" (slug truncation at 40 chars or
    # heavy non-ASCII normalization can produce collisions).
    existing_by_slug: dict[str, Path] = {}
    if inputs_dir.is_dir():
        slug_pat = re.compile(r"^source_\d{3,4}_(.+)\.md$")
        for f in inputs_dir.iterdir():
            m = slug_pat.match(f.name)
            if m:
                existing_by_slug.setdefault(m.group(1), f)
    # Reserve in-batch slugs so two src files in the SAME run don't
    # both try to claim source_NNN_<slug>.md (they'd race + clobber).
    reserved_slugs: set[str] = set(existing_by_slug.keys())
    for src in src_files:
        kind = _classify(src) or "text"
        slug = _slugify(src.stem)
        # Compute the same Origin string the manifest writer would
        # produce, for the idempotency comparison.
        try:
            origin_rel = str(src.relative_to(src_dir_root))
        except ValueError:
            origin_rel = str(src)

        # --- Primary idempotency check: Origin in manifest. -----------
        if origin_rel in already_staged and not force:
            sid_num = next_id
            sid = f"S-{sid_num:03d}"
            target_name = f"source_{sid_num:03d}_{slug}.md"
            target = inputs_dir / target_name
            plans.append(SourcePlan(
                src=src, kind=kind, target=target, source_id=sid,
                origin_rel=origin_rel,
                skipped_reason=(
                    f"already staged in source_manifest.csv "
                    f"(Origin={origin_rel!r}); pass --force to re-stage"
                ),
            ))
            continue

        # --- Slug-backstop with provenance disambiguation. ------------
        # If the slug already exists on disk, look at the existing
        # file's provenance comment to decide:
        #   - same Origin → truly already staged, skip (no false-pos)
        #   - different Origin → slug collision, allocate alt slug
        # Provenance is the canonical Origin (relative path), NOT
        # basename — round-3 fix: comparing basenames false-skipped
        # distinct nested files like team_a/foo.md vs team_b/foo.md.
        if slug in existing_by_slug and not force:
            existing_file = existing_by_slug[slug]
            existing_origin = _read_staged_provenance(existing_file)
            if existing_origin is not None and existing_origin == origin_rel:
                sid_num = next_id
                sid = f"S-{sid_num:03d}"
                target_name = f"source_{sid_num:03d}_{slug}.md"
                target = inputs_dir / target_name
                plans.append(SourcePlan(
                    src=src, kind=kind, target=target, source_id=sid,
                    origin_rel=origin_rel,
                    skipped_reason=(
                        f"input file with the same slug already staged at "
                        f"{existing_file.name} (provenance match); pass "
                        f"--force to re-stage"
                    ),
                ))
                continue
            # Slug collision but DIFFERENT source (or no provenance
            # to verify) → allocate a unique slug rather than silently
            # skip. Overwrite-safe: never touches the existing file.
            slug = _next_unique_slug(slug, reserved_slugs, src.stem)

        sid_num = next_id
        sid = f"S-{sid_num:03d}"
        target_name = f"source_{sid_num:03d}_{slug}.md"
        target = inputs_dir / target_name

        # --- Final backstop: exact target path collision (manifest +
        # slug both clean, but we're about to overwrite an in-tree file)
        if target.exists() and not force:
            plans.append(SourcePlan(
                src=src, kind=kind, target=target, source_id=sid,
                origin_rel=origin_rel,
                skipped_reason=(
                    f"target exists ({target.name}); pass --force to overwrite"
                ),
            ))
            continue

        plans.append(SourcePlan(
            src=src, kind=kind, target=target, source_id=sid,
            origin_rel=origin_rel, skipped_reason=None,
        ))
        reserved_slugs.add(slug)
        next_id += 1  # only burn an ID for plans we'll actually write
    return plans


def _next_unique_slug(base: str, reserved: set[str], stem: str) -> str:
    """Return `base` if free, else `base_<6char-hash>` based on the
    original stem (stable per-source). Guarantees uniqueness within
    the run AND independent of insertion order."""
    if base not in reserved:
        return base
    import hashlib
    suffix = hashlib.sha1(stem.encode("utf-8")).hexdigest()[:6]
    candidate = f"{base[:33]}_{suffix}"  # 33 + 1 + 6 = 40-char ceiling
    # In the unlikely event that the hashed slug also collides
    # (would require two files with identical stems and identical
    # 40-char base slugs — practically impossible), append a counter.
    n = 1
    final = candidate
    while final in reserved:
        n += 1
        final = f"{candidate}_{n}"
    return final


def _render_draft_manifest(plans: list[SourcePlan], src_dir_root: Path) -> str:
    """Render a draft source_manifest.csv. ReliabilityTier defaults to
    T5 (most cautious) — the user MUST re-tag during /bsa-stage 1
    review. Notes column flags this clearly so the worker sees it."""
    cols = [
        "SourceID", "SourceType", "Title", "Origin", "AccessStatus",
        "ReliabilityTier", "Priority", "Language", "DateOrVersion", "Notes",
    ]
    out = [",".join(cols)]
    today = _today_iso()
    for p in plans:
        if p.skipped_reason is not None:
            continue
        # SourceType heuristic: "interview" anywhere in the slug → interview_transcript.
        slug_lower = p.target.stem.lower()
        if "interview" in slug_lower or "transcript" in slug_lower:
            stype = "interview_transcript"
        elif p.kind in ("pdf", "docx"):
            stype = "document"
        else:
            stype = "process_note"
        title = _csv_escape(p.src.stem)
        # Origin is canonical: same string used by both the manifest
        # row AND the staged file's provenance comment (see
        # _plan_conversions). origin_rel is set in the planner; we
        # only fall back to absolute path if planning code didn't
        # populate it (defensive — current callers always do).
        origin = _csv_escape(p.origin_rel or str(p.src))
        notes = (
            "auto-staged by `bsa materials`; ReliabilityTier defaulted to "
            "T5 — re-tag based on epistemic proximity per "
            "skills/bsa-evidence-intake/references/reliability_tier_spec.md "
            "before /bsa-promote"
        )
        row = [
            p.source_id, stype, title, origin, "readable",
            "T5", "medium", "en", today, _csv_escape(notes),
        ]
        out.append(",".join(row))
    return "\n".join(out) + "\n"


def _csv_escape(value: str) -> str:
    """Minimal RFC4180 CSV escape. We control the input shape so don't
    need a full csv.writer roundtrip."""
    if any(ch in value for ch in (",", '"', "\n", "\r")):
        return '"' + value.replace('"', '""') + '"'
    return value


def _today_iso() -> str:
    """ISO date for DateOrVersion column."""
    from datetime import date
    return date.today().isoformat()


def _bytes_human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 ** 2:.1f} MB"


def cmd_materials(args: argparse.Namespace) -> int:
    """Stage PDF/DOCX/MD/TXT inputs into analysis/proposals/stage1/inputs/.

    Default is dry-run — prints what would be done. --commit performs
    writes. --force overwrites existing target files. --recursive
    walks subdirectories.

    Exit codes:
        0 = preview rendered (dry-run) OR all writes succeeded.
        1 = at least one file failed to convert (per-file
            ConversionFailed — corrupt PDF, encrypted DOCX, etc.) OR
            optional library missing for at least one file
            (ConversionUnavailable). Both surface in the summary
            with per-file detail; ConversionUnavailable additionally
            prints a `pip install ...` hint.
        2 = invocation / structural error: bad src dir, uninitialized
            workspace, EMPTY src dir, OR an existing source_manifest.csv
            whose header has drifted away from the canonical A50
            column order (we refuse to append unsafe rows).
    """
    root = Path(args.workspace).resolve()
    ws = WorkspaceState(root)
    src_dir = Path(args.src_dir).resolve()

    if not src_dir.is_dir():
        sys.stderr.write(
            f"[bsa materials] source directory not found: {src_dir}\n"
        )
        return 2
    if not ws.is_initialized():
        sys.stderr.write(
            f"[bsa materials] {root} is not a BSA workspace "
            "(no analysis/ directory). Run /bsa-start in Claude "
            "Code first.\n"
        )
        return 2

    # Write containment (Codex round-1 HIGH): RESOLVE the staging dir
    # and refuse to proceed if any of inputs/, source_manifest.csv,
    # or any planned target file would land OUTSIDE the resolved
    # `<workspace>/analysis/proposals/stage1/` subtree. Without this,
    # a symlinked `analysis/`, `proposals/`, `stage1/`, or `inputs/`
    # would let `--commit` write into arbitrary filesystem locations
    # under the user's account.
    stage1_dir = (ws.analysis / "proposals" / "stage1")
    inputs_dir = stage1_dir / "inputs"
    manifest_path = stage1_dir / "source_manifest.csv"

    contain_error = _check_write_containment(stage1_dir, inputs_dir, manifest_path)
    if contain_error is not None:
        sys.stderr.write(f"[bsa materials] {contain_error}\n")
        return 2

    # 1. Walk source dir.
    supported, unsupported, too_big = _scan_source_dir(
        src_dir, recursive=bool(args.recursive)
    )
    if not supported and not unsupported and not too_big:
        sys.stderr.write(
            f"[bsa materials] no files found under {src_dir} "
            f"(recursive={bool(args.recursive)}). "
            f"Supported extensions: {sorted(_EXT_TO_KIND)}.\n"
        )
        return 2

    # 2. Plan conversions (assigns IDs, flags target collisions).
    plans = _plan_conversions(
        supported, inputs_dir, manifest_path, src_dir, force=bool(args.force)
    )

    # 3. Render preview.
    print(f"BSA materials: {src_dir} → {inputs_dir}")
    print()
    print(f"Found {len(supported)} convertible file(s)"
          f" ({_count_kinds(plans)})"
          f"; {len(unsupported)} unsupported, {len(too_big)} too-large")
    print()
    if plans:
        print("Plan:")
        for p in plans:
            mark = " (SKIP)" if p.skipped_reason else ""
            # For skipped plans the SourceID we'd assign is moot
            # (we won't write the manifest row). Show "(existing)"
            # to avoid the visual confusion of multiple skipped
            # entries all sharing the same provisional ID.
            sid_label = "(existing)" if p.skipped_reason else p.source_id
            print(f"  [{sid_label}] {p.src.name:<40s} → {p.target.name}{mark}")
            if p.skipped_reason:
                print(f"           reason: {p.skipped_reason}")
    if unsupported:
        print()
        print("Unsupported (not staged):")
        for f in unsupported[:10]:
            print(f"  - {f.name}  ({f.suffix or 'no-ext'})")
        if len(unsupported) > 10:
            print(f"  ... and {len(unsupported) - 10} more")
    if too_big:
        print()
        print(f"Too large (> {_bytes_human(_DEFAULT_MAX_FILE_BYTES)}; not staged):")
        for f in too_big:
            print(f"  - {f.name}  ({_bytes_human(f.stat().st_size)})")

    print()
    if not args.commit:
        print("DRY RUN. Re-run with --commit to actually write files + draft manifest.")
        if any(not p.skipped_reason for p in plans):
            print("Suggested next:")
            print(f"  bsa --workspace {root} materials {src_dir} --commit")
        return 0

    # PRE-FLIGHT: header-drift check + leaf-symlink check.
    # Round-2 fix: do these BEFORE any file writes so we never leave
    # a half-committed state (input files written + manifest unwritable).
    # Round-3 fix: catch the "manifest_path is a directory / device /
    # other non-file" case BEFORE writing inputs. Without this, the
    # commit phase could orphan input files when the post-write
    # manifest update failed late.
    if manifest_path.exists() and not manifest_path.is_file():
        sys.stderr.write(
            f"[bsa materials] {manifest_path} exists but is not a regular "
            f"file (directory? device? socket?). Refuse to write — clean "
            f"up the path manually before re-running.\n"
        )
        return 2
    if manifest_path.is_file():
        # Round-6 fix: previously _atomic_write_text would silently
        # overwrite a read-only manifest because os.replace inspects
        # the parent directory's permission, not the file's. The
        # user explicitly chose to chmod the manifest read-only —
        # honor that intent before we plan any writes.
        if not os.access(manifest_path, os.W_OK):
            sys.stderr.write(
                f"[bsa materials] existing source_manifest.csv is not "
                f"writable ({manifest_path}). The atomic-write path "
                f"would otherwise replace it via os.replace, bypassing "
                f"the file's mode bits. If you want to update it, run "
                f"`chmod u+w {manifest_path}` first.\n"
            )
            return 2
        try:
            existing_text = manifest_path.read_text(encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(
                f"[bsa materials] cannot read existing manifest {manifest_path}: {exc}\n"
            )
            return 2
        existing_lines = existing_text.splitlines()
        existing_header = existing_lines[0].strip() if existing_lines else ""
        if existing_header != _A50_HEADER:
            sys.stderr.write(
                f"[bsa materials] existing source_manifest.csv has a non-canonical header.\n"
                f"  Expected: {_A50_HEADER}\n"
                f"  Found:    {existing_header or '(empty)'}\n"
                f"Refuse to append — column misalignment would corrupt the register.\n"
                f"Recovery options:\n"
                f"  (a) restore the canonical A50 column order in the manifest manually, OR\n"
                f"  (b) delete the manifest AND the input files in {inputs_dir} \n"
                f"      (or pass --force on the next run to bypass slug-skip), then re-run.\n"
            )
            return 2
    if manifest_path.is_symlink():
        sys.stderr.write(
            f"[bsa materials] refusing to write: {manifest_path} is a symlink. "
            f"Replace with a real file before running --commit.\n"
        )
        return 2
    # Per-target leaf-symlink check.
    for p in plans:
        if p.skipped_reason is not None:
            continue
        if p.target.is_symlink():
            sys.stderr.write(
                f"[bsa materials] refusing to write: {p.target} is a symlink. "
                f"Replace with a real file or delete it before --commit.\n"
            )
            return 2

    # 4. Commit phase: convert + write each file. Track failures.
    inputs_dir.mkdir(parents=True, exist_ok=True)
    written: list[SourcePlan] = []
    failed: list[tuple[SourcePlan, str]] = []
    unavailable_seen: set[str] = set()
    for p in plans:
        if p.skipped_reason is not None:
            continue
        try:
            content = _convert_one(p)
        except ConversionUnavailable as exc:
            unavailable_seen.add(p.kind)
            failed.append((p, f"unavailable: {exc}"))
            continue
        except ConversionFailed as exc:
            failed.append((p, f"conversion failed: {exc}"))
            continue
        # Wrap each converted file with a small header so downstream
        # consumers (and humans diffing inputs/) can trace provenance
        # without grepping the manifest.
        # Provenance comment uses the canonical Origin (relative
        # path under src_dir_root) so disambiguation in
        # _plan_conversions can compare apples-to-apples with the
        # manifest's Origin column. Round-3 fix.
        body = (
            f"<!-- bsa materials: staged from {p.origin_rel} "
            f"(kind={p.kind}); SourceID={p.source_id} -->\n\n"
            + content
        )
        try:
            p.target.write_text(body, encoding="utf-8")
            written.append(p)
        except OSError as exc:
            failed.append((p, f"write failed: {exc}"))

    # 5. Write draft manifest (only for files we successfully wrote).
    # Header drift was already caught in the pre-flight; here we
    # only need to append/create. We STILL wrap in try/except OSError
    # because between the pre-flight check and this write, anything
    # external (chmod, rm + replace with directory, fs full) could
    # have changed the path's writability. If the manifest write
    # fails, we surface the orphan-input state clearly so the user
    # can either fix the manifest manually OR delete the input
    # files and re-run.
    manifest_action = "skipped (no successful writes)"
    if written:
        try:
            manifest_action = _upsert_draft_manifest(
                manifest_path, written, src_dir
            )
        except OSError as exc:
            # Round-4 fix: previously the recovery guidance suggested
            # "fix the underlying issue and re-run" — but a plain
            # re-run would slug-match the orphaned inputs, set
            # written=[] (because all plans become skipped), and
            # never write the manifest. Net: the user thinks they
            # recovered but the orphan persists. Honest guidance is
            # the only correct fix without a dedicated --recreate-
            # manifest flow (deferred polish).
            #
            # Round-5 fix: _atomic_write_text guarantees that a
            # failed manifest write leaves the ORIGINAL manifest
            # untouched (write to tempfile + os.replace; failure
            # before replace = original safe). So the user's
            # workspace is in one of two clean states:
            #   - manifest absent + new orphaned inputs (first-write fail)
            #   - manifest unchanged + new orphaned inputs (append fail)
            # No corrupted-manifest state.
            orphans = ", ".join(p.target.name for p in written)
            sys.stderr.write(
                f"[bsa materials] WROTE {len(written)} input file(s) "
                f"successfully, but the manifest write FAILED: {exc}\n"
                f"  The manifest at {manifest_path} is UNCHANGED (atomic\n"
                f"  write protects against partial-corruption); the new\n"
                f"  inputs are ORPHANED. The slug-collision backstop\n"
                f"  would skip these files on a plain re-run, so the\n"
                f"  manifest would not get the rows for them. To recover:\n"
                f"\n"
                f"    1. Fix the underlying problem (permissions, disk\n"
                f"       space, conflicting path).\n"
                f"    2. Delete the orphaned input file(s):\n"
                f"         {orphans}\n"
                f"    3. Re-run `bsa materials --commit` from scratch.\n"
            )
            print()
            print(f"Wrote {len(written)} file(s) under {inputs_dir}")
            print(
                f"Manifest: UNCHANGED ({exc}) — atomic write rolled back; "
                f"see stderr for orphan-input recovery."
            )
            return 2

    # 6. Summary.
    print()
    print(f"Wrote {len(written)} file(s) under {inputs_dir}")
    print(f"Manifest: {manifest_path} — {manifest_action}")
    if failed:
        print()
        print(f"Failed ({len(failed)}):")
        for p, reason in failed:
            print(f"  - [{p.source_id}] {p.src.name}: {reason}")
        if unavailable_seen:
            print()
            print(
                "Hint: install optional dependencies for these formats:"
            )
            if "pdf" in unavailable_seen:
                print("  pip install pypdf")
            if "docx" in unavailable_seen:
                print("  pip install python-docx")
        return 1

    print()
    print("Next steps:")
    print(f"  1. Review {manifest_path.name} — re-tag any ReliabilityTier")
    print(f"     entries that should be T1-T4 instead of the T5 default.")
    print(f"  2. /bsa-stage 1   in Claude Code to run evidence-intake.")
    return 0


def _convert_one(p: SourcePlan) -> str:
    """Dispatch by kind. Pure helper for cmd_materials."""
    if p.kind == "pdf":
        return _convert_pdf(p.src)
    if p.kind == "docx":
        return _convert_docx(p.src)
    if p.kind == "text":
        return _read_text(p.src)
    raise ConversionFailed(f"unknown kind {p.kind!r} for {p.src.name}")


def _count_kinds(plans: list[SourcePlan]) -> str:
    """Render 'PDF: 3, DOCX: 1, TXT/MD: 2' for the preview header."""
    counts: dict[str, int] = {}
    for p in plans:
        if p.skipped_reason is not None:
            continue
        counts[p.kind] = counts.get(p.kind, 0) + 1
    if not counts:
        return "all skipped"
    return ", ".join(
        f"{label}: {counts[k]}"
        for k, label in (("pdf", "PDF"), ("docx", "DOCX"), ("text", "TXT/MD"))
        if k in counts
    )


# Canonical A50 column order. MUST match _render_draft_manifest's row
# emission AND governance/schemas/a50.schema.json
# x-bsa-csv-columns-order. Header validation in _upsert_draft_manifest
# uses this as the must-equal set for safe append.
_A50_HEADER = (
    "SourceID,SourceType,Title,Origin,AccessStatus,"
    "ReliabilityTier,Priority,Language,DateOrVersion,Notes"
)


class ManifestHeaderDrift(RuntimeError):
    """Raised by _upsert_draft_manifest when an existing manifest has
    a header that doesn't match _A50_HEADER. Appending under a drifted
    header would yield structurally broken rows — caller must fail
    loudly so the user can fix the manifest manually."""


def _atomic_write_text(path: Path, content: str) -> None:
    """Write `content` to `path` atomically via temp-file + rename.

    Round-5 fix: `Path.write_text` is NOT atomic — a mid-write
    OSError (disk full, NFS hiccup, etc.) leaves the destination
    truncated/corrupted. POSIX rename(2) on the same filesystem
    IS atomic; we write to a sibling tempfile then rename over
    the destination. If anything fails before the rename, the
    original `path` is untouched and the tempfile is best-effort
    cleaned up.

    Round-6 fix: `os.replace` swaps the inode wholesale. Without
    explicit metadata copy, the new file inherits the tempfile's
    mode (typically 0600 from mkstemp) — losing the original's
    mode bits / ACL. We `os.chmod()` the tempfile to match the
    original's mode BEFORE the replace, so the user's permission
    intent (e.g., 0644 for a manifest committed to git, 0664 for
    group-shared workspace) survives the atomic update. We do NOT
    preserve uid/gid (would require root in most cases).
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    # Capture original mode if the destination already exists — we
    # restore it on the tempfile before replace so the new inode
    # carries the same permission bits.
    orig_mode: Optional[int] = None
    try:
        orig_mode = path.stat().st_mode & 0o7777
    except OSError:
        pass  # file doesn't exist yet; new mode = umask default
    # Use mkstemp in the SAME directory so the rename is same-filesystem
    # (atomic). Default tempdir would be `/tmp` and rename across mounts
    # falls back to copy + unlink — not atomic.
    import tempfile  # local — only used here
    fd, tmp_name = tempfile.mkstemp(
        dir=str(parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        if orig_mode is not None:
            try:
                os.chmod(tmp_name, orig_mode)
            except OSError:
                pass  # best-effort; chmod failure is not write failure
        # os.replace is the documented atomic-on-same-fs primitive
        # (and works on Windows too — beats Path.rename which has
        # different cross-platform semantics).
        os.replace(tmp_name, str(path))
    except OSError:
        # Best-effort cleanup; re-raise to caller.
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _upsert_draft_manifest(
    manifest_path: Path, written: list[SourcePlan], src_dir_root: Path
) -> str:
    """Append new draft rows to an existing source_manifest.csv (or
    create fresh). Returns a one-line description of what happened
    for the summary line.

    Pre-condition (verified by cmd_materials pre-flight, NOT
    re-checked here to keep the function single-responsibility):
    if manifest_path exists, its header matches _A50_HEADER. The
    pre-flight ensures we never reach this function with a drifted
    manifest, so we can safely append without re-validating.

    Atomicity (round-5 fix): the actual file replacement uses
    `_atomic_write_text` (tempfile + os.replace), so a mid-write
    OSError leaves the original manifest untouched rather than
    truncated.
    """
    new_rows = _render_draft_manifest(written, src_dir_root)
    if manifest_path.is_file():
        existing = manifest_path.read_text(encoding="utf-8")
        # Drop the header from new_rows (line 0).
        new_body_lines = new_rows.splitlines()[1:]
        merged = existing.rstrip("\n") + "\n" + "\n".join(new_body_lines) + "\n"
        _atomic_write_text(manifest_path, merged)
        return f"appended {len(written)} draft row(s) to existing manifest"
    _atomic_write_text(manifest_path, new_rows)
    return f"created with {len(written)} draft row(s)"


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
            "Stage external PDF/DOCX/MD/TXT files into "
            "analysis/proposals/stage1/inputs/ + draft source_manifest.csv. "
            "Default is dry-run; pass --commit to write."
        ),
    )
    p_mat.add_argument(
        "src_dir",
        help="Directory containing source files to stage (PDF/DOCX/MD/TXT).",
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
    p_mat.set_defaults(func=cmd_materials)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
