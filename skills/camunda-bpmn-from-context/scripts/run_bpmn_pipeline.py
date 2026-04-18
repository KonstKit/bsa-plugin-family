#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
SCHEMA_DIR = PACKAGE_ROOT / "schemas"

MANIFEST_SCHEMA_VERSION = "2"
LINKED_REPORT_SCHEMA_VERSION = "2"
DEFAULT_BUILD_VERSION = "unknown"
DEFAULT_SKILL_VERSION = "camunda-bpmn-from-context"
DEFAULT_RUNTIME_TARGET = "camunda-bpmn-pipeline"
LAYOUT_REPORT_SUMMARY_FILENAME = "layout_report.summary.json"

ARTIFACT_BACKEND_SELECTION = "backend_selection"
ARTIFACT_SEMANTIC_REPORT = "semantic_report"
ARTIFACT_LAYOUT_REPORT = "layout_report"
ARTIFACT_PREVIEW_REPORT = "preview_report"
ARTIFACT_HUMAN_SUMMARY = "human_summary"
ARTIFACT_TYPED_ISSUE_TARGETS = "typed_issue_targets"

CANONICAL_ARTIFACT_FILENAMES = {
    ARTIFACT_BACKEND_SELECTION: "backend_selection.json",
    ARTIFACT_SEMANTIC_REPORT: "semantic_report.json",
    ARTIFACT_LAYOUT_REPORT: "layout_report.md",
    ARTIFACT_PREVIEW_REPORT: "preview_report.json",
    ARTIFACT_HUMAN_SUMMARY: "human_summary.md",
    ARTIFACT_TYPED_ISSUE_TARGETS: "typed_issue_targets.json",
}

STATE_SELECT = "SELECT"
STATE_PROJECT = "PROJECT"
STATE_SIMPLE_LAYOUT = "SIMPLE_LAYOUT"
STATE_POST_PROCESS = "POST_PROCESS"
STATE_VALIDATE = "VALIDATE"
STATE_PREVIEW = "PREVIEW"
STATE_FALLBACK_NATIVE = "FALLBACK_NATIVE"
STATE_FINALIZE = "FINALIZE"
STATE_FAIL = "FAIL"

FALLBACK_SIMPLE_HELPER_FAILED = "simple_helper_failed"
FALLBACK_SIMPLE_POSTPROCESS_FAILED = "simple_postprocess_failed"
FALLBACK_SIMPLE_HARD_CHECK_FAILED = "simple_hard_check_failed"
FALLBACK_NATIVE_FAILED = "native_fallback_failed"
FALLBACK_NATIVE_PRESERVE_DEGRADED = "native_preserve_degraded_to_greenfield"
FAILURE_PREVIEW_BUILD_FAILED = "preview_build_failed"

DETAIL_SIMPLE_POSTPROCESS_LAYOUT_FAILED = "postprocess_layout_failed"
DETAIL_SIMPLE_EDGE_DI_INCOMPLETE = "postprocess_edge_di_incomplete"
DETAIL_SIMPLE_LAYOUT_POLICY_FAILED = "postprocess_layout_policy_failed"
DETAIL_SIMPLE_LAYOUT_SUMMARY_INVALID = "postprocess_layout_summary_invalid"
DETAIL_SIMPLE_VALIDATION_FAILED = "simple_validation_failed"
LAYOUT_HINT_SOURCE_NONE = "none"
LAYOUT_FINAL_STATUS_RE = re.compile(
    r"\bfinal\s+status\s*:\s*(pass|fail)\b",
    re.IGNORECASE,
)
LAYOUT_SUMMARY_REQUIRED_FIELDS = {
    "final_status",
    "final_mode",
    "layout_profile_family",
    "typed_issue_count",
    "warning_issue_count",
    "error_issue_count",
    "shape_budget_violations",
    "label_budget_violations",
    "participant_lane_budget_violations",
    "advisory_only",
}
LAYOUT_SUMMARY_ALLOWED_FAMILIES = {"native", "simple_postprocess"}


def _load_local_module(module_name, file_name):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_DIR / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BACKEND_SELECTOR = _load_local_module("backend_selector_local", "backend_selector.py")
SIMPLE_BRIDGE = _load_local_module("simple_mode_bridge_local", "simple_mode_bridge.py")
VALIDATOR = _load_local_module("validate_run_manifest_local", "validate_run_manifest.py")
SEMANTIC_VALIDATE = _load_local_module("semantic_validate_bpmn_local", "semantic_validate_bpmn.py")
PREVIEW_BUILDER = _load_local_module("build_preview_artifacts_local", "build_preview_artifacts.py")

classify_eligibility = BACKEND_SELECTOR.classify_eligibility
run_simple_mode_bridge = SIMPLE_BRIDGE.run_simple_mode_bridge
validate_bpmn = SEMANTIC_VALIDATE.validate_bpmn
load_schema = VALIDATOR.load_schema
validate_manifest_data = VALIDATOR.validate_manifest_data
build_preview_artifacts = PREVIEW_BUILDER.build_preview_artifacts

BPMN_MODEL_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMN_DI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
SELECTOR_FACT_CONSTRUCT_BY_TAG = {
    "messageFlow": "messageFlow",
    "textAnnotation": "textAnnotation",
    "association": "association",
    "complexGateway": "complexGateway",
    "group": "group",
    "boundaryEvent": "boundaryEvent",
}


def _write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(text)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _load_json(path):
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tag_namespace(tag):
    if isinstance(tag, str) and tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return ""


def _tag_local_name(tag):
    if isinstance(tag, str) and tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return str(tag)


def _classify_di_quality(sequence_flow_count, bpmn_shape_count, bpmn_edge_count, edge_without_two_waypoints_count=0):
    if bpmn_shape_count <= 0 and bpmn_edge_count <= 0:
        return "no_di"
    if bpmn_shape_count <= 0:
        return "partial_di"
    if sequence_flow_count > 0 and (
        bpmn_edge_count < sequence_flow_count or edge_without_two_waypoints_count > 0
    ):
        return "partial_di"
    return "usable_di"


def _extract_selector_facts_from_bpmn(input_bpmn):
    root = ET.parse(str(input_bpmn)).getroot()

    constructs = set()
    participant_count = 0
    subprocess_ids = set()
    sequence_flow_count = 0
    bpmn_shape_count = 0
    bpmn_edge_count = 0
    edge_without_two_waypoints_count = 0
    has_bpmn_di = False

    for element in root.iter():
        namespace = _tag_namespace(element.tag)
        if namespace != BPMN_MODEL_NS:
            if namespace == BPMN_DI_NS:
                has_bpmn_di = True
                tag_name = _tag_local_name(element.tag)
                if tag_name == "BPMNShape":
                    bpmn_shape_count += 1
                elif tag_name == "BPMNEdge":
                    bpmn_edge_count += 1
                    waypoint_count = sum(1 for child in list(element) if _tag_local_name(child.tag) == "waypoint")
                    if waypoint_count < 2:
                        edge_without_two_waypoints_count += 1
            continue
        tag_name = _tag_local_name(element.tag)
        if tag_name == "sequenceFlow":
            sequence_flow_count += 1
            continue
        if tag_name == "participant":
            participant_count += 1
            continue
        mapped_construct = SELECTOR_FACT_CONSTRUCT_BY_TAG.get(tag_name)
        if mapped_construct:
            constructs.add(mapped_construct)
            continue
        if tag_name == "subProcess":
            element_id = element.get("id")
            if element_id:
                subprocess_ids.add(element_id)
            if str(element.get("triggeredByEvent", "")).strip().lower() == "true":
                constructs.add("eventSubProcess")

    for element in root.iter():
        if _tag_namespace(element.tag) != BPMN_DI_NS or _tag_local_name(element.tag) != "BPMNShape":
            continue
        if str(element.get("isExpanded", "")).strip().lower() != "true":
            continue
        bpmn_element_id = element.get("bpmnElement")
        if bpmn_element_id and bpmn_element_id in subprocess_ids:
            constructs.add("expandedSubProcess")
            break

    di_quality = _classify_di_quality(
        sequence_flow_count=sequence_flow_count,
        bpmn_shape_count=bpmn_shape_count,
        bpmn_edge_count=bpmn_edge_count,
        edge_without_two_waypoints_count=edge_without_two_waypoints_count,
    )
    return {
        "participant_count": participant_count,
        "sequence_flow_count": sequence_flow_count,
        "constructs": sorted(constructs),
        "has_bpmn_di": bool(has_bpmn_di),
        "bpmn_shape_count": int(bpmn_shape_count),
        "bpmn_edge_count": int(bpmn_edge_count),
        "edge_without_two_waypoints_count": int(edge_without_two_waypoints_count),
        "di_quality": di_quality,
        "has_existing_di": di_quality != "no_di",
        "has_partial_di": di_quality == "partial_di",
        "has_usable_di": di_quality == "usable_di",
    }


def _merge_selector_facts(input_bpmn, caller_facts):
    caller_facts = dict(caller_facts or {})
    extracted_facts = {}
    extraction_error = None
    try:
        extracted_facts = _extract_selector_facts_from_bpmn(input_bpmn)
    except (OSError, ET.ParseError, ValueError) as exc:
        extraction_error = str(exc)
    merged = dict(extracted_facts)
    merged.update(caller_facts)
    return {
        "merged": merged,
        "extracted": extracted_facts,
        "supplied": caller_facts,
        "extraction_error": extraction_error,
    }


def _artifact_record(path, schema_version=None):
    return _linked_artifact_record(
        report_kind=Path(path).stem,
        presence="present",
        status="PASS",
        path=path,
        schema_version=schema_version,
    )


def _linked_artifact_record(report_kind, presence, status, path=None, schema_version=LINKED_REPORT_SCHEMA_VERSION):
    record = {
        "report_kind": report_kind,
        "presence": presence,
        "status": status,
        "schema_version": schema_version,
    }
    if presence == "present":
        record["path"] = Path(path).name
        record["hash"] = _sha256(path)
    return record


def _optional_artifact_record(report_kind, status, path=None, absent_presence="skipped"):
    if path and Path(path).exists():
        return _linked_artifact_record(
            report_kind=report_kind,
            presence="present",
            status=status,
            path=path,
        )
    return _linked_artifact_record(
        report_kind=report_kind,
        presence=absent_presence,
        status="SKIPPED",
    )


def _classify_layout_hint_source(enable_layout_hints=False, layout_hints_json=None):
    if not layout_hints_json:
        return LAYOUT_HINT_SOURCE_NONE
    if not enable_layout_hints:
        return "disabled"
    candidate = Path(str(layout_hints_json)).expanduser()
    if candidate.exists():
        return "file_json"
    return "inline_json"


def _read_layout_hint_status(report_path):
    status = {
        "layout_hint_source": LAYOUT_HINT_SOURCE_NONE,
        "hint_applied": False,
    }
    if not report_path:
        return status

    path = Path(report_path)
    if not path.exists():
        return status

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("- layout_hint_source:"):
            value = line.split(":", 1)[1].strip().strip("`")
            if value:
                status["layout_hint_source"] = value
        elif line.startswith("- hint_applied:"):
            value = line.split(":", 1)[1].strip().strip("`").lower()
            if value in ("true", "false"):
                status["hint_applied"] = value == "true"
    return status


def _read_layout_final_status(report_path):
    if not report_path:
        return None

    path = Path(report_path)
    if not path.exists():
        return None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        normalized_line = raw_line.replace("*", "").replace("`", "")
        match = LAYOUT_FINAL_STATUS_RE.search(normalized_line)
        if match:
            return match.group(1).upper()
    return None


def _read_layout_final_mode(report_path):
    if not report_path:
        return None

    path = Path(report_path)
    if not path.exists():
        return None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("- final_mode:"):
            continue
        value = line.split(":", 1)[1].strip().strip("`")
        if value:
            return value
    return None


def _empty_layout_summary(layout_status="SKIPPED"):
    final_status = "PASS" if layout_status == "PASS" else ("FAIL" if layout_status == "FAIL" else "SKIPPED")
    return {
        "final_status": final_status,
        "final_mode": "none" if layout_status == "SKIPPED" else "unknown",
        "layout_profile_family": "none" if layout_status == "SKIPPED" else "unknown",
        "typed_issue_count": 0,
        "warning_issue_count": 0,
        "error_issue_count": 0,
        "shape_budget_violations": 0,
        "label_budget_violations": 0,
        "participant_lane_budget_violations": 0,
        "diagram_width_px": 0,
        "diagram_height_px": 0,
        "aspect_ratio_x100": 0,
        "max_depth_columns": 0,
        "max_edge_span_columns": 0,
        "consecutive_gateway_chain_length": 0,
        "readability_violations": 0,
        "layout_requires_decomposition": False,
        "advisory_only": False,
        "layout_policy_status": final_status,
    }


def _read_layout_summary(report_json_path, report_path=None, expected_profile_family=None):
    fallback_mode = _read_layout_final_mode(report_path) or "unknown"

    def fail_summary(reason):
        return (
            {
                **_empty_layout_summary("FAIL"),
                "final_mode": fallback_mode,
                "layout_profile_family": str(expected_profile_family or "unknown"),
                "layout_policy_status": "FAIL",
            },
            str(reason),
        )

    path = Path(report_json_path) if report_json_path else None
    if not path or not path.exists():
        return fail_summary("layout_summary_missing")

    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return fail_summary(f"layout_summary_unreadable:{exc}")

    if not isinstance(payload, dict):
        return fail_summary("layout_summary_not_object")
    missing_fields = sorted(LAYOUT_SUMMARY_REQUIRED_FIELDS.difference(payload.keys()))
    if missing_fields:
        return fail_summary("layout_summary_missing_fields:" + ",".join(missing_fields))

    try:
        summary = {
            "final_status": str(payload.get("final_status") or "").upper(),
            "final_mode": str(payload.get("final_mode") or ""),
            "layout_profile_family": str(payload.get("layout_profile_family") or ""),
            "typed_issue_count": int(payload.get("typed_issue_count", 0)),
            "warning_issue_count": int(payload.get("warning_issue_count", 0)),
            "error_issue_count": int(payload.get("error_issue_count", 0)),
            "shape_budget_violations": int(payload.get("shape_budget_violations", 0)),
            "label_budget_violations": int(payload.get("label_budget_violations", 0)),
            "participant_lane_budget_violations": int(payload.get("participant_lane_budget_violations", 0)),
            "diagram_width_px": int(payload.get("diagram_width_px", 0)),
            "diagram_height_px": int(payload.get("diagram_height_px", 0)),
            "aspect_ratio_x100": int(payload.get("aspect_ratio_x100", 0)),
            "max_depth_columns": int(payload.get("max_depth_columns", 0)),
            "max_edge_span_columns": int(payload.get("max_edge_span_columns", 0)),
            "consecutive_gateway_chain_length": int(payload.get("consecutive_gateway_chain_length", 0)),
            "readability_violations": int(payload.get("readability_violations", 0)),
            "layout_requires_decomposition": bool(payload.get("layout_requires_decomposition", False)),
            "advisory_only": bool(payload.get("advisory_only", False)),
        }
    except (TypeError, ValueError) as exc:
        return fail_summary(f"layout_summary_value_error:{exc}")

    if summary["final_status"] not in {"PASS", "FAIL"}:
        return fail_summary(f"layout_summary_invalid_final_status:{summary['final_status']}")
    if summary["layout_profile_family"] not in LAYOUT_SUMMARY_ALLOWED_FAMILIES:
        return fail_summary(f"layout_summary_invalid_profile_family:{summary['layout_profile_family']}")
    if summary["warning_issue_count"] + summary["error_issue_count"] > summary["typed_issue_count"]:
        return fail_summary("layout_summary_severity_counts_exceed_total")
    if summary["advisory_only"] and (
        summary["error_issue_count"] != 0 or summary["typed_issue_count"] <= 0
    ):
        return fail_summary("layout_summary_invalid_advisory_only")
    for key in (
        "diagram_width_px",
        "diagram_height_px",
        "aspect_ratio_x100",
        "max_depth_columns",
        "max_edge_span_columns",
        "consecutive_gateway_chain_length",
        "readability_violations",
    ):
        if summary[key] < 0:
            return fail_summary(f"layout_summary_negative_{key}")
    if summary["layout_requires_decomposition"] and summary["readability_violations"] <= 0:
        return fail_summary("layout_summary_inconsistent_decomposition_flag")
    summary["layout_policy_status"] = summary["final_status"]
    return summary, None


def _ensure_layout_report(
    path,
    backend,
    returncode,
    stdout,
    stderr,
    enable_layout_hints=False,
    layout_hints_json=None,
):
    path = Path(path)
    if path.exists():
        return str(path)
    layout_hint_source = _classify_layout_hint_source(
        enable_layout_hints=enable_layout_hints,
        layout_hints_json=layout_hints_json,
    )
    _write_text(
        path,
        "\n".join(
            [
                "# Layout Report",
                "",
                f"- backend: `{backend}`",
                f"- layout_returncode: `{returncode}`",
                f"- layout_stdout: `{stdout or ''}`",
                f"- layout_stderr: `{stderr or ''}`",
                f"- layout_hint_source: {layout_hint_source}",
                "- hint_applied: false",
                "",
            ]
        ),
    )
    return str(path)


def _run_layout(
    input_bpmn,
    output_bpmn,
    report_path,
    report_json_path,
    enable_layout_hints=False,
    layout_hints_json=None,
    simple_postprocess=False,
    preserve_existing_di_strict=False,
):
    command = [
        sys.executable,
        str(SCRIPT_DIR / "apply_bpmn_layout_policy.py"),
        str(input_bpmn),
        "--output",
        str(output_bpmn),
        "--report",
        str(report_path),
        "--report-json",
        str(report_json_path),
    ]
    if enable_layout_hints:
        command.append("--enable-layout-hints")
    if layout_hints_json:
        command.extend(["--layout-hints-json", str(layout_hints_json)])
    if simple_postprocess:
        command.append("--simple-postprocess")
    if preserve_existing_di_strict:
        command.append("--preserve-existing-di-strict")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return completed


def _run_semantic_validation(bpmn_path):
    errors, warnings = validate_bpmn(str(bpmn_path))
    return {
        "errors": list(errors),
        "warnings": list(warnings),
        "status": "PASS" if not errors else "FAIL",
    }


def _result_output_hash(path):
    if not path:
        return None
    candidate = Path(path)
    if not candidate.exists():
        return None
    return _sha256(candidate)


def _resolve_initial_backend(selection, simple_backend_available=True):
    if selection["forced_skip_layout"]:
        return "none"
    if selection["forced_native"]:
        return "native"
    if selection["requested_mode"] in ("auto", "simple"):
        if not simple_backend_available:
            return "native"
        return "simple"
    return "native"


def _execute_native(
    input_bpmn,
    work_dir,
    semantic_report_path,
    enable_layout_hints=False,
    layout_hints_json=None,
    preserve_existing_di_strict=False,
):
    output_bpmn = Path(work_dir) / "native_layout_output.bpmn"
    layout_report_path = Path(work_dir) / "layout_report.md"
    layout_report_json_path = Path(work_dir) / LAYOUT_REPORT_SUMMARY_FILENAME
    layout_completed = _run_layout(
        input_bpmn,
        output_bpmn,
        layout_report_path,
        layout_report_json_path,
        enable_layout_hints=enable_layout_hints,
        layout_hints_json=layout_hints_json,
        preserve_existing_di_strict=preserve_existing_di_strict,
    )

    semantic_payload = {
        "backend": "native",
        "layout_returncode": layout_completed.returncode,
        "layout_stdout": layout_completed.stdout,
        "layout_stderr": layout_completed.stderr,
        "warnings": [],
        "errors": [],
        "status": "FAIL",
    }

    layout_report = str(layout_report_path) if layout_report_path.exists() else None

    if layout_completed.returncode == 0:
        semantic_payload = _run_semantic_validation(output_bpmn)
        semantic_payload["backend"] = "native"
        semantic_payload["layout_returncode"] = layout_completed.returncode
        semantic_payload["layout_stdout"] = layout_completed.stdout
        semantic_payload["layout_stderr"] = layout_completed.stderr
    else:
        layout_report = _ensure_layout_report(
            layout_report_path,
            backend="native",
            returncode=layout_completed.returncode,
            stdout=layout_completed.stdout,
            stderr=layout_completed.stderr,
            enable_layout_hints=enable_layout_hints,
            layout_hints_json=layout_hints_json,
        )

    hint_status = _read_layout_hint_status(layout_report)
    layout_summary, layout_summary_error = _read_layout_summary(
        layout_report_json_path,
        layout_report,
        expected_profile_family="native",
    )
    if layout_completed.returncode != 0:
        layout_summary["final_status"] = "FAIL"
        layout_summary["layout_policy_status"] = "FAIL"
    layout_policy_status = layout_summary.get("layout_policy_status")
    layout_final_mode = layout_summary.get("final_mode")
    if enable_layout_hints and hint_status["layout_hint_source"] == LAYOUT_HINT_SOURCE_NONE:
        hint_status["layout_hint_source"] = _classify_layout_hint_source(
            enable_layout_hints=enable_layout_hints,
            layout_hints_json=layout_hints_json,
        )

    semantic_payload["layout_policy_status"] = layout_policy_status
    if layout_summary_error:
        semantic_payload["layout_summary_error"] = layout_summary_error
    _write_json(semantic_report_path, semantic_payload)
    layout_policy_failed = layout_summary.get("final_status") == "FAIL" or layout_policy_status == "FAIL"
    ok = (
        layout_completed.returncode == 0
        and not layout_policy_failed
        and semantic_payload["status"] == "PASS"
    )
    failure_code = None
    if layout_completed.returncode != 0:
        failure_code = "native_layout_failed"
    elif layout_policy_failed:
        failure_code = "native_layout_policy_failed"
    elif semantic_payload["status"] != "PASS":
        failure_code = "native_hard_check_failed"

    return {
        "ok": ok,
        "failure_code": failure_code,
        "layout_status": "PASS" if layout_completed.returncode == 0 and not layout_policy_failed else "FAIL",
        "semantic_status": semantic_payload["status"],
        "layout_policy_status": layout_policy_status,
        "layout_final_mode": layout_final_mode,
        "layout_summary": layout_summary,
        "layout_summary_error": layout_summary_error,
        "layout_report_path": layout_report,
        "layout_hint_source": hint_status["layout_hint_source"],
        "hint_applied": hint_status["hint_applied"],
        "semantic_report_path": str(semantic_report_path),
        "output_bpmn_path": str(output_bpmn) if output_bpmn.exists() else None,
        "output_bpmn_hash": _result_output_hash(output_bpmn),
        "semantic_payload": semantic_payload,
    }


def _run_simple_bridge(input_bpmn, work_dir, helper_command, timeout_seconds):
    bridge_work_dir = Path(work_dir) / "simple_bridge"
    return run_simple_mode_bridge(
        input_bpmn,
        bridge_work_dir,
        helper_command,
        timeout_seconds=timeout_seconds,
    )


def _inspect_di_completeness(bpmn_path):
    result = {
        "ok": False,
        "sequence_flow_count": 0,
        "bpmn_shape_count": 0,
        "bpmn_edge_count": 0,
        "edge_without_two_waypoints_count": 0,
        "edge_di_complete": False,
        "di_quality": "no_di",
        "parse_error": None,
    }
    try:
        root = ET.parse(str(bpmn_path)).getroot()
    except (OSError, ET.ParseError) as exc:
        result["parse_error"] = str(exc)
        return result

    sequence_flow_count = 0
    bpmn_shape_count = 0
    bpmn_edge_count = 0
    edge_without_two_waypoints_count = 0
    for element in root.iter():
        namespace = _tag_namespace(element.tag)
        local = _tag_local_name(element.tag)
        if namespace == BPMN_MODEL_NS and local == "sequenceFlow":
            sequence_flow_count += 1
        elif namespace == BPMN_DI_NS and local == "BPMNShape":
            bpmn_shape_count += 1
        elif namespace == BPMN_DI_NS and local == "BPMNEdge":
            bpmn_edge_count += 1
            waypoint_count = sum(1 for child in list(element) if _tag_local_name(child.tag) == "waypoint")
            if waypoint_count < 2:
                edge_without_two_waypoints_count += 1

    edge_di_complete = True
    if sequence_flow_count > 0 and bpmn_edge_count < sequence_flow_count:
        edge_di_complete = False
    if edge_without_two_waypoints_count > 0:
        edge_di_complete = False

    result.update(
        {
            "ok": edge_di_complete,
            "sequence_flow_count": sequence_flow_count,
            "bpmn_shape_count": bpmn_shape_count,
            "bpmn_edge_count": bpmn_edge_count,
            "edge_without_two_waypoints_count": edge_without_two_waypoints_count,
            "edge_di_complete": edge_di_complete,
            "di_quality": _classify_di_quality(
                sequence_flow_count=sequence_flow_count,
                bpmn_shape_count=bpmn_shape_count,
                bpmn_edge_count=bpmn_edge_count,
                edge_without_two_waypoints_count=edge_without_two_waypoints_count,
            ),
        }
    )
    return result


def _append_simple_di_report(layout_report_path, di_completeness):
    path = Path(layout_report_path)
    if not path.exists():
        return
    lines = [
        "",
        "## Simple Postprocess DI Completeness",
        f"- sequence_flow_count: `{di_completeness['sequence_flow_count']}`",
        f"- bpmn_shape_count: `{di_completeness['bpmn_shape_count']}`",
        f"- bpmn_edge_count: `{di_completeness['bpmn_edge_count']}`",
        f"- edge_without_two_waypoints_count: `{di_completeness['edge_without_two_waypoints_count']}`",
        f"- edge_di_complete: `{'true' if di_completeness['edge_di_complete'] else 'false'}`",
        f"- di_quality: `{di_completeness['di_quality']}`",
    ]
    if di_completeness.get("parse_error"):
        lines.append(f"- parse_error: `{di_completeness['parse_error']}`")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _post_process_simple(
    input_bpmn,
    work_dir,
    bridge_result=None,
    enable_layout_hints=False,
    layout_hints_json=None,
):
    output_bpmn = Path(work_dir) / "simple_postprocessed_output.bpmn"
    layout_report_path = Path(work_dir) / "layout_report.md"
    layout_report_json_path = Path(work_dir) / LAYOUT_REPORT_SUMMARY_FILENAME
    helper_di_completeness = None
    helper_di_quality = "no_di"
    if bridge_result and bridge_result.get("final_bpmn_path"):
        helper_di_completeness = _inspect_di_completeness(bridge_result["final_bpmn_path"])
        helper_di_quality = helper_di_completeness.get("di_quality", "no_di")
    layout_completed = _run_layout(
        input_bpmn,
        output_bpmn,
        layout_report_path,
        layout_report_json_path,
        enable_layout_hints=enable_layout_hints,
        layout_hints_json=layout_hints_json,
        simple_postprocess=True,
        preserve_existing_di_strict=False,
    )
    layout_returncode = layout_completed.returncode
    layout_stdout = layout_completed.stdout
    layout_stderr = layout_completed.stderr
    layout_report = str(layout_report_path) if layout_report_path.exists() else None
    if layout_report is None:
        layout_report = _ensure_layout_report(
            layout_report_path,
            backend="simple",
            returncode=layout_returncode,
            stdout=layout_stdout,
            stderr=layout_stderr,
            enable_layout_hints=enable_layout_hints,
            layout_hints_json=layout_hints_json,
        )
    layout_summary, layout_summary_error = _read_layout_summary(
        layout_report_json_path,
        layout_report,
        expected_profile_family="simple_postprocess",
    )
    if layout_returncode != 0:
        layout_summary["final_status"] = "FAIL"
        layout_summary["layout_policy_status"] = "FAIL"
    layout_policy_status = layout_summary.get("layout_policy_status")
    fallback_category = FALLBACK_SIMPLE_POSTPROCESS_FAILED
    failure_code = None
    di_completeness = _inspect_di_completeness(output_bpmn if output_bpmn.exists() else input_bpmn)
    if layout_returncode == 0:
        _append_simple_di_report(layout_report, di_completeness)
        if layout_summary_error:
            failure_code = DETAIL_SIMPLE_LAYOUT_SUMMARY_INVALID
            fallback_category = FALLBACK_SIMPLE_HARD_CHECK_FAILED
        elif layout_summary.get("final_status") == "FAIL" or layout_policy_status == "FAIL":
            failure_code = DETAIL_SIMPLE_LAYOUT_POLICY_FAILED
            fallback_category = FALLBACK_SIMPLE_HARD_CHECK_FAILED
        elif not di_completeness["ok"]:
            failure_code = DETAIL_SIMPLE_EDGE_DI_INCOMPLETE
            fallback_category = FALLBACK_SIMPLE_HARD_CHECK_FAILED
    else:
        failure_code = DETAIL_SIMPLE_POSTPROCESS_LAYOUT_FAILED

    ok = (
        failure_code is None
        and layout_returncode == 0
        and layout_summary.get("final_status") != "FAIL"
        and layout_policy_status != "FAIL"
        and output_bpmn.exists()
        and di_completeness["ok"]
    )
    hint_status = _read_layout_hint_status(layout_report)
    if enable_layout_hints and hint_status["layout_hint_source"] == LAYOUT_HINT_SOURCE_NONE:
        hint_status["layout_hint_source"] = _classify_layout_hint_source(
            enable_layout_hints=enable_layout_hints,
            layout_hints_json=layout_hints_json,
        )
    return {
        "ok": ok,
        "failure_code": failure_code,
        "fallback_category": fallback_category if not ok else None,
        "layout_status": "PASS" if ok else "FAIL",
        "layout_policy_status": layout_policy_status,
        "layout_final_mode": layout_summary.get("final_mode"),
        "layout_profile_family": layout_summary.get("layout_profile_family"),
        "layout_summary": layout_summary,
        "layout_summary_error": layout_summary_error,
        "helper_di_quality": helper_di_quality,
        "helper_di_completeness": helper_di_completeness,
        "layout_report_path": layout_report,
        "layout_hint_source": hint_status["layout_hint_source"],
        "hint_applied": hint_status["hint_applied"],
        "output_bpmn_path": str(output_bpmn) if output_bpmn.exists() else None,
        "output_bpmn_hash": _result_output_hash(output_bpmn),
        "layout_returncode": layout_returncode,
        "layout_stdout": layout_stdout,
        "layout_stderr": layout_stderr,
        "di_completeness": di_completeness,
    }


def _validate_simple_output(output_bpmn, bridge_result, post_process_result, semantic_report_path):
    semantic_payload = _run_semantic_validation(output_bpmn)
    semantic_payload["backend"] = "simple"
    semantic_payload["bridge_result"] = bridge_result
    semantic_payload["layout_returncode"] = post_process_result["layout_returncode"]
    semantic_payload["layout_stdout"] = post_process_result["layout_stdout"]
    semantic_payload["layout_stderr"] = post_process_result["layout_stderr"]
    _write_json(semantic_report_path, semantic_payload)

    ok = semantic_payload["status"] == "PASS"
    return {
        "ok": ok,
        "failure_code": None if ok else DETAIL_SIMPLE_VALIDATION_FAILED,
        "layout_status": "PASS",
        "semantic_status": semantic_payload["status"],
        "layout_summary": post_process_result.get("layout_summary"),
        "layout_final_mode": post_process_result.get("layout_final_mode"),
        "layout_profile_family": post_process_result.get("layout_profile_family"),
        "layout_report_path": post_process_result["layout_report_path"],
        "layout_hint_source": post_process_result["layout_hint_source"],
        "hint_applied": post_process_result["hint_applied"],
        "semantic_report_path": str(semantic_report_path),
        "output_bpmn_path": post_process_result["output_bpmn_path"],
        "output_bpmn_hash": post_process_result.get("output_bpmn_hash"),
        "semantic_payload": semantic_payload,
    }


def _build_human_summary(manifest):
    lines = [
        "# BPMN Pipeline Summary",
        "",
        f"- manifest_schema_version: `{manifest['manifest_schema_version']}`",
        f"- linked_report_schema_version: `{manifest['linked_report_schema_version']}`",
        f"- runtime_target: `{manifest['runtime_target']}`",
        f"- build_version: `{manifest['build_version']}`",
        f"- skill_version: `{manifest['skill_version']}`",
        f"- requested_mode: `{manifest['requested_mode']}`",
        f"- eligibility_class: `{manifest['eligibility_class']}`",
        f"- initial_backend: `{manifest['initial_backend']}`",
        f"- final_backend: `{manifest['final_backend']}`",
        f"- fallback_happened: `{str(manifest['fallback_happened']).lower()}`",
        f"- semantic_status: `{manifest['semantic_status']}`",
        f"- layout_status: `{manifest['layout_status']}`",
        f"- layout_policy_status: `{manifest['layout_summary']['layout_policy_status']}`",
        f"- layout_final_mode: `{manifest['layout_summary']['final_mode']}`",
        f"- advisory_only: `{str(manifest['layout_summary']['advisory_only']).lower()}`",
        f"- warning_issue_count: `{manifest['layout_summary']['warning_issue_count']}`",
        f"- error_issue_count: `{manifest['layout_summary']['error_issue_count']}`",
        f"- diagram_width_px: `{manifest['layout_summary'].get('diagram_width_px', 0)}`",
        f"- diagram_height_px: `{manifest['layout_summary'].get('diagram_height_px', 0)}`",
        f"- aspect_ratio_x100: `{manifest['layout_summary'].get('aspect_ratio_x100', 0)}`",
        f"- layout_requires_decomposition: `{str(manifest['layout_summary'].get('layout_requires_decomposition', False)).lower()}`",
        f"- preview_status: `{manifest['preview_status']}`",
        f"- layout_hint_source: `{manifest['layout_hint_source']}`",
        f"- hint_applied: `{str(manifest['hint_applied']).lower()}`",
        f"- traceability_count: `{manifest['traceability_count']}`",
        f"- assumptions_count: `{manifest['assumptions_count']}`",
    ]
    if manifest.get("scenario_id"):
        lines.append(f"- scenario_id: `{manifest['scenario_id']}`")
    if manifest.get("fixture_id"):
        lines.append(f"- fixture_id: `{manifest['fixture_id']}`")
    if manifest.get("fallback_reason_code"):
        lines.append(f"- fallback_reason_code: `{manifest['fallback_reason_code']}`")
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
        ]
    )
    for artifact_key in (
        ARTIFACT_BACKEND_SELECTION,
        ARTIFACT_SEMANTIC_REPORT,
        ARTIFACT_LAYOUT_REPORT,
        ARTIFACT_PREVIEW_REPORT,
        ARTIFACT_TYPED_ISSUE_TARGETS,
    ):
        artifact = manifest["artifacts"][artifact_key]
        lines.append(
            f"- {artifact_key}: presence=`{artifact['presence']}` status=`{artifact['status']}`"
        )
        if artifact["presence"] == "present":
            lines.append(f"  path=`{artifact['path']}`")
    return "\n".join(lines) + "\n"


def _transition(runtime_state, new_state, reason, **details):
    runtime_state["state"] = new_state
    entry = {
        "index": len(runtime_state["state_history"]) + 1,
        "state": new_state,
        "reason": reason,
    }
    for key, value in details.items():
        if value is not None:
            entry[key] = value
    runtime_state["state_history"].append(entry)


def _initialize_runtime_state(selection, semantic_report_path, simple_backend_available, run_context):
    initial_backend = _resolve_initial_backend(selection, simple_backend_available=simple_backend_available)
    skipped = initial_backend == "none"
    return {
        "selection": selection,
        "state": None,
        "state_history": [],
        "initial_backend": initial_backend,
        "final_backend": initial_backend,
        "fallback_happened": False,
        "fallback_trigger_category": None,
        "fallback_trigger_detail_code": None,
        "fallback_reason_code": None,
        "final_failure_category": None,
        "final_failure_detail_code": None,
        "native_fallback_failure_code": None,
        "layout_status": "SKIPPED" if skipped else "FAIL",
        "semantic_status": "PASS" if skipped else "FAIL",
        "layout_summary": _empty_layout_summary("SKIPPED" if skipped else "FAIL"),
        "preview_status": "SKIPPED",
        "preview_report_path": None,
        "typed_issue_targets_path": None,
        "preview_result": None,
        "layout_hint_source": LAYOUT_HINT_SOURCE_NONE,
        "hint_applied": False,
        "layout_report_path": None,
        "semantic_report_path": str(semantic_report_path),
        "simple_bridge_result": None,
        "simple_postprocess_result": None,
        "simple_validation_result": None,
        "native_result": None,
        "selector_facts": {},
        "run_context": dict(run_context),
    }


def _record_simple_fallback(runtime_state, category, detail_code):
    runtime_state["fallback_happened"] = True
    runtime_state["fallback_trigger_category"] = category
    runtime_state["fallback_trigger_detail_code"] = detail_code
    runtime_state["fallback_reason_code"] = category
    runtime_state["final_backend"] = "native"


def _derive_fallback_reason_code(runtime_state):
    if not runtime_state["fallback_happened"]:
        return None
    if runtime_state["final_failure_category"]:
        return runtime_state["final_failure_category"]
    return runtime_state["fallback_trigger_category"]


def _run_native_phase(
    runtime_state,
    input_bpmn,
    work_path,
    semantic_report_path,
    reason,
    enable_layout_hints=False,
    layout_hints_json=None,
    preserve_existing_di_strict=False,
):
    _transition(
        runtime_state,
        STATE_FALLBACK_NATIVE,
        reason,
        fallback_happened=runtime_state["fallback_happened"],
        trigger_category=runtime_state["fallback_trigger_category"],
        backend="native",
    )
    native_result = _execute_native(
        input_bpmn,
        work_path,
        semantic_report_path,
        enable_layout_hints=enable_layout_hints,
        layout_hints_json=layout_hints_json,
        preserve_existing_di_strict=preserve_existing_di_strict,
    )
    runtime_state["native_result"] = native_result
    runtime_state["final_backend"] = "native"
    runtime_state["layout_status"] = native_result["layout_status"]
    runtime_state["semantic_status"] = native_result["semantic_status"]
    runtime_state["layout_summary"] = native_result.get("layout_summary") or _empty_layout_summary(
        native_result["layout_status"]
    )
    runtime_state["layout_report_path"] = native_result["layout_report_path"]
    runtime_state["layout_hint_source"] = native_result["layout_hint_source"]
    runtime_state["hint_applied"] = native_result["hint_applied"]
    preserve_degraded_to_greenfield = (
        native_result["ok"]
        and not runtime_state["fallback_happened"]
        and runtime_state["selection"].get("effective_preserve_existing_di")
        and native_result.get("layout_final_mode") == "native_greenfield"
    )
    if preserve_degraded_to_greenfield:
        runtime_state["fallback_happened"] = True
        runtime_state["fallback_trigger_category"] = FALLBACK_NATIVE_PRESERVE_DEGRADED
        runtime_state["fallback_trigger_detail_code"] = "layout_final_mode_native_greenfield"
        runtime_state["fallback_reason_code"] = FALLBACK_NATIVE_PRESERVE_DEGRADED
    _transition(
        runtime_state,
        STATE_VALIDATE,
        "native_validation_complete",
        backend="native",
        ok=native_result["ok"],
        failure_code=native_result["failure_code"],
    )
    if native_result["ok"]:
        _transition(runtime_state, STATE_FINALIZE, "native_pass", backend="native")
        return True

    if runtime_state["fallback_happened"]:
        runtime_state["native_fallback_failure_code"] = native_result["failure_code"] or FALLBACK_NATIVE_FAILED
        runtime_state["final_failure_category"] = FALLBACK_NATIVE_FAILED
        runtime_state["final_failure_detail_code"] = runtime_state["native_fallback_failure_code"]
        _transition(
            runtime_state,
            STATE_FAIL,
            FALLBACK_NATIVE_FAILED,
            category=FALLBACK_NATIVE_FAILED,
            detail_code=runtime_state["native_fallback_failure_code"],
        )
    else:
        runtime_state["final_failure_detail_code"] = native_result["failure_code"]
        _transition(
            runtime_state,
            STATE_FAIL,
            "native_path_failed",
            backend="native",
            detail_code=native_result["failure_code"],
        )
    return False


def _build_backend_selection_payload(runtime_state):
    payload = {
        "selection": runtime_state["selection"],
        "selector_facts": runtime_state.get("selector_facts", {}),
        "state": runtime_state["state"],
        "state_history": runtime_state["state_history"],
        "initial_backend": runtime_state["initial_backend"],
        "final_backend": runtime_state["final_backend"],
        "fallback_happened": runtime_state["fallback_happened"],
        "fallback_reason_code": _derive_fallback_reason_code(runtime_state),
        "fallback_trigger_category": runtime_state["fallback_trigger_category"],
        "fallback_trigger_detail_code": runtime_state["fallback_trigger_detail_code"],
        "final_failure_category": runtime_state["final_failure_category"],
        "final_failure_detail_code": runtime_state["final_failure_detail_code"],
        "native_fallback_failure_code": runtime_state["native_fallback_failure_code"],
        "semantic_status": runtime_state["semantic_status"],
        "layout_status": runtime_state["layout_status"],
        "layout_summary": runtime_state.get("layout_summary"),
        "preview_status": runtime_state["preview_status"],
        "layout_hint_source": runtime_state["layout_hint_source"],
        "hint_applied": runtime_state["hint_applied"],
    }
    if runtime_state["simple_bridge_result"] is not None:
        payload["simple_bridge_result"] = runtime_state["simple_bridge_result"]
    if runtime_state["simple_postprocess_result"] is not None:
        payload["simple_postprocess_result"] = runtime_state["simple_postprocess_result"]
    if runtime_state["simple_validation_result"] is not None:
        payload["simple_validation_result"] = runtime_state["simple_validation_result"]
    if runtime_state["native_result"] is not None:
        payload["native_result"] = runtime_state["native_result"]
    if runtime_state["preview_result"] is not None:
        payload["preview_result"] = runtime_state["preview_result"]
    return payload


def _build_manifest(runtime_state):
    selection = runtime_state["selection"]
    run_context = runtime_state["run_context"]
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "linked_report_schema_version": LINKED_REPORT_SCHEMA_VERSION,
        "build_version": str(run_context.get("build_version") or DEFAULT_BUILD_VERSION),
        "skill_version": str(run_context.get("skill_version") or DEFAULT_SKILL_VERSION),
        "runtime_target": str(run_context.get("runtime_target") or DEFAULT_RUNTIME_TARGET),
        "requested_mode": selection["requested_mode"],
        "logic_only": selection["logic_only"],
        "preserve_existing_di": selection["preserve_existing_di"],
        "full_relayout": selection["full_relayout"],
        "layout_bypass": bool(run_context.get("layout_bypass", False)),
        "eligibility_class": selection["eligibility_class"],
        "eligibility_reasons": list(selection["eligibility_reasons"]),
        "scenario_id": run_context.get("scenario_id"),
        "fixture_id": run_context.get("fixture_id"),
        "traceability_count": int(run_context.get("traceability_count", 0)),
        "assumptions_count": int(run_context.get("assumptions_count", 0)),
        "initial_backend": runtime_state["initial_backend"],
        "final_backend": runtime_state["final_backend"],
        "fallback_happened": runtime_state["fallback_happened"],
        "semantic_status": runtime_state["semantic_status"],
        "layout_status": runtime_state["layout_status"],
        "layout_summary": runtime_state.get("layout_summary") or _empty_layout_summary(
            runtime_state["layout_status"]
        ),
        "preview_status": runtime_state["preview_status"],
        "layout_hint_source": runtime_state["layout_hint_source"],
        "hint_applied": runtime_state["hint_applied"],
        "artifacts": {},
    }
    fallback_reason_code = _derive_fallback_reason_code(runtime_state)
    if fallback_reason_code is not None:
        manifest["fallback_reason_code"] = fallback_reason_code
    preview_result = runtime_state.get("preview_result")
    if isinstance(preview_result, dict):
        preview_summary = {
            "preview_import_ok": bool(preview_result.get("audit", {}).get("ok", False)),
            "typed_issue_target_count": int(preview_result.get("typed_issue_target_count", 0)),
        }
        manifest["preview_summary"] = preview_summary
    return manifest


def _build_artifacts(
    runtime_state,
    manifest,
    backend_selection_path,
    semantic_report_path,
    human_summary_path,
    preview_report_path=None,
    typed_issue_targets_path=None,
):
    layout_report_status = manifest["layout_status"]
    preview_report_status = manifest["preview_status"]
    run_status = "PASS" if runtime_state["state"] == STATE_FINALIZE else "FAIL"
    artifacts = {
        ARTIFACT_BACKEND_SELECTION: _linked_artifact_record(
            report_kind=ARTIFACT_BACKEND_SELECTION,
            presence="present",
            status=run_status,
            path=backend_selection_path,
        ),
        ARTIFACT_SEMANTIC_REPORT: _linked_artifact_record(
            report_kind=ARTIFACT_SEMANTIC_REPORT,
            presence="present",
            status=manifest["semantic_status"],
            path=semantic_report_path,
        ),
        ARTIFACT_LAYOUT_REPORT: _optional_artifact_record(
            report_kind=ARTIFACT_LAYOUT_REPORT,
            status=layout_report_status,
            path=runtime_state["layout_report_path"],
            absent_presence="skipped",
        ),
        ARTIFACT_PREVIEW_REPORT: _optional_artifact_record(
            report_kind=ARTIFACT_PREVIEW_REPORT,
            status=preview_report_status,
            path=preview_report_path,
            absent_presence="skipped",
        ),
        ARTIFACT_TYPED_ISSUE_TARGETS: _optional_artifact_record(
            report_kind=ARTIFACT_TYPED_ISSUE_TARGETS,
            status="PASS" if typed_issue_targets_path else "SKIPPED",
            path=typed_issue_targets_path,
            absent_presence="not_applicable",
        ),
    }
    if human_summary_path is not None and Path(human_summary_path).exists():
        artifacts[ARTIFACT_HUMAN_SUMMARY] = _linked_artifact_record(
            report_kind=ARTIFACT_HUMAN_SUMMARY,
            presence="present",
            status=run_status,
            path=human_summary_path,
        )
    else:
        artifacts[ARTIFACT_HUMAN_SUMMARY] = _linked_artifact_record(
            report_kind=ARTIFACT_HUMAN_SUMMARY,
            presence="skipped",
            status="SKIPPED",
        )
    return artifacts


def _materialize_manifest(
    runtime_state,
    manifest_path,
    backend_selection_path,
    semantic_report_path,
    human_summary_path,
):
    runtime_state["fallback_reason_code"] = _derive_fallback_reason_code(runtime_state)
    _write_json(backend_selection_path, _build_backend_selection_payload(runtime_state))

    manifest = _build_manifest(runtime_state)
    manifest["artifacts"] = _build_artifacts(
        runtime_state,
        manifest,
        backend_selection_path,
        semantic_report_path,
        None,
        preview_report_path=runtime_state.get("preview_report_path"),
        typed_issue_targets_path=runtime_state.get("typed_issue_targets_path"),
    )
    _write_text(human_summary_path, _build_human_summary(manifest))
    manifest["artifacts"] = _build_artifacts(
        runtime_state,
        manifest,
        backend_selection_path,
        semantic_report_path,
        human_summary_path,
        preview_report_path=runtime_state.get("preview_report_path"),
        typed_issue_targets_path=runtime_state.get("typed_issue_targets_path"),
    )

    schema = load_schema(SCHEMA_DIR)
    manifest_errors = validate_manifest_data(manifest, schema)
    if manifest_errors:
        raise RuntimeError("run_manifest validation failed: " + "; ".join(manifest_errors))
    _write_json(manifest_path, manifest)
    return manifest


def _write_preview_failure_report(report_path, manifest_path, error_message):
    payload = {
        "schema_version": getattr(PREVIEW_BUILDER, "PREVIEW_SCHEMA_VERSION", "1"),
        "status": "FAIL",
        "manifest_path": str(Path(manifest_path)),
        "error": str(error_message),
    }
    _write_json(report_path, payload)
    return str(report_path)


def _run_preview_phase(runtime_state, manifest_path, work_path, preview_output_dir=None):
    _transition(
        runtime_state,
        STATE_PREVIEW,
        "build_preview_artifacts",
        backend=runtime_state["final_backend"],
    )
    preview_dir = Path(preview_output_dir) if preview_output_dir else Path(work_path) / "preview_artifacts"
    try:
        preview_result = build_preview_artifacts(manifest_path, preview_dir)
        runtime_state["preview_status"] = "PASS"
        runtime_state["preview_report_path"] = preview_result.get("preview_report_path")
        runtime_state["typed_issue_targets_path"] = preview_result.get("typed_issue_targets_path")
        runtime_state["preview_result"] = preview_result
        _transition(runtime_state, STATE_FINALIZE, "preview_pass", backend=runtime_state["final_backend"])
        return
    except Exception as exc:
        failure_detail = str(exc)

    preview_failure_report_path = Path(work_path) / CANONICAL_ARTIFACT_FILENAMES[ARTIFACT_PREVIEW_REPORT]
    runtime_state["preview_status"] = "FAIL"
    runtime_state["preview_report_path"] = _write_preview_failure_report(
        preview_failure_report_path,
        manifest_path,
        failure_detail,
    )
    runtime_state["typed_issue_targets_path"] = None
    runtime_state["preview_result"] = {
        "ok": False,
        "error": failure_detail,
    }
    runtime_state["final_failure_category"] = FAILURE_PREVIEW_BUILD_FAILED
    runtime_state["final_failure_detail_code"] = FAILURE_PREVIEW_BUILD_FAILED
    _transition(
        runtime_state,
        STATE_FAIL,
        FAILURE_PREVIEW_BUILD_FAILED,
        category=FAILURE_PREVIEW_BUILD_FAILED,
        detail_code=failure_detail,
    )


def run_pipeline(
    input_bpmn,
    work_dir,
    requested_mode="auto",
    logic_only=False,
    preserve_existing_di=False,
    full_relayout=False,
    helper_command=None,
    timeout_seconds=30,
    facts=None,
    manifest_path=None,
    enable_layout_hints=False,
    layout_hints_json=None,
    build_preview=False,
    preview_output_dir=None,
):
    caller_facts = dict(facts or {})
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(manifest_path) if manifest_path else work_path / "run_manifest.json"

    selector_fact_bundle = _merge_selector_facts(input_bpmn, caller_facts)
    merged_selector_facts = selector_fact_bundle["merged"]
    di_quality = str(
        merged_selector_facts.get("di_quality")
        or selector_fact_bundle["extracted"].get("di_quality")
        or "no_di"
    ).strip().lower()
    inferred_preserve_existing_di = (
        not logic_only
        and not full_relayout
        and not preserve_existing_di
        and di_quality == "usable_di"
        and str(requested_mode or "auto").strip().lower() != "simple"
    )
    effective_preserve_existing_di = bool(preserve_existing_di or inferred_preserve_existing_di)
    merged_selector_facts["di_quality"] = di_quality
    merged_selector_facts["has_existing_di"] = di_quality != "no_di"
    merged_selector_facts["has_partial_di"] = di_quality == "partial_di"
    merged_selector_facts["has_usable_di"] = di_quality == "usable_di"
    selection = classify_eligibility(
        requested_mode=requested_mode,
        logic_only=logic_only,
        preserve_existing_di=effective_preserve_existing_di,
        full_relayout=full_relayout,
        facts=merged_selector_facts,
    )
    simple_backend_available = bool(helper_command and str(helper_command).strip())
    selection_runtime = dict(selection)
    selection_runtime["requested_preserve_existing_di"] = bool(preserve_existing_di)
    selection_runtime["preserve_existing_di"] = effective_preserve_existing_di
    selection_runtime["effective_preserve_existing_di"] = effective_preserve_existing_di
    selection_runtime["inferred_preserve_existing_di"] = inferred_preserve_existing_di
    selection_runtime["di_quality"] = di_quality
    native_preserve_strict = bool(
        selection_runtime["effective_preserve_existing_di"]
        and not selection_runtime["full_relayout"]
        and selection_runtime["requested_mode"] != "auto"
    )
    selection_runtime["native_preserve_strict"] = native_preserve_strict
    if (
        selection_runtime["requested_mode"] in ("auto", "simple")
        and not selection_runtime["forced_skip_layout"]
        and not selection_runtime["forced_native"]
        and not simple_backend_available
    ):
        selection_runtime["eligibility_reasons"] = list(selection_runtime["eligibility_reasons"]) + [
            "simple_helper_unavailable_forced_native"
        ]

    backend_selection_path = work_path / "backend_selection.json"
    semantic_report_path = work_path / "semantic_report.json"
    human_summary_path = work_path / "human_summary.md"

    runtime_state = _initialize_runtime_state(
        selection_runtime,
        semantic_report_path,
        simple_backend_available=simple_backend_available,
        run_context=caller_facts,
    )
    runtime_state["selector_facts"] = selector_fact_bundle
    _transition(
        runtime_state,
        STATE_SELECT,
        "selector_result",
        requested_mode=selection_runtime["requested_mode"],
        eligibility_class=selection_runtime["eligibility_class"],
        initial_backend=runtime_state["initial_backend"],
        simple_backend_available=simple_backend_available,
    )

    if runtime_state["initial_backend"] == "none":
        _write_json(
            semantic_report_path,
            {
                "backend": "none",
                "status": "PASS",
                "errors": [],
                "warnings": ["logic_only mode skips layout and preview"],
            },
        )
        runtime_state["final_backend"] = "none"
        _transition(runtime_state, STATE_FINALIZE, "logic_only_short_circuit", backend="none")
    elif runtime_state["initial_backend"] == "native":
        _run_native_phase(
            runtime_state,
            input_bpmn,
            work_path,
            semantic_report_path,
            reason="initial_backend_native",
            enable_layout_hints=enable_layout_hints,
            layout_hints_json=layout_hints_json,
            preserve_existing_di_strict=native_preserve_strict,
        )
    else:
        _transition(runtime_state, STATE_PROJECT, "prepare_simple_projection", backend="simple")
        _transition(runtime_state, STATE_SIMPLE_LAYOUT, "run_simple_helper", backend="simple")
        bridge_result = _run_simple_bridge(
            input_bpmn,
            work_path,
            helper_command,
            timeout_seconds,
        )
        runtime_state["simple_bridge_result"] = bridge_result

        if not bridge_result["ok"]:
            _record_simple_fallback(
                runtime_state,
                FALLBACK_SIMPLE_HELPER_FAILED,
                bridge_result["failure_code"],
            )
            _run_native_phase(
                runtime_state,
                input_bpmn,
                work_path,
                semantic_report_path,
                reason=FALLBACK_SIMPLE_HELPER_FAILED,
                enable_layout_hints=enable_layout_hints,
                layout_hints_json=layout_hints_json,
            )
        else:
            _transition(runtime_state, STATE_POST_PROCESS, "post_process_simple_output", backend="simple")
            post_process_result = _post_process_simple(
                bridge_result["final_bpmn_path"],
                work_path,
                bridge_result=bridge_result,
                enable_layout_hints=enable_layout_hints,
                layout_hints_json=layout_hints_json,
            )
            runtime_state["simple_postprocess_result"] = post_process_result

            if not post_process_result["ok"]:
                runtime_state["layout_status"] = "FAIL"
                runtime_state["semantic_status"] = "FAIL"
                runtime_state["layout_summary"] = post_process_result.get("layout_summary") or _empty_layout_summary("FAIL")
                runtime_state["layout_report_path"] = post_process_result["layout_report_path"]
                runtime_state["layout_hint_source"] = post_process_result["layout_hint_source"]
                runtime_state["hint_applied"] = post_process_result["hint_applied"]
                fallback_category = post_process_result.get("fallback_category") or FALLBACK_SIMPLE_POSTPROCESS_FAILED
                _record_simple_fallback(
                    runtime_state,
                    fallback_category,
                    post_process_result["failure_code"],
                )
                _run_native_phase(
                    runtime_state,
                    input_bpmn,
                    work_path,
                    semantic_report_path,
                    reason=fallback_category,
                    enable_layout_hints=enable_layout_hints,
                    layout_hints_json=layout_hints_json,
                )
            else:
                _transition(runtime_state, STATE_VALIDATE, "validate_simple_output", backend="simple")
                simple_validation_result = _validate_simple_output(
                    post_process_result["output_bpmn_path"],
                    bridge_result,
                    post_process_result,
                    semantic_report_path,
                )
                runtime_state["simple_validation_result"] = simple_validation_result
                runtime_state["layout_status"] = simple_validation_result["layout_status"]
                runtime_state["semantic_status"] = simple_validation_result["semantic_status"]
                runtime_state["layout_summary"] = simple_validation_result.get("layout_summary") or _empty_layout_summary(
                    simple_validation_result["layout_status"]
                )
                runtime_state["layout_report_path"] = simple_validation_result["layout_report_path"]
                runtime_state["layout_hint_source"] = simple_validation_result["layout_hint_source"]
                runtime_state["hint_applied"] = simple_validation_result["hint_applied"]

                if simple_validation_result["ok"]:
                    runtime_state["final_backend"] = "simple"
                    _transition(runtime_state, STATE_FINALIZE, "simple_pass", backend="simple")
                else:
                    _record_simple_fallback(
                        runtime_state,
                        FALLBACK_SIMPLE_HARD_CHECK_FAILED,
                        simple_validation_result["failure_code"],
                    )
                    _run_native_phase(
                        runtime_state,
                        input_bpmn,
                        work_path,
                        semantic_report_path,
                        reason=FALLBACK_SIMPLE_HARD_CHECK_FAILED,
                        enable_layout_hints=enable_layout_hints,
                        layout_hints_json=layout_hints_json,
                    )

    manifest = _materialize_manifest(
        runtime_state,
        manifest_path,
        backend_selection_path,
        semantic_report_path,
        human_summary_path,
    )
    if build_preview and runtime_state["state"] == STATE_FINALIZE and runtime_state["final_backend"] != "none":
        _run_preview_phase(
            runtime_state,
            manifest_path,
            work_path,
            preview_output_dir=preview_output_dir,
        )
        manifest = _materialize_manifest(
            runtime_state,
            manifest_path,
            backend_selection_path,
            semantic_report_path,
            human_summary_path,
        )
    success = runtime_state["state"] == STATE_FINALIZE
    return {
        "ok": success,
        "manifest": manifest,
        "manifest_path": str(manifest_path),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the minimal BPMN pipeline.")
    parser.add_argument("input")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--manifest-path")
    parser.add_argument("--requested-mode", default="auto", choices=["auto", "native", "simple"])
    parser.add_argument("--logic-only", action="store_true")
    parser.add_argument("--preserve-existing-di", action="store_true")
    parser.add_argument("--full-relayout", action="store_true")
    parser.add_argument("--helper-command")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--facts-json", help="Inline JSON object or path to a JSON file")
    parser.add_argument("--enable-layout-hints", action="store_true")
    parser.add_argument("--layout-hints-json", help="Inline JSON or path to hint payload")
    parser.add_argument("--build-preview", action="store_true")
    parser.add_argument("--preview-output-dir", help="Directory for offline preview assets and report payloads")
    args = parser.parse_args(argv)

    facts = {}
    if args.facts_json:
        facts = BACKEND_SELECTOR._load_facts(args.facts_json)

    result = run_pipeline(
        input_bpmn=args.input,
        work_dir=args.work_dir,
        requested_mode=args.requested_mode,
        logic_only=args.logic_only,
        preserve_existing_di=args.preserve_existing_di,
        full_relayout=args.full_relayout,
        helper_command=args.helper_command,
        timeout_seconds=args.timeout_seconds,
        facts=facts,
        manifest_path=args.manifest_path,
        enable_layout_hints=args.enable_layout_hints,
        layout_hints_json=args.layout_hints_json,
        build_preview=args.build_preview,
        preview_output_dir=args.preview_output_dir,
    )
    print(json.dumps(result["manifest"], indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
