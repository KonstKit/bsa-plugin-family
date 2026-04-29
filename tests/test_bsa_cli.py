"""Tests for scripts/bsa_cli.py (v1.0.4 UX wrapper).

Covers:
  - WorkspaceState readers against synthetic + real-fixture workspaces.
  - `bsa status` CLI output shape (not exact formatting — exit code + key
    substrings so the test survives reasonable layout tweaks).
  - Graceful degradation: uninitialized workspace, missing A48, missing
    A51, malformed markers, Pilot-1-drifted (camelCase-payload) markers.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_SCRIPT = REPO_ROOT / "scripts" / "bsa_cli.py"
BSA_SHELL = REPO_ROOT / "scripts" / "bsa"


# ---- Helpers --------------------------------------------------------


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI_SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def _init_workspace(tmp_path: Path, a48_fields: dict[str, str] | None = None) -> Path:
    """Create a minimal analysis/ layout with an A48 card."""
    analysis = tmp_path / "analysis"
    core = analysis / "canonical" / "core_controls"
    core.mkdir(parents=True)
    (analysis / "runtime" / "ready").mkdir(parents=True)
    (analysis / "discovery" / "runtime" / "ready").mkdir(parents=True)
    fields = a48_fields or {
        "RunID": "test-run-001",
        "Mode": "direct",
        "CurrentStage": "stage1",
        "CanonPolicyVersion": "1.0.0",
    }
    # Bullet-backtick A48 (the format the plugin test suite uses internally).
    lines = ["# A48 Run Context Card", ""]
    for k, v in fields.items():
        lines.append(f"- `{k}`: {v}")
    (core / "A48_run_context_card.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return tmp_path


def _write_marker(workspace: Path, filename: str, payload: dict, discovery: bool = False) -> None:
    subdir = "discovery/runtime/ready" if discovery else "runtime/ready"
    (workspace / "analysis" / subdir / filename).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_a51(workspace: Path, rows: list[dict]) -> None:
    """Write A51 with the canonical column order."""
    core = workspace / "analysis" / "canonical" / "core_controls"
    cols = [
        "A51Ref", "IssueType", "Severity", "BlockingStatus", "RaisedByStage",
        "RelatedSourceID", "RelatedClaimID", "NextAction", "ResolutionStatus",
    ]
    lines = [",".join(cols)]
    for row in rows:
        cells = []
        for c in cols:
            v = row.get(c, "")
            if "," in v or '"' in v:
                cells.append(f'"{v.replace(chr(34), chr(34) * 2)}"')
            else:
                cells.append(v)
        lines.append(",".join(cells))
    (core / "A51_issue_route_register.csv").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


# ---- 1. Uninitialized workspace -------------------------------------


def test_status_uninitialized_workspace_exits_2(tmp_path: Path) -> None:
    result = _run_cli(["-w", str(tmp_path), "status"])
    assert result.returncode == 2
    assert "not a BSA workspace" in result.stderr


def test_status_nonexistent_workspace_exits_2(tmp_path: Path) -> None:
    result = _run_cli(["-w", str(tmp_path / "nope"), "status"])
    assert result.returncode == 2


# ---- 2. Minimal workspace -------------------------------------------


def test_status_minimal_workspace_shows_a48_fields(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path)
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0, result.stderr
    assert "test-run-001" in result.stdout
    assert "direct" in result.stdout
    assert "stage1" in result.stdout
    assert "1.0.0" in result.stdout
    # No markers yet.
    assert "(none)" in result.stdout


def test_status_no_a51_reports_zero_counts(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path)
    result = _run_cli(["-w", str(ws), "status"])
    assert "Open A51 items:    0 (of 0 total)" in result.stdout


# ---- 3. Markers -----------------------------------------------------


def test_status_surfaces_last_marker(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path)
    _write_marker(
        ws,
        "stage3.ready.json",
        {
            "marker_id": "stage3.ready",
            "stage": "stage3",
            "verdict": "READY",
            "timestamp": "2026-04-22T10:15:00Z",
            "canon_policy_version": "1.0.0",
        },
    )
    _write_marker(
        ws,
        "stage3.citation_audit.pass.json",
        {
            "marker_id": "stage3.citation_audit.pass",
            "stage": "stage3",
            "verdict": "PASS",
            "timestamp": "2026-04-22T11:30:00Z",
            "canon_policy_version": "1.0.0",
        },
    )
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    # Most-recent timestamp wins for "last marker".
    assert "stage3.citation_audit.pass" in result.stdout
    # Both markers listed under the main zone.
    assert "stage3.ready" in result.stdout


def test_status_shows_discovery_markers_separately(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path, {
        "RunID": "d-test",
        "Mode": "discovery_then_bsa",
        "CurrentStage": "d2",
        "CanonPolicyVersion": "1.0.0",
    })
    _write_marker(
        ws,
        "discovery.d1.ready.json",
        {
            "marker_id": "discovery.d1.ready",
            "stage": "d1",
            "verdict": "READY",
            "timestamp": "2026-04-22T10:00:00Z",
            "canon_policy_version": "1.0.0",
        },
        discovery=True,
    )
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    assert "discovery:" in result.stdout
    assert "discovery.d1.ready" in result.stdout


# ---- 4. A51 readers -------------------------------------------------


def test_status_a51_counts_by_blocking_status(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path)
    _write_a51(ws, [
        {"A51Ref": "A51-001", "IssueType": "uncertainty", "Severity": "high",
         "BlockingStatus": "hard", "RaisedByStage": "stage1",
         "NextAction": "x", "ResolutionStatus": "open"},
        {"A51Ref": "A51-002", "IssueType": "contradiction", "Severity": "medium",
         "BlockingStatus": "soft", "RaisedByStage": "stage3",
         "NextAction": "y", "ResolutionStatus": "open"},
        {"A51Ref": "A51-003", "IssueType": "missing_source", "Severity": "low",
         "BlockingStatus": "informational", "RaisedByStage": "stage1",
         "NextAction": "z", "ResolutionStatus": "resolved_by_remediation"},
    ])
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    assert "Open A51 items:    2 (of 3 total)" in result.stdout
    assert "hard blockers:   1" in result.stdout
    assert "soft:            1" in result.stdout
    assert "informational:   1" in result.stdout


# ---- 5. Pilot-1-drifted markers (camelCase) ---------------------------


def test_status_tolerates_camelcase_pilot1_markers(tmp_path: Path) -> None:
    """Pilot-1 engagement markers use `marker`/`emittedAt` instead of
    `marker_id`/`timestamp`. CLI must still read them (fallback
    keys) rather than crash. It's a DIAGNOSTIC tool — refusing to
    open non-conformant workspaces is the wrong call; surfacing the
    drift visibly (verdict='?') is the right one."""
    ws = _init_workspace(tmp_path)
    _write_marker(
        ws,
        "discovery.d1.ready.json",
        {
            "marker": "discovery.d1.ready",
            "runId": "pilot1-like",
            "emittedAt": "2026-04-22T09:00:00Z",
            "canonPolicyVersion": "1.0.0",
        },
        discovery=True,
    )
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    # Marker surfaces by filename stem fallback.
    assert "discovery.d1.ready" in result.stdout


def test_status_tolerates_malformed_marker_json(tmp_path: Path) -> None:
    """A malformed JSON marker must not crash the CLI — just skip it."""
    ws = _init_workspace(tmp_path)
    (ws / "analysis" / "runtime" / "ready" / "broken.json").write_text(
        "{ not valid", encoding="utf-8"
    )
    # Also add a valid marker so the output has something to show.
    _write_marker(ws, "stage1.ready.json", {
        "marker_id": "stage1.ready", "stage": "stage1", "verdict": "READY",
        "timestamp": "2026-04-22T10:00:00Z", "canon_policy_version": "1.0.0",
    })
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    assert "stage1.ready" in result.stdout


# ---- 6. Real fixture end-to-end -------------------------------------


def test_status_reads_real_golden_fixture(tmp_path: Path) -> None:
    """Point the CLI at the committed project_0001 fixture via a
    symlink, verify it parses the real A48 / markers / A51."""
    # Some test runners block os.symlink on Windows; check + skip.
    fx = REPO_ROOT / "fixtures" / "golden" / "project_0001" / "expected_outputs"
    try:
        (tmp_path / "analysis").symlink_to(fx)
    except OSError:
        pytest.skip("symlink unsupported on this platform")
    result = _run_cli(["-w", str(tmp_path), "status"])
    assert result.returncode == 0, result.stderr
    assert "fixture-project-0001" in result.stdout
    assert "stage1" in result.stdout
    assert "0.95" in result.stdout


# ---- 7. Shell wrapper smoke -----------------------------------------


def test_bash_wrapper_delegates_to_cli(tmp_path: Path) -> None:
    """The bash wrapper at scripts/bsa should reach the CLI and forward args."""
    ws = _init_workspace(tmp_path)
    result = subprocess.run(
        ["/bin/bash", str(BSA_SHELL), "-w", str(ws), "status"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "test-run-001" in result.stdout


# ---- 8. Codex-surfaced v1.0.4 regression guards ---------------------


def test_bash_wrapper_works_from_symlink_install(tmp_path: Path) -> None:
    """Documented install path: `ln -s /path/to/plugin/scripts/bsa ~/.local/bin/bsa`.
    Codex review surfaced that the pre-fix wrapper used `dirname "$0"`
    without resolving `$0` through symlinks, so the symlinked-in install
    broke: PLUGIN_REPO became the parent of ~/.local/bin instead of the
    plugin repo.
    """
    ws = _init_workspace(tmp_path)
    link_dir = tmp_path / "bin"
    link_dir.mkdir()
    symlink = link_dir / "bsa"
    try:
        symlink.symlink_to(BSA_SHELL)
    except OSError:
        pytest.skip("symlink unsupported on this platform")
    result = subprocess.run(
        ["/bin/bash", str(symlink), "-w", str(ws), "status"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Symlink-install invocation failed — bash wrapper isn't resolving "
        f"$0 through symlinks.\nstderr={result.stderr!r}"
    )
    assert "test-run-001" in result.stdout


def test_status_recognizes_promoted_no_new_claims_report(tmp_path: Path) -> None:
    """Codex review: audit_outputs() looked at
    `stage8/stage8_no_new_claims_report.md` but the canonical filename
    is `stage8/no_new_claims_report.md`. Fixed; this test pins it."""
    ws = _init_workspace(tmp_path, {
        "RunID": "audit-test",
        "Mode": "direct",
        "CurrentStage": "stage8",
        "CanonPolicyVersion": "1.0.0",
    })
    stage8 = ws / "analysis" / "canonical" / "stage8"
    stage8.mkdir(parents=True)
    (stage8 / "no_new_claims_report.md").write_text(
        "# Report content\n", encoding="utf-8"
    )
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    # The line format is "  no_new_claims        PRESENT"
    assert "no_new_claims" in result.stdout
    # PRESENT indicator for this audit specifically (not just any PRESENT).
    assert "no_new_claims        PRESENT" in result.stdout


# ---- 9. `bsa next` subcommand ---------------------------------------
# State-machine suggester. Must:
#   - match hooks/pre_bash_promote.sh required-marker set so it never
#     points at a command the hook would block
#   - degrade gracefully on non-canonical workspaces (unknown stage,
#     missing A48, discovery.complete state, etc.)


def test_next_uninitialized_suggests_bsa_start(tmp_path: Path) -> None:
    result = _run_cli(["-w", str(tmp_path), "next"])
    assert result.returncode == 0
    assert "/bsa-start" in result.stdout
    # Both modes mentioned.
    assert "--mode=direct" in result.stdout
    assert "--mode=discovery_then_bsa" in result.stdout


def test_next_stage1_no_markers_suggests_stage_run(tmp_path: Path) -> None:
    """Default init state — CurrentStage=stage1, no markers yet."""
    ws = _init_workspace(tmp_path)
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    assert "/bsa-stage 1 run" in result.stdout
    assert "stage1.excerpts.merged" in result.stdout


def test_next_stage1_promoted_suggests_promote(tmp_path: Path) -> None:
    """Stage1 audit marker present → next action is /bsa-promote."""
    ws = _init_workspace(tmp_path)
    _write_marker(ws, "stage1.excerpts.merged.json", {
        "marker_id": "stage1.excerpts.merged",
        "stage": "stage1",
        "verdict": "MERGED",
        "timestamp": "2026-04-22T10:00:00Z",
        "canon_policy_version": "1.0.0",
    })
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    assert "/bsa-promote" in result.stdout


def test_next_stage4_no_gate_suggests_promote(tmp_path: Path) -> None:
    """Stage 4 has no audit gate per run-profile-gates.md."""
    ws = _init_workspace(tmp_path, {
        "RunID": "x",
        "Mode": "direct",
        "CurrentStage": "stage4",
        "CanonPolicyVersion": "1.0.0",
    })
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    assert "/bsa-promote" in result.stdout
    assert "no audit gate" in result.stdout


def test_next_d2_missing_one_of_two_required_mentions_both(tmp_path: Path) -> None:
    """D2 needs both discovery.d2.claims.merged AND
    discovery.d2.research_quality.pass — missing one should still
    report the full required list so the operator knows what audits
    to chase."""
    ws = _init_workspace(tmp_path, {
        "RunID": "x",
        "Mode": "discovery_then_bsa",
        "CurrentStage": "d2",
        "CanonPolicyVersion": "1.0.0",
    })
    _write_marker(ws, "discovery.d2.claims.merged.json", {
        "marker_id": "discovery.d2.claims.merged",
        "stage": "d2",
        "verdict": "MERGED",
        "timestamp": "2026-04-22T09:00:00Z",
        "canon_policy_version": "1.0.0",
    }, discovery=True)
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    # Missing list mentions only research_quality.pass (claims.merged already present).
    assert "discovery.d2.research_quality.pass" in result.stdout
    assert "/bsa-stage d2 run" in result.stdout


def test_next_stage8_promoted_suggests_handoff(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path, {
        "RunID": "x",
        "Mode": "direct",
        "CurrentStage": "stage8",
        "CanonPolicyVersion": "1.0.0",
    })
    _write_marker(ws, "stage8.no_new_claims.pass.json", {
        "marker_id": "stage8.no_new_claims.pass",
        "stage": "stage8",
        "verdict": "PASS",
        "timestamp": "2026-04-22T16:00:00Z",
        "canon_policy_version": "1.0.0",
    })
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    assert "/bsa-handoff" in result.stdout


def test_next_discovery_complete_with_bridge_shows_two_paths(tmp_path: Path) -> None:
    """The  Pilot-1 state: discovery.complete + bsa.stage1.entry.enabled
    present, no main-cycle stage markers. The Sprint-5 F7 notice says
    this deserves a two-path suggestion: continue OR treat as
    deliverable. `bsa next` mirrors that."""
    ws = _init_workspace(tmp_path, {
        "RunID": "x",
        "Mode": "discovery_then_bsa",
        "CurrentStage": "discovery.complete",
        "CanonPolicyVersion": "1.0.0",
    })
    _write_marker(ws, "bsa.stage1.entry.enabled.json", {
        "marker_id": "bsa.stage1.entry.enabled",
        "stage": "discovery.bridge",
        "verdict": "READY",
        "timestamp": "2026-04-22T10:00:00Z",
        "canon_policy_version": "1.0.0",
    })
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    assert "Two valid paths" in result.stdout
    assert "/bsa-stage 1 run" in result.stdout
    assert "discovery-only deliverable" in result.stdout


def test_next_handoff_ready_reports_pipeline_complete(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path, {
        "RunID": "x",
        "Mode": "direct",
        "CurrentStage": "handoff",
        "CanonPolicyVersion": "1.0.0",
    })
    _write_marker(ws, "stage8.no_new_claims.pass.json", {
        "marker_id": "stage8.no_new_claims.pass",
        "stage": "stage8",
        "verdict": "PASS",
        "timestamp": "2026-04-22T16:00:00Z",
        "canon_policy_version": "1.0.0",
    })
    _write_marker(ws, "handoff.ready.json", {
        "marker_id": "handoff.ready",
        "stage": "handoff",
        "verdict": "READY",
        "timestamp": "2026-04-22T17:00:00Z",
        "canon_policy_version": "1.0.0",
    })
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    assert "pipeline complete" in result.stdout.lower()


def test_next_unknown_stage_warns_inspect_a48(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path, {
        "RunID": "x",
        "Mode": "direct",
        "CurrentStage": "stageX",  # not a recognized stage
        "CanonPolicyVersion": "1.0.0",
    })
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    # Does not crash; advises to inspect A48.
    assert "A48_run_context_card.md" in result.stdout


def test_next_suggestion_matches_pre_bash_promote_required_set(tmp_path: Path) -> None:
    """CRITICAL invariant: the required-marker table in bsa_cli must
    match the one in hooks/pre_bash_promote.sh so `bsa next` never
    points at a /bsa-promote the hook would block. This test extracts
    the case-pattern list from the hook script and asserts each is in
    the CLI's _STAGE_REQUIRED_MARKERS table (or explicitly none for
    stage4 which has no gate).
    """
    import re
    from scripts.bsa_cli import _STAGE_REQUIRED_MARKERS  # type: ignore

    hook_path = REPO_ROOT / "hooks" / "pre_bash_promote.sh"
    hook_text = hook_path.read_text(encoding="utf-8")

    # Parse the case-pattern block: extract each stage branch up to its
    # terminating ';;'. Then look for `required=(...)` INSIDE that branch
    # only. Branches without `required=(...)` (e.g., stage4 which exits
    # early with no audit gate) map to empty list.
    branch_pattern = re.compile(
        r"^\s*(stage[1-8]|handoff|d[1-5])\)\s*$"
        r"(?P<body>(?:.|\n)*?)"
        r"^\s*;;\s*$",
        re.MULTILINE,
    )
    required_inside = re.compile(r'required=\(([^)]*)\)')
    found: dict[str, list[str]] = {}
    for m in branch_pattern.finditer(hook_text):
        stage = m.group(1)
        body = m.group("body")
        req_match = required_inside.search(body)
        if req_match:
            items = re.findall(r'"([^"]+)\.json"', req_match.group(1))
            found[stage] = items
        else:
            # Branch with no required=() — stage4 (no audit gate) today.
            found[stage] = []

    # Every hook-declared required set must match the CLI table exactly.
    for stage, hook_required in found.items():
        cli_required = _STAGE_REQUIRED_MARKERS.get(stage, [])
        assert sorted(cli_required) == sorted(hook_required), (
            f"Drift: bsa_cli._STAGE_REQUIRED_MARKERS[{stage!r}]={cli_required!r} "
            f"but hooks/pre_bash_promote.sh requires {hook_required!r}. "
            f"A /bsa-promote suggestion on this stage would be blocked by the hook."
        )

    # Coverage assertion: the parsed set MUST include every stage the
    # CLI table knows about (protects against hook-reformatting that
    # silently weakens the regex — a branch dropped from the parse
    # results would pass the per-stage loop above because the dict
    # key would just be absent).
    expected_stages = set(_STAGE_REQUIRED_MARKERS.keys())
    assert set(found.keys()) == expected_stages, (
        f"Drift-parser coverage mismatch.\n"
        f"  Parsed from hook: {sorted(found.keys())}\n"
        f"  Expected (CLI table keys): {sorted(expected_stages)}\n"
        f"Either the hook was edited without updating the CLI table, "
        f"or the hook-parser regex needs a tweak."
    )


# ---- v1.0.4 chunk-2 round-2 regression guards -----------------------
# Codex review of chunk-2 flagged four state-machine gaps. Each fix has
# a direct replay test.


def test_next_d1_init_state_does_not_suggest_promote(tmp_path: Path) -> None:
    """`/bsa-start --mode=discovery_then_bsa` emits discovery.d1.ready
    at init time. Presence of the ready marker alone does NOT mean the
    d0-problem-framer worker ran. Pre-fix, bsa next said "all markers
    present → /bsa-promote" which would either (a) hit the hook check
    (which only looks at the ready marker, so it would PASS → wrong
    canonical state) or (b) confuse the operator about the workflow.
    Post-fix, bsa next checks proposals/d1/ emptiness and points at
    `/bsa-stage d1 run` when the worker hasn't produced output yet."""
    ws = _init_workspace(tmp_path, {
        "RunID": "d-init",
        "Mode": "discovery_then_bsa",
        "CurrentStage": "d1",
        "CanonPolicyVersion": "1.0.0",
    })
    # Simulate /bsa-start emitting the ready marker:
    _write_marker(ws, "discovery.d1.ready.json", {
        "marker_id": "discovery.d1.ready",
        "stage": "d1",
        "verdict": "READY",
        "timestamp": "2026-04-22T10:00:00Z",
        "canon_policy_version": "1.0.0",
    }, discovery=True)
    # discovery/proposals/d1/ either doesn't exist or is empty.
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    assert "/bsa-stage d1 run" in result.stdout
    # Must NOT suggest promote at init.
    assert "/bsa-promote" not in result.stdout


def test_next_d1_with_proposal_output_suggests_promote(tmp_path: Path) -> None:
    """Post-worker-run state: proposals/d1/ has files → ready to promote."""
    ws = _init_workspace(tmp_path, {
        "RunID": "d-ready",
        "Mode": "discovery_then_bsa",
        "CurrentStage": "d1",
        "CanonPolicyVersion": "1.0.0",
    })
    _write_marker(ws, "discovery.d1.ready.json", {
        "marker_id": "discovery.d1.ready",
        "stage": "d1",
        "verdict": "READY",
        "timestamp": "2026-04-22T10:00:00Z",
        "canon_policy_version": "1.0.0",
    }, discovery=True)
    # Simulate d0-problem-framer producing output:
    prop_dir = ws / "analysis" / "discovery" / "proposals" / "d1"
    prop_dir.mkdir(parents=True)
    (prop_dir / "problem_framing.md").write_text("# problem framing\n", encoding="utf-8")
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    assert "/bsa-promote" in result.stdout


def test_next_presence_checks_filenames_not_payload_marker_ids(tmp_path: Path) -> None:
    """Codex review: a misnamed file whose payload carries a recognized
    marker_id must NOT trigger "ready to promote" — the hook checks
    filenames, so bsa next must check filenames too.
    """
    ws = _init_workspace(tmp_path)
    # File named "wrong.json" carrying marker_id=stage1.excerpts.merged.
    # Pre-fix, _collect_marker_ids (payload-based) would include the
    # payload's marker_id, so suggest_next would green-light /bsa-promote.
    # Post-fix, _collect_marker_filenames (disk-based) returns {"wrong"},
    # which is NOT in the required-marker set → suggest stage run.
    (ws / "analysis" / "runtime" / "ready" / "wrong.json").write_text(
        json.dumps({
            "marker_id": "stage1.excerpts.merged",
            "stage": "stage1",
            "verdict": "MERGED",
            "timestamp": "2026-04-22T10:00:00Z",
            "canon_policy_version": "1.0.0",
        }),
        encoding="utf-8",
    )
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    # Must suggest running stage1 (filename-based gate not satisfied),
    # NOT /bsa-promote.
    assert "/bsa-stage 1 run" in result.stdout
    assert "/bsa-promote" not in result.stdout


def test_next_discovery_complete_without_bridge_surfaces_broken_state(tmp_path: Path) -> None:
    """Codex review: discovery.complete without bridge marker AND
    without main-cycle progress is a broken state (discovery exit
    declared but bridge emission failed). Previously this fell into
    the "main-cycle markers present" message even when no markers
    were present. Fixed to surface an inspect-and-recover guidance."""
    ws = _init_workspace(tmp_path, {
        "RunID": "broken-d",
        "Mode": "discovery_then_bsa",
        "CurrentStage": "discovery.complete",
        "CanonPolicyVersion": "1.0.0",
    })
    # NO bridge marker, NO main-cycle markers.
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    # Should advise about the broken bridge state.
    assert "bridge marker" in result.stdout or "bsa.stage1.entry.enabled" in result.stdout
    assert "/bsa-status" in result.stdout


def test_next_handoff_without_stage8_does_not_suggest_bogus_stage_run(tmp_path: Path) -> None:
    """Codex review: `CurrentStage=handoff` with stage8.no_new_claims.pass
    missing previously suggested `/bsa-stage handoff run` — no such
    command exists. Fixed to point operator back at Stage 8 first."""
    ws = _init_workspace(tmp_path, {
        "RunID": "broken-handoff",
        "Mode": "direct",
        "CurrentStage": "handoff",
        "CanonPolicyVersion": "1.0.0",
    })
    # No markers at all.
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    # Must NOT suggest "/bsa-stage handoff run".
    assert "/bsa-stage handoff run" not in result.stdout
    # Must point at Stage 8 flow.
    assert "stage 8" in result.stdout.lower() or "stage8" in result.stdout.lower()
    assert "stage8.no_new_claims.pass" in result.stdout


# ---- v1.0.4 chunk-2 round-3 regression guards -----------------------
# Codex re-review of chunk-2 round-2 flagged that HIGH-2 was only
# partially closed: _collect_marker_filenames unioned both zones, so a
# correctly-named marker in the wrong zone could still make bsa next
# suggest /bsa-promote while the hook blocks it. Fixed by zone-aware
# _zone_filenames_for_stage(ws, stage). These tests cover both
# directions of wrong-zone placement.


def test_next_main_stage_ignores_marker_in_discovery_zone(tmp_path: Path) -> None:
    """stage1.excerpts.merged.json placed in analysis/discovery/runtime/ready/
    (wrong zone) must NOT satisfy the stage1 promote gate. The hook
    looks only at analysis/runtime/ready/ for main-cycle stages, so
    bsa next must do the same to avoid a false-positive /bsa-promote."""
    ws = _init_workspace(tmp_path, {
        "RunID": "wrong-zone-main",
        "Mode": "direct",
        "CurrentStage": "stage1",
        "CanonPolicyVersion": "1.0.0",
    })
    # Put the correctly-NAMED marker in the WRONG zone (discovery).
    _write_marker(ws, "stage1.excerpts.merged.json", {
        "marker_id": "stage1.excerpts.merged",
        "stage": "stage1",
        "verdict": "MERGED",
        "timestamp": "2026-04-22T10:00:00Z",
        "canon_policy_version": "1.0.0",
    }, discovery=True)
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    # Must suggest running stage1 (main zone empty), NOT /bsa-promote.
    assert "/bsa-stage 1 run" in result.stdout
    assert "/bsa-promote" not in result.stdout


def test_next_discovery_stage_ignores_marker_in_main_zone(tmp_path: Path) -> None:
    """discovery.d2.claims.merged.json placed in analysis/runtime/ready/
    (wrong zone) must NOT satisfy the d2 promote gate. Discovery
    stages look at the discovery zone only."""
    ws = _init_workspace(tmp_path, {
        "RunID": "wrong-zone-discovery",
        "Mode": "discovery_then_bsa",
        "CurrentStage": "d2",
        "CanonPolicyVersion": "1.0.0",
    })
    # Put both correctly-NAMED d2 markers in the WRONG zone (main).
    _write_marker(ws, "discovery.d2.claims.merged.json", {
        "marker_id": "discovery.d2.claims.merged",
        "stage": "d2",
        "verdict": "MERGED",
        "timestamp": "2026-04-22T09:00:00Z",
        "canon_policy_version": "1.0.0",
    })  # main zone
    _write_marker(ws, "discovery.d2.research_quality.pass.json", {
        "marker_id": "discovery.d2.research_quality.pass",
        "stage": "d2",
        "verdict": "PASS",
        "timestamp": "2026-04-22T09:30:00Z",
        "canon_policy_version": "1.0.0",
    })  # main zone
    result = _run_cli(["-w", str(ws), "next"])
    assert result.returncode == 0
    # Hook looks at discovery zone → empty → d2 promote would be
    # blocked → bsa next must point at /bsa-stage d2 run.
    assert "/bsa-stage d2 run" in result.stdout
    assert "/bsa-promote" not in result.stdout


# ---- 9. Doctor (chunk 3) --------------------------------------------


def test_doctor_uninitialized_workspace_exits_2(tmp_path: Path) -> None:
    """Doctor refuses to run on a directory that's not a BSA workspace
    — same 'guard at the door' pattern as `status` and `next`."""
    result = _run_cli(["-w", str(tmp_path), "doctor"])
    assert result.returncode == 2
    assert "not a BSA workspace" in result.stderr


def test_doctor_minimal_clean_workspace_returns_zero(tmp_path: Path) -> None:
    """A minimally-initialized workspace (just A48, empty marker dirs,
    no A70) should pass all four orchestrated validators + the content
    walk. Confirms the SKIP branches behave correctly."""
    ws = _init_workspace(tmp_path)
    result = _run_cli(["-w", str(ws), "doctor"])
    assert result.returncode == 0, (
        f"expected ALL CLEAN; stdout=\n{result.stdout}\nstderr=\n{result.stderr}"
    )
    assert "ALL CLEAN" in result.stdout
    # All five sections present in expected order.
    for section in (
        "marker chain (main):",
        "marker chain (discovery):",
        "A51 reconciliation:",
        "no-new-stories:",
        "privacy scan:",
        "content validation:",
    ):
        assert section in result.stdout, f"missing section: {section}"


def test_doctor_no_a70_skips_no_new_stories(tmp_path: Path) -> None:
    """no-new-stories is a Phase-3 auditor — it has no signal until
    A70 exists. Doctor must SKIP rather than FAIL on pre-Phase-3
    workspaces."""
    ws = _init_workspace(tmp_path)
    result = _run_cli(["-w", str(ws), "doctor"])
    assert "no-new-stories: SKIP" in result.stdout
    # Even with the SKIP, overall result is clean.
    assert result.returncode == 0


def test_doctor_flags_a51_reconciliation_drift(tmp_path: Path) -> None:
    """Manufacture an A51 reconciliation finding: marker says A51-001
    is resolved, but A51 register has it as `open`. validate_a51_
    reconciliation should fire; doctor must surface it as a FAIL
    section and exit 1."""
    ws = _init_workspace(tmp_path)
    _write_a51(ws, [
        {"A51Ref": "A51-001", "IssueType": "uncertainty", "Severity": "high",
         "BlockingStatus": "hard", "RaisedByStage": "stage1",
         "NextAction": "x", "ResolutionStatus": "open"},
    ])
    # A marker that claims A51-001 is resolved — disagrees with the register.
    _write_marker(ws, "stage3.citation_audit.pass.json", {
        "marker_id": "stage3.citation_audit.pass",
        "stage": "stage3",
        "verdict": "PASS",
        "timestamp": "2026-04-22T10:00:00Z",
        "canon_policy_version": "1.0.0",
        "notes": "A51-001 resolved during stage3 review",
    })
    result = _run_cli(["-w", str(ws), "doctor"])
    assert result.returncode == 1
    assert "A51 reconciliation: FAIL" in result.stdout
    assert "A51-001" in result.stdout


def test_doctor_flags_malformed_canonical_marker(tmp_path: Path) -> None:
    """A marker missing required fields trips marker_chain (which is
    schema-only) and the content walk (which dispatches into the F5
    write-validator). Doctor surfaces both."""
    ws = _init_workspace(tmp_path)
    # Missing required `marker_id`, `stage`, `verdict`,
    # `canon_policy_version` — both validators should object.
    (ws / "analysis" / "runtime" / "ready" / "stage1.ready.json").write_text(
        json.dumps({"timestamp": "2026-04-22T10:00:00Z"}), encoding="utf-8"
    )
    result = _run_cli(["-w", str(ws), "doctor"])
    assert result.returncode == 1
    assert "marker chain (main): FAIL" in result.stdout
    # Content walk should also flag this file by relative path.
    assert "content validation: FAIL" in result.stdout
    assert "stage1.ready.json" in result.stdout


def test_doctor_does_not_corrupt_plugin_privacy_audit_md(tmp_path: Path) -> None:
    """Regression for chunk-3 internal bug: privacy_scan.py defaults
    `--output` to `<plugin-repo>/docs/privacy_audit.md`. Doctor against
    an EXTERNAL workspace must NOT write into the plugin repo's own
    audit file. Doctor must pass `--output <tmp>` to keep the plugin
    repo untouched."""
    ws = _init_workspace(tmp_path)
    plugin_audit = REPO_ROOT / "docs" / "privacy_audit.md"
    if not plugin_audit.is_file():
        pytest.skip("plugin docs/privacy_audit.md missing — bootstrap state")
    before = plugin_audit.read_text(encoding="utf-8")
    result = _run_cli(["-w", str(ws), "doctor"])
    assert result.returncode == 0, result.stderr
    after = plugin_audit.read_text(encoding="utf-8")
    assert before == after, (
        "doctor mutated <plugin-repo>/docs/privacy_audit.md when run "
        "against an external workspace — privacy_scan --output must be "
        "redirected to a temp file"
    )


def test_doctor_workspace_flag_must_precede_subcommand(tmp_path: Path) -> None:
    """Argparse-shape regression: `--workspace` lives on the TOP-level
    parser (per chunks 1+2 design), so it must appear BEFORE the
    `doctor` subcommand. Document and pin this so we don't silently
    move it to subcommand-level later (which would break invocations
    in the help text + bash wrapper docs)."""
    ws = _init_workspace(tmp_path)
    # Wrong order — flag AFTER subcommand — should fail with arg error.
    wrong = _run_cli(["doctor", "-w", str(ws)])
    assert wrong.returncode != 0
    assert "unrecognized arguments" in wrong.stderr or "error" in wrong.stderr.lower()
    # Correct order — flag BEFORE subcommand — succeeds.
    right = _run_cli(["-w", str(ws), "doctor"])
    assert right.returncode == 0, right.stderr


def test_doctor_privacy_scan_actually_scans_analysis_tree(tmp_path: Path) -> None:
    """Codex round-1 HIGH: `privacy_scan.py` has `analysis` in
    DEFAULT_SKIP_DIR_NAMES, so running with `--root <workspace>`
    silently scans NOTHING in a normal BSA workspace (all content
    lives under analysis/). Fix: point --root at <workspace>/analysis
    instead.

    Regression: drop a real-looking blocker finding under
    analysis/ and confirm doctor's privacy section surfaces it.
    """
    ws = _init_workspace(tmp_path)
    # Plant a file the privacy scanner is expected to flag. A
    # corporate-looking email triggers the `email` detector at
    # BLOCKER severity (per privacy_scan.py: "email: blocker if
    # corporate-looking domain; info if test/local TLD"). We nest it
    # under analysis/discovery/ so the test depends on doctor
    # pointing `--root` INTO analysis/ (not at the workspace root
    # where DEFAULT_SKIP_DIR_NAMES would skip it).
    #
    # IMPORTANT: the email literal is SPLIT across Python string
    # concatenation so THIS TEST FILE itself does not contain the
    # full pattern — otherwise `test_scan_baseline_has_no_blockers`
    # would fail on repo-wide scan. The scanner's EMAIL_RE requires
    # a contiguous token on one line.
    leaked = ws / "analysis" / "discovery" / "d1_leaked_snippet.txt"
    leaked.parent.mkdir(parents=True, exist_ok=True)
    leaked.write_text(
        "# Leaked transcript line\n"
        "From: " + "payroll" + "@" + "bigcorp-acme-industries" + ".com\n",
        encoding="utf-8",
    )
    result = _run_cli(["-w", str(ws), "doctor"])
    # Non-zero because privacy scan flagged the secret.
    assert result.returncode == 1, (
        f"expected privacy finding to set exit=1; got {result.returncode}\n"
        f"stdout=\n{result.stdout}\nstderr=\n{result.stderr}"
    )
    assert "privacy scan: FAIL" in result.stdout, (
        "doctor must surface privacy findings under analysis/ — if this "
        "section says OK, privacy_scan was invoked with a --root that "
        "DEFAULT_SKIP_DIR_NAMES short-circuits. Re-check cmd_doctor's "
        "privacy branch."
    )


def test_iter_workspace_canonical_files_strict_raises_when_analysis_missing(tmp_path: Path) -> None:
    """Codex round-4: the only way to close the content-walk false-clean
    race (analysis/ disappears between the privacy-scan branch and the
    content-walk enumeration) is to have the helper itself signal the
    missing-analysis case. `strict=True` makes that signal explicit
    via FileNotFoundError; legacy `strict=False` keeps the silent
    `return []` for non-doctor callers."""
    # Late import to avoid module-side-effects.
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts.bsa_cli import (  # type: ignore[import-not-found]
            WorkspaceState,
            _iter_workspace_canonical_files,
        )
    finally:
        sys.path.pop(0)
    ws = WorkspaceState(tmp_path)  # tmp_path has no analysis/ yet
    # Default (strict=False): silent empty list.
    assert _iter_workspace_canonical_files(ws) == []
    # strict=True: explicit signal.
    with pytest.raises(FileNotFoundError):
        _iter_workspace_canonical_files(ws, strict=True)


def test_doctor_separates_error_from_fail_exit_codes(tmp_path: Path) -> None:
    """Codex round-1 MEDIUM: when a validator returns rc=2 (invocation
    error, e.g., missing script) doctor must distinguish that from
    rc=1 (workspace issues) so CI can tell "doctor is broken" from
    "workspace is dirty". Exit code 2 is reserved for the ERROR class.

    We force rc=2 by running `doctor` against an external workspace
    that is not initialized — `cmd_doctor` itself bails with rc=2
    before running any validator. This test pins the invariant
    "doctor returns 2 when it can't diagnose" from the user-facing side.
    """
    # Empty dir → WorkspaceState.is_initialized() is False.
    result = _run_cli(["-w", str(tmp_path), "doctor"])
    assert result.returncode == 2


def test_doctor_exits_with_summary_line(tmp_path: Path) -> None:
    """Both clean and failing runs must end with a single-line
    Summary, so callers (humans + CI) can grep for it."""
    ws = _init_workspace(tmp_path)
    clean = _run_cli(["-w", str(ws), "doctor"])
    assert any(
        line.startswith("Summary:") for line in clean.stdout.splitlines()
    ), "Summary line missing from clean run"
    # Force a failure (same shape as the malformed-marker test).
    (ws / "analysis" / "runtime" / "ready" / "stage1.ready.json").write_text(
        "{}", encoding="utf-8"
    )
    fail = _run_cli(["-w", str(ws), "doctor"])
    assert any(
        line.startswith("Summary:") for line in fail.stdout.splitlines()
    ), "Summary line missing from failing run"


def test_last_marker_uses_emittedat_for_pilot1_markers(tmp_path: Path) -> None:
    """Codex review: `last_marker()` only read `timestamp`. Pilot-1-class
    drifted markers use `emittedAt`. Fixed to accept either."""
    ws = _init_workspace(tmp_path, {
        "RunID": "emittedat-test",
        "Mode": "discovery_then_bsa",
        "CurrentStage": "d1",
        "CanonPolicyVersion": "1.0.0",
    })
    # Older marker (would be "last" if only timestamp is considered).
    _write_marker(
        ws,
        "discovery.d1.ready.json",
        {
            "marker_id": "discovery.d1.ready",
            "stage": "d1",
            "verdict": "READY",
            "timestamp": "2026-04-22T08:00:00Z",
            "canon_policy_version": "1.0.0",
        },
        discovery=True,
    )
    # Newer Pilot-1-drifted marker — uses emittedAt instead of timestamp.
    _write_marker(
        ws,
        "discovery.d2.ready.json",
        {
            "marker": "discovery.d2.ready",
            "runId": "x",
            "emittedAt": "2026-04-22T09:00:00Z",
        },
        discovery=True,
    )
    result = _run_cli(["-w", str(ws), "status"])
    assert result.returncode == 0
    # The Pilot-1-drifted d2 marker should win the "Last marker" line
    # because emittedAt 09:00 > timestamp 08:00. Pre-fix, the drifted
    # marker was ignored in recency sorting; conformant d1 marker won.
    last_line = [
        line for line in result.stdout.splitlines() if line.startswith("Last marker:")
    ]
    assert last_line, "Last marker line missing from output"
    assert "discovery.d2.ready" in last_line[0]


# ---- 10. Materials (chunk 4) -----------------------------------------


def _make_src_dir(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a source dir under tmp_path/src with named files."""
    src = tmp_path / "src"
    src.mkdir()
    for name, body in files.items():
        (src / name).write_text(body, encoding="utf-8")
    return src


def test_materials_missing_src_dir_exits_2(tmp_path: Path) -> None:
    """Bad src arg → exit 2 with clear message."""
    ws = _init_workspace(tmp_path)
    result = _run_cli(["-w", str(ws), "materials", str(tmp_path / "nope")])
    assert result.returncode == 2
    assert "source directory not found" in result.stderr


def test_materials_uninitialized_workspace_exits_2(tmp_path: Path) -> None:
    """Workspace must be initialized before staging."""
    src = _make_src_dir(tmp_path, {"a.md": "x"})
    result = _run_cli(["-w", str(tmp_path / "blank"), "materials", str(src)])
    assert result.returncode == 2
    assert "not a BSA workspace" in result.stderr


def test_materials_dry_run_writes_nothing(tmp_path: Path) -> None:
    """Default behavior is preview — no files appear in the workspace,
    no manifest created. The exit code is 0 (preview rendered OK)."""
    ws = _init_workspace(tmp_path)
    src = _make_src_dir(tmp_path, {
        "Procurement Policy v4.2.md": "# Policy\nbody",
        "Interview Alex.txt": "transcript",
    })
    result = _run_cli(["-w", str(ws), "materials", str(src)])
    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
    assert "S-001" in result.stdout
    assert "S-002" in result.stdout
    # Nothing written.
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    assert not inputs.exists()
    manifest = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    assert not manifest.exists()


def test_materials_commit_writes_inputs_and_manifest(tmp_path: Path) -> None:
    """--commit actually writes converted files + draft manifest."""
    ws = _init_workspace(tmp_path)
    src = _make_src_dir(tmp_path, {
        "Procurement Policy v4.2.md": "# Policy v4.2\nbody",
        "Interview Alex.txt": "transcript with Alex",
    })
    result = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert result.returncode == 0, result.stderr
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    files = sorted(p.name for p in inputs.iterdir())
    assert files == [
        "source_001_interview_alex.md",
        "source_002_procurement_policy_v4_2.md",
    ], files
    # The version marker `v4_2` must survive the slug — early bug
    # double-stripped it to `v4`.
    body = (inputs / "source_002_procurement_policy_v4_2.md").read_text(encoding="utf-8")
    assert "Policy v4.2" in body
    # Provenance comment present.
    assert "bsa materials" in body
    assert "SourceID=S-002" in body
    # Manifest has header + 2 rows; T5 default; corp-clean Origins.
    manifest = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("SourceID,SourceType,Title,Origin")
    assert lines[1].startswith("S-001,interview_transcript,")
    assert ",T5," in lines[1]
    assert lines[2].startswith("S-002,process_note,")
    assert ",T5," in lines[2]


def test_materials_idempotent_re_run_skips_already_staged(tmp_path: Path) -> None:
    """Re-running on the SAME src dir must NOT duplicate-stage:
    existing Origin entries in source_manifest.csv are detected and
    skipped. Manifest stays stable; no new files written."""
    ws = _init_workspace(tmp_path)
    src = _make_src_dir(tmp_path, {"a.md": "x", "b.md": "y"})
    # First run: writes both.
    first = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert first.returncode == 0
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    manifest = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    files_before = sorted(p.name for p in inputs.iterdir())
    manifest_before = manifest.read_text(encoding="utf-8")
    # Second run with same args.
    second = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert second.returncode == 0
    assert "Wrote 0 file(s)" in second.stdout
    assert "already staged" in second.stdout
    # No new files; manifest byte-equal.
    files_after = sorted(p.name for p in inputs.iterdir())
    assert files_after == files_before
    assert manifest.read_text(encoding="utf-8") == manifest_before


def test_materials_force_overwrites(tmp_path: Path) -> None:
    """--force re-stages files that idempotency would skip; manifest
    grows by the re-staged rows."""
    ws = _init_workspace(tmp_path)
    src = _make_src_dir(tmp_path, {"a.md": "v1"})
    _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    # Mutate source between runs to verify the new content lands.
    (src / "a.md").write_text("v2 body", encoding="utf-8")
    second = _run_cli(["-w", str(ws), "materials", str(src), "--commit", "--force"])
    assert second.returncode == 0
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    files = sorted(p.name for p in inputs.iterdir())
    # First run took S-001; --force re-stages with a NEW SourceID
    # (S-002) since SourceID assignment is monotonic.
    assert "source_001_a.md" in files
    assert "source_002_a.md" in files
    assert "v2 body" in (inputs / "source_002_a.md").read_text(encoding="utf-8")


def test_materials_unsupported_files_reported_separately(tmp_path: Path) -> None:
    """Files with unsupported extensions are listed in the report
    but do not abort the run; convertible files still proceed."""
    ws = _init_workspace(tmp_path)
    src = _make_src_dir(tmp_path, {
        "ok.md": "good",
        "bin.exe": "junk",
        "image.png": "binary-stub",
    })
    result = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert result.returncode == 0
    assert "Unsupported (not staged)" in result.stdout
    assert "bin.exe" in result.stdout
    assert "image.png" in result.stdout
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    files = [p.name for p in inputs.iterdir()]
    assert files == ["source_001_ok.md"]


def test_materials_empty_src_dir_exits_2(tmp_path: Path) -> None:
    """An empty source dir is an error — there's nothing to stage."""
    ws = _init_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    result = _run_cli(["-w", str(ws), "materials", str(src)])
    assert result.returncode == 2
    assert "no files found" in result.stderr


def test_materials_recursive_walks_subdirectories(tmp_path: Path) -> None:
    """Without --recursive, subdirs are ignored; with --recursive, they
    are walked."""
    ws = _init_workspace(tmp_path)
    src = tmp_path / "src"
    sub = src / "interviews"
    sub.mkdir(parents=True)
    (src / "top.md").write_text("top", encoding="utf-8")
    (sub / "deep.md").write_text("deep", encoding="utf-8")
    flat = _run_cli(["-w", str(ws), "materials", str(src)])
    assert flat.returncode == 0
    assert "top.md" in flat.stdout
    assert "deep.md" not in flat.stdout
    deep = _run_cli(["-w", str(ws), "materials", str(src), "--recursive"])
    assert deep.returncode == 0
    assert "top.md" in deep.stdout
    assert "deep.md" in deep.stdout


def test_materials_skips_hidden_files_and_dirs(tmp_path: Path) -> None:
    """`.DS_Store`, `.git/`, etc. must not pollute the planned set."""
    ws = _init_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / ".DS_Store").write_text("junk", encoding="utf-8")
    (src / ".hidden.md").write_text("hidden", encoding="utf-8")
    git = src / ".git"
    git.mkdir()
    (git / "config").write_text("x", encoding="utf-8")
    (src / "real.md").write_text("real body", encoding="utf-8")
    result = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert result.returncode == 0
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    files = [p.name for p in inputs.iterdir()]
    assert files == ["source_001_real.md"]


def test_materials_pdf_unavailable_raises_with_install_hint(
    tmp_path: Path, monkeypatch
) -> None:
    """When `pypdf` is not importable, _convert_pdf must raise
    ConversionUnavailable with an install hint pointing at
    `pip install pypdf`. We test the module helper directly because
    subprocess-isolation prevents monkey-patching sys.modules in
    the child via `_run_cli`."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts.bsa_cli import _convert_pdf, ConversionUnavailable
    finally:
        sys.path.pop(0)
    pdf = tmp_path / "stub.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    # Setting sys.modules['pypdf'] = None makes `import pypdf` raise
    # ImportError inside _convert_pdf (the documented stdlib trick
    # for masking an installed module in a single test).
    monkeypatch.setitem(sys.modules, "pypdf", None)
    with pytest.raises(ConversionUnavailable) as exc:
        _convert_pdf(pdf)
    assert "pip install pypdf" in str(exc.value)


def test_materials_install_hint_emitted_in_summary(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: when ANY file's converter raises ConversionUnavailable,
    cmd_materials must print the corresponding install hint in the
    summary block (so users hit by the missing-lib trap know what to
    install). We invoke cmd_materials in-process so we can mask
    pypdf via sys.modules before the call."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts.bsa_cli import cmd_materials
    finally:
        sys.path.pop(0)
    ws = _init_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "doc.pdf").write_bytes(b"%PDF-1.4\n")

    # Mask pypdf (and an unused docx, to make sure only the relevant
    # hint is emitted).
    monkeypatch.setitem(sys.modules, "pypdf", None)

    import argparse, io, contextlib
    args = argparse.Namespace(
        workspace=str(ws), src_dir=str(src),
        commit=True, force=False, recursive=False,
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_materials(args)
    out = buf.getvalue()
    assert rc == 1, out
    assert "doc.pdf" in out
    assert "pip install pypdf" in out
    # Did NOT spuriously include the docx hint when no docx file present.
    assert "pip install python-docx" not in out


def test_materials_preserves_versioned_filenames(tmp_path: Path) -> None:
    """Slug must NOT eat trailing `vN.M` version segments. Early
    Path.stem-twice bug stripped `v4.2` to `v4`."""
    ws = _init_workspace(tmp_path)
    src = _make_src_dir(tmp_path, {
        "Doc v4.2.md": "x",
        "Other v10.3.5.md": "y",
    })
    result = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert result.returncode == 0
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    names = sorted(p.name for p in inputs.iterdir())
    assert "source_001_doc_v4_2.md" in names
    assert "source_002_other_v10_3_5.md" in names


def test_materials_refuses_when_analysis_is_symlink(tmp_path: Path) -> None:
    """Codex round-1 HIGH: --commit must NOT follow a symlinked
    workspace path. Even an in-tree symlink is rejected — defense in
    depth (a future swap could redirect writes)."""
    # Initialize a clean workspace, then replace `analysis/` with a
    # symlink to a sibling directory. Even though the sibling is
    # under tmp_path, the symlink itself is suspicious.
    real = tmp_path / "real_analysis_dir"
    real.mkdir()
    (real / "canonical" / "core_controls").mkdir(parents=True)
    (real / "canonical" / "core_controls" / "A48_run_context_card.md").write_text(
        "# A48\n- `RunID`: x\n- `Mode`: direct\n- `CurrentStage`: stage1\n"
        "- `CanonPolicyVersion`: 1.0.0\n",
        encoding="utf-8",
    )
    try:
        (tmp_path / "analysis").symlink_to(real)
    except OSError:
        pytest.skip("symlink unsupported on this platform")
    src = _make_src_dir(tmp_path, {"a.md": "x"})
    result = _run_cli(["-w", str(tmp_path), "materials", str(src), "--commit"])
    assert result.returncode == 2
    assert "symlink" in result.stderr.lower()
    # Real dir was NOT written to.
    assert not (real / "proposals").exists()


def test_materials_slug_idempotency_without_manifest(tmp_path: Path) -> None:
    """Codex round-1 HIGH: if source_manifest.csv is deleted but
    inputs/ still has source_NNN_<slug>.md files, re-running must NOT
    duplicate-stage by slug. Backstop fires from the inputs/ scan."""
    ws = _init_workspace(tmp_path)
    src = _make_src_dir(tmp_path, {"foo.md": "v1"})
    first = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert first.returncode == 0
    # Delete the manifest; keep inputs/.
    manifest = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    manifest.unlink()
    # Re-run.
    second = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert second.returncode == 0
    assert "Wrote 0 file(s)" in second.stdout
    assert "same slug already staged" in second.stdout
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    files = sorted(p.name for p in inputs.iterdir())
    assert files == ["source_001_foo.md"]  # no source_002_foo.md duplicate


def test_materials_routes_around_existing_input_symlink_default(tmp_path: Path) -> None:
    """Codex round-2 HIGH (default-mode case): a pre-existing
    symlinked source_NNN_<slug>.md must NOT be overwritten via the
    symlink. Default mode: slug-collision routing detects the
    collision (provenance comment absent on the symlink target),
    allocates an alternative slug, writes elsewhere — symlink
    target file untouched."""
    ws = _init_workspace(tmp_path)
    src = _make_src_dir(tmp_path, {"foo.md": "v2"})
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    inputs.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere.md"
    elsewhere.write_text("PRE-EXISTING\n", encoding="utf-8")
    try:
        (inputs / "source_001_foo.md").symlink_to(elsewhere)
    except OSError:
        pytest.skip("symlink unsupported on this platform")
    result = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert result.returncode == 0, result.stderr
    # Symlink target is byte-equal — write was NOT redirected.
    assert elsewhere.read_text(encoding="utf-8") == "PRE-EXISTING\n"
    # New file landed under an alternative slug variant.
    files = sorted(p.name for p in inputs.iterdir() if not p.is_symlink())
    assert any(f.startswith("source_") and f != "source_001_foo.md" for f in files)


# Note: a "force overwrites through symlink" test would be useful
# to pin the per-target leaf-symlink check in cmd_materials, but
# the combination of monotonic `_next_source_id` allocation + slug-
# collision routing means a planned target name can't actually BE a
# pre-existing symlink in any reachable code path. The per-target
# check stays as defense-in-depth (cheap to keep), but exercising
# it requires monkey-patching the planner internals — out of scope
# for chunk 4.


def test_materials_refuses_when_manifest_is_symlink(tmp_path: Path) -> None:
    """Same defense for source_manifest.csv itself: a symlinked
    manifest could redirect writes outside the workspace."""
    ws = _init_workspace(tmp_path)
    src = _make_src_dir(tmp_path, {"foo.md": "x"})
    stage1 = ws / "analysis" / "proposals" / "stage1"
    stage1.mkdir(parents=True)
    elsewhere = tmp_path / "fake_manifest.csv"
    elsewhere.write_text(
        "SourceID,SourceType,Title,Origin,AccessStatus,ReliabilityTier,"
        "Priority,Language,DateOrVersion,Notes\n",
        encoding="utf-8",
    )
    try:
        (stage1 / "source_manifest.csv").symlink_to(elsewhere)
    except OSError:
        pytest.skip("symlink unsupported on this platform")
    result = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert result.returncode == 2
    assert "symlink" in result.stderr.lower()
    # The fake-manifest target must remain unchanged.
    assert elsewhere.read_text(encoding="utf-8").splitlines()[0].startswith("SourceID,")
    # Header line only — no rows appended.
    assert len(elsewhere.read_text(encoding="utf-8").splitlines()) == 1


def test_materials_slug_collision_with_different_source_uses_unique_slug(
    tmp_path: Path,
) -> None:
    """Codex round-2 MEDIUM: slug-only idempotency was a false-
    positive guillotine — two distinct sources whose 40-char-
    truncated slugs collide were both skipped. Round-2 fix consults
    the existing file's provenance comment to disambiguate; if
    Origins differ, allocate a unique slug variant."""
    ws = _init_workspace(tmp_path)
    src = _make_src_dir(tmp_path, {
        # Two filenames that, after slugify, collide on the first 40 chars
        # but represent legitimately different sources. The slugifier
        # truncates to 40; both produce
        # "the_quick_brown_fox_jumps_over_the_lazy".
        "The Quick Brown Fox Jumps Over The Lazy DOG.md": "v1",
        "The Quick Brown Fox Jumps Over The Lazy CAT.md": "v2",
    })
    result = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert result.returncode == 0, result.stderr
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    files = sorted(p.name for p in inputs.iterdir())
    # Both files should land under DIFFERENT target names — the second
    # gets a hash-suffixed slug variant. Without the fix the second
    # would have been skipped as "same slug already staged".
    assert len(files) == 2, files
    # Bodies preserve content from each distinct source (no clobber).
    bodies = {f: (inputs / f).read_text(encoding="utf-8") for f in files}
    contents = "\n".join(bodies.values())
    assert "v1" in contents and "v2" in contents


def test_materials_recursive_distinct_basenames_not_falsely_skipped(
    tmp_path: Path,
) -> None:
    """Codex round-3 MEDIUM (reproduced as round-4 LOW notes): test
    must actually exercise the slug-collision-via-provenance path.
    Setup: stage team_a/foo.md FIRST so its provenance comment is on
    disk. Then DELETE the manifest. Then add team_b/foo.md to src
    and re-run --recursive. Round-3 invariant: the team_b file must
    be staged under an alt slug (provenance differs); team_a file
    skipped (provenance matches). Pre-fix, basename equality made
    team_b a false-positive skip."""
    ws = _init_workspace(tmp_path)
    src = tmp_path / "src"
    (src / "team_a").mkdir(parents=True)
    (src / "team_a" / "foo.md").write_text("from A", encoding="utf-8")
    # First run: stage team_a/foo.md alone.
    first = _run_cli(["-w", str(ws), "materials", str(src),
                      "--recursive", "--commit"])
    assert first.returncode == 0, first.stderr
    inputs = ws / "analysis" / "proposals" / "stage1" / "inputs"
    assert (inputs / "source_001_foo.md").is_file()
    # Sanity: provenance comment uses the canonical relative-path Origin.
    body_a = (inputs / "source_001_foo.md").read_text(encoding="utf-8")
    assert "team_a/foo.md" in body_a, body_a[:200]
    # Delete the manifest to force the slug-collision branch on re-run
    # (without manifest, primary Origin idempotency check sees nothing).
    manifest = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    manifest.unlink()
    # Add team_b/foo.md (same basename, DIFFERENT canonical Origin).
    (src / "team_b").mkdir(parents=True)
    (src / "team_b" / "foo.md").write_text("from B", encoding="utf-8")
    # Re-run.
    second = _run_cli(["-w", str(ws), "materials", str(src),
                       "--recursive", "--commit"])
    assert second.returncode == 0, second.stderr
    inputs_now = sorted(p.name for p in inputs.iterdir())
    # team_a file should be SKIPPED (provenance match: team_a/foo.md).
    # team_b file should be STAGED under an alt slug variant.
    # Net: 2 files in inputs/.
    assert len(inputs_now) == 2, inputs_now
    # The first file is unchanged (still has "from A").
    assert "from A" in (inputs / "source_001_foo.md").read_text(encoding="utf-8")
    # A second file exists with "from B" content. Pre-fix, this would
    # have been false-skipped because basename "foo.md" equality
    # match with team_a/foo.md.
    other = [f for f in inputs_now if f != "source_001_foo.md"][0]
    assert "from B" in (inputs / other).read_text(encoding="utf-8")
    # That second file's provenance comment should hold team_b/foo.md.
    assert "team_b/foo.md" in (inputs / other).read_text(encoding="utf-8")


def test_materials_atomic_write_leaves_manifest_intact_on_failure(
    tmp_path: Path, monkeypatch
) -> None:
    """Codex round-5 MEDIUM: _upsert_draft_manifest used to call
    write_text directly — a mid-write OSError (disk full, etc.) would
    leave a truncated/corrupted manifest. Round-5 fix uses
    _atomic_write_text (tempfile + os.replace), which guarantees the
    original manifest is left untouched on failure.

    We test by monkey-patching os.replace to raise OSError after the
    tempfile has been written — the original manifest must survive
    byte-equal."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts.bsa_cli import _atomic_write_text
    finally:
        sys.path.pop(0)
    target = tmp_path / "subdir" / "manifest.csv"
    target.parent.mkdir()
    target.write_text("ORIGINAL\n", encoding="utf-8")
    snapshot = target.read_bytes()

    import os as _os
    real_replace = _os.replace

    def boom(*a, **kw):
        raise OSError("simulated mid-rename failure")

    monkeypatch.setattr(_os, "replace", boom)
    with pytest.raises(OSError, match="simulated"):
        _atomic_write_text(target, "NEW CONTENT THAT MUST NOT LAND\n")
    # Manifest unchanged.
    assert target.read_bytes() == snapshot
    # No leftover tempfiles in the dir (atomic-write cleans up on failure).
    leftovers = [
        p for p in target.parent.iterdir() if p.suffix == ".tmp"
    ]
    assert leftovers == []
    # Restore for any later test.
    monkeypatch.setattr(_os, "replace", real_replace)


def test_materials_refuses_when_existing_manifest_is_readonly(
    tmp_path: Path,
) -> None:
    """Codex round-6 MEDIUM: with the round-5 atomic-write change,
    `os.replace` swaps inodes governed by parent-dir permission, not
    the destination file's mode. A read-only manifest used to
    refuse new writes via write_text; now it would be silently
    replaced. Pre-flight must check W_OK and refuse."""
    ws = _init_workspace(tmp_path)
    stage1 = ws / "analysis" / "proposals" / "stage1"
    stage1.mkdir(parents=True)
    manifest = stage1 / "source_manifest.csv"
    manifest.write_text(
        "SourceID,SourceType,Title,Origin,AccessStatus,ReliabilityTier,"
        "Priority,Language,DateOrVersion,Notes\n"
        "S-099,document,Pre-existing,manual,readable,T2,high,en,2025-12-01,locked\n",
        encoding="utf-8",
    )
    snapshot = manifest.read_bytes()
    import os as _os
    _os.chmod(manifest, 0o444)
    try:
        src = _make_src_dir(tmp_path, {"x.md": "x"})
        result = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
        assert result.returncode == 2
        assert "not writable" in result.stderr
        # Manifest unchanged.
        assert manifest.read_bytes() == snapshot
        # Inputs should NOT have been written either (pre-flight).
        inputs = stage1 / "inputs"
        assert not inputs.exists() or list(inputs.iterdir()) == []
    finally:
        _os.chmod(manifest, 0o644)


def test_materials_atomic_write_preserves_file_mode(tmp_path: Path) -> None:
    """Codex round-6 MEDIUM (mode-preservation half): _atomic_write_text
    must NOT lose the original file's mode bits. Verify by chmod-ing
    a file 0640 then writing through the helper — mode survives."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts.bsa_cli import _atomic_write_text
    finally:
        sys.path.pop(0)
    target = tmp_path / "manifest.csv"
    target.write_text("v1\n", encoding="utf-8")
    import os as _os
    _os.chmod(target, 0o640)
    pre_mode = _os.stat(target).st_mode & 0o7777
    assert pre_mode == 0o640, f"setup failed: chmod did not stick ({oct(pre_mode)})"
    _atomic_write_text(target, "v2\n")
    post_mode = _os.stat(target).st_mode & 0o7777
    assert post_mode == 0o640, (
        f"file mode lost during atomic replace: {oct(pre_mode)} → {oct(post_mode)}"
    )
    assert target.read_text(encoding="utf-8") == "v2\n"


def test_materials_manifest_path_is_directory_caught_pre_flight(
    tmp_path: Path,
) -> None:
    """Codex round-3 MEDIUM: a directory at source_manifest.csv would
    fail the late write_text() — leaving inputs orphaned. Pre-flight
    must detect non-file existence and refuse before any input writes."""
    ws = _init_workspace(tmp_path)
    stage1 = ws / "analysis" / "proposals" / "stage1"
    stage1.mkdir(parents=True)
    # Plant a directory where the manifest file should be.
    (stage1 / "source_manifest.csv").mkdir()
    src = _make_src_dir(tmp_path, {"x.md": "x"})
    result = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert result.returncode == 2
    assert "not a regular file" in result.stderr
    inputs = stage1 / "inputs"
    # CRITICAL: no input files written.
    assert not inputs.exists() or list(inputs.iterdir()) == []


def test_materials_drifted_header_caught_pre_flight_no_partial_write(
    tmp_path: Path,
) -> None:
    """Codex round-2 MEDIUM: header-drift used to be caught AFTER
    input files were already written, leaving a half-committed
    state. Round-2 moved the check pre-flight; verify zero files
    are written when drift is detected."""
    ws = _init_workspace(tmp_path)
    stage1 = ws / "analysis" / "proposals" / "stage1"
    stage1.mkdir(parents=True)
    # Plant a drifted manifest.
    (stage1 / "source_manifest.csv").write_text(
        "SourceID,WRONG,COLUMNS\nS-099,a,b\n", encoding="utf-8",
    )
    src = _make_src_dir(tmp_path, {"new1.md": "x", "new2.md": "y"})
    result = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert result.returncode == 2
    assert "non-canonical header" in result.stderr
    inputs = stage1 / "inputs"
    # CRITICAL invariant: no input files were written despite --commit.
    assert not inputs.exists() or list(inputs.iterdir()) == []


def test_materials_refuses_drifted_manifest_header(tmp_path: Path) -> None:
    """Codex round-1 HIGH: if an existing manifest has a non-canonical
    header (manual edit, legacy shape, reordered cols), refuse to
    append to avoid row misalignment. Exit 2 + clear stderr."""
    ws = _init_workspace(tmp_path)
    # Stage a manifest with a DIFFERENT (drifted) header.
    stage1 = ws / "analysis" / "proposals" / "stage1"
    stage1.mkdir(parents=True)
    (stage1 / "source_manifest.csv").write_text(
        # Reordered: SourceType moved to second-from-last; Title dropped.
        "SourceID,Origin,AccessStatus,ReliabilityTier,Priority,Language,"
        "DateOrVersion,Notes,SourceType\n"
        "S-099,manually-added,readable,T2,high,en,2025-12-01,note,document\n",
        encoding="utf-8",
    )
    src = _make_src_dir(tmp_path, {"new.md": "x"})
    result = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert result.returncode == 2
    assert "non-canonical header" in result.stderr
    assert "Refuse to append" in result.stderr or "refuse" in result.stderr.lower()


def test_materials_recursive_skips_symlinked_subdirs(tmp_path: Path) -> None:
    """Codex round-1 MEDIUM: --recursive must NOT follow symlinked
    subdirs (would loop forever on `src/loop -> .` and could escape
    the requested src tree)."""
    ws = _init_workspace(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "real.md").write_text("real", encoding="utf-8")
    # Create a self-referential symlink: src/loop -> src
    try:
        (src / "loop").symlink_to(src)
    except OSError:
        pytest.skip("symlink unsupported on this platform")
    result = _run_cli(["-w", str(ws), "materials", str(src), "--recursive"])
    # If we DID follow the symlink, recursion would never terminate;
    # the test would hang. Reaching this assert at all proves the
    # symlink check fired.
    assert result.returncode == 0
    assert "real.md" in result.stdout
    # Should NOT have re-discovered real.md as some inflated count via the loop.
    assert result.stdout.count("real.md") <= 2  # appears once in plan + once in summary


def test_materials_install_hint_no_canonical_header_safety(tmp_path: Path) -> None:
    """Pin: the canonical header constants in bsa_cli match the
    A50 schema's documented column order exactly. If a future schema
    edit reorders A50 columns, both _A50_HEADER and _A50_HEADER_WITH_
    EFFECTIVE_DATE must follow — otherwise drift detection becomes a
    false-positive guillotine."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts.bsa_cli import (
            _A50_HEADER,
            _A50_HEADER_WITH_EFFECTIVE_DATE,
            _A50_HEADER_WITH_HASHES,
        )
    finally:
        sys.path.pop(0)
    schema_path = REPO_ROOT / "governance" / "schemas" / "a50.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    cols = schema["x-bsa-csv-columns-order"]
    documented = ",".join(cols["order"])
    assert _A50_HEADER == documented, (
        f"_A50_HEADER drifted from a50.schema.json. "
        f"_A50_HEADER={_A50_HEADER!r} vs documented={documented!r}. "
        f"Update _A50_HEADER in scripts/bsa_cli.py to match."
    )
    # v1.2.16 R1 fix: also pin the extended-shape variant. Inserts
    # every optional_order column after DateOrVersion (before Notes)
    # in the order they're listed in the schema.
    # v1.4.4: pin all THREE accepted shapes against the schema. We
    # walk optional_order's prefix sequences so the pin survives
    # additions to the optional set without rewriting every variant
    # constant.
    optional = cols.get("optional_order", [])
    base = list(cols["order"])
    notes_idx = base.index("Notes")
    # Variant 1: base + EffectiveDate + Notes (v1.2.16 shape).
    expected_eff = base[:notes_idx] + ["EffectiveDate"] + base[notes_idx:]
    assert _A50_HEADER_WITH_EFFECTIVE_DATE == ",".join(expected_eff), (
        f"_A50_HEADER_WITH_EFFECTIVE_DATE drifted from a50.schema.json. "
        f"_A50_HEADER_WITH_EFFECTIVE_DATE={_A50_HEADER_WITH_EFFECTIVE_DATE!r} "
        f"vs expected={','.join(expected_eff)!r}. Update bsa_cli.py to match."
    )
    # Variant 2: base + EffectiveDate + ContentHash + OriginalBytes
    #          + OriginalMtimeUtc + Notes (v1.4.4 shape — the full
    # optional_order set).
    expected_hashes = base[:notes_idx] + optional + base[notes_idx:]
    assert _A50_HEADER_WITH_HASHES == ",".join(expected_hashes), (
        f"_A50_HEADER_WITH_HASHES drifted from a50.schema.json. "
        f"_A50_HEADER_WITH_HASHES={_A50_HEADER_WITH_HASHES!r} "
        f"vs expected={','.join(expected_hashes)!r}. Update bsa_cli.py to match."
    )


def test_materials_appends_to_existing_manifest_with_effective_date(
    tmp_path: Path,
) -> None:
    """v1.2.16 R1 fix: an existing manifest whose header already
    carries EffectiveDate (operator backfilled) must accept new
    `bsa materials --commit` rows without false-rejecting on
    'non-canonical header'. New rows are aligned to the extended
    shape (empty EffectiveDate cell)."""
    ws = _init_workspace(tmp_path)
    stage1 = ws / "analysis" / "proposals" / "stage1"
    stage1.mkdir(parents=True, exist_ok=True)
    manifest = stage1 / "source_manifest.csv"
    # Operator-backfilled manifest with EffectiveDate column populated.
    manifest.write_text(
        "SourceID,SourceType,Title,Origin,AccessStatus,ReliabilityTier,"
        "Priority,Language,DateOrVersion,EffectiveDate,Notes\n"
        "S-001,document,Existing,operator,readable,T2,medium,en,"
        "2026-02-10,2026-02-10,backfilled\n",
        encoding="utf-8",
    )
    # Stage some new inputs.
    src = _make_src_dir(tmp_path, {"new_doc.md": "x"})
    result = _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    assert result.returncode == 0, (
        f"materials must accept extended-header manifest; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    body = manifest.read_text(encoding="utf-8").splitlines()
    # Header preserved (extended shape, 11 columns).
    assert body[0].endswith(",EffectiveDate,Notes")
    assert body[0].count(",") == 10  # 11 columns → 10 commas
    # Original row preserved.
    assert "S-001," in body[1]
    # New row appended with the SAME column count (i.e., aligned).
    new_row = body[2]
    assert new_row.count(",") == 10, (
        f"appended row column count must match extended header (10 commas); "
        f"row={new_row!r}"
    )


def test_materials_draft_manifest_validates_against_a50_schema(tmp_path: Path) -> None:
    """The draft manifest we emit must be a valid A50 register — the
    same schema the F5 hook would gate at promotion. Run the actual
    write_validator against the manifest and assert clean."""
    ws = _init_workspace(tmp_path)
    src = _make_src_dir(tmp_path, {
        "doc.md": "x",
        "Interview Alex.txt": "y",
    })
    _run_cli(["-w", str(ws), "materials", str(src), "--commit"])
    manifest = ws / "analysis" / "proposals" / "stage1" / "source_manifest.csv"
    # write_validator's dispatcher matches paths under
    # analysis/canonical/core_controls/, so we don't run the full
    # dispatcher (the manifest lives under proposals/, intentionally
    # outside the canonical surface). Instead, we directly invoke
    # the A50 schema validation by symlinking the manifest into the
    # canonical surface temporarily.
    canon = ws / "analysis" / "canonical" / "core_controls"
    target = canon / "A50_source_register.csv"
    target.write_text(manifest.read_text(encoding="utf-8"), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "governance.schemas.write_validator",
         "analysis/canonical/core_controls/A50_source_register.csv"],
        input=target.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert proc.returncode == 0, (
        f"draft source_manifest.csv failed A50 schema validation:\n"
        f"stderr=\n{proc.stderr}"
    )
