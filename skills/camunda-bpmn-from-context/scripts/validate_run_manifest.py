#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


SCHEMA_NAME = "run_manifest.schema.json"
LINKED_REPORT_SCHEMA_NAME = "linked_report.schema.json"

ARTIFACT_BACKEND_SELECTION = "backend_selection"
ARTIFACT_SEMANTIC_REPORT = "semantic_report"
ARTIFACT_LAYOUT_REPORT = "layout_report"
ARTIFACT_PREVIEW_REPORT = "preview_report"
ARTIFACT_HUMAN_SUMMARY = "human_summary"
ARTIFACT_TYPED_ISSUE_TARGETS = "typed_issue_targets"

REQUIRED_PRESENT_ARTIFACTS = (
    ARTIFACT_BACKEND_SELECTION,
    ARTIFACT_SEMANTIC_REPORT,
    ARTIFACT_HUMAN_SUMMARY,
)

STATUS_FIELD_BY_ARTIFACT = {
    ARTIFACT_SEMANTIC_REPORT: "semantic_status",
    ARTIFACT_LAYOUT_REPORT: "layout_status",
    ARTIFACT_PREVIEW_REPORT: "preview_status",
}

CANONICAL_ARTIFACT_PATHS = {
    ARTIFACT_BACKEND_SELECTION: "backend_selection.json",
    ARTIFACT_SEMANTIC_REPORT: "semantic_report.json",
    ARTIFACT_LAYOUT_REPORT: "layout_report.md",
    ARTIFACT_PREVIEW_REPORT: "preview_report.json",
    ARTIFACT_HUMAN_SUMMARY: "human_summary.md",
    ARTIFACT_TYPED_ISSUE_TARGETS: "typed_issue_targets.json",
}

SUPPORTED_MANIFEST_SCHEMA_VERSIONS = {"2"}
SUPPORTED_LINKED_REPORT_SCHEMA_VERSIONS = {"2"}
ALLOWED_LAYOUT_PROFILE_FAMILIES = {"native", "simple_postprocess", "none"}


def load_json(path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def unescape_json_pointer(token):
    return token.replace("~1", "/").replace("~0", "~")


def resolve_ref(root_schema, ref):
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported $ref: {ref}")
    node = root_schema
    for part in ref[2:].split("/"):
        node = node[unescape_json_pointer(part)]
    return node


def type_matches(instance, schema_type):
    if schema_type == "object":
        return isinstance(instance, dict)
    if schema_type == "array":
        return isinstance(instance, list)
    if schema_type == "string":
        return isinstance(instance, str)
    if schema_type == "boolean":
        return isinstance(instance, bool)
    if schema_type == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if schema_type == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if schema_type == "null":
        return instance is None
    return False


def validate_instance(instance, schema, root_schema=None, path="$"):
    if root_schema is None:
        root_schema = schema

    if "$ref" in schema:
        return validate_instance(instance, resolve_ref(root_schema, schema["$ref"]), root_schema, path)

    errors = []

    schema_type = schema.get("type")
    if schema_type is not None:
        if isinstance(schema_type, list):
            if not any(type_matches(instance, item) for item in schema_type):
                errors.append(f"{path}: expected type {schema_type}, got {type(instance).__name__}")
                return errors
        elif not type_matches(instance, schema_type):
            errors.append(f"{path}: expected type {schema_type}, got {type(instance).__name__}")
            return errors

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
        return errors

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']!r}, got {instance!r}")
        return errors

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: string shorter than minimum length {schema['minLength']}")
        if "pattern" in schema and re.fullmatch(schema["pattern"], instance) is None:
            errors.append(f"{path}: value {instance!r} does not match pattern {schema['pattern']!r}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: array shorter than minimum length {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: array longer than maximum length {schema['maxItems']}")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(instance):
                errors.extend(validate_instance(item, item_schema, root_schema, f"{path}[{index}]"))

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                errors.append(f"{path}: missing required property {key!r}")
        for key, value in instance.items():
            if key in properties:
                errors.extend(validate_instance(value, properties[key], root_schema, f"{path}.{key}"))
            elif schema.get("additionalProperties", True) is False:
                errors.append(f"{path}: unexpected property {key!r}")

    if "allOf" in schema:
        for index, sub_schema in enumerate(schema["allOf"]):
            errors.extend(validate_instance(instance, sub_schema, root_schema, f"{path}.allOf[{index}]"))

    if "anyOf" in schema:
        matches = 0
        branch_errors = []
        for sub_schema in schema["anyOf"]:
            sub_errors = validate_instance(instance, sub_schema, root_schema, path)
            if not sub_errors:
                matches += 1
            else:
                branch_errors.append(sub_errors)
        if matches == 0:
            errors.append(f"{path}: did not match any anyOf branch")

    if "oneOf" in schema:
        matches = 0
        for sub_schema in schema["oneOf"]:
            if not validate_instance(instance, sub_schema, root_schema, path):
                matches += 1
        if matches != 1:
            errors.append(f"{path}: expected exactly one matching oneOf branch, got {matches}")

    if "not" in schema and not validate_instance(instance, schema["not"], root_schema, path):
        errors.append(f"{path}: matched forbidden schema")

    return errors


def load_schema(schema_dir):
    return load_json(schema_dir / SCHEMA_NAME)


def load_linked_report_schema(schema_dir):
    return load_json(Path(schema_dir) / LINKED_REPORT_SCHEMA_NAME)


def _validate_artifact_record(record, artifact_key, linked_schema):
    errors = validate_instance(record, linked_schema, linked_schema, f"$.artifacts.{artifact_key}")
    if not isinstance(record, dict):
        return errors

    report_kind = record.get("report_kind")
    if report_kind != artifact_key:
        errors.append(f"$.artifacts.{artifact_key}.report_kind must equal {artifact_key!r}")

    if record.get("presence") == "present":
        path = record.get("path")
        expected_name = CANONICAL_ARTIFACT_PATHS.get(artifact_key)
        if not isinstance(path, str) or not path.strip():
            errors.append(f"$.artifacts.{artifact_key}.path must be a non-empty string when presence is present")
        elif expected_name and Path(path).name != expected_name:
            errors.append(
                f"$.artifacts.{artifact_key}.path must use canonical filename {expected_name!r}"
            )
    elif record.get("status") != "SKIPPED":
        errors.append(f"$.artifacts.{artifact_key}.status must be SKIPPED when presence is not present")
    return errors


def validate_manifest_data(manifest, schema, linked_schema=None):
    errors = validate_instance(manifest, schema)
    if linked_schema is None:
        schema_dir = Path(__file__).resolve().parent.parent / "schemas"
        linked_schema = load_linked_report_schema(schema_dir)

    logic_only = manifest.get("logic_only")
    layout_bypass = manifest.get("layout_bypass", False)
    layout_status = manifest.get("layout_status")
    layout_summary = manifest.get("layout_summary")
    preview_summary = manifest.get("preview_summary")
    layout_hint_source = manifest.get("layout_hint_source")
    hint_applied = manifest.get("hint_applied")
    initial_backend = manifest.get("initial_backend")
    final_backend = manifest.get("final_backend")

    if layout_status == "SKIPPED" and not (logic_only or layout_bypass):
        errors.append("layout_status SKIPPED requires logic_only=true or layout_bypass=true")
    if layout_bypass and layout_status != "SKIPPED":
        errors.append("layout_bypass=true requires layout_status=SKIPPED")
    if layout_hint_source in (None, ""):
        errors.append("layout_hint_source is required")
    if hint_applied and layout_hint_source in (None, "", "none"):
        errors.append("hint_applied=true requires layout_hint_source to identify a hint payload")
    if layout_status == "SKIPPED" and hint_applied:
        errors.append("hint_applied=true is not allowed when layout_status=SKIPPED")

    if not isinstance(layout_summary, dict):
        errors.append("layout_summary is required and must be an object")
    else:
        summary_final_status = layout_summary.get("final_status")
        summary_policy_status = layout_summary.get("layout_policy_status")
        typed_issue_count = layout_summary.get("typed_issue_count")
        warning_issue_count = layout_summary.get("warning_issue_count")
        error_issue_count = layout_summary.get("error_issue_count")
        advisory_only = layout_summary.get("advisory_only")
        diagram_width_px = layout_summary.get("diagram_width_px")
        diagram_height_px = layout_summary.get("diagram_height_px")
        aspect_ratio_x100 = layout_summary.get("aspect_ratio_x100")
        max_depth_columns = layout_summary.get("max_depth_columns")
        max_edge_span_columns = layout_summary.get("max_edge_span_columns")
        consecutive_gateway_chain_length = layout_summary.get("consecutive_gateway_chain_length")
        readability_violations = layout_summary.get("readability_violations")
        layout_requires_decomposition = layout_summary.get("layout_requires_decomposition")

        if layout_status in {"PASS", "FAIL"} and summary_final_status != layout_status:
            errors.append(
                "layout_summary.final_status must match layout_status when layout_status is PASS/FAIL"
            )
        if layout_status == "SKIPPED" and summary_final_status != "SKIPPED":
            errors.append(
                "layout_summary.final_status must be SKIPPED when layout_status=SKIPPED"
            )
        if layout_status in {"PASS", "FAIL"} and summary_policy_status not in {"PASS", "FAIL"}:
            errors.append(
                "layout_summary.layout_policy_status must be PASS/FAIL when layout_status is PASS/FAIL"
            )
        if (
            isinstance(typed_issue_count, int)
            and isinstance(warning_issue_count, int)
            and isinstance(error_issue_count, int)
            and warning_issue_count + error_issue_count > typed_issue_count
        ):
            errors.append(
                "layout_summary warning/error issue counts must not exceed typed_issue_count"
            )
        profile_family = layout_summary.get("layout_profile_family")
        if profile_family not in ALLOWED_LAYOUT_PROFILE_FAMILIES:
            errors.append(
                "layout_summary.layout_profile_family must be one of "
                f"{sorted(ALLOWED_LAYOUT_PROFILE_FAMILIES)!r}"
            )
        optional_non_negative = {
            "diagram_width_px": diagram_width_px,
            "diagram_height_px": diagram_height_px,
            "aspect_ratio_x100": aspect_ratio_x100,
            "max_depth_columns": max_depth_columns,
            "max_edge_span_columns": max_edge_span_columns,
            "consecutive_gateway_chain_length": consecutive_gateway_chain_length,
            "readability_violations": readability_violations,
        }
        for field, value in optional_non_negative.items():
            if value is None:
                continue
            if not isinstance(value, int) or value < 0:
                errors.append(f"layout_summary.{field} must be an integer >= 0 when present")
        if layout_requires_decomposition is not None and not isinstance(layout_requires_decomposition, bool):
            errors.append("layout_summary.layout_requires_decomposition must be boolean when present")
        if (
            layout_requires_decomposition is True
            and isinstance(readability_violations, int)
            and readability_violations <= 0
        ):
            errors.append(
                "layout_summary.layout_requires_decomposition=true requires readability_violations>0"
            )
        if advisory_only:
            if layout_status != "PASS":
                errors.append("layout_summary.advisory_only=true requires layout_status=PASS")
            if isinstance(error_issue_count, int) and error_issue_count != 0:
                errors.append("layout_summary.advisory_only=true requires error_issue_count=0")
            if isinstance(typed_issue_count, int) and typed_issue_count <= 0:
                errors.append("layout_summary.advisory_only=true requires typed_issue_count>0")

    if preview_summary is not None:
        if not isinstance(preview_summary, dict):
            errors.append("preview_summary must be an object when present")
        elif manifest.get("preview_status") == "PASS":
            typed_issue_count = manifest.get("layout_summary", {}).get("typed_issue_count")
            typed_issue_target_count = preview_summary.get("typed_issue_target_count")
            if isinstance(typed_issue_count, int) and isinstance(typed_issue_target_count, int):
                if typed_issue_target_count < 0:
                    errors.append("preview_summary.typed_issue_target_count must be >= 0")

    if initial_backend == "none" and not logic_only:
        errors.append("initial_backend=none is allowed only when logic_only=true")
    if final_backend == "none" and not logic_only:
        errors.append("final_backend=none is allowed only when logic_only=true")

    if manifest.get("fallback_happened"):
        reason = manifest.get("fallback_reason_code")
        if not reason:
            errors.append("fallback_reason_code is required when fallback_happened=true")
    elif "fallback_reason_code" in manifest and manifest.get("fallback_reason_code") not in (None, ""):
        errors.append("fallback_reason_code must be omitted or empty when fallback_happened=false")

    manifest_schema_version = manifest.get("manifest_schema_version")
    linked_report_schema_version = manifest.get("linked_report_schema_version")
    if not manifest_schema_version:
        errors.append("manifest_schema_version is required")
    elif manifest_schema_version not in SUPPORTED_MANIFEST_SCHEMA_VERSIONS:
        errors.append(
            f"unsupported manifest_schema_version {manifest_schema_version!r}; supported versions: {sorted(SUPPORTED_MANIFEST_SCHEMA_VERSIONS)!r}"
        )
    if not linked_report_schema_version:
        errors.append("linked_report_schema_version is required")
    elif linked_report_schema_version not in SUPPORTED_LINKED_REPORT_SCHEMA_VERSIONS:
        errors.append(
            f"unsupported linked_report_schema_version {linked_report_schema_version!r}; supported versions: {sorted(SUPPORTED_LINKED_REPORT_SCHEMA_VERSIONS)!r}"
        )

    artifacts = manifest.get("artifacts", {})
    for key in REQUIRED_PRESENT_ARTIFACTS:
        record = artifacts.get(key)
        if not isinstance(record, dict) or record.get("presence") != "present":
            errors.append(f"artifacts.{key} must be present")

    for artifact_key, record in artifacts.items():
        errors.extend(_validate_artifact_record(record, artifact_key, linked_schema))
        if (
            linked_report_schema_version
            and isinstance(record, dict)
            and record.get("schema_version") != linked_report_schema_version
        ):
            errors.append(
                f"artifacts.{artifact_key}.schema_version must match linked_report_schema_version"
            )

    if final_backend == "none" and layout_status != "SKIPPED":
        errors.append("final_backend=none requires layout_status=SKIPPED")
    if final_backend == "none" and manifest.get("preview_status") != "SKIPPED":
        errors.append("final_backend=none requires preview_status=SKIPPED")

    fallback_happened = bool(manifest.get("fallback_happened"))
    backend_pair = (initial_backend, final_backend)
    allowed_backend_pairs = {
        ("none", "none"),
        ("native", "native"),
        ("simple", "simple"),
        ("simple", "native"),
    }
    if initial_backend is not None and final_backend is not None and backend_pair not in allowed_backend_pairs:
        errors.append(
            f"unsupported backend transition {initial_backend!r}->{final_backend!r} for the current pipeline contract"
        )

    if fallback_happened:
        if logic_only:
            errors.append("fallback_happened=true is not allowed when logic_only=true")
        reason = str(manifest.get("fallback_reason_code") or "").strip()
        if backend_pair == ("native", "native"):
            if reason != "native_preserve_degraded_to_greenfield":
                errors.append(
                    "fallback_happened=true with initial_backend=native and final_backend=native "
                    "requires fallback_reason_code='native_preserve_degraded_to_greenfield'"
                )
        elif backend_pair != ("simple", "native"):
            errors.append(
                "fallback_happened=true requires either initial_backend=simple and final_backend=native, "
                "or native->native with fallback_reason_code='native_preserve_degraded_to_greenfield'"
            )
    else:
        if initial_backend != final_backend:
            errors.append("fallback_happened=false requires initial_backend and final_backend to match")

    for artifact_key, status_field in STATUS_FIELD_BY_ARTIFACT.items():
        record = artifacts.get(artifact_key)
        if not isinstance(record, dict):
            continue
        manifest_status = manifest.get(status_field)
        if record.get("presence") == "present":
            if record.get("status") != manifest_status:
                errors.append(
                    f"artifacts.{artifact_key}.status must match {status_field} when present"
                )
        elif manifest_status != "SKIPPED":
            errors.append(
                f"artifacts.{artifact_key} must be present when {status_field} is {manifest_status}"
            )

    backend_selection = artifacts.get(ARTIFACT_BACKEND_SELECTION)
    if isinstance(backend_selection, dict) and backend_selection.get("presence") == "present":
        expected_status = "FAIL" if "FAIL" in (
            manifest.get("semantic_status"),
            manifest.get("layout_status"),
            manifest.get("preview_status"),
        ) else "PASS"
        if backend_selection.get("status") != expected_status:
            errors.append("artifacts.backend_selection.status must reflect terminal pipeline outcome")

    human_summary = artifacts.get(ARTIFACT_HUMAN_SUMMARY)
    if isinstance(human_summary, dict) and human_summary.get("presence") == "present":
        expected_summary_status = "PASS" if backend_selection and backend_selection.get("status") == "PASS" else "FAIL"
        if human_summary.get("status") != expected_summary_status:
            errors.append("artifacts.human_summary.status must match backend_selection.status")

    typed_issue_targets = artifacts.get(ARTIFACT_TYPED_ISSUE_TARGETS)
    if isinstance(typed_issue_targets, dict) and typed_issue_targets.get("presence") == "present":
        if Path(typed_issue_targets.get("path", "")).name != CANONICAL_ARTIFACT_PATHS[ARTIFACT_TYPED_ISSUE_TARGETS]:
            errors.append("artifacts.typed_issue_targets.path must use canonical filename 'typed_issue_targets.json'")

    for count_field in ("traceability_count", "assumptions_count"):
        value = manifest.get(count_field)
        if isinstance(value, int) and value < 0:
            errors.append(f"{count_field} must be >= 0")

    return errors


def validate_manifest_file(manifest_path, schema_dir=None):
    manifest_path = Path(manifest_path)
    schema_dir = Path(schema_dir) if schema_dir is not None else Path(__file__).resolve().parent.parent / "schemas"
    try:
        manifest = load_json(manifest_path)
    except FileNotFoundError as exc:
        return [f"{manifest_path}: file not found ({exc})"]
    except json.JSONDecodeError as exc:
        return [f"{manifest_path}: invalid JSON ({exc.msg} at line {exc.lineno}, column {exc.colno})"]
    except OSError as exc:
        return [f"{manifest_path}: unable to read file ({exc})"]
    try:
        schema = load_schema(schema_dir)
    except FileNotFoundError as exc:
        return [f"{schema_dir / SCHEMA_NAME}: file not found ({exc})"]
    except json.JSONDecodeError as exc:
        return [f"{schema_dir / SCHEMA_NAME}: invalid schema JSON ({exc.msg} at line {exc.lineno}, column {exc.colno})"]
    except OSError as exc:
        return [f"{schema_dir / SCHEMA_NAME}: unable to read file ({exc})"]
    try:
        linked_schema = load_linked_report_schema(schema_dir)
    except FileNotFoundError as exc:
        return [f"{schema_dir / LINKED_REPORT_SCHEMA_NAME}: file not found ({exc})"]
    except json.JSONDecodeError as exc:
        return [f"{schema_dir / LINKED_REPORT_SCHEMA_NAME}: invalid schema JSON ({exc.msg} at line {exc.lineno}, column {exc.colno})"]
    except OSError as exc:
        return [f"{schema_dir / LINKED_REPORT_SCHEMA_NAME}: unable to read file ({exc})"]
    return validate_manifest_data(manifest, schema, linked_schema=linked_schema)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate run_manifest.json against the package contract.")
    parser.add_argument("manifest", help="Path to run_manifest.json")
    parser.add_argument("--schema-dir", help="Directory that contains the schema files")
    args = parser.parse_args(argv)

    errors = validate_manifest_file(args.manifest, args.schema_dir)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print("run_manifest validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
