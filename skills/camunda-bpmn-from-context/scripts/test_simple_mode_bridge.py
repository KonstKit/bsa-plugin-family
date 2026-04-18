#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parent / "simple_mode_bridge.py"
SPEC = importlib.util.spec_from_file_location("simple_mode_bridge", SCRIPT_PATH)
BRIDGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRIDGE)

BASIC_BPMN = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<bpmn:definitions xmlns:bpmn=\"http://www.omg.org/spec/BPMN/20100524/MODEL\" id=\"Definitions_1\" targetNamespace=\"http://example.com/test\">
  <bpmn:process id=\"Process_1\" isExecutable=\"true\">
    <bpmn:startEvent id=\"Start_1\" />
    <bpmn:endEvent id=\"End_1\" />
    <bpmn:sequenceFlow id=\"Flow_1\" sourceRef=\"Start_1\" targetRef=\"End_1\" />
  </bpmn:process>
</bpmn:definitions>
"""

ZEEBE_BPMN = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<bpmn:definitions xmlns:bpmn=\"http://www.omg.org/spec/BPMN/20100524/MODEL\"
                  xmlns:zeebe=\"http://camunda.org/schema/zeebe/1.0\"
                  id=\"Definitions_1\"
                  targetNamespace=\"http://example.com/test\">
  <bpmn:process id=\"Process_1\" isExecutable=\"true\">
    <bpmn:startEvent id=\"Start_1\" />
    <bpmn:serviceTask id=\"Task_1\">
      <bpmn:extensionElements>
        <zeebe:taskDefinition type=\"job-type\" retries=\"3\" />
      </bpmn:extensionElements>
    </bpmn:serviceTask>
    <bpmn:endEvent id=\"End_1\" />
    <bpmn:sequenceFlow id=\"Flow_1\" sourceRef=\"Start_1\" targetRef=\"Task_1\" />
    <bpmn:sequenceFlow id=\"Flow_2\" sourceRef=\"Task_1\" targetRef=\"End_1\" />
  </bpmn:process>
</bpmn:definitions>
"""


def write_text(path, content):
    Path(path).write_text(content, encoding="utf-8")


class SimpleModeBridgeTests(unittest.TestCase):
    def test_missing_helper_command_maps_to_launch_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.bpmn"
            write_text(input_path, BASIC_BPMN)
            result = BRIDGE.run_simple_mode_bridge(
                input_path,
                Path(tmpdir) / "work",
                "",
                timeout_seconds=5,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_code"], BRIDGE.FAILURE_HELPER_LAUNCH)

    def test_non_zero_helper_exit_maps_to_runtime_failure_and_preserves_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.bpmn"
            write_text(input_path, BASIC_BPMN)

            def fake_run(command, capture_output, text, timeout, check):
                diagnostics_path = Path(command[command.index("--diagnostics") + 1])
                diagnostics_path.write_text(
                    json.dumps(
                        {
                            "version": "1.0",
                            "status": "FAIL",
                            "errors": ["helper_crashed"],
                            "warnings": [],
                            "helper": {"launched": True},
                            "output": {
                                "bpmn_written": False,
                                "sequence_flow_count": 1,
                                "bpmn_shape_count": 0,
                                "bpmn_edge_count": 0,
                                "edge_without_two_waypoints_count": 0,
                                "edge_di_complete": False,
                                "di_quality": "no_di",
                            },
                            "runtime_target": {
                                "namespace_uris_detected": [],
                                "requires_namespace_preservation": False,
                                "requires_extension_preservation": False,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                return mock.Mock(returncode=7, stdout="", stderr="helper failed")

            with mock.patch.object(BRIDGE.subprocess, "run", side_effect=fake_run):
                result = BRIDGE.run_simple_mode_bridge(
                    input_path,
                    Path(tmpdir) / "work",
                    "fake-helper",
                    timeout_seconds=5,
                )

            saved = json.loads(Path(result["diagnostics_path"]).read_text(encoding="utf-8"))

        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_code"], BRIDGE.FAILURE_HELPER_RUNTIME)
        self.assertEqual(saved["failure_code"], BRIDGE.FAILURE_HELPER_RUNTIME)
        self.assertEqual(saved["helper"]["returncode"], 7)
        self.assertIn("raw_helper_diagnostics", saved)

    def test_helper_reported_fail_status_maps_to_runtime_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.bpmn"
            write_text(input_path, BASIC_BPMN)

            def fake_run(command, capture_output, text, timeout, check):
                diagnostics_path = Path(command[command.index("--diagnostics") + 1])
                output_path = Path(command[command.index("--output") + 1])
                diagnostics_path.write_text(
                    json.dumps(
                        {
                            "version": "1.0",
                            "status": "FAIL",
                            "errors": ["unsupported_construct"],
                            "warnings": [],
                            "helper": {"launched": True, "command": ["fake-helper"]},
                            "output": {
                                "bpmn_written": True,
                                "sequence_flow_count": 1,
                                "bpmn_shape_count": 2,
                                "bpmn_edge_count": 0,
                                "edge_without_two_waypoints_count": 0,
                                "edge_di_complete": False,
                                "di_quality": "partial_di",
                            },
                            "runtime_target": {
                                "namespace_uris_detected": [],
                                "requires_namespace_preservation": False,
                                "requires_extension_preservation": False,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                write_text(output_path, BASIC_BPMN)
                return mock.Mock(returncode=0, stdout="ok", stderr="")

            with mock.patch.object(BRIDGE.subprocess, "run", side_effect=fake_run):
                result = BRIDGE.run_simple_mode_bridge(
                    input_path,
                    Path(tmpdir) / "work",
                    "fake-helper",
                    timeout_seconds=5,
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_code"], BRIDGE.FAILURE_HELPER_RUNTIME)

    def test_invalid_diagnostics_contract_maps_to_invalid_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.bpmn"
            write_text(input_path, BASIC_BPMN)
            work_dir = Path(tmpdir) / "work"

            def fake_run(command, capture_output, text, timeout, check):
                diagnostics_path = Path(command[command.index("--diagnostics") + 1])
                output_path = Path(command[command.index("--output") + 1])
                diagnostics_path.write_text(
                    json.dumps({"status": "PASS"}),
                    encoding="utf-8",
                )
                write_text(output_path, BASIC_BPMN)
                return mock.Mock(returncode=0, stdout="ok", stderr="")

            with mock.patch.object(BRIDGE.subprocess, "run", side_effect=fake_run):
                result = BRIDGE.run_simple_mode_bridge(
                    input_path,
                    work_dir,
                    "fake-helper",
                    timeout_seconds=5,
                )
            saved = json.loads(Path(result["diagnostics_path"]).read_text(encoding="utf-8"))

        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_code"], BRIDGE.FAILURE_HELPER_INVALID_OUTPUT)
        self.assertEqual(saved["failure_code"], BRIDGE.FAILURE_HELPER_INVALID_OUTPUT)
        self.assertTrue(saved["invariant_violations"])

    def test_success_writes_projection_sidecar_and_default_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.bpmn"
            write_text(input_path, BASIC_BPMN)
            work_dir = Path(tmpdir) / "work"

            def fake_run(command, capture_output, text, timeout, check):
                output_path = Path(command[command.index("--output") + 1])
                write_text(output_path, BASIC_BPMN)
                return mock.Mock(returncode=0, stdout="ok", stderr="")

            with mock.patch.object(BRIDGE.subprocess, "run", side_effect=fake_run):
                result = BRIDGE.run_simple_mode_bridge(
                    input_path,
                    work_dir,
                    "fake-helper",
                    timeout_seconds=5,
                )

            sidecar = json.loads((work_dir / "projection_sidecar.json").read_text(encoding="utf-8"))
            diagnostics = json.loads((work_dir / "helper_diagnostics.json").read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(sidecar["version"], "1.0")
        self.assertEqual(sidecar["projection_mode"], "passthrough_projection")
        self.assertIn("excluded_constructs", sidecar)
        self.assertEqual(sidecar["id_map"]["strategy"], "identity")
        self.assertEqual(diagnostics["status"], "PASS")
        self.assertEqual(diagnostics["version"], "1.0")
        self.assertTrue(diagnostics["output"]["bpmn_written"])
        self.assertIn("sequence_flow_count", diagnostics["output"])
        self.assertIn("bpmn_edge_count", diagnostics["output"])
        self.assertIn("edge_di_complete", diagnostics["output"])
        self.assertEqual(diagnostics["output"]["di_quality"], "no_di")
        self.assertFalse(result["layout_ready"])

    def test_success_normalizes_runtime_target_from_input_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.bpmn"
            write_text(input_path, ZEEBE_BPMN)
            work_dir = Path(tmpdir) / "work"

            def fake_run(command, capture_output, text, timeout, check):
                output_path = Path(command[command.index("--output") + 1])
                diagnostics_path = Path(command[command.index("--diagnostics") + 1])
                write_text(output_path, ZEEBE_BPMN)
                diagnostics_path.write_text(
                    json.dumps(
                        {
                            "version": "1.0",
                            "status": "PASS",
                            "errors": [],
                            "warnings": [],
                            "helper": {"launched": True},
                            "output": {
                                "bpmn_written": True,
                                "sequence_flow_count": 2,
                                "bpmn_shape_count": 3,
                                "bpmn_edge_count": 2,
                                "edge_without_two_waypoints_count": 0,
                                "edge_di_complete": True,
                                "di_quality": "usable_di",
                            },
                            "runtime_target": {
                                "namespace_uris_detected": [],
                                "requires_namespace_preservation": False,
                                "requires_extension_preservation": False,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                return mock.Mock(returncode=0, stdout="ok", stderr="")

            with mock.patch.object(BRIDGE.subprocess, "run", side_effect=fake_run):
                result = BRIDGE.run_simple_mode_bridge(
                    input_path,
                    work_dir,
                    "fake-helper",
                    timeout_seconds=5,
                )

            diagnostics = json.loads((work_dir / "helper_diagnostics.json").read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertIn("http://camunda.org/schema/zeebe/1.0", diagnostics["runtime_target"]["namespace_uris_detected"])
        self.assertTrue(diagnostics["runtime_target"]["requires_namespace_preservation"])
        self.assertTrue(diagnostics["runtime_target"]["requires_extension_preservation"])

    def test_success_drops_helper_invented_runtime_target_for_plain_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.bpmn"
            write_text(input_path, BASIC_BPMN)
            work_dir = Path(tmpdir) / "work"

            def fake_run(command, capture_output, text, timeout, check):
                output_path = Path(command[command.index("--output") + 1])
                diagnostics_path = Path(command[command.index("--diagnostics") + 1])
                write_text(output_path, BASIC_BPMN)
                diagnostics_path.write_text(
                    json.dumps(
                        {
                            "version": "1.0",
                            "status": "PASS",
                            "errors": [],
                            "warnings": [],
                            "helper": {"launched": True},
                            "output": {
                                "bpmn_written": True,
                                "sequence_flow_count": 1,
                                "bpmn_shape_count": 2,
                                "bpmn_edge_count": 1,
                                "edge_without_two_waypoints_count": 0,
                                "edge_di_complete": True,
                                "di_quality": "usable_di",
                            },
                            "runtime_target": {
                                "namespace_uris_detected": ["http://camunda.org/schema/zeebe/1.0"],
                                "requires_namespace_preservation": True,
                                "requires_extension_preservation": True,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                return mock.Mock(returncode=0, stdout="ok", stderr="")

            with mock.patch.object(BRIDGE.subprocess, "run", side_effect=fake_run):
                result = BRIDGE.run_simple_mode_bridge(
                    input_path,
                    work_dir,
                    "fake-helper",
                    timeout_seconds=5,
                )

            diagnostics = json.loads((work_dir / "helper_diagnostics.json").read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(diagnostics["runtime_target"]["namespace_uris_detected"], [])
        self.assertFalse(diagnostics["runtime_target"]["requires_namespace_preservation"])
        self.assertFalse(diagnostics["runtime_target"]["requires_extension_preservation"])

    def test_success_marks_layout_ready_when_helper_reports_complete_edge_di(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.bpmn"
            write_text(input_path, BASIC_BPMN)
            work_dir = Path(tmpdir) / "work"

            def fake_run(command, capture_output, text, timeout, check):
                output_path = Path(command[command.index("--output") + 1])
                diagnostics_path = Path(command[command.index("--diagnostics") + 1])
                write_text(output_path, BASIC_BPMN)
                diagnostics_path.write_text(
                    json.dumps(
                        {
                            "version": "1.0",
                            "status": "PASS",
                            "errors": [],
                            "warnings": [],
                            "helper": {"launched": True},
                            "output": {
                                "bpmn_written": True,
                                "sequence_flow_count": 1,
                                "bpmn_shape_count": 2,
                                "bpmn_edge_count": 1,
                                "edge_without_two_waypoints_count": 0,
                                "edge_di_complete": True,
                                "di_quality": "usable_di",
                            },
                            "runtime_target": {
                                "namespace_uris_detected": [],
                                "requires_namespace_preservation": False,
                                "requires_extension_preservation": False,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                return mock.Mock(returncode=0, stdout="ok", stderr="")

            with mock.patch.object(BRIDGE.subprocess, "run", side_effect=fake_run):
                result = BRIDGE.run_simple_mode_bridge(
                    input_path,
                    work_dir,
                    "fake-helper",
                    timeout_seconds=5,
                )

        self.assertTrue(result["ok"])
        self.assertTrue(result["layout_ready"])
        self.assertTrue(result["helper_edge_di_complete"])
        self.assertEqual(result["helper_di_quality"], "usable_di")


if __name__ == "__main__":
    unittest.main()
