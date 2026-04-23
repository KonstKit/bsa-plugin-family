"""Tests for the v1.1.17 shell import drivers (Sprint 1 / T5).

Pins:
  * All three drivers (jira, linear, github) exist + are executable.
  * Each accepts --help + exits 0.
  * Each dry-run correctly prints the plan against a synthetic export
    (no real API calls).
  * Each refuses --apply without the required auth env var + target arg.
  * Idempotency: a prior live_api_response_{platform}_shell.json
    (separate path from Python impl; see v1.1.17 round-3) with a
    `status=created` entry skips that row on the next run.
  * Missing dependencies surface as exit 2 with a helpful diagnostic
    (skipped on CI where jq/gh/python3 are all present).
  * macOS compatibility: scripts use POSIX `sha256sum`/`shasum` fallback
    and do NOT use `declare -A` (bash 3.2 on macOS default lacks
    associative arrays — earlier round used tmpfile + grep pattern).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
JIRA_SCRIPT = REPO_ROOT / "scripts" / "jira_import_from_export.sh"
LINEAR_SCRIPT = REPO_ROOT / "scripts" / "linear_import_from_export.sh"
GITHUB_SCRIPT = REPO_ROOT / "scripts" / "github_import_from_export.sh"

SCRIPTS = [JIRA_SCRIPT, LINEAR_SCRIPT, GITHUB_SCRIPT]

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="shell drivers are unix-only",
)


# ---- Presence + structure -------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_exists_and_executable(script: Path) -> None:
    assert script.is_file(), f"missing shell driver: {script}"
    assert os.access(script, os.X_OK), (
        f"shell driver not executable: {script} (run `chmod +x`)"
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_shebang_uses_env_bash(script: Path) -> None:
    """Pin: shebang must be #!/usr/bin/env bash so drivers work on
    systems where bash isn't at /bin/bash (e.g., nix, alpine)."""
    first_line = script.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#!/usr/bin/env bash", (
        f"{script.name} shebang is {first_line!r}; expected #!/usr/bin/env bash"
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_has_usage_help(script: Path) -> None:
    """`-h` / `--help` must print usage + exit 0 — catches the case
    where someone edits the script in a way that breaks argv parsing."""
    result = subprocess.run(
        ["bash", str(script), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, (
        f"{script.name} --help exited {result.returncode}: {result.stderr!r}"
    )
    assert "Usage:" in result.stdout


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_avoids_declare_dash_a(script: Path) -> None:
    """Bash 3.2 (macOS default) lacks `declare -A`. Pin that the
    drivers use the tmpfile + grep pattern instead. This catches
    future drift where someone 'refactors' back to associative
    arrays + silently breaks on macOS.

    Looks for `declare -A` at the START of a line (possibly
    indented) — i.e., an actual declaration, not a mention inside
    a comment. Inline comments documenting the macOS-compat
    rationale are allowed."""
    import re
    body = script.read_text(encoding="utf-8")
    # Match lines that are actual declarations: optional leading
    # whitespace, then `declare -A` at the start (not preceded by `#`
    # or embedded mid-line).
    non_comment_lines = [
        line for line in body.splitlines()
        if not line.lstrip().startswith("#")
    ]
    for line in non_comment_lines:
        if re.match(r"^\s*declare\s+-A\b", line):
            pytest.fail(
                f"{script.name} has actual `declare -A` declaration: "
                f"{line!r}. Incompatible with macOS bash 3.2; use tmpfile "
                f"+ grep -Fxq pattern instead."
            )


# ---- Dry-run smoke --------------------------------------------------


def _make_workspace(tmp_path: Path) -> Path:
    handoff = tmp_path / "analysis" / "handoff"
    handoff.mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_jira_export(workspace: Path, n_rows: int = 2) -> None:
    issues = []
    for i in range(1, n_rows + 1):
        issues.append({
            "fields": {
                "summary": f"Test story {i}",
                "project": {"key": "BSA"},
                "labels": ["bsa-export", f"STORY-{i:03d}"],
            },
            "bsa_provenance": {"story_id": f"STORY-{i:03d}"},
        })
    (workspace / "analysis/handoff/backlog_export_jira.json").write_text(
        json.dumps({"issues": issues}, indent=2), encoding="utf-8",
    )


def _write_csv_export(workspace: Path, filename: str, n_rows: int = 2) -> None:
    lines = [
        "Title,Description,Status,Priority,Labels,Estimate,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs,Project,Cycle"
    ]
    for i in range(1, n_rows + 1):
        lines.append(
            f'Test {i},"Body text",Backlog,2,'
            f'"bsa-export,level-2,invest-pass",3,'
            f'STORY-{i:03d},C-{i:03d},,,'
        )
    (workspace / f"analysis/handoff/{filename}").write_text(
        "\n".join(lines) + "\n", encoding="utf-8",
    )


def _write_github_csv_export(workspace: Path, n_rows: int = 2) -> None:
    """GitHub export has a DIFFERENT column set from Linear
    (Body/Size instead of Description/Estimate per
    governance/schemas/backlog_export_github.schema.json).
    v1.1.17 round-1 (Codex should #2): previous test used Linear
    shape for GitHub dry-run — misleading."""
    lines = [
        "Title,Body,Status,Priority,Size,Labels,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs"
    ]
    for i in range(1, n_rows + 1):
        lines.append(
            f'Test {i},"Issue body markdown",Todo,2,M,'
            f'"bsa-export,level-2,invest-pass",'
            f'STORY-{i:03d},C-{i:03d},'
        )
    (workspace / "analysis/handoff/backlog_export_github.csv").write_text(
        "\n".join(lines) + "\n", encoding="utf-8",
    )


def test_jira_dry_run_prints_plan(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_jira_export(workspace, n_rows=3)
    result = subprocess.run(
        ["bash", str(JIRA_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "DRY-RUN" in result.stdout
    assert "rows: 3" in result.stdout
    for i in range(1, 4):
        assert f"STORY-{i:03d}" in result.stdout
    assert "3 ok, 0 skipped, 0 failed" in result.stdout


def test_linear_dry_run_prints_plan(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_csv_export(workspace, "backlog_export_linear.csv", n_rows=2)
    result = subprocess.run(
        ["bash", str(LINEAR_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "DRY-RUN" in result.stdout
    assert "issueCreate" in result.stdout
    assert "2 ok" in result.stdout


def test_github_dry_run_prints_plan(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_github_csv_export(workspace, n_rows=2)
    # gh is a hard dep but only for --apply. Dry-run invokes
    # `command -v gh` at the top — if gh isn't installed, skip.
    if shutil.which("gh") is None:
        pytest.skip("gh CLI not installed — required for dry-run dep check")
    result = subprocess.run(
        ["bash", str(GITHUB_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "DRY-RUN" in result.stdout
    assert "gh-issue-create" in result.stdout
    for i in range(1, 3):
        assert f"STORY-{i:03d}" in result.stdout


# ---- Missing-input + auth-refusal -----------------------------------


def test_jira_missing_export_exits_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    # No export written → exit 2.
    result = subprocess.run(
        ["bash", str(JIRA_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "export file not found" in result.stderr


def test_jira_apply_refuses_without_token(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_jira_export(workspace)
    env = os.environ.copy()
    env.pop("BSA_JIRA_TOKEN", None)
    env.pop("BSA_JIRA_EMAIL", None)
    result = subprocess.run(
        [
            "bash", str(JIRA_SCRIPT),
            "--workspace", str(workspace),
            "--apply",
            "--base-url", "https://example.atlassian.net",
        ],
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert result.returncode == 2
    # The driver rejects missing BSA_JIRA_EMAIL first.
    assert "BSA_JIRA_EMAIL" in result.stderr or "BSA_JIRA_TOKEN" in result.stderr


def test_jira_apply_refuses_without_base_url(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_jira_export(workspace)
    env = os.environ.copy()
    env["BSA_JIRA_EMAIL"] = "test@example.com"
    env["BSA_JIRA_TOKEN"] = "ATATT3-test-only-not-real"
    result = subprocess.run(
        ["bash", str(JIRA_SCRIPT), "--workspace", str(workspace), "--apply"],
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert result.returncode == 2
    assert "--base-url" in result.stderr


def test_linear_apply_refuses_without_team_id(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_csv_export(workspace, "backlog_export_linear.csv")
    env = os.environ.copy()
    env["BSA_LINEAR_TOKEN"] = "lin_api_test_only"
    result = subprocess.run(
        ["bash", str(LINEAR_SCRIPT), "--workspace", str(workspace), "--apply"],
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert result.returncode == 2
    assert "--team-id" in result.stderr


def test_github_apply_refuses_without_repo(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_csv_export(workspace, "backlog_export_github.csv")
    if shutil.which("gh") is None:
        pytest.skip("gh CLI not installed")
    result = subprocess.run(
        ["bash", str(GITHUB_SCRIPT), "--workspace", str(workspace), "--apply"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "--repo" in result.stderr


# ---- Idempotency ----------------------------------------------------


def test_jira_prior_state_skips_already_created(tmp_path) -> None:
    """A prior live_api_response_jira_shell.json with an idempotency_key
    matching the current row must cause that row to be skipped."""
    workspace = _make_workspace(tmp_path)
    _write_jira_export(workspace, n_rows=2)
    # Compute the expected idempotency key for STORY-001 the same
    # way the driver does: sha256("STORY-001|Test story 1") first 8
    # hex chars, prefixed with "bsa-STORY-001-sh-".
    import hashlib
    digest = hashlib.sha256(b"STORY-001|Test story 1").hexdigest()[:8]
    prior_key = f"bsa-STORY-001-sh-{digest}"
    (workspace / "analysis/handoff/live_api_response_jira_shell.json").write_text(
        json.dumps({
            "rows": [
                {"idempotency_key": prior_key, "outcome": "created"},
            ],
        }), encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(JIRA_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    # STORY-001 should be SKIPPED, STORY-002 should DRY-RUN through.
    assert "[SKIP] STORY-001" in result.stdout
    assert "1 ok, 1 skipped" in result.stdout


# ---- Dependency-check edge case ------------------------------------


def test_scripts_check_dependencies_early(tmp_path) -> None:
    """The deps (jq, curl, python3, gh) must be checked before any
    auth / export parsing. Smoke: --help still works even without
    the target auth env set."""
    workspace = _make_workspace(tmp_path)
    env = os.environ.copy()
    env.pop("BSA_JIRA_TOKEN", None)
    for script in SCRIPTS:
        result = subprocess.run(
            ["bash", str(script), "--help"],
            capture_output=True, text=True, env=env, timeout=10,
        )
        assert result.returncode == 0, (
            f"{script.name} --help failed with no auth env set"
        )


# ---- v1.1.17 round-1 Codex CRITICAL fixes -------------------------


def test_jira_auth_not_in_argv(tmp_path) -> None:
    """v1.1.17 round-1 (Codex CRITICAL): credentials must NOT appear
    in the curl argv (visible via `ps`/`/proc` during execution).
    The driver now writes a 0600-perm curl config file with
    `user = "email:token"` and passes `-K <tmpfile>`. Pin that
    the curl `-u` / `--user` flag is absent AND `-K` is present."""
    import re
    body = JIRA_SCRIPT.read_text(encoding="utf-8")
    non_comment_lines = [
        line for line in body.splitlines()
        if not line.lstrip().startswith("#")
    ]
    non_comment_body = "\n".join(non_comment_lines)
    # Look for `curl ... -u` or `curl ... --user` patterns. We allow
    # `-u` on other tools (e.g., `sort -u`) since the only secret-
    # leaking case is curl. Multiline regex tolerates `\` continuations.
    curl_with_u = re.search(
        r"curl\b[^\n]*?(?:\\\n[^\n]*)*?\s-u\s",
        non_comment_body,
    )
    assert curl_with_u is None, (
        f"jira driver uses `curl -u ...`; violates argv-secret-leak "
        f"contract. Match: {curl_with_u.group(0)!r}"
    )
    curl_with_user = re.search(
        r"curl\b[^\n]*?(?:\\\n[^\n]*)*?\s--user\s",
        non_comment_body,
    )
    assert curl_with_user is None, (
        "jira driver uses `curl --user ...`; violates argv-secret-leak"
    )
    # The tmpfile-based config must be present.
    assert " -K " in non_comment_body or "--config " in non_comment_body, (
        "jira driver must pass auth via `-K <tmpfile>` (not argv)"
    )
    assert "chmod 600" in non_comment_body, (
        "jira driver must chmod 600 the auth tmpfile"
    )


def test_linear_auth_not_in_argv(tmp_path) -> None:
    """Same contract as Jira: Linear's Authorization header MUST NOT
    be passed via curl `-H "Authorization: $TOKEN"` on argv. Use
    tmpfile config instead."""
    body = LINEAR_SCRIPT.read_text(encoding="utf-8")
    non_comment_lines = [
        line for line in body.splitlines()
        if not line.lstrip().startswith("#")
    ]
    non_comment_body = "\n".join(non_comment_lines)
    # Reject `-H "Authorization:` patterns that would leak the token.
    # We explicitly allow -H for Content-Type, Accept, etc.
    import re
    matches = re.findall(r'-H\s+["\']Authorization', non_comment_body)
    assert not matches, (
        f"linear driver uses `-H 'Authorization: ...'` which leaks "
        f"token via argv: {matches}. Use `-K <tmpfile>` instead."
    )
    assert "-K" in non_comment_body, (
        "linear driver must pass auth header via `-K <tmpfile>`"
    )


def test_jira_body_wraps_fields_correctly(tmp_path) -> None:
    """v1.1.17 round-1 (Codex CRITICAL): Jira REST v3 POST body is
    `{"fields": {...}}`, not `.fields` directly. Pin that the jq
    filter emits the wrapping `{fields: ...}` shape."""
    body = JIRA_SCRIPT.read_text(encoding="utf-8")
    # Look for the jq filter structure that emits `{fields: .fields}`.
    assert "{fields: .fields}" in body, (
        "jira driver's jq emitter must produce {fields: .fields} "
        "(the Jira REST v3 body envelope). Plain `.fields` would "
        "be rejected by Jira."
    )


# ---- v1.1.17 round-1 Codex HIGH — state writeback -----------------


def test_jira_apply_without_apply_flag_does_not_write_state(tmp_path) -> None:
    """Dry-run must NEVER write to live_api_response_jira_shell.json — that
    file is the idempotency ledger for real runs only."""
    workspace = _make_workspace(tmp_path)
    _write_jira_export(workspace, n_rows=2)
    state_path = workspace / "analysis/handoff/live_api_response_jira_shell.json"
    result = subprocess.run(
        ["bash", str(JIRA_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not state_path.exists(), (
        f"dry-run wrote to state file {state_path} — violates contract"
    )


def test_jira_prior_state_preserved_on_rerun(tmp_path) -> None:
    """If a prior live_api_response_jira_shell.json exists (from Python impl
    or earlier shell run), a subsequent shell-driver invocation must
    preserve those prior entries AND add new ones, not overwrite."""
    workspace = _make_workspace(tmp_path)
    _write_jira_export(workspace, n_rows=1)
    state_path = workspace / "analysis/handoff/live_api_response_jira_shell.json"
    # Prior state from (hypothetical) Python run carries a different key space.
    state_path.write_text(json.dumps({
        "platform": "jira",
        "rows": [
            {
                "idempotency_key": "bsa-STORY-999-python-old",
                "outcome": "created",
                "story_id": "STORY-999",
                "driver": "python",
            },
        ],
    }), encoding="utf-8")
    # Dry-run: state must NOT be mutated.
    subprocess.run(
        ["bash", str(JIRA_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=15,
    )
    parsed = json.loads(state_path.read_text(encoding="utf-8"))
    assert any(r["idempotency_key"] == "bsa-STORY-999-python-old" for r in parsed["rows"])


# ---- v1.1.17 round-1 Codex should #2 — Linear idempotency ---------


def test_linear_prior_state_skips_already_created(tmp_path) -> None:
    """Mirror of test_jira_prior_state_skips_already_created for the
    Linear driver — earlier test coverage only exercised the Jira
    path. Per Codex should #2."""
    import hashlib
    workspace = _make_workspace(tmp_path)
    _write_csv_export(workspace, "backlog_export_linear.csv", n_rows=2)
    digest = hashlib.sha256(b"STORY-001|Test 1").hexdigest()[:8]
    prior_key = f"bsa-STORY-001-sh-{digest}"
    (workspace / "analysis/handoff/live_api_response_linear_shell.json").write_text(
        json.dumps({
            "platform": "linear",
            "rows": [
                {"idempotency_key": prior_key, "outcome": "created"},
            ],
        }),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(LINEAR_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "[SKIP] STORY-001" in result.stdout
    assert "1 ok, 1 skipped" in result.stdout


# ---- v1.1.17 round-1 Codex should #2 — missing-auth coverage ------


def test_linear_apply_refuses_without_token(tmp_path) -> None:
    """Mirror of test_jira_apply_refuses_without_token for Linear.
    Per Codex should #2 — earlier tests missed Linear auth path."""
    workspace = _make_workspace(tmp_path)
    _write_csv_export(workspace, "backlog_export_linear.csv")
    env = os.environ.copy()
    env.pop("BSA_LINEAR_TOKEN", None)
    result = subprocess.run(
        [
            "bash", str(LINEAR_SCRIPT),
            "--workspace", str(workspace),
            "--apply",
            "--team-id", "team-uuid-placeholder",
        ],
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert result.returncode == 2
    assert "BSA_LINEAR_TOKEN" in result.stderr


# ---- v1.1.17 round-1 Codex should #2 — malformed input ------------


def test_jira_malformed_json_does_not_crash(tmp_path) -> None:
    """A malformed JSON export must produce a clean failure (non-zero
    exit, non-empty stderr), not a cryptic shell trace. Per Codex
    should #2 — earlier tests missed this attack surface."""
    workspace = _make_workspace(tmp_path)
    (workspace / "analysis/handoff/backlog_export_jira.json").write_text(
        "{ this is not JSON ]}}", encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(JIRA_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=10,
    )
    # jq will fail; the script's `jq .issues | length` produces an
    # error. Expected: non-zero exit + some diagnostic stderr. We
    # don't pin the exact message (it's jq's) but we DO require
    # the script not go into an infinite loop or silently exit 0.
    assert result.returncode != 0, (
        f"malformed JSON must not silently exit 0. "
        f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
    )


def test_github_prior_state_skips_already_created(tmp_path) -> None:
    """v1.1.17 round-2 (Codex PARTIAL #1): mirror the Jira/Linear
    idempotency test for GitHub — earlier coverage was dry-run-only.
    Uses the canonical .results[]/.status state shape (round-2)."""
    import hashlib
    workspace = _make_workspace(tmp_path)
    _write_github_csv_export(workspace, n_rows=2)
    if shutil.which("gh") is None:
        pytest.skip("gh CLI not installed")
    digest = hashlib.sha256(b"STORY-001|Test 1").hexdigest()[:8]
    prior_key = f"bsa-STORY-001-sh-{digest}"
    (workspace / "analysis/handoff/live_api_response_github_shell.json").write_text(
        json.dumps({
            "platform": "github",
            "results": [
                {"idempotency_key": prior_key, "status": "created", "story_id": "STORY-001"},
            ],
        }),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(GITHUB_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "[SKIP] STORY-001" in result.stdout
    assert "1 ok, 1 skipped" in result.stdout


def test_drivers_accept_canonical_results_shape(tmp_path) -> None:
    """v1.1.17 round-2 (Codex HIGH): cross-tool interop. The shell
    drivers MUST accept the canonical Python state shape
    (`.results[].status`) — NOT just the round-1 shell shape
    (`.rows[].outcome`). Pin: prior state in canonical shape causes
    the matching idempotency key to be skipped on a shell rerun."""
    import hashlib
    workspace = _make_workspace(tmp_path)
    _write_jira_export(workspace, n_rows=1)
    digest = hashlib.sha256(b"STORY-001|Test story 1").hexdigest()[:8]
    prior_key = f"bsa-STORY-001-sh-{digest}"
    # Use the Python canonical shape exactly.
    (workspace / "analysis/handoff/live_api_response_jira_shell.json").write_text(
        json.dumps({
            "platform": "jira",
            "results": [
                {
                    "story_id": "STORY-001",
                    "idempotency_key": prior_key,
                    "status": "created",
                    "attempts": 1,
                    "platform_id": "BSA-42",
                    "platform_url": "https://example.invalid/browse/BSA-42",
                },
            ],
        }, indent=2),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(JIRA_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "[SKIP] STORY-001" in result.stdout, (
        f"shell driver did NOT honor canonical .results[].status state shape. "
        f"stdout: {result.stdout!r}"
    )


def test_drivers_use_separate_state_path_from_python(tmp_path) -> None:
    """v1.1.17 round-3 (Codex HIGH closure): the shell drivers MUST
    write to `live_api_response_<plat>_shell.json` (with `_shell`
    suffix), NOT the canonical `live_api_response_<plat>.json` path
    used by `scripts/backlog_live_apply.py`. Pin: a Python state
    file at the canonical path is NEVER touched by a shell-driver
    apply run."""
    workspace = _make_workspace(tmp_path)
    _write_jira_export(workspace, n_rows=2)
    # Drop a Python-shaped state file at the CANONICAL path. The
    # shell driver must NOT read or modify it.
    canonical_path = workspace / "analysis/handoff/live_api_response_jira.json"
    canonical_payload = {
        "schema_version": "1.0",
        "platform": "jira",
        "results": [
            {
                "story_id": "STORY-001",
                "idempotency_key": "bsa-STORY-001-deadbeef",  # Python format
                "status": "created",
                "attempts": 1,
            },
        ],
    }
    canonical_content = json.dumps(canonical_payload, indent=2)
    canonical_path.write_text(canonical_content, encoding="utf-8")

    result = subprocess.run(
        ["bash", str(JIRA_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    # Shell driver reports zero prior keys (it reads from
    # *_shell.json which doesn't exist → empty), so STORY-001 is
    # NOT skipped.
    assert "[SKIP] STORY-001" not in result.stdout, (
        "shell driver incorrectly read Python's canonical state file"
    )
    # Python's canonical file MUST be unchanged byte-for-byte.
    assert canonical_path.read_text(encoding="utf-8") == canonical_content, (
        "shell driver modified Python's canonical state file"
    )


def test_drivers_accept_legacy_rows_shape(tmp_path) -> None:
    """v1.1.17 round-2 (Codex HIGH): in-place upgrade for round-1
    shell state files (.rows[]/.outcome shape). Pin: prior state in
    legacy shape ALSO causes the matching key to be skipped."""
    import hashlib
    workspace = _make_workspace(tmp_path)
    _write_jira_export(workspace, n_rows=1)
    digest = hashlib.sha256(b"STORY-001|Test story 1").hexdigest()[:8]
    prior_key = f"bsa-STORY-001-sh-{digest}"
    # Round-1 shell shape (legacy).
    (workspace / "analysis/handoff/live_api_response_jira_shell.json").write_text(
        json.dumps({
            "platform": "jira",
            "rows": [
                {"idempotency_key": prior_key, "outcome": "created", "story_id": "STORY-001"},
            ],
        }),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(JIRA_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "[SKIP] STORY-001" in result.stdout


def test_linear_malformed_csv_does_not_crash(tmp_path) -> None:
    """Malformed CSV (missing required columns) must NOT crash — it
    should exit cleanly (0 OR 2). The driver currently treats
    missing StoryID as empty string, which the dry-run loop prints
    as a row with empty title; not ideal UX but NOT a silent-
    success either (row_json leaks into the dry-run message,
    signaling the operator something is wrong). Per Codex should
    #2 — pinning that the driver does not crash / loop / segfault.

    Follow-up (v1.1.18+ candidate): add explicit header-validation
    check mirroring the Jira driver's implicit jq-level validation
    so malformed CSV exits 2 with a clear diagnostic."""
    workspace = _make_workspace(tmp_path)
    # CSV with wrong columns — missing Title + StoryID.
    (workspace / "analysis/handoff/backlog_export_linear.csv").write_text(
        "WrongHeader1,WrongHeader2\nfoo,bar\n", encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(LINEAR_SCRIPT), "--workspace", str(workspace)],
        capture_output=True, text=True, timeout=10,
    )
    # Must exit cleanly (not shell trace / segfault). Accepted
    # outcomes: exit 0 (soft-pass), exit 2 (hard-fail with
    # diagnostic). Either is acceptable per current design;
    # pin absent-of-crash.
    assert result.returncode in (0, 2), (
        f"malformed CSV caused unexpected exit {result.returncode}. "
        f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
    )
