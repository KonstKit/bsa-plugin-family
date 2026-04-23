"""Tests for `scripts/promote_strict_preflight.py` + the
`hooks/pre_bash_promote.sh` strict-mode wiring (v1.1.16, Sprint 1 / T6).

Pins:
  * The preflight script's classification logic (BlockingStatus=hard +
    ResolutionStatus=open is the headline condition).
  * H4 waiver detection — only `## Decisions Required` references count;
    other H4 sections (Open Items Digest, Suggested Owners) do NOT.
  * Discovery-zone A51 register is also scanned (the spec calls out
    both main + discovery canonical paths).
  * Exit codes: 0 = clean / waivered, 1 = block, 2 = invocation error.
  * BLOCKED message format matches the contract pinned by
    tests/test_adversarial_b3_fixtures.py.
  * Hook wiring: --strict-on-hard-a51 flag AND BSA_STRICT_ON_HARD_A51=1
    env both activate the preflight; default mode (no flag/env) skips
    it entirely (zero overhead).
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "promote_strict_preflight.py"
HOOK_PATH = REPO_ROOT / "hooks" / "pre_bash_promote.sh"
SPEC_FIXTURE = REPO_ROOT / "fixtures" / "golden" / "adversarial_block_on_contradiction_001"


@pytest.fixture(scope="module")
def preflight():
    spec = importlib.util.spec_from_file_location(
        "promote_strict_preflight", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- A51 classification ---------------------------------------------


def _make_a51(workspace: Path, csv_body: str, *, discovery: bool = False) -> Path:
    """Drop a synthetic A51 CSV at the appropriate canonical path."""
    if discovery:
        rel = "analysis/discovery/canonical/core_controls"
    else:
        rel = "analysis/canonical/core_controls"
    target_dir = workspace / rel
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "A51_issue_route_register.csv"
    target.write_text(csv_body, encoding="utf-8")
    return target


def test_clean_workspace_passes(preflight, tmp_path) -> None:
    """An A51 CSV with NO hard+open rows passes the preflight."""
    _make_a51(tmp_path, (
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        "A51-001,uncertainty,low,informational,stage1,S-001,C-001,note,open\n"
        "A51-002,decision_needed,medium,soft,stage3,S-002,C-002,note,open\n"
    ))
    rc, msg = preflight.run_preflight(tmp_path)
    assert rc == 0
    assert msg == ""


def test_hard_open_row_blocks(preflight, tmp_path) -> None:
    """The headline contract: hard+open with no waiver → exit 1 + BLOCKED."""
    _make_a51(tmp_path, (
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        "A51-CONFL-003,contradiction,critical,hard,stage1,S-001;S-002,"
        "C-001;C-002,Resolve customer-refund authority dispute,open\n"
    ))
    rc, msg = preflight.run_preflight(tmp_path)
    assert rc == 1
    assert "BLOCKED" in msg
    assert "A51-CONFL-003" in msg
    assert "BlockingStatus=hard" in msg
    assert "ResolutionStatus=open" in msg
    assert "contradiction" in msg
    assert "Severity=critical" in msg


def test_hard_resolved_row_does_not_block(preflight, tmp_path) -> None:
    """hard + (resolved | resolved_by_remediation | superseded | wontfix)
    must NOT block — only `open` does."""
    for status in ("resolved", "resolved_by_remediation", "superseded", "wontfix"):
        _make_a51(tmp_path, (
            "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
            "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
            f"A51-001,contradiction,high,hard,stage1,S-001,C-001,Done,{status}\n"
        ))
        rc, _ = preflight.run_preflight(tmp_path)
        assert rc == 0, f"hard+{status} should NOT block (it's already closed)"


def test_open_soft_row_does_not_block(preflight, tmp_path) -> None:
    """open + (soft | informational) must NOT block — only `hard` does."""
    for blocking in ("soft", "informational"):
        _make_a51(tmp_path, (
            "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
            "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
            f"A51-001,decision_needed,medium,{blocking},stage1,S-001,C-001,Note,open\n"
        ))
        rc, _ = preflight.run_preflight(tmp_path)
        assert rc == 0, f"open+{blocking} should NOT block (only hard does)"


def test_multiple_blockers_all_listed_in_message(preflight, tmp_path) -> None:
    """When N rows block, all N appear in the BLOCKED message."""
    _make_a51(tmp_path, (
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        "A51-001,contradiction,high,hard,stage1,S-001,C-001,Action1,open\n"
        "A51-002,missing_source,critical,hard,stage1,S-002,C-002,Action2,open\n"
        "A51-003,inventory_gap,medium,hard,stage3,S-003,C-003,Action3,open\n"
    ))
    rc, msg = preflight.run_preflight(tmp_path)
    assert rc == 1
    assert "3 unresolved hard-blocking A51 row(s)" in msg
    for ref in ("A51-001", "A51-002", "A51-003"):
        assert ref in msg


def test_discovery_zone_a51_also_scanned(preflight, tmp_path) -> None:
    """The spec calls out both main + discovery canonical A51 paths.
    A blocker in the discovery register MUST also fire the block."""
    _make_a51(tmp_path, (
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        "A51-D-001,contradiction,high,hard,d2,S-001,C-001,Discovery block,open\n"
    ), discovery=True)
    rc, msg = preflight.run_preflight(tmp_path)
    assert rc == 1
    assert "A51-D-001" in msg


# ---- H4 waiver detection --------------------------------------------


def _write_h4(workspace: Path, body: str) -> Path:
    target = workspace / "analysis" / "handoff" / "H4_open_items_packet.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def test_h4_waiver_in_decisions_required_unblocks(preflight, tmp_path) -> None:
    """A51Ref inside `## Decisions Required` waivers the block."""
    _make_a51(tmp_path, (
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        "A51-CONFL-003,contradiction,critical,hard,stage1,S-001,C-001,Note,open\n"
    ))
    _write_h4(tmp_path, (
        "# H4 packet\n\n"
        "## Open Items Digest\n\n"
        "| A51Ref | ...\n"
        "\n"
        "## Decisions Required (by severity)\n\n"
        "**Critical**\n\n"
        "1. Sponsor approves promotion despite the customer-refund "
        "authority dispute — work continues with the support runbook "
        "as the source of truth pending finance review. [A51-CONFL-003]\n"
    ))
    rc, _ = preflight.run_preflight(tmp_path)
    assert rc == 0, "H4 waiver in `## Decisions Required` must unblock"


def test_h4_waiver_outside_decisions_required_does_NOT_unblock(
    preflight, tmp_path
) -> None:
    """The spec is precise: only references in `## Decisions Required`
    count as waivers. Mentions in `## Open Items Digest` or other
    sections are informational only — they don't override the block."""
    _make_a51(tmp_path, (
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        "A51-CONFL-003,contradiction,critical,hard,stage1,S-001,C-001,Note,open\n"
    ))
    _write_h4(tmp_path, (
        "# H4 packet\n\n"
        "## Open Items Digest (A51 filtered)\n\n"
        "| A51Ref | ...\n"
        "| [A51-CONFL-003] | ... |\n\n"  # mention is here, not in Decisions Required
        "## Suggested Owners\n\n"
        "| [A51-CONFL-003] | support_lead | ...\n"
    ))
    rc, msg = preflight.run_preflight(tmp_path)
    assert rc == 1, (
        "A51 mention outside `## Decisions Required` must NOT count as waiver"
    )
    assert "A51-CONFL-003" in msg


def test_h4_partial_waiver_only_unblocks_named_refs(preflight, tmp_path) -> None:
    """Two blockers, one waivered → still blocks on the other."""
    _make_a51(tmp_path, (
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        "A51-001,contradiction,high,hard,stage1,S-001,C-001,Note1,open\n"
        "A51-002,missing_source,high,hard,stage1,S-002,C-002,Note2,open\n"
    ))
    _write_h4(tmp_path, (
        "## Decisions Required\n\n"
        "1. Sponsor approves [A51-001] — work proceeds.\n"
    ))
    rc, msg = preflight.run_preflight(tmp_path)
    assert rc == 1
    assert "A51-002" in msg
    # The waivered ref should NOT appear in the BLOCKED message.
    assert "A51-001 " not in msg, "waivered A51-001 must not be listed"


# ---- Edge cases -----------------------------------------------------


def test_no_workspace_returns_2(preflight, tmp_path) -> None:
    """A path that doesn't have an `analysis/` subdir is operator
    misconfiguration → exit 2 (not a real block)."""
    rc, msg = preflight.run_preflight(tmp_path)
    assert rc == 2
    assert "not initialized" in msg


def test_no_a51_file_returns_0(preflight, tmp_path) -> None:
    """An initialized workspace with NO A51 register yet (pre-Stage-1
    promote) must pass — there's nothing to block on."""
    (tmp_path / "analysis").mkdir()
    rc, _ = preflight.run_preflight(tmp_path)
    assert rc == 0


def test_empty_a51_ref_in_row_yields_parse_error(preflight, tmp_path) -> None:
    """A row with empty A51Ref cannot be classified → parse error
    surfaced via exit 2 (operator misconfig, not silent block-bypass)."""
    _make_a51(tmp_path, (
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        ",contradiction,high,hard,stage1,S-001,C-001,Note,open\n"
    ))
    rc, msg = preflight.run_preflight(tmp_path)
    assert rc == 2, (
        "empty A51Ref must surface as parse error, not silently bypass block"
    )
    assert "empty A51Ref" in msg


def test_malformed_csv_missing_header_column_exits_2(preflight, tmp_path) -> None:
    """v1.1.16 round-1 (Codex): typoed or missing required header column
    (e.g., `Resolution_Status` instead of `ResolutionStatus`) must
    surface as exit 2, NOT silently classify every row as non-blocking.
    Earlier impl fail-opened: csv.DictReader.row.get("ResolutionStatus")
    returned None for the typoed header → mapped to "" → equality
    check against "open" was False → blocker silently slipped through."""
    _make_a51(tmp_path, (
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,Resolution_Status\n"  # typo!
        "A51-001,contradiction,high,hard,stage1,S-001,C-001,Block me,open\n"
    ))
    rc, msg = preflight.run_preflight(tmp_path)
    assert rc == 2, (
        f"typoed ResolutionStatus header must exit 2 (fail-closed); got {rc}. "
        f"Message: {msg!r}"
    )
    assert "ResolutionStatus" in msg
    assert "missing required column" in msg


def test_malformed_csv_truncated_row_exits_2(preflight, tmp_path) -> None:
    """A row with fewer cells than the header row (truncated row or
    missing delimiter) must surface as parse error — NOT silently
    classified as non-blocking. `csv.DictReader` pads missing cells
    with None; the preflight explicitly checks for None on any
    required column and fails closed."""
    _make_a51(tmp_path, (
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        "A51-001,contradiction,high,hard\n"  # truncated — missing 5 cells
    ))
    rc, msg = preflight.run_preflight(tmp_path)
    assert rc == 2, (
        f"truncated row must exit 2 (fail-closed); got {rc}. "
        f"Message: {msg!r}"
    )
    assert "truncated" in msg or "missing cell" in msg


def test_malformed_csv_extra_field_overflow_exits_2(preflight, tmp_path) -> None:
    """v1.1.16 round-2 (Codex): a row with MORE cells than the header
    (unescaped comma in a text field shifting columns leftward, or
    an accidental extra delimiter) must also surface as parse error.
    Earlier round-2 only handled the short-row case; long-row shift
    passed through because every named column still got a string
    value — the real blocker's BlockingStatus+ResolutionStatus
    classification was simply wrong.

    Attack scenario: operator writes `NextAction` text with an
    unescaped comma — `Need sponsor, decision` — which shifts
    `decision` into ResolutionStatus and `open` into the overflow
    bucket. Without this check, the row would silently classify as
    non-blocking (ResolutionStatus != 'open'), letting a real hard+
    open A51 slip past strict mode."""
    _make_a51(tmp_path, (
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        # NextAction field carries an unescaped comma — shifts
        # ResolutionStatus into overflow. Would pass pre-round-2.
        "A51-001,contradiction,high,hard,stage1,S-001,C-001,"
        "Need sponsor, decision,open\n"
    ))
    rc, msg = preflight.run_preflight(tmp_path)
    assert rc == 2, (
        f"extra-field overflow must exit 2 (fail-closed); got {rc}. "
        f"Message: {msg!r}"
    )
    assert "extra cell" in msg or "overflow" in msg.lower()


# ---- Spec fixture end-to-end ----------------------------------------


def test_spec_fixture_exact_blocked_message_shape(preflight, tmp_path) -> None:
    """End-to-end: drop the spec fixture's A51 into a synthetic
    workspace, run the preflight, verify the BLOCKED message matches
    the contract pinned by tests/test_adversarial_b3_fixtures.py."""
    src = SPEC_FIXTURE / "expected_outputs/canonical/core_controls/A51_issue_route_register.csv"
    (tmp_path / "analysis/canonical/core_controls").mkdir(parents=True)
    shutil.copy(src, tmp_path / "analysis/canonical/core_controls/A51_issue_route_register.csv")
    rc, msg = preflight.run_preflight(tmp_path)
    assert rc == 1
    # Match the format string in scripts/promote_strict_preflight.py
    # exactly — this is the contract surface.
    assert msg.startswith(
        "BLOCKED: /bsa-promote --strict-on-hard-a51 refused canonical "
        "write — 1 unresolved hard-blocking A51 row(s):\n"
    )
    assert "  A51-CONFL-003 (contradiction, Severity=critical, BlockingStatus=hard, ResolutionStatus=open)" in msg


def test_format_blocked_message_truncates_long_next_action(preflight) -> None:
    """NextAction is truncated to 80 chars + ... so the BLOCKED message
    stays operator-readable. Full text remains in the A51 CSV."""
    long_action = "X" * 200
    blockers = [preflight.BlockingRow(
        a51_ref="A51-001", issue_type="contradiction", severity="high",
        next_action=long_action, source_path="dummy",
    )]
    msg = preflight.format_blocked_message(blockers)
    # Truncated form: 80 X's + "..."
    assert "X" * 80 + "..." in msg
    # Full 200-char version must NOT appear.
    assert "X" * 200 not in msg


# ---- Hook integration ---------------------------------------------


@pytest.mark.skipif(sys.platform.startswith("win"), reason="bash hook is unix-only")
def test_hook_strict_flag_invokes_preflight(tmp_path) -> None:
    """`/bsa-promote --strict-on-hard-a51` activates the preflight;
    a hard-blocking A51 must produce exit 1 from the hook."""
    # Build a synthetic workspace with a passing marker (so the hook's
    # earlier marker check doesn't trip) AND a hard-blocking A51.
    workspace = tmp_path / "ws"
    (workspace / "analysis/canonical/core_controls").mkdir(parents=True)
    # A48 with CurrentStage=stage1 (the simplest marker-required path).
    (workspace / "analysis/canonical/core_controls/A48_run_context_card.md").write_text(
        "| Field | Value |\n|---|---|\n| CurrentStage | stage1 |\n",
        encoding="utf-8",
    )
    (workspace / "analysis/runtime/ready").mkdir(parents=True)
    (workspace / "analysis/runtime/ready/stage1.excerpts.merged.json").write_text(
        '{"marker_id":"stage1.excerpts.merged","stage":"stage1","verdict":"PASS","timestamp":"2026-04-23T00:00:00Z","canon_policy_version":"1.1.6+hash:ac63a8c3"}',
        encoding="utf-8",
    )
    # Hard-blocking A51.
    (workspace / "analysis/canonical/core_controls/A51_issue_route_register.csv").write_text(
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        "A51-001,contradiction,high,hard,stage1,S-001,C-001,Block test,open\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    result = subprocess.run(
        ["bash", str(HOOK_PATH), "/bsa-promote --strict-on-hard-a51"],
        cwd=str(workspace), capture_output=True, text=True, env=env, timeout=20,
    )
    assert result.returncode == 1, (
        f"strict flag should produce exit 1; got {result.returncode}. "
        f"stderr: {result.stderr!r}"
    )
    assert "A51-001" in result.stderr


@pytest.mark.skipif(sys.platform.startswith("win"), reason="bash hook is unix-only")
def test_hook_strict_env_invokes_preflight(tmp_path) -> None:
    """Same as the flag test but via `BSA_STRICT_ON_HARD_A51=1` env."""
    workspace = tmp_path / "ws"
    (workspace / "analysis/canonical/core_controls").mkdir(parents=True)
    (workspace / "analysis/canonical/core_controls/A48_run_context_card.md").write_text(
        "| Field | Value |\n|---|---|\n| CurrentStage | stage1 |\n",
        encoding="utf-8",
    )
    (workspace / "analysis/runtime/ready").mkdir(parents=True)
    (workspace / "analysis/runtime/ready/stage1.excerpts.merged.json").write_text(
        '{"marker_id":"stage1.excerpts.merged","stage":"stage1","verdict":"PASS","timestamp":"2026-04-23T00:00:00Z","canon_policy_version":"1.1.6+hash:ac63a8c3"}',
        encoding="utf-8",
    )
    (workspace / "analysis/canonical/core_controls/A51_issue_route_register.csv").write_text(
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        "A51-001,contradiction,high,hard,stage1,S-001,C-001,Block test,open\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["BSA_STRICT_ON_HARD_A51"] = "1"
    result = subprocess.run(
        ["bash", str(HOOK_PATH), "/bsa-promote"],  # NO --strict flag in argv
        cwd=str(workspace), capture_output=True, text=True, env=env, timeout=20,
    )
    assert result.returncode == 1, (
        f"env var should produce exit 1; got {result.returncode}. "
        f"stderr: {result.stderr!r}"
    )


@pytest.mark.skipif(sys.platform.startswith("win"), reason="bash hook is unix-only")
def test_hook_boundary_aware_flag_does_not_activate_on_suffixed_token(tmp_path) -> None:
    """v1.1.16 round-1 (Codex): substring match like `*--strict-on-hard-a51*`
    falsely activates on `--strict-on-hard-a51-EXTRA` or any argument
    containing the flag as a substring. The hook now uses a bash-
    regex boundary check (preceded by start-of-string OR whitespace,
    followed by end-of-string OR whitespace OR `=`) so only a literal
    flag activates.

    Pin: arg `--strict-on-hard-a51-DISABLED` MUST NOT activate strict
    mode — if the bug regressed, we'd get exit 1 (block) here."""
    workspace = tmp_path / "ws"
    (workspace / "analysis/canonical/core_controls").mkdir(parents=True)
    (workspace / "analysis/canonical/core_controls/A48_run_context_card.md").write_text(
        "| Field | Value |\n|---|---|\n| CurrentStage | stage1 |\n",
        encoding="utf-8",
    )
    (workspace / "analysis/runtime/ready").mkdir(parents=True)
    (workspace / "analysis/runtime/ready/stage1.excerpts.merged.json").write_text(
        '{"marker_id":"stage1.excerpts.merged","stage":"stage1","verdict":"PASS","timestamp":"2026-04-23T00:00:00Z","canon_policy_version":"1.1.6+hash:ac63a8c3"}',
        encoding="utf-8",
    )
    (workspace / "analysis/canonical/core_controls/A51_issue_route_register.csv").write_text(
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        "A51-001,contradiction,high,hard,stage1,S-001,C-001,Block test,open\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env.pop("BSA_STRICT_ON_HARD_A51", None)
    # Pass the SUFFIXED flag — must NOT activate strict mode.
    result = subprocess.run(
        ["bash", str(HOOK_PATH), "/bsa-promote --strict-on-hard-a51-DISABLED"],
        cwd=str(workspace), capture_output=True, text=True, env=env, timeout=20,
    )
    assert result.returncode == 0, (
        f"suffix --strict-on-hard-a51-DISABLED must NOT activate strict "
        f"mode; hook falsely blocked. stderr: {result.stderr!r}"
    )
    assert "BLOCKED" not in result.stderr


@pytest.mark.skipif(sys.platform.startswith("win"), reason="bash hook is unix-only")
def test_hook_default_mode_skips_preflight(tmp_path) -> None:
    """Without --strict-on-hard-a51 OR the env var, the hook MUST NOT
    invoke the preflight even when hard-blocking A51 rows exist.
    Default behavior is permissive — protected by this test."""
    workspace = tmp_path / "ws"
    (workspace / "analysis/canonical/core_controls").mkdir(parents=True)
    (workspace / "analysis/canonical/core_controls/A48_run_context_card.md").write_text(
        "| Field | Value |\n|---|---|\n| CurrentStage | stage1 |\n",
        encoding="utf-8",
    )
    (workspace / "analysis/runtime/ready").mkdir(parents=True)
    (workspace / "analysis/runtime/ready/stage1.excerpts.merged.json").write_text(
        '{"marker_id":"stage1.excerpts.merged","stage":"stage1","verdict":"PASS","timestamp":"2026-04-23T00:00:00Z","canon_policy_version":"1.1.6+hash:ac63a8c3"}',
        encoding="utf-8",
    )
    # Hard-blocking A51 PRESENT but the operator did not opt in.
    (workspace / "analysis/canonical/core_controls/A51_issue_route_register.csv").write_text(
        "A51Ref,IssueType,Severity,BlockingStatus,RaisedByStage,"
        "RelatedSourceID,RelatedClaimID,NextAction,ResolutionStatus\n"
        "A51-001,contradiction,high,hard,stage1,S-001,C-001,Note,open\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    # NO BSA_STRICT_ON_HARD_A51 in env
    env.pop("BSA_STRICT_ON_HARD_A51", None)
    result = subprocess.run(
        ["bash", str(HOOK_PATH), "/bsa-promote"],
        cwd=str(workspace), capture_output=True, text=True, env=env, timeout=20,
    )
    assert result.returncode == 0, (
        f"default mode must pass even with hard-blocking A51; got "
        f"exit {result.returncode}. stderr: {result.stderr!r}"
    )
    # The BLOCKED message must NOT appear (preflight wasn't invoked).
    assert "BLOCKED" not in result.stderr
