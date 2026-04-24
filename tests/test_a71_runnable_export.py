"""Tests for `scripts/a71_runnable_export.py` (v1.2.3, T3).

Pins the contract documented in the script + skill TODO closure:

  * Cucumber `.feature` files: one per A70 story; correct Gherkin
    structure (Tags above Scenario; Given/When/Then ordering).
  * pytest-bdd export: companion `test_*.py` with module-level
    `scenarios("...")` bulk loader + per-scenario `@given`/`@when`/
    `@then` step-stub functions whose bodies raise
    `pytest.fail("step not implemented")`.
  * jest export: companion `*.steps.js` with jest-cucumber
    `defineFeature` + `test()` blocks + step bodies that throw
    `Error('step not implemented')`.
  * AutomationStatus filter (covers all 5 A71 enum values per
    governance/schemas/a71.schema.json):
    - `automated` + `partial` → exported by default (both have automation)
    - `manual` + `not-automated` → SKIPPED unless `--include-manual`
    - `deferred` → SKIPPED unless `--include-deferred` (A51Ref kept
      as comment)
  * Header validation: missing required column → exit 2.
  * Truncated row → exit 2.
  * Extra-comma overflow → exit 2.
  * Missing workspace / missing A71 → exit 2.
  * `_safe_filename` correctly normalises STORY-PERF-001 → story_perf_001.feature
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "a71_runnable_export.py"
SAMPLE_A71 = REPO_ROOT / "fixtures/golden/project_0001/expected_outputs/canonical/core_controls/A71_test_scenario_register.csv"


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location("a71_runnable_export", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_workspace_with_a71(tmp_path: Path, csv_body: str | None = None) -> Path:
    target_dir = tmp_path / "analysis/canonical/core_controls"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "A71_test_scenario_register.csv"
    if csv_body is None:
        target.write_text(SAMPLE_A71.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        target.write_text(csv_body, encoding="utf-8")
    return tmp_path


# ---- _safe_filename + helpers --------------------------------------


def test_safe_filename_lowercases_and_separates(helper) -> None:
    assert helper._safe_filename("STORY-001", "feature") == "story_001.feature"
    assert helper._safe_filename("STORY-PERF-001", "feature") == "story_perf_001.feature"
    assert helper._safe_filename("STORY-A1B2-099", "py") == "story_a1b2_099.py"


def test_split_tags_filters_empty(helper) -> None:
    assert helper._split_tags("@smoke,@perf") == ("@smoke", "@perf")
    assert helper._split_tags("") == ()
    assert helper._split_tags("@a, , @b") == ("@a", "@b")


# ---- _read_a71 + filter --------------------------------------------


def test_read_real_fixture(helper, tmp_path) -> None:
    workspace = _make_workspace_with_a71(tmp_path)
    a71 = workspace / "analysis/canonical/core_controls/A71_test_scenario_register.csv"
    scenarios, errors = helper._read_a71(a71)
    assert not errors
    assert len(scenarios) == 3
    ts1 = scenarios[0]
    assert ts1.scenario_id == "TS-001"
    assert ts1.story_id == "STORY-001"
    assert ts1.nfr_id == "NFR-PERF-001"
    assert ts1.automation_status == "automated"
    assert "@smoke" in ts1.tags


def test_read_missing_required_column_returns_error(helper, tmp_path) -> None:
    csv_body = (
        "ScenarioID,Title,SourceStoryID,Given,When,Then,Tags,Priority\n"  # missing AutomationStatus
        "TS-001,Test,STORY-001,g,w,t,@smoke,level-1\n"
    )
    workspace = _make_workspace_with_a71(tmp_path, csv_body)
    scenarios, errors = helper._read_a71(workspace / "analysis/canonical/core_controls/A71_test_scenario_register.csv")
    assert not scenarios
    assert any("AutomationStatus" in e for e in errors)


def test_read_truncated_row_returns_error(helper, tmp_path) -> None:
    csv_body = (
        "ScenarioID,Title,SourceStoryID,RelatedNFRID,Given,When,Then,Tags,Priority,AutomationStatus\n"
        "TS-001,Test,STORY-001\n"  # truncated
    )
    workspace = _make_workspace_with_a71(tmp_path, csv_body)
    scenarios, errors = helper._read_a71(workspace / "analysis/canonical/core_controls/A71_test_scenario_register.csv")
    assert not scenarios
    assert any("truncated" in e or "missing cell" in e for e in errors)


def test_read_extra_field_overflow_returns_error(helper, tmp_path) -> None:
    """v1.2.3 mirrors v1.1.17 round-2 contract: unescaped comma in
    text field shifts columns + overflows. Reject."""
    csv_body = (
        "ScenarioID,Title,SourceStoryID,RelatedNFRID,Given,When,Then,Tags,Priority,AutomationStatus\n"
        # When field has unescaped comma → shifts Then into overflow
        "TS-001,Test,STORY-001,,g,unescaped, comma here,t,@smoke,level-1,automated\n"
    )
    workspace = _make_workspace_with_a71(tmp_path, csv_body)
    scenarios, errors = helper._read_a71(workspace / "analysis/canonical/core_controls/A71_test_scenario_register.csv")
    assert not scenarios
    assert any("extra cell" in e or "overflow" in e.lower() for e in errors)


def test_filter_default_drops_manual_and_deferred(helper, tmp_path) -> None:
    workspace = _make_workspace_with_a71(tmp_path)
    scenarios, _ = helper._read_a71(workspace / "analysis/canonical/core_controls/A71_test_scenario_register.csv")
    filtered = helper.filter_scenarios(scenarios, include_manual=False, include_deferred=False)
    assert len(filtered) == 1
    assert filtered[0].automation_status == "automated"


def test_filter_include_manual_adds_manual_only(helper, tmp_path) -> None:
    workspace = _make_workspace_with_a71(tmp_path)
    scenarios, _ = helper._read_a71(workspace / "analysis/canonical/core_controls/A71_test_scenario_register.csv")
    filtered = helper.filter_scenarios(scenarios, include_manual=True, include_deferred=False)
    statuses = {s.automation_status for s in filtered}
    assert statuses == {"automated", "manual"}
    assert len(filtered) == 2


def test_filter_include_both_yields_all(helper, tmp_path) -> None:
    workspace = _make_workspace_with_a71(tmp_path)
    scenarios, _ = helper._read_a71(workspace / "analysis/canonical/core_controls/A71_test_scenario_register.csv")
    filtered = helper.filter_scenarios(scenarios, include_manual=True, include_deferred=True)
    assert len(filtered) == 3


def test_filter_handles_all_5_automation_status_enum_values(helper) -> None:
    """v1.2.3 round-1 (Codex CRITICAL): A71 schema defines 5
    AutomationStatus enum values (automated, partial, manual,
    deferred, not-automated). Earlier impl only handled 3 — `partial`
    and `not-automated` rows silently disappeared. Pin the full
    coverage policy:
      automated     → exported by default
      partial       → exported by default (some automation exists)
      manual        → opt-in via --include-manual
      not-automated → opt-in via --include-manual (semantically
                      equivalent — no automation)
      deferred      → opt-in via --include-deferred
    """
    def _make(status: str) -> "object":
        return helper.Scenario(
            scenario_id=f"TS-{status[:3].upper()}-001", title="x",
            story_id="STORY-001", nfr_id="", given="g", when="w",
            then="t", tags=(), priority="level-2",
            automation_status=status, a51_ref="", notes="",
        )
    all_5 = [_make(s) for s in (
        "automated", "partial", "manual", "deferred", "not-automated",
    )]
    # Default policy.
    default = helper.filter_scenarios(all_5, include_manual=False, include_deferred=False)
    statuses = {s.automation_status for s in default}
    assert statuses == {"automated", "partial"}, (
        f"default should export automated + partial; got {statuses!r}"
    )
    # --include-manual adds both manual + not-automated.
    with_manual = helper.filter_scenarios(all_5, include_manual=True, include_deferred=False)
    statuses = {s.automation_status for s in with_manual}
    assert statuses == {"automated", "partial", "manual", "not-automated"}, (
        f"--include-manual should add BOTH manual + not-automated; got {statuses!r}"
    )
    # --include-deferred adds deferred.
    with_def = helper.filter_scenarios(all_5, include_manual=False, include_deferred=True)
    statuses = {s.automation_status for s in with_def}
    assert statuses == {"automated", "partial", "deferred"}
    # Both flags → all 5.
    all_in = helper.filter_scenarios(all_5, include_manual=True, include_deferred=True)
    assert len(all_in) == 5


# ---- Format generators ---------------------------------------------


def test_cucumber_export_one_feature_per_story(helper, tmp_path) -> None:
    workspace = _make_workspace_with_a71(tmp_path)
    scenarios, _ = helper._read_a71(workspace / "analysis/canonical/core_controls/A71_test_scenario_register.csv")
    filtered = helper.filter_scenarios(scenarios, include_manual=True, include_deferred=True)
    output_dir = tmp_path / "out"
    written = helper.export_cucumber(output_dir, filtered)
    # 3 stories → 3 .feature files
    assert len(written) == 3
    assert {p.name for p in written} == {"story_001.feature", "story_002.feature", "story_003.feature"}


def test_cucumber_feature_body_has_gherkin_structure(helper, tmp_path) -> None:
    workspace = _make_workspace_with_a71(tmp_path)
    scenarios, _ = helper._read_a71(workspace / "analysis/canonical/core_controls/A71_test_scenario_register.csv")
    automated = [s for s in scenarios if s.automation_status == "automated"]
    body = helper._feature_body(automated[0].story_id, automated)
    assert "Feature: STORY-001" in body
    assert "@smoke @perf" in body
    assert "Scenario: TS-001 — High-severity ticket pages on-call inside SLA window" in body
    assert "Given a ticket arrives" in body
    assert "When the triage flow assigns" in body
    assert "Then the on-call agent receives a page" in body
    # Auto-generated header MUST be present so operators don't hand-edit.
    assert "Auto-generated" in body


def test_cucumber_a51_ref_emitted_as_comment_for_deferred(helper, tmp_path) -> None:
    workspace = _make_workspace_with_a71(tmp_path)
    scenarios, _ = helper._read_a71(workspace / "analysis/canonical/core_controls/A71_test_scenario_register.csv")
    deferred = [s for s in scenarios if s.automation_status == "deferred"]
    assert deferred, "fixture must have a deferred scenario for this test"
    body = helper._feature_body(deferred[0].story_id, deferred)
    assert "A51Ref=" in body
    assert deferred[0].a51_ref in body


def test_pytest_bdd_export_writes_feature_and_test_module(helper, tmp_path) -> None:
    workspace = _make_workspace_with_a71(tmp_path)
    scenarios, _ = helper._read_a71(workspace / "analysis/canonical/core_controls/A71_test_scenario_register.csv")
    filtered = helper.filter_scenarios(scenarios, include_manual=False, include_deferred=False)
    output_dir = tmp_path / "out_pytest"
    written = helper.export_pytest_bdd(output_dir, filtered)
    # 1 automated scenario → 1 story → 2 files (.feature + .py)
    assert len(written) == 2
    py_path = next(p for p in written if p.suffix == ".py")
    body = py_path.read_text(encoding="utf-8")
    assert "from pytest_bdd import scenarios, given, when, then" in body
    assert 'scenarios("story_001.feature")' in body
    assert "@given(" in body
    assert "@when(" in body
    assert "@then(" in body
    assert "step not implemented" in body


def test_jest_export_writes_feature_and_steps_module(helper, tmp_path) -> None:
    workspace = _make_workspace_with_a71(tmp_path)
    scenarios, _ = helper._read_a71(workspace / "analysis/canonical/core_controls/A71_test_scenario_register.csv")
    filtered = helper.filter_scenarios(scenarios, include_manual=False, include_deferred=False)
    output_dir = tmp_path / "out_jest"
    written = helper.export_jest(output_dir, filtered)
    assert len(written) == 2
    js_path = next(p for p in written if p.suffix == ".js")
    body = js_path.read_text(encoding="utf-8")
    assert "jest-cucumber" in body
    assert "loadFeature('./story_001.feature')" in body
    assert "defineFeature(feature, test =>" in body
    assert "step not implemented" in body


def test_grouping_by_story_handles_multi_scenario_story(helper) -> None:
    """One story with multiple scenarios → emits a single .feature
    file containing all scenarios in input order."""
    s1 = helper.Scenario(
        scenario_id="TS-001", title="T1", story_id="STORY-001", nfr_id="",
        given="g1", when="w1", then="t1", tags=(), priority="level-1",
        automation_status="automated", a51_ref="", notes="",
    )
    s2 = helper.Scenario(
        scenario_id="TS-002", title="T2", story_id="STORY-001", nfr_id="",
        given="g2", when="w2", then="t2", tags=(), priority="level-2",
        automation_status="automated", a51_ref="", notes="",
    )
    grouped = helper._group_by_story([s1, s2])
    assert grouped == {"STORY-001": [s1, s2]}


# ---- CLI -----------------------------------------------------------


def test_main_returns_2_on_missing_workspace(helper, tmp_path) -> None:
    rc = helper.main([
        "--workspace", str(tmp_path / "absent"),
        "--format", "cucumber",
    ])
    assert rc == 2


def test_main_returns_2_on_missing_a71(helper, tmp_path) -> None:
    (tmp_path / "analysis").mkdir()
    rc = helper.main([
        "--workspace", str(tmp_path),
        "--format", "cucumber",
    ])
    assert rc == 2


def test_main_returns_2_on_invalid_format(helper, tmp_path) -> None:
    workspace = _make_workspace_with_a71(tmp_path)
    # argparse exits with SystemExit(2) on choices violation.
    with pytest.raises(SystemExit) as exc:
        helper.main(["--workspace", str(workspace), "--format", "junit"])
    assert exc.value.code == 2


def test_main_default_export_writes_one_automated_feature(helper, tmp_path) -> None:
    workspace = _make_workspace_with_a71(tmp_path)
    rc = helper.main([
        "--workspace", str(workspace), "--format", "cucumber", "--quiet",
    ])
    assert rc == 0
    out_dir = workspace / "analysis/handoff/runnable_tests/cucumber"
    assert out_dir.is_dir()
    files = sorted(p.name for p in out_dir.glob("*.feature"))
    assert files == ["story_001.feature"]  # only automated scenario


def test_main_include_all_writes_three_features(helper, tmp_path) -> None:
    workspace = _make_workspace_with_a71(tmp_path)
    rc = helper.main([
        "--workspace", str(workspace), "--format", "cucumber",
        "--include-manual", "--include-deferred", "--quiet",
    ])
    assert rc == 0
    out_dir = workspace / "analysis/handoff/runnable_tests/cucumber"
    files = sorted(p.name for p in out_dir.glob("*.feature"))
    assert files == ["story_001.feature", "story_002.feature", "story_003.feature"]


def test_main_custom_output_dir(helper, tmp_path) -> None:
    workspace = _make_workspace_with_a71(tmp_path)
    custom = tmp_path / "custom"
    rc = helper.main([
        "--workspace", str(workspace), "--format", "cucumber",
        "--output-dir", str(custom), "--quiet",
    ])
    assert rc == 0
    assert (custom / "story_001.feature").is_file()
    # Default path should NOT be created.
    assert not (workspace / "analysis/handoff/runnable_tests").exists()
