"""Tests for `scripts/phase_7_telemetry_collector.py` +
`governance/schemas/telemetry_run.schema.json` (v1.2.4, P1+P2).

Pins:
  * Schema exists + has the v1.2.4 required top-level fields.
  * Collected snapshot validates against the schema (committed +
    representative case + null-KPI cases).
  * KPI-001 weighted formula matches reliability_tier_spec.md
    line 142 (sum of bound ClaimStrength / count of direct claims).
  * KPI-006 story coverage matches bsa-traceability-matrix SKILL.md
    line 71 (|stories with direct A72 row| / |A70 stories|).
  * Null cases (missing A59 / A70 / A72) → status=n/a + value=null.
  * Atomic write: tmpfile in same dir + os.replace.
  * --run-id pattern validation (lowercase + hyphen + underscore;
    8-64 chars).
  * --print-only doesn't write to disk.
  * Auto-generated run_id matches the pattern.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "phase_7_telemetry_collector.py"
SCHEMA_PATH = REPO_ROOT / "governance" / "schemas" / "telemetry_run.schema.json"
SAMPLE_FIXTURE = REPO_ROOT / "fixtures" / "golden" / "project_0001"


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location("phase_7_telemetry_collector", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def jsonschema_module():
    return pytest.importorskip("jsonschema")


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _seed_workspace_from_fixture(tmp_path: Path) -> Path:
    """Copy A59/A70/A72 from project_0001 fixture into a synthetic
    workspace under tmp_path."""
    target = tmp_path / "analysis/canonical/core_controls"
    target.mkdir(parents=True, exist_ok=True)
    src = SAMPLE_FIXTURE / "expected_outputs/canonical/core_controls"
    for fname in ("A50_source_register.csv", "A59_claim_register.csv",
                  "A70_story_register.csv", "A72_traceability_matrix.csv"):
        if (src / fname).is_file():
            (target / fname).write_text((src / fname).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


# ---- Schema presence + shape ---------------------------------------


def test_schema_exists_and_has_required_top_level() -> None:
    assert SCHEMA_PATH.is_file()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    required = set(schema.get("required", []))
    expected = {
        "schema_version", "captured_at", "run_id", "plugin_version",
        "canon_policy_version", "kpi_observations", "summary",
    }
    assert expected <= required, (
        f"schema missing required fields. Expected {expected}, got {required}"
    )


def test_schema_kpi_observation_has_required_fields(schema) -> None:
    """v1.2.4 schema definitionsfor a kpi_observation MUST require
    value/target/comparison/status."""
    kpi_def = schema["$defs"]["kpi_observation"]
    assert set(kpi_def["required"]) >= {"value", "target", "comparison", "status"}
    assert kpi_def["properties"]["status"]["enum"] == ["at_target", "below_target", "n/a"]


# ---- KPI computation -----------------------------------------------


def test_kpi_001_against_real_fixture(helper, tmp_path) -> None:
    workspace = _seed_workspace_from_fixture(tmp_path)
    obs = helper.compute_kpi_001_weighted(workspace)
    assert obs.value is not None
    assert obs.value > 0
    assert obs.target == 0.75
    assert obs.comparison == ">="
    assert obs.status in ("at_target", "below_target")
    assert obs.numerator is not None
    assert obs.denominator is not None
    assert obs.denominator >= 1


def test_kpi_001_returns_na_when_a59_missing(helper, tmp_path) -> None:
    (tmp_path / "analysis").mkdir()
    obs = helper.compute_kpi_001_weighted(tmp_path)
    assert obs.value is None
    assert obs.status == "n/a"


def test_kpi_001_returns_na_when_no_direct_claims(helper, tmp_path) -> None:
    """A59 with only inference / analyst_judgment claims → KPI-001
    is mathematically n/a (denominator 0)."""
    (tmp_path / "analysis/canonical/core_controls").mkdir(parents=True)
    csv_body = (
        "ClaimID,SourceID,ExcerptID,ClaimType,Statement,JustificationRationale,A51Ref,ClaimStrength,Criticality,Notes\n"
        "C-001,S-001,E-001,inference,test,j,,0.5,level-2,n\n"
        "C-002,,,analyst_judgment,test,j,,,level-1,n\n"
    )
    (tmp_path / "analysis/canonical/core_controls/A59_claim_register.csv").write_text(csv_body, encoding="utf-8")
    obs = helper.compute_kpi_001_weighted(tmp_path)
    assert obs.value is None
    assert obs.status == "n/a"
    assert obs.denominator == 0


def test_kpi_001_at_target_when_all_direct_claims_bound_high(helper, tmp_path) -> None:
    (tmp_path / "analysis/canonical/core_controls").mkdir(parents=True)
    csv_body = (
        "ClaimID,SourceID,ExcerptID,ClaimType,Statement,JustificationRationale,A51Ref,ClaimStrength,Criticality,Notes\n"
        "C-001,S-001,E-001,direct,test,,,0.85,level-2,n\n"
        "C-002,S-002,E-002,direct,test,,,0.85,level-2,n\n"
    )
    (tmp_path / "analysis/canonical/core_controls/A59_claim_register.csv").write_text(csv_body, encoding="utf-8")
    obs = helper.compute_kpi_001_weighted(tmp_path)
    assert obs.value == 0.85
    assert obs.status == "at_target"


def test_kpi_001_below_target_when_unbound_dominates(helper, tmp_path) -> None:
    """A59 with mostly unbound direct claims → numerator = sum(bound
    only) / 4 → low value."""
    (tmp_path / "analysis/canonical/core_controls").mkdir(parents=True)
    csv_body = (
        "ClaimID,SourceID,ExcerptID,ClaimType,Statement,JustificationRationale,A51Ref,ClaimStrength,Criticality,Notes\n"
        "C-001,,,direct,unbound,,A51-001,0.85,level-2,n\n"
        "C-002,,,direct,unbound,,A51-002,0.85,level-2,n\n"
        "C-003,,,direct,unbound,,A51-003,0.85,level-2,n\n"
        "C-004,S-001,E-001,direct,bound,,,0.85,level-2,n\n"
    )
    (tmp_path / "analysis/canonical/core_controls/A59_claim_register.csv").write_text(csv_body, encoding="utf-8")
    obs = helper.compute_kpi_001_weighted(tmp_path)
    # 1 bound at 0.85 / 4 direct = 0.2125
    assert obs.value == 0.2125
    assert obs.status == "below_target"
    assert obs.numerator == 0.85
    assert obs.denominator == 4


def test_kpi_006_against_real_fixture(helper, tmp_path) -> None:
    workspace = _seed_workspace_from_fixture(tmp_path)
    obs = helper.compute_kpi_006_story_coverage(workspace)
    assert obs.value is not None
    assert obs.target == 0.90
    assert obs.numerator is not None
    assert obs.denominator is not None
    assert obs.denominator >= 1


def test_kpi_006_returns_na_when_a70_missing(helper, tmp_path) -> None:
    (tmp_path / "analysis").mkdir()
    obs = helper.compute_kpi_006_story_coverage(tmp_path)
    assert obs.value is None
    assert obs.status == "n/a"


def test_kpi_006_returns_na_when_a72_missing(helper, tmp_path) -> None:
    """v1.2.4 round-1 (Codex CRITICAL): KPI-006 requires BOTH A70 +
    A72. Earlier impl only guarded A70 — A70 present + A72 missing
    falsely returned `value=0.0, status=below_target` instead of
    `value=null, status=n/a`. Pin: A72 missing → n/a."""
    (tmp_path / "analysis/canonical/core_controls").mkdir(parents=True)
    a70_body = (
        "StoryID,Title,SourceClaimIDs,RelatedNFRIDs,StoryText,AcceptanceCriteria,Priority,EstimationHint,INVESTStatus,A51Ref,Notes\n"
        "STORY-001,t,C-001,,as a user...,ac,level-2,m,pass,,n\n"
    )
    (tmp_path / "analysis/canonical/core_controls/A70_story_register.csv").write_text(a70_body, encoding="utf-8")
    # NOTE: A72 deliberately NOT created — that's the test case.
    obs = helper.compute_kpi_006_story_coverage(tmp_path)
    assert obs.value is None, (
        f"A72-missing should return value=null; got {obs.value} "
        f"(status={obs.status}). Earlier impl falsely emitted "
        f"value=0.0, status=below_target — re-introducing that "
        f"would falsely signal coverage failure pre-Phase-3."
    )
    assert obs.status == "n/a"


def test_kpi_006_at_target_when_all_stories_traced(helper, tmp_path) -> None:
    (tmp_path / "analysis/canonical/core_controls").mkdir(parents=True)
    a70_body = (
        "StoryID,Title,SourceClaimIDs,RelatedNFRIDs,StoryText,AcceptanceCriteria,Priority,EstimationHint,INVESTStatus,A51Ref,Notes\n"
        "STORY-001,t,C-001,,as a user...,ac,level-2,m,pass,,n\n"
        "STORY-002,t,C-002,,as a user...,ac,level-2,m,pass,,n\n"
    )
    a72_body = (
        "TraceID,StoryID,ClaimID,SourceID,LinkType,LinkStrength,A51Ref,Notes\n"
        "TR-001,STORY-001,C-001,S-001,direct,high,,n\n"
        "TR-002,STORY-002,C-002,S-002,direct,high,,n\n"
    )
    (tmp_path / "analysis/canonical/core_controls/A70_story_register.csv").write_text(a70_body, encoding="utf-8")
    (tmp_path / "analysis/canonical/core_controls/A72_traceability_matrix.csv").write_text(a72_body, encoding="utf-8")
    obs = helper.compute_kpi_006_story_coverage(tmp_path)
    assert obs.value == 1.0
    assert obs.status == "at_target"


# ---- Snapshot + schema validation ----------------------------------


def test_snapshot_validates_against_schema(helper, schema, jsonschema_module, tmp_path) -> None:
    workspace = _seed_workspace_from_fixture(tmp_path)
    snapshot = helper.collect_snapshot(workspace, run_id="test-run-12345")
    validator = jsonschema_module.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(snapshot), key=lambda e: e.path)
    assert not errors, [e.message for e in errors]


def test_snapshot_with_null_kpis_validates(helper, schema, jsonschema_module, tmp_path) -> None:
    """Pre-Stage-1 workspace (no A59 / A70 / A72) → KPI values null;
    snapshot MUST still validate."""
    (tmp_path / "analysis").mkdir()
    snapshot = helper.collect_snapshot(tmp_path, run_id="empty-workspace-test")
    validator = jsonschema_module.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(snapshot), key=lambda e: e.path)
    assert not errors, [e.message for e in errors]
    # Both KPIs should be null + n/a.
    assert snapshot["kpi_observations"]["kpi_001_weighted_coverage"]["value"] is None
    assert snapshot["kpi_observations"]["kpi_001_weighted_coverage"]["status"] == "n/a"
    assert snapshot["kpi_observations"]["kpi_006_story_coverage"]["value"] is None
    assert snapshot["kpi_observations"]["kpi_006_story_coverage"]["status"] == "n/a"
    # Summary counts should reflect the n/a status.
    assert snapshot["summary"]["kpis_captured"] == 2
    assert snapshot["summary"]["kpis_at_target"] == 0
    assert snapshot["summary"]["kpis_below_target"] == 0


def test_snapshot_includes_workspace_path_when_provided(helper, schema, jsonschema_module, tmp_path) -> None:
    workspace = _seed_workspace_from_fixture(tmp_path)
    snapshot = helper.collect_snapshot(
        workspace, run_id="ws-path-test", workspace_path_override="/private/tmp/pilot-workspace",
    )
    assert snapshot["workspace_path"] == "/private/tmp/pilot-workspace"
    validator = jsonschema_module.Draft202012Validator(schema)
    errors = list(validator.iter_errors(snapshot))
    assert not errors


# ---- Atomic write --------------------------------------------------


def test_write_snapshot_atomic_via_same_dir_tmpfile(helper, tmp_path, monkeypatch) -> None:
    target = tmp_path / "analysis/telemetry/run_xyz.json"
    recorded_dirs: list[str] = []
    import tempfile as _tf
    real_mkstemp = _tf.mkstemp
    def spy_mkstemp(**kwargs):
        recorded_dirs.append(kwargs.get("dir", ""))
        return real_mkstemp(**kwargs)
    monkeypatch.setattr(_tf, "mkstemp", spy_mkstemp)
    helper.write_snapshot(target, {"x": 1})
    assert recorded_dirs
    # Resolve to handle macOS /private/var → /var symlink.
    assert Path(recorded_dirs[0]).resolve() == target.parent.resolve(), (
        f"tmpfile in wrong dir: {recorded_dirs[0]} (expected {target.parent})"
    )
    # File written.
    assert target.is_file()
    assert json.loads(target.read_text(encoding="utf-8")) == {"x": 1}


# ---- run_id pattern --------------------------------------------------


def test_auto_generated_run_id_matches_schema_pattern(helper) -> None:
    run_id = helper._generate_run_id()
    assert re.fullmatch(r"[a-z0-9_\-]{8,64}", run_id), (
        f"auto run_id {run_id!r} does not match schema pattern"
    )


# ---- CLI -------------------------------------------------------------


def test_main_returns_2_on_missing_workspace(helper, tmp_path) -> None:
    rc = helper.main(["--workspace", str(tmp_path / "absent")])
    assert rc == 2


def test_main_returns_2_on_invalid_run_id(helper, tmp_path) -> None:
    workspace = _seed_workspace_from_fixture(tmp_path)
    rc = helper.main([
        "--workspace", str(workspace),
        "--run-id", "Bad UPPERCASE!",  # invalid (uppercase + space + !)
    ])
    assert rc == 2


def test_main_writes_snapshot_to_default_path(helper, tmp_path) -> None:
    workspace = _seed_workspace_from_fixture(tmp_path)
    rc = helper.main([
        "--workspace", str(workspace), "--run-id", "default-path-test",
        "--quiet",
    ])
    assert rc == 0
    target = workspace / "analysis/telemetry/run_default-path-test.json"
    assert target.is_file()
    snapshot = json.loads(target.read_text(encoding="utf-8"))
    assert snapshot["run_id"] == "default-path-test"
    assert snapshot["schema_version"] == helper.SCHEMA_VERSION


def test_main_print_only_does_not_write(helper, tmp_path, capsys) -> None:
    workspace = _seed_workspace_from_fixture(tmp_path)
    rc = helper.main([
        "--workspace", str(workspace), "--run-id", "print-only-test",
        "--print-only",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["run_id"] == "print-only-test"
    # Default path should NOT exist.
    assert not (workspace / "analysis/telemetry").exists()


def test_main_custom_output_path(helper, tmp_path) -> None:
    workspace = _seed_workspace_from_fixture(tmp_path)
    custom = tmp_path / "custom_out" / "snapshot.json"
    rc = helper.main([
        "--workspace", str(workspace), "--run-id", "custom-path-test",
        "--output-path", str(custom), "--quiet",
    ])
    assert rc == 0
    assert custom.is_file()
    # Default path should NOT be created.
    assert not (workspace / "analysis/telemetry").exists()
