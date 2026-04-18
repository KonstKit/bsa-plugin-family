#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent / "validate_run_manifest.py"
SPEC = importlib.util.spec_from_file_location("validate_run_manifest", SCRIPT_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
LINKED_SCHEMA_PATH = SCHEMA_DIR / "linked_report.schema.json"


HASHES = {
    "backend_selection": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "semantic_report": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "layout_report": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "preview_report": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "human_summary": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "typed_issue_targets": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
}

CANONICAL_PATHS = {
    "backend_selection": "backend_selection.json",
    "semantic_report": "semantic_report.json",
    "layout_report": "layout_report.md",
    "preview_report": "preview_report.json",
    "human_summary": "human_summary.md",
    "typed_issue_targets": "typed_issue_targets.json",
}


def linked_artifact(report_kind, presence="present", status="PASS", path=None, schema_version="2"):
    record = {
        "report_kind": report_kind,
        "presence": presence,
        "status": status,
        "schema_version": schema_version,
    }
    if presence == "present":
        record["path"] = path or CANONICAL_PATHS[report_kind]
        record["hash"] = HASHES[report_kind]
    return record


def valid_manifest(**overrides):
    manifest = {
        "manifest_schema_version": "2",
        "linked_report_schema_version": "2",
        "build_version": "workspace-local",
        "skill_version": "camunda-bpmn-from-context",
        "runtime_target": "camunda-bpmn-pipeline",
        "requested_mode": "preview",
        "logic_only": False,
        "preserve_existing_di": True,
        "full_relayout": False,
        "layout_bypass": False,
        "eligibility_class": "eligible",
        "eligibility_reasons": ["baseline DI can be preserved"],
        "scenario_id": None,
        "fixture_id": None,
        "traceability_count": 0,
        "assumptions_count": 0,
        "initial_backend": "native",
        "final_backend": "native",
        "fallback_happened": False,
        "semantic_status": "PASS",
        "layout_status": "PASS",
        "layout_summary": {
            "final_status": "PASS",
            "final_mode": "native_preserve_existing",
            "layout_profile_family": "native",
            "layout_policy_status": "PASS",
            "typed_issue_count": 0,
            "warning_issue_count": 0,
            "error_issue_count": 0,
            "shape_budget_violations": 0,
            "label_budget_violations": 0,
            "participant_lane_budget_violations": 0,
            "advisory_only": False,
        },
        "preview_status": "SKIPPED",
        "layout_hint_source": "none",
        "hint_applied": False,
        "artifacts": {
            "backend_selection": linked_artifact("backend_selection"),
            "semantic_report": linked_artifact("semantic_report"),
            "layout_report": linked_artifact("layout_report"),
            "preview_report": linked_artifact("preview_report", presence="skipped", status="SKIPPED"),
            "human_summary": linked_artifact("human_summary"),
            "typed_issue_targets": linked_artifact(
                "typed_issue_targets",
                presence="not_applicable",
                status="SKIPPED",
            ),
        },
    }
    for key, value in overrides.items():
        manifest[key] = value
    return manifest


def write_manifest(manifest):
    fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    with fh:
        json.dump(manifest, fh)
    return Path(fh.name)


class ValidateRunManifestTests(unittest.TestCase):
    def test_valid_manifest_passes(self):
        manifest_path = write_manifest(valid_manifest())
        errors = VALIDATOR.validate_manifest_file(manifest_path, SCHEMA_DIR)
        self.assertEqual(errors, [])

    def test_hash_must_be_sha256_hex(self):
        manifest = valid_manifest()
        manifest["artifacts"]["semantic_report"]["hash"] = "not-a-sha256"
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("semantic_report.hash" in error for error in errors))

    def test_layout_skipped_requires_logic_only_or_bypass(self):
        manifest = valid_manifest(
            layout_status="SKIPPED",
            artifacts={
                **valid_manifest()["artifacts"],
                "layout_report": linked_artifact("layout_report", presence="skipped", status="SKIPPED"),
            },
        )
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("layout_status SKIPPED requires" in error for error in errors))

    def test_layout_skipped_allowed_with_bypass(self):
        manifest = valid_manifest(
            layout_status="SKIPPED",
            layout_bypass=True,
            layout_summary={
                **valid_manifest()["layout_summary"],
                "final_status": "SKIPPED",
                "layout_policy_status": "SKIPPED",
            },
            artifacts={
                **valid_manifest()["artifacts"],
                "layout_report": linked_artifact("layout_report", presence="skipped", status="SKIPPED"),
            },
        )
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertEqual(errors, [])

    def test_none_backend_requires_logic_only(self):
        manifest = valid_manifest(initial_backend="none")
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("initial_backend=none" in error for error in errors))

    def test_fallback_requires_reason(self):
        manifest = valid_manifest(fallback_happened=True, fallback_reason_code="")
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("fallback_reason_code is required" in error for error in errors))

    def test_optional_artifact_rejects_hash_when_skipped(self):
        manifest = valid_manifest()
        manifest["artifacts"]["preview_report"] = {
            "report_kind": "preview_report",
            "presence": "skipped",
            "status": "SKIPPED",
            "schema_version": "2",
            "hash": HASHES["preview_report"],
        }
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("preview_report" in error for error in errors))

    def test_linked_report_schema_rejects_path_for_skipped_presence(self):
        linked_schema = VALIDATOR.load_json(LINKED_SCHEMA_PATH)
        payload = {
            "report_kind": "layout_report",
            "presence": "skipped",
            "status": "SKIPPED",
            "schema_version": "2",
            "path": "layout_report.md",
        }
        errors = VALIDATOR.validate_instance(payload, linked_schema)
        self.assertTrue(errors)

    def test_linked_report_schema_rejects_fail_status_for_not_applicable(self):
        linked_schema = VALIDATOR.load_json(LINKED_SCHEMA_PATH)
        payload = {
            "report_kind": "typed_issue_targets",
            "presence": "not_applicable",
            "status": "FAIL",
            "schema_version": "2",
        }
        errors = VALIDATOR.validate_instance(payload, linked_schema)
        self.assertTrue(errors)

    def test_artifact_schema_version_must_match_manifest_policy(self):
        manifest = valid_manifest()
        manifest["artifacts"]["semantic_report"]["schema_version"] = "1"
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("semantic_report.schema_version must match linked_report_schema_version" in error for error in errors))

    def test_unsupported_manifest_schema_version_is_rejected(self):
        manifest = valid_manifest(manifest_schema_version="999")
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("unsupported manifest_schema_version" in error for error in errors))

    def test_unsupported_linked_report_schema_version_is_rejected(self):
        manifest = valid_manifest(linked_report_schema_version="999")
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("unsupported linked_report_schema_version" in error for error in errors))

    def test_layout_report_must_be_present_when_layout_status_fails(self):
        manifest = valid_manifest(layout_status="FAIL")
        manifest["artifacts"]["layout_report"] = linked_artifact(
            "layout_report",
            presence="skipped",
            status="SKIPPED",
        )
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("layout_report must be present" in error for error in errors))

    def test_typed_issue_targets_present_requires_canonical_filename(self):
        manifest = valid_manifest()
        manifest["artifacts"]["typed_issue_targets"] = linked_artifact(
            "typed_issue_targets",
            presence="present",
            status="PASS",
            path="issues.json",
        )
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("typed_issue_targets.path must use canonical filename" in error for error in errors))

    def test_fallback_rejects_native_to_native_without_degraded_reason_code(self):
        manifest = valid_manifest(
            initial_backend="native",
            final_backend="native",
            fallback_happened=True,
            fallback_reason_code="simple_helper_failed",
        )
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("native_preserve_degraded_to_greenfield" in error for error in errors))

    def test_fallback_allows_native_to_native_for_explicit_preserve_degradation(self):
        manifest = valid_manifest(
            initial_backend="native",
            final_backend="native",
            fallback_happened=True,
            fallback_reason_code="native_preserve_degraded_to_greenfield",
        )
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertEqual(errors, [])

    def test_backend_transition_requires_fallback_flag(self):
        manifest = valid_manifest(
            initial_backend="simple",
            final_backend="native",
            fallback_happened=False,
        )
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("fallback_happened=false requires initial_backend and final_backend to match" in error for error in errors))

    def test_unsupported_backend_transition_is_rejected(self):
        manifest = valid_manifest(
            initial_backend="native",
            final_backend="simple",
            fallback_happened=False,
        )
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("unsupported backend transition" in error for error in errors))

    def test_present_artifact_missing_path_returns_validation_error(self):
        manifest = valid_manifest()
        manifest["artifacts"]["semantic_report"]["path"] = None
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("semantic_report.path" in error for error in errors))

    def test_non_object_artifact_record_returns_validation_error(self):
        manifest = valid_manifest()
        manifest["artifacts"]["semantic_report"] = "invalid-record"
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("$.artifacts.semantic_report" in error for error in errors))

    def test_hint_applied_requires_non_none_source(self):
        manifest = valid_manifest(
            layout_hint_source="none",
            hint_applied=True,
        )
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("hint_applied=true requires layout_hint_source" in error for error in errors))

    def test_hint_applied_not_allowed_when_layout_skipped(self):
        manifest = valid_manifest(
            layout_status="SKIPPED",
            layout_bypass=True,
            layout_hint_source="inline_json",
            hint_applied=True,
            artifacts={
                **valid_manifest()["artifacts"],
                "layout_report": linked_artifact("layout_report", presence="skipped", status="SKIPPED"),
            },
        )
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("hint_applied=true is not allowed when layout_status=SKIPPED" in error for error in errors))

    def test_manifest_fails_when_layout_summary_missing(self):
        manifest = valid_manifest()
        manifest.pop("layout_summary", None)
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("layout_summary" in error for error in errors))

    def test_manifest_fails_when_layout_status_conflicts_with_layout_summary(self):
        manifest = valid_manifest()
        manifest["layout_status"] = "PASS"
        manifest["layout_summary"]["final_status"] = "FAIL"
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(any("layout_summary.final_status must match layout_status" in error for error in errors))

    def test_layout_summary_readability_fields_must_be_non_negative_when_present(self):
        manifest = valid_manifest()
        manifest["layout_summary"]["diagram_width_px"] = -1
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(
            any("layout_summary.diagram_width_px must be an integer >= 0 when present" in error for error in errors)
        )

    def test_layout_requires_decomposition_requires_readability_violations(self):
        manifest = valid_manifest()
        manifest["layout_summary"]["layout_requires_decomposition"] = True
        manifest["layout_summary"]["readability_violations"] = 0
        errors = VALIDATOR.validate_manifest_data(manifest, VALIDATOR.load_schema(SCHEMA_DIR))
        self.assertTrue(
            any(
                "layout_summary.layout_requires_decomposition=true requires readability_violations>0" in error
                for error in errors
            )
        )


if __name__ == "__main__":
    unittest.main()
