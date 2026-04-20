"""Tests for plugin hooks (US-S4-03).

Exercises the three hook scripts under ./hooks/ against synthetic
workspaces in tmp_path. Verifies:

1. hooks.json parses as JSON and declares the three expected events
   (SessionStart, PreToolUse with two entries).
2. session_start.sh exits 0 in non-BSA dirs (quiet) and emits a
   suggestion when analysis/canonical/core_controls/ is present.
3. pre_write_canonical.sh blocks unless BSA_WRITER=bsa-orchestrator.
4. pre_bash_promote.sh blocks when required markers are missing and
   allows when they're present; always allows when --dry-run is in argv.

Stdlib-only.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "hooks"

HOOKS_JSON = HOOKS_DIR / "hooks.json"
SESSION_START = HOOKS_DIR / "session_start.sh"
PRE_WRITE = HOOKS_DIR / "pre_write_canonical.sh"
PRE_BASH = HOOKS_DIR / "pre_bash_promote.sh"


def _run(script: Path, *args: str, cwd: Path | None = None, env: dict | None = None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["/bin/bash", str(script), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=merged_env,
    )


# ---- hooks.json structural tests ---------------------------------------


def test_hooks_json_parses() -> None:
    json.loads(HOOKS_JSON.read_text(encoding="utf-8"))


def test_hooks_json_has_three_hook_entries() -> None:
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    hooks = data["hooks"]
    assert "SessionStart" in hooks
    assert "PreToolUse" in hooks
    # PreToolUse has 2 entries: canonical-write block + bash-promote gate.
    assert len(hooks["PreToolUse"]) == 2
    # Both reference ${CLAUDE_PLUGIN_ROOT} which Claude Code expands to
    # the plugin install directory at runtime.
    for entry in hooks["PreToolUse"]:
        for h in entry["hooks"]:
            assert "${CLAUDE_PLUGIN_ROOT}" in h["command"]


# ---- session_start.sh --------------------------------------------------


def test_session_start_quiet_in_non_bsa_dir(tmp_path: Path) -> None:
    """Empty directory → no output, exit 0."""
    result = _run(SESSION_START, cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout == ""


def test_session_start_emits_suggestion_when_bsa_dir(tmp_path: Path) -> None:
    """analysis/canonical/core_controls/ exists with A48 → suggest /bsa-status."""
    canonical = tmp_path / "analysis" / "canonical" / "core_controls"
    canonical.mkdir(parents=True)
    (canonical / "A48_run_context_card.md").write_text(
        "# A48 Run Context Card\n\n- `RunID`: test-run-001\n- `Mode`: direct\n",
        encoding="utf-8",
    )
    result = _run(SESSION_START, cwd=tmp_path)
    assert result.returncode == 0
    assert "BSA workspace detected" in result.stdout
    assert "/bsa-status" in result.stdout


def test_session_start_handles_missing_a48(tmp_path: Path) -> None:
    """canonical/core_controls/ exists but A48 missing → partial-init message."""
    (tmp_path / "analysis" / "canonical" / "core_controls").mkdir(parents=True)
    result = _run(SESSION_START, cwd=tmp_path)
    assert result.returncode == 0
    assert "partially initialized" in result.stdout
    assert "/bsa-start" in result.stdout


# ---- pre_write_canonical.sh --------------------------------------------


def test_pre_write_blocks_without_writer_env() -> None:
    result = _run(PRE_WRITE)
    assert result.returncode == 1
    assert "BLOCKED" in result.stderr
    assert "INV-02" in result.stderr


def test_pre_write_blocks_with_wrong_writer_env() -> None:
    result = _run(PRE_WRITE, env={"BSA_WRITER": "some-other-skill"})
    assert result.returncode == 1
    assert "BLOCKED" in result.stderr


def test_pre_write_allows_orchestrator() -> None:
    result = _run(PRE_WRITE, env={"BSA_WRITER": "bsa-orchestrator"})
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


# ---- pre_bash_promote.sh -----------------------------------------------


def _init_workspace(tmp_path: Path, current_stage: str, mode: str = "direct") -> Path:
    """Create a minimal BSA workspace shell with A48 declaring the given stage."""
    canonical = tmp_path / "analysis" / "canonical" / "core_controls"
    canonical.mkdir(parents=True)
    (canonical / "A48_run_context_card.md").write_text(
        f"# A48 Run Context Card\n\n"
        f"- `RunID`: test-run\n"
        f"- `Mode`: {mode}\n"
        f"- `CurrentStage`: {current_stage}\n"
        f"- `CanonPolicyVersion`: 1.0.0-rc1+hash:test\n",
        encoding="utf-8",
    )
    (tmp_path / "analysis" / "runtime" / "ready").mkdir(parents=True)
    (tmp_path / "analysis" / "discovery" / "runtime" / "ready").mkdir(parents=True)
    return tmp_path


def _touch_marker(workspace: Path, name: str, discovery: bool = False) -> None:
    subdir = "discovery/runtime/ready" if discovery else "runtime/ready"
    (workspace / "analysis" / subdir / name).write_text(
        "{\"marker_id\": \"test\"}", encoding="utf-8"
    )


def test_pre_bash_promote_blocks_when_no_workspace(tmp_path: Path) -> None:
    result = _run(PRE_BASH, cwd=tmp_path)
    assert result.returncode == 1
    assert "no A48_run_context_card.md" in result.stderr


def test_pre_bash_promote_blocks_on_missing_marker(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path, "stage3")
    result = _run(PRE_BASH, cwd=ws)
    assert result.returncode == 1
    assert "stage3.citation_audit.pass.json" in result.stderr
    assert "missing required marker" in result.stderr
    # Hook should also suggest the next-step command.
    assert "/bsa-audit citation" in result.stderr


def test_pre_bash_promote_allows_when_marker_present(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path, "stage3")
    _touch_marker(ws, "stage3.citation_audit.pass.json")
    result = _run(PRE_BASH, cwd=ws)
    assert result.returncode == 0


def test_pre_bash_promote_always_allows_dry_run(tmp_path: Path) -> None:
    """--dry-run short-circuits the marker check because it never mutates."""
    ws = _init_workspace(tmp_path, "stage3")
    # No marker present — would normally block.
    result = _run(PRE_BASH, "--dry-run", cwd=ws)
    assert result.returncode == 0


def test_pre_bash_promote_handles_discovery_stage(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path, "d2", mode="discovery_then_bsa")
    result = _run(PRE_BASH, cwd=ws)
    assert result.returncode == 1
    assert "discovery.d2.claims.merged.json" in result.stderr
    # Now supply both markers:
    _touch_marker(ws, "discovery.d2.claims.merged.json", discovery=True)
    _touch_marker(ws, "discovery.d2.research_quality.pass.json", discovery=True)
    result2 = _run(PRE_BASH, cwd=ws)
    assert result2.returncode == 0


def test_pre_bash_promote_blocks_unknown_stage(tmp_path: Path) -> None:
    ws = _init_workspace(tmp_path, "stageX")
    result = _run(PRE_BASH, cwd=ws)
    assert result.returncode == 1
    assert "unknown CurrentStage" in result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
