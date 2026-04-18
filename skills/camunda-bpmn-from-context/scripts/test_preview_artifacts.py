#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent / "build_preview_artifacts.py"
SPEC = importlib.util.spec_from_file_location("build_preview_artifacts", SCRIPT_PATH)
PREVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREVIEW)

SAMPLE_BPMN = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<bpmn:definitions xmlns:bpmn=\"http://www.omg.org/spec/BPMN/20100524/MODEL\"
                  xmlns:bpmndi=\"http://www.omg.org/spec/BPMN/20100524/DI\"
                  xmlns:dc=\"http://www.omg.org/spec/DD/20100524/DC\"
                  xmlns:di=\"http://www.omg.org/spec/DD/20100524/DI\"
                  id=\"Definitions_1\"
                  targetNamespace=\"http://example.com/preview\">
  <bpmn:process id=\"Process_1\" isExecutable=\"false\">
    <bpmn:startEvent id=\"StartEvent_1\" />
    <bpmn:serviceTask id=\"Task_1\" />
    <bpmn:endEvent id=\"EndEvent_1\" />
    <bpmn:sequenceFlow id=\"Flow_1\" sourceRef=\"StartEvent_1\" targetRef=\"Task_1\" />
    <bpmn:sequenceFlow id=\"Flow_2\" sourceRef=\"Task_1\" targetRef=\"EndEvent_1\" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id=\"BPMNDiagram_1\">
    <bpmndi:BPMNPlane id=\"BPMNPlane_1\" bpmnElement=\"Process_1\">
      <bpmndi:BPMNShape id=\"StartEvent_1_di\" bpmnElement=\"StartEvent_1\">
        <dc:Bounds x=\"173\" y=\"102\" width=\"36\" height=\"36\" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id=\"Task_1_di\" bpmnElement=\"Task_1\">
        <dc:Bounds x=\"260\" y=\"80\" width=\"100\" height=\"80\" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id=\"EndEvent_1_di\" bpmnElement=\"EndEvent_1\">
        <dc:Bounds x=\"420\" y=\"102\" width=\"36\" height=\"36\" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id=\"Flow_1_di\" bpmnElement=\"Flow_1\">
        <di:waypoint x=\"209\" y=\"120\" />
        <di:waypoint x=\"260\" y=\"120\" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id=\"Flow_2_di\" bpmnElement=\"Flow_2\">
        <di:waypoint x=\"360\" y=\"120\" />
        <di:waypoint x=\"420\" y=\"120\" />
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PreviewArtifactsTests(unittest.TestCase):
    def _write_json(self, path, payload):
        Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _write_fixture_bundle(self, tmpdir):
        root = Path(tmpdir)
        final_bpmn_path = root / "native_layout_output.bpmn"
        final_bpmn_path.write_text(SAMPLE_BPMN, encoding="utf-8")

        backend_selection_path = root / "backend_selection.json"
        semantic_report_path = root / "semantic_report.json"
        human_summary_path = root / "human_summary.md"
        layout_report_path = root / "layout_report.md"

        self._write_json(
            backend_selection_path,
            {
                "initial_backend": "native",
                "final_backend": "native",
                "fallback_happened": False,
                "semantic_status": "PASS",
                "layout_status": "PASS",
                "preview_status": "SKIPPED",
                "native_result": {
                    "output_bpmn_path": str(final_bpmn_path),
                    "output_bpmn_hash": sha256(final_bpmn_path),
                    "ok": True,
                },
            },
        )
        self._write_json(
            semantic_report_path,
            {
                "backend": "native",
                "status": "PASS",
                "errors": [],
                "warnings": ["preview warning"],
            },
        )
        human_summary_path.write_text("# BPMN Pipeline Summary\n\n- final_backend: `native`\n", encoding="utf-8")
        layout_report_path.write_text(
            "\n".join(
                [
                    "# Layout Report",
                    "",
                    "- typed_issue_count: 2",
                    "- issue_code.shape_overlap: 1",
                    "- issue_code.column_gap_violation: 1",
                    "- issue: code=shape_overlap severity=error target_type=pair element_id=Task_A secondary_element_id=Task_B bbox=[10, 20, 30, 40]",
                    "- issue: code=column_gap_violation severity=warning target_type=global element_id=layout secondary_element_id=none bbox=none",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        manifest_path = root / "run_manifest.json"
        manifest = {
            "manifest_schema_version": "2",
            "linked_report_schema_version": "2",
            "build_version": "build-1",
            "skill_version": "skill-preview",
            "runtime_target": "preview-tests",
            "requested_mode": "native",
            "logic_only": False,
            "preserve_existing_di": False,
            "full_relayout": False,
            "layout_bypass": False,
            "eligibility_class": "simple_eligible",
            "eligibility_reasons": ["requested_mode_native"],
            "scenario_id": "scenario-preview",
            "fixture_id": "fixture-preview",
            "traceability_count": 2,
            "assumptions_count": 1,
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
                "typed_issue_count": 2,
                "warning_issue_count": 1,
                "error_issue_count": 1,
                "shape_budget_violations": 0,
                "label_budget_violations": 0,
                "participant_lane_budget_violations": 0,
                "advisory_only": False,
            },
            "preview_status": "SKIPPED",
            "layout_hint_source": "none",
            "hint_applied": False,
            "artifacts": {
                "backend_selection": {
                    "report_kind": "backend_selection",
                    "presence": "present",
                    "status": "PASS",
                    "schema_version": "2",
                    "path": "backend_selection.json",
                    "hash": sha256(backend_selection_path),
                },
                "semantic_report": {
                    "report_kind": "semantic_report",
                    "presence": "present",
                    "status": "PASS",
                    "schema_version": "2",
                    "path": "semantic_report.json",
                    "hash": sha256(semantic_report_path),
                },
                "layout_report": {
                    "report_kind": "layout_report",
                    "presence": "present",
                    "status": "PASS",
                    "schema_version": "2",
                    "path": "layout_report.md",
                    "hash": sha256(layout_report_path),
                },
                "preview_report": {
                    "report_kind": "preview_report",
                    "presence": "skipped",
                    "status": "SKIPPED",
                    "schema_version": "2",
                },
                "human_summary": {
                    "report_kind": "human_summary",
                    "presence": "present",
                    "status": "PASS",
                    "schema_version": "2",
                    "path": "human_summary.md",
                    "hash": sha256(human_summary_path),
                },
                "typed_issue_targets": {
                    "report_kind": "typed_issue_targets",
                    "presence": "not_applicable",
                    "status": "SKIPPED",
                    "schema_version": "2",
                },
            },
        }
        self._write_json(manifest_path, manifest)
        return manifest_path

    def test_build_preview_artifacts_emits_self_contained_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = self._write_fixture_bundle(tmpdir)
            output_dir = Path(tmpdir) / "preview"
            result = PREVIEW.build_preview_artifacts(manifest_path, output_dir)
            index_path = Path(result["index_path"])
            html = index_path.read_text(encoding="utf-8")
            typed_issue_targets_path = index_path.parent / PREVIEW.TYPED_ISSUE_TARGETS_PATH
            preview_report_path = Path(result["preview_report_path"])
            canonical_typed_targets_path = Path(result["typed_issue_targets_path"])
            typed_issue_targets = json.loads(typed_issue_targets_path.read_text(encoding="utf-8"))
            self.assertTrue(index_path.exists())
            self.assertTrue((index_path.parent / "assets" / "preview-app.js").exists())
            self.assertTrue((index_path.parent / "assets" / "vendor" / "bpmn-viewer.production.min.js").exists())
            self.assertTrue(typed_issue_targets_path.exists())
            self.assertTrue(preview_report_path.exists())
            self.assertTrue(canonical_typed_targets_path.exists())
            preview_report = json.loads(preview_report_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["preview_schema_version"], PREVIEW.PREVIEW_SCHEMA_VERSION)
        self.assertIn('id="preview-bpmn-xml"', html)
        self.assertIn('id="preview-manifest-summary"', html)
        self.assertIn('id="preview-metadata-summary"', html)
        self.assertIn('id="preview-typed-issue-targets"', html)
        self.assertIn('id="preview-report-summary"', html)
        self.assertIn('data-testid="metadata-summary"', html)
        self.assertIn('data-testid="typed-issue-summary"', html)
        self.assertIn('sequence_flow_count: 2', html)
        self.assertIn('bpmn_edge_count: 2', html)
        self.assertIn('layout_requires_decomposition: false', html)
        self.assertIn('skill_version</strong>: skill-preview', html)
        self.assertIn('preview_schema_version</strong>: 1', html)
        self.assertIn('build_timestamp</strong>: not-provided', html)
        self.assertIn('http://www.omg.org/spec/BPMN/20100524/MODEL', html)
        self.assertIn('Viewer Only', html)
        self.assertIn('No runtime network fetch', html)
        self.assertEqual(typed_issue_targets["schema_version"], PREVIEW.TYPED_ISSUE_TARGETS_SCHEMA_VERSION)
        self.assertEqual(typed_issue_targets["counts"]["total"], 2)
        self.assertEqual(typed_issue_targets["counts"]["by_target_type"]["pair"], 1)
        self.assertEqual(typed_issue_targets["counts"]["by_target_type"]["global"], 1)
        self.assertEqual(typed_issue_targets["counts"]["by_severity"]["warning"], 1)
        self.assertEqual(typed_issue_targets["items"][0]["source_report"], "layout_report")
        self.assertEqual(typed_issue_targets["items"][1]["bbox"], None)
        schema = PREVIEW._load_typed_issue_targets_schema()
        schema_errors = PREVIEW.VALIDATOR.validate_instance(typed_issue_targets, schema, schema)
        self.assertEqual(schema_errors, [])
        self.assertEqual(preview_report["status"], "PASS")
        self.assertTrue(preview_report["preview_import_ok"])
        self.assertEqual(preview_report["layout_final_mode"], "native_preserve_existing")
        self.assertEqual(preview_report["warning_issue_count"], 1)
        self.assertEqual(preview_report["error_issue_count"], 1)
        self.assertFalse(preview_report["advisory_only"])
        self.assertFalse(preview_report["layout_requires_decomposition"])
        self.assertIn("diagram_width_px", preview_report)
        self.assertIn("diagram_height_px", preview_report)
        self.assertIn("aspect_ratio_x100", preview_report)
        self.assertEqual(preview_report["sequence_flow_count"], 2)
        self.assertEqual(preview_report["bpmn_edge_count"], 2)
        self.assertEqual(preview_report["typed_issue_target_count"], 2)
        self.assertEqual(preview_report["typed_issue_targets"]["count"], 2)
        self.assertTrue(result["audit"]["ok"])

    def test_preview_report_includes_flow_and_connection_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = self._write_fixture_bundle(tmpdir)
            result = PREVIEW.build_preview_artifacts(manifest_path, Path(tmpdir) / "preview")
            preview_report = json.loads(Path(result["preview_report_path"]).read_text(encoding="utf-8"))
            typed_issue_targets = json.loads(Path(result["typed_issue_targets_path"]).read_text(encoding="utf-8"))

        self.assertIn("sequence_flow_count", preview_report)
        self.assertIn("bpmn_edge_count", preview_report)
        self.assertIn("preview_import_ok", preview_report)
        self.assertEqual(preview_report["typed_issue_target_count"], typed_issue_targets["counts"]["total"])
        self.assertIn("warning_issue_count", preview_report)
        self.assertIn("error_issue_count", preview_report)
        self.assertIn("layout_final_mode", preview_report)
        self.assertIn("layout_requires_decomposition", preview_report)

    def test_build_preview_artifacts_rejects_linked_artifact_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = self._write_fixture_bundle(tmpdir)
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            manifest["artifacts"]["semantic_report"]["hash"] = "0" * 64
            Path(manifest_path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                PREVIEW.build_preview_artifacts(manifest_path, Path(tmpdir) / "preview")

    def test_build_preview_artifacts_rejects_final_bpmn_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = self._write_fixture_bundle(tmpdir)
            backend_selection_path = Path(tmpdir) / "backend_selection.json"
            backend_selection = json.loads(backend_selection_path.read_text(encoding="utf-8"))
            backend_selection["native_result"]["output_bpmn_hash"] = "f" * 64
            backend_selection_path.write_text(
                json.dumps(backend_selection, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            manifest["artifacts"]["backend_selection"]["hash"] = sha256(backend_selection_path)
            Path(manifest_path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "final BPMN XML hash mismatch"):
                PREVIEW.build_preview_artifacts(manifest_path, Path(tmpdir) / "preview")

    def test_build_preview_artifacts_rejects_optional_layout_report_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = self._write_fixture_bundle(tmpdir)
            layout_report_path = Path(tmpdir) / "layout_report.md"
            layout_report_path.write_text("# tampered layout report\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "artifacts.layout_report hash mismatch"):
                PREVIEW.build_preview_artifacts(manifest_path, Path(tmpdir) / "preview")

    def test_runtime_audit_rejects_fetch_dependency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "index.html").write_text("<html><body><script src='assets/app.js'></script></body></html>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("fetch('https://example.com/runtime')", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "forbidden runtime network primitive"):
                PREVIEW.audit_preview_runtime(root)

    def test_runtime_audit_rejects_iframe_and_srcset_network_bypasses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "index.html").write_text(
                "<html><body>"
                "<iframe src='https://example.com/frame'></iframe>"
                "<img srcset='https://example.com/preview.png 1x, assets/local.png 2x'>"
                "</body></html>",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "external src|external srcset"):
                PREVIEW.audit_preview_runtime(root)

    def test_runtime_audit_rejects_send_beacon(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "index.html").write_text("<html><body><script src='assets/app.js'></script></body></html>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("navigator.sendBeacon('https://example.com/beacon', 'x')", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "navigator.sendBeacon"):
                PREVIEW.audit_preview_runtime(root)

    def test_runtime_audit_rejects_image_src_network_channel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "index.html").write_text("<html><body><script src='assets/app.js'></script></body></html>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("new Image().src = 'https://example.com/pixel'", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "new Image\\(\\)\\.src"):
                PREVIEW.audit_preview_runtime(root)

    def test_runtime_audit_rejects_location_href_navigation_channel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "index.html").write_text("<html><body><script src='assets/app.js'></script></body></html>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("location.href = 'https://example.com/redirect'", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "location.href"):
                PREVIEW.audit_preview_runtime(root)

    def test_runtime_audit_rejects_location_assign_navigation_channel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "index.html").write_text("<html><body><script src='assets/app.js'></script></body></html>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("location.assign('https://example.com/redirect')", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "location.assign"):
                PREVIEW.audit_preview_runtime(root)

    def test_runtime_audit_rejects_window_open_navigation_channel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "index.html").write_text("<html><body><script src='assets/app.js'></script></body></html>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("window.open('https://example.com/popup')", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "window.open"):
                PREVIEW.audit_preview_runtime(root)

    def test_runtime_audit_rejects_location_replace_navigation_channel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "index.html").write_text("<html><body><script src='assets/app.js'></script></body></html>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("location.replace('https://example.com/replace')", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "external URL literal"):
                PREVIEW.audit_preview_runtime(root)

    def test_runtime_audit_rejects_protocol_relative_location_replace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "index.html").write_text("<html><body><script src='assets/app.js'></script></body></html>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("location.replace('//example.com/replace')", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "external URL literal"):
                PREVIEW.audit_preview_runtime(root)

    def test_runtime_audit_rejects_open_navigation_channel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "index.html").write_text("<html><body><script src='assets/app.js'></script></body></html>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("open('https://example.com/popup')", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "external URL literal"):
                PREVIEW.audit_preview_runtime(root)

    def test_runtime_audit_rejects_protocol_relative_open_navigation_channel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "index.html").write_text("<html><body><script src='assets/app.js'></script></body></html>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("open('//example.com/popup')", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "external URL literal"):
                PREVIEW.audit_preview_runtime(root)

    def test_runtime_audit_rejects_plain_external_url_literal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "index.html").write_text("<html><body><script src='assets/app.js'></script></body></html>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("const stray = 'https://example.com/stray';", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "external URL literal"):
                PREVIEW.audit_preview_runtime(root)

    def test_build_preview_artifacts_is_deterministic_for_identical_inputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = self._write_fixture_bundle(tmpdir)
            output_a = Path(tmpdir) / "preview-a"
            output_b = Path(tmpdir) / "preview-b"
            result_a = PREVIEW.build_preview_artifacts(manifest_path, output_a)
            result_b = PREVIEW.build_preview_artifacts(manifest_path, output_b)
            html_a = Path(result_a["index_path"]).read_bytes()
            html_b = Path(result_b["index_path"]).read_bytes()
            typed_a = (output_a / PREVIEW.TYPED_ISSUE_TARGETS_PATH).read_bytes()
            typed_b = (output_b / PREVIEW.TYPED_ISSUE_TARGETS_PATH).read_bytes()

        self.assertEqual(html_a, html_b)
        self.assertEqual(typed_a, typed_b)

    def test_build_preview_artifacts_rejects_unparseable_layout_issue_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = self._write_fixture_bundle(tmpdir)
            layout_report_path = Path(tmpdir) / "layout_report.md"
            layout_report_path.write_text(
                "# Layout Report\n\n- issue: malformed line that does not match typed issue format\n",
                encoding="utf-8",
            )
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            manifest["artifacts"]["layout_report"]["hash"] = sha256(layout_report_path)
            Path(manifest_path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unable to parse typed issue line"):
                PREVIEW.build_preview_artifacts(manifest_path, Path(tmpdir) / "preview")

    def test_build_preview_artifacts_rejects_empty_issue_element_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = self._write_fixture_bundle(tmpdir)
            layout_report_path = Path(tmpdir) / "layout_report.md"
            layout_report_path.write_text(
                "# Layout Report\n\n"
                "- issue: code=shape_overlap severity=error target_type=pair "
                "element_id=none secondary_element_id=Task_B bbox=[10, 20, 30, 40]\n",
                encoding="utf-8",
            )
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            manifest["artifacts"]["layout_report"]["hash"] = sha256(layout_report_path)
            Path(manifest_path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "empty element_id"):
                PREVIEW.build_preview_artifacts(manifest_path, Path(tmpdir) / "preview")


if __name__ == "__main__":
    unittest.main()
