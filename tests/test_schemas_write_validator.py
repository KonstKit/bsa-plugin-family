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


# ---- 6. apply_edit (Edit-tool support extension) ---------------------


def test_apply_edit_simple_replacement() -> None:
    from governance.schemas.write_validator import apply_edit

    result = apply_edit("hello world", "world", "there")
    assert result == "hello there"


def test_apply_edit_unique_required_when_replace_all_false() -> None:
    """Edit-tool semantics: old_string MUST be unique unless replace_all=True."""
    from governance.schemas.write_validator import apply_edit, EditError

    with pytest.raises(EditError, match="occurs 2 times"):
        apply_edit("foo bar foo", "foo", "baz")


def test_apply_edit_replace_all_does_global() -> None:
    from governance.schemas.write_validator import apply_edit

    result = apply_edit("foo bar foo", "foo", "baz", replace_all=True)
    assert result == "baz bar baz"


def test_apply_edit_missing_old_string_raises() -> None:
    from governance.schemas.write_validator import apply_edit, EditError

    with pytest.raises(EditError, match="not found"):
        apply_edit("hello", "missing", "x")


def test_apply_edit_empty_old_string_raises() -> None:
    from governance.schemas.write_validator import apply_edit, EditError

    with pytest.raises(EditError, match="must be non-empty"):
        apply_edit("hello", "", "x")


def test_apply_edit_noop_raises() -> None:
    """Edit-tool semantics: new_string MUST differ from old_string."""
    from governance.schemas.write_validator import apply_edit, EditError

    with pytest.raises(EditError, match="identical"):
        apply_edit("hello", "hello", "hello")


# ---- 7. v1.0.2 C2: A59 x-bsa-claim-type-rules cross-field enforcement
# Pre-C2 the x-bsa-claim-type-rules extension was documentation-only;
# per-row JSON Schema caught ClaimType enum violations but ignored the
# cross-field rules INV-01 + INV-07 declare. Codex retroactive security
# review flagged this as CRITICAL because:
#   - ClaimType=direct with empty ExcerptID AND empty A51Ref passed F5
#     → unsupported canonical claim lands at write time (INV-01 bypass)
#   - ClaimType=analyst_judgment with empty JustificationRationale passed
#     → untraceable recommendation lands at write time (INV-07 bypass)
# These tests are the regression guard for both paths.


_A59_HEADER = (
    "ClaimID,SourceID,ExcerptID,ClaimType,Statement,JustificationRationale,"
    "A51Ref,ClaimStrength,Criticality,Notes\n"
)


def test_a59_direct_with_empty_excerpt_and_empty_a51_rejected() -> None:
    """INV-01: direct claim without ExcerptID or A51Ref is evidence-less."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A59_HEADER
        + 'C-001,S-001,,direct,"unsupported statement",,,"0.85",level-2,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A59_claim_register.csv", content
    )
    assert not ok, (
        f"C2 regression: ClaimType=direct with empty ExcerptID AND empty A51Ref "
        f"must be blocked per INV-01.\nActual messages: {msgs}"
    )
    err_text = " ".join(msgs)
    assert "ExcerptID" in err_text
    assert "A51Ref" in err_text
    assert "x-bsa-claim-type-rules" in err_text


def test_a59_direct_with_a51ref_alternative_accepted() -> None:
    """INV-01: direct claim guarded by A51Ref is legitimate (unresolved hypothesis)."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A59_HEADER
        + 'C-001,S-001,,direct,"guarded hypothesis",,A51-DEC-007,"0.0",level-2,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A59_claim_register.csv", content
    )
    assert ok, f"direct + A51Ref should pass: {msgs}"


def test_a59_direct_with_excerpt_id_accepted() -> None:
    """INV-01 default path: direct claim with proper evidence."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A59_HEADER
        + 'C-001,S-001,E-001,direct,"supported statement",,,"0.85",level-2,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A59_claim_register.csv", content
    )
    assert ok, f"direct + ExcerptID should pass: {msgs}"


def test_a59_inference_with_empty_excerpt_and_empty_a51_rejected() -> None:
    """INV-01 applies to inference same as direct."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A59_HEADER
        + 'C-001,S-001,,inference,"drift inference",,,"0.45",level-2,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A59_claim_register.csv", content
    )
    assert not ok
    err_text = " ".join(msgs)
    assert "inference" in err_text


def test_a59_analyst_judgment_with_empty_rationale_rejected() -> None:
    """INV-07: analyst_judgment MUST carry JustificationRationale."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A59_HEADER
        + 'C-001,,,analyst_judgment,"ungrounded recommendation",,,,level-2,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A59_claim_register.csv", content
    )
    assert not ok, (
        f"C2 regression: analyst_judgment without JustificationRationale "
        f"must be blocked per INV-07.\nActual messages: {msgs}"
    )
    err_text = " ".join(msgs)
    assert "analyst_judgment" in err_text
    assert "JustificationRationale" in err_text


def test_a59_analyst_judgment_with_rationale_accepted() -> None:
    """INV-07 default path: analyst_judgment with proper rationale passes."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A59_HEADER
        + 'C-001,,,analyst_judgment,"recommendation",'
          '"Derived from C-007 and C-009 via the prioritization-matrix axis weights",'
          ',,level-2,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A59_claim_register.csv", content
    )
    assert ok, f"analyst_judgment + JustificationRationale should pass: {msgs}"


def test_a59_analyst_judgment_a51ref_does_NOT_substitute_for_rationale() -> None:
    """INV-07 is strict: A51Ref is the INV-01 alternative for direct/inference
    only. analyst_judgment always needs JustificationRationale."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A59_HEADER
        + 'C-001,,,analyst_judgment,"ungrounded recommendation",,A51-DEC-042,,level-2,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A59_claim_register.csv", content
    )
    assert not ok, (
        f"A51Ref must NOT substitute for JustificationRationale on "
        f"analyst_judgment rows (INV-07 scope).\nActual: {msgs}"
    )


def test_a59_mixed_valid_and_invalid_rows_surface_only_invalid() -> None:
    """Multi-row input: valid rows silent, invalid rows surface with line numbers."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A59_HEADER
        + 'C-001,S-001,E-001,direct,"supported",,,"0.85",level-2,\n'  # valid
        + 'C-002,S-002,,direct,"unsupported",,,"0.85",level-2,\n'  # INVALID (line 3)
        + 'C-003,,,analyst_judgment,"grounded","upstream from C-001",,,level-2,\n'  # valid
        + 'C-004,,,analyst_judgment,"ungrounded",,,,level-2,\n'  # INVALID (line 5)
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A59_claim_register.csv", content
    )
    assert not ok
    # Both bad rows should be flagged with their line numbers.
    err_text = " ".join(msgs)
    assert "line 3" in err_text
    assert "line 5" in err_text
    # Good rows should not have cross-field violations surfaced.
    assert "line 2" not in err_text
    assert "line 4" not in err_text


def test_a59_claim_type_rules_schema_extension_structure() -> None:
    """Pin the shape of x-bsa-claim-type-rules so future schema edits
    don't silently remove the executable enforcement hook."""
    from governance.schemas import loader

    schema = loader.load_schema("a59")
    rules = schema.get("x-bsa-claim-type-rules", {})
    # All three INV-07 claim types must be declared.
    assert set(rules.keys()) >= {"direct", "inference", "analyst_judgment"}
    # direct + inference require ExcerptID non-empty with A51Ref fallback.
    for ct in ("direct", "inference"):
        rule = rules[ct]
        assert "ExcerptID" in rule["requires_non_empty"]
        assert rule.get("or_a51ref_set") is True
    # analyst_judgment requires JustificationRationale; no A51Ref fallback.
    aj = rules["analyst_judgment"]
    assert "JustificationRationale" in aj["requires_non_empty"]
    assert aj.get("or_a51ref_set", False) is False


# ---- 8. v1.0.2 H-sec-4 — marker filename↔marker_id + FormatChecker ----
# Pre-H-sec-4 the marker validator ran jsonschema WITHOUT FormatChecker,
# so `format: date-time` on timestamp was advisory only. A marker with
# `timestamp: "not-a-date"` silently passed F5. Also, filename↔marker_id
# binding was not enforced, so a file named
# `stage8.no_new_claims.pass.json` could contain an unrelated marker
# payload (e.g., marker_id=`stage1.ready`) and still satisfy
# pre_bash_promote.sh's filename-presence check. This commit closes
# both gaps.


def _valid_marker(marker_id: str = "stage1.ready", **overrides) -> dict:
    base = {
        "marker_id": marker_id,
        "stage": "stage1",
        "verdict": "READY",
        "timestamp": "2026-04-21T10:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    base.update(overrides)
    return base


def test_marker_rejects_malformed_timestamp_post_format_checker() -> None:
    """H-sec-4.1: `timestamp: "not-a-date"` was silently accepted pre-fix."""
    from governance.schemas.write_validator import validate_canonical_write

    bad = _valid_marker(timestamp="not-a-date")
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/stage1.ready.json", json.dumps(bad)
    )
    assert not ok, f"Malformed timestamp passed (H-sec-4.1 regression): {msgs}"
    err_text = " ".join(msgs)
    assert "timestamp" in err_text


def test_marker_accepts_valid_iso8601_timestamp() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    for ts in (
        "2026-04-21T10:00:00Z",
        "2026-04-21T10:00:00.123Z",
        "2026-04-21T10:00:00+04:00",
    ):
        good = _valid_marker(timestamp=ts)
        ok, msgs = validate_canonical_write(
            "analysis/runtime/ready/stage1.ready.json", json.dumps(good)
        )
        assert ok, f"Valid ISO-8601 {ts} rejected: {msgs}"


def test_marker_rejects_filename_mismatch_marker_id() -> None:
    """H-sec-4.2: a file named for one marker MUST contain that marker_id."""
    from governance.schemas.write_validator import validate_canonical_write

    # Filename says stage8 promotion, but payload claims stage1 readiness.
    payload = _valid_marker(
        marker_id="stage1.ready", stage="stage1", verdict="READY"
    )
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/stage8.no_new_claims.pass.json",
        json.dumps(payload),
    )
    assert not ok, (
        "Filename-payload mismatch was not caught (H-sec-4.2 regression). "
        "This is the exploit path pre_bash_promote.sh was vulnerable to: "
        "a file named stage8.no_new_claims.pass.json could satisfy the "
        "marker-presence check while holding an unrelated payload."
    )
    err_text = " ".join(msgs)
    assert "filename-binding" in err_text or "stem" in err_text


def test_marker_accepts_filename_matching_marker_id() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    payload = _valid_marker(marker_id="stage1.ready")
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/stage1.ready.json", json.dumps(payload)
    )
    assert ok, f"Matching filename+marker_id rejected: {msgs}"


def test_marker_rejects_stage_mismatch_marker_id() -> None:
    """H-sec-4.3: stage3.citation_audit.pass implies stage=stage3."""
    from governance.schemas.write_validator import validate_canonical_write

    bad = {
        "marker_id": "stage3.citation_audit.pass",
        "stage": "stage5",  # mismatch — stage3.* should be stage3
        "verdict": "PASS",
        "timestamp": "2026-04-21T10:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/stage3.citation_audit.pass.json", json.dumps(bad)
    )
    assert not ok
    err_text = " ".join(msgs)
    assert "stage" in err_text
    assert "marker_id" in err_text


def test_marker_rejects_verdict_mismatch_marker_id() -> None:
    """H-sec-4.3: stage3.citation_audit.pass implies verdict=PASS."""
    from governance.schemas.write_validator import validate_canonical_write

    bad = {
        "marker_id": "stage3.citation_audit.pass",
        "stage": "stage3",
        "verdict": "FAIL",  # mismatch — *.pass → PASS
        "timestamp": "2026-04-21T10:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/stage3.citation_audit.pass.json", json.dumps(bad)
    )
    assert not ok
    err_text = " ".join(msgs)
    assert "verdict" in err_text


def test_marker_decision_markers_verdict_enforced() -> None:
    """discovery.go implies verdict=GO; discovery.pivot → PIVOT; etc."""
    from governance.schemas.write_validator import validate_canonical_write

    # Valid GO decision.
    good_go = {
        "marker_id": "discovery.go",
        "stage": "discovery.exit",
        "verdict": "GO",
        "timestamp": "2026-04-21T10:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, msgs = validate_canonical_write(
        "analysis/discovery/runtime/ready/discovery.go.json", json.dumps(good_go)
    )
    assert ok, msgs

    # Malicious: marker_id=discovery.no_go but verdict=GO would
    # mis-route downstream consumers.
    bad_decision = {
        "marker_id": "discovery.no_go",
        "stage": "discovery.exit",
        "verdict": "GO",  # mismatch: no_go should be NO_GO
        "timestamp": "2026-04-21T10:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, msgs = validate_canonical_write(
        "analysis/discovery/runtime/ready/discovery.no_go.json",
        json.dumps(bad_decision),
    )
    assert not ok
    err_text = " ".join(msgs)
    assert "verdict" in err_text


def test_marker_bridge_marker_bindings() -> None:
    """bsa.stage1.entry.enabled → stage=discovery.bridge, verdict=READY."""
    from governance.schemas.write_validator import validate_canonical_write

    good = {
        "marker_id": "bsa.stage1.entry.enabled",
        "stage": "discovery.bridge",
        "verdict": "READY",
        "timestamp": "2026-04-21T10:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/bsa.stage1.entry.enabled.json", json.dumps(good)
    )
    assert ok, msgs


def test_dispatcher_normalizes_dotdot_path_traversal() -> None:
    """H-sec-4 round-2 regression: `..` segments must not bypass dispatch.

    Pre-fix: `analysis/runtime/ready/../ready/stage8.no_new_claims.pass.json`
    did NOT match the dispatcher regex (which expected flat paths), so
    the dispatcher returned None and the write passed unchecked. When
    the write layer later resolves `..`, the file lands at
    `analysis/runtime/ready/stage8.no_new_claims.pass.json` — satisfying
    `pre_bash_promote.sh`'s filename-presence check with arbitrary
    content. This test locks the normalization that closes the bypass.
    """
    from governance.schemas.write_validator import _dispatch, validate_canonical_write

    traversal_path = "analysis/runtime/ready/../ready/stage8.no_new_claims.pass.json"
    # 1. Dispatcher now resolves the path and returns the marker validator.
    result = _dispatch(traversal_path)
    assert result is not None, (
        "Dispatcher still returns None for `..`-traversal path "
        "(H-sec-4 round-2 regression)"
    )
    schema_name, _fn = result
    assert schema_name == "marker"

    # 2. End-to-end: a malformed timestamp through a traversal path is
    # now blocked (pre-fix it would have passed).
    bad = _valid_marker(
        marker_id="stage8.no_new_claims.pass",
        stage="stage8",
        verdict="PASS",
        timestamp="not-a-date",
    )
    ok, msgs = validate_canonical_write(traversal_path, json.dumps(bad))
    assert not ok
    err_text = " ".join(msgs)
    assert "timestamp" in err_text


def test_dispatcher_normalizes_leading_dot_slash() -> None:
    """`./analysis/...` should normalize to `analysis/...` and dispatch same."""
    from governance.schemas.write_validator import _dispatch

    result = _dispatch("./analysis/runtime/ready/stage1.ready.json")
    assert result is not None
    assert result[0] == "marker"


def test_dispatcher_normalizes_duplicate_slashes() -> None:
    from governance.schemas.write_validator import _dispatch

    result = _dispatch("analysis//runtime//ready//stage1.ready.json")
    assert result is not None
    assert result[0] == "marker"


def test_dispatcher_normalizes_discovery_traversal() -> None:
    """Same traversal class on discovery paths."""
    from governance.schemas.write_validator import _dispatch

    result = _dispatch(
        "analysis/discovery/canonical/core_controls/../core_controls/A59_claim_register.csv"
    )
    assert result is not None
    assert result[0] == "a59"


def test_marker_stem_uses_normalized_path() -> None:
    """Filename↔marker_id binding must use the normalized stem, not the raw stem."""
    from governance.schemas.write_validator import validate_canonical_write

    # Payload marker_id MATCHES the file that would land after `..` resolution.
    matching = _valid_marker(marker_id="stage1.ready")
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/../ready/stage1.ready.json",
        json.dumps(matching),
    )
    assert ok, f"Normalized-stem match rejected: {msgs}"

    # Payload marker_id does NOT match the normalized-stem → rejected.
    mismatching = _valid_marker(marker_id="stage1.ready")
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/../ready/stage3.citation_audit.pass.json",
        json.dumps(mismatching),
    )
    assert not ok, "Normalized-stem mismatch was not caught"


# ---- 9. v1.0.3 polish — C2 pattern applied to A62/A70 extension rules
# The Sprint-6+7 retroactive review flagged three HIGH findings where
# schema extensions declared rules in plain text but no executable code
# enforced them. This group is the regression guard for the fix:
#   - A62 x-bsa-measurability-rules (NFR INV-09 seed)
#   - A70 x-bsa-provenance-rules (story INV-08 seed)
#   - A70 x-bsa-invest-rules (INVEST-A51 coupling)
# Each test replays a Codex-indicated bypass shape.


_A62_HEADER = (
    "NFRID,NFRCategory,Statement,SourceClaimIDs,MeasurabilityType,"
    "Metric,Target,TestabilityNotes,Criticality,A51Ref,Notes\n"
)
_A70_HEADER = (
    "StoryID,Title,Persona,StoryText,AcceptanceCriteria,SourceClaimIDs,"
    "RelatedNFRIDs,Priority,EstimationHint,INVESTStatus,A51Ref,Notes\n"
)


# A62 measurability rules ---------------------------------------------


def test_a62_performance_without_metric_or_a51_rejected() -> None:
    """INV-09: performance NFR MUST have Metric+Target OR A51Ref."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A62_HEADER
        + 'NFR-001,performance,"Fast please.",C-042,quantitative,,,"load test",level-1,,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A62_nfr_register.csv", content
    )
    assert not ok, (
        "Performance NFR without Metric/Target AND without A51Ref must be "
        "rejected (v1.0.3 INV-09 regression)."
    )
    err_text = " ".join(msgs)
    assert "NFRCategory" in err_text or "performance" in err_text
    assert "x-bsa-measurability-rules" in err_text


def test_a62_availability_without_metric_target_rejected() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A62_HEADER
        + 'NFR-001,availability,"Up always.",C-042,quantitative,,,"check",level-1,,\n'
    )
    ok, _msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A62_nfr_register.csv", content
    )
    assert not ok


def test_a62_scalability_without_metric_target_rejected() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A62_HEADER
        + 'NFR-001,scalability,"Scale up.",C-042,quantitative,,,"bench",level-1,,\n'
    )
    ok, _msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A62_nfr_register.csv", content
    )
    assert not ok


def test_a62_performance_with_metric_and_target_accepted() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A62_HEADER
        + 'NFR-001,performance,"p95 < 500ms.",C-042,quantitative,'
          '"p95 latency ms","< 500","k6 load test",level-1,,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A62_nfr_register.csv", content
    )
    assert ok, f"Valid performance NFR rejected: {msgs}"


def test_a62_performance_with_a51ref_alternative_accepted() -> None:
    """Explicit measurability gap routed via A51: legitimate path."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A62_HEADER
        + 'NFR-001,performance,"Fast, target tbd.",C-042,quantitative,,,'
          '"decide target with PO",level-2,A51-DEC-007,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A62_nfr_register.csv", content
    )
    assert ok, f"A51-routed performance gap should pass: {msgs}"


def test_a62_qualitative_categories_unaffected_by_measurability_rule() -> None:
    """usability/compliance/security don't require Metric+Target by INV-09."""
    from governance.schemas.write_validator import validate_canonical_write

    for category in ("usability", "compliance", "security", "maintainability",
                     "observability", "portability"):
        content = (
            _A62_HEADER
            + f'NFR-001,{category},"Good experience.",C-042,qualitative,,,'
              '"quarterly audit",level-2,,\n'
        )
        ok, msgs = validate_canonical_write(
            "analysis/canonical/core_controls/A62_nfr_register.csv", content
        )
        assert ok, f"{category} NFR falsely rejected by measurability rule: {msgs}"


# A70 provenance rules (INV-08) ---------------------------------------


def test_a70_story_without_any_provenance_rejected() -> None:
    """INV-08: story MUST have at least one of SourceClaimIDs / RelatedNFRIDs non-empty."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A70_HEADER
        + 'STORY-001,"Orphan","Agent",'
          '"As a Agent, I want a feature, so that it works.","it works",'
          ',,level-2,m,pass,,\n'  # both SourceClaimIDs and RelatedNFRIDs empty
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A70_story_register.csv", content
    )
    assert not ok, (
        "Story with no claim AND no NFR provenance must be rejected (INV-08 regression)."
    )
    err_text = " ".join(msgs)
    assert "SourceClaimIDs" in err_text or "RelatedNFRIDs" in err_text
    assert "x-bsa-provenance-rules" in err_text


def test_a70_story_with_claim_only_accepted() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A70_HEADER
        + 'STORY-001,"Claim-rooted","Agent",'
          '"As a Agent, I want X, so that Y.","X happens",'
          'C-042,,level-2,m,pass,,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A70_story_register.csv", content
    )
    assert ok, msgs


def test_a70_story_with_nfr_only_accepted() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A70_HEADER
        + 'STORY-001,"NFR-rooted","Agent",'
          '"As a Agent, I want fast response, so that UX.",'
          '"response < 500ms",'
          ',NFR-PERF-001,level-1,m,pass,,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A70_story_register.csv", content
    )
    assert ok, msgs


# A70 invest rules ----------------------------------------------------


def test_a70_non_pass_invest_without_a51_rejected() -> None:
    """INVESTStatus != 'pass' requires non-empty A51Ref."""
    from governance.schemas.write_validator import validate_canonical_write

    for status in (
        "needs-splitting",
        "needs-estimation",
        "needs-testable-acceptance",
        "needs-negotiation",
        "escalate",
    ):
        content = (
            _A70_HEADER
            + f'STORY-001,"Deferred story","Agent",'
              '"As a Agent, I want X, so that Y.","X happens",'
              f'C-042,,level-2,m,{status},,\n'  # A51Ref empty
        )
        ok, msgs = validate_canonical_write(
            "analysis/canonical/core_controls/A70_story_register.csv", content
        )
        assert not ok, (
            f"INVESTStatus={status!r} without A51Ref must be rejected "
            f"(v1.0.3 INVEST-A51 coupling regression)."
        )
        err_text = " ".join(msgs)
        assert status in err_text
        assert "x-bsa-invest-rules" in err_text


def test_a70_non_pass_invest_with_a51_accepted() -> None:
    """The escape hatch: INVEST-deferred rows with A51Ref are legitimate."""
    from governance.schemas.write_validator import validate_canonical_write

    for status in ("needs-splitting", "needs-estimation", "escalate"):
        content = (
            _A70_HEADER
            + f'STORY-001,"Deferred story","Agent",'
              '"As a Agent, I want X, so that Y.","X happens",'
              f'C-042,,level-2,m,{status},A51-DEC-042,\n'
        )
        ok, msgs = validate_canonical_write(
            "analysis/canonical/core_controls/A70_story_register.csv", content
        )
        assert ok, f"INVESTStatus={status!r} + A51Ref should pass: {msgs}"


def test_a70_pass_invest_without_a51_accepted() -> None:
    """INVESTStatus=pass does NOT require A51Ref."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A70_HEADER
        + 'STORY-001,"Clean story","Agent",'
          '"As a Agent, I want X, so that Y.","X happens",'
          'C-042,,level-2,m,pass,,\n'
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A70_story_register.csv", content
    )
    assert ok, msgs


# Multi-rule interaction ----------------------------------------------


def test_a70_row_can_trip_both_provenance_and_invest_rules() -> None:
    """Orphan + deferred — both violations surface with line number."""
    from governance.schemas.write_validator import validate_canonical_write

    content = (
        _A70_HEADER
        + 'STORY-001,"Orphan deferred","Agent",'
          '"As a Agent, I want X, so that Y.","X happens",'
          ',,level-2,m,escalate,,\n'  # provenance empty + INVEST=escalate, A51Ref empty
    )
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A70_story_register.csv", content
    )
    assert not ok
    err_text = " ".join(msgs)
    # Both rules fire independently.
    assert "provenance-rules" in err_text
    assert "invest-rules" in err_text


def test_marker_sysco_attack_replay_fully_blocked() -> None:
    """The Sysco-engagement attack shape, now with H-sec-4 enforcement.

    Original attack: write `stage8.no_new_claims.pass.json` (which
    pre_bash_promote.sh trusts for Stage-8 promotion) containing an
    unrelated payload. Pre-H-sec-4 the per-row schema could pass if
    the payload was technically a valid marker shape. Now the filename
    binding catches this immediately."""
    from governance.schemas.write_validator import validate_canonical_write

    # Payload is a perfectly valid stage1.ready marker — but lands
    # under the stage8 marker filename.
    attack_payload = _valid_marker(
        marker_id="stage1.ready",
        stage="stage1",
        verdict="READY",
    )
    ok, msgs = validate_canonical_write(
        "analysis/runtime/ready/stage8.no_new_claims.pass.json",
        json.dumps(attack_payload),
    )
    assert not ok
    err_text = " ".join(msgs)
    # Filename binding catches the mismatch even though the payload
    # itself is individually well-formed.
    assert "stage1.ready" in err_text
    assert "stage8.no_new_claims.pass" in err_text
