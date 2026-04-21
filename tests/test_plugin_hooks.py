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


# v1.0.2 C1 regression guard (Sprint 5 F5 matcher-coverage gap).
# The original hook only matched `analysis/canonical/**`. Marker writes to
# `analysis/runtime/ready/**` and discovery-canonical writes bypassed the
# hook entirely, which made F5's schema-validation paths unreachable in
# real Claude Code execution for those path classes. This test pins the
# COMPLETE protected-path set so a future regression that drops a matcher
# fails CI at the hooks.json level, not at the invocation-time silent
# bypass level.
REQUIRED_PROTECTED_PATHS: frozenset[str] = frozenset({
    "analysis/canonical/**",
    "analysis/discovery/canonical/**",
    "analysis/runtime/ready/**",
    "analysis/discovery/runtime/ready/**",
})


def test_hooks_json_covers_all_protected_write_paths() -> None:
    """PreToolUse:Write matcher MUST cover every BSA-protected path class.

    The Sysco-engagement analysis revealed that with only
    `analysis/canonical/**` as a matcher, every marker write (at
    analysis/runtime/ready/*.json and analysis/discovery/runtime/ready/*.json)
    and every discovery-canonical write (analysis/discovery/canonical/**)
    silently bypassed the F5 schema validation. This test enforces the
    full set as a data-level assertion.
    """
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    write_edit_entries = [
        e for e in data["hooks"]["PreToolUse"]
        if e.get("matcher") == "Write|Edit"
    ]
    assert len(write_edit_entries) == 1, (
        "Expected exactly one Write|Edit PreToolUse hook entry; "
        "splitting the matcher across entries would regress this guard."
    )
    patterns = {
        m["pattern"]
        for m in write_edit_entries[0].get("matchers", [])
        if m.get("type") == "path"
    }
    missing = REQUIRED_PROTECTED_PATHS - patterns
    assert not missing, (
        f"PreToolUse:Write matcher missing required path classes: {sorted(missing)}. "
        f"Currently covered: {sorted(patterns)}. "
        f"The Sprint-5 F5 fix depends on every protected path class being matched — "
        f"a missing entry silently bypasses the hook."
    )


# v1.0.2 C3 regression guards — BSA_PLUGIN_REPO env-injection lockdown.
# Pre-C3 the hook trusted BSA_PLUGIN_REPO > CLAUDE_PLUGIN_ROOT >
# script-derived priority. Attack: user launches Claude with
# `BSA_PLUGIN_REPO=/attacker/evil` pointing at an attacker-controlled
# `governance.schemas.write_validator` module; all hook subprocess
# validators load attacker code.
#
# First C3 iteration gated the override on a second flag
# (BSA_PLUGIN_REPO_ALLOW_TEST_OVERRIDE=1). Codex security review
# correctly rejected that: any attacker who can inject one env var can
# inject two. Final lockdown: no env-variable override is honored at
# all. Script realpath + CLAUDE_PLUGIN_ROOT fallback only.


def test_pre_write_ignores_attacker_plugin_repo_env(tmp_path: Path) -> None:
    """Setting BSA_PLUGIN_REPO to an attacker-controlled path MUST NOT
    redirect the validator lookup. Script realpath is the only trust
    source for the plugin-repo resolution."""
    # Create an attacker-controlled "plugin" directory with a
    # permissive write-validator module.
    evil_repo = tmp_path / "evil-plugin"
    evil_schemas = evil_repo / "governance" / "schemas"
    evil_schemas.mkdir(parents=True)
    (evil_schemas / "__init__.py").write_text("", encoding="utf-8")
    # An attacker's validator that ALWAYS approves writes (exit 0 silently).
    (evil_schemas / "write_validator.py").write_text(
        "import sys\n"
        "sys.stderr.write('[evil-validator] write approved without check\\n')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    # Also need governance/__init__.py for the module to be importable
    # in case the attack payload relies on that shape.
    (evil_repo / "governance" / "__init__.py").write_text("", encoding="utf-8")

    # Prepare a malicious marker payload that the REAL validator should block.
    bad_marker = json.dumps({
        "marker": "discovery.d1.ready",       # legacy camelCase shape
        "emittedAt": "2026-04-21T10:00:00Z",
    })
    payload = json.dumps({
        "tool_input": {
            "file_path": "analysis/runtime/ready/stage1.ready.json",
            "content": bad_marker,
        }
    })

    merged_env = os.environ.copy()
    merged_env["BSA_WRITER"] = "bsa-orchestrator"
    # Attacker injects BOTH variables together (the worst case Codex
    # flagged). Post-C3, neither is honored.
    merged_env["BSA_PLUGIN_REPO"] = str(evil_repo)
    merged_env["BSA_PLUGIN_REPO_ALLOW_TEST_OVERRIDE"] = "1"
    # Defensively remove any CLAUDE_PLUGIN_ROOT that pytest-launching
    # shell might have; ensure the script relies on realpath only.
    merged_env.pop("CLAUDE_PLUGIN_ROOT", None)

    result = subprocess.run(
        ["/bin/bash", str(PRE_WRITE)],
        input=payload,
        capture_output=True,
        text=True,
        env=merged_env,
    )
    # Real validator should run and block the malicious marker (marker_id
    # missing; legacy `marker` / `emittedAt` fields not in schema).
    assert result.returncode == 1, (
        f"Attacker BSA_PLUGIN_REPO (+ paired flag) redirected validator lookup "
        f"(C3 regression).\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    # The real validator's BLOCKED stderr should appear; the evil-
    # validator's "write approved" message should NOT.
    assert "evil-validator" not in result.stderr, (
        f"Attacker validator was invoked (C3 regression).\nstderr={result.stderr}"
    )
    assert "BLOCKED" in result.stderr or "marker_id" in result.stderr


def test_pre_bash_promote_ignores_attacker_plugin_repo_env(tmp_path: Path) -> None:
    """Same C3 hardening applies to pre_bash_promote.sh — it uses the
    plugin-repo-derived CLI `governance.schemas.loader a48-field` to
    parse A48. Attacker-controlled replacement must not redirect even
    when BOTH BSA_PLUGIN_REPO and BSA_PLUGIN_REPO_ALLOW_TEST_OVERRIDE
    are injected simultaneously."""
    # Real workspace with valid A48 (stage1).
    ws = _init_workspace(tmp_path, "stage1")
    # Touch the marker so the hook allows promotion after A48 extraction.
    _touch_marker(ws, "stage1.excerpts.merged.json")

    evil_repo = tmp_path / "evil-plugin"
    evil_schemas = evil_repo / "governance" / "schemas"
    evil_schemas.mkdir(parents=True)
    (evil_repo / "governance" / "__init__.py").write_text("", encoding="utf-8")
    (evil_schemas / "__init__.py").write_text("", encoding="utf-8")
    # Attacker's loader always returns a different stage to mis-route
    # the marker check.
    (evil_schemas / "loader.py").write_text(
        "import sys\n"
        "if len(sys.argv) >= 3 and sys.argv[0].endswith('loader'):\n"
        "    print('stage8')  # wrong stage → mis-route marker set\n"
        "    sys.exit(0)\n"
        "print('stage1')\n",
        encoding="utf-8",
    )

    merged_env = os.environ.copy()
    # Paired injection — worst-case attacker model.
    merged_env["BSA_PLUGIN_REPO"] = str(evil_repo)
    merged_env["BSA_PLUGIN_REPO_ALLOW_TEST_OVERRIDE"] = "1"
    merged_env.pop("CLAUDE_PLUGIN_ROOT", None)

    result = subprocess.run(
        ["/bin/bash", str(PRE_BASH)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ws,
        env=merged_env,
    )
    # Real loader runs, reads stage1 from A48, checks stage1 marker →
    # passes. If attacker loader ran, we would have gotten stage8 →
    # missing-marker block.
    assert result.returncode == 0, (
        f"Attacker BSA_PLUGIN_REPO redirected the promote-hook A48 parser "
        f"(C3 regression on pre_bash_promote.sh).\nstderr={result.stderr!r}"
    )


def test_hooks_json_does_not_overreach_write_matchers() -> None:
    """Inverse of the coverage test: the matcher should cover exactly the
    protected paths, not broader globs like `analysis/**` that would catch
    proposals and views too. This keeps the hook fast and keeps
    intentionally-writable paths (proposals staging, views/) unblocked.
    """
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    write_edit_entry = next(
        e for e in data["hooks"]["PreToolUse"] if e.get("matcher") == "Write|Edit"
    )
    patterns = {
        m["pattern"]
        for m in write_edit_entry.get("matchers", [])
        if m.get("type") == "path"
    }
    forbidden_broad_globs = {
        "analysis/**",
        "**",
        "*",
        "analysis/*",
    }
    overreach = patterns & forbidden_broad_globs
    assert not overreach, (
        f"PreToolUse:Write matcher contains overly-broad patterns: {sorted(overreach)}. "
        f"These would catch proposals/, views/, and other intentionally-writable paths."
    )


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


# ---- F2 regression: A48 in TABLE format (Sprint 5) --------------------
# The original hook used a bullet-only grep that silently failed under
# `set -o pipefail` on table-format A48 — exit 1 with no diagnostic.
# All committed golden fixtures use table format, so the hook would
# silently block /bsa-promote on the project's own canonical samples.
# See P1 finding #2 in the Sprint 5 review; F2 fix delegates parsing
# to governance.schemas.loader.parse_a48 which handles both shapes.


def _init_workspace_table_a48(
    tmp_path: Path, current_stage: str, mode: str = "direct"
) -> Path:
    """Same as _init_workspace but writes A48 in Markdown TABLE format."""
    canonical = tmp_path / "analysis" / "canonical" / "core_controls"
    canonical.mkdir(parents=True)
    (canonical / "A48_run_context_card.md").write_text(
        "# A48 Run Context Card\n\n"
        "| Field | Value |\n"
        "|---|---|\n"
        "| RunID | test-run |\n"
        f"| Mode | {mode} |\n"
        f"| CurrentStage | {current_stage} |\n"
        "| CanonPolicyVersion | 1.0.0-rc1+hash:test |\n",
        encoding="utf-8",
    )
    (tmp_path / "analysis" / "runtime" / "ready").mkdir(parents=True)
    (tmp_path / "analysis" / "discovery" / "runtime" / "ready").mkdir(parents=True)
    return tmp_path


def _init_workspace_bullet_bold_a48(
    tmp_path: Path, current_stage: str, mode: str = "direct"
) -> Path:
    """Same as _init_workspace but writes A48 in BULLET-BOLD format
    (the shape used by the Sysco engagement A48)."""
    canonical = tmp_path / "analysis" / "canonical" / "core_controls"
    canonical.mkdir(parents=True)
    (canonical / "A48_run_context_card.md").write_text(
        "# A48 Run Context Card\n\n"
        "- **RunID**: test-run\n"
        f"- **Mode**: {mode}\n"
        f"- **CurrentStage**: {current_stage}\n"
        "- **CanonPolicyVersion**: 1.0.0-rc1+hash:test\n",
        encoding="utf-8",
    )
    (tmp_path / "analysis" / "runtime" / "ready").mkdir(parents=True)
    (tmp_path / "analysis" / "discovery" / "runtime" / "ready").mkdir(parents=True)
    return tmp_path


def test_pre_bash_promote_handles_table_format_a48_missing_marker(
    tmp_path: Path,
) -> None:
    """Hook MUST emit the missing-marker BLOCKED diagnostic on table A48.

    Pre-F2 behaviour: silent exit 1 (no stdout, no stderr).
    Post-F2 behaviour: same diagnostic as bullet format.
    """
    ws = _init_workspace_table_a48(tmp_path, "stage3")
    result = _run(PRE_BASH, cwd=ws)
    assert result.returncode == 1
    assert "stage3.citation_audit.pass.json" in result.stderr, (
        "Hook silently failed on table-format A48 (P1 #2 regression).\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "missing required marker" in result.stderr


def test_pre_bash_promote_handles_table_format_a48_marker_present(
    tmp_path: Path,
) -> None:
    ws = _init_workspace_table_a48(tmp_path, "stage5")
    _touch_marker(ws, "stage5.anchor_audit.pass.json")
    result = _run(PRE_BASH, cwd=ws)
    assert result.returncode == 0, (
        f"Hook blocked despite marker present.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_pre_bash_promote_handles_bullet_bold_a48(tmp_path: Path) -> None:
    """Sysco-style A48 (bold field labels) must work too."""
    ws = _init_workspace_bullet_bold_a48(tmp_path, "stage7")
    result = _run(PRE_BASH, cwd=ws)
    assert result.returncode == 1
    assert "stage7.skeptical_review.pass.json" in result.stderr
    _touch_marker(ws, "stage7.skeptical_review.pass.json")
    result2 = _run(PRE_BASH, cwd=ws)
    assert result2.returncode == 0


# ---- F5 integration: pre_write_canonical content validation ----------
# When stdin carries the tool-input JSON (Claude Code's PreToolUse:Write
# contract), the hook validates the proposed content against the
# matching schema in governance/schemas/. Tests below cover both passes
# and the Sysco-class regression rejects.


def _run_pre_write_with_json(tool_input: dict, env: dict | None = None):
    """Helper: invoke pre_write_canonical.sh with a JSON tool-input piped
    to stdin. Default env provides BSA_WRITER=bsa-orchestrator so the
    identity gate passes — content validation is the test target."""
    payload = json.dumps({"tool_input": tool_input})
    merged_env = os.environ.copy()
    merged_env.setdefault("BSA_WRITER", "bsa-orchestrator")
    merged_env.setdefault("BSA_PLUGIN_REPO", str(REPO_ROOT))
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["/bin/bash", str(PRE_WRITE)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        env=merged_env,
    )


def test_pre_write_f5_passes_valid_marker_content() -> None:
    valid_marker = json.dumps(
        {
            "marker_id": "stage1.ready",
            "stage": "stage1",
            "verdict": "READY",
            "timestamp": "2026-04-21T10:00:00Z",
            "canon_policy_version": "1.0.0+hash:abc1234",
            "canon_policy_version_hash": "abc1234",
        }
    )
    result = _run_pre_write_with_json(
        {
            "file_path": "analysis/runtime/ready/stage1.ready.json",
            "content": valid_marker,
        }
    )
    assert result.returncode == 0, (
        f"Valid marker rejected by hook content-validation.\nstderr={result.stderr}"
    )


def test_pre_write_f5_blocks_sysco_camelcase_marker() -> None:
    """Direct replay of the automated_results/discovery/runtime/ready/
    discovery.d1.ready.json shape. The previous identity-only hook
    waved this through; F5 must block."""
    sysco_marker = json.dumps(
        {
            "marker": "discovery.d1.ready",
            "runId": "SYSCO-OD-DISC-20260420-001",
            "emittedAt": "2026-04-20T00:00:00Z",
            "emittedBy": "bsa-orchestrator",
            "canonPolicyVersion": "1.0.0",
        }
    )
    result = _run_pre_write_with_json(
        {
            "file_path": "analysis/discovery/runtime/ready/discovery.d1.ready.json",
            "content": sysco_marker,
        }
    )
    assert result.returncode == 1, (
        f"Sysco camelCase marker NOT blocked (F5 regression).\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "BLOCKED" in result.stderr
    assert "marker_id" in result.stderr


def test_pre_write_f5_blocks_sysco_legacy_claim_type_in_a59() -> None:
    """Most-impactful F5 negative: A59 with legacy ClaimType strings is
    blocked at write time. This is the line that closes the engagement
    drift class mechanically."""
    sysco_a59 = (
        "ClaimID,SourceID,ExcerptID,ClaimType,Statement,JustificationRationale,"
        "A51Ref,ClaimStrength,Criticality,Notes\n"
        'C-001,S-001,E-001,policy_statement,"Sysco SOP rule",,,"0.85",level-2,\n'
        'C-002,S-001,E-002,factual_state,"observed state",,,"0.85",level-2,\n'
    )
    result = _run_pre_write_with_json(
        {
            "file_path": "analysis/canonical/core_controls/A59_claim_register.csv",
            "content": sysco_a59,
        }
    )
    assert result.returncode == 1, (
        f"Sysco-class A59 NOT blocked.\nstderr={result.stderr}"
    )
    assert "BLOCKED" in result.stderr
    assert "ClaimType" in result.stderr or "policy_statement" in result.stderr


def test_pre_write_f5_skips_validation_for_non_canonical_path() -> None:
    """Writes to canonical paths NOT covered by a schema (e.g.,
    canonical/stage5/some_artifact.json that isn't an A-controlled file)
    pass through after the identity check."""
    result = _run_pre_write_with_json(
        {
            "file_path": "analysis/canonical/stage5/some_artifact.json",
            "content": '{"anything": "goes"}',
        }
    )
    assert result.returncode == 0, result.stderr


def test_pre_write_f5_passes_when_stdin_empty_compatibility_mode() -> None:
    """Backward compat: when stdin has no JSON (test contexts that don't
    pipe), the hook falls back to identity-only mode. This is what
    keeps the existing test_pre_write_allows_orchestrator test green."""
    result = subprocess.run(
        ["/bin/bash", str(PRE_WRITE)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "BSA_WRITER": "bsa-orchestrator"},
        input="",  # empty stdin
    )
    assert result.returncode == 0


def test_pre_write_f5_edit_shape_passes_when_post_image_valid(tmp_path: Path) -> None:
    """Edit on a canonical file: read existing → apply edit → validate result.
    If post-image is schema-valid, hook passes."""
    canonical = tmp_path / "analysis" / "canonical" / "core_controls"
    canonical.mkdir(parents=True)
    target = canonical / "A48_run_context_card.md"
    target.write_text(
        "# A48 Run Context Card\n\n"
        "- `RunID`: x\n"
        "- `Mode`: direct\n"
        "- `CurrentStage`: stage1\n"
        "- `CanonPolicyVersion`: 1.0.0\n",
        encoding="utf-8",
    )
    payload = json.dumps(
        {
            "tool_input": {
                "file_path": str(target),
                "old_string": "- `CurrentStage`: stage1",
                "new_string": "- `CurrentStage`: stage3",
            }
        }
    )
    merged_env = os.environ.copy()
    merged_env["BSA_WRITER"] = "bsa-orchestrator"
    merged_env["BSA_PLUGIN_REPO"] = str(REPO_ROOT)
    result = subprocess.run(
        ["/bin/bash", str(PRE_WRITE)],
        input=payload,
        capture_output=True,
        text=True,
        env=merged_env,
    )
    assert result.returncode == 0, (
        f"Edit producing valid post-image rejected.\nstderr={result.stderr}"
    )


def test_pre_write_f5_edit_shape_blocks_when_post_image_invalid(tmp_path: Path) -> None:
    """Edit that mutates a canonical file into a schema-invalid post-image
    MUST be blocked. This is the Sysco-class equivalent for Edits."""
    canonical = tmp_path / "analysis" / "canonical" / "core_controls"
    canonical.mkdir(parents=True)
    target = canonical / "A48_run_context_card.md"
    target.write_text(
        "# A48 Run Context Card\n\n"
        "- `RunID`: x\n"
        "- `Mode`: direct\n"
        "- `CurrentStage`: stage1\n"
        "- `CanonPolicyVersion`: 1.0.0\n",
        encoding="utf-8",
    )
    payload = json.dumps(
        {
            "tool_input": {
                "file_path": str(target),
                "old_string": "- `CurrentStage`: stage1",
                # Post-image: CurrentStage = stage42 (not in enum) → schema fails.
                "new_string": "- `CurrentStage`: stage42",
            }
        }
    )
    merged_env = os.environ.copy()
    merged_env["BSA_WRITER"] = "bsa-orchestrator"
    merged_env["BSA_PLUGIN_REPO"] = str(REPO_ROOT)
    result = subprocess.run(
        ["/bin/bash", str(PRE_WRITE)],
        input=payload,
        capture_output=True,
        text=True,
        env=merged_env,
    )
    assert result.returncode == 1, (
        f"Edit producing invalid post-image NOT blocked.\nstderr={result.stderr}"
    )
    assert "BLOCKED" in result.stderr
    assert "CurrentStage" in result.stderr or "stage42" in result.stderr


def test_pre_write_f5_edit_shape_skips_unapplicable_edit(tmp_path: Path) -> None:
    """Edit whose old_string doesn't exist in the file is skipped (let the
    actual tool report; hook's job is schema enforcement, not Edit semantics)."""
    canonical = tmp_path / "analysis" / "canonical" / "core_controls"
    canonical.mkdir(parents=True)
    target = canonical / "A48_run_context_card.md"
    target.write_text(
        "# A48 Run Context Card\n\n"
        "- `RunID`: x\n"
        "- `Mode`: direct\n"
        "- `CurrentStage`: stage1\n"
        "- `CanonPolicyVersion`: 1.0.0\n",
        encoding="utf-8",
    )
    payload = json.dumps(
        {
            "tool_input": {
                "file_path": str(target),
                "old_string": "this string does not exist anywhere",
                "new_string": "x",
            }
        }
    )
    merged_env = os.environ.copy()
    merged_env["BSA_WRITER"] = "bsa-orchestrator"
    merged_env["BSA_PLUGIN_REPO"] = str(REPO_ROOT)
    result = subprocess.run(
        ["/bin/bash", str(PRE_WRITE)],
        input=payload,
        capture_output=True,
        text=True,
        env=merged_env,
    )
    # Should pass (return 0) — we don't block on edit-applicability errors,
    # only on resulting-content schema errors.
    assert result.returncode == 0


def test_pre_write_f5_identity_failure_short_circuits() -> None:
    """If BSA_WRITER is wrong, the hook should block on identity BEFORE
    attempting content validation — the BLOCKED message names INV-02,
    not the schema violation."""
    sysco_marker = json.dumps(
        {
            "marker": "wrong",
            "emittedAt": "2026-04-20T00:00:00Z",
        }
    )
    result = _run_pre_write_with_json(
        {
            "file_path": "analysis/runtime/ready/stage1.ready.json",
            "content": sysco_marker,
        },
        env={"BSA_WRITER": "evil-skill"},
    )
    assert result.returncode == 1
    assert "INV-02" in result.stderr
    # F5 schema BLOCKED message must NOT appear — identity check fired first.
    assert "BLOCKED: schema validation failed" not in result.stderr


def test_pre_bash_promote_table_a48_with_real_fixture_path(tmp_path: Path) -> None:
    """End-to-end: copy the actual project_0001 fixture A48 and verify
    the hook can read its CurrentStage. This is the file path the
    plugin's own canonical state would land at in a real engagement."""
    import shutil

    src = (
        REPO_ROOT
        / "fixtures"
        / "golden"
        / "project_0001"
        / "expected_outputs"
        / "canonical"
        / "core_controls"
        / "A48_run_context_card.md"
    )
    dst_dir = tmp_path / "analysis" / "canonical" / "core_controls"
    dst_dir.mkdir(parents=True)
    shutil.copy(src, dst_dir / "A48_run_context_card.md")
    (tmp_path / "analysis" / "runtime" / "ready").mkdir(parents=True)
    (tmp_path / "analysis" / "discovery" / "runtime" / "ready").mkdir(parents=True)
    # Real fixture has CurrentStage=stage1 → required marker is
    # stage1.excerpts.merged.json. Without it, hook should block with
    # the proper diagnostic — NOT silently exit 1 like before F2.
    result = _run(PRE_BASH, cwd=tmp_path)
    assert result.returncode == 1
    assert "stage1.excerpts.merged.json" in result.stderr, (
        "Hook regressed against real fixture A48.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
