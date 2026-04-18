#!/usr/bin/env python3
import argparse
from collections import Counter
import hashlib
import html
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
NODE_TOOLING_DIR = PACKAGE_ROOT / "node_tooling"
PREVIEW_ASSETS_DIR = NODE_TOOLING_DIR / "preview_assets"
PREVIEW_SCHEMA_VERSION = "1"
TYPED_ISSUE_TARGETS_SCHEMA_VERSION = "1"
DEFAULT_OUTPUT_DIRNAME = "preview_artifacts"
PREVIEW_REPORT_PATH = "preview_report.json"
REQUIRED_ARTIFACTS = ("backend_selection", "semantic_report", "human_summary")
OPTIONAL_ARTIFACTS = ("layout_report",)
TYPED_ISSUE_TARGETS_SCHEMA_PATH = PACKAGE_ROOT / "schemas" / "typed_issue_targets.schema.json"
TYPED_ISSUE_TARGETS_PATH = "typed_issue_targets.json"
_ISSUE_LINE_PATTERN = re.compile(
    r"^- issue: code=(?P<code>\S+) "
    r"severity=(?P<severity>\S+) "
    r"target_type=(?P<target_type>\S+) "
    r"element_id=(?P<element_id>\S+) "
    r"secondary_element_id=(?P<secondary_element_id>\S+) "
    r"bbox=(?P<bbox>.+)$"
)
_TARGET_TYPE_ORDER = ("shape", "edge", "label", "pair", "global")
_SEVERITY_ORDER = ("error", "warning", "info")
_NONE_MARKERS = {"none", "null", "n/a", "na"}
_TARGET_TYPE_MESSAGE_HINTS = {
    "shape": "Shape-targeted layout issue",
    "edge": "Edge-targeted layout issue",
    "label": "Label-targeted layout issue",
    "pair": "Pairwise conflict issue",
    "global": "Global layout issue (text-only guidance)",
}


def _load_local_module(module_name, file_name):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_DIR / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_local_module("validate_run_manifest_local_preview", "validate_run_manifest.py")


def _load_json(path):
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8") as fh:
        fh.write(text)


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


def _resolve_artifact_path(manifest_path, record):
    candidate = Path(record["path"])
    if candidate.is_absolute():
        return candidate
    return manifest_path.parent / candidate


def _assert_manifest_valid(manifest_path):
    errors = VALIDATOR.validate_manifest_file(manifest_path)
    if errors:
        raise RuntimeError("run_manifest validation failed: " + "; ".join(errors))


def _require_present_artifact(manifest, manifest_path, key):
    record = manifest["artifacts"].get(key)
    if not record or record.get("presence") != "present":
        raise RuntimeError(f"artifacts.{key} must be present for preview build")
    path = _resolve_artifact_path(manifest_path, record)
    if not path.exists():
        raise RuntimeError(f"artifacts.{key} path does not exist: {path}")
    actual_hash = _sha256(path)
    if actual_hash != record.get("hash"):
        raise RuntimeError(f"artifacts.{key} hash mismatch: manifest={record.get('hash')} actual={actual_hash}")
    return path


def _resolve_optional_text(manifest, manifest_path, key):
    record = manifest["artifacts"].get(key)
    if not record or record.get("presence") != "present":
        return None
    path = _resolve_artifact_path(manifest_path, record)
    if not path.exists():
        raise RuntimeError(f"artifacts.{key} path does not exist: {path}")
    actual_hash = _sha256(path)
    if actual_hash != record.get("hash"):
        raise RuntimeError(f"artifacts.{key} hash mismatch: manifest={record.get('hash')} actual={actual_hash}")
    return path.read_text(encoding="utf-8")


def _normalize_optional_text(value):
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _NONE_MARKERS:
        return None
    return text


def _parse_bbox(raw_bbox):
    bbox_text = str(raw_bbox).strip()
    if bbox_text.lower() in _NONE_MARKERS:
        return None
    try:
        value = json.loads(bbox_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"unable to parse typed issue bbox: {bbox_text!r}") from exc
    if not isinstance(value, list) or len(value) != 4:
        raise RuntimeError(f"typed issue bbox must be a 4-item list when present, got {value!r}")
    normalized = []
    for item in value:
        if not isinstance(item, (int, float)):
            raise RuntimeError(f"typed issue bbox values must be numeric, got {item!r}")
        normalized.append(float(item) if isinstance(item, float) else int(item))
    return normalized


def _message_for_issue(target_type, code):
    if code:
        return f"{code.replace('_', ' ')} detected"
    return _TARGET_TYPE_MESSAGE_HINTS.get(target_type, "layout issue detected")


def _parse_layout_report_typed_issues(layout_report_text):
    if not layout_report_text:
        return []
    issues = []
    for line_number, line in enumerate(str(layout_report_text).splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("- issue:"):
            continue
        match = _ISSUE_LINE_PATTERN.match(stripped)
        if not match:
            raise RuntimeError(
                "unable to parse typed issue line in layout_report.md at "
                f"line {line_number}: {stripped}"
            )
        target_type = match.group("target_type")
        issue_code = match.group("code")
        severity = match.group("severity")
        element_id = _normalize_optional_text(match.group("element_id"))
        if not element_id:
            raise RuntimeError(
                "typed issue line in layout_report.md has empty element_id at "
                f"line {line_number}: {stripped}"
            )
        issue = {
            "issue_id": f"layout-{len(issues) + 1:04d}",
            "target_type": target_type,
            "element_id": element_id,
            "secondary_element_id": _normalize_optional_text(match.group("secondary_element_id")),
            "label_role": "external_label" if target_type == "label" else None,
            "bbox": _parse_bbox(match.group("bbox")),
            "severity": severity,
            "code": issue_code,
            "message": _message_for_issue(target_type, issue_code),
            "source_report": "layout_report",
            "source_rule": issue_code,
        }
        issues.append(issue)
    return issues


def _build_issue_counts(issues):
    by_type = {target_type: 0 for target_type in _TARGET_TYPE_ORDER}
    by_severity = {severity: 0 for severity in _SEVERITY_ORDER}
    type_counter = Counter(issue["target_type"] for issue in issues)
    severity_counter = Counter(issue["severity"] for issue in issues)
    for target_type, count in sorted(type_counter.items()):
        by_type[target_type] = count
    for severity, count in sorted(severity_counter.items()):
        by_severity[severity] = count
    return {
        "total": len(issues),
        "by_target_type": by_type,
        "by_severity": by_severity,
    }


def _build_typed_issue_targets_payload(manifest, layout_report_text):
    issues = _parse_layout_report_typed_issues(layout_report_text)
    counts = _build_issue_counts(issues)
    return {
        "schema_version": TYPED_ISSUE_TARGETS_SCHEMA_VERSION,
        "source": {
            "manifest_schema_version": str(manifest.get("manifest_schema_version") or ""),
            "linked_report_schema_version": str(manifest.get("linked_report_schema_version") or ""),
            "final_backend": str(manifest.get("final_backend") or ""),
            "layout_status": str(manifest.get("layout_status") or ""),
        },
        "highlight_policy": {
            "phase": "deferred_phase_5",
            "canvas_target_types": ["shape", "edge", "label", "pair"],
            "global_target_behavior": "text_only",
        },
        "counts": counts,
        "items": issues,
    }


def _extract_bpmn_graph_counts(xml_text):
    sequence_flow_count = len(re.findall(r"<(?:[A-Za-z_][\w.-]*:)?sequenceFlow\b", xml_text))
    bpmn_shape_count = len(re.findall(r"<(?:[A-Za-z_][\w.-]*:)?BPMNShape\b", xml_text))
    bpmn_edge_count = len(re.findall(r"<(?:[A-Za-z_][\w.-]*:)?BPMNEdge\b", xml_text))
    return {
        "sequence_flow_count": sequence_flow_count,
        "bpmn_shape_count": bpmn_shape_count,
        "bpmn_edge_count": bpmn_edge_count,
    }


def _load_typed_issue_targets_schema():
    if not TYPED_ISSUE_TARGETS_SCHEMA_PATH.exists():
        raise RuntimeError(f"typed issue targets schema is missing: {TYPED_ISSUE_TARGETS_SCHEMA_PATH}")
    return _load_json(TYPED_ISSUE_TARGETS_SCHEMA_PATH)


def _validate_typed_issue_targets_payload(payload):
    schema = _load_typed_issue_targets_schema()
    errors = VALIDATOR.validate_instance(payload, schema, schema)
    if errors:
        raise RuntimeError("typed_issue_targets payload validation failed: " + "; ".join(errors))


def _resolve_final_bpmn_path(manifest, backend_selection_path):
    backend_selection = _load_json(backend_selection_path)
    final_backend = manifest.get("final_backend")
    if final_backend == "none":
        raise RuntimeError("preview build is not supported for logic_only / final_backend=none runs")

    candidates = []
    if final_backend == "native":
        candidates.extend(
            [
                (
                    backend_selection.get("native_result", {}).get("output_bpmn_path"),
                    backend_selection.get("native_result", {}).get("output_bpmn_hash"),
                ),
            ]
        )
    elif final_backend == "simple":
        candidates.extend(
            [
                (
                    backend_selection.get("simple_validation_result", {}).get("output_bpmn_path"),
                    backend_selection.get("simple_validation_result", {}).get("output_bpmn_hash"),
                ),
                (
                    backend_selection.get("simple_postprocess_result", {}).get("output_bpmn_path"),
                    backend_selection.get("simple_postprocess_result", {}).get("output_bpmn_hash"),
                ),
            ]
        )

    for candidate, expected_hash in candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if not candidate_path.is_absolute():
            candidate_path = backend_selection_path.parent / candidate_path
        if candidate_path.exists():
            if not expected_hash:
                raise RuntimeError(
                    f"backend_selection is missing expected BPMN hash for final backend path: {candidate_path}"
                )
            actual_hash = _sha256(candidate_path)
            if actual_hash != expected_hash:
                raise RuntimeError(
                    "final BPMN XML hash mismatch: "
                    f"expected={expected_hash} actual={actual_hash} path={candidate_path}"
                )
            return candidate_path, actual_hash

    raise RuntimeError(f"unable to resolve final BPMN XML path for final_backend={final_backend!r}")


def _derive_build_timestamp(manifest):
    stable_fallback = "not-provided"
    build_version = str(manifest.get("build_version") or "").strip()
    if build_version and build_version.lower() != "unknown":
        return stable_fallback
    return stable_fallback


def _build_manifest_summary(manifest):
    layout_summary = manifest.get("layout_summary") or {}
    return {
        "requested_mode": manifest.get("requested_mode"),
        "initial_backend": manifest.get("initial_backend"),
        "final_backend": manifest.get("final_backend"),
        "fallback_happened": manifest.get("fallback_happened"),
        "fallback_reason_code": manifest.get("fallback_reason_code"),
        "semantic_status": manifest.get("semantic_status"),
        "layout_status": manifest.get("layout_status"),
        "layout_final_mode": layout_summary.get("final_mode", "unknown"),
        "layout_policy_status": layout_summary.get("layout_policy_status", "UNKNOWN"),
        "layout_requires_decomposition": bool(layout_summary.get("layout_requires_decomposition", False)),
        "advisory_only": bool(layout_summary.get("advisory_only", False)),
        "preview_status": manifest.get("preview_status"),
        "scenario_id": manifest.get("scenario_id"),
        "fixture_id": manifest.get("fixture_id"),
        "traceability_count": manifest.get("traceability_count"),
        "assumptions_count": manifest.get("assumptions_count"),
    }


def _build_metadata_summary(manifest, typed_issue_targets, bpmn_counts):
    layout_summary = manifest.get("layout_summary") or {}
    typed_issue_target_count = int(typed_issue_targets.get("counts", {}).get("total", 0))
    typed_issue_count = int(layout_summary.get("typed_issue_count", typed_issue_target_count))
    return {
        "build_version": str(manifest.get("build_version") or "unknown"),
        "skill_version": str(manifest.get("skill_version") or "unknown"),
        "runtime_target": str(manifest.get("runtime_target") or "unknown"),
        "manifest_schema_version": str(manifest.get("manifest_schema_version") or "unknown"),
        "linked_report_schema_version": str(manifest.get("linked_report_schema_version") or "unknown"),
        "scenario_id": manifest.get("scenario_id") or "n/a",
        "fixture_id": manifest.get("fixture_id") or "n/a",
        "traceability_count": int(manifest.get("traceability_count", 0)),
        "assumptions_count": int(manifest.get("assumptions_count", 0)),
        "fallback_reason_code": manifest.get("fallback_reason_code") or "none",
        "typed_issue_count": typed_issue_count,
        "typed_issue_target_count": typed_issue_target_count,
        "warning_issue_count": int(layout_summary.get("warning_issue_count", 0)),
        "error_issue_count": int(layout_summary.get("error_issue_count", 0)),
        "layout_final_mode": str(layout_summary.get("final_mode") or "unknown"),
        "layout_profile_family": str(layout_summary.get("layout_profile_family") or "unknown"),
        "advisory_only": bool(layout_summary.get("advisory_only", False)),
        "layout_requires_decomposition": bool(layout_summary.get("layout_requires_decomposition", False)),
        "diagram_width_px": int(layout_summary.get("diagram_width_px", 0)),
        "diagram_height_px": int(layout_summary.get("diagram_height_px", 0)),
        "aspect_ratio_x100": int(layout_summary.get("aspect_ratio_x100", 0)),
        "max_depth_columns": int(layout_summary.get("max_depth_columns", 0)),
        "max_edge_span_columns": int(layout_summary.get("max_edge_span_columns", 0)),
        "consecutive_gateway_chain_length": int(layout_summary.get("consecutive_gateway_chain_length", 0)),
        "readability_violations": int(layout_summary.get("readability_violations", 0)),
        "sequence_flow_count": int(bpmn_counts.get("sequence_flow_count", 0)),
        "bpmn_edge_count": int(bpmn_counts.get("bpmn_edge_count", 0)),
        "bpmn_shape_count": int(bpmn_counts.get("bpmn_shape_count", 0)),
        "highlight_policy_phase": typed_issue_targets.get("highlight_policy", {}).get("phase", "deferred_phase_5"),
    }


def _first_lines(text, limit):
    lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    return lines[:limit]


def _build_report_summary(manifest, semantic_report, human_summary_text, layout_report_text, bpmn_counts, typed_issue_targets):
    layout_summary = manifest.get("layout_summary") or {}
    lines = [
        f"semantic_status: {manifest.get('semantic_status')}",
        f"layout_status: {manifest.get('layout_status')}",
        f"layout_policy_status: {layout_summary.get('layout_policy_status', 'UNKNOWN')}",
        f"layout_final_mode: {layout_summary.get('final_mode', 'unknown')}",
        f"advisory_only: {str(bool(layout_summary.get('advisory_only', False))).lower()}",
        f"layout_requires_decomposition: {str(bool(layout_summary.get('layout_requires_decomposition', False))).lower()}",
        f"diagram_width_px: {int(layout_summary.get('diagram_width_px', 0))}",
        f"diagram_height_px: {int(layout_summary.get('diagram_height_px', 0))}",
        f"aspect_ratio_x100: {int(layout_summary.get('aspect_ratio_x100', 0))}",
        f"max_depth_columns: {int(layout_summary.get('max_depth_columns', 0))}",
        f"max_edge_span_columns: {int(layout_summary.get('max_edge_span_columns', 0))}",
        f"consecutive_gateway_chain_length: {int(layout_summary.get('consecutive_gateway_chain_length', 0))}",
        f"readability_violations: {int(layout_summary.get('readability_violations', 0))}",
        f"preview_status: {manifest.get('preview_status')}",
        f"sequence_flow_count: {int(bpmn_counts.get('sequence_flow_count', 0))}",
        f"bpmn_edge_count: {int(bpmn_counts.get('bpmn_edge_count', 0))}",
        f"bpmn_shape_count: {int(bpmn_counts.get('bpmn_shape_count', 0))}",
        f"typed_issue_target_count: {int(typed_issue_targets.get('counts', {}).get('total', 0))}",
        f"warning_issue_count: {int(layout_summary.get('warning_issue_count', 0))}",
        f"error_issue_count: {int(layout_summary.get('error_issue_count', 0))}",
        f"semantic_errors: {len(semantic_report.get('errors', []))}",
        f"semantic_warnings: {len(semantic_report.get('warnings', []))}",
    ]
    for error in semantic_report.get("errors", [])[:3]:
        lines.append(f"error: {error}")
    for warning in semantic_report.get("warnings", [])[:3]:
        lines.append(f"warning: {warning}")
    if layout_report_text:
        lines.append("layout_report_excerpt:")
        lines.extend(f"  {line}" for line in _first_lines(layout_report_text, 6))
    if human_summary_text:
        lines.append("human_summary_excerpt:")
        lines.extend(f"  {line}" for line in _first_lines(human_summary_text, 6))
    return {
        "text": "\n".join(lines),
        "semantic_errors": semantic_report.get("errors", []),
        "semantic_warnings": semantic_report.get("warnings", []),
    }


def _build_preview_report_payload(
    manifest,
    output_dir,
    build_timestamp,
    final_bpmn_hash,
    typed_issue_targets,
    audit_result,
    bpmn_counts,
):
    layout_summary = manifest.get("layout_summary") or {}
    return {
        "schema_version": PREVIEW_SCHEMA_VERSION,
        "status": "PASS",
        "build_timestamp": build_timestamp,
        "manifest_schema_version": str(manifest.get("manifest_schema_version") or ""),
        "linked_report_schema_version": str(manifest.get("linked_report_schema_version") or ""),
        "final_backend": str(manifest.get("final_backend") or ""),
        "final_bpmn_hash": final_bpmn_hash,
        "preview_import_ok": True,
        "layout_policy_status": str(layout_summary.get("layout_policy_status") or "UNKNOWN"),
        "layout_final_mode": str(layout_summary.get("final_mode") or "unknown"),
        "advisory_only": bool(layout_summary.get("advisory_only", False)),
        "layout_requires_decomposition": bool(layout_summary.get("layout_requires_decomposition", False)),
        "warning_issue_count": int(layout_summary.get("warning_issue_count", 0)),
        "error_issue_count": int(layout_summary.get("error_issue_count", 0)),
        "diagram_width_px": int(layout_summary.get("diagram_width_px", 0)),
        "diagram_height_px": int(layout_summary.get("diagram_height_px", 0)),
        "aspect_ratio_x100": int(layout_summary.get("aspect_ratio_x100", 0)),
        "max_depth_columns": int(layout_summary.get("max_depth_columns", 0)),
        "max_edge_span_columns": int(layout_summary.get("max_edge_span_columns", 0)),
        "consecutive_gateway_chain_length": int(layout_summary.get("consecutive_gateway_chain_length", 0)),
        "readability_violations": int(layout_summary.get("readability_violations", 0)),
        "sequence_flow_count": int(bpmn_counts.get("sequence_flow_count", 0)),
        "bpmn_shape_count": int(bpmn_counts.get("bpmn_shape_count", 0)),
        "bpmn_edge_count": int(bpmn_counts.get("bpmn_edge_count", 0)),
        "typed_issue_target_count": int(typed_issue_targets.get("counts", {}).get("total", 0)),
        "preview_output_dir": str(Path(output_dir)),
        "index_path": str(Path(output_dir) / "index.html"),
        "assets_dir": str(Path(output_dir) / "assets"),
        "typed_issue_targets": {
            "path": TYPED_ISSUE_TARGETS_PATH,
            "count": int(typed_issue_targets.get("counts", {}).get("total", 0)),
            "schema_version": TYPED_ISSUE_TARGETS_SCHEMA_VERSION,
        },
        "audit": audit_result,
    }


def _copy_runtime_assets(output_dir):
    assets_out = Path(output_dir) / "assets"
    if assets_out.exists():
        shutil.rmtree(assets_out)
    shutil.copytree(PREVIEW_ASSETS_DIR, assets_out)
    return assets_out


def _build_index_html(xml_text, manifest_summary, metadata_summary, report_summary, typed_issue_targets, version_info):
    return f"""<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>BPMN Offline Preview</title>
    <link rel=\"stylesheet\" href=\"assets/vendor/diagram-js.css\" />
    <link rel=\"stylesheet\" href=\"assets/vendor/bpmn-embedded.css\" />
    <link rel=\"stylesheet\" href=\"assets/preview-app.css\" />
  </head>
  <body>
    <div class=\"preview-shell\">
      <aside class=\"sidebar\">
        <section class=\"brand-block\">
          <div class=\"kicker\">Offline Preview MVP</div>
          <h1 class=\"title\">Camunda BPMN Preview</h1>
          <p class=\"subtitle\">Viewer-only bundle assembled from <code>run_manifest.json</code> and linked artifacts. No CDN references. No runtime network fetch.</p>
        </section>

        <section class=\"version-stamp\" id=\"version-stamp\" data-testid=\"version-stamp\">
          <div><strong>skill_version</strong>: {html.escape(version_info['skill_version'])}</div>
          <div><strong>preview_schema_version</strong>: {html.escape(version_info['preview_schema_version'])}</div>
          <div><strong>build_timestamp</strong>: {html.escape(version_info['build_timestamp'])}</div>
        </section>

        <section class=\"panel-section\">
          <h2>Controls</h2>
          <div class=\"controls-grid\">
            <button id=\"pan-up\" data-testid=\"pan-up\">Pan Up</button>
            <button id=\"zoom-reset\" data-testid=\"zoom-reset\">Reset</button>
            <button id=\"zoom-in\" data-testid=\"zoom-in\">Zoom In</button>
            <button id=\"pan-left\" data-testid=\"pan-left\">Pan Left</button>
            <button id=\"pan-down\" data-testid=\"pan-down\">Pan Down</button>
            <button id=\"zoom-out\" data-testid=\"zoom-out\">Zoom Out</button>
          </div>
          <div class=\"control-strip\">
            <button id=\"pan-right\" data-testid=\"pan-right\">Pan Right</button>
          </div>
        </section>

        <section class=\"panel-section\">
          <h2>Manifest Summary</h2>
          <dl class=\"key-grid\">
            <div class=\"key-card\"><dt>Requested Mode</dt><dd id=\"manifest-requested-mode\"></dd></div>
            <div class=\"key-card\"><dt>Final Backend</dt><dd id=\"manifest-final-backend\"></dd></div>
            <div class=\"key-card\"><dt>Fallback</dt><dd id=\"manifest-fallback\"></dd></div>
            <div class=\"key-card\"><dt>Semantic</dt><dd id=\"manifest-semantic-status\"></dd></div>
            <div class=\"key-card\"><dt>Layout</dt><dd id=\"manifest-layout-status\"></dd></div>
            <div class=\"key-card\"><dt>Preview</dt><dd id=\"manifest-preview-status\"></dd></div>
            <div class=\"key-card\"><dt>Scenario</dt><dd id=\"manifest-scenario-id\"></dd></div>
            <div class=\"key-card\"><dt>Fixture</dt><dd id=\"manifest-fixture-id\"></dd></div>
          </dl>
        </section>

        <section class=\"panel-section\">
          <h2>Metadata Summary</h2>
          <div id=\"metadata-summary\" class=\"metadata-summary\" data-testid=\"metadata-summary\"></div>
        </section>

        <section class=\"panel-section\">
          <h2>Typed Issue Targets</h2>
          <div id=\"typed-issue-summary\" class=\"typed-issue-summary\" data-testid=\"typed-issue-summary\"></div>
        </section>

        <section class=\"panel-section\">
          <h2>Report Summary</h2>
          <div id=\"report-summary\" class=\"report-summary\" data-testid=\"report-summary\"></div>
        </section>
      </aside>

      <main class=\"viewer-panel\">
        <div class=\"viewer-toolbar\">
          <h2 data-testid=\"viewer-mode\">Viewer Only</h2>
          <div id=\"zoom-indicator\" class=\"zoom-indicator\" data-testid=\"zoom-indicator\">100%</div>
        </div>
        <div class=\"canvas-shell\">
          <div id=\"preview-error\" class=\"error-banner\" data-testid=\"preview-error\"></div>
          <div id=\"preview-canvas\" data-testid=\"preview-canvas\"></div>
        </div>
      </main>
    </div>

    <script id=\"preview-bpmn-xml\" type=\"application/xml\">{html.escape(xml_text)}</script>
    <script id=\"preview-manifest-summary\" type=\"application/json\">{html.escape(json.dumps(manifest_summary, indent=2, sort_keys=True))}</script>
    <script id=\"preview-metadata-summary\" type=\"application/json\">{html.escape(json.dumps(metadata_summary, indent=2, sort_keys=True))}</script>
    <script id=\"preview-report-summary\" type=\"application/json\">{html.escape(json.dumps(report_summary, indent=2, sort_keys=True))}</script>
    <script id=\"preview-typed-issue-targets\" type=\"application/json\">{html.escape(json.dumps(typed_issue_targets, indent=2, sort_keys=True))}</script>
    <script id=\"preview-version-info\" type=\"application/json\">{html.escape(json.dumps(version_info, indent=2, sort_keys=True))}</script>
    <script src=\"assets/vendor/bpmn-viewer.production.min.js\"></script>
    <script src=\"assets/preview-app.js\"></script>
  </body>
</html>
"""


def audit_preview_runtime(output_dir):
    target = Path(output_dir)
    command = [
        "node",
        str(NODE_TOOLING_DIR / "preview_builder.js"),
        "audit-runtime",
        str(target),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError("preview runtime audit failed: " + stderr)
    return json.loads(completed.stdout)


def build_preview_artifacts(manifest_path, output_dir=None):
    manifest_path = Path(manifest_path).resolve()
    _assert_manifest_valid(manifest_path)
    manifest = _load_json(manifest_path)

    if not PREVIEW_ASSETS_DIR.exists():
        raise RuntimeError(f"preview assets directory is missing: {PREVIEW_ASSETS_DIR}")

    for key in REQUIRED_ARTIFACTS:
        _require_present_artifact(manifest, manifest_path, key)

    backend_selection_path = _require_present_artifact(manifest, manifest_path, "backend_selection")
    semantic_report_path = _require_present_artifact(manifest, manifest_path, "semantic_report")
    human_summary_path = _require_present_artifact(manifest, manifest_path, "human_summary")
    final_bpmn_path, final_bpmn_hash = _resolve_final_bpmn_path(manifest, backend_selection_path)
    if not final_bpmn_path.exists():
        raise RuntimeError(f"final BPMN XML path does not exist: {final_bpmn_path}")

    semantic_report = _load_json(semantic_report_path)
    human_summary_text = human_summary_path.read_text(encoding="utf-8")
    layout_report_text = _resolve_optional_text(manifest, manifest_path, "layout_report")
    xml_text = final_bpmn_path.read_text(encoding="utf-8")
    bpmn_counts = _extract_bpmn_graph_counts(xml_text)

    typed_issue_targets = _build_typed_issue_targets_payload(manifest, layout_report_text)
    _validate_typed_issue_targets_payload(typed_issue_targets)
    manifest_summary = _build_manifest_summary(manifest)
    metadata_summary = _build_metadata_summary(manifest, typed_issue_targets, bpmn_counts)
    report_summary = _build_report_summary(
        manifest,
        semantic_report,
        human_summary_text,
        layout_report_text,
        bpmn_counts,
        typed_issue_targets,
    )
    build_timestamp = _derive_build_timestamp(manifest)
    version_info = {
        "skill_version": manifest.get("skill_version") or "unknown",
        "preview_schema_version": PREVIEW_SCHEMA_VERSION,
        "build_timestamp": build_timestamp,
        "final_bpmn_hash": final_bpmn_hash,
    }

    output_dir = Path(output_dir) if output_dir else manifest_path.parent / DEFAULT_OUTPUT_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    typed_issue_targets_out = output_dir / TYPED_ISSUE_TARGETS_PATH
    _write_json(typed_issue_targets_out, typed_issue_targets)
    canonical_typed_issue_targets_path = manifest_path.parent / TYPED_ISSUE_TARGETS_PATH
    _write_json(canonical_typed_issue_targets_path, typed_issue_targets)
    _copy_runtime_assets(output_dir)
    index_html = _build_index_html(
        xml_text,
        manifest_summary,
        metadata_summary,
        report_summary,
        typed_issue_targets,
        version_info,
    )
    index_path = output_dir / "index.html"
    _write_text(index_path, index_html)

    audit_result = audit_preview_runtime(output_dir)
    preview_report_payload = _build_preview_report_payload(
        manifest,
        output_dir,
        build_timestamp,
        final_bpmn_hash,
        typed_issue_targets,
        audit_result,
        bpmn_counts,
    )
    preview_report_path = manifest_path.parent / PREVIEW_REPORT_PATH
    _write_json(preview_report_path, preview_report_payload)
    return {
        "ok": True,
        "preview_schema_version": PREVIEW_SCHEMA_VERSION,
        "build_timestamp": build_timestamp,
        "index_path": str(index_path),
        "assets_dir": str(output_dir / "assets"),
        "preview_report_path": str(preview_report_path),
        "typed_issue_targets_path": str(canonical_typed_issue_targets_path),
        "typed_issue_target_count": int(typed_issue_targets.get("counts", {}).get("total", 0)),
        "preview_import_ok": True,
        "audit": audit_result,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build offline preview artifacts from run_manifest.json")
    parser.add_argument("manifest", help="Path to run_manifest.json")
    parser.add_argument("--output-dir", help="Directory to write index.html and assets/")
    args = parser.parse_args(argv)

    result = build_preview_artifacts(args.manifest, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
