#!/usr/bin/env python3
import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parent / "run_bpmn_pipeline.py"
SPEC = importlib.util.spec_from_file_location("run_bpmn_pipeline", SCRIPT_PATH)
PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPELINE)
FIXTURE_DIR = SCRIPT_PATH.parent / "fixtures"


class RunBpmnPipelineTests(unittest.TestCase):
    def _sha256(self, path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _input_file(self, tmpdir):
        path = Path(tmpdir) / "input.bpmn"
        path.write_text("<definitions />", encoding="utf-8")
        return path

    def _sequence_flow_bpmn(self, include_edge_di):
        edge_block = ""
        if include_edge_di:
            edge_block = """
      <bpmndi:BPMNEdge id=\"Edge_Flow_1\" bpmnElement=\"Flow_1\">
        <di:waypoint x=\"136\" y=\"118\" />
        <di:waypoint x=\"200\" y=\"118\" />
      </bpmndi:BPMNEdge>
            """.rstrip()
        return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<bpmn:definitions xmlns:bpmn=\"http://www.omg.org/spec/BPMN/20100524/MODEL\"
                  xmlns:bpmndi=\"http://www.omg.org/spec/BPMN/20100524/DI\"
                  xmlns:dc=\"http://www.omg.org/spec/DD/20100524/DC\"
                  xmlns:di=\"http://www.omg.org/spec/DD/20100524/DI\"
                  id=\"Definitions_1\"
                  targetNamespace=\"http://example.com/test\">
  <bpmn:process id=\"Process_1\" isExecutable=\"false\">
    <bpmn:startEvent id=\"Start_1\" />
    <bpmn:endEvent id=\"End_1\" />
    <bpmn:sequenceFlow id=\"Flow_1\" sourceRef=\"Start_1\" targetRef=\"End_1\" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id=\"BPMNDiagram_1\">
    <bpmndi:BPMNPlane id=\"BPMNPlane_1\" bpmnElement=\"Process_1\">
      <bpmndi:BPMNShape id=\"Shape_Start_1\" bpmnElement=\"Start_1\">
        <dc:Bounds x=\"100\" y=\"100\" width=\"36\" height=\"36\" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id=\"Shape_End_1\" bpmnElement=\"End_1\">
        <dc:Bounds x=\"200\" y=\"100\" width=\"36\" height=\"36\" />
      </bpmndi:BPMNShape>
      {edge_block}
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""

    def _read_json(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def _read_text(self, path):
        return Path(path).read_text(encoding="utf-8")

    def _load_outputs(self, result, tmpdir):
        manifest = self._read_json(result["manifest_path"])
        backend_selection = self._read_json(Path(tmpdir) / "backend_selection.json")
        return manifest, backend_selection

    def _assert_manifest_backend_selection_parity(self, manifest, backend_selection):
        for field in (
            "initial_backend",
            "final_backend",
            "fallback_happened",
            "semantic_status",
            "layout_status",
            "layout_summary",
            "preview_status",
            "layout_hint_source",
            "hint_applied",
        ):
            self.assertEqual(manifest[field], backend_selection[field], field)
        self.assertEqual(
            manifest.get("fallback_reason_code"),
            backend_selection.get("fallback_reason_code"),
            "fallback_reason_code",
        )

    def _assert_linked_artifact(self, manifest, key, presence):
        artifact = manifest["artifacts"][key]
        self.assertEqual(artifact["report_kind"], key)
        self.assertEqual(artifact["presence"], presence)
        self.assertEqual(artifact["schema_version"], PIPELINE.LINKED_REPORT_SCHEMA_VERSION)
        if presence == "present":
            self.assertIn("path", artifact)
            self.assertIn("hash", artifact)
        else:
            self.assertNotIn("path", artifact)
            self.assertNotIn("hash", artifact)

    def _make_layout_runner(self, steps):
        sequence = list(steps)

        def fake_run(command, capture_output, text, check):
            if not sequence:
                raise AssertionError(f"unexpected layout invocation: {command}")
            step = sequence.pop(0)
            output_path = Path(command[command.index("--output") + 1])
            report_path = Path(command[command.index("--report") + 1])
            report_text = step.get("report_text", "# report\n")
            report_path.write_text(report_text, encoding="utf-8")
            if "--report-json" in command:
                report_json_path = Path(command[command.index("--report-json") + 1])
                default_mode = (
                    "simple_postprocess_refine"
                    if output_path.name == "simple_postprocessed_output.bpmn"
                    else "native_preserve_existing"
                )
                default_family = "simple_postprocess" if output_path.name == "simple_postprocessed_output.bpmn" else "native"
                inferred_status = "PASS"
                normalized_report_text = report_text.lower()
                if "final status" in normalized_report_text and "fail" in normalized_report_text:
                    inferred_status = "FAIL"
                report_json_payload = {
                    "schema_version": "1",
                    "final_status": step.get("layout_policy_status", inferred_status),
                    "final_mode": step.get("final_mode", default_mode),
                    "layout_profile_family": step.get("layout_profile_family", default_family),
                    "simple_postprocess_mode": output_path.name == "simple_postprocessed_output.bpmn",
                    "budget_violations_hard": not (output_path.name == "simple_postprocessed_output.bpmn"),
                    "shape_budget_violations": 0,
                    "label_budget_violations": 0,
                    "participant_lane_budget_violations": 0,
                    "typed_issue_count": 0,
                    "warning_issue_count": 0,
                    "error_issue_count": 0,
                    "advisory_only": False,
                    "hint_applied": False,
                    "layout_hint_source": "none",
                }
                report_json_path.write_text(
                    json.dumps(report_json_payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            if step.get("write_output", step.get("returncode", 0) == 0):
                output_path.write_text(step.get("output_text", "<definitions />"), encoding="utf-8")
            return mock.Mock(
                returncode=step.get("returncode", 0),
                stdout=step.get("stdout", "layout ok"),
                stderr=step.get("stderr", ""),
            )

        return fake_run

    def _validate_by_name(self, outcomes):
        def validator(path):
            return outcomes[Path(path).name]

        return validator

    def _write_layout_summary_for_command(
        self,
        command,
        output_path,
        status="PASS",
        final_mode=None,
        layout_profile_family=None,
    ):
        if "--report-json" not in command:
            return
        report_json_path = Path(command[command.index("--report-json") + 1])
        default_mode = (
            "simple_postprocess_refine"
            if output_path.name == "simple_postprocessed_output.bpmn"
            else "native_preserve_existing"
        )
        default_family = "simple_postprocess" if output_path.name == "simple_postprocessed_output.bpmn" else "native"
        payload = {
            "schema_version": "1",
            "final_status": status,
            "final_mode": final_mode or default_mode,
            "layout_profile_family": layout_profile_family or default_family,
            "simple_postprocess_mode": output_path.name == "simple_postprocessed_output.bpmn",
            "budget_violations_hard": not (output_path.name == "simple_postprocessed_output.bpmn"),
            "shape_budget_violations": 0,
            "label_budget_violations": 0,
            "participant_lane_budget_violations": 0,
            "typed_issue_count": 0,
            "warning_issue_count": 0,
            "error_issue_count": 0,
            "advisory_only": False,
            "hint_applied": False,
            "layout_hint_source": "none",
        }
        report_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_logic_only_short_circuit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = PIPELINE.run_pipeline(
                input_bpmn=self._input_file(tmpdir),
                work_dir=tmpdir,
                requested_mode="simple",
                logic_only=True,
            )
            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["initial_backend"], "none")
        self.assertEqual(manifest["final_backend"], "none")
        self.assertEqual(manifest["layout_status"], "SKIPPED")
        self.assertEqual(manifest["preview_status"], "SKIPPED")
        self.assertEqual(manifest["manifest_schema_version"], PIPELINE.MANIFEST_SCHEMA_VERSION)
        self.assertEqual(manifest["linked_report_schema_version"], PIPELINE.LINKED_REPORT_SCHEMA_VERSION)
        self.assertEqual(manifest["build_version"], PIPELINE.DEFAULT_BUILD_VERSION)
        self.assertEqual(manifest["skill_version"], PIPELINE.DEFAULT_SKILL_VERSION)
        self.assertEqual(manifest["runtime_target"], PIPELINE.DEFAULT_RUNTIME_TARGET)
        self.assertEqual(manifest["traceability_count"], 0)
        self.assertEqual(manifest["assumptions_count"], 0)
        self.assertEqual(manifest["layout_hint_source"], "none")
        self.assertFalse(manifest["hint_applied"])
        self.assertIsNone(manifest["scenario_id"])
        self.assertIsNone(manifest["fixture_id"])
        self.assertEqual(
            [entry["state"] for entry in backend_selection["state_history"]],
            [PIPELINE.STATE_SELECT, PIPELINE.STATE_FINALIZE],
        )
        self._assert_linked_artifact(manifest, "backend_selection", "present")
        self._assert_linked_artifact(manifest, "semantic_report", "present")
        self._assert_linked_artifact(manifest, "layout_report", "skipped")
        self._assert_linked_artifact(manifest, "preview_report", "skipped")
        self._assert_linked_artifact(manifest, "human_summary", "present")
        self._assert_linked_artifact(manifest, "typed_issue_targets", "not_applicable")
        self._assert_manifest_backend_selection_parity(manifest, backend_selection)

    def test_auto_without_helper_forces_native_without_synthetic_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            with mock.patch.object(
                PIPELINE.subprocess,
                "run",
                side_effect=self._make_layout_runner([{"returncode": 0}]),
            ):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="auto",
                        helper_command=None,
                    )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["initial_backend"], "native")
        self.assertFalse(manifest["fallback_happened"])
        self.assertNotIn("fallback_reason_code", manifest)
        self.assertEqual(
            [entry["state"] for entry in backend_selection["state_history"]],
            [
                PIPELINE.STATE_SELECT,
                PIPELINE.STATE_FALLBACK_NATIVE,
                PIPELINE.STATE_VALIDATE,
                PIPELINE.STATE_FINALIZE,
            ],
        )
        self._assert_manifest_backend_selection_parity(manifest, backend_selection)

    def test_requested_simple_without_helper_forces_native_without_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            with mock.patch.object(
                PIPELINE.subprocess,
                "run",
                side_effect=self._make_layout_runner([{"returncode": 0}]),
            ):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="simple",
                        helper_command=None,
                    )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["initial_backend"], "native")
        self.assertFalse(manifest["fallback_happened"])
        self.assertNotIn("fallback_reason_code", manifest)
        self.assertEqual(
            [entry["state"] for entry in backend_selection["state_history"]],
            [
                PIPELINE.STATE_SELECT,
                PIPELINE.STATE_FALLBACK_NATIVE,
                PIPELINE.STATE_VALIDATE,
                PIPELINE.STATE_FINALIZE,
            ],
        )
        self._assert_manifest_backend_selection_parity(manifest, backend_selection)

    def test_requested_native_has_no_fallback_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            with mock.patch.object(
                PIPELINE.subprocess,
                "run",
                side_effect=self._make_layout_runner([{"returncode": 0}]),
            ):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="native",
                    )
            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertFalse(manifest["fallback_happened"])
        self.assertNotIn("fallback_reason_code", manifest)
        self._assert_manifest_backend_selection_parity(manifest, backend_selection)

    def test_selector_extracts_hard_exclusions_from_bpmn_without_external_facts(self):
        input_path = FIXTURE_DIR / "negative" / "neg_boundary_event.bpmn"
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                PIPELINE.subprocess,
                "run",
                side_effect=self._make_layout_runner([{"returncode": 0}]),
            ):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="auto",
                        helper_command="fake-helper",
                    )
            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["initial_backend"], "native")
        self.assertEqual(manifest["final_backend"], "native")
        self.assertFalse(manifest["fallback_happened"])
        self.assertIn("boundary_event_present", backend_selection["selection"]["hard_exclusions"])
        self.assertEqual(
            backend_selection["selector_facts"]["extracted"]["constructs"],
            ["boundaryEvent"],
        )
        self.assertEqual(backend_selection["selector_facts"]["extracted"]["di_quality"], "no_di")

    def test_preserve_existing_di_forces_native_without_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            observed_commands = []

            def fake_run(command, capture_output, text, check):
                observed_commands.append(list(command))
                output_path = Path(command[command.index("--output") + 1])
                report_path = Path(command[command.index("--report") + 1])
                output_path.write_text("<definitions id='native' />", encoding="utf-8")
                report_path.write_text("# Layout Report\n\n- layout_hint_source: none\n- hint_applied: false\n", encoding="utf-8")
                self._write_layout_summary_for_command(command, output_path, status="PASS")
                return mock.Mock(returncode=0, stdout="ok", stderr="")

            with mock.patch.object(
                PIPELINE.subprocess,
                "run",
                side_effect=fake_run,
            ):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="simple",
                        preserve_existing_di=True,
                    )
            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["initial_backend"], "native")
        self.assertFalse(manifest["fallback_happened"])
        self.assertNotIn("fallback_reason_code", manifest)
        self.assertTrue(backend_selection["selection"]["native_preserve_strict"])
        self.assertIn("--preserve-existing-di-strict", observed_commands[0])
        self._assert_manifest_backend_selection_parity(manifest, backend_selection)

    def test_existing_di_input_auto_forces_native_preserve_without_explicit_flag(self):
        input_path = FIXTURE_DIR / "original" / "01_original.bpmn"
        with tempfile.TemporaryDirectory() as tmpdir:
            observed_commands = []

            def fake_run(command, capture_output, text, check):
                observed_commands.append(list(command))
                output_path = Path(command[command.index("--output") + 1])
                report_path = Path(command[command.index("--report") + 1])
                output_path.write_text("<definitions id='native' />", encoding="utf-8")
                report_path.write_text("# Layout Report\n\n- layout_hint_source: none\n- hint_applied: false\n", encoding="utf-8")
                self._write_layout_summary_for_command(command, output_path, status="PASS")
                return mock.Mock(returncode=0, stdout="ok", stderr="")

            with mock.patch.object(PIPELINE.subprocess, "run", side_effect=fake_run):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="auto",
                        helper_command="fake-helper",
                    )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["initial_backend"], "native")
        self.assertEqual(manifest["final_backend"], "native")
        self.assertFalse(manifest["fallback_happened"])
        self.assertTrue(manifest["preserve_existing_di"])
        self.assertFalse(backend_selection["selection"]["requested_preserve_existing_di"])
        self.assertTrue(backend_selection["selection"]["preserve_existing_di"])
        self.assertTrue(backend_selection["selection"]["effective_preserve_existing_di"])
        self.assertTrue(backend_selection["selection"]["inferred_preserve_existing_di"])
        self.assertFalse(backend_selection["selection"]["native_preserve_strict"])
        self.assertEqual(backend_selection["selection"]["di_quality"], "usable_di")
        self.assertNotIn("--preserve-existing-di-strict", observed_commands[0])

    def test_auto_preserve_degradation_is_tracked_as_native_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            observed_commands = []

            def fake_run(command, capture_output, text, check):
                observed_commands.append(list(command))
                output_path = Path(command[command.index("--output") + 1])
                report_path = Path(command[command.index("--report") + 1])
                output_path.write_text("<definitions id='native' />", encoding="utf-8")
                report_path.write_text(
                    "\n".join(
                        [
                            "# Layout Report",
                            "",
                            "- layout_hint_source: none",
                            "- hint_applied: false",
                            "- final_mode: native_greenfield",
                            "Final status: PASS",
                        ]
                    ),
                    encoding="utf-8",
                )
                self._write_layout_summary_for_command(
                    command,
                    output_path,
                    status="PASS",
                    final_mode="native_greenfield",
                    layout_profile_family="native",
                )
                return mock.Mock(returncode=0, stdout="ok", stderr="")

            with mock.patch.object(PIPELINE.subprocess, "run", side_effect=fake_run):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="auto",
                        preserve_existing_di=True,
                    )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["initial_backend"], "native")
        self.assertEqual(manifest["final_backend"], "native")
        self.assertTrue(manifest["fallback_happened"])
        self.assertEqual(
            manifest["fallback_reason_code"],
            PIPELINE.FALLBACK_NATIVE_PRESERVE_DEGRADED,
        )
        self.assertEqual(
            backend_selection["selection"]["native_preserve_strict"],
            False,
        )
        self.assertEqual(
            backend_selection["native_result"]["layout_final_mode"],
            "native_greenfield",
        )
        self.assertNotIn("--preserve-existing-di-strict", observed_commands[0])

    def test_native_layout_report_final_fail_markdown_variant_forces_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            report_text = "\n".join(
                [
                    "# Layout Report",
                    "",
                    "- layout_hint_source: none",
                    "- hint_applied: false",
                    "- **Final status:** `fail`",
                ]
            )
            with mock.patch.object(
                PIPELINE.subprocess,
                "run",
                side_effect=self._make_layout_runner([{"returncode": 0, "report_text": report_text}]),
            ):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="native",
                    )
            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertFalse(result["ok"])
        self.assertEqual(manifest["layout_status"], "FAIL")
        self.assertEqual(backend_selection["native_result"]["layout_policy_status"], "FAIL")

    def test_partial_di_input_does_not_infer_preserve_existing_di(self):
        input_path = FIXTURE_DIR / "original" / "04a_original.bpmn"
        with tempfile.TemporaryDirectory() as tmpdir:
            observed_calls = []

            def fake_classify_eligibility(*, requested_mode, logic_only, preserve_existing_di, full_relayout, facts):
                observed_calls.append(
                    {
                        "requested_mode": requested_mode,
                        "logic_only": logic_only,
                        "preserve_existing_di": preserve_existing_di,
                        "full_relayout": full_relayout,
                        "di_quality": facts.get("di_quality"),
                    }
                )
                return {
                    "requested_mode": requested_mode,
                    "logic_only": logic_only,
                    "preserve_existing_di": preserve_existing_di,
                    "full_relayout": full_relayout,
                    "eligibility_class": "simple_eligible",
                    "eligibility_reasons": ["test"],
                    "forced_native": False,
                    "forced_skip_layout": False,
                    "hard_exclusions": [],
                    "normalized_facts": {},
                    "primary_reason": "test",
                }

            with mock.patch.object(PIPELINE, "classify_eligibility", side_effect=fake_classify_eligibility):
                with mock.patch.object(
                    PIPELINE.subprocess,
                    "run",
                    side_effect=self._make_layout_runner([{"returncode": 0}]),
                ):
                    with mock.patch.object(
                        PIPELINE,
                        "validate_bpmn",
                        side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                    ):
                        result = PIPELINE.run_pipeline(
                            input_bpmn=input_path,
                            work_dir=tmpdir,
                            requested_mode="auto",
                            helper_command=None,
                        )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(backend_selection["selector_facts"]["extracted"]["di_quality"], "partial_di")
        self.assertFalse(backend_selection["selection"]["effective_preserve_existing_di"])
        self.assertFalse(backend_selection["selection"]["inferred_preserve_existing_di"])
        self.assertEqual(observed_calls[0]["di_quality"], "partial_di")
        self.assertFalse(observed_calls[0]["preserve_existing_di"])
        self.assertEqual(manifest["initial_backend"], "native")

    def test_native_layout_report_final_fail_forces_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            report_text = "\n".join(
                [
                    "# Layout Report",
                    "",
                    "- layout_hint_source: none",
                    "- hint_applied: false",
                    "Final status: FAIL",
                ]
            )
            with mock.patch.object(
                PIPELINE.subprocess,
                "run",
                side_effect=self._make_layout_runner([{"returncode": 0, "report_text": report_text}]),
            ):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="native",
                    )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertFalse(result["ok"])
        self.assertEqual(manifest["initial_backend"], "native")
        self.assertEqual(manifest["final_backend"], "native")
        self.assertEqual(manifest["layout_status"], "FAIL")
        self.assertEqual(manifest["semantic_status"], "PASS")
        self.assertEqual(
            backend_selection["native_result"]["failure_code"],
            "native_layout_policy_failed",
        )
        self.assertEqual(
            backend_selection["native_result"]["layout_policy_status"],
            "FAIL",
        )
        self.assertEqual(
            backend_selection["native_result"]["semantic_payload"]["layout_policy_status"],
            "FAIL",
        )

    def test_native_missing_layout_summary_json_forces_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)

            def fake_layout_run(command, capture_output, text, check):
                output_path = Path(command[command.index("--output") + 1])
                report_path = Path(command[command.index("--report") + 1])
                output_path.write_text("<definitions id='native' />", encoding="utf-8")
                report_path.write_text(
                    "# Layout Report\n\n- layout_hint_source: none\n- hint_applied: false\nFinal status: PASS\n",
                    encoding="utf-8",
                )
                return mock.Mock(returncode=0, stdout="ok", stderr="")

            with mock.patch.object(PIPELINE.subprocess, "run", side_effect=fake_layout_run):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="native",
                    )
            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertFalse(result["ok"])
        self.assertEqual(manifest["layout_status"], "FAIL")
        self.assertEqual(manifest["semantic_status"], "PASS")
        self.assertEqual(
            backend_selection["native_result"]["failure_code"],
            "native_layout_policy_failed",
        )
        self.assertEqual(
            backend_selection["native_result"]["layout_summary_error"],
            "layout_summary_missing",
        )

    def test_native_invalid_layout_summary_json_forces_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)

            def fake_layout_run(command, capture_output, text, check):
                output_path = Path(command[command.index("--output") + 1])
                report_path = Path(command[command.index("--report") + 1])
                report_json_path = Path(command[command.index("--report-json") + 1])
                output_path.write_text("<definitions id='native' />", encoding="utf-8")
                report_path.write_text(
                    "# Layout Report\n\n- layout_hint_source: none\n- hint_applied: false\nFinal status: PASS\n",
                    encoding="utf-8",
                )
                report_json_path.write_text("{ invalid json", encoding="utf-8")
                return mock.Mock(returncode=0, stdout="ok", stderr="")

            with mock.patch.object(PIPELINE.subprocess, "run", side_effect=fake_layout_run):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="native",
                    )
            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertFalse(result["ok"])
        self.assertEqual(manifest["layout_status"], "FAIL")
        self.assertEqual(
            backend_selection["native_result"]["failure_code"],
            "native_layout_policy_failed",
        )
        self.assertTrue(
            backend_selection["native_result"]["layout_summary_error"].startswith(
                "layout_summary_unreadable:"
            )
        )

    def test_existing_di_plus_full_relayout_allows_simple_or_auto_reroute(self):
        input_path = FIXTURE_DIR / "original" / "01_original.bpmn"
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                PIPELINE,
                "run_simple_mode_bridge",
                return_value={
                    "ok": False,
                    "failure_code": "helper_runtime_failed",
                    "diagnostics": {},
                    "diagnostics_path": str(Path(tmpdir) / "helper_diagnostics.json"),
                    "artifacts": {},
                    "final_bpmn_path": None,
                },
            ):
                with mock.patch.object(
                    PIPELINE.subprocess,
                    "run",
                    side_effect=self._make_layout_runner([{"returncode": 0}]),
                ):
                    with mock.patch.object(
                        PIPELINE,
                        "validate_bpmn",
                        side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                    ):
                        result = PIPELINE.run_pipeline(
                            input_bpmn=input_path,
                            work_dir=tmpdir,
                            requested_mode="auto",
                            helper_command="fake-helper",
                            full_relayout=True,
                        )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(backend_selection["initial_backend"], "simple")
        self.assertFalse(backend_selection["selection"]["effective_preserve_existing_di"])
        self.assertFalse(backend_selection["selection"]["inferred_preserve_existing_di"])
        self.assertEqual(backend_selection["selection"]["di_quality"], "usable_di")
        self.assertEqual(manifest["fallback_reason_code"], PIPELINE.FALLBACK_SIMPLE_HELPER_FAILED)

    def test_simple_success_requires_postprocess_and_validate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            helper_output = Path(tmpdir) / "simple_bridge" / "helper_raw_output.bpmn"
            helper_output.parent.mkdir(parents=True, exist_ok=True)
            helper_output.write_text("<definitions id='helper' />", encoding="utf-8")

            with mock.patch.object(
                PIPELINE,
                "run_simple_mode_bridge",
                return_value={
                    "ok": True,
                    "failure_code": None,
                    "diagnostics": {},
                    "diagnostics_path": str(Path(tmpdir) / "helper_diagnostics.json"),
                    "artifacts": {},
                    "final_bpmn_path": str(helper_output),
                },
            ):
                with mock.patch.object(
                    PIPELINE.subprocess,
                    "run",
                    side_effect=self._make_layout_runner([{"returncode": 0}]),
                ):
                    with mock.patch.object(
                        PIPELINE,
                        "validate_bpmn",
                        side_effect=self._validate_by_name(
                            {"simple_postprocessed_output.bpmn": ([], [])}
                        ),
                    ):
                        result = PIPELINE.run_pipeline(
                            input_bpmn=input_path,
                            work_dir=tmpdir,
                            requested_mode="simple",
                            helper_command="fake-helper",
                        )

            manifest, backend_selection = self._load_outputs(result, tmpdir)
            output_hash = self._sha256(Path(tmpdir) / "simple_postprocessed_output.bpmn")

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["final_backend"], "simple")
        self.assertFalse(manifest["fallback_happened"])
        self.assertEqual(
            [entry["state"] for entry in backend_selection["state_history"]],
            [
                PIPELINE.STATE_SELECT,
                PIPELINE.STATE_PROJECT,
                PIPELINE.STATE_SIMPLE_LAYOUT,
                PIPELINE.STATE_POST_PROCESS,
                PIPELINE.STATE_VALIDATE,
                PIPELINE.STATE_FINALIZE,
            ],
        )
        self.assertEqual(
            Path(backend_selection["simple_bridge_result"]["final_bpmn_path"]).name,
            "helper_raw_output.bpmn",
        )
        self.assertEqual(
            Path(backend_selection["simple_validation_result"]["output_bpmn_path"]).name,
            "simple_postprocessed_output.bpmn",
        )
        self.assertEqual(
            backend_selection["simple_validation_result"]["output_bpmn_hash"],
            output_hash,
        )
        self.assertIn("layout_summary", manifest)
        self.assertEqual(manifest["layout_summary"]["final_mode"], "simple_postprocess_refine")
        self.assertEqual(manifest["layout_summary"]["layout_profile_family"], "simple_postprocess")
        self.assertIn("diagram_width_px", manifest["layout_summary"])
        self.assertIn("layout_requires_decomposition", manifest["layout_summary"])
        self.assertEqual(
            backend_selection["simple_postprocess_result"]["layout_final_mode"],
            "simple_postprocess_refine",
        )
        self.assertEqual(
            backend_selection["simple_postprocess_result"]["layout_profile_family"],
            "simple_postprocess",
        )
        self._assert_manifest_backend_selection_parity(manifest, backend_selection)

    def test_simple_postprocess_does_not_strict_preserve_partial_helper_di(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            helper_output = Path(tmpdir) / "simple_bridge" / "helper_raw_output.bpmn"
            helper_output.parent.mkdir(parents=True, exist_ok=True)
            helper_output.write_text(self._sequence_flow_bpmn(include_edge_di=False), encoding="utf-8")
            observed_commands = []

            def fake_layout_run(command, capture_output, text, check):
                observed_commands.append(list(command))
                output_path = Path(command[command.index("--output") + 1])
                report_path = Path(command[command.index("--report") + 1])
                report_path.write_text(
                    "# Layout Report\n\n- layout_hint_source: none\n- hint_applied: false\n",
                    encoding="utf-8",
                )
                self._write_layout_summary_for_command(command, output_path, status="PASS")
                output_path.write_text(self._sequence_flow_bpmn(include_edge_di=True), encoding="utf-8")
                return mock.Mock(returncode=0, stdout="ok", stderr="")

            with mock.patch.object(
                PIPELINE,
                "run_simple_mode_bridge",
                return_value={
                    "ok": True,
                    "failure_code": None,
                    "diagnostics": {"output": {"edge_di_complete": False}},
                    "diagnostics_path": str(Path(tmpdir) / "helper_diagnostics.json"),
                    "artifacts": {},
                    "final_bpmn_path": str(helper_output),
                },
            ):
                with mock.patch.object(PIPELINE.subprocess, "run", side_effect=fake_layout_run):
                    with mock.patch.object(
                        PIPELINE,
                        "validate_bpmn",
                        side_effect=self._validate_by_name({"simple_postprocessed_output.bpmn": ([], [])}),
                    ):
                        result = PIPELINE.run_pipeline(
                            input_bpmn=input_path,
                            work_dir=tmpdir,
                            requested_mode="simple",
                            helper_command="fake-helper",
                        )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["final_backend"], "simple")
        self.assertFalse(manifest["fallback_happened"])
        self.assertTrue(observed_commands)
        self.assertNotIn("--preserve-existing-di-strict", observed_commands[0])
        self.assertEqual(
            backend_selection["simple_postprocess_result"]["helper_di_quality"],
            "partial_di",
        )
        self.assertEqual(
            backend_selection["simple_postprocess_result"]["di_completeness"]["di_quality"],
            "usable_di",
        )

    def test_simple_postprocess_layout_report_final_fail_forces_native_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            helper_output = Path(tmpdir) / "simple_bridge" / "helper_raw_output.bpmn"
            helper_output.parent.mkdir(parents=True, exist_ok=True)
            helper_output.write_text(self._sequence_flow_bpmn(include_edge_di=False), encoding="utf-8")

            def fake_layout_run(command, capture_output, text, check):
                output_path = Path(command[command.index("--output") + 1])
                report_path = Path(command[command.index("--report") + 1])
                if output_path.name == "simple_postprocessed_output.bpmn":
                    report_path.write_text(
                        "\n".join(
                            [
                                "# Layout Report",
                                "",
                                "- layout_hint_source: none",
                                "- hint_applied: false",
                                "Final status: FAIL",
                            ]
                        ),
                        encoding="utf-8",
                    )
                    self._write_layout_summary_for_command(command, output_path, status="FAIL")
                    output_path.write_text(self._sequence_flow_bpmn(include_edge_di=True), encoding="utf-8")
                    return mock.Mock(returncode=0, stdout="simple-postprocess", stderr="")
                report_path.write_text(
                    "# Layout Report\n\n- layout_hint_source: none\n- hint_applied: false\nFinal status: PASS\n",
                    encoding="utf-8",
                )
                self._write_layout_summary_for_command(command, output_path, status="PASS")
                output_path.write_text("<definitions id='native' />", encoding="utf-8")
                return mock.Mock(returncode=0, stdout="native", stderr="")

            with mock.patch.object(
                PIPELINE,
                "run_simple_mode_bridge",
                return_value={
                    "ok": True,
                    "failure_code": None,
                    "diagnostics": {"output": {"edge_di_complete": False}},
                    "diagnostics_path": str(Path(tmpdir) / "helper_diagnostics.json"),
                    "artifacts": {},
                    "final_bpmn_path": str(helper_output),
                },
            ):
                with mock.patch.object(PIPELINE.subprocess, "run", side_effect=fake_layout_run):
                    with mock.patch.object(
                        PIPELINE,
                        "validate_bpmn",
                        side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                    ):
                        result = PIPELINE.run_pipeline(
                            input_bpmn=input_path,
                            work_dir=tmpdir,
                            requested_mode="simple",
                            helper_command="fake-helper",
                        )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["final_backend"], "native")
        self.assertTrue(manifest["fallback_happened"])
        self.assertEqual(manifest["fallback_reason_code"], PIPELINE.FALLBACK_SIMPLE_HARD_CHECK_FAILED)
        self.assertEqual(
            backend_selection["simple_postprocess_result"]["failure_code"],
            PIPELINE.DETAIL_SIMPLE_LAYOUT_POLICY_FAILED,
        )
        self.assertEqual(
            backend_selection["simple_postprocess_result"]["layout_policy_status"],
            "FAIL",
        )

    def test_simple_postprocess_missing_layout_summary_json_forces_native_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            helper_output = Path(tmpdir) / "simple_bridge" / "helper_raw_output.bpmn"
            helper_output.parent.mkdir(parents=True, exist_ok=True)
            helper_output.write_text(self._sequence_flow_bpmn(include_edge_di=False), encoding="utf-8")

            def fake_layout_run(command, capture_output, text, check):
                output_path = Path(command[command.index("--output") + 1])
                report_path = Path(command[command.index("--report") + 1])
                report_path.write_text(
                    "# Layout Report\n\n- layout_hint_source: none\n- hint_applied: false\nFinal status: PASS\n",
                    encoding="utf-8",
                )
                if output_path.name == "simple_postprocessed_output.bpmn":
                    output_path.write_text(self._sequence_flow_bpmn(include_edge_di=True), encoding="utf-8")
                    return mock.Mock(returncode=0, stdout="simple-postprocess", stderr="")
                self._write_layout_summary_for_command(command, output_path, status="PASS")
                output_path.write_text("<definitions id='native' />", encoding="utf-8")
                return mock.Mock(returncode=0, stdout="native", stderr="")

            with mock.patch.object(
                PIPELINE,
                "run_simple_mode_bridge",
                return_value={
                    "ok": True,
                    "failure_code": None,
                    "diagnostics": {"output": {"edge_di_complete": False}},
                    "diagnostics_path": str(Path(tmpdir) / "helper_diagnostics.json"),
                    "artifacts": {},
                    "final_bpmn_path": str(helper_output),
                },
            ):
                with mock.patch.object(PIPELINE.subprocess, "run", side_effect=fake_layout_run):
                    with mock.patch.object(
                        PIPELINE,
                        "validate_bpmn",
                        side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                    ):
                        result = PIPELINE.run_pipeline(
                            input_bpmn=input_path,
                            work_dir=tmpdir,
                            requested_mode="simple",
                            helper_command="fake-helper",
                        )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["final_backend"], "native")
        self.assertTrue(manifest["fallback_happened"])
        self.assertEqual(
            manifest["fallback_reason_code"],
            PIPELINE.FALLBACK_SIMPLE_HARD_CHECK_FAILED,
        )
        self.assertEqual(
            backend_selection["simple_postprocess_result"]["failure_code"],
            PIPELINE.DETAIL_SIMPLE_LAYOUT_SUMMARY_INVALID,
        )
        self.assertEqual(
            backend_selection["simple_postprocess_result"]["layout_summary_error"],
            "layout_summary_missing",
        )

    def test_simple_postprocess_materializes_edge_di_for_sequence_flows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            helper_output = Path(tmpdir) / "simple_bridge" / "helper_raw_output.bpmn"
            helper_output.parent.mkdir(parents=True, exist_ok=True)
            helper_output.write_text(self._sequence_flow_bpmn(include_edge_di=False), encoding="utf-8")
            observed_commands = []

            def fake_layout_run(command, capture_output, text, check):
                observed_commands.append(list(command))
                output_path = Path(command[command.index("--output") + 1])
                report_path = Path(command[command.index("--report") + 1])
                report_path.write_text("# Layout Report\n\n- layout_hint_source: none\n- hint_applied: false\n", encoding="utf-8")
                self._write_layout_summary_for_command(command, output_path, status="PASS")
                output_path.write_text(self._sequence_flow_bpmn(include_edge_di=True), encoding="utf-8")
                return mock.Mock(returncode=0, stdout="ok", stderr="")

            with mock.patch.object(
                PIPELINE,
                "run_simple_mode_bridge",
                return_value={
                    "ok": True,
                    "failure_code": None,
                    "diagnostics": {"output": {"edge_di_complete": False}},
                    "diagnostics_path": str(Path(tmpdir) / "helper_diagnostics.json"),
                    "artifacts": {},
                    "final_bpmn_path": str(helper_output),
                },
            ):
                with mock.patch.object(PIPELINE.subprocess, "run", side_effect=fake_layout_run):
                    with mock.patch.object(
                        PIPELINE,
                        "validate_bpmn",
                        side_effect=self._validate_by_name({"simple_postprocessed_output.bpmn": ([], [])}),
                    ):
                        result = PIPELINE.run_pipeline(
                            input_bpmn=input_path,
                            work_dir=tmpdir,
                            requested_mode="simple",
                            helper_command="fake-helper",
                        )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["final_backend"], "simple")
        self.assertFalse(manifest["fallback_happened"])
        self.assertTrue(
            backend_selection["simple_postprocess_result"]["di_completeness"]["edge_di_complete"]
        )
        self.assertEqual(
            backend_selection["simple_postprocess_result"]["di_completeness"]["sequence_flow_count"],
            1,
        )
        self.assertEqual(
            backend_selection["simple_postprocess_result"]["di_completeness"]["bpmn_edge_count"],
            1,
        )
        self.assertNotIn("--preserve-existing-di-strict", observed_commands[0])

    def test_simple_pipeline_falls_back_when_final_edge_di_incomplete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            helper_output = Path(tmpdir) / "simple_bridge" / "helper_raw_output.bpmn"
            helper_output.parent.mkdir(parents=True, exist_ok=True)
            helper_output.write_text(self._sequence_flow_bpmn(include_edge_di=False), encoding="utf-8")

            def fake_layout_run(command, capture_output, text, check):
                output_path = Path(command[command.index("--output") + 1])
                report_path = Path(command[command.index("--report") + 1])
                report_path.write_text("# Layout Report\n\n- layout_hint_source: none\n- hint_applied: false\n", encoding="utf-8")
                self._write_layout_summary_for_command(command, output_path, status="PASS")
                if output_path.name == "simple_postprocessed_output.bpmn":
                    output_path.write_text(self._sequence_flow_bpmn(include_edge_di=False), encoding="utf-8")
                    return mock.Mock(returncode=0, stdout="simple-postprocess", stderr="")
                output_path.write_text("<definitions id='native' />", encoding="utf-8")
                return mock.Mock(returncode=0, stdout="native", stderr="")

            with mock.patch.object(
                PIPELINE,
                "run_simple_mode_bridge",
                return_value={
                    "ok": True,
                    "failure_code": None,
                    "diagnostics": {"output": {"edge_di_complete": False}},
                    "diagnostics_path": str(Path(tmpdir) / "helper_diagnostics.json"),
                    "artifacts": {},
                    "final_bpmn_path": str(helper_output),
                },
            ):
                with mock.patch.object(PIPELINE.subprocess, "run", side_effect=fake_layout_run):
                    with mock.patch.object(
                        PIPELINE,
                        "validate_bpmn",
                        side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                    ):
                        result = PIPELINE.run_pipeline(
                            input_bpmn=input_path,
                            work_dir=tmpdir,
                            requested_mode="simple",
                            helper_command="fake-helper",
                        )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["final_backend"], "native")
        self.assertTrue(manifest["fallback_happened"])
        self.assertEqual(manifest["fallback_reason_code"], PIPELINE.FALLBACK_SIMPLE_HARD_CHECK_FAILED)
        self.assertEqual(
            backend_selection["simple_postprocess_result"]["failure_code"],
            PIPELINE.DETAIL_SIMPLE_EDGE_DI_INCOMPLETE,
        )
        self.assertEqual(
            backend_selection["fallback_trigger_category"],
            PIPELINE.FALLBACK_SIMPLE_HARD_CHECK_FAILED,
        )

    def test_native_backend_selection_records_output_bpmn_hash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            native_xml = "<definitions id='native-hash' />"
            with mock.patch.object(
                PIPELINE.subprocess,
                "run",
                side_effect=self._make_layout_runner([{"returncode": 0, "output_text": native_xml}]),
            ):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="native",
                    )

            _, backend_selection = self._load_outputs(result, tmpdir)
            output_hash = self._sha256(Path(tmpdir) / "native_layout_output.bpmn")

        self.assertEqual(
            backend_selection["native_result"]["output_bpmn_hash"],
            output_hash,
        )

    def test_layout_hints_are_passed_to_layout_and_reflected_in_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            hint_payload = '{"max_shape_shift": 90}'
            observed_commands = []
            report_text = "\n".join(
                [
                    "# BPMN Layout Report",
                    "",
                    "- layout_hint_source: inline_json",
                    "- hint_applied: true",
                ]
            )

            def capture_run(command, capture_output, text, check):
                observed_commands.append(list(command))
                return self._make_layout_runner(
                    [{"returncode": 0, "report_text": report_text}]
                )(command, capture_output, text, check)

            with mock.patch.object(
                PIPELINE.subprocess,
                "run",
                side_effect=capture_run,
            ):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="native",
                        enable_layout_hints=True,
                        layout_hints_json=hint_payload,
                    )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertTrue(observed_commands)
        layout_cmd = observed_commands[0]
        self.assertIn("--enable-layout-hints", layout_cmd)
        self.assertIn("--layout-hints-json", layout_cmd)
        self.assertEqual(
            layout_cmd[layout_cmd.index("--layout-hints-json") + 1],
            hint_payload,
        )
        self.assertEqual(manifest["layout_hint_source"], "inline_json")
        self.assertTrue(manifest["hint_applied"])
        self.assertEqual(backend_selection["layout_hint_source"], "inline_json")
        self.assertTrue(backend_selection["hint_applied"])

    def test_human_summary_is_manifest_derived_view(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            with mock.patch.object(
                PIPELINE.subprocess,
                "run",
                side_effect=self._make_layout_runner([{"returncode": 0}]),
            ):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="native",
                    )

            manifest = self._read_json(result["manifest_path"])
            human_summary = self._read_text(Path(tmpdir) / "human_summary.md")

        self.assertIn(f"- manifest_schema_version: `{manifest['manifest_schema_version']}`", human_summary)
        self.assertIn(f"- linked_report_schema_version: `{manifest['linked_report_schema_version']}`", human_summary)
        self.assertIn(f"- runtime_target: `{manifest['runtime_target']}`", human_summary)
        self.assertIn(
            f"- layout_report: presence=`{manifest['artifacts']['layout_report']['presence']}` status=`{manifest['artifacts']['layout_report']['status']}`",
            human_summary,
        )
        self.assertIn(
            f"- typed_issue_targets: presence=`{manifest['artifacts']['typed_issue_targets']['presence']}` status=`{manifest['artifacts']['typed_issue_targets']['status']}`",
            human_summary,
        )

    def test_context_facts_are_promoted_into_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            with mock.patch.object(
                PIPELINE.subprocess,
                "run",
                side_effect=self._make_layout_runner([{"returncode": 0}]),
            ):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="native",
                        facts={
                            "build_version": "build-42",
                            "skill_version": "skill-7",
                            "runtime_target": "acceptance-harness",
                            "scenario_id": "scenario-native",
                            "fixture_id": "fixture-basic",
                            "traceability_count": 3,
                            "assumptions_count": 1,
                        },
                    )

            manifest = self._read_json(result["manifest_path"])

        self.assertEqual(manifest["build_version"], "build-42")
        self.assertEqual(manifest["skill_version"], "skill-7")
        self.assertEqual(manifest["runtime_target"], "acceptance-harness")
        self.assertEqual(manifest["scenario_id"], "scenario-native")
        self.assertEqual(manifest["fixture_id"], "fixture-basic")
        self.assertEqual(manifest["traceability_count"], 3)
        self.assertEqual(manifest["assumptions_count"], 1)

    def test_simple_helper_failure_falls_back_to_native(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)

            with mock.patch.object(
                PIPELINE,
                "run_simple_mode_bridge",
                return_value={
                    "ok": False,
                    "failure_code": "helper_launch_failed",
                    "diagnostics": {},
                    "diagnostics_path": str(Path(tmpdir) / "helper_diagnostics.json"),
                    "artifacts": {},
                    "final_bpmn_path": None,
                },
            ):
                with mock.patch.object(
                    PIPELINE.subprocess,
                    "run",
                    side_effect=self._make_layout_runner([{"returncode": 0}]),
                ):
                    with mock.patch.object(
                        PIPELINE,
                        "validate_bpmn",
                        side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                    ):
                        result = PIPELINE.run_pipeline(
                            input_bpmn=input_path,
                            work_dir=tmpdir,
                            requested_mode="simple",
                            helper_command="fake-helper",
                        )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["final_backend"], "native")
        self.assertTrue(manifest["fallback_happened"])
        self.assertEqual(manifest["fallback_reason_code"], PIPELINE.FALLBACK_SIMPLE_HELPER_FAILED)
        self.assertEqual(backend_selection["fallback_trigger_detail_code"], "helper_launch_failed")
        self.assertEqual(
            [entry["state"] for entry in backend_selection["state_history"]],
            [
                PIPELINE.STATE_SELECT,
                PIPELINE.STATE_PROJECT,
                PIPELINE.STATE_SIMPLE_LAYOUT,
                PIPELINE.STATE_FALLBACK_NATIVE,
                PIPELINE.STATE_VALIDATE,
                PIPELINE.STATE_FINALIZE,
            ],
        )
        self._assert_manifest_backend_selection_parity(manifest, backend_selection)

    def test_simple_postprocess_failure_falls_back_to_native(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            helper_output = Path(tmpdir) / "simple_bridge" / "helper_raw_output.bpmn"
            helper_output.parent.mkdir(parents=True, exist_ok=True)
            helper_output.write_text("<definitions id='helper' />", encoding="utf-8")

            with mock.patch.object(
                PIPELINE,
                "run_simple_mode_bridge",
                return_value={
                    "ok": True,
                    "failure_code": None,
                    "diagnostics": {},
                    "diagnostics_path": str(Path(tmpdir) / "helper_diagnostics.json"),
                    "artifacts": {},
                    "final_bpmn_path": str(helper_output),
                },
            ):
                with mock.patch.object(
                    PIPELINE,
                    "_post_process_simple",
                    return_value={
                        "ok": False,
                        "failure_code": PIPELINE.DETAIL_SIMPLE_POSTPROCESS_LAYOUT_FAILED,
                        "layout_status": "FAIL",
                        "layout_report_path": str(Path(tmpdir) / "layout_report.md"),
                        "layout_hint_source": "none",
                        "hint_applied": False,
                        "output_bpmn_path": None,
                        "output_bpmn_hash": None,
                        "layout_returncode": 1,
                        "layout_stdout": "",
                        "layout_stderr": "post-process failed",
                    },
                ):
                    with mock.patch.object(
                        PIPELINE.subprocess,
                        "run",
                        side_effect=self._make_layout_runner([{"returncode": 0}]),
                    ):
                        with mock.patch.object(
                            PIPELINE,
                            "validate_bpmn",
                            side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                        ):
                            result = PIPELINE.run_pipeline(
                                input_bpmn=input_path,
                                work_dir=tmpdir,
                                requested_mode="simple",
                                helper_command="fake-helper",
                            )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["fallback_reason_code"], PIPELINE.FALLBACK_SIMPLE_POSTPROCESS_FAILED)
        self.assertEqual(backend_selection["fallback_trigger_detail_code"], PIPELINE.DETAIL_SIMPLE_POSTPROCESS_LAYOUT_FAILED)
        self.assertEqual(
            [entry["state"] for entry in backend_selection["state_history"]],
            [
                PIPELINE.STATE_SELECT,
                PIPELINE.STATE_PROJECT,
                PIPELINE.STATE_SIMPLE_LAYOUT,
                PIPELINE.STATE_POST_PROCESS,
                PIPELINE.STATE_FALLBACK_NATIVE,
                PIPELINE.STATE_VALIDATE,
                PIPELINE.STATE_FINALIZE,
            ],
        )
        self._assert_manifest_backend_selection_parity(manifest, backend_selection)

    def test_build_preview_updates_manifest_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            observed = {}

            def fake_preview(manifest_path, output_dir):
                preview_report_path = Path(tmpdir) / "preview_report.json"
                typed_targets_path = Path(tmpdir) / "typed_issue_targets.json"
                preview_report_path.write_text(
                    json.dumps({"status": "PASS", "schema_version": "1"}, indent=2) + "\n",
                    encoding="utf-8",
                )
                typed_targets_path.write_text(
                    json.dumps({"schema_version": "1", "counts": {"total": 0}, "items": []}, indent=2) + "\n",
                    encoding="utf-8",
                )
                observed["manifest_path"] = str(manifest_path)
                observed["output_dir"] = str(output_dir)
                return {
                    "ok": True,
                    "preview_schema_version": "1",
                    "build_timestamp": "not-provided",
                    "index_path": str(Path(tmpdir) / "preview_artifacts" / "index.html"),
                    "assets_dir": str(Path(tmpdir) / "preview_artifacts" / "assets"),
                    "preview_report_path": str(preview_report_path),
                    "typed_issue_targets_path": str(typed_targets_path),
                    "audit": {"ok": True},
                }

            with mock.patch.object(
                PIPELINE.subprocess,
                "run",
                side_effect=self._make_layout_runner([{"returncode": 0}]),
            ):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    with mock.patch.object(PIPELINE, "build_preview_artifacts", side_effect=fake_preview):
                        result = PIPELINE.run_pipeline(
                            input_bpmn=input_path,
                            work_dir=tmpdir,
                            requested_mode="native",
                            build_preview=True,
                        )

            manifest = self._read_json(result["manifest_path"])

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["preview_status"], "PASS")
        self.assertEqual(manifest["artifacts"]["preview_report"]["presence"], "present")
        self.assertEqual(manifest["artifacts"]["preview_report"]["status"], "PASS")
        self.assertEqual(manifest["artifacts"]["typed_issue_targets"]["presence"], "present")
        self.assertEqual(manifest["artifacts"]["typed_issue_targets"]["status"], "PASS")
        self.assertEqual(observed["manifest_path"], str(Path(tmpdir) / "run_manifest.json"))
        self.assertEqual(observed["output_dir"], str(Path(tmpdir) / "preview_artifacts"))

    def test_build_preview_failure_marks_pipeline_fail_and_writes_preview_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            with mock.patch.object(
                PIPELINE.subprocess,
                "run",
                side_effect=self._make_layout_runner([{"returncode": 0}]),
            ):
                with mock.patch.object(
                    PIPELINE,
                    "validate_bpmn",
                    side_effect=self._validate_by_name({"native_layout_output.bpmn": ([], [])}),
                ):
                    with mock.patch.object(
                        PIPELINE,
                        "build_preview_artifacts",
                        side_effect=RuntimeError("preview exploded"),
                    ):
                        result = PIPELINE.run_pipeline(
                            input_bpmn=input_path,
                            work_dir=tmpdir,
                            requested_mode="native",
                            build_preview=True,
                        )

            manifest = self._read_json(result["manifest_path"])

        self.assertFalse(result["ok"])
        self.assertEqual(manifest["preview_status"], "FAIL")
        self.assertEqual(manifest["artifacts"]["preview_report"]["presence"], "present")
        self.assertEqual(manifest["artifacts"]["preview_report"]["status"], "FAIL")
        self.assertEqual(manifest["artifacts"]["typed_issue_targets"]["presence"], "not_applicable")
        self.assertEqual(manifest["artifacts"]["typed_issue_targets"]["status"], "SKIPPED")

    def test_simple_hard_check_failure_falls_back_to_native(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)
            helper_output = Path(tmpdir) / "simple_bridge" / "helper_raw_output.bpmn"
            helper_output.parent.mkdir(parents=True, exist_ok=True)
            helper_output.write_text("<definitions id='helper' />", encoding="utf-8")

            with mock.patch.object(
                PIPELINE,
                "run_simple_mode_bridge",
                return_value={
                    "ok": True,
                    "failure_code": None,
                    "diagnostics": {},
                    "diagnostics_path": str(Path(tmpdir) / "helper_diagnostics.json"),
                    "artifacts": {},
                    "final_bpmn_path": str(helper_output),
                },
            ):
                with mock.patch.object(
                    PIPELINE.subprocess,
                    "run",
                    side_effect=self._make_layout_runner([{"returncode": 0}, {"returncode": 0}]),
                ):
                    with mock.patch.object(
                        PIPELINE,
                        "validate_bpmn",
                        side_effect=self._validate_by_name(
                            {
                                "simple_postprocessed_output.bpmn": (["semantic fail"], []),
                                "native_layout_output.bpmn": ([], []),
                            }
                        ),
                    ):
                        result = PIPELINE.run_pipeline(
                            input_bpmn=input_path,
                            work_dir=tmpdir,
                            requested_mode="simple",
                            helper_command="fake-helper",
                        )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertTrue(result["ok"])
        self.assertEqual(manifest["final_backend"], "native")
        self.assertEqual(manifest["fallback_reason_code"], PIPELINE.FALLBACK_SIMPLE_HARD_CHECK_FAILED)
        self.assertEqual(backend_selection["fallback_trigger_detail_code"], PIPELINE.DETAIL_SIMPLE_VALIDATION_FAILED)
        self.assertEqual(
            [entry["state"] for entry in backend_selection["state_history"]],
            [
                PIPELINE.STATE_SELECT,
                PIPELINE.STATE_PROJECT,
                PIPELINE.STATE_SIMPLE_LAYOUT,
                PIPELINE.STATE_POST_PROCESS,
                PIPELINE.STATE_VALIDATE,
                PIPELINE.STATE_FALLBACK_NATIVE,
                PIPELINE.STATE_VALIDATE,
                PIPELINE.STATE_FINALIZE,
            ],
        )
        self._assert_manifest_backend_selection_parity(manifest, backend_selection)

    def test_simple_fail_and_native_fail_returns_fail_category(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self._input_file(tmpdir)

            with mock.patch.object(
                PIPELINE,
                "run_simple_mode_bridge",
                return_value={
                    "ok": False,
                    "failure_code": "projection_generation_failed",
                    "diagnostics": {},
                    "diagnostics_path": str(Path(tmpdir) / "helper_diagnostics.json"),
                    "artifacts": {},
                    "final_bpmn_path": None,
                },
            ):
                with mock.patch.object(
                    PIPELINE.subprocess,
                    "run",
                    side_effect=self._make_layout_runner(
                        [{"returncode": 1, "stdout": "", "stderr": "native failed", "write_output": False}]
                    ),
                ):
                    result = PIPELINE.run_pipeline(
                        input_bpmn=input_path,
                        work_dir=tmpdir,
                        requested_mode="simple",
                        helper_command="fake-helper",
                    )

            manifest, backend_selection = self._load_outputs(result, tmpdir)

        self.assertFalse(result["ok"])
        self.assertEqual(manifest["final_backend"], "native")
        self.assertEqual(manifest["layout_status"], "FAIL")
        self.assertEqual(manifest["semantic_status"], "FAIL")
        self.assertEqual(manifest["fallback_reason_code"], PIPELINE.FALLBACK_NATIVE_FAILED)
        self.assertEqual(backend_selection["fallback_trigger_category"], PIPELINE.FALLBACK_SIMPLE_HELPER_FAILED)
        self.assertEqual(backend_selection["fallback_trigger_detail_code"], "projection_generation_failed")
        self.assertEqual(backend_selection["final_failure_category"], PIPELINE.FALLBACK_NATIVE_FAILED)
        self.assertEqual(backend_selection["native_fallback_failure_code"], "native_layout_failed")
        self.assertEqual(backend_selection["state"], PIPELINE.STATE_FAIL)
        self.assertEqual(
            [entry["state"] for entry in backend_selection["state_history"]],
            [
                PIPELINE.STATE_SELECT,
                PIPELINE.STATE_PROJECT,
                PIPELINE.STATE_SIMPLE_LAYOUT,
                PIPELINE.STATE_FALLBACK_NATIVE,
                PIPELINE.STATE_VALIDATE,
                PIPELINE.STATE_FAIL,
            ],
        )
        self._assert_manifest_backend_selection_parity(manifest, backend_selection)


if __name__ == "__main__":
    unittest.main()
