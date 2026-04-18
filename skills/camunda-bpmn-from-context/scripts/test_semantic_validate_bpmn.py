#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent / "semantic_validate_bpmn.py"
SPEC = importlib.util.spec_from_file_location("semantic_validate", SCRIPT_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def validate_xml(xml_text, **kwargs):
    with tempfile.NamedTemporaryFile("w", suffix=".bpmn", delete=False) as fh:
        fh.write(xml_text)
        path = fh.name
    return VALIDATOR.validate_bpmn(path, **kwargs)


VALID_BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="Process_1">
    <bpmn:startEvent id="Start_1" />
    <bpmn:serviceTask id="Task_1" name="Lookup delivery" />
    <bpmn:endEvent id="End_1" />
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
  </bpmn:process>
</bpmn:definitions>
"""


class SemanticValidatorTests(unittest.TestCase):
    def test_valid_bpmn(self):
        errors, warnings = validate_xml(VALID_BPMN)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_generic_task_is_treated_as_flow_node(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:task id="Task_1" name="Generic step" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, warnings = validate_xml(xml)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_invalid_flow_refs(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Missing_Target" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("invalid targetRef" in error for error in errors))

    def test_duplicate_ids_error(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Duplicate_1" />
            <bpmn:endEvent id="Duplicate_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("Duplicate id" in error for error in errors))

    def test_missing_task_name_warning(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        _, warnings = validate_xml(xml)
        self.assertTrue(any("missing a name" in warning for warning in warnings))

    def test_disconnected_node_warning(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:serviceTask id="Task_1" name="Connected" />
            <bpmn:serviceTask id="Task_2" name="Orphan" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        _, warnings = validate_xml(xml)
        self.assertTrue(any("Task_2" in warning and "incoming" in warning for warning in warnings))
        self.assertTrue(any("Task_2" in warning and "outgoing" in warning for warning in warnings))

    def test_gateway_default_flow_error(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:exclusiveGateway id="Gateway_1" default="Flow_Missing" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Gateway_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Gateway_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("default flow" in error for error in errors))

    def test_gateway_missing_branch_labels_warning(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:exclusiveGateway id="Gateway_1" />
            <bpmn:endEvent id="End_A" />
            <bpmn:endEvent id="End_B" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Gateway_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Gateway_1" targetRef="End_A" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Gateway_1" targetRef="End_B" />
          </bpmn:process>
        </bpmn:definitions>
        """
        _, warnings = validate_xml(xml)
        self.assertTrue(any("has no name or conditionExpression" in warning for warning in warnings))

    def test_message_flow_same_participant_error(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:collaboration id="Collab_1">
            <bpmn:participant id="Participant_A" processRef="Process_A" />
            <bpmn:messageFlow id="Message_1" sourceRef="Task_A" targetRef="End_A" />
          </bpmn:collaboration>
          <bpmn:process id="Process_A">
            <bpmn:startEvent id="Start_A" />
            <bpmn:serviceTask id="Task_A" name="Notify" />
            <bpmn:endEvent id="End_A" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_A" targetRef="Task_A" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_A" targetRef="End_A" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("must cross participant boundaries" in error for error in errors))

    def test_message_flow_cross_participant_valid(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:collaboration id="Collab_1">
            <bpmn:participant id="Participant_A" processRef="Process_A" />
            <bpmn:participant id="Participant_B" processRef="Process_B" />
            <bpmn:messageFlow id="Message_1" sourceRef="Task_A" targetRef="Task_B" />
          </bpmn:collaboration>
          <bpmn:process id="Process_A">
            <bpmn:startEvent id="Start_A" />
            <bpmn:serviceTask id="Task_A" name="Send" />
            <bpmn:endEvent id="End_A" />
            <bpmn:sequenceFlow id="Flow_A1" sourceRef="Start_A" targetRef="Task_A" />
            <bpmn:sequenceFlow id="Flow_A2" sourceRef="Task_A" targetRef="End_A" />
          </bpmn:process>
          <bpmn:process id="Process_B">
            <bpmn:startEvent id="Start_B" />
            <bpmn:serviceTask id="Task_B" name="Receive" />
            <bpmn:endEvent id="End_B" />
            <bpmn:sequenceFlow id="Flow_B1" sourceRef="Start_B" targetRef="Task_B" />
            <bpmn:sequenceFlow id="Flow_B2" sourceRef="Task_B" targetRef="End_B" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, warnings = validate_xml(xml)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_minimal_process_warning(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        _, warnings = validate_xml(xml)
        self.assertTrue(any("fewer than 3 flow nodes" in warning for warning in warnings))

    def test_missing_end_event_warning(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:serviceTask id="Task_1" name="Only task" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        _, warnings = validate_xml(xml)
        self.assertTrue(any("missing endEvent" in warning for warning in warnings))

    def test_gateway_insufficient_outgoing_error(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:exclusiveGateway id="Gateway_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Gateway_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Gateway_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("insufficient outgoing sequenceFlow" in error for error in errors))

    def test_loop_warning(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:serviceTask id="Task_1" name="Step 1" />
            <bpmn:serviceTask id="Task_2" name="Step 2" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="Task_2" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Task_2" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Task_2" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        _, warnings = validate_xml(xml)
        self.assertTrue(any("loop back-edge" in warning for warning in warnings))

    def test_unsupported_element_warning(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:transaction id="Txn_1" name="Transactional step" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Txn_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Txn_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        _, warnings = validate_xml(xml)
        self.assertTrue(any("`transaction`" in warning and "partial-support generation" in warning for warning in warnings))

    def test_unspecified_message_catch_does_not_require_zeebe_subscription(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:message id="Message_1" name="DeliveryUpdated" />
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:intermediateCatchEvent id="Catch_1">
              <bpmn:messageEventDefinition messageRef="Message_1" />
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Catch_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Catch_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="unspecified")
        self.assertEqual(errors, [])

    def test_camunda7_message_catch_does_not_require_zeebe_subscription(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:message id="Message_1" name="DeliveryUpdated" />
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:intermediateCatchEvent id="Catch_1">
              <bpmn:messageEventDefinition messageRef="Message_1" />
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Catch_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Catch_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertEqual(errors, [])

    def test_top_level_process_requires_top_level_start_even_if_subprocess_has_start(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:subProcess id="Sub_1" name="Embedded">
              <bpmn:startEvent id="Start_Sub_1" />
              <bpmn:endEvent id="End_Sub_1" />
              <bpmn:sequenceFlow id="Flow_Sub_1" sourceRef="Start_Sub_1" targetRef="End_Sub_1" />
            </bpmn:subProcess>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Sub_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("missing a top-level startEvent" in error for error in errors))

    def test_sequence_flow_cannot_cross_subprocess_boundary(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:subProcess id="Sub_1" name="Embedded">
              <bpmn:startEvent id="Start_Sub_1" />
              <bpmn:serviceTask id="Task_Sub_1" name="Inside" />
              <bpmn:endEvent id="End_Sub_1" />
              <bpmn:sequenceFlow id="Flow_Sub_1" sourceRef="Start_Sub_1" targetRef="Task_Sub_1" />
              <bpmn:sequenceFlow id="Flow_Sub_2" sourceRef="Task_Sub_1" targetRef="End_Sub_1" />
            </bpmn:subProcess>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_Sub_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Sub_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("crosses the boundary" in error for error in errors))

    def test_embedded_subprocess_rejects_timer_start(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:subProcess id="Sub_1" name="Embedded">
              <bpmn:startEvent id="Start_Sub_1">
                <bpmn:timerEventDefinition>
                  <bpmn:timeDate>2026-03-21T10:00:00Z</bpmn:timeDate>
                </bpmn:timerEventDefinition>
              </bpmn:startEvent>
              <bpmn:endEvent id="End_Sub_1" />
              <bpmn:sequenceFlow id="Flow_Sub_1" sourceRef="Start_Sub_1" targetRef="End_Sub_1" />
            </bpmn:subProcess>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Sub_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Sub_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("embedded subprocess `Sub_1` must use exactly one none startEvent" in error for error in errors))

    def test_embedded_subprocess_requires_exactly_one_start_event(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:subProcess id="Sub_1" name="Embedded">
              <bpmn:startEvent id="Start_Sub_1" />
              <bpmn:startEvent id="Start_Sub_2" />
              <bpmn:endEvent id="End_Sub_1" />
              <bpmn:sequenceFlow id="Flow_Sub_1" sourceRef="Start_Sub_1" targetRef="End_Sub_1" />
              <bpmn:sequenceFlow id="Flow_Sub_2" sourceRef="Start_Sub_2" targetRef="End_Sub_1" />
            </bpmn:subProcess>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Sub_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Sub_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("embedded subprocess `Sub_1` must have exactly one direct startEvent" in error for error in errors))

    def test_event_subprocess_requires_exactly_one_start_event(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:subProcess id="Event_Sub_1" triggeredByEvent="true">
              <bpmn:startEvent id="Start_Sub_1">
                <bpmn:messageEventDefinition messageRef="Message_1" />
              </bpmn:startEvent>
              <bpmn:startEvent id="Start_Sub_2">
                <bpmn:errorEventDefinition />
              </bpmn:startEvent>
              <bpmn:endEvent id="End_Sub_1" />
              <bpmn:sequenceFlow id="Flow_Sub_1" sourceRef="Start_Sub_1" targetRef="End_Sub_1" />
              <bpmn:sequenceFlow id="Flow_Sub_2" sourceRef="Start_Sub_2" targetRef="End_Sub_1" />
            </bpmn:subProcess>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("event subprocess `Event_Sub_1` must have exactly one direct startEvent" in error for error in errors))

    def test_event_subprocess_rejects_unsupported_start_type(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:subProcess id="Event_Sub_1" triggeredByEvent="true">
              <bpmn:startEvent id="Start_Sub_1">
                <bpmn:conditionalEventDefinition />
              </bpmn:startEvent>
              <bpmn:endEvent id="End_Sub_1" />
              <bpmn:sequenceFlow id="Flow_Sub_1" sourceRef="Start_Sub_1" targetRef="End_Sub_1" />
            </bpmn:subProcess>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("event subprocess `Event_Sub_1` startEvent must be timer/message/error/signal/escalation" in error for error in errors))

    def test_event_subprocess_accepts_signal_start(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:signal id="Signal_1" name="delivery-signal" />
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:subProcess id="Event_Sub_1" triggeredByEvent="true">
              <bpmn:startEvent id="Start_Sub_1">
                <bpmn:signalEventDefinition signalRef="Signal_1" />
              </bpmn:startEvent>
              <bpmn:endEvent id="End_Sub_1" />
              <bpmn:sequenceFlow id="Flow_Sub_1" sourceRef="Start_Sub_1" targetRef="End_Sub_1" />
            </bpmn:subProcess>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertEqual(errors, [])

    def test_signal_event_definition_requires_signal_ref(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1">
              <bpmn:signalEventDefinition />
            </bpmn:startEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("signalEventDefinition is missing signalRef" in error for error in errors))

    def test_boundary_signal_names_are_unique_while_start_boundary_message_scopes_are_separate(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:message id="Message_1" name="dup-name" />
          <bpmn:message id="Message_2" name="dup-name" />
          <bpmn:signal id="Signal_1" name="signal-name" />
          <bpmn:signal id="Signal_2" name="signal-name" />
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1">
              <bpmn:messageEventDefinition messageRef="Message_1" />
            </bpmn:startEvent>
            <bpmn:userTask id="Task_1" name="Review" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1">
              <bpmn:messageEventDefinition messageRef="Message_2" />
            </bpmn:boundaryEvent>
            <bpmn:boundaryEvent id="Boundary_2" attachedToRef="Task_1">
              <bpmn:signalEventDefinition signalRef="Signal_1" />
            </bpmn:boundaryEvent>
            <bpmn:boundaryEvent id="Boundary_3" attachedToRef="Task_1">
              <bpmn:signalEventDefinition signalRef="Signal_2" />
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="Boundary_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="Boundary_2" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Boundary_2" targetRef="Boundary_3" />
            <bpmn:sequenceFlow id="Flow_5" sourceRef="Boundary_3" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertFalse(any("duplicate message `dup-name`" in error for error in errors))
        self.assertTrue(any("duplicate signal `signal-name`" in error for error in errors))

    def test_signal_and_message_start_and_boundary_events_with_distinct_names_are_allowed(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:message id="Message_1" name="start-order" />
          <bpmn:message id="Message_2" name="boundary-order" />
          <bpmn:signal id="Signal_1" name="signal-start" />
          <bpmn:signal id="Signal_2" name="signal-boundary" />
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1">
              <bpmn:messageEventDefinition messageRef="Message_1" />
            </bpmn:startEvent>
            <bpmn:userTask id="Task_1" name="Review" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1">
              <bpmn:messageEventDefinition messageRef="Message_2" />
            </bpmn:boundaryEvent>
            <bpmn:boundaryEvent id="Boundary_2" attachedToRef="Task_1">
              <bpmn:signalEventDefinition signalRef="Signal_1" />
            </bpmn:boundaryEvent>
            <bpmn:boundaryEvent id="Boundary_3" attachedToRef="Task_1">
              <bpmn:signalEventDefinition signalRef="Signal_2" />
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="Boundary_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="Boundary_2" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Boundary_2" targetRef="Boundary_3" />
            <bpmn:sequenceFlow id="Flow_5" sourceRef="Boundary_3" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertEqual(errors, [])
    def test_event_subprocess_accepts_escalation_start(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:subProcess id="Event_Sub_1" triggeredByEvent="true">
              <bpmn:startEvent id="Start_Sub_1">
                <bpmn:escalationEventDefinition />
              </bpmn:startEvent>
              <bpmn:endEvent id="End_Sub_1" />
              <bpmn:sequenceFlow id="Flow_Sub_1" sourceRef="Start_Sub_1" targetRef="End_Sub_1" />
            </bpmn:subProcess>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, warnings = validate_xml(xml, camunda_version="8")
        self.assertEqual(errors, [])
        self.assertTrue(any("`escalationEventDefinition`" in warning for warning in warnings))

    def test_event_definition_partial_support_warnings(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:intermediateCatchEvent id="Error_1">
              <bpmn:errorEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:intermediateCatchEvent id="Escalation_1">
              <bpmn:escalationEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:intermediateCatchEvent id="Conditional_1">
              <bpmn:conditionalEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Error_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Error_1" targetRef="Escalation_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Escalation_1" targetRef="Conditional_1" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Conditional_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        _, warnings = validate_xml(xml)
        self.assertTrue(any("`errorEventDefinition`" in warning for warning in warnings))
        self.assertTrue(any("`escalationEventDefinition`" in warning for warning in warnings))
        self.assertTrue(any("`conditionalEventDefinition`" in warning for warning in warnings))

    def test_advanced_event_definition_manual_review_warnings(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:intermediateCatchEvent id="Terminate_1">
              <bpmn:terminateEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:intermediateCatchEvent id="Cancel_1">
              <bpmn:cancelEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:intermediateCatchEvent id="Link_1">
              <bpmn:linkEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:intermediateCatchEvent id="Multiple_1">
              <bpmn:multipleEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:intermediateCatchEvent id="Compensate_1">
              <bpmn:compensateEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Terminate_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Terminate_1" targetRef="Cancel_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Cancel_1" targetRef="Link_1" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Link_1" targetRef="Multiple_1" />
            <bpmn:sequenceFlow id="Flow_5" sourceRef="Multiple_1" targetRef="Compensate_1" />
            <bpmn:sequenceFlow id="Flow_6" sourceRef="Compensate_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        _, warnings = validate_xml(xml)
        self.assertTrue(any("`terminateEventDefinition`" in warning for warning in warnings))
        self.assertTrue(any("`cancelEventDefinition`" in warning for warning in warnings))
        self.assertTrue(any("`linkEventDefinition`" in warning for warning in warnings))
        self.assertTrue(any("`multipleEventDefinition`" in warning for warning in warnings))
        self.assertTrue(any("`compensateEventDefinition`" in warning for warning in warnings))

    def test_event_subprocess_warning(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:subProcess id="Event_Sub_1" triggeredByEvent="true" name="Cancel flow">
              <bpmn:startEvent id="Start_Sub_1" />
              <bpmn:endEvent id="End_Sub_1" />
              <bpmn:sequenceFlow id="Flow_Sub_1" sourceRef="Start_Sub_1" targetRef="End_Sub_1" />
            </bpmn:subProcess>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        _, warnings = validate_xml(xml)
        self.assertTrue(any("event subprocess" in warning for warning in warnings))

    def test_multi_instance_warning(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review items">
              <bpmn:multiInstanceLoopCharacteristics isSequential="true" />
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        _, warnings = validate_xml(xml)
        self.assertTrue(any("multi-instance semantics" in warning for warning in warnings))

    def test_to_be_manual_task_warning(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:manualTask id="Task_1" name="Call customer" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        _, warnings = validate_xml(xml, analysis_mode="to-be")
        self.assertTrue(any("appears in TO-BE mode" in warning for warning in warnings))

    def test_overview_detail_level_warning(self):
        tasks = "\n".join(f'<bpmn:serviceTask id="Task_{i}" name="Step {i}" />' for i in range(1, 15))
        flows = ['<bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />']
        for i in range(1, 14):
            flows.append(f'<bpmn:sequenceFlow id="Flow_{i+1}" sourceRef="Task_{i}" targetRef="Task_{i+1}" />')
        flows.append('<bpmn:sequenceFlow id="Flow_15" sourceRef="Task_14" targetRef="End_1" />')
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            {tasks}
            <bpmn:endEvent id="End_1" />
            {' '.join(flows)}
          </bpmn:process>
        </bpmn:definitions>
        """
        _, warnings = validate_xml(xml, detail_level="overview")
        self.assertTrue(any("overview detail level exceeded" in warning for warning in warnings))

    def test_camunda_version_namespace_mismatch_error(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:serviceTask id="Task_1" name="Do work">
              <bpmn:extensionElements>
                <zeebe:taskDefinition type="worker" retries="3" />
              </bpmn:extensionElements>
            </bpmn:serviceTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertTrue(any("Camunda 7 target selected" in error for error in errors))

    def test_camunda_version_missing_namespace_warning(self):
        _, warnings = validate_xml(VALID_BPMN, camunda_version="8")
        self.assertTrue(any("Camunda 8 target selected" in warning for warning in warnings))

    def test_boundary_event_missing_attachment_error(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Wait" />
            <bpmn:boundaryEvent id="Boundary_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("missing attachedToRef" in error for error in errors))

    def test_boundary_event_invalid_host_error(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Start_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Boundary_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("is not a valid host" in error for error in errors))

    def test_camunda8_service_task_requires_task_definition(self):
        errors, _ = validate_xml(VALID_BPMN, camunda_version="8")
        self.assertTrue(any("serviceTask `Task_1` is missing zeebe:taskDefinition" in error for error in errors))

    def test_camunda8_receive_task_requires_message_and_subscription(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:receiveTask id="Task_1" name="Wait for message" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("missing messageRef" in error for error in errors))

    def test_camunda8_receive_task_validates_subscription_on_referenced_message(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:message id="Message_1" name="DeliveryUpdated">
            <bpmn:extensionElements>
              <zeebe:subscription correlationKey="=orderId" />
            </bpmn:extensionElements>
          </bpmn:message>
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:receiveTask id="Task_1" name="Wait for delivery update" messageRef="Message_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertEqual(errors, [])

    def test_camunda8_receive_task_requires_message_name_on_referenced_message(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:message id="Message_1">
            <bpmn:extensionElements>
              <zeebe:subscription correlationKey="=orderId" />
            </bpmn:extensionElements>
          </bpmn:message>
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:receiveTask id="Task_1" name="Wait for delivery update" messageRef="Message_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("referenced message `Message_1` is missing name" in error for error in errors))

    def test_camunda8_receive_task_missing_subscription_on_message(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:message id="Message_1" name="DeliveryUpdated" />
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:receiveTask id="Task_1" name="Wait for delivery update" messageRef="Message_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("referenced message `Message_1` is missing zeebe:subscription" in error for error in errors))

    def test_camunda8_event_based_gateway_insufficient_outgoing_is_error(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:eventBasedGateway id="Gateway_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Gateway_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Gateway_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("Gateway_1 has insufficient outgoing sequenceFlow" in error for error in errors))

    def test_camunda8_business_rule_task_requires_called_decision_or_task_definition(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:businessRuleTask id="Task_1" name="Decide" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("businessRuleTask `Task_1` needs" in error for error in errors))

    def test_camunda8_empty_task_definition_type_is_invalid(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:serviceTask id="Task_1" name="Do work">
              <bpmn:extensionElements>
                <zeebe:taskDefinition />
              </bpmn:extensionElements>
            </bpmn:serviceTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("zeebe:taskDefinition is missing type" in error for error in errors))

    def test_camunda8_empty_called_decision_attributes_are_invalid(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:businessRuleTask id="Task_1" name="Decide">
              <bpmn:extensionElements>
                <zeebe:calledDecision />
              </bpmn:extensionElements>
            </bpmn:businessRuleTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("zeebe:calledDecision is missing decisionId" in error for error in errors))
        self.assertTrue(any("zeebe:calledDecision is missing resultVariable" in error for error in errors))

    def test_camunda8_script_task_requires_script_or_task_definition(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:scriptTask id="Task_1" name="Transform" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("scriptTask `Task_1` needs" in error for error in errors))

    def test_camunda8_empty_script_attributes_are_invalid(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:scriptTask id="Task_1" name="Transform">
              <bpmn:extensionElements>
                <zeebe:script />
              </bpmn:extensionElements>
            </bpmn:scriptTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("zeebe:script is missing expression" in error for error in errors))
        self.assertTrue(any("zeebe:script is missing resultVariable" in error for error in errors))

    def test_camunda8_event_based_gateway_requires_valid_targets(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:eventBasedGateway id="Gateway_1" />
            <bpmn:serviceTask id="Task_1" name="Wrong target">
              <bpmn:extensionElements>
                <zeebe:taskDefinition type="worker" retries="3" />
              </bpmn:extensionElements>
            </bpmn:serviceTask>
            <bpmn:intermediateCatchEvent id="Catch_1">
              <bpmn:timerEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Gateway_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Gateway_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Gateway_1" targetRef="Catch_1" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Catch_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_5" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("eventBasedGateway `Gateway_1` must lead" in error for error in errors))

    def test_camunda8_event_based_gateway_cannot_target_receive_task(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:message id="Message_1">
            <bpmn:extensionElements>
              <zeebe:subscription correlationKey="=orderId" />
            </bpmn:extensionElements>
          </bpmn:message>
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:eventBasedGateway id="Gateway_1" />
            <bpmn:receiveTask id="Task_1" name="Wait for delivery update" messageRef="Message_1" />
            <bpmn:intermediateCatchEvent id="Catch_1">
              <bpmn:timerEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Gateway_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Gateway_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Gateway_1" targetRef="Catch_1" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Catch_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_5" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("must lead to intermediateCatchEvent, not `receiveTask`" in error for error in errors))

    def test_camunda8_event_based_gateway_message_target_requires_message_ref(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:eventBasedGateway id="Gateway_1" />
            <bpmn:intermediateCatchEvent id="Catch_Message">
              <bpmn:messageEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:intermediateCatchEvent id="Catch_Timer">
              <bpmn:timerEventDefinition>
                <bpmn:timeDuration>PT5M</bpmn:timeDuration>
              </bpmn:timerEventDefinition>
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Gateway_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Gateway_1" targetRef="Catch_Message" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Gateway_1" targetRef="Catch_Timer" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Catch_Message" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_5" sourceRef="Catch_Timer" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("messageEventDefinition is missing messageRef" in error for error in errors))

    def test_camunda8_event_based_gateway_timer_target_requires_timer_value(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:message id="Message_1" name="DeliveryUpdated">
            <bpmn:extensionElements>
              <zeebe:subscription correlationKey="=orderId" />
            </bpmn:extensionElements>
          </bpmn:message>
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:eventBasedGateway id="Gateway_1" />
            <bpmn:intermediateCatchEvent id="Catch_Message">
              <bpmn:messageEventDefinition messageRef="Message_1" />
            </bpmn:intermediateCatchEvent>
            <bpmn:intermediateCatchEvent id="Catch_Timer">
              <bpmn:timerEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Gateway_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Gateway_1" targetRef="Catch_Message" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Gateway_1" targetRef="Catch_Timer" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Catch_Message" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_5" sourceRef="Catch_Timer" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("timerEventDefinition must define exactly one" in error for error in errors))

    def test_intermediate_catch_timer_event_with_time_cycle_is_invalid_for_c8(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:intermediateCatchEvent id="Catch_1">
              <bpmn:timerEventDefinition>
                <bpmn:timeCycle>R/PT1M</bpmn:timeCycle>
              </bpmn:timerEventDefinition>
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Catch_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Catch_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("intermediateCatchEvent `Catch_1` timerEventDefinition for event-based waits must use timeDate or timeDuration" in error for error in errors))

    def test_intermediate_catch_timer_event_with_time_date_is_supported(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:intermediateCatchEvent id="Catch_1">
              <bpmn:timerEventDefinition>
                <bpmn:timeDate>2026-03-21T10:00:00Z</bpmn:timeDate>
              </bpmn:timerEventDefinition>
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Catch_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Catch_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertFalse(any("intermediateCatchEvent `Catch_1` timerEventDefinition for event-based waits must use timeDate or timeDuration" in error for error in errors))
        self.assertFalse(any("for event-based waits" in error for error in errors))

    def test_intermediate_catch_timer_event_with_time_duration_is_supported(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:intermediateCatchEvent id="Catch_1">
              <bpmn:timerEventDefinition>
                <bpmn:timeDuration>PT5M</bpmn:timeDuration>
              </bpmn:timerEventDefinition>
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Catch_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Catch_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertFalse(any("intermediateCatchEvent `Catch_1` timerEventDefinition for event-based waits must use timeDate or timeDuration" in error for error in errors))

    def test_event_based_gateway_target_timer_catch_with_time_cycle_is_invalid(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:message id="Message_1" name="DeliveryUpdated">
            <bpmn:extensionElements>
              <zeebe:subscription correlationKey="=orderId" />
            </bpmn:extensionElements>
          </bpmn:message>
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:eventBasedGateway id="Gateway_1" />
            <bpmn:intermediateCatchEvent id="Catch_Message">
              <bpmn:messageEventDefinition messageRef="Message_1" />
            </bpmn:intermediateCatchEvent>
            <bpmn:intermediateCatchEvent id="Catch_Timer">
              <bpmn:timerEventDefinition>
                <bpmn:timeCycle>R/PT1M</bpmn:timeCycle>
              </bpmn:timerEventDefinition>
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Gateway_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Gateway_1" targetRef="Catch_Message" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Gateway_1" targetRef="Catch_Timer" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Catch_Message" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_5" sourceRef="Catch_Timer" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("intermediateCatchEvent `Catch_Timer` timerEventDefinition for event-based waits must use timeDate or timeDuration" in error for error in errors))

    def test_event_based_gateway_target_timer_catch_with_time_date_is_supported(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:message id="Message_1" name="DeliveryUpdated">
            <bpmn:extensionElements>
              <zeebe:subscription correlationKey="=orderId" />
            </bpmn:extensionElements>
          </bpmn:message>
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:eventBasedGateway id="Gateway_1" />
            <bpmn:intermediateCatchEvent id="Catch_Message">
              <bpmn:messageEventDefinition messageRef="Message_1" />
            </bpmn:intermediateCatchEvent>
            <bpmn:intermediateCatchEvent id="Catch_Timer">
              <bpmn:timerEventDefinition>
                <bpmn:timeDate>2026-03-21T10:00:00Z</bpmn:timeDate>
              </bpmn:timerEventDefinition>
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Gateway_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Gateway_1" targetRef="Catch_Message" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Gateway_1" targetRef="Catch_Timer" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Catch_Message" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_5" sourceRef="Catch_Timer" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertFalse(any("intermediateCatchEvent `Catch_Timer` timerEventDefinition for event-based waits must use timeDate or timeDuration" in error for error in errors))

    def test_event_based_gateway_invalid_targets_do_not_duplicate_errors(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:eventBasedGateway id="Gateway_1" />
            <bpmn:intermediateCatchEvent id="Catch_Message">
              <bpmn:messageEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:intermediateCatchEvent id="Catch_Timer">
              <bpmn:timerEventDefinition />
            </bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Gateway_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Gateway_1" targetRef="Catch_Message" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Gateway_1" targetRef="Catch_Timer" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Catch_Message" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_5" sourceRef="Catch_Timer" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertEqual(sum("messageEventDefinition is missing messageRef" in error for error in errors), 1)
        self.assertEqual(sum("timerEventDefinition must define exactly one" in error for error in errors), 1)

    def test_transaction_is_treated_as_flow_node(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:transaction id="Txn_1" name="Transactional step">
              <bpmn:startEvent id="Start_T" />
              <bpmn:endEvent id="End_T" />
              <bpmn:sequenceFlow id="Flow_T1" sourceRef="Start_T" targetRef="End_T" />
            </bpmn:transaction>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Txn_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Txn_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, warnings = validate_xml(xml)
        self.assertEqual(errors, [])
        self.assertTrue(any("`transaction`" in warning for warning in warnings))

    def test_ad_hoc_subprocess_is_treated_as_partial_flow_node(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:adHocSubProcess id="AdHoc_1" name="Coordinate handlers">
              <bpmn:serviceTask id="Task_A" name="Handle A" />
              <bpmn:serviceTask id="Task_B" name="Handle B" />
            </bpmn:adHocSubProcess>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="AdHoc_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="AdHoc_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, warnings = validate_xml(xml)
        self.assertEqual(errors, [])
        self.assertTrue(any("`adHocSubProcess`" in warning and "partial-support generation" in warning for warning in warnings))

    def test_non_interrupting_error_boundary_event_is_invalid(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review order" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1" cancelActivity="false">
              <bpmn:errorEventDefinition />
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:endEvent id="End_2" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="End_2" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("error boundaryEvent `Boundary_1` must be interrupting" in error for error in errors))

    def test_boundary_timer_interrupting_rejects_time_cycle(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review order" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1">
              <bpmn:timerEventDefinition>
                <bpmn:timeCycle>R/PT1M</bpmn:timeCycle>
              </bpmn:timerEventDefinition>
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:endEvent id="End_2" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="End_2" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("must use timeDate or timeDuration when interrupting" in error for error in errors))

    def test_boundary_timer_non_interrupting_accepts_time_date(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review order" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1" cancelActivity="false">
              <bpmn:timerEventDefinition>
                <bpmn:timeDate>2026-03-21T10:00:00Z</bpmn:timeDate>
              </bpmn:timerEventDefinition>
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:endEvent id="End_2" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="End_2" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertFalse(any("Boundary_1" in error and "timerEventDefinition" in error for error in errors))

    def test_boundary_timer_non_interrupting_accepts_time_cycle(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review order" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1" cancelActivity="false">
              <bpmn:timerEventDefinition>
                <bpmn:timeCycle>R/PT1M</bpmn:timeCycle>
              </bpmn:timerEventDefinition>
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:endEvent id="End_2" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="End_2" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertFalse(any("Boundary_1" in error and "timerEventDefinition" in error for error in errors))

    def test_camunda8_message_start_names_must_be_unique(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:message id="Message_1" name="order-created">
            <bpmn:extensionElements>
              <zeebe:subscription correlationKey="=orderId" />
            </bpmn:extensionElements>
          </bpmn:message>
          <bpmn:message id="Message_2" name="order-created">
            <bpmn:extensionElements>
              <zeebe:subscription correlationKey="=orderId" />
            </bpmn:extensionElements>
          </bpmn:message>
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1">
              <bpmn:messageEventDefinition messageRef="Message_1" />
            </bpmn:startEvent>
            <bpmn:startEvent id="Start_2">
              <bpmn:messageEventDefinition messageRef="Message_2" />
            </bpmn:startEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Start_2" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("duplicate message `order-created`" in error for error in errors))

    def test_camunda8_boundary_message_names_must_be_unique(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:message id="Message_1" name="order-updated">
            <bpmn:extensionElements>
              <zeebe:subscription correlationKey="=orderId" />
            </bpmn:extensionElements>
          </bpmn:message>
          <bpmn:message id="Message_2" name="order-updated">
            <bpmn:extensionElements>
              <zeebe:subscription correlationKey="=orderId" />
            </bpmn:extensionElements>
          </bpmn:message>
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review order" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1">
              <bpmn:messageEventDefinition messageRef="Message_1" />
            </bpmn:boundaryEvent>
            <bpmn:boundaryEvent id="Boundary_2" attachedToRef="Task_1">
              <bpmn:messageEventDefinition messageRef="Message_2" />
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:endEvent id="End_2" />
            <bpmn:endEvent id="End_3" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="End_2" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Boundary_2" targetRef="End_3" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("duplicate message `order-updated`" in error for error in errors))

    def test_camunda8_signal_event_requires_signal_ref(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1">
              <bpmn:signalEventDefinition />
            </bpmn:boundaryEvent>
            <bpmn:userTask id="Task_1" name="Review order" />
            <bpmn:endEvent id="End_1" />
            <bpmn:endEvent id="End_2" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="End_2" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("signalEventDefinition is missing signalRef" in error for error in errors))

    def test_camunda8_signal_event_requires_named_signal(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:signal id="Signal_1" />
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review order" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1">
              <bpmn:signalEventDefinition signalRef="Signal_1" />
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:endEvent id="End_2" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="End_2" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("references signal `Signal_1` is missing name" in error for error in errors))

    def test_camunda8_boundary_signal_names_must_be_unique(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:signal id="Signal_1" name="order-alert" />
          <bpmn:signal id="Signal_2" name="order-alert" />
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review order" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1">
              <bpmn:signalEventDefinition signalRef="Signal_1" />
            </bpmn:boundaryEvent>
            <bpmn:boundaryEvent id="Boundary_2" attachedToRef="Task_1">
              <bpmn:signalEventDefinition signalRef="Signal_2" />
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:endEvent id="End_2" />
            <bpmn:endEvent id="End_3" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="End_2" />
            <bpmn:sequenceFlow id="Flow_4" sourceRef="Boundary_2" targetRef="End_3" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("duplicate signal `order-alert`" in error for error in errors))

    def test_camunda8_same_message_name_allowed_between_start_and_boundary_scopes(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:message id="Message_1" name="order-sync">
            <bpmn:extensionElements>
              <zeebe:subscription correlationKey="=orderId" />
            </bpmn:extensionElements>
          </bpmn:message>
          <bpmn:message id="Message_2" name="order-sync">
            <bpmn:extensionElements>
              <zeebe:subscription correlationKey="=orderId" />
            </bpmn:extensionElements>
          </bpmn:message>
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1">
              <bpmn:messageEventDefinition messageRef="Message_1" />
            </bpmn:startEvent>
            <bpmn:userTask id="Task_1" name="Review order" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1">
              <bpmn:messageEventDefinition messageRef="Message_2" />
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:endEvent id="End_2" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="End_2" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertFalse(any("duplicate message `order-sync`" in error for error in errors))

    def test_camunda8_same_signal_name_allowed_between_start_and_boundary_scopes(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:signal id="Signal_1" name="order-alert" />
          <bpmn:signal id="Signal_2" name="order-alert" />
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1">
              <bpmn:signalEventDefinition signalRef="Signal_1" />
            </bpmn:startEvent>
            <bpmn:userTask id="Task_1" name="Review order" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1">
              <bpmn:signalEventDefinition signalRef="Signal_2" />
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:endEvent id="End_2" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="End_2" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertFalse(any("duplicate signal `order-alert`" in error for error in errors))

    def test_boundary_timer_interrupting_event_rejects_time_cycle(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review order" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1">
              <bpmn:timerEventDefinition>
                <bpmn:timeCycle>R/P1D</bpmn:timeCycle>
              </bpmn:timerEventDefinition>
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="Boundary_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("boundaryEvent `Boundary_1` timerEventDefinition must use timeDate or timeDuration when interrupting" in error for error in errors))

    def test_boundary_timer_non_interrupting_event_allows_time_date(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review order" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1" cancelActivity="false">
              <bpmn:timerEventDefinition>
                <bpmn:timeDate>2026-03-21T10:00:00Z</bpmn:timeDate>
              </bpmn:timerEventDefinition>
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="Boundary_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertFalse(any("boundaryEvent `Boundary_1` timerEventDefinition" in error for error in errors))

    def test_boundary_timer_non_interrupting_event_with_time_duration_is_valid(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review order" />
            <bpmn:boundaryEvent id="Boundary_1" attachedToRef="Task_1" cancelActivity="false">
              <bpmn:timerEventDefinition>
                <bpmn:timeDuration>PT10M</bpmn:timeDuration>
              </bpmn:timerEventDefinition>
            </bpmn:boundaryEvent>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="Boundary_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="Boundary_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertFalse(any("boundaryEvent `Boundary_1` timerEventDefinition" in error for error in errors))

    def test_participant_process_ref_must_resolve(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:collaboration id="Collab_1">
            <bpmn:participant id="Participant_A" processRef="Missing_Process" />
          </bpmn:collaboration>
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml)
        self.assertTrue(any("participant processRef `Missing_Process` does not exist" in error for error in errors))

    def test_black_box_participant_without_process_ref_warns_only(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:collaboration id="Collab_1">
            <bpmn:participant id="Participant_A" />
          </bpmn:collaboration>
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, warnings = validate_xml(xml)
        self.assertEqual(errors, [])
        self.assertTrue(any("treated as a black-box participant" in warning for warning in warnings))

    def test_camunda8_user_task_empty_optional_extensions_are_errors_when_blocks_present(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:userTask />
                <zeebe:assignmentDefinition />
                <zeebe:taskSchedule />
                <zeebe:taskListeners />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, warnings = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("zeebe:assignmentDefinition is empty" in error for error in errors))
        self.assertTrue(any("zeebe:taskSchedule is empty" in error for error in errors))
        self.assertTrue(any("zeebe:taskListeners has no taskListener entries" in error for error in errors))
        self.assertFalse(any("zeebe:assignmentDefinition is empty" in warning for warning in warnings))

    def test_camunda8_user_task_priority_accepts_feel_and_range_values(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:taskDefinition type="review-worker" priority="=taskPriority" />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertEqual(errors, [])

    def test_camunda8_user_task_priority_accepts_numeric_values_in_range(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:taskDefinition type="review-worker" priority="42" />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertEqual(errors, [])

    def test_camunda8_user_task_priority_rejects_out_of_range_values(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:priorityDefinition priority="101" />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("priorityDefinition priority must be integer 0..100 or FEEL expression" in error for error in errors))

    def test_camunda8_user_task_form_definition_requires_valid_binding(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:formDefinition binding="versionTag" versionTag="2026-Q1" formId="review-form" />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertEqual(errors, [])

    def test_camunda8_user_task_form_definition_rejects_invalid_binding(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:formDefinition binding="invalid" formId="review-form" />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("zeebe:formDefinition has invalid bindingType `invalid`" in error for error in errors))

    def test_camunda8_user_task_form_definition_rejects_missing_version_tag_for_versiontag_binding(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:formDefinition binding="versionTag" formId="review-form" />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("uses bindingType=versionTag but is missing versionTag" in error for error in errors))

    def test_camunda8_user_task_form_definition_rejects_version_tag_without_binding(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:formDefinition versionTag="2026-Q1" formId="review-form" />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("has versionTag but no binding" in error for error in errors))

    def test_camunda8_user_task_listener_event_type_rejects_invalid_values(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:taskListeners>
                  <zeebe:taskListener eventType="created" type="notify" retries="3" />
                </zeebe:taskListeners>
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("has invalid eventType `created`" in error for error in errors))

    def test_camunda8_user_task_listener_retries_accepts_feel_and_non_negative_integers(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:taskDefinition type="review-worker" />
                <zeebe:taskListeners>
                  <zeebe:taskListener eventType="creating" type="notify" retries="3" />
                  <zeebe:taskListener eventType="completing" type="audit" retries="=retries" />
                </zeebe:taskListeners>
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertEqual(errors, [])

    def test_camunda8_user_task_listener_retries_rejects_negative_values(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:taskListeners>
                  <zeebe:taskListener eventType="assigning" type="notify" retries="-1" />
                </zeebe:taskListeners>
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("retries must be non-negative integer or FEEL expression" in error for error in errors))

    def test_camunda8_user_task_task_headers_require_unique_keys_and_values(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:taskDefinition type="review-worker" />
                <zeebe:taskHeaders>
                  <zeebe:header key="tenant" value="value_1" />
                  <zeebe:header key="tenant" value="value_2" />
                  <zeebe:header key="region" />
                </zeebe:taskHeaders>
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("has duplicate key `tenant`" in error for error in errors))
        self.assertTrue(any("zeebe:taskHeader is missing value" in error for error in errors))

    def test_camunda8_user_task_task_headers_allow_unique_complete_entries(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:taskDefinition type="review-worker" />
                <zeebe:taskHeaders>
                  <zeebe:header key="tenant" value="acme" />
                  <zeebe:header key="region" value="eu" />
                </zeebe:taskHeaders>
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertEqual(errors, [])

    def test_camunda8_user_task_task_definition_missing_type_is_error(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:taskDefinition />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("zeebe:taskDefinition is missing type" in error for error in errors))

    def test_camunda8_user_task_task_definition_invalid_retries_is_error(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:taskDefinition type="review-worker" retries="-1" />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("zeebe:taskDefinition retries must be non-negative integer or FEEL expression" in error for error in errors))

    def test_camunda8_user_task_legacy_job_worker_path_warns(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:taskDefinition type="review-worker" />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, warnings = validate_xml(xml, camunda_version="8")
        self.assertEqual(errors, [])
        self.assertTrue(any("uses legacy/job-worker implementation" in warning for warning in warnings))

    def test_camunda8_user_task_without_user_task_metadata_warns(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, warnings = validate_xml(xml, camunda_version="8")
        self.assertEqual(errors, [])
        self.assertTrue(any("missing zeebe:userTask metadata" in warning for warning in warnings))

    def test_camunda8_user_task_priority_range(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:userTask />
                <zeebe:priorityDefinition priority="101" />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("priorityDefinition priority must be integer 0..100 or FEEL expression" in error for error in errors))

    def test_camunda8_user_task_form_version_tag_requires_version_tag(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:userTask />
                <zeebe:formDefinition formId="review-form" bindingType="versionTag" />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("uses bindingType=versionTag but is missing versionTag" in error for error in errors))

    def test_camunda8_user_task_listener_event_type_enum(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:userTask />
                <zeebe:taskListeners>
                  <zeebe:taskListener eventType="bogus" type="listener-worker" retries="1" />
                </zeebe:taskListeners>
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("taskListener has invalid eventType `bogus`" in error for error in errors))

    def test_camunda8_user_task_listener_retries_numeric(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:userTask />
                <zeebe:taskListeners>
                  <zeebe:taskListener eventType="creating" type="listener-worker" retries="NaN" />
                </zeebe:taskListeners>
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("taskListener retries must be non-negative integer or FEEL expression" in error for error in errors))

    def test_camunda8_user_task_task_headers_non_empty(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review delivery">
              <bpmn:extensionElements>
                <zeebe:userTask />
                <zeebe:taskHeaders>
                  <zeebe:header key="tenant" value="" />
                </zeebe:taskHeaders>
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="8")
        self.assertTrue(any("taskHeader is missing value" in error for error in errors))

    def test_camunda7_service_task_requires_implementation(self):
        errors, _ = validate_xml(VALID_BPMN, camunda_version="7")
        self.assertTrue(any("serviceTask `Task_1` is missing execution implementation attributes" in error for error in errors))

    def test_camunda7_external_service_task_requires_topic(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:serviceTask id="Task_1" name="External" camunda:type="external" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertTrue(any("missing camunda:topic" in error for error in errors))

    def test_camunda7_service_task_topic_only_for_external(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:serviceTask id="Task_1" name="JavaDelegate" camunda:class="com.example.Task" camunda:topic="topic-a" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertTrue(any("sets camunda:topic but type is not `external`" in error for error in errors))

    def test_camunda7_service_task_result_variable_requires_expression(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:serviceTask id="Task_1" name="JavaDelegate" camunda:class="com.example.Task" camunda:resultVariable="result" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertTrue(any("sets camunda:resultVariable without camunda:expression" in error for error in errors))

    def test_camunda7_service_task_task_priority_only_for_external(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:serviceTask id="Task_1" name="JavaDelegate" camunda:class="com.example.Task" camunda:taskPriority="100" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertTrue(any("sets camunda:taskPriority but type is not `external`" in error for error in errors))

    def test_camunda7_user_task_assignee_conflicts_with_human_performer(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review" camunda:assignee="demo">
              <bpmn:humanPerformer />
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertTrue(any("uses both camunda:assignee and humanPerformer" in error for error in errors))

    def test_camunda7_user_task_allows_only_one_form_data(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review" camunda:assignee="demo">
              <bpmn:extensionElements>
                <camunda:formData />
                <camunda:formData />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertTrue(any("has multiple camunda:formData entries" in error for error in errors))

    def test_camunda7_external_service_task_with_topic_is_valid(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:serviceTask id="Task_1" name="External" camunda:type="external" camunda:topic="topic-queue" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertFalse(any("Camunda 7 serviceTask `Task_1`" in error and "missing camunda:topic" in error for error in errors))
        self.assertFalse(any("sets camunda:topic but type is not `external`" in error for error in errors))

    def test_camunda7_non_external_service_task_with_topic_is_invalid(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:serviceTask id="Task_1" name="Java task"
              camunda:type="java" camunda:class="com.example.Task" camunda:topic="topic-queue" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertFalse(any("is missing execution implementation attributes" in error for error in errors))
        self.assertTrue(any("sets camunda:topic but type is not `external`" in error for error in errors))

    def test_camunda7_service_task_result_variable_requires_expression(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:serviceTask id="Task_1" name="External" camunda:type="external" camunda:topic="topic-queue" camunda:resultVariable="result" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertTrue(any("sets camunda:resultVariable without camunda:expression" in error for error in errors))

    def test_camunda7_service_task_result_variable_with_expression_is_allowed(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:serviceTask id="Task_1" name="External" camunda:type="external" camunda:topic="topic-queue" camunda:expression="${true}" camunda:resultVariable="result" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertFalse(any("sets camunda:resultVariable without camunda:expression" in error for error in errors))

    def test_camunda7_user_task_disallows_assignee_with_human_performer(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review" camunda:assignee="john">
              <bpmn:humanPerformer id="Performer_1" />
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertTrue(any("uses both camunda:assignee and humanPerformer" in error for error in errors))

    def test_camunda7_user_task_multiple_form_data_entries_are_invalid(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review">
              <bpmn:extensionElements>
                <camunda:formData />
                <camunda:formData />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertTrue(any("has multiple camunda:formData entries" in error for error in errors))

    def test_camunda7_user_task_single_form_data_entry_is_allowed(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:camunda="http://camunda.org/schema/1.0/bpmn">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:userTask id="Task_1" name="Review">
              <bpmn:extensionElements>
                <camunda:formData />
              </bpmn:extensionElements>
            </bpmn:userTask>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        errors, _ = validate_xml(xml, camunda_version="7")
        self.assertFalse(any("multiple camunda:formData entries" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
