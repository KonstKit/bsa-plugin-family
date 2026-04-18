#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent / "simple_mode_bridge.py"
SPEC = importlib.util.spec_from_file_location("simple_mode_bridge", SCRIPT_PATH)
BRIDGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRIDGE)

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

ZEEBE_ID_MISMATCH_BPMN = ZEEBE_BPMN.replace('id="Flow_2"', 'id="Flow_9"')
ZEEBE_NAMESPACE_LOSS_BPMN = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<bpmn:definitions xmlns:bpmn=\"http://www.omg.org/spec/BPMN/20100524/MODEL\"
                  id=\"Definitions_1\"
                  targetNamespace=\"http://example.com/test\">
  <bpmn:process id=\"Process_1\" isExecutable=\"true\">
    <bpmn:startEvent id=\"Start_1\" />
    <bpmn:serviceTask id=\"Task_1\" />
    <bpmn:endEvent id=\"End_1\" />
    <bpmn:sequenceFlow id=\"Flow_1\" sourceRef=\"Start_1\" targetRef=\"Task_1\" />
    <bpmn:sequenceFlow id=\"Flow_2\" sourceRef=\"Task_1\" targetRef=\"End_1\" />
  </bpmn:process>
</bpmn:definitions>
"""
ZEEBE_EXTENSION_LOSS_BPMN = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<bpmn:definitions xmlns:bpmn=\"http://www.omg.org/spec/BPMN/20100524/MODEL\"
                  xmlns:zeebe=\"http://camunda.org/schema/zeebe/1.0\"
                  id=\"Definitions_1\"
                  targetNamespace=\"http://example.com/test\">
  <bpmn:process id=\"Process_1\" isExecutable=\"true\">
    <bpmn:startEvent id=\"Start_1\" />
    <bpmn:serviceTask id=\"Task_1\" />
    <bpmn:endEvent id=\"End_1\" />
    <bpmn:sequenceFlow id=\"Flow_1\" sourceRef=\"Start_1\" targetRef=\"Task_1\" />
    <bpmn:sequenceFlow id=\"Flow_2\" sourceRef=\"Task_1\" targetRef=\"End_1\" />
  </bpmn:process>
</bpmn:definitions>
"""

ZEEBE_IO_ORDER_BASE_BPMN = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<bpmn:definitions xmlns:bpmn=\"http://www.omg.org/spec/BPMN/20100524/MODEL\"
                  xmlns:zeebe=\"http://camunda.org/schema/zeebe/1.0\"
                  id=\"Definitions_1\"
                  targetNamespace=\"http://example.com/test\">
  <bpmn:process id=\"Process_1\" isExecutable=\"true\">
    <bpmn:startEvent id=\"Start_1\" />
    <bpmn:serviceTask id=\"Task_1\">
      <bpmn:extensionElements>
        <zeebe:ioMapping>
          <zeebe:input source=\"=a\" target=\"x\" />
          <zeebe:output source=\"=x\" target=\"y\" />
        </zeebe:ioMapping>
      </bpmn:extensionElements>
    </bpmn:serviceTask>
    <bpmn:endEvent id=\"End_1\" />
    <bpmn:sequenceFlow id=\"Flow_1\" sourceRef=\"Start_1\" targetRef=\"Task_1\" />
    <bpmn:sequenceFlow id=\"Flow_2\" sourceRef=\"Task_1\" targetRef=\"End_1\" />
  </bpmn:process>
</bpmn:definitions>
"""

ZEEBE_IO_ORDER_REORDERED_BPMN = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<bpmn:definitions xmlns:bpmn=\"http://www.omg.org/spec/BPMN/20100524/MODEL\"
                  xmlns:zeebe=\"http://camunda.org/schema/zeebe/1.0\"
                  id=\"Definitions_1\"
                  targetNamespace=\"http://example.com/test\">
  <bpmn:process id=\"Process_1\" isExecutable=\"true\">
    <bpmn:startEvent id=\"Start_1\" />
    <bpmn:serviceTask id=\"Task_1\">
      <bpmn:extensionElements>
        <zeebe:ioMapping>
          <zeebe:output source=\"=x\" target=\"y\" />
          <zeebe:input source=\"=a\" target=\"x\" />
        </zeebe:ioMapping>
      </bpmn:extensionElements>
    </bpmn:serviceTask>
    <bpmn:endEvent id=\"End_1\" />
    <bpmn:sequenceFlow id=\"Flow_1\" sourceRef=\"Start_1\" targetRef=\"Task_1\" />
    <bpmn:sequenceFlow id=\"Flow_2\" sourceRef=\"Task_1\" targetRef=\"End_1\" />
  </bpmn:process>
</bpmn:definitions>
"""

ZEEBE_DUPLICATE_HEADERS_BPMN = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<bpmn:definitions xmlns:bpmn=\"http://www.omg.org/spec/BPMN/20100524/MODEL\"
                  xmlns:zeebe=\"http://camunda.org/schema/zeebe/1.0\"
                  id=\"Definitions_1\"
                  targetNamespace=\"http://example.com/test\">
  <bpmn:process id=\"Process_1\" isExecutable=\"true\">
    <bpmn:startEvent id=\"Start_1\" />
    <bpmn:serviceTask id=\"Task_1\">
      <bpmn:extensionElements>
        <zeebe:taskHeaders>
          <zeebe:header key=\"x\" value=\"1\" />
          <zeebe:header key=\"x\" value=\"1\" />
        </zeebe:taskHeaders>
      </bpmn:extensionElements>
    </bpmn:serviceTask>
    <bpmn:endEvent id=\"End_1\" />
    <bpmn:sequenceFlow id=\"Flow_1\" sourceRef=\"Start_1\" targetRef=\"Task_1\" />
    <bpmn:sequenceFlow id=\"Flow_2\" sourceRef=\"Task_1\" targetRef=\"End_1\" />
  </bpmn:process>
</bpmn:definitions>
"""

ZEEBE_DUPLICATE_HEADERS_LOST_ONE_BPMN = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<bpmn:definitions xmlns:bpmn=\"http://www.omg.org/spec/BPMN/20100524/MODEL\"
                  xmlns:zeebe=\"http://camunda.org/schema/zeebe/1.0\"
                  id=\"Definitions_1\"
                  targetNamespace=\"http://example.com/test\">
  <bpmn:process id=\"Process_1\" isExecutable=\"true\">
    <bpmn:startEvent id=\"Start_1\" />
    <bpmn:serviceTask id=\"Task_1\">
      <bpmn:extensionElements>
        <zeebe:taskHeaders>
          <zeebe:header key=\"x\" value=\"1\" />
        </zeebe:taskHeaders>
      </bpmn:extensionElements>
    </bpmn:serviceTask>
    <bpmn:endEvent id=\"End_1\" />
    <bpmn:sequenceFlow id=\"Flow_1\" sourceRef=\"Start_1\" targetRef=\"Task_1\" />
    <bpmn:sequenceFlow id=\"Flow_2\" sourceRef=\"Task_1\" targetRef=\"End_1\" />
  </bpmn:process>
</bpmn:definitions>
"""


def write_fixture(path, content):
    Path(path).write_text(content, encoding="utf-8")


class ProjectionRehydrationContractTests(unittest.TestCase):
    def evaluate(self, original, candidate):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.bpmn"
            output_path = Path(tmpdir) / "output.bpmn"
            write_fixture(input_path, original)
            write_fixture(output_path, candidate)
            return BRIDGE.evaluate_projection_rehydration_contract(input_path, output_path)

    def test_id_mismatch_detected(self):
        result = self.evaluate(ZEEBE_BPMN, ZEEBE_ID_MISMATCH_BPMN)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_code"], BRIDGE.FAILURE_ID_MISMATCH)

    def test_namespace_loss_detected(self):
        result = self.evaluate(ZEEBE_BPMN, ZEEBE_NAMESPACE_LOSS_BPMN)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_code"], BRIDGE.FAILURE_NAMESPACE_LOSS)

    def test_extension_loss_detected(self):
        result = self.evaluate(ZEEBE_BPMN, ZEEBE_EXTENSION_LOSS_BPMN)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_code"], BRIDGE.FAILURE_EXTENSION_LOSS)

    def test_happy_path_preserves_invariants(self):
        result = self.evaluate(ZEEBE_BPMN, ZEEBE_BPMN)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["failure_code"])

    def test_runtime_extension_order_only_rewrite_is_allowed(self):
        result = self.evaluate(ZEEBE_IO_ORDER_BASE_BPMN, ZEEBE_IO_ORDER_REORDERED_BPMN)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["failure_code"])

    def test_duplicate_runtime_extension_loss_is_detected(self):
        result = self.evaluate(ZEEBE_DUPLICATE_HEADERS_BPMN, ZEEBE_DUPLICATE_HEADERS_LOST_ONE_BPMN)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_code"], BRIDGE.FAILURE_EXTENSION_LOSS)


if __name__ == "__main__":
    unittest.main()
