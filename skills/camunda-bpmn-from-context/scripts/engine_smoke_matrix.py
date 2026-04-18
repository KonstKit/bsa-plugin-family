#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ENGINE_SMOKE = SCRIPT_DIR / "engine_smoke_bpmn.py"
DEFAULT_FIXTURE_DIR = SCRIPT_DIR / "engine_smoke_fixtures"
DEFAULT_ACCEPTANCE_INVENTORY = SCRIPT_DIR / "fixtures" / "fixture_inventory.json"
DEFAULT_ACCEPTANCE_FIXTURES_ROOT = SCRIPT_DIR / "fixtures"
DEFAULT_FIXTURE_LINEAGE = SCRIPT_DIR / "fixtures" / "fixture_lineage.json"
DEFAULT_PIPELINE_SCRIPT = SCRIPT_DIR / "run_bpmn_pipeline.py"
DEFAULT_MANIFEST_VALIDATOR = SCRIPT_DIR / "validate_run_manifest.py"
DEFAULT_PREVIEW_BUILDER = SCRIPT_DIR / "build_preview_artifacts.py"
DEFAULT_GOVERNANCE_VALIDATOR = SCRIPT_DIR / "validate_governance_docs.py"
DEFAULT_GOVERNANCE_DOCS_ROOT = SCRIPT_DIR.parent / "references"

PROFILE_FIXTURES = {
    "7": {
        "happy": "c7_happy_path.bpmn",
        "negative": "c7_failing.bpmn",
    },
    "8": {
        "happy": "c8_happy_path.bpmn",
        "negative": "c8_failing.bpmn",
    },
}

STATUS_PASS = "PASS"
STATUS_NOT_VERIFIED = "NOT_VERIFIED"

ACCEPTANCE_PROFILE_PR = "pr"
ACCEPTANCE_PROFILE_NIGHTLY = "nightly"
ACCEPTANCE_PROFILE_RC = "release_candidate"
LAYOUT_FINAL_STATUS_RE = re.compile(
    r"\bfinal\s+status\s*:\s*(pass|fail)\b",
    re.IGNORECASE,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run BPMN matrix checks (legacy engine-smoke or acceptance mode).")

    # Legacy mode options (must remain backward-compatible)
    parser.add_argument(
        "--profiles",
        choices=["7", "8", "both"],
        default="both",
        help="[legacy] Which engine profile(s) to run.",
    )
    parser.add_argument(
        "--suite",
        choices=["happy", "negative", "all"],
        default="happy",
        help="[legacy] Fixture suite to run.",
    )
    parser.add_argument(
        "--report-dir",
        required=True,
        help="Directory for per-fixture reports and matrix summary.",
    )
    parser.add_argument(
        "--engine-smoke-script",
        default=str(DEFAULT_ENGINE_SMOKE),
        help="[legacy] Path to engine_smoke_bpmn.py entrypoint.",
    )
    parser.add_argument(
        "--fixture-dir",
        default=str(DEFAULT_FIXTURE_DIR),
        help="[legacy] Directory containing fixture BPMN files.",
    )
    parser.add_argument("--import-cmd", help="[legacy] Happy-path import/open command template.")
    parser.add_argument("--deploy-cmd", help="[legacy] Happy-path deploy command template.")
    parser.add_argument("--process-test-cmd", help="[legacy] Happy-path process smoke command template.")
    parser.add_argument("--shell", help="Optional shell for legacy commands and preview smoke command.")
    parser.add_argument(
        "--negative-import-cmd",
        help="[legacy] Override command template for negative fixtures (import step).",
    )
    parser.add_argument(
        "--negative-deploy-cmd",
        help="[legacy] Override command template for negative fixtures (deploy step).",
    )
    parser.add_argument(
        "--negative-process-test-cmd",
        help="[legacy] Override command template for negative fixtures (process smoke step).",
    )

    # Unified mode switch
    parser.add_argument(
        "--mode",
        choices=["legacy", "acceptance"],
        default="legacy",
        help="Matrix mode. Defaults to legacy engine-smoke compatibility mode.",
    )

    # Acceptance mode options
    parser.add_argument(
        "--gate-profile",
        choices=[ACCEPTANCE_PROFILE_PR, ACCEPTANCE_PROFILE_NIGHTLY, ACCEPTANCE_PROFILE_RC],
        help="[acceptance] Gate profile.",
    )
    parser.add_argument(
        "--inventory",
        default=str(DEFAULT_ACCEPTANCE_INVENTORY),
        help="[acceptance] Fixture inventory JSON path.",
    )
    parser.add_argument(
        "--fixtures-root",
        default=str(DEFAULT_ACCEPTANCE_FIXTURES_ROOT),
        help="[acceptance] Root directory used for inventory-relative fixture paths.",
    )
    parser.add_argument(
        "--lineage",
        default=str(DEFAULT_FIXTURE_LINEAGE),
        help="[acceptance] Lineage manifest JSON path.",
    )
    parser.add_argument(
        "--pipeline-script",
        default=str(DEFAULT_PIPELINE_SCRIPT),
        help="[acceptance] Path to run_bpmn_pipeline.py-compatible script.",
    )
    parser.add_argument(
        "--manifest-validator",
        default=str(DEFAULT_MANIFEST_VALIDATOR),
        help="[acceptance] Path to validate_run_manifest.py-compatible script.",
    )
    parser.add_argument(
        "--preview-builder-script",
        default=str(DEFAULT_PREVIEW_BUILDER),
        help="[acceptance] Path to build_preview_artifacts.py-compatible script.",
    )
    parser.add_argument(
        "--governance-validator-script",
        default=str(DEFAULT_GOVERNANCE_VALIDATOR),
        help="[acceptance] Path to validate_governance_docs.py-compatible script.",
    )
    parser.add_argument(
        "--governance-docs-root",
        default=str(DEFAULT_GOVERNANCE_DOCS_ROOT),
        help="[acceptance] Root directory containing governance docs.",
    )
    parser.add_argument(
        "--helper-command",
        help="[acceptance] Optional helper command forwarded to pipeline for simple mode.",
    )
    parser.add_argument(
        "--preview-smoke-cmd",
        help="[acceptance] Optional shell command for preview smoke. Required for PR profile.",
    )
    parser.add_argument(
        "--repeatability-runs",
        type=int,
        default=2,
        help="[acceptance] Number of repeat runs per fixture for selector repeatability checks (>=2).",
    )
    parser.add_argument(
        "--selector-repeatability",
        choices=["PASS", "FAIL"],
        default="PASS",
        help="[acceptance] Test hook to force selector repeatability gate result.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="[acceptance] Timeout seconds forwarded to pipeline.",
    )
    parser.add_argument(
        "--build-version",
        default="acceptance-matrix",
        help="[acceptance] build_version fact passed to pipeline.",
    )
    parser.add_argument(
        "--skill-version",
        default="camunda-bpmn-from-context",
        help="[acceptance] skill_version fact passed to pipeline.",
    )
    parser.add_argument(
        "--runtime-target",
        default="acceptance-matrix",
        help="[acceptance] runtime_target fact passed to pipeline.",
    )
    parser.add_argument(
        "--real-critical-corpus",
        action="store_true",
        help="[acceptance] Select real shipped critical corpus (original/stripped/negative) for runtime execution.",
    )

    return parser.parse_args(argv)


def should_run_acceptance_mode(args):
    return args.mode == "acceptance" or bool(args.gate_profile)


def selected_profiles(value):
    if value == "both":
        return ["7", "8"]
    return [value]


def selected_fixture_kinds(value):
    if value == "all":
        return ["happy", "negative"]
    return [value]


def resolve_commands(args, fixture_kind):
    import_cmd = args.import_cmd
    deploy_cmd = args.deploy_cmd
    process_cmd = args.process_test_cmd

    if fixture_kind == "negative":
        import_cmd = args.negative_import_cmd or import_cmd
        deploy_cmd = args.negative_deploy_cmd or deploy_cmd
        process_cmd = args.negative_process_test_cmd or process_cmd
        if deploy_cmd is None:
            deploy_cmd = "false"

    return import_cmd, deploy_cmd, process_cmd


def expected_status(fixture_kind):
    return STATUS_PASS if fixture_kind == "happy" else STATUS_NOT_VERIFIED


def run_case(engine_smoke_script, fixture_path, report_path, profile, fixture_kind, commands, shell):
    import_cmd, deploy_cmd, process_cmd = commands
    command = [
        sys.executable,
        str(engine_smoke_script),
        str(fixture_path),
        "--camunda-version",
        profile,
        "--deploy-profile",
        profile,
        "--report",
        str(report_path),
    ]
    if import_cmd:
        command.extend(["--import-cmd", import_cmd])
    if deploy_cmd:
        command.extend(["--deploy-cmd", deploy_cmd])
    if process_cmd:
        command.extend(["--process-test-cmd", process_cmd])
    if shell:
        command.extend(["--shell", shell])
    completed = subprocess.run(command, capture_output=True, text=True)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return completed, report


def ensure_fixture_exists(path):
    if not path.exists():
        raise FileNotFoundError(f"Fixture does not exist: {path}")


def run_legacy_mode(args):
    engine_smoke_script = Path(args.engine_smoke_script).resolve()
    fixture_dir = Path(args.fixture_dir).resolve()
    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    if not engine_smoke_script.exists():
        print(f"Engine smoke script not found: {engine_smoke_script}", file=sys.stderr)
        return 2

    matrix_results = []
    has_mismatch = False

    for profile in selected_profiles(args.profiles):
        for fixture_kind in selected_fixture_kinds(args.suite):
            fixture_name = PROFILE_FIXTURES[profile][fixture_kind]
            fixture_path = fixture_dir / fixture_name
            ensure_fixture_exists(fixture_path)

            commands = resolve_commands(args, fixture_kind)
            report_path = report_dir / f"{profile}_{fixture_kind}.json"
            completed, report = run_case(
                engine_smoke_script,
                fixture_path,
                report_path,
                profile,
                fixture_kind,
                commands,
                args.shell,
            )
            expected = expected_status(fixture_kind)
            status = report.get("status")
            ok = status == expected
            if not ok:
                has_mismatch = True
            matrix_results.append(
                {
                    "profile": profile,
                    "fixture_kind": fixture_kind,
                    "fixture": str(fixture_path),
                    "expected_status": expected,
                    "actual_status": status,
                    "returncode": completed.returncode,
                    "ok": ok,
                    "report": str(report_path),
                }
            )

    summary = {
        "mode": "legacy",
        "profiles": args.profiles,
        "suite": args.suite,
        "results": matrix_results,
        "all_ok": not has_mismatch,
    }
    summary_path = report_dir / "matrix_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    if has_mismatch:
        print(f"Engine smoke matrix mismatches found. See {summary_path}", file=sys.stderr)
        return 1

    print(f"Engine smoke matrix passed. Summary: {summary_path}")
    return 0


def _load_json(path):
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_artifact_path(manifest_path, manifest, artifact_key):
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    record = artifacts.get(artifact_key)
    if not isinstance(record, dict):
        return None
    if record.get("presence") != "present":
        return None
    artifact_rel_path = record.get("path")
    if not artifact_rel_path:
        return None
    candidate = Path(str(artifact_rel_path))
    if not candidate.is_absolute():
        candidate = Path(manifest_path).parent / candidate
    return candidate


def _read_layout_report_final_status(layout_report_path):
    if not layout_report_path:
        return None
    path = Path(layout_report_path)
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        normalized_line = raw_line.replace("*", "").replace("`", "")
        match = LAYOUT_FINAL_STATUS_RE.search(normalized_line)
        if match:
            return match.group(1).upper()
    return None


def _layout_summary_from_manifest(manifest):
    summary = manifest.get("layout_summary")
    if not isinstance(summary, dict):
        return {}
    return summary


def _profile_selected(fixture, profile):
    required_profiles = fixture.get("required_profiles") or []
    category = fixture.get("category")
    if category == "original":
        if profile in {ACCEPTANCE_PROFILE_PR, ACCEPTANCE_PROFILE_RC}:
            return True
        return profile in required_profiles
    if profile == ACCEPTANCE_PROFILE_NIGHTLY:
        return True
    return profile in required_profiles


def _selected_acceptance_fixtures(inventory, profile, real_critical_corpus=False):
    if real_critical_corpus:
        fixtures = [
            fixture
            for fixture in inventory.get("fixtures", [])
            if fixture.get("category") in {"original", "stripped", "negative"}
        ]
        return sorted(fixtures, key=lambda item: item.get("fixture_id", ""))
    fixtures = [
        fixture
        for fixture in inventory.get("fixtures", [])
        if _profile_selected(fixture, profile)
    ]
    return sorted(fixtures, key=lambda item: item.get("fixture_id", ""))


def _lineage_gate(inventory, fixtures_root, lineage_path):
    result = {
        "ok": True,
        "errors": [],
    }
    try:
        lineage = _load_json(lineage_path)
    except FileNotFoundError:
        result["ok"] = False
        result["errors"].append(f"lineage manifest not found: {lineage_path}")
        return result
    except json.JSONDecodeError as exc:
        result["ok"] = False
        result["errors"].append(
            f"lineage manifest is invalid JSON ({exc.msg} at line {exc.lineno}, column {exc.colno})"
        )
        return result
    except OSError as exc:
        result["ok"] = False
        result["errors"].append(f"unable to read lineage manifest: {exc}")
        return result
    entry_by_fixture = {entry.get("fixture_id"): entry for entry in lineage.get("entries", [])}

    originals = [
        item
        for item in inventory.get("fixtures", [])
        if item.get("category") == "original" and item.get("fixture_id") and item.get("path") and item.get("strip_to")
    ]
    for fixture in sorted(originals, key=lambda item: item.get("fixture_id", "")):
        fixture_id = fixture["fixture_id"]
        entry = entry_by_fixture.get(fixture_id)
        if entry is None:
            result["ok"] = False
            result["errors"].append(f"missing lineage entry for original fixture {fixture_id}")
            continue

        source_rel = Path(fixture["path"])
        stripped_rel = Path(fixture["strip_to"])
        source_path = fixtures_root / source_rel
        stripped_path = fixtures_root / stripped_rel
        if not source_path.exists():
            result["ok"] = False
            result["errors"].append(f"missing original fixture file: {source_rel}")
            continue
        if not stripped_path.exists():
            result["ok"] = False
            result["errors"].append(f"missing stripped fixture file: {stripped_rel}")
            continue

        entry_source = Path(entry.get("source_path", ""))
        entry_stripped = Path(entry.get("stripped_path", ""))
        if entry_source != source_rel:
            result["ok"] = False
            result["errors"].append(
                f"lineage source_path mismatch for {fixture_id}: inventory={source_rel} lineage={entry_source}"
            )
        if entry_stripped != stripped_rel:
            result["ok"] = False
            result["errors"].append(
                f"lineage stripped_path mismatch for {fixture_id}: inventory={stripped_rel} lineage={entry_stripped}"
            )

        source_sha = _sha256(source_path)
        stripped_sha = _sha256(stripped_path)
        if entry.get("source_sha256") != source_sha:
            result["ok"] = False
            result["errors"].append(
                f"lineage source hash mismatch for {fixture_id}: expected={entry.get('source_sha256')} actual={source_sha}"
            )
        if entry.get("stripped_sha256") != stripped_sha:
            result["ok"] = False
            result["errors"].append(
                f"lineage stripped hash mismatch for {fixture_id}: expected={entry.get('stripped_sha256')} actual={stripped_sha}"
            )
    return result


def _repeatability_fields(manifest):
    return {
        "requested_mode": manifest.get("requested_mode"),
        "eligibility_class": manifest.get("eligibility_class"),
        "initial_backend": manifest.get("initial_backend"),
        "final_backend": manifest.get("final_backend"),
        "fallback_happened": manifest.get("fallback_happened"),
        "fallback_reason_code": manifest.get("fallback_reason_code"),
        "semantic_status": manifest.get("semantic_status"),
        "layout_status": manifest.get("layout_status"),
        "preview_status": manifest.get("preview_status"),
    }


def _run_pipeline_fixture(args, fixture, fixture_path, report_dir):
    fixture_id = fixture["fixture_id"]
    scenario_id = fixture.get("scenario_id")
    requested_mode = fixture.get("requested_mode", "auto")
    fixture_preserve_existing_di = bool(fixture.get("preserve_existing_di", False))
    fixture_full_relayout = bool(fixture.get("full_relayout", False))
    fixture_logic_only = bool(fixture.get("logic_only", False))
    facts_base = dict(fixture.get("facts") or {})
    facts_base.setdefault("fixture_id", fixture_id)
    facts_base.setdefault("scenario_id", scenario_id)
    facts_base.setdefault("traceability_count", 0)
    facts_base.setdefault("assumptions_count", 0)
    facts_base.setdefault("build_version", args.build_version)
    facts_base.setdefault("skill_version", args.skill_version)
    facts_base.setdefault("runtime_target", args.runtime_target)

    repeats = []
    repeatability_ok = True
    repeatability_errors = []

    for run_index in range(1, max(2, args.repeatability_runs) + 1):
        run_dir = report_dir / "runs" / f"{fixture_id}__{run_index:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        facts_path = run_dir / "facts.json"
        _write_json(facts_path, facts_base)

        command = [
            sys.executable,
            str(Path(args.pipeline_script).resolve()),
            str(fixture_path),
            "--work-dir",
            str(run_dir),
            "--requested-mode",
            str(requested_mode),
            "--facts-json",
            str(facts_path),
            "--timeout-seconds",
            str(args.timeout_seconds),
        ]
        if args.helper_command:
            command.extend(["--helper-command", args.helper_command])
        if fixture_preserve_existing_di:
            command.append("--preserve-existing-di")
        if fixture_full_relayout:
            command.append("--full-relayout")
        if fixture_logic_only:
            command.append("--logic-only")

        completed = None
        timeout = max(1, int(args.timeout_seconds) + 5)
        manifest_path = run_dir / "run_manifest.json"
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            repeats.append(
                {
                    "run_index": run_index,
                    "returncode": 124,
                    "manifest_path": str(manifest_path),
                    "manifest_exists": manifest_path.exists(),
                    "manifest": None,
                    "stderr": str(exc),
                }
            )
            continue

        manifest = None
        if manifest_path.exists():
            try:
                manifest = _load_json(manifest_path)
            except json.JSONDecodeError:
                manifest = None

        repeat_entry = {
            "run_index": run_index,
            "returncode": completed.returncode,
            "manifest_path": str(manifest_path),
            "manifest_exists": manifest_path.exists(),
            "manifest": manifest,
            "stderr": (completed.stderr or "").strip(),
        }
        repeats.append(repeat_entry)

    baseline_manifest = repeats[0]["manifest"]
    if baseline_manifest is None:
        repeatability_ok = False
        repeatability_errors.append("baseline manifest missing or invalid JSON")
    else:
        baseline_signature = _repeatability_fields(baseline_manifest)
        for repeat_entry in repeats[1:]:
            if repeat_entry["manifest"] is None:
                repeatability_ok = False
                repeatability_errors.append(
                    f"repeat run {repeat_entry['run_index']} manifest missing or invalid"
                )
                continue
            if _repeatability_fields(repeat_entry["manifest"]) != baseline_signature:
                repeatability_ok = False
                repeatability_errors.append(
                    f"repeatability mismatch at run {repeat_entry['run_index']}"
                )

    result_errors = list(repeatability_errors)
    manifest_valid = False
    manifest_validation_output = ""
    manifest_id = None
    baseline_path = Path(repeats[0]["manifest_path"])
    if baseline_path.exists():
        manifest_id = _sha256(baseline_path)
        validator_cmd = [
            sys.executable,
            str(Path(args.manifest_validator).resolve()),
            str(baseline_path),
        ]
        validator_completed = subprocess.run(
            validator_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        manifest_valid = validator_completed.returncode == 0
        manifest_validation_output = (validator_completed.stderr or "")
        if not manifest_valid:
            result_errors.append("manifest schema validation failed")
    else:
        result_errors.append("manifest file not found")

    baseline = baseline_manifest or {}

    expected_eligibility = fixture.get("expected_eligibility_class")
    if expected_eligibility and baseline.get("eligibility_class") != expected_eligibility:
        result_errors.append(
            f"eligibility mismatch expected={expected_eligibility} actual={baseline.get('eligibility_class')}"
        )

    expected_final_backend = fixture.get("expected_final_backend")
    if expected_final_backend and baseline.get("final_backend") != expected_final_backend:
        result_errors.append(
            f"final_backend mismatch expected={expected_final_backend} actual={baseline.get('final_backend')}"
        )

    layout_status = baseline.get("layout_status")
    semantic_status = baseline.get("semantic_status")
    layout_summary = _layout_summary_from_manifest(baseline)
    layout_summary_status = layout_summary.get("final_status")
    layout_final_mode = layout_summary.get("final_mode")
    layout_profile_family = layout_summary.get("layout_profile_family")
    warning_issue_count = int(layout_summary.get("warning_issue_count", 0) or 0)
    error_issue_count = int(layout_summary.get("error_issue_count", 0) or 0)
    advisory_only = bool(layout_summary.get("advisory_only", False))
    diagram_width_px = int(layout_summary.get("diagram_width_px", 0) or 0)
    diagram_height_px = int(layout_summary.get("diagram_height_px", 0) or 0)
    aspect_ratio_x100 = int(layout_summary.get("aspect_ratio_x100", 0) or 0)
    max_depth_columns = int(layout_summary.get("max_depth_columns", 0) or 0)
    max_edge_span_columns = int(layout_summary.get("max_edge_span_columns", 0) or 0)
    consecutive_gateway_chain_length = int(layout_summary.get("consecutive_gateway_chain_length", 0) or 0)
    readability_violations = int(layout_summary.get("readability_violations", 0) or 0)
    layout_requires_decomposition = bool(layout_summary.get("layout_requires_decomposition", False))
    expected_layout_status = str(
        fixture.get("expected_layout_status") or ("SKIPPED" if fixture_logic_only else "PASS")
    ).upper()
    expected_semantic_status = str(fixture.get("expected_semantic_status") or "PASS").upper()
    layout_report_path = _resolve_artifact_path(baseline_path, baseline, "layout_report")
    layout_report_final_status = _read_layout_report_final_status(layout_report_path)
    expected_layout_report_status = None
    if expected_layout_status != "ANY" and layout_status != expected_layout_status:
        result_errors.append(
            f"layout_status mismatch expected={expected_layout_status} actual={layout_status}"
        )
    if expected_semantic_status != "ANY" and semantic_status != expected_semantic_status:
        result_errors.append(
            f"semantic_status mismatch expected={expected_semantic_status} actual={semantic_status}"
        )
    if expected_layout_status in {"PASS", "FAIL"}:
        expected_layout_report_status = expected_layout_status
    if layout_status in {"PASS", "FAIL"}:
        if layout_summary_status in {"PASS", "FAIL"} and layout_summary_status != layout_status:
            result_errors.append(
                "layout_summary final status mismatch "
                f"manifest={layout_status} summary={layout_summary_status}"
            )
    if expected_layout_report_status:
        observed_layout_verdict = layout_summary_status if layout_summary_status in {"PASS", "FAIL"} else layout_report_final_status
        if observed_layout_verdict is None:
            result_errors.append("layout_report final status missing or unreadable")
        elif observed_layout_verdict != expected_layout_report_status:
            result_errors.append(
                "layout_report final status mismatch "
                f"expected={expected_layout_report_status} actual={observed_layout_verdict}"
            )

    expected_layout_final_mode = fixture.get("expected_layout_final_mode")
    if expected_layout_final_mode and layout_final_mode != expected_layout_final_mode:
        result_errors.append(
            f"layout_final_mode mismatch expected={expected_layout_final_mode} actual={layout_final_mode}"
        )

    expected_layout_profile_family = fixture.get("expected_layout_profile_family")
    if expected_layout_profile_family and layout_profile_family != expected_layout_profile_family:
        result_errors.append(
            "layout_profile_family mismatch "
            f"expected={expected_layout_profile_family} actual={layout_profile_family}"
        )

    if "max_warning_issue_count" in fixture:
        max_warning_issue_count = int(fixture.get("max_warning_issue_count") or 0)
        if warning_issue_count > max_warning_issue_count:
            result_errors.append(
                "warning_issue_count exceeds fixture budget "
                f"max={max_warning_issue_count} actual={warning_issue_count}"
            )

    if "max_error_issue_count" in fixture:
        max_error_issue_count = int(fixture.get("max_error_issue_count") or 0)
        if error_issue_count > max_error_issue_count:
            result_errors.append(
                "error_issue_count exceeds fixture budget "
                f"max={max_error_issue_count} actual={error_issue_count}"
            )

    if "advisory_only_allowed" in fixture:
        advisory_only_allowed = bool(fixture.get("advisory_only_allowed"))
        if advisory_only and not advisory_only_allowed:
            result_errors.append("advisory_only=true is not allowed for this fixture")
    if "max_diagram_width_px" in fixture:
        max_diagram_width_px = int(fixture.get("max_diagram_width_px") or 0)
        if diagram_width_px > max_diagram_width_px:
            result_errors.append(
                "diagram_width_px exceeds fixture budget "
                f"max={max_diagram_width_px} actual={diagram_width_px}"
            )
    if "max_aspect_ratio_x100" in fixture:
        max_aspect_ratio_x100 = int(fixture.get("max_aspect_ratio_x100") or 0)
        if aspect_ratio_x100 > max_aspect_ratio_x100:
            result_errors.append(
                "aspect_ratio_x100 exceeds fixture budget "
                f"max={max_aspect_ratio_x100} actual={aspect_ratio_x100}"
            )
    if "max_depth_columns" in fixture:
        max_depth_columns_budget = int(fixture.get("max_depth_columns") or 0)
        if max_depth_columns > max_depth_columns_budget:
            result_errors.append(
                "max_depth_columns exceeds fixture budget "
                f"max={max_depth_columns_budget} actual={max_depth_columns}"
            )
    if "max_edge_span_columns" in fixture:
        max_edge_span_columns_budget = int(fixture.get("max_edge_span_columns") or 0)
        if max_edge_span_columns > max_edge_span_columns_budget:
            result_errors.append(
                "max_edge_span_columns exceeds fixture budget "
                f"max={max_edge_span_columns_budget} actual={max_edge_span_columns}"
            )
    if "allow_requires_decomposition" in fixture:
        allow_requires_decomposition = bool(fixture.get("allow_requires_decomposition"))
        if layout_requires_decomposition and not allow_requires_decomposition:
            result_errors.append("layout_requires_decomposition=true is not allowed for this fixture")

    expected_routing_class = fixture.get("expected_routing_class")
    actual_routing_class = None
    if baseline:
        if baseline.get("initial_backend") == "native" and baseline.get("final_backend") == "native":
            if baseline.get("fallback_happened"):
                actual_routing_class = "native_fallback"
            elif baseline.get("preserve_existing_di"):
                actual_routing_class = "native_preserve"
            else:
                actual_routing_class = "native_direct"
        elif baseline.get("initial_backend") == "simple" and baseline.get("final_backend") == "simple":
            actual_routing_class = "simple_direct"
        elif baseline.get("initial_backend") == "simple" and baseline.get("final_backend") == "native":
            actual_routing_class = "simple_fallback_to_native"
    if expected_routing_class and actual_routing_class != expected_routing_class:
        result_errors.append(
            "routing_class mismatch "
            f"expected={expected_routing_class} actual={actual_routing_class}"
        )

    if scenario_id is not None and baseline.get("scenario_id") != scenario_id:
        result_errors.append(
            f"scenario_id mismatch expected={scenario_id} actual={baseline.get('scenario_id')}"
        )
    if baseline.get("fixture_id") != fixture_id:
        result_errors.append(
            f"fixture_id mismatch expected={fixture_id} actual={baseline.get('fixture_id')}"
        )

    ok = not result_errors and manifest_valid and repeatability_ok

    return {
        "fixture_id": fixture_id,
        "scenario_id": scenario_id,
        "fixture_path": str(fixture_path),
        "category": fixture.get("category"),
        "requested_mode": requested_mode,
        "manifest_id": manifest_id,
        "manifest_path": str(baseline_path),
        "initial_backend": baseline.get("initial_backend"),
        "final_backend": baseline.get("final_backend"),
        "fallback_happened": baseline.get("fallback_happened"),
        "eligibility_class": baseline.get("eligibility_class"),
        "semantic_status": baseline.get("semantic_status"),
        "layout_status": baseline.get("layout_status"),
        "layout_summary_status": layout_summary_status,
        "layout_final_mode": layout_final_mode,
        "layout_profile_family": layout_profile_family,
        "warning_issue_count": warning_issue_count,
        "error_issue_count": error_issue_count,
        "advisory_only": advisory_only,
        "diagram_width_px": diagram_width_px,
        "diagram_height_px": diagram_height_px,
        "aspect_ratio_x100": aspect_ratio_x100,
        "max_depth_columns": max_depth_columns,
        "max_edge_span_columns": max_edge_span_columns,
        "consecutive_gateway_chain_length": consecutive_gateway_chain_length,
        "readability_violations": readability_violations,
        "layout_requires_decomposition": layout_requires_decomposition,
        "preview_status": baseline.get("preview_status"),
        "layout_report_path": str(layout_report_path) if layout_report_path else None,
        "layout_report_final_status": layout_report_final_status,
        "expected_layout_status": expected_layout_status,
        "expected_semantic_status": expected_semantic_status,
        "expected_eligibility_class": expected_eligibility,
        "expected_final_backend": expected_final_backend,
        "expected_routing_class": expected_routing_class,
        "actual_routing_class": actual_routing_class,
        "repeatability_ok": repeatability_ok,
        "manifest_valid": manifest_valid,
        "manifest_validation_output": manifest_validation_output.strip(),
        "status": "PASS" if ok else "FAIL",
        "ok": ok,
        "errors": result_errors,
        "repeat_runs": [
            {
                "run_index": item["run_index"],
                "returncode": item["returncode"],
                "manifest_path": item["manifest_path"],
                "manifest_exists": item["manifest_exists"],
                "stderr": item.get("stderr", ""),
            }
            for item in repeats
        ],
    }


def _resolve_shell(shell_override):
    candidates = []
    if shell_override:
        candidates.append(shell_override)
    env_shell = os.getenv("SHELL")
    if env_shell and env_shell not in candidates:
        candidates.append(env_shell)
    for fallback in ("sh", "bash", "zsh"):
        if fallback not in candidates:
            candidates.append(fallback)

    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _run_preview_smoke(args, report_dir, selected_results):
    required = args.gate_profile in {ACCEPTANCE_PROFILE_PR, ACCEPTANCE_PROFILE_RC}
    result = {
        "required": required,
        "executed": False,
        "ok": not required,
        "command": args.preview_smoke_cmd,
        "preview_dir": None,
        "errors": [],
    }

    if not args.preview_smoke_cmd:
        if required:
            result["ok"] = False
            result["errors"].append("preview smoke command is required for pr/release_candidate gate profiles")
        return result

    candidate = next(
        (
            item
            for item in selected_results
            if item.get("manifest_path")
            and item.get("manifest_valid")
            and item.get("layout_status") == "PASS"
            and (
                item.get("layout_summary_status") == "PASS"
                or item.get("layout_report_final_status") == "PASS"
            )
            and item.get("final_backend") in {"native", "simple"}
        ),
        None,
    )
    if candidate is None:
        result["ok"] = False
        result["errors"].append("no preview-ready manifest available for preview smoke")
        return result

    preview_dir = report_dir / "preview_smoke"
    preview_builder_cmd = [
        sys.executable,
        str(Path(args.preview_builder_script).resolve()),
        candidate["manifest_path"],
        "--output-dir",
        str(preview_dir),
    ]
    preview_builder = subprocess.run(preview_builder_cmd, capture_output=True, text=True)
    if preview_builder.returncode != 0:
        result["ok"] = False
        result["errors"].append("preview build failed before smoke")
        result["preview_builder_stdout"] = preview_builder.stdout.strip()
        result["preview_builder_stderr"] = preview_builder.stderr.strip()
        return result

    shell_path = _resolve_shell(args.shell)
    if shell_path is None:
        result["ok"] = False
        result["errors"].append("no executable shell available for preview smoke command")
        return result

    env = os.environ.copy()
    env["PREVIEW_DIR"] = str(preview_dir)
    smoke = subprocess.run([shell_path, "-lc", args.preview_smoke_cmd], capture_output=True, text=True, env=env)
    result["executed"] = True
    result["preview_dir"] = str(preview_dir)
    result["returncode"] = smoke.returncode
    result["stdout"] = smoke.stdout.strip()
    result["stderr"] = smoke.stderr.strip()
    result["ok"] = smoke.returncode == 0
    if smoke.returncode != 0:
        result["errors"].append("preview smoke command failed")
    return result


def _run_governance_check(args, report_dir):
    required = args.gate_profile == ACCEPTANCE_PROFILE_RC
    validator_path = Path(args.governance_validator_script).resolve()
    docs_root = Path(args.governance_docs_root).resolve()
    result = {
        "required": required,
        "executed": False,
        "ok": not required,
        "command": str(validator_path),
        "docs_root": str(docs_root),
        "gate_profile": args.gate_profile or ACCEPTANCE_PROFILE_PR,
        "errors": [],
        "stdout": "",
        "stderr": "",
        "details": None,
    }

    if not validator_path.exists():
        result["ok"] = False
        result["errors"].append(f"governance validator not found: {validator_path}")
        return result
    if not docs_root.exists():
        result["ok"] = False
        result["errors"].append(f"governance docs root not found: {docs_root}")
        return result

    command = [
        sys.executable,
        str(validator_path),
        "--docs-root",
        str(docs_root),
        "--gate-profile",
        result["gate_profile"],
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    result["executed"] = True
    result["returncode"] = completed.returncode
    result["stdout"] = completed.stdout.strip()
    result["stderr"] = completed.stderr.strip()
    result["ok"] = completed.returncode == 0
    if completed.returncode != 0:
        result["errors"].append("governance validation failed")
    if completed.stdout.strip():
        try:
            result["details"] = json.loads(completed.stdout)
        except json.JSONDecodeError:
            result["details"] = {"raw_stdout": completed.stdout.strip()}
    report_path = report_dir / "governance_validation.json"
    _write_json(report_path, result)
    return result


def run_acceptance_mode(args):
    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    inventory_path = Path(args.inventory).resolve()
    fixtures_root = Path(args.fixtures_root).resolve()
    lineage_path = Path(args.lineage).resolve()

    try:
        inventory = _load_json(inventory_path)
    except FileNotFoundError:
        inventory_error = f"fixture inventory not found: {inventory_path}"
    except json.JSONDecodeError as exc:
        inventory_error = (
            f"fixture inventory is invalid JSON ({exc.msg} at line {exc.lineno}, column {exc.colno})"
        )
    except OSError as exc:
        inventory_error = f"unable to read fixture inventory: {exc}"
    else:
        inventory_error = None

    if inventory_error is not None:
        gate_profile = args.gate_profile or ACCEPTANCE_PROFILE_PR
        preview_required = gate_profile in {ACCEPTANCE_PROFILE_PR, ACCEPTANCE_PROFILE_RC}
        governance_required = gate_profile == ACCEPTANCE_PROFILE_RC
        summary = {
            "mode": "acceptance",
            "gate_profile": gate_profile,
            "inventory": str(inventory_path),
            "fixtures_root": str(fixtures_root),
            "lineage": {
                "path": str(lineage_path),
                "ok": False,
                "errors": [],
            },
            "selected_fixture_ids": [],
            "results": [],
            "gate_checks": {
                "required_fixtures_pass": False,
                "selector_repeatability_pass": False,
                "negative_exclusions_pass": False,
                "manifest_schema_pass": False,
                "preview_smoke_pass": False,
                "governance_pass": False,
            },
            "gate_requirements": {
                "preview_smoke_required": preview_required,
                "governance_required": governance_required,
            },
            "preview_smoke": {
                "required": preview_required,
                "executed": False,
                "ok": False,
                "command": args.preview_smoke_cmd,
                "errors": [],
            },
            "governance": {
                "required": governance_required,
                "executed": False,
                "ok": False,
                "command": str(Path(args.governance_validator_script).resolve()),
                "docs_root": str(Path(args.governance_docs_root).resolve()),
                "errors": [],
            },
            "release_gate_pass": False,
            "all_ok": False,
            "errors": [inventory_error],
        }
        summary_path = report_dir / "matrix_summary.json"
        _write_json(summary_path, summary)
        print(f"Acceptance matrix blocked by inventory error. Summary: {summary_path}", file=sys.stderr)
        return 1

    lineage_gate = _lineage_gate(inventory, fixtures_root, lineage_path)

    selected = _selected_acceptance_fixtures(
        inventory,
        args.gate_profile or ACCEPTANCE_PROFILE_PR,
        real_critical_corpus=bool(args.real_critical_corpus),
    )
    summary = {
        "mode": "acceptance",
        "gate_profile": args.gate_profile or ACCEPTANCE_PROFILE_PR,
        "inventory": str(inventory_path),
        "fixtures_root": str(fixtures_root),
        "lineage": {
            "path": str(lineage_path),
            "ok": lineage_gate["ok"],
            "errors": sorted(lineage_gate["errors"]),
        },
        "selected_fixture_ids": [fixture["fixture_id"] for fixture in selected],
        "results": [],
        "gate_checks": {
            "required_fixtures_pass": False,
            "selector_repeatability_pass": False,
            "negative_exclusions_pass": False,
            "manifest_schema_pass": False,
            "preview_smoke_pass": False,
            "governance_pass": False,
        },
        "gate_requirements": {
            "preview_smoke_required": (args.gate_profile or ACCEPTANCE_PROFILE_PR) in {ACCEPTANCE_PROFILE_PR, ACCEPTANCE_PROFILE_RC},
            "governance_required": (args.gate_profile or ACCEPTANCE_PROFILE_PR) == ACCEPTANCE_PROFILE_RC,
        },
        "preview_smoke": {
            "required": (args.gate_profile or ACCEPTANCE_PROFILE_PR) in {ACCEPTANCE_PROFILE_PR, ACCEPTANCE_PROFILE_RC},
            "executed": False,
            "ok": False,
            "command": args.preview_smoke_cmd,
            "errors": [],
        },
        "governance": {
            "required": (args.gate_profile or ACCEPTANCE_PROFILE_PR) == ACCEPTANCE_PROFILE_RC,
            "executed": False,
            "ok": False,
            "command": str(Path(args.governance_validator_script).resolve()),
            "docs_root": str(Path(args.governance_docs_root).resolve()),
            "errors": [],
        },
        "all_ok": False,
        "errors": [],
    }

    if not lineage_gate["ok"]:
        summary_path = report_dir / "matrix_summary.json"
        _write_json(summary_path, summary)
        print(f"Acceptance matrix blocked by lineage mismatch. Summary: {summary_path}", file=sys.stderr)
        return 1

    results = []
    for fixture in selected:
        fixture_path = fixtures_root / fixture["path"]
        if not fixture_path.exists():
            results.append(
                {
                    "fixture_id": fixture.get("fixture_id"),
                    "scenario_id": fixture.get("scenario_id"),
                    "fixture_path": str(fixture_path),
                    "status": "FAIL",
                    "ok": False,
                    "manifest_id": None,
                    "initial_backend": None,
                    "final_backend": None,
                    "fallback_happened": None,
                    "errors": [f"fixture file not found: {fixture_path}"],
                    "repeatability_ok": False,
                    "manifest_valid": False,
                }
            )
            continue
        result = _run_pipeline_fixture(args, fixture, fixture_path, report_dir)
        results.append(result)

    results = sorted(results, key=lambda item: item.get("fixture_id", ""))
    if not results:
        summary["errors"].append(
            f"no acceptance fixtures selected for profile '{args.gate_profile or ACCEPTANCE_PROFILE_PR}'"
        )

    has_results = bool(results)
    required_fixtures_pass = has_results and all(item.get("ok") for item in results)
    selector_repeatability_pass = has_results and all(item.get("repeatability_ok") for item in results)
    if args.selector_repeatability == "FAIL":
        selector_repeatability_pass = False
        summary["errors"].append("selector repeatability forced to FAIL by test hook")
    manifest_schema_pass = has_results and all(item.get("manifest_valid") for item in results)

    negative_results = [item for item in results if item.get("category") == "negative"]
    negative_exclusions_pass = bool(negative_results) and all(
        item.get("eligibility_class") == "simple_ineligible" and item.get("final_backend") == "native"
        for item in negative_results
    )

    preview_smoke = _run_preview_smoke(args, report_dir, results)
    governance = _run_governance_check(args, report_dir)

    gate_checks = {
        "required_fixtures_pass": required_fixtures_pass,
        "selector_repeatability_pass": selector_repeatability_pass,
        "negative_exclusions_pass": negative_exclusions_pass,
        "manifest_schema_pass": manifest_schema_pass,
        "preview_smoke_pass": preview_smoke.get("ok", False),
        "governance_pass": governance.get("ok", False),
    }

    required_checks = [
        gate_checks["required_fixtures_pass"],
        gate_checks["selector_repeatability_pass"],
        gate_checks["negative_exclusions_pass"],
        gate_checks["manifest_schema_pass"],
    ]
    if preview_smoke.get("required"):
        required_checks.append(gate_checks["preview_smoke_pass"])
    if governance.get("required"):
        required_checks.append(gate_checks["governance_pass"])
    all_ok = all(required_checks)

    summary["results"] = results
    summary["gate_checks"] = gate_checks
    summary["preview_smoke"] = preview_smoke
    summary["governance"] = governance
    summary["release_gate_pass"] = all_ok
    summary["all_ok"] = all_ok

    summary_path = report_dir / "matrix_summary.json"
    _write_json(summary_path, summary)

    if not all_ok:
        print(f"Acceptance matrix checks failed. Summary: {summary_path}", file=sys.stderr)
        return 1

    print(f"Acceptance matrix passed. Summary: {summary_path}")
    return 0


def main(argv=None):
    args = parse_args(argv)
    if should_run_acceptance_mode(args):
        if args.repeatability_runs < 2:
            print("repeatability-runs must be >= 2", file=sys.stderr)
            return 2
        if not args.gate_profile:
            args.gate_profile = ACCEPTANCE_PROFILE_PR
        return run_acceptance_mode(args)
    return run_legacy_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
