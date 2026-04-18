#!/usr/bin/env python3
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
NODE_TOOLING_DIR = SCRIPT_DIR.parent / "node_tooling"
HELPER_PATH = NODE_TOOLING_DIR / "simple_layout_helper.js"

INPUT_BPMN_NO_DI = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  id="Definitions_1"
                  targetNamespace="http://example.com/test">
  <bpmn:process id="Process_1" isExecutable="false">
    <bpmn:startEvent id="StartEvent_1" />
    <bpmn:task id="Task_1" />
    <bpmn:endEvent id="EndEvent_1" />
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Task_1" />
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="EndEvent_1" />
  </bpmn:process>
</bpmn:definitions>
"""


class SimpleLayoutHelperTests(unittest.TestCase):
    def setUp(self):
        node_binary = shutil.which("node")
        if not node_binary:
            self.skipTest("node is not installed")
        self.node_binary = node_binary
        if not HELPER_PATH.exists():
            self.skipTest(f"helper script is missing: {HELPER_PATH}")
        resolve_check = subprocess.run(
            [self.node_binary, "-e", "require.resolve('bpmn-auto-layout')"],
            cwd=NODE_TOOLING_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        if resolve_check.returncode != 0:
            self.skipTest("bpmn-auto-layout is not installed in node_tooling; run npm install first")

    def test_helper_runs_bpmn_auto_layout_and_writes_di(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.bpmn"
            output_path = Path(tmpdir) / "output.bpmn"
            diagnostics_path = Path(tmpdir) / "helper_diagnostics.json"
            input_path.write_text(INPUT_BPMN_NO_DI, encoding="utf-8")

            completed = subprocess.run(
                [
                    self.node_binary,
                    str(HELPER_PATH),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--diagnostics",
                    str(diagnostics_path),
                ],
                cwd=NODE_TOOLING_DIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            self.assertTrue(output_path.exists())
            self.assertTrue(diagnostics_path.exists())

            input_xml = input_path.read_text(encoding="utf-8")
            output_xml = output_path.read_text(encoding="utf-8")
            diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))

        self.assertNotEqual(output_xml, input_xml)
        self.assertIn("bpmndi:BPMNDiagram", output_xml)
        self.assertIn("dc:Bounds", output_xml)
        self.assertEqual(diagnostics["status"], "PASS")
        self.assertTrue(any(line.startswith("layout_engine=bpmn-auto-layout@") for line in diagnostics["warnings"]))
        self.assertTrue(diagnostics["output"]["bpmn_written"])
        self.assertIn("sequence_flow_count", diagnostics["output"])
        self.assertIn("bpmn_edge_count", diagnostics["output"])
        self.assertIn("edge_di_complete", diagnostics["output"])
        self.assertEqual(diagnostics["output"]["di_quality"], "partial_di")


if __name__ == "__main__":
    unittest.main()
