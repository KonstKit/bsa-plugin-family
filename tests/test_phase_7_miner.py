"""Tests for `scripts/phase_7_miner.py` +
`governance/schemas/miner_proposal.schema.json` (v1.2.18, L1b skeleton).

Pins:
  * Schema exists + has v1.2.18 required top-level fields.
  * Stub `_mine_proposals` always returns [].
  * `_parse_captured_at`: strict ISO-8601 UTC; rejects non-Z, non-strict
    shape, malformed dates.
  * `_validate_telemetry_shape`: required fields enforced; malformed
    docs counted not raised.
  * `_load_telemetry_runs`: reads only `run_*.json`; counts malformed
    files separately.
  * `_filter_by_window`: rolling window semantics
    (today_utc - window_days, today_utc]; future-dated excluded.
  * `build_bundle`: schema-conformant output; summary counts add up;
    proposals always [] in v1.2.18 stub.
  * Atomic write: tmpfile in same dir + os.replace; no `.tmp` leftovers.
  * CLI: --workspace / --telemetry-dir / --window-days / --today /
    --print-only / --quiet / --output-path; error paths
    (uninit workspace, malformed flags).
  * Fixture-based integration: 5 fixtures (3 recent + 1 old + 1
    malformed) → 3 in-window, 1 outside, 1 malformed.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "phase_7_miner.py"
SCHEMA_PATH = REPO_ROOT / "governance" / "schemas" / "miner_proposal.schema.json"
FIXTURE_TELEMETRY_DIR = REPO_ROOT / "tests" / "fixtures" / "telemetry"


# ---- Module loader --------------------------------------------------


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location("phase_7_miner", SCRIPT_PATH)
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


# ---- Workspace + telemetry helpers ----------------------------------


def _make_workspace(tmp_path: Path) -> Path:
    (tmp_path / "analysis" / "telemetry").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _telemetry_dir(workspace: Path) -> Path:
    return workspace / "analysis" / "telemetry"


def _write_run(
    target_dir: Path,
    *,
    run_id: str,
    captured_at: str,
    plugin_version: str = "1.2.17",
    canon_policy_version: str = "1.2.17+hash:ea69b86e",
) -> Path:
    """Write a minimally-valid telemetry-run JSON to target_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema_version": "1.0",
        "captured_at": captured_at,
        "run_id": run_id,
        "plugin_version": plugin_version,
        "canon_policy_version": canon_policy_version,
        "kpi_observations": {},
        "summary": {
            "kpis_captured": 0,
            "kpis_at_target": 0,
            "kpis_below_target": 0,
        },
    }
    path = target_dir / f"run_{run_id}.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


# ---- Schema presence + shape ----------------------------------------


def test_schema_exists_and_has_required_top_level() -> None:
    assert SCHEMA_PATH.is_file()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    expected = {
        "schema_version", "generated_at", "window", "summary", "proposals",
    }
    assert expected <= set(schema.get("required", []))


def test_schema_proposal_def_has_required_fields(schema) -> None:
    proposal = schema["$defs"]["proposal"]
    expected = {
        "proposal_id", "tunable_id", "current_value", "proposed_value",
        "confidence", "evidence_run_ids", "linked_invariants",
        "change_class", "immutable_conflict", "rationale",
    }
    assert set(proposal["required"]) >= expected


def test_schema_summary_has_required_counts(schema) -> None:
    summary = schema["properties"]["summary"]
    expected = {
        "runs_total", "runs_in_window", "runs_excluded_outside_window",
        "runs_excluded_malformed", "proposals_count",
        "proposals_immutable_conflict_count",
    }
    assert set(summary["required"]) >= expected


# ---- Pure unit: _parse_captured_at ----------------------------------


def test_parse_captured_at_iso_z(helper) -> None:
    assert helper._parse_captured_at("2026-04-20T10:00:00Z") == date(2026, 4, 20)


def test_parse_captured_at_rejects_no_z(helper) -> None:
    """Collector emits explicit `Z`. Anything else is suspicious — better
    to count as malformed than silently treat as UTC."""
    assert helper._parse_captured_at("2026-04-20T10:00:00") is None


def test_parse_captured_at_rejects_offset(helper) -> None:
    """Per telemetry_run.schema.json the pattern allows `±HH:MM` but the
    collector specifically emits Z-suffixed UTC. Miner only consumes Z
    for window arithmetic — explicitly reject offsets to surface clock-
    skew or non-UTC capture."""
    assert helper._parse_captured_at("2026-04-20T10:00:00+02:00") is None


def test_parse_captured_at_rejects_short_string(helper) -> None:
    assert helper._parse_captured_at("2026-04") is None


def test_parse_captured_at_rejects_non_string(helper) -> None:
    assert helper._parse_captured_at(None) is None
    assert helper._parse_captured_at(12345) is None


def test_parse_captured_at_rejects_invalid_date(helper) -> None:
    assert helper._parse_captured_at("2026-02-30T10:00:00Z") is None


# ---- Pure unit: _validate_telemetry_shape ---------------------------


def test_validate_shape_minimal_valid(helper) -> None:
    assert helper._validate_telemetry_shape({
        "schema_version": "1.0",
        "captured_at": "2026-04-20T10:00:00Z",
        "run_id": "x" * 8,
        "plugin_version": "1.2.17",
        "canon_policy_version": "1.2.17+hash:ea69b86e",
        "kpi_observations": {},
        "summary": {},
    }) is True


def test_validate_shape_missing_field_rejected(helper) -> None:
    assert helper._validate_telemetry_shape({
        "schema_version": "1.0",
        "captured_at": "2026-04-20T10:00:00Z",
        "run_id": "x" * 8,
        # missing plugin_version, canon_policy_version, kpi_observations, summary
    }) is False


def test_validate_shape_non_dict_rejected(helper) -> None:
    assert helper._validate_telemetry_shape("not a dict") is False
    assert helper._validate_telemetry_shape(None) is False
    assert helper._validate_telemetry_shape([]) is False


def test_validate_shape_captured_at_must_be_string(helper) -> None:
    assert helper._validate_telemetry_shape({
        "schema_version": "1.0",
        "captured_at": 1234,  # not a string
        "run_id": "x" * 8,
        "plugin_version": "1.2.17",
        "canon_policy_version": "1.2.17+hash:ea69b86e",
        "kpi_observations": {},
        "summary": {},
    }) is False


# ---- _load_telemetry_runs -------------------------------------------


def test_load_runs_empty_dir(helper, tmp_path) -> None:
    runs, malformed = helper._load_telemetry_runs(tmp_path)
    assert runs == []
    assert malformed == 0


def test_load_runs_missing_dir_returns_empty(helper, tmp_path) -> None:
    runs, malformed = helper._load_telemetry_runs(tmp_path / "nonexistent")
    assert runs == []
    assert malformed == 0


def test_load_runs_skips_non_run_files(helper, tmp_path) -> None:
    """Only `run_*.json` files are eligible — the `miner_proposals.json`
    output file (and any other JSON) must be silently ignored, otherwise
    the miner would re-ingest its own output."""
    target_dir = _telemetry_dir(_make_workspace(tmp_path))
    _write_run(target_dir, run_id="aaaaaaaa", captured_at="2026-04-20T10:00:00Z")
    # Drop a non-eligible file in the same dir.
    (target_dir / "miner_proposals.json").write_text(
        '{"hello": "world"}', encoding="utf-8"
    )
    runs, malformed = helper._load_telemetry_runs(target_dir)
    assert len(runs) == 1
    assert malformed == 0


def test_load_runs_counts_malformed_separately(helper, tmp_path) -> None:
    target_dir = _telemetry_dir(_make_workspace(tmp_path))
    _write_run(target_dir, run_id="aaaaaaaa", captured_at="2026-04-20T10:00:00Z")
    # Garbage JSON.
    (target_dir / "run_garbage.json").write_text("not { json", encoding="utf-8")
    # Valid JSON but missing required fields.
    (target_dir / "run_partial.json").write_text(
        '{"schema_version": "1.0"}', encoding="utf-8"
    )
    runs, malformed = helper._load_telemetry_runs(target_dir)
    assert len(runs) == 1
    assert malformed == 2


def test_load_runs_deterministic_order(helper, tmp_path) -> None:
    """Files are read in sorted-filename order so test output is stable."""
    target_dir = _telemetry_dir(_make_workspace(tmp_path))
    for rid in ("zzzzzzzz", "aaaaaaaa", "mmmmmmmm"):
        _write_run(target_dir, run_id=rid, captured_at="2026-04-20T10:00:00Z")
    runs, _ = helper._load_telemetry_runs(target_dir)
    assert [r["run_id"] for r in runs] == ["aaaaaaaa", "mmmmmmmm", "zzzzzzzz"]


# ---- _filter_by_window ----------------------------------------------


def test_filter_in_window(helper) -> None:
    runs = [{"captured_at": "2026-04-20T10:00:00Z"}]
    in_window, outside, parse_failed = helper._filter_by_window(
        runs, today_utc=date(2026, 4, 25), window_days=30,
    )
    assert len(in_window) == 1
    assert outside == 0
    assert parse_failed == 0


def test_filter_outside_window_old(helper) -> None:
    runs = [{"captured_at": "2026-01-01T10:00:00Z"}]
    in_window, outside, parse_failed = helper._filter_by_window(
        runs, today_utc=date(2026, 4, 25), window_days=30,
    )
    assert in_window == []
    assert outside == 1
    assert parse_failed == 0


def test_filter_window_lower_bound_open(helper) -> None:
    """A run captured exactly window_days ago is OUTSIDE the window
    (lower bound is strictly greater-than). today_utc - 30 → excluded."""
    runs = [{"captured_at": "2026-03-26T10:00:00Z"}]  # exactly 30 days before 2026-04-25
    in_window, outside, parse_failed = helper._filter_by_window(
        runs, today_utc=date(2026, 4, 25), window_days=30,
    )
    assert in_window == []
    assert outside == 1
    assert parse_failed == 0


def test_filter_window_one_day_inside_boundary(helper) -> None:
    """A run captured 29 days ago IS in the window (delta < window_days)."""
    runs = [{"captured_at": "2026-03-27T10:00:00Z"}]
    in_window, outside, parse_failed = helper._filter_by_window(
        runs, today_utc=date(2026, 4, 25), window_days=30,
    )
    assert len(in_window) == 1
    assert outside == 0
    assert parse_failed == 0


def test_filter_excludes_future_dated_as_outside_window(helper) -> None:
    """Future-dated runs are outside-window (clock skew is a valid-
    but-out-of-range timestamp, not malformed input)."""
    runs = [{"captured_at": "2027-01-01T10:00:00Z"}]
    in_window, outside, parse_failed = helper._filter_by_window(
        runs, today_utc=date(2026, 4, 25), window_days=30,
    )
    assert in_window == []
    assert outside == 1
    assert parse_failed == 0


def test_filter_unparseable_captured_at_counted_as_parse_failed(helper) -> None:
    """R1 fix: previously unparseable timestamps were lumped into
    `outside_window` which misled operators debugging rejected `+02:00`
    or fractional timestamps. Now classified as parse_failed and
    folded back into the malformed bucket by `build_bundle`."""
    runs = [{"captured_at": "garbage"}]
    in_window, outside, parse_failed = helper._filter_by_window(
        runs, today_utc=date(2026, 4, 25), window_days=30,
    )
    assert in_window == []
    assert outside == 0
    assert parse_failed == 1


def test_filter_offset_timestamp_counted_as_parse_failed(helper) -> None:
    """R1 fix: `+02:00`-suffixed timestamp is shape-valid (string) but
    rejected by `_parse_captured_at`. Goes to parse_failed → operator-
    visible as malformed in the bundle summary."""
    runs = [{"captured_at": "2026-04-20T10:00:00+02:00"}]
    in_window, outside, parse_failed = helper._filter_by_window(
        runs, today_utc=date(2026, 4, 25), window_days=30,
    )
    assert in_window == []
    assert outside == 0
    assert parse_failed == 1


# ---- _mine_proposals (stub) -----------------------------------------


def test_mine_proposals_stub_returns_empty(helper) -> None:
    """v1.2.18: skeleton ships stub algorithm; always [].
    This test will FAIL when a real algorithm lands — that's the
    explicit signal to update the test as part of the algorithm PR."""
    assert helper._mine_proposals([]) == []
    assert helper._mine_proposals([{"any": "input"}]) == []
    assert helper._mine_proposals(
        [{"a": 1}, {"b": 2}, {"c": 3}]
    ) == []


# ---- build_bundle ---------------------------------------------------


def test_build_bundle_empty_workspace(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    bundle = helper.build_bundle(
        workspace, today_utc=date(2026, 4, 25), window_days=30,
    )
    assert bundle["schema_version"] == "1.0"
    assert bundle["window"]["window_days"] == 30
    assert bundle["window"]["today_utc"] == "2026-04-25"
    s = bundle["summary"]
    assert s["runs_total"] == 0
    assert s["runs_in_window"] == 0
    assert s["proposals_count"] == 0
    assert s["proposals_immutable_conflict_count"] == 0
    assert bundle["proposals"] == []


def test_build_bundle_validates_against_schema(
    helper, jsonschema_module, schema, tmp_path
) -> None:
    workspace = _make_workspace(tmp_path)
    target = _telemetry_dir(workspace)
    _write_run(target, run_id="aaaaaaaa", captured_at="2026-04-20T10:00:00Z")
    bundle = helper.build_bundle(
        workspace, today_utc=date(2026, 4, 25), window_days=30,
    )
    validator = jsonschema_module.Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(bundle), key=lambda e: list(e.absolute_path)
    )
    assert errors == [], (
        f"bundle does not validate against schema:\n"
        + "\n".join(f"{e.absolute_path}: {e.message}" for e in errors)
    )


def test_build_bundle_summary_counts_add_up(helper, tmp_path) -> None:
    """runs_total == runs_in_window + runs_excluded_outside_window
    + runs_excluded_malformed."""
    workspace = _make_workspace(tmp_path)
    target = _telemetry_dir(workspace)
    # 2 recent (in window).
    _write_run(target, run_id="recent01", captured_at="2026-04-20T10:00:00Z")
    _write_run(target, run_id="recent02", captured_at="2026-04-15T10:00:00Z")
    # 1 old (outside window).
    _write_run(target, run_id="oldold01", captured_at="2026-01-01T10:00:00Z")
    # 1 malformed.
    (target / "run_malformed.json").write_text("garbage", encoding="utf-8")
    bundle = helper.build_bundle(
        workspace, today_utc=date(2026, 4, 25), window_days=30,
    )
    s = bundle["summary"]
    assert s["runs_total"] == 4  # all files including malformed
    assert s["runs_in_window"] == 2
    assert s["runs_excluded_outside_window"] == 1
    assert s["runs_excluded_malformed"] == 1
    # Conservation invariant.
    assert (
        s["runs_in_window"]
        + s["runs_excluded_outside_window"]
        + s["runs_excluded_malformed"]
        == s["runs_total"]
    )


def test_build_bundle_parse_failed_captured_at_folded_into_malformed(
    helper, tmp_path
) -> None:
    """R1 fix: a shape-valid run whose `captured_at` doesn't parse as
    strict YYYY-MM-DDTHH:MM:SSZ (e.g., `+02:00` offset, fractional)
    must surface in `runs_excluded_malformed`, NOT in
    `runs_excluded_outside_window`. Pre-R1 lumping there misled
    operators debugging non-Z timestamps."""
    workspace = _make_workspace(tmp_path)
    target = _telemetry_dir(workspace)
    # 1 valid in-window.
    _write_run(target, run_id="recent01", captured_at="2026-04-20T10:00:00Z")
    # 1 shape-valid but captured_at has +02:00 offset (non-Z).
    _write_run(target, run_id="offsetts", captured_at="2026-04-20T10:00:00+02:00")
    # 1 shape-valid but captured_at is garbage.
    _write_run(target, run_id="badparse", captured_at="not-a-timestamp")
    bundle = helper.build_bundle(
        workspace, today_utc=date(2026, 4, 25), window_days=30,
    )
    s = bundle["summary"]
    assert s["runs_in_window"] == 1
    assert s["runs_excluded_outside_window"] == 0
    # Both parse-failed runs land in the malformed bucket.
    assert s["runs_excluded_malformed"] == 2
    # Conservation invariant still holds.
    assert (
        s["runs_in_window"]
        + s["runs_excluded_outside_window"]
        + s["runs_excluded_malformed"]
        == s["runs_total"]
    )


def test_build_bundle_against_committed_fixtures(
    helper, jsonschema_module, schema
) -> None:
    """Read the 5 committed fixtures: 3 recent + 1 old + 1 malformed."""
    bundle = helper.build_bundle(
        REPO_ROOT,  # workspace doesn't matter when telemetry_dir is given
        telemetry_dir=FIXTURE_TELEMETRY_DIR,
        today_utc=date(2026, 4, 25),
        window_days=30,
    )
    s = bundle["summary"]
    assert s["runs_total"] == 5
    assert s["runs_in_window"] == 3  # run_001/002/003
    assert s["runs_excluded_outside_window"] == 1  # run_004 (Jan 5)
    assert s["runs_excluded_malformed"] == 1  # run_005
    assert s["proposals_count"] == 0  # stub
    # Validate against schema.
    validator = jsonschema_module.Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(bundle), key=lambda e: list(e.absolute_path)
    )
    assert errors == []


# ---- CLI ------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_print_only_does_not_write(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(workspace),
        "--print-only",
        "--today", "2026-04-25",
    )
    assert result.returncode == 0
    bundle = json.loads(result.stdout)
    assert bundle["proposals"] == []
    assert not (workspace / "analysis/telemetry/miner_proposals.json").exists()


def test_cli_writes_bundle(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(workspace),
        "--today", "2026-04-25",
        "--quiet",
    )
    assert result.returncode == 0
    out = workspace / "analysis/telemetry/miner_proposals.json"
    assert out.exists()
    bundle = json.loads(out.read_text(encoding="utf-8"))
    assert bundle["schema_version"] == "1.0"


def test_cli_telemetry_dir_override(tmp_path) -> None:
    """--telemetry-dir lets the miner read fixtures without a BSA
    workspace (no analysis/ dir required)."""
    result = _run_cli(
        "--workspace", str(tmp_path),  # no analysis/ dir
        "--telemetry-dir", str(FIXTURE_TELEMETRY_DIR),
        "--today", "2026-04-25",
        "--print-only",
    )
    assert result.returncode == 0
    bundle = json.loads(result.stdout)
    assert bundle["summary"]["runs_in_window"] == 3


def test_cli_window_days_override(tmp_path) -> None:
    """--window-days=200 should pull run_004 (Jan 5) into window."""
    result = _run_cli(
        "--workspace", str(tmp_path),
        "--telemetry-dir", str(FIXTURE_TELEMETRY_DIR),
        "--window-days", "200",
        "--today", "2026-04-25",
        "--print-only",
    )
    assert result.returncode == 0
    bundle = json.loads(result.stdout)
    # run_004 (Jan 5) is now within 200 days of Apr 25.
    assert bundle["summary"]["runs_in_window"] == 4


def test_cli_workspace_not_initialized_returns_2(tmp_path) -> None:
    """No --telemetry-dir override AND no analysis/ dir → exit 2."""
    result = _run_cli(
        "--workspace", str(tmp_path),
        "--today", "2026-04-25",
        "--print-only",
    )
    assert result.returncode == 2
    assert "not initialized" in result.stderr


def test_cli_explicit_telemetry_dir_missing_returns_2(tmp_path) -> None:
    """R1 fix: an explicit --telemetry-dir typo previously slipped
    through as exit 0 + empty bundle. Now rejected with exit 2 so the
    operator sees the typo immediately rather than misreading 'zero
    telemetry' as the L2 baseline. The implicit (workspace-derived)
    path remains permissive — see
    test_cli_implicit_missing_telemetry_dir_is_permissive."""
    workspace = _make_workspace(tmp_path)
    bogus = workspace / "this_dir_does_not_exist"
    result = _run_cli(
        "--workspace", str(workspace),
        "--telemetry-dir", str(bogus),
        "--today", "2026-04-25",
        "--print-only",
    )
    assert result.returncode == 2
    assert "does not exist" in result.stderr or "not a directory" in result.stderr


def test_cli_explicit_telemetry_dir_pointing_to_file_returns_2(tmp_path) -> None:
    """R1 fix follow-on: --telemetry-dir pointing at a regular file
    (not a directory) must also be rejected — same fail-fast rationale."""
    workspace = _make_workspace(tmp_path)
    file_not_dir = workspace / "this_is_a_file.txt"
    file_not_dir.write_text("not a directory", encoding="utf-8")
    result = _run_cli(
        "--workspace", str(workspace),
        "--telemetry-dir", str(file_not_dir),
        "--today", "2026-04-25",
        "--print-only",
    )
    assert result.returncode == 2


def test_cli_implicit_missing_telemetry_dir_is_permissive(tmp_path) -> None:
    """Implicit path: workspace has analysis/ but not analysis/telemetry/.
    This is a legitimate 'no runs captured yet' state, not a typo →
    miner emits empty bundle with exit 0. Pinned to prevent future
    over-tightening that would block operators on first run."""
    workspace = tmp_path
    (workspace / "analysis").mkdir()  # has analysis/, no telemetry/ subdir
    result = _run_cli(
        "--workspace", str(workspace),
        "--today", "2026-04-25",
        "--print-only",
    )
    assert result.returncode == 0
    bundle = json.loads(result.stdout)
    assert bundle["summary"]["runs_total"] == 0


def test_cli_invalid_window_days_returns_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(workspace),
        "--window-days", "0",
        "--print-only",
    )
    assert result.returncode == 2


def test_cli_negative_window_days_returns_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(workspace),
        "--window-days", "-5",
        "--print-only",
    )
    assert result.returncode == 2


def test_cli_invalid_today_returns_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(workspace),
        "--today", "not-a-date",
        "--print-only",
    )
    assert result.returncode == 2


def test_cli_today_short_year_rejected(tmp_path) -> None:
    """Strict YYYY-MM-DD per freshness_audit pattern — `26-04-25`
    rejected (length check)."""
    workspace = _make_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(workspace),
        "--today", "26-04-25",
        "--print-only",
    )
    assert result.returncode == 2


# ---- Atomic write hygiene -------------------------------------------


def test_no_tmp_files_after_write(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(workspace),
        "--today", "2026-04-25",
        "--quiet",
    )
    assert result.returncode == 0
    out_dir = workspace / "analysis/telemetry"
    leftovers = [
        p.name for p in out_dir.iterdir()
        if p.name.startswith(".miner_proposals_")
    ]
    assert leftovers == [], f"tempfile leftovers: {leftovers}"
