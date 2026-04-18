#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent / "make_stripped_fixture.py"
SPEC = importlib.util.spec_from_file_location("make_stripped_fixture", SCRIPT_PATH)
STRIPPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STRIPPER)

SAMPLE_ORIGINAL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
                  xmlns:zeebe="http://camunda.org/schema/zeebe/1.0"
                  id="Definitions_1"
                  targetNamespace="http://example.com/test">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="Start_1" />
    <bpmn:serviceTask id="Task_1">
      <bpmn:extensionElements>
        <zeebe:taskDefinition type="payment" retries="3" />
      </bpmn:extensionElements>
    </bpmn:serviceTask>
    <bpmn:endEvent id="End_1" />
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1">
      <bpmndi:BPMNShape id="Start_1_di" bpmnElement="Start_1"><dc:Bounds x="100" y="100" width="36" height="36" /></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_1_di" bpmnElement="Task_1"><dc:Bounds x="220" y="80" width="120" height="80" /></bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""


class MakeStrippedFixtureTests(unittest.TestCase):
    def test_strip_fixture_removes_bpmndi_and_preserves_invariants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.bpmn"
            output = Path(tmpdir) / "stripped.bpmn"
            source.write_text(SAMPLE_ORIGINAL, encoding="utf-8")

            result = STRIPPER.strip_fixture(source, output, fixture_id="fixture-a")
            stripped_xml = output.read_text(encoding="utf-8")

        self.assertEqual(result["fixture_id"], "fixture-a")
        self.assertTrue(result["invariants_ok"])
        self.assertGreater(result["removed_bpmndi_elements"], 0)
        self.assertNotIn("bpmndi:BPMNDiagram", stripped_xml)
        self.assertIn("camunda.org/schema/zeebe/1.0", stripped_xml)
        self.assertIn("taskDefinition", stripped_xml)
        self.assertTrue(result["invariants"]["remove_bpmndi_only"])
        self.assertTrue(result["invariants"]["runtime_contract_preserved"])
        self.assertTrue(result["invariants"]["collaboration_semantics_preserved"])
        self.assertEqual(len(result["source_sha256"]), 64)
        self.assertEqual(len(result["stripped_sha256"]), 64)

    def test_strip_fixture_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.bpmn"
            output_a = Path(tmpdir) / "stripped-a.bpmn"
            output_b = Path(tmpdir) / "stripped-b.bpmn"
            source.write_text(SAMPLE_ORIGINAL, encoding="utf-8")

            STRIPPER.strip_fixture(source, output_a, fixture_id="fixture-a")
            STRIPPER.strip_fixture(source, output_b, fixture_id="fixture-a")

            payload_a = output_a.read_bytes()
            payload_b = output_b.read_bytes()

        self.assertEqual(payload_a, payload_b)

    def test_generate_from_inventory_writes_lineage_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "original").mkdir()
            (root / "stripped").mkdir()
            (root / "original" / "b_fixture.bpmn").write_text(SAMPLE_ORIGINAL, encoding="utf-8")
            (root / "original" / "a_fixture.bpmn").write_text(SAMPLE_ORIGINAL.replace("Process_1", "Process_2"), encoding="utf-8")

            inventory = {
                "schema_version": "1",
                "fixtures": [
                    {
                        "fixture_id": "b_fixture",
                        "path": "original/b_fixture.bpmn",
                        "strip_to": "stripped/b_fixture.bpmn",
                    },
                    {
                        "fixture_id": "a_fixture",
                        "path": "original/a_fixture.bpmn",
                        "strip_to": "stripped/a_fixture.bpmn",
                    },
                ],
            }
            inventory_path = root / "inventory.json"
            inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            lineage_path = root / "fixture_lineage.json"

            result = STRIPPER.generate_from_inventory(inventory_path, root, lineage_path)
            persisted = json.loads(lineage_path.read_text(encoding="utf-8"))

        self.assertEqual(result, persisted)
        self.assertEqual([item["fixture_id"] for item in result["entries"]], ["a_fixture", "b_fixture"])
        self.assertEqual(result["schema_version"], STRIPPER.LINEAGE_SCHEMA_VERSION)
        self.assertEqual(result["entries"][0]["source_fixture_id"], "a_fixture")
        self.assertEqual(result["entries"][0]["stripped_fixture_id"], "a_fixture")

    def test_strip_fixture_preserves_collaboration_lane_semantics(self):
        sample = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  id="Definitions_lane"
                  targetNamespace="http://example.com/test">
  <bpmn:collaboration id="Collab_1">
    <bpmn:participant id="Participant_1" processRef="Process_1" />
  </bpmn:collaboration>
  <bpmn:process id="Process_1" isExecutable="false">
    <bpmn:laneSet id="LaneSet_1">
      <bpmn:lane id="Lane_1">
        <bpmn:flowNodeRef>Task_1</bpmn:flowNodeRef>
      </bpmn:lane>
    </bpmn:laneSet>
    <bpmn:task id="Task_1" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id="Diagram_1">
    <bpmndi:BPMNPlane id="Plane_1" bpmnElement="Collab_1">
      <bpmndi:BPMNShape id="Task_1_di" bpmnElement="Task_1"><dc:Bounds x="100" y="100" width="120" height="80" /></bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source_lane.bpmn"
            output = Path(tmpdir) / "stripped_lane.bpmn"
            source.write_text(sample, encoding="utf-8")
            result = STRIPPER.strip_fixture(source, output, fixture_id="lane-case")
            source_semantics = STRIPPER._collect_collaboration_semantics(source)
            output_semantics = STRIPPER._collect_collaboration_semantics(output)

        self.assertTrue(result["invariants_ok"])
        self.assertEqual(source_semantics, output_semantics)

    def test_generate_from_inventory_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "original").mkdir()
            (root / "stripped").mkdir()
            (root / "original" / "fixture.bpmn").write_text(SAMPLE_ORIGINAL, encoding="utf-8")

            inventory = {
                "schema_version": "1",
                "fixtures": [
                    {
                        "fixture_id": "fixture",
                        "path": "original/fixture.bpmn",
                        "strip_to": "../escaped_outside.bpmn",
                    }
                ],
            }
            inventory_path = root / "inventory.json"
            inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            lineage_path = root / "fixture_lineage.json"

            with self.assertRaisesRegex(RuntimeError, "escapes fixtures-root"):
                STRIPPER.generate_from_inventory(inventory_path, root, lineage_path)


if __name__ == "__main__":
    unittest.main()
