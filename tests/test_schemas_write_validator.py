"""Write-validator tests for ``governance/schemas/write_validator.py`` (F5, Sprint 5).

This is the single most-impactful test file in Sprint 5: it pins the
mechanical enforcement that closes the Sysco-engagement schema-drift
class. Without these tests passing, F5 is rhetorical only.

Five test groups:

1. **Path dispatcher** — every canonical artifact path resolves to its
   schema; non-canonical paths resolve to None (allow).
2. **Positive cases** — well-formed content for each artifact passes.
3. **Negative cases — Sysco regression class** — exact replays of the
   bad shapes from automated_results/ are blocked. This is the primary
   value of F5: the bad output the plugin produced WITHOUT this hook
   would now be blocked AT the hook.
4. **Negative cases — generic** — invalid JSON, missing fields,
   malformed values.
5. **CLI smoke tests** — the hook's exact integration point.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---- 1. Dispatcher ----------------------------------------------------


@pytest.mark.parametrize(
    "path,expected_schema",
    [
        ("analysis/runtime/ready/stage1.ready.json", "marker"),
        ("analysis/runtime/ready/stage8.no_new_claims.pass.json", "marker"),
        ("analysis/discovery/runtime/ready/discovery.go.json", "marker"),
        ("analysis/runtime/ready/bsa.stage1.entry.enabled.json", "marker"),
        ("analysis/canonical/core_controls/A48_run_context_card.md", "a48"),
        ("analysis/discovery/canonical/core_controls/A48_run_context_card.md", "a48"),
        ("analysis/canonical/core_controls/A50_source_register.csv", "a50"),
        ("analysis/canonical/core_controls/A51_issue_route_register.csv", "a51"),
        ("analysis/canonical/core_controls/A58_evidence_excerpts.csv", "a58"),
        ("analysis/canonical/core_controls/A59_claim_register.csv", "a59"),
        ("analysis/canonical/core_controls/A60_negative_evidence_register.csv", "a60"),
        ("/abs/path/to/repo/analysis/canonical/core_controls/A50_source_register.csv", "a50"),
    ],
)
def test_dispatcher_matches_canonical_paths(path: str, expected_schema: str) -> None:
    from governance.schemas.write_validator import _dispatch

    result = _dispatch(path)
    assert result is not None, f"dispatcher missed canonical path {path}"
    schema_name, _validator_fn = result
    assert schema_name == expected_schema


@pytest.mark.parametrize(
    "path",
    [
        "analysis/proposals/stage3/inputs/sample.md",
        "analysis/views/c4/diagram.puml",
        "analysis/canonical/stage5/some_artifact.json",  # non-core_controls
        "/tmp/random.json",
        "README.md",
    ],
)
def test_dispatcher_skips_non_canonical_paths(path: str) -> None:
    from governance.schemas.write_validator import _dispatch

    assert _dispatch(path) is None


def test_list_known_paths_returns_dispatcher_alphabet() -> None:
    from governance.schemas.write_validator import list_known_paths

    patterns = list_known_paths()
    assert len(patterns) >= 7  # marker + a48 + 5 csv schemas
    assert any("runtime/ready" in p for p in patterns)
    assert any("A48" in p for p in patterns)
    assert any("A59" in p for p in patterns)


# ---- 2. Positive cases ------------------------------------------------


def test_marker_valid_passes() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = json.dumps(
        {
            "marker_id": "stage1.ready",
            "stage": "stage1",
            "verdict": "READY",
            "timestamp": "2026-04-21T10:00:00Z",
            "canon_policy_version": "1.0.0+hash:abc1234",
            "canon_policy_version_hash": "abc1234",
        }
    )
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/stage1.ready.json", content
    )
    assert ok, msgs
    assert any("marker.schema.json" in m for m in msgs)


def test_a48_valid_table_passes() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "# A48 Run Context Card\n\n"
        "| Field | Value |\n"
        "|---|---|\n"
        "| RunID | test-run |\n"
        "| Mode | direct |\n"
        "| CurrentStage | stage1 |\n"
        "| CanonPolicyVersion | 1.0.0 |\n"
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A48_run_context_card.md", content
    )
    assert ok, msgs


def test_a48_valid_bullet_bold_passes() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "# A48 Run Context Card\n\n"
        "- **RunID**: x\n"
        "- **Mode**: discovery_then_bsa\n"
        "- **CurrentStage**: discovery.complete\n"
        "- **CanonPolicyVersion**: 1.0.0\n"
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A48_run_context_card.md", content
    )
    assert ok, msgs


def test_a59_valid_passes() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "ClaimID,SourceID,ExcerptID,ClaimType,Statement,JustificationRationale,A51Ref,ClaimStrength,Criticality,Notes\n"
        'C-001,S-001,E-001,direct,"Some statement",,,"0.85",level-2,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A59_claim_register.csv", content
    )
    assert ok, msgs


def test_non_canonical_path_unconditional_pass() -> None:
    """Anything outside analysis/(discovery/)?canonical/core_controls/
    or runtime/ready/ is silently allowed — the hook's job is to enforce
    canonical schemas, not to govern arbitrary writes."""
    from governance.schemas.write_validator import validate_canonical_write

    ok, msgs = validate_canonical_write(
        "analysis/proposals/stage1/inputs/sample.md", "anything goes"
    )
    assert ok
    assert msgs == []


# ---- 3. Sysco regression class (THE main value of F5) -----------------


def test_sysco_camelcase_marker_blocked() -> None:
    """The exact marker shape that came out of automated_results/discovery/
    runtime/ready/discovery.d1.ready.json is rejected at write time."""
    from governance.schemas.write_validator import validate_canonical_write

    content = json.dumps(
        {
            "marker": "discovery.d1.ready",
            "runId": "SYSCO-OD-DISC-20260420-001",
            "mode": "discovery_then_bsa",
            "emittedAt": "2026-04-20T00:00:00Z",
            "emittedBy": "bsa-orchestrator",
            "canonPolicyVersion": "1.0.0",
        }
    )
    ok, msgs = validate_canonical_write(
        "analysis/discovery/runtime/ready/discovery.d1.ready.json", content
    )
    assert not ok
    err_text = "\n".join(msgs)
    assert "marker_id" in err_text
    assert "timestamp" in err_text


def test_sysco_legacy_no_new_facts_marker_filename_blocked() -> None:
    """The filename pre-Sprint-2 (no_new_facts vs no_new_claims) emits
    a payload whose marker_id is also no_new_facts — the alphabet
    rejects it."""
    from governance.schemas.write_validator import validate_canonical_write

    content = json.dumps(
        {
            "marker_id": "discovery.d5.no_new_facts.pass",  # legacy
            "stage": "d5",
            "verdict": "PASS",
            "timestamp": "2026-04-20T05:00:00Z",
            "canon_policy_version": "1.0.0",
        }
    )
    ok, msgs = validate_canonical_write(
        "analysis/discovery/runtime/ready/discovery.d5.no_new_facts.pass.json",
        content,
    )
    assert not ok
    assert any("not one of" in m for m in msgs)


def test_sysco_legacy_claim_type_in_a59_blocked() -> None:
    """A59 with the legacy ClaimType strings (policy_statement / factual_state /
    process_step / decision_pending) MUST be blocked at the hook. This is the
    single most-impactful negative test in F5 — it's the line that closes the
    Sysco-class drift mechanically rather than rhetorically."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "ClaimID,SourceID,ExcerptID,ClaimType,Statement,JustificationRationale,A51Ref,ClaimStrength,Criticality,Notes\n"
        'C-001,S-001,E-001,policy_statement,"Sysco SOP rule",,,"0.85",level-2,\n'
        'C-002,S-001,E-002,factual_state,"observed state",,,"0.85",level-2,\n'
        'C-003,S-001,E-003,process_step,"step in flow",,,"0.85",level-2,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A59_claim_register.csv", content
    )
    assert not ok
    err_text = "\n".join(msgs)
    # All three legacy values must surface as ClaimType violations.
    assert "policy_statement" in err_text or "ClaimType" in err_text
    # Multiple lines flagged.
    assert sum(1 for m in msgs if "line" in m) >= 3


def test_sysco_drift_tier_label_in_a50_blocked() -> None:
    """A50 with custom-tier labels (T1_multi_source_consistent etc.) is blocked."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        "SourceID,SourceType,Title,Origin,AccessStatus,ReliabilityTier,Priority,Language,DateOrVersion,Notes\n"
        "S-001,document,Test,/tmp/x.md,readable,T1_multi_source_consistent,medium,en,2026-04-20,\n"
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A50_source_register.csv", content
    )
    assert not ok
    assert any("ReliabilityTier" in m or "T1_multi_source_consistent" in m for m in msgs)


# ---- 4. Generic negative cases ----------------------------------------


def test_marker_invalid_json_blocked() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/stage1.ready.json", "{ not valid json"
    )
    assert not ok
    assert any("invalid JSON" in m for m in msgs)


def test_marker_missing_required_blocked() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = json.dumps({"marker_id": "stage1.ready"})
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/stage1.ready.json", content
    )
    assert not ok


def test_a48_no_recognizable_fields_blocked() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A48_run_context_card.md",
        "Just plain prose with no field structure.\n",
    )
    assert not ok
    assert any("no recognizable fields" in m for m in msgs)


def test_csv_column_mismatch_reported() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = "wrong,columns\n1,2\n"
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A51_issue_route_register.csv", content
    )
    assert not ok
    assert any("missing required columns" in m for m in msgs)


# ---- 5. CLI smoke tests (hook integration point) ----------------------


def _run_cli(path: str, content: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "governance.schemas.write_validator", path],
        input=content,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_cli_passes_valid_marker() -> None:
    valid = json.dumps(
        {
            "marker_id": "stage1.ready",
            "stage": "stage1",
            "verdict": "READY",
            "timestamp": "2026-04-21T10:00:00Z",
            "canon_policy_version": "1.0.0",
        }
    )
    result = _run_cli("analysis/runtime/ready/stage1.ready.json", valid)
    assert result.returncode == 0, result.stderr
    assert "matched marker.schema.json" in result.stderr


def test_cli_blocks_sysco_marker() -> None:
    bad = json.dumps(
        {
            "marker": "discovery.d1.ready",
            "emittedAt": "2026-04-20T00:00:00Z",
            "canonPolicyVersion": "1.0.0",
        }
    )
    result = _run_cli("analysis/discovery/runtime/ready/discovery.d1.ready.json", bad)
    assert result.returncode == 1
    assert "BLOCKED" in result.stderr
    assert "marker_id" in result.stderr


def test_cli_passes_unknown_path() -> None:
    """Non-canonical paths are silently allowed (exit 0, no diagnostic)."""
    result = _run_cli("/tmp/random.json", '{"anything": "goes"}')
    assert result.returncode == 0


def test_cli_missing_arg_exits_2() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "governance.schemas.write_validator"],
        input="",
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr
