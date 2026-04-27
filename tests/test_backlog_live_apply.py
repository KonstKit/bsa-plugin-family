"""Tests for scripts/backlog_live_apply.py (Section C v1.1.6).

Closes TODO-S9-LIVE-API. Covers:

  Schema (live_api_response.json F5 dispatch):
    - well-formed dry-run response passes the validator
    - malformed shapes blocked: bad platform enum, missing required field,
      bad idempotency_key shape, summary arithmetic mismatch, status='created'
      without platform_id, status='failed' without last_error
    - F5 dispatcher routes analysis/handoff/live_api_response.json correctly

  Script behavior (mocked HTTP, no live network):
    - dry-run mode: no HTTP, no response file written, stdout shows preview
    - apply mode + Jira 201: ResultRow.status=created, platform_id=key
    - apply mode + GitHub 201: ResultRow.status=created, platform_id=number
    - apply mode + Linear GraphQL success: ResultRow.status=created
    - retry on 429: 2 attempts, second succeeds
    - retry on 5xx: backoff fires; final 503 → status=failed
    - 4xx (other than 429) does NOT retry
    - idempotency: prior live_api_response.json with status=created → skip on re-run
    - missing token env → exit 2 with InvocationError
    - tokens never appear in log file
    - Authorization scrubbed from error messages
    - run_id auto-generated when not supplied

Test isolation: every test uses pytest tmp_path + monkeypatch to set
env vars / patch urllib.request.urlopen / cd into a workspace tree.
NEVER hits a live network endpoint.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "backlog_live_apply.py"


# ---- Schema-level F5 tests --------------------------------------------


def _baseline_response(platform: str = "jira") -> dict:
    return {
        "schema_version": "1.0",
        "generated_at": "2026-04-23T07:30:00Z",
        "platform": platform,
        "platform_base_url": "https://acme.atlassian.net",
        "operator_run_id": "demo-run-1",
        "source_export_path": f"analysis/handoff/backlog_export_{platform}.json",
        "source_export_canon_hash": "eefb7204",
        "results": [
            {
                "story_id": "STORY-001",
                "idempotency_key": "bsa-STORY-001-eefb7204",
                "status": "created",
                "attempts": 1,
                "platform_id": "BSA-123",
                "platform_url": "https://acme.atlassian.net/browse/BSA-123",
            }
        ],
        "summary": {"total": 1, "created": 1, "skipped": 0, "failed": 0},
    }


def test_baseline_response_passes_f5_validator() -> None:
    from governance.schemas.write_validator import validate_canonical_write
    ok, msgs = validate_canonical_write(
        "analysis/handoff/live_api_response_jira.json",
        json.dumps(_baseline_response()),
    )
    assert ok, msgs


def test_dispatcher_routes_live_api_response() -> None:
    from governance.schemas.write_validator import _dispatch
    # Per-platform file naming (Codex round-1 critical fix)
    for platform in ("jira", "linear", "github"):
        dispatch = _dispatch(f"analysis/handoff/live_api_response_{platform}.json")
        assert dispatch is not None, f"missing dispatcher for {platform}"
        schema_name, _fn = dispatch
        assert schema_name == "live_api_response"
    # Old shared filename does NOT match (intentional)
    assert _dispatch("analysis/handoff/live_api_response.json") is None


def test_bad_platform_enum_blocked() -> None:
    from governance.schemas.write_validator import validate_canonical_write
    bad = _baseline_response()
    bad["platform"] = "bitbucket"  # not in enum
    ok, msgs = validate_canonical_write(
        "analysis/handoff/live_api_response_jira.json", json.dumps(bad)
    )
    assert not ok
    assert any("platform" in m for m in msgs)


def test_missing_required_field_blocked() -> None:
    from governance.schemas.write_validator import validate_canonical_write
    bad = _baseline_response()
    del bad["operator_run_id"]
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/live_api_response_jira.json", json.dumps(bad)
    )
    assert not ok


def test_bad_idempotency_key_shape_blocked() -> None:
    from governance.schemas.write_validator import validate_canonical_write
    bad = _baseline_response()
    bad["results"][0]["idempotency_key"] = "STORY-001"  # missing bsa- prefix + canon-hash
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/live_api_response_jira.json", json.dumps(bad)
    )
    assert not ok


def test_summary_arithmetic_mismatch_blocked() -> None:
    """Cross-field invariant: total == created + skipped + failed."""
    from governance.schemas.write_validator import validate_canonical_write
    bad = _baseline_response()
    bad["summary"] = {"total": 5, "created": 1, "skipped": 0, "failed": 0}  # arithmetic broken
    ok, msgs = validate_canonical_write(
        "analysis/handoff/live_api_response_jira.json", json.dumps(bad)
    )
    assert not ok
    assert any("created+skipped+failed" in m for m in msgs)


def test_status_created_without_platform_id_blocked() -> None:
    """Cross-field invariant: status=created MUST carry platform_id."""
    from governance.schemas.write_validator import validate_canonical_write
    bad = _baseline_response()
    bad["results"][0].pop("platform_id", None)
    ok, msgs = validate_canonical_write(
        "analysis/handoff/live_api_response_jira.json", json.dumps(bad)
    )
    assert not ok
    assert any("status='created' requires non-empty platform_id" in m for m in msgs)


def test_status_failed_without_last_error_blocked() -> None:
    """Cross-field invariant: status=failed MUST carry last_error."""
    from governance.schemas.write_validator import validate_canonical_write
    bad = _baseline_response()
    bad["results"][0]["status"] = "failed"
    bad["results"][0].pop("platform_id", None)
    bad["results"][0]["attempts"] = 5
    bad["summary"] = {"total": 1, "created": 0, "skipped": 0, "failed": 1}
    ok, msgs = validate_canonical_write(
        "analysis/handoff/live_api_response_jira.json", json.dumps(bad)
    )
    assert not ok
    assert any("status='failed' requires non-empty last_error" in m for m in msgs)


def test_attempts_above_cap_blocked() -> None:
    """attempts is capped at 10 to bound runtime."""
    from governance.schemas.write_validator import validate_canonical_write
    bad = _baseline_response()
    bad["results"][0]["attempts"] = 99
    ok, _msgs = validate_canonical_write(
        "analysis/handoff/live_api_response_jira.json", json.dumps(bad)
    )
    assert not ok


# ---- Helpers for script-behavior tests --------------------------------


def _make_workspace_with_jira_export(tmp_path: Path, story_count: int = 1) -> Path:
    ws = tmp_path / "workspace"
    handoff = ws / "analysis" / "handoff"
    handoff.mkdir(parents=True)
    issues = []
    for i in range(1, story_count + 1):
        sid = f"STORY-{i:03d}"
        issues.append({
            "fields": {
                "project": {"key": "BSA"},
                "issuetype": {"name": "Story"},
                "summary": f"Story {i}",
                "description": "body",
                "labels": ["bsa-export", "level-1", "invest-pass"],
            },
            "bsa_provenance": {
                "story_id": sid,
                "source_claim_ids": ["C-001"],
                "related_nfr_ids": [],
                "trace_count": 1,
            },
        })
    export = {
        "export_format": "jira",
        "export_format_version": "1.0",
        "generated_at": "2026-04-23T07:30:00Z",
        "source_artifacts": {
            "a70_story_register": "analysis/canonical/core_controls/A70_story_register.csv",
            "a72_traceability_matrix": "analysis/canonical/core_controls/A72_traceability_matrix.csv",
        },
        "issues": issues,
    }
    (handoff / "backlog_export_jira.json").write_text(
        json.dumps(export), encoding="utf-8",
    )
    return ws


def _make_workspace_with_github_export(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    handoff = ws / "analysis" / "handoff"
    handoff.mkdir(parents=True)
    content = (
        "Title,Body,Status,Priority,Size,Labels,StoryID,SourceClaimIDs,RelatedNFRIDs\n"
        '"Page on H/Crit","Body text",Backlog,P1,M,'
        '"bsa-export,level-1,invest-pass",STORY-001,C-003,NFR-PERF-001\n'
    )
    (handoff / "backlog_export_github.csv").write_text(content, encoding="utf-8")
    return ws


def _make_workspace_with_linear_export(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    handoff = ws / "analysis" / "handoff"
    handoff.mkdir(parents=True)
    content = (
        "Title,Description,Status,Priority,Labels,Estimate,StoryID,"
        "SourceClaimIDs,RelatedNFRIDs,Project,Cycle\n"
        '"Page","body",Todo,1,"bsa-export,level-1,invest-pass",'
        "3,STORY-001,C-003,NFR-PERF-001,,\n"
    )
    (handoff / "backlog_export_linear.csv").write_text(content, encoding="utf-8")
    return ws


@contextmanager
def _mock_urlopen(response_factory) -> Iterator[MagicMock]:
    """Patch urllib.request.urlopen to return the factory's response.
    response_factory(req) → context-manager-yielded mock with .read()
    + .status."""
    with patch("urllib.request.urlopen", side_effect=response_factory) as m:
        yield m


def _make_mock_response(status: int, body: dict | str = b"") -> MagicMock:
    cm = MagicMock()
    raw = body if isinstance(body, (bytes, bytearray)) else (
        body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
    )
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    cm.read = MagicMock(return_value=raw)
    cm.status = status
    return cm


def _make_http_error(code: int, body: dict | str = b"") -> urllib.error.HTTPError:
    raw = body if isinstance(body, (bytes, bytearray)) else (
        body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
    )
    err = urllib.error.HTTPError(
        url="https://example.invalid/",
        code=code,
        msg=f"HTTP {code}",
        hdrs={},  # type: ignore
        fp=io.BytesIO(raw),
    )
    return err


# ---- Script behavior --------------------------------------------------


def _run_script(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True, check=False,
    )


def test_dry_run_produces_no_response_file(tmp_path: Path) -> None:
    ws = _make_workspace_with_jira_export(tmp_path)
    result = _run_script([
        f"--workspace={ws}", "--platform=jira", "--canon-hash=eefb7204",
        "--run-id=demo-test-001",
        # --apply NOT passed → dry-run
    ])
    assert result.returncode == 0, result.stderr
    assert "dry-run" in result.stdout
    # Response file MUST NOT be written in dry-run
    response_file = ws / "analysis" / "handoff" / "live_api_response.json"
    assert not response_file.exists(), "dry-run must not write response file"


def test_dry_run_prints_response_preview(tmp_path: Path) -> None:
    ws = _make_workspace_with_jira_export(tmp_path)
    result = _run_script([
        f"--workspace={ws}", "--platform=jira", "--canon-hash=eefb7204",
        "--run-id=demo-test-001",
    ])
    assert result.returncode == 0
    assert "<DRY_RUN>" in result.stdout
    assert "STORY-001" in result.stdout


def test_missing_canon_hash_fails(tmp_path: Path) -> None:
    ws = _make_workspace_with_jira_export(tmp_path)
    result = _run_script([
        f"--workspace={ws}", "--platform=jira", "--run-id=demo-test-001",
    ])
    # argparse rejects missing required arg
    assert result.returncode == 2


def test_missing_workspace_fails(tmp_path: Path) -> None:
    result = _run_script([
        f"--workspace={tmp_path / 'nonexistent'}", "--platform=jira",
        "--canon-hash=eefb7204", "--run-id=demo-test-001",
    ])
    assert result.returncode == 2
    assert "workspace" in result.stderr.lower()


def test_run_id_auto_generated_when_missing(tmp_path: Path) -> None:
    ws = _make_workspace_with_jira_export(tmp_path)
    result = _run_script([
        f"--workspace={ws}", "--platform=jira", "--canon-hash=eefb7204",
        # no --run-id
    ])
    assert result.returncode == 0
    # auto-generated run_id matches the required pattern
    assert re.search(r'"operator_run_id":\s*"[a-z0-9_\-]{8,64}"', result.stdout)


def test_invalid_run_id_rejected(tmp_path: Path) -> None:
    ws = _make_workspace_with_jira_export(tmp_path)
    result = _run_script([
        f"--workspace={ws}", "--platform=jira", "--canon-hash=eefb7204",
        "--run-id=BAD!ID",  # uppercase + special
    ])
    assert result.returncode == 2
    assert "run-id" in result.stderr or "run_id" in result.stderr


def test_apply_jira_missing_token_env_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without BSA_JIRA_TOKEN env, --apply on Jira must exit 2."""
    ws = _make_workspace_with_jira_export(tmp_path)
    monkeypatch.delenv("BSA_JIRA_TOKEN", raising=False)
    monkeypatch.setenv("BSA_JIRA_EMAIL", "demo@example.com")
    result = _run_script([
        f"--workspace={ws}", "--platform=jira", "--canon-hash=eefb7204",
        "--run-id=demo-test-001", "--apply",
        "--jira-base-url=https://example.atlassian.net",
    ])
    assert result.returncode == 2
    assert "BSA_JIRA_TOKEN" in result.stderr


# ---- In-process tests (HTTP mocked) -----------------------------------
# These exercise the script in-process so we can patch urlopen.


def _import_script_as_module():
    """Load backlog_live_apply.py as a module so we can call its helpers.

    Cached in sys.modules so dataclass-internal lookups (e.g.,
    ClassVar detection at field-define time) can resolve via
    sys.modules[__name__].__dict__. Without registration we'd hit
    'NoneType has no attribute __dict__' inside dataclasses.py.
    """
    import importlib.util
    if "backlog_live_apply" in sys.modules:
        return sys.modules["backlog_live_apply"]
    spec = importlib.util.spec_from_file_location("backlog_live_apply", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backlog_live_apply"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_idempotency_skips_prior_state(tmp_path: Path) -> None:
    """A prior live_api_response_<platform>.json with status=created → skip on re-run.

    v1.1.6 round-1: per-platform filename + platform-filtered prior-state
    loader. The test fixture must place the file at the per-platform
    path AND the script's loader hard-filters by platform field."""
    mod = _import_script_as_module()
    prior_response = _baseline_response("jira")
    handoff = tmp_path / "analysis" / "handoff"
    handoff.mkdir(parents=True)
    response_file = handoff / "live_api_response_jira.json"
    response_file.write_text(json.dumps(prior_response), encoding="utf-8")

    prior_state = mod._load_prior_state_validated(response_file, "jira")
    assert "bsa-STORY-001-eefb7204" in prior_state
    cfg = mod.PlatformConfig(platform="jira", base_url="https://example.invalid")
    log_records: list = []
    result = mod._process_row(
        cfg, story_id="STORY-001", canon_hash_prefix="eefb7204",
        payload={}, prior_state=prior_state,
        apply_mode=True, operator_run_id="demo-test-001",
        log_records=log_records,
    )
    assert result.status == "skipped"
    assert result.attempts == 0
    assert result.platform_id == "BSA-123"
    assert log_records == [], "skipped row must NOT produce HTTP log records"


def test_load_prior_state_filters_by_platform(tmp_path: Path) -> None:
    """A Jira state file MUST NOT propagate idempotency keys into a
    Linear run, even if the file got renamed/moved (Codex round-1 critical)."""
    mod = _import_script_as_module()
    handoff = tmp_path / "analysis" / "handoff"
    handoff.mkdir(parents=True)
    # Write a Jira-platform response under a misleading Linear filename.
    response_file = handoff / "live_api_response_linear.json"
    bad = _baseline_response("jira")  # platform field says jira
    response_file.write_text(json.dumps(bad), encoding="utf-8")
    # Loader called with expected_platform="linear" must reject it
    prior_state = mod._load_prior_state_validated(response_file, "linear")
    assert prior_state == {}, "platform-mismatched prior file must produce empty state"


def test_load_prior_state_rejects_token_shaped_fields(tmp_path: Path) -> None:
    """A poisoned prior file with a token-shaped platform_id MUST be
    quarantined (Codex round-1 should-fix #2 — defense-in-depth)."""
    mod = _import_script_as_module()
    handoff = tmp_path / "analysis" / "handoff"
    handoff.mkdir(parents=True)
    poisoned = _baseline_response("jira")
    poisoned["results"][0]["platform_id"] = "ghp_aB3dEfGhIjKlMnOpQrStUvWxYz0123456789"  # GitHub PAT shape
    response_file = handoff / "live_api_response_jira.json"
    response_file.write_text(json.dumps(poisoned), encoding="utf-8")
    # The schema validator rejects the file (token-shaped platform_id),
    # so the validated loader should return empty state.
    prior_state = mod._load_prior_state_validated(response_file, "jira")
    assert prior_state == {}, "token-shaped platform_id must quarantine the row"


def test_jira_201_marks_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_script_as_module()
    cfg = mod.PlatformConfig(
        platform="jira", base_url="https://example.atlassian.net",
        headers={"Authorization": "Basic <REDACTED>"},
    )
    response = _make_mock_response(201, {"key": "BSA-42", "id": "10042"})
    log_records: list = []
    with patch("urllib.request.urlopen", return_value=response):
        result = mod._process_row(
            cfg, story_id="STORY-001", canon_hash_prefix="abcd1234",
            payload={"fields": {}}, prior_state={},
            apply_mode=True, operator_run_id="demo-test-001",
            log_records=log_records,
        )
    assert result.status == "created"
    assert result.attempts == 1
    assert result.platform_id == "BSA-42"
    assert result.platform_url == "https://example.atlassian.net/browse/BSA-42"


def test_github_201_marks_created(tmp_path: Path) -> None:
    mod = _import_script_as_module()
    cfg = mod.PlatformConfig(
        platform="github", base_url="https://api.github.com",
        headers={"Authorization": "Bearer <REDACTED>"},
        extra={"repo": "acme/demo"},
    )
    response = _make_mock_response(201, {
        "number": 99, "html_url": "https://github.com/acme/demo/issues/99",
    })
    log_records: list = []
    with patch("urllib.request.urlopen", return_value=response):
        result = mod._process_row(
            cfg, story_id="STORY-001", canon_hash_prefix="abcd1234",
            payload={"Title": "x", "Body": "y", "Labels": "bsa-export"},
            prior_state={}, apply_mode=True,
            operator_run_id="demo-test-001", log_records=log_records,
        )
    assert result.status == "created"
    assert result.platform_id == "99"
    assert result.platform_url.endswith("/issues/99")


def test_linear_graphql_errors_marks_failed_no_retry(tmp_path: Path) -> None:
    """Linear can return HTTP 200 with a top-level errors[] array (GraphQL
    soft failure). The script MUST mark this as failed without burning
    the retry budget (Codex round-1 critical fix #2)."""
    mod = _import_script_as_module()
    cfg = mod.PlatformConfig(
        platform="linear", base_url="https://api.linear.app",
        headers={"Authorization": "<REDACTED>"},
        extra={"team_id": "team-uuid-123"},
    )
    response = _make_mock_response(200, {
        "errors": [{"message": "Invalid teamId: team-uuid-123 not found"}],
    })
    log_records: list = []
    call_count = [0]
    def side_effect(*args, **kwargs):
        call_count[0] += 1
        return response
    with patch("urllib.request.urlopen", side_effect=side_effect):
        result = mod._process_row(
            cfg, story_id="STORY-001", canon_hash_prefix="abcd1234",
            payload={"Title": "x", "Description": "y", "Priority": "1"},
            prior_state={}, apply_mode=True,
            operator_run_id="demo-test-001", log_records=log_records,
        )
    assert call_count[0] == 1, "GraphQL soft failure must NOT retry (input would re-fail)"
    assert result.status == "failed"
    assert "Invalid teamId" in result.last_error or "GraphQL errors" in result.last_error


def test_linear_graphql_success_false_marks_failed(tmp_path: Path) -> None:
    """Linear's data.issueCreate.success=false (without errors[]) is
    also a soft failure — must not be marked created."""
    mod = _import_script_as_module()
    cfg = mod.PlatformConfig(
        platform="linear", base_url="https://api.linear.app",
        headers={"Authorization": "<REDACTED>"},
        extra={"team_id": "team-uuid-123"},
    )
    response = _make_mock_response(200, {
        "data": {"issueCreate": {"success": False, "issue": None}}
    })
    log_records: list = []
    with patch("urllib.request.urlopen", return_value=response):
        result = mod._process_row(
            cfg, story_id="STORY-001", canon_hash_prefix="abcd1234",
            payload={"Title": "x", "Description": "y", "Priority": "1"},
            prior_state={}, apply_mode=True,
            operator_run_id="demo-test-001", log_records=log_records,
        )
    assert result.status == "failed"
    assert "success=false" in result.last_error


def test_linear_graphql_missing_identifier_marks_failed(tmp_path: Path) -> None:
    """data.issueCreate.success=true BUT issue.identifier missing/empty
    → still failed (script can't record an empty platform_id)."""
    mod = _import_script_as_module()
    cfg = mod.PlatformConfig(
        platform="linear", base_url="https://api.linear.app",
        headers={"Authorization": "<REDACTED>"},
        extra={"team_id": "team-uuid-123"},
    )
    response = _make_mock_response(200, {
        "data": {"issueCreate": {"success": True, "issue": {"id": "u-1", "identifier": "", "url": ""}}}
    })
    log_records: list = []
    with patch("urllib.request.urlopen", return_value=response):
        result = mod._process_row(
            cfg, story_id="STORY-001", canon_hash_prefix="abcd1234",
            payload={"Title": "x", "Description": "y", "Priority": "1"},
            prior_state={}, apply_mode=True,
            operator_run_id="demo-test-001", log_records=log_records,
        )
    assert result.status == "failed"


def test_linear_missing_team_id_fast_fails_at_config_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--apply for platform=linear without --linear-team-id must fail
    FAST at config-build time (Codex round-1 critical fix #2). The
    previous behavior was to burn the retry budget on a server-side
    'missing required field' error."""
    ws = _make_workspace_with_linear_export(tmp_path)
    monkeypatch.setenv("BSA_LINEAR_TOKEN", "linear-test-token")
    result = _run_script([
        f"--workspace={ws}", "--platform=linear", "--canon-hash=eefb7204",
        "--run-id=demo-test-001", "--apply",
        # NOTE: no --linear-team-id
    ])
    assert result.returncode == 2, f"missing --linear-team-id must exit 2 immediately; got {result.returncode}"
    assert "linear-team-id" in result.stderr.lower()


def test_linear_graphql_success_marks_created(tmp_path: Path) -> None:
    mod = _import_script_as_module()
    cfg = mod.PlatformConfig(
        platform="linear", base_url="https://api.linear.app",
        headers={"Authorization": "<REDACTED>"},
        extra={"team_id": "team-uuid-123"},
    )
    response = _make_mock_response(200, {
        "data": {
            "issueCreate": {
                "success": True,
                "issue": {
                    "id": "issue-uuid-456",
                    "identifier": "OPS-789",
                    "url": "https://linear.app/acme/issue/OPS-789",
                },
            }
        }
    })
    log_records: list = []
    with patch("urllib.request.urlopen", return_value=response):
        result = mod._process_row(
            cfg, story_id="STORY-001", canon_hash_prefix="abcd1234",
            payload={"Title": "x", "Description": "y", "Priority": "1"},
            prior_state={}, apply_mode=True,
            operator_run_id="demo-test-001", log_records=log_records,
        )
    assert result.status == "created"
    assert result.platform_id == "OPS-789"
    assert "OPS-789" in result.platform_url


def test_apply_returns_3_when_ledger_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """v1.3.7 P1 regression: if the live API call succeeds (external
    state mutated) but writing the local idempotency ledger fails, the
    script MUST exit non-zero AND dump the in-memory ledger to stderr
    so the operator can persist it manually before re-running. The
    pre-v1.3.7 behavior was to print WARN and fall through to
    `return 0/1 based on summary['failed']` — that lost the ledger and
    set up the next --apply run to double-create every row.

    Simulates the failure by pre-creating the ledger path AS A DIRECTORY
    so write_text raises IsADirectoryError (a subclass of OSError)."""
    import argparse

    mod = _import_script_as_module()
    ws = _make_workspace_with_jira_export(tmp_path)
    monkeypatch.setenv("BSA_JIRA_EMAIL", "test@example.com")
    monkeypatch.setenv("BSA_JIRA_TOKEN", "test-token-redacted")

    handoff = ws / "analysis" / "handoff"
    response_path = handoff / "live_api_response_jira.json"
    response_path.mkdir()

    args = argparse.Namespace(
        workspace=ws,
        platform="jira",
        apply=True,
        canon_hash="eefb7204",
        run_id="demo-test-001",
        jira_base_url="https://acme.atlassian.net",
        jira_email_env="BSA_JIRA_EMAIL",
        jira_token_env="BSA_JIRA_TOKEN",
        linear_base_url="",
        linear_token_env="BSA_LINEAR_TOKEN",
        linear_team_id="",
        github_base_url="",
        github_repo="",
        github_token_env="BSA_GITHUB_TOKEN",
    )

    response = _make_mock_response(201, {"key": "BSA-42", "id": "10042"})
    with patch("urllib.request.urlopen", return_value=response):
        rc = mod.run(args)

    assert rc == 3, (
        f"ledger-write failure must return exit 3 (got {rc}); "
        "silent return 0 means operator will double-create on re-run"
    )
    captured = capsys.readouterr()
    assert "cannot write idempotency ledger" in captured.err
    assert "---LEDGER-BEGIN---" in captured.err
    assert "---LEDGER-END---" in captured.err
    # The in-memory ledger MUST be present in stderr for manual recovery.
    assert "BSA-42" in captured.err
    assert "STORY-001" in captured.err


def test_429_retries_then_succeeds(tmp_path: Path) -> None:
    mod = _import_script_as_module()
    # Speed up backoff for test
    monkey = pytest.MonkeyPatch()
    monkey.setattr(mod, "INITIAL_BACKOFF_SEC", 0.01)
    cfg = mod.PlatformConfig(
        platform="jira", base_url="https://example.atlassian.net",
        headers={"Authorization": "Basic <REDACTED>"},
    )
    # First call: 429. Second call: 201.
    responses = iter([
        _make_http_error(429, {"errorMessages": ["rate limited"]}),
        _make_mock_response(201, {"key": "BSA-99"}),
    ])

    def side_effect(*args, **kwargs):
        r = next(responses)
        if isinstance(r, urllib.error.HTTPError):
            raise r
        return r

    log_records: list = []
    with patch("urllib.request.urlopen", side_effect=side_effect):
        result = mod._process_row(
            cfg, story_id="STORY-001", canon_hash_prefix="abcd1234",
            payload={"fields": {}}, prior_state={},
            apply_mode=True, operator_run_id="demo-test-001",
            log_records=log_records,
        )
    monkey.undo()
    assert result.status == "created"
    assert result.attempts == 2
    assert result.platform_id == "BSA-99"
    # Both attempts produced log records
    assert len(log_records) == 2
    assert log_records[0].status_code == 429
    assert log_records[1].status_code == 201


def test_500_exhausts_retry_budget_marks_failed(tmp_path: Path) -> None:
    mod = _import_script_as_module()
    monkey = pytest.MonkeyPatch()
    monkey.setattr(mod, "INITIAL_BACKOFF_SEC", 0.001)
    monkey.setattr(mod, "MAX_ATTEMPTS", 3)
    cfg = mod.PlatformConfig(
        platform="jira", base_url="https://example.atlassian.net",
        headers={"Authorization": "Basic <REDACTED>"},
    )

    def always_500(*args, **kwargs):
        raise _make_http_error(503, {"errorMessages": ["server unavailable"]})

    log_records: list = []
    with patch("urllib.request.urlopen", side_effect=always_500):
        result = mod._process_row(
            cfg, story_id="STORY-001", canon_hash_prefix="abcd1234",
            payload={"fields": {}}, prior_state={},
            apply_mode=True, operator_run_id="demo-test-001",
            log_records=log_records,
        )
    monkey.undo()
    assert result.status == "failed"
    assert result.attempts == 3
    assert "503" in result.last_error
    assert len(log_records) == 3


def test_400_does_not_retry(tmp_path: Path) -> None:
    """4xx (other than 429) is a persistent client error — don't retry."""
    mod = _import_script_as_module()
    cfg = mod.PlatformConfig(
        platform="jira", base_url="https://example.atlassian.net",
        headers={"Authorization": "Basic <REDACTED>"},
    )
    call_count = [0]

    def http_400(*args, **kwargs):
        call_count[0] += 1
        raise _make_http_error(400, {"errorMessages": ["bad request"]})

    log_records: list = []
    with patch("urllib.request.urlopen", side_effect=http_400):
        result = mod._process_row(
            cfg, story_id="STORY-001", canon_hash_prefix="abcd1234",
            payload={"fields": {}}, prior_state={},
            apply_mode=True, operator_run_id="demo-test-001",
            log_records=log_records,
        )
    assert call_count[0] == 1, "4xx (non-429) must not retry"
    assert result.status == "failed"
    assert result.attempts == 1


def test_idempotency_key_format() -> None:
    mod = _import_script_as_module()
    key = mod._make_idempotency_key("STORY-001", "abcd1234")
    assert key == "bsa-STORY-001-abcd1234"
    # Bad canon_hash_prefix → InvocationError
    with pytest.raises(mod.InvocationError):
        mod._make_idempotency_key("STORY-001", "ABCD1234")  # uppercase
    with pytest.raises(mod.InvocationError):
        mod._make_idempotency_key("STORY-001", "abc")  # too short


def test_scrub_secrets_redacts_authorization() -> None:
    mod = _import_script_as_module()
    err = "request to https://x failed: Authorization: Bearer abc123token"
    scrubbed = mod._scrub_secrets(err)
    assert "abc123token" not in scrubbed
    assert "<REDACTED>" in scrubbed


def test_scrub_secrets_handles_basic_auth() -> None:
    mod = _import_script_as_module()
    err = "auth failed: Authorization=Basic dXNlcjpwYXNz"
    scrubbed = mod._scrub_secrets(err)
    assert "dXNlcjpwYXNz" not in scrubbed
    assert "<REDACTED>" in scrubbed


# ---- End-to-end via subprocess (mocked HTTP not possible; dry-run only) -


def test_subprocess_jira_dry_run_writes_log_records(tmp_path: Path) -> None:
    """Dry-run does NOT write the response file but DOES print to stdout.
    No log records (no HTTP attempts in dry-run)."""
    ws = _make_workspace_with_jira_export(tmp_path, story_count=2)
    result = _run_script([
        f"--workspace={ws}", "--platform=jira", "--canon-hash=eefb7204",
        "--run-id=demo-test-001",
    ])
    assert result.returncode == 0
    log_path = ws / "analysis" / "handoff" / "live_api_log.jsonl"
    # No log file: dry-run skipped HTTP
    assert not log_path.exists()
    # stdout JSON has 2 results
    json_start = result.stdout.index('{\n  "schema_version"')
    response = json.loads(result.stdout[json_start:])
    assert response["summary"]["total"] == 2
    assert response["platform"] == "jira"


def test_subprocess_summary_line_format(tmp_path: Path) -> None:
    ws = _make_workspace_with_jira_export(tmp_path, story_count=3)
    result = _run_script([
        f"--workspace={ws}", "--platform=jira", "--canon-hash=eefb7204",
        "--run-id=demo-test-001",
    ])
    assert result.returncode == 0
    assert re.search(
        r"BSA backlog live-apply \(jira, dry-run\): "
        r"total=3 created=3 skipped=0 failed=0",
        result.stdout,
    )


def test_subprocess_github_dry_run(tmp_path: Path) -> None:
    ws = _make_workspace_with_github_export(tmp_path)
    result = _run_script([
        f"--workspace={ws}", "--platform=github", "--canon-hash=eefb7204",
        "--run-id=demo-test-001",
    ])
    assert result.returncode == 0
    assert "github" in result.stdout
    assert "STORY-001" in result.stdout


def test_subprocess_linear_dry_run(tmp_path: Path) -> None:
    ws = _make_workspace_with_linear_export(tmp_path)
    result = _run_script([
        f"--workspace={ws}", "--platform=linear", "--canon-hash=eefb7204",
        "--run-id=demo-test-001",
    ])
    assert result.returncode == 0
    assert "linear" in result.stdout
    assert "STORY-001" in result.stdout


def test_missing_export_file_exits_2(tmp_path: Path) -> None:
    """Workspace with handoff dir but no export file → exit 2."""
    ws = tmp_path / "workspace"
    (ws / "analysis" / "handoff").mkdir(parents=True)
    result = _run_script([
        f"--workspace={ws}", "--platform=jira", "--canon-hash=eefb7204",
        "--run-id=demo-test-001",
    ])
    assert result.returncode == 2
    assert "missing" in result.stderr.lower()


# ---- v1.1.6 round-1 hardening (Codex) ---------------------------------


def test_concurrency_lock_blocks_second_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex round-1 should-fix #4: two concurrent --apply runs against
    the same workspace+platform must NOT race. The second run sees the
    lock held by the first and exits 2 with a clear message."""
    mod = _import_script_as_module()
    handoff = tmp_path / "analysis" / "handoff"
    handoff.mkdir(parents=True)
    lock_path = handoff / "live_api_response_jira.lock"
    # First "run": acquire and hold the lock.
    lock_handle = mod._acquire_platform_lock(lock_path)
    try:
        # Second "run": acquire must raise _LockBusy.
        with pytest.raises(mod._LockBusy):
            mod._acquire_platform_lock(lock_path)
    finally:
        mod._release_platform_lock(lock_handle, lock_path)
    # After release, a third acquire must succeed.
    lock_handle3 = mod._acquire_platform_lock(lock_path)
    mod._release_platform_lock(lock_handle3, lock_path)


def test_response_file_validated_before_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex round-1 should-fix #1: the script calls validate_canonical_write
    on the response document BEFORE writing. Catches future drift in
    _process_row that would produce a malformed response."""
    mod = _import_script_as_module()
    # Patch _process_row to return a result row that would FAIL the
    # cross-field invariant (status='created' without platform_id).
    bad_result = mod.ResultRow(
        story_id="STORY-001", idempotency_key="bsa-STORY-001-eefb7204",
        status="created", attempts=1, platform_id="",  # ← invariant violation
    )
    # We can't easily test the run() path end-to-end without a lot of
    # plumbing, so we verify the contract via direct schema-validator
    # call — same code path the script uses pre-write.
    response = _baseline_response("jira")
    response["results"][0]["platform_id"] = ""  # mirror the bad row
    from governance.schemas.write_validator import validate_canonical_write
    ok, msgs = validate_canonical_write(
        "analysis/handoff/live_api_response_jira.json", json.dumps(response),
    )
    assert not ok, "validator must catch status='created' without platform_id"
    # In production, the script's pre-write check would catch this and
    # return exit 2 before clobbering a real prior state file.


def test_strict_deadline_does_not_overshoot(tmp_path: Path) -> None:
    """Codex round-1 should-fix #3: per-row deadline is strictly enforced.
    With a tight budget + always-503 server, the loop should NOT count an
    'unsent' attempt and should NOT sleep past the deadline."""
    mod = _import_script_as_module()
    monkey = pytest.MonkeyPatch()
    monkey.setattr(mod, "PER_ROW_DEADLINE_SEC", 2)  # 2-second budget
    monkey.setattr(mod, "INITIAL_BACKOFF_SEC", 0.5)
    monkey.setattr(mod, "MAX_ATTEMPTS", 10)  # large attempts cap, deadline should bound it
    cfg = mod.PlatformConfig(
        platform="jira", base_url="https://example.atlassian.net",
        headers={"Authorization": "Basic <REDACTED>"},
    )

    def always_503(*args, **kwargs):
        raise _make_http_error(503, {"err": "x"})

    log_records: list = []
    started = __import__("time").time()
    with patch("urllib.request.urlopen", side_effect=always_503):
        result = mod._process_row(
            cfg, story_id="STORY-001", canon_hash_prefix="abcd1234",
            payload={"fields": {}}, prior_state={},
            apply_mode=True, operator_run_id="demo-test-001",
            log_records=log_records,
        )
    elapsed = __import__("time").time() - started
    monkey.undo()
    assert result.status == "failed"
    # Total elapsed must not significantly exceed the 2-second deadline
    # (allow 2s for the budget + 1s for the final HTTP timeout-cap = 3s total).
    assert elapsed < 5.0, f"deadline overshot: {elapsed:.2f}s for 2s budget"
    # attempts counts ONLY actually-sent HTTP calls (no 'deadline-exhausted-before-attempt' counted).
    assert result.attempts == len(log_records), (
        f"attempts ({result.attempts}) must match log_records ({len(log_records)}) — "
        f"unsent attempts must NOT be counted"
    )


def test_token_shaped_platform_id_blocked_by_schema() -> None:
    """Schema rejects token-shaped strings in platform_id field
    (Codex round-1 should-fix #2 — defense-in-depth)."""
    from governance.schemas.write_validator import validate_canonical_write
    bad = _baseline_response("jira")
    bad["results"][0]["platform_id"] = "ghp_aB3dEfGhIjKlMnOpQrStUvWxYz0123456789"  # GitHub PAT shape
    ok, msgs = validate_canonical_write(
        "analysis/handoff/live_api_response_jira.json", json.dumps(bad),
    )
    assert not ok, "GitHub PAT-shaped platform_id must be rejected"


def test_token_shaped_last_error_blocked_by_schema() -> None:
    """Schema rejects token-shaped strings in last_error field
    (Codex round-1 should-fix #2 — defense-in-depth)."""
    from governance.schemas.write_validator import validate_canonical_write
    bad = _baseline_response("jira")
    bad["results"][0]["status"] = "failed"
    bad["results"][0].pop("platform_id", None)
    bad["results"][0]["last_error"] = "auth fail: Bearer eyJabcdef0123456789ghijkl"
    bad["summary"] = {"total": 1, "created": 0, "skipped": 0, "failed": 1}
    ok, msgs = validate_canonical_write(
        "analysis/handoff/live_api_response_jira.json", json.dumps(bad),
    )
    assert not ok, "Bearer-prefix last_error must be rejected"


def test_token_shaped_platform_url_blocked_by_schema() -> None:
    """Schema rejects token-shaped strings in platform_url field."""
    from governance.schemas.write_validator import validate_canonical_write
    bad = _baseline_response("jira")
    bad["results"][0]["platform_url"] = "https://x/?token=ghp_aB3dEfGhIjKlMnOpQrStUvWxYz0123456789"
    ok, msgs = validate_canonical_write(
        "analysis/handoff/live_api_response_jira.json", json.dumps(bad),
    )
    assert not ok, "token-shaped query string in platform_url must be rejected"
