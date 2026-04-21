"""Tests for scripts/bsa_cli.py (v1.0.4 UX wrapper).

Covers:
  - WorkspaceState readers against synthetic + real-fixture workspaces.
  - `bsa status` CLI output shape (not exact formatting — exit code + key
    substrings so the test survives reasonable layout tweaks).
  - Graceful degradation: uninitialized workspace, missing A48, missing
    A51, malformed markers, Sysco-drifted (camelCase-payload) markers.
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


# ---- 5. Sysco-drifted markers (camelCase) ---------------------------


def test_status_tolerates_camelcase_sysco_markers(tmp_path: Path) -> None:
    """Sysco-engagement markers use `marker`/`emittedAt` instead of
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
            "runId": "sysco-like",
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
    """The Sysco state: discovery.complete + bsa.stage1.entry.enabled
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


def test_last_marker_uses_emittedat_for_sysco_markers(tmp_path: Path) -> None:
    """Codex review: `last_marker()` only read `timestamp`. Sysco-style
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
    # Newer Sysco-drifted marker — uses emittedAt instead of timestamp.
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
    # The Sysco-drifted d2 marker should win the "Last marker" line
    # because emittedAt 09:00 > timestamp 08:00. Pre-fix, the drifted
    # marker was ignored in recency sorting; conformant d1 marker won.
    last_line = [
        line for line in result.stdout.splitlines() if line.startswith("Last marker:")
    ]
    assert last_line, "Last marker line missing from output"
    assert "discovery.d2.ready" in last_line[0]
