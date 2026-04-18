#!/usr/bin/env python3
import importlib.util
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parent / "apply_bpmn_layout_policy.py"
SPEC = importlib.util.spec_from_file_location("layout_policy", SCRIPT_PATH)
LAYOUT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAYOUT)
DEFAULT_LAYOUT_POLICY = LAYOUT.load_layout_policy_config()
DEFAULT_NESTED_THRESHOLDS = LAYOUT.resolve_threshold_profile(
    DEFAULT_LAYOUT_POLICY,
    DEFAULT_LAYOUT_POLICY["policy"]["default_profile"],
    scope="nested",
)
DEFAULT_MAIN_THRESHOLDS = LAYOUT.resolve_threshold_profile(
    DEFAULT_LAYOUT_POLICY,
    DEFAULT_LAYOUT_POLICY["policy"]["default_profile"],
    scope="main",
)


class LayoutPolicyTests(unittest.TestCase):
    def _simple_process_xml(self):
        return """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """

    def _wide_chain_process_xml(self, task_count=35):
        parts = [
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
            "<bpmn:definitions xmlns:bpmn=\"http://www.omg.org/spec/BPMN/20100524/MODEL\">",
            "  <bpmn:process id=\"Process_1\">",
            "    <bpmn:startEvent id=\"Start_1\" />",
        ]
        for index in range(1, task_count + 1):
            parts.append(f"    <bpmn:task id=\"Task_{index}\" name=\"Task {index}\" />")
        parts.append("    <bpmn:endEvent id=\"End_1\" />")
        previous = "Start_1"
        flow_index = 1
        for index in range(1, task_count + 1):
            task_id = f"Task_{index}"
            parts.append(
                f"    <bpmn:sequenceFlow id=\"Flow_{flow_index}\" sourceRef=\"{previous}\" targetRef=\"{task_id}\" />"
            )
            previous = task_id
            flow_index += 1
        parts.append(
            f"    <bpmn:sequenceFlow id=\"Flow_{flow_index}\" sourceRef=\"{previous}\" targetRef=\"End_1\" />"
        )
        parts.extend(["  </bpmn:process>", "</bpmn:definitions>"])
        return "\n".join(parts)

    def test_rect_intersect(self):
        self.assertTrue(LAYOUT.rect_intersect((0, 0, 20, 20), (10, 10, 20, 20)))
        self.assertFalse(LAYOUT.rect_intersect((0, 0, 20, 20), (30, 30, 20, 20)))

    def test_seg_hits_rect(self):
        self.assertTrue(LAYOUT.seg_hits_rect((0, 10), (30, 10), (5, 5, 10, 10)))
        self.assertFalse(LAYOUT.seg_hits_rect((0, 30), (30, 30), (5, 5, 10, 10)))

    def test_segment_intersection_invalid(self):
        self.assertTrue(LAYOUT.segment_intersection_invalid(((10, 0), (10, 20)), ((0, 10), (20, 10))))
        self.assertFalse(LAYOUT.segment_intersection_invalid(((10, 0), (10, 10)), ((10, 10), (20, 10))))
        self.assertTrue(LAYOUT.segment_intersection_invalid(((0, 10), (20, 10)), ((10, 10), (30, 10))))

    def test_detect_back_edges_cycle(self):
        nodes = {"Start": {}, "A": {}, "B": {}}
        outgoing = {"Start": ["A"], "A": ["B"], "B": ["A"]}
        self.assertEqual(LAYOUT.detect_back_edges(nodes, outgoing, ["Start"]), {("B", "A")})

    def test_compute_depths_handles_cycle(self):
        nodes = {
            "Start": {"type": "startEvent"},
            "A": {"type": "serviceTask"},
            "B": {"type": "serviceTask"},
        }
        flows = [
            {"source": "Start", "target": "A"},
            {"source": "A", "target": "B"},
            {"source": "B", "target": "A"},
        ]
        depth = LAYOUT.compute_depths(nodes, flows)
        self.assertEqual(depth["Start"], 0)
        self.assertGreaterEqual(depth["A"], 1)
        self.assertGreaterEqual(depth["B"], depth["A"])

    def test_path_anchor_mismatches(self):
        rect_a = (0, 0, 100, 80)
        rect_b = (200, 0, 100, 80)
        self.assertEqual(LAYOUT.path_anchor_mismatches([(100, 40), (200, 40)], rect_a, rect_b), 0)
        self.assertEqual(LAYOUT.path_anchor_mismatches([(95, 40), (200, 40)], rect_a, rect_b), 1)

    def test_anchor_uses_exact_visual_midpoints_for_gateway_and_event(self):
        gateway_rect = (100, 200, 50, 50)
        self.assertEqual(LAYOUT.anchor(gateway_rect, "right"), (150, 225))
        self.assertEqual(LAYOUT.anchor(gateway_rect, "bottom"), (125, 250))

        event_rect = (300, 400, 36, 36)
        self.assertEqual(LAYOUT.anchor(event_rect, "right"), (336, 418))
        self.assertEqual(LAYOUT.anchor(event_rect, "bottom"), (318, 436))

    def test_gateway_anchor_preference_penalty_prefers_same_lane_left_right(self):
        rects = {
            "Gateway_1": (100, 100, 50, 50),
            "Task_1": (300, 100, 180, 80),
        }
        lane = {"Gateway_1": 0, "Task_1": 0}
        nodes = {
            "Gateway_1": {"type": "exclusiveGateway"},
            "Task_1": {"type": "serviceTask"},
        }
        preferred = [LAYOUT.anchor(rects["Gateway_1"], "right"), LAYOUT.anchor(rects["Task_1"], "left")]
        nonpreferred = [LAYOUT.anchor(rects["Gateway_1"], "top"), LAYOUT.anchor(rects["Task_1"], "left")]
        self.assertEqual(
            LAYOUT.gateway_anchor_preference_penalty("Gateway_1", "Task_1", preferred, rects, lane, nodes),
            0,
        )
        self.assertGreater(
            LAYOUT.gateway_anchor_preference_penalty("Gateway_1", "Task_1", nonpreferred, rects, lane, nodes),
            0,
        )

    def test_load_existing_di_keeps_off_grid_waypoints(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                          xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                          xmlns:di="http://www.omg.org/spec/DD/20100524/DI">
          <bpmn:process id="Process_1">
            <bpmn:serviceTask id="Task_A" />
            <bpmn:serviceTask id="Task_B" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Task_A" targetRef="Task_B" />
          </bpmn:process>
          <bpmndi:BPMNDiagram id="BPMNDiagram_1">
            <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1">
              <bpmndi:BPMNShape id="Shape_Task_A" bpmnElement="Task_A">
                <dc:Bounds x="100" y="200" width="180" height="80" />
              </bpmndi:BPMNShape>
              <bpmndi:BPMNShape id="Shape_Task_B" bpmnElement="Task_B">
                <dc:Bounds x="500" y="200" width="180" height="80" />
              </bpmndi:BPMNShape>
              <bpmndi:BPMNEdge id="Edge_Flow_1" bpmnElement="Flow_1">
                <di:waypoint x="280" y="245" />
                <di:waypoint x="500" y="245" />
              </bpmndi:BPMNEdge>
            </bpmndi:BPMNPlane>
          </bpmndi:BPMNDiagram>
        </bpmn:definitions>
        """
        root = ET.fromstring(xml)
        _, _, edges, _, _, _, _ = LAYOUT.load_existing_di(root, {"Task_A", "Task_B"}, {"Flow_1"})
        self.assertEqual(edges["Flow_1"][0], (280, 245))
        self.assertEqual(edges["Flow_1"][-1], (500, 245))

    def test_load_layout_policy_config_uses_default_path(self):
        policy = LAYOUT.load_layout_policy_config()
        self.assertEqual(
            Path(policy["path"]),
            LAYOUT.default_layout_config_path(),
        )
        self.assertEqual(policy["policy"]["default_profile"], "native_preserve_existing")
        self.assertEqual(policy["policy"]["simple_default_profile"], "simple_postprocess_refine")
        self.assertEqual(policy["policy"]["simple_escalated_profile"], "simple_postprocess_repair")
        self.assertEqual(policy["policy"]["simple_fallback_profile"], "simple_postprocess_greenfield")

    def test_load_layout_policy_config_fails_fast_on_missing_required_keys(self):
        bad_policy = """
        policy:
          default_profile: native_preserve_existing
          fallback_profile: native_greenfield
          escalated_profile: native_repair_escalated
        profiles:
          native_greenfield:
            main:
              margin_x: 80
            nested:
              margin_x: 30
              margin_y: 50
              gap_x: 60
              gap_y: 90
              subrow_gap: 80
              max_shape_shift: 120
              max_label_shift: 80
          native_preserve_existing:
            main:
              margin_x: 80
              margin_y: 80
              gap_x: 80
              gap_y: 130
              subrow_gap: 100
              max_shape_shift: 120
              max_label_shift: 80
            nested:
              margin_x: 30
              margin_y: 50
              gap_x: 60
              gap_y: 90
              subrow_gap: 80
              max_shape_shift: 120
              max_label_shift: 80
          native_repair_escalated:
            main:
              margin_x: 80
              margin_y: 80
              gap_x: 80
              gap_y: 130
              subrow_gap: 100
              max_shape_shift: 120
              max_label_shift: 80
            nested:
              margin_x: 30
              margin_y: 50
              gap_x: 60
              gap_y: 90
              subrow_gap: 80
              max_shape_shift: 120
              max_label_shift: 80
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "layout_thresholds.yaml"
            config_path.write_text(bad_policy, encoding="utf-8")
            with self.assertRaisesRegex(
                LAYOUT.LayoutError,
                "profiles.native_greenfield.main: margin_y, gap_x, gap_y, subrow_gap, max_shape_shift, max_label_shift",
            ):
                LAYOUT.load_layout_policy_config(config_path)

    def test_resolve_threshold_profile_returns_explicit_main_and_nested_modes(self):
        self.assertTrue(set(LAYOUT.NATIVE_LAYOUT_PROFILES).issubset(set(DEFAULT_LAYOUT_POLICY["profiles"].keys())))
        preserve_main = LAYOUT.resolve_threshold_profile(DEFAULT_LAYOUT_POLICY, "native_preserve_existing", scope="main")
        greenfield_nested = LAYOUT.resolve_threshold_profile(DEFAULT_LAYOUT_POLICY, "native_greenfield", scope="nested")
        repair_main = LAYOUT.resolve_threshold_profile(DEFAULT_LAYOUT_POLICY, "native_repair_escalated", scope="main")
        self.assertEqual(preserve_main["gap_x"], 80)
        self.assertEqual(greenfield_nested["gap_x"], 60)
        self.assertEqual(repair_main["max_shape_shift"], 120)

    def test_resolve_threshold_profile_accepts_canonical_aliases(self):
        preserve_native = LAYOUT.resolve_threshold_profile(DEFAULT_LAYOUT_POLICY, "native_preserve_existing", scope="main")
        preserve_alias = LAYOUT.resolve_threshold_profile(DEFAULT_LAYOUT_POLICY, "preserve_existing", scope="main")
        greenfield_native = LAYOUT.resolve_threshold_profile(DEFAULT_LAYOUT_POLICY, "native_greenfield", scope="nested")
        greenfield_alias = LAYOUT.resolve_threshold_profile(DEFAULT_LAYOUT_POLICY, "greenfield_canonical", scope="nested")
        repair_native = LAYOUT.resolve_threshold_profile(DEFAULT_LAYOUT_POLICY, "native_repair_escalated", scope="main")
        repair_alias = LAYOUT.resolve_threshold_profile(DEFAULT_LAYOUT_POLICY, "repair_escalated", scope="main")
        self.assertEqual(preserve_alias, preserve_native)
        self.assertEqual(greenfield_alias, greenfield_native)
        self.assertEqual(repair_alias, repair_native)

    def test_load_layout_policy_config_resolves_alias_policy_names(self):
        config = """
        policy:
          default_profile: preserve_existing
          fallback_profile: greenfield_canonical
          escalated_profile: repair_escalated
        profiles:
          greenfield_canonical:
            main:
              margin_x: 80
              margin_y: 80
              gap_x: 80
              gap_y: 130
              subrow_gap: 100
              max_shape_shift: 120
              max_label_shift: 80
            nested:
              margin_x: 30
              margin_y: 50
              gap_x: 60
              gap_y: 90
              subrow_gap: 80
              max_shape_shift: 120
              max_label_shift: 80
          preserve_existing:
            main:
              margin_x: 80
              margin_y: 80
              gap_x: 80
              gap_y: 130
              subrow_gap: 100
              max_shape_shift: 120
              max_label_shift: 80
            nested:
              margin_x: 30
              margin_y: 50
              gap_x: 60
              gap_y: 90
              subrow_gap: 80
              max_shape_shift: 120
              max_label_shift: 80
          repair_escalated:
            main:
              margin_x: 80
              margin_y: 80
              gap_x: 80
              gap_y: 130
              subrow_gap: 100
              max_shape_shift: 120
              max_label_shift: 80
            nested:
              margin_x: 30
              margin_y: 50
              gap_x: 60
              gap_y: 90
              subrow_gap: 80
              max_shape_shift: 120
              max_label_shift: 80
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "layout_thresholds.yaml"
            config_path.write_text(config, encoding="utf-8")
            policy = LAYOUT.load_layout_policy_config(config_path)
        self.assertEqual(policy["policy"]["default_profile"], "native_preserve_existing")
        self.assertEqual(policy["policy"]["fallback_profile"], "native_greenfield")
        self.assertEqual(policy["policy"]["escalated_profile"], "native_repair_escalated")

    def test_resolve_threshold_profile_includes_framing_policy_keys(self):
        preserve_main = LAYOUT.resolve_threshold_profile(DEFAULT_LAYOUT_POLICY, "native_preserve_existing", scope="main")
        self.assertEqual(preserve_main["participant_band_margin"], 40)
        self.assertEqual(preserve_main["lane_inset_x"], 10)
        self.assertEqual(preserve_main["compaction_margin"], 40)
        self.assertEqual(preserve_main["max_participant_lane_shift"], 120)
        self.assertEqual(preserve_main["label_conflict_max_budget"], 200)
        self.assertEqual(preserve_main["edge_reroute_max_passes"], 5)

    def test_initial_route_uses_threshold_offsets(self):
        route = LAYOUT.initial_route(
            (0, 0, 100, 80),
            (300, 0, 100, 80),
            0,
            0,
            thresholds={
                "edge_route_same_lane_knee_offset": 70,
                "edge_route_vertical_mid_offset": 90,
                "edge_route_horizontal_mid_offset": 110,
            },
        )
        self.assertEqual(route[1][0] - route[0][0], 70)
        self.assertEqual(route[-2][0] - route[0][0], 70)

    def test_load_layout_policy_config_rejects_non_integral_numeric_and_bool_thresholds(self):
        invalid_configs = (
            (
                """
                policy:
                  default_profile: native_preserve_existing
                  fallback_profile: native_greenfield
                  escalated_profile: native_repair_escalated
                profiles:
                  native_greenfield:
                    main:
                      margin_x: 80
                      margin_y: 80
                      gap_x: 80.5
                      gap_y: 130
                      subrow_gap: 100
                      max_shape_shift: 120
                      max_label_shift: 80
                    nested:
                      margin_x: 30
                      margin_y: 50
                      gap_x: 60
                      gap_y: 90
                      subrow_gap: 80
                      max_shape_shift: 120
                      max_label_shift: 80
                  native_preserve_existing:
                    main:
                      margin_x: 80
                      margin_y: 80
                      gap_x: 80
                      gap_y: 130
                      subrow_gap: 100
                      max_shape_shift: 120
                      max_label_shift: 80
                    nested:
                      margin_x: 30
                      margin_y: 50
                      gap_x: 60
                      gap_y: 90
                      subrow_gap: 80
                      max_shape_shift: 120
                      max_label_shift: 80
                  native_repair_escalated:
                    main:
                      margin_x: 80
                      margin_y: 80
                      gap_x: 80
                      gap_y: 130
                      subrow_gap: 100
                      max_shape_shift: 120
                      max_label_shift: 80
                    nested:
                      margin_x: 30
                      margin_y: 50
                      gap_x: 60
                      gap_y: 90
                      subrow_gap: 80
                      max_shape_shift: 120
                      max_label_shift: 80
                """,
                "profiles.native_greenfield.main.gap_x",
            ),
            (
                """
                policy:
                  default_profile: native_preserve_existing
                  fallback_profile: native_greenfield
                  escalated_profile: native_repair_escalated
                profiles:
                  native_greenfield:
                    main:
                      margin_x: 80
                      margin_y: 80
                      gap_x: 80
                      gap_y: 130
                      subrow_gap: 100
                      max_shape_shift: true
                      max_label_shift: 80
                    nested:
                      margin_x: 30
                      margin_y: 50
                      gap_x: 60
                      gap_y: 90
                      subrow_gap: 80
                      max_shape_shift: 120
                      max_label_shift: 80
                  native_preserve_existing:
                    main:
                      margin_x: 80
                      margin_y: 80
                      gap_x: 80
                      gap_y: 130
                      subrow_gap: 100
                      max_shape_shift: 120
                      max_label_shift: 80
                    nested:
                      margin_x: 30
                      margin_y: 50
                      gap_x: 60
                      gap_y: 90
                      subrow_gap: 80
                      max_shape_shift: 120
                      max_label_shift: 80
                  native_repair_escalated:
                    main:
                      margin_x: 80
                      margin_y: 80
                      gap_x: 80
                      gap_y: 130
                      subrow_gap: 100
                      max_shape_shift: 120
                      max_label_shift: 80
                    nested:
                      margin_x: 30
                      margin_y: 50
                      gap_x: 60
                      gap_y: 90
                      subrow_gap: 80
                      max_shape_shift: 120
                      max_label_shift: 80
                """,
                "profiles.native_greenfield.main.max_shape_shift",
            ),
        )
        for config_text, key_path in invalid_configs:
            with self.subTest(key_path=key_path), tempfile.TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "layout_thresholds.yaml"
                config_path.write_text(config_text, encoding="utf-8")
                with self.assertRaisesRegex(LAYOUT.LayoutError, key_path):
                    LAYOUT.load_layout_policy_config(config_path)

    def test_extract_lane_membership(self):
        xml = """
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:laneSet id="LaneSet_1">
              <bpmn:lane id="Lane_A"><bpmn:flowNodeRef>Task_A</bpmn:flowNodeRef></bpmn:lane>
              <bpmn:lane id="Lane_B"><bpmn:flowNodeRef>Task_B</bpmn:flowNodeRef></bpmn:lane>
            </bpmn:laneSet>
          </bpmn:process>
        </bpmn:definitions>
        """
        root = ET.fromstring(xml)
        process = root.find(LAYOUT.q("bpmn", "process"))
        lanes = LAYOUT.extract_lane_membership(process)
        self.assertEqual(lanes["Task_A"], 0)
        self.assertEqual(lanes["Task_B"], 1)

    def test_collect_direct_container_graph_includes_generic_task(self):
        xml = """
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
        root = ET.fromstring(xml)
        process = root.find(LAYOUT.q("bpmn", "process"))
        nodes, flows, _ = LAYOUT.collect_direct_container_graph(process, "Process_1")
        self.assertIn("Task_1", nodes)
        self.assertEqual(nodes["Task_1"]["type"], "task")
        self.assertEqual(len(flows), 2)

    def test_collect_direct_container_graph_includes_transaction_and_adhoc(self):
        xml = """
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:transaction id="Txn_1" name="Transactional step" />
            <bpmn:adHocSubProcess id="AdHoc_1" name="Coordinate handlers" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Txn_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Txn_1" targetRef="AdHoc_1" />
            <bpmn:sequenceFlow id="Flow_3" sourceRef="AdHoc_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        root = ET.fromstring(xml)
        process = root.find(LAYOUT.q("bpmn", "process"))
        nodes, flows, subprocesses = LAYOUT.collect_direct_container_graph(process, "Process_1")
        self.assertEqual(nodes["Txn_1"]["type"], "transaction")
        self.assertEqual(nodes["AdHoc_1"]["type"], "adHocSubProcess")
        self.assertIn("Txn_1", subprocesses)
        self.assertIn("AdHoc_1", subprocesses)
        self.assertEqual(len(flows), 3)

    def test_infer_lane_keywords(self):
        self.assertEqual(LAYOUT.infer_lane("Task_ErrorHandler"), 3)
        self.assertEqual(LAYOUT.infer_lane("Task_EscalateToHuman"), 2)
        self.assertEqual(LAYOUT.infer_lane("Gateway_ApprovalRequired"), 1)
        self.assertEqual(LAYOUT.infer_lane("Task_Normal"), 0)

    def test_node_dims_type_override(self):
        dims = LAYOUT.node_dims("userTask", "Review order", {"userTask": {"width": 240, "height": 100}})
        self.assertEqual(dims, (240, 100))

    def test_default_label_rect_gateway_and_event(self):
        gateway_rect = (100, 100, 50, 50)
        event_rect = (200, 200, 36, 36)
        gateway_primary = LAYOUT.default_label_rect("parallelGateway", gateway_rect, 80, 20, alternate=False)
        gateway_alternate = LAYOUT.default_label_rect("parallelGateway", gateway_rect, 80, 20, alternate=True)
        event_primary = LAYOUT.default_label_rect("intermediateCatchEvent", event_rect, 80, 20, alternate=False)
        event_alternate = LAYOUT.default_label_rect("intermediateCatchEvent", event_rect, 80, 20, alternate=True)
        self.assertLess(gateway_primary[1], gateway_rect[1])
        self.assertGreater(gateway_alternate[1], gateway_rect[1] + gateway_rect[3])
        self.assertGreater(event_primary[1], event_rect[1] + event_rect[3])
        self.assertLess(event_alternate[1], event_rect[1])

    def test_label_candidate_rects_respect_budget(self):
        rect = (100, 100, 50, 50)
        current = [90, 60, 80, 20]
        baseline = [90, 60, 80, 20]
        candidates = LAYOUT.label_candidate_rects("exclusiveGateway", rect, current, baseline_rect=baseline, budget=80)
        self.assertTrue(candidates)
        self.assertTrue(all(LAYOUT.rect_distance(candidate, baseline) <= 80 for candidate in candidates))

    def test_label_candidate_rects_use_policy_shift_levels(self):
        rect = (100, 100, 50, 50)
        current = [90, 60, 80, 20]
        thresholds = dict(DEFAULT_MAIN_THRESHOLDS, label_conflict_shift_step=30, label_conflict_shift_levels=2)
        candidates = LAYOUT.label_candidate_rects(
            "exclusiveGateway",
            rect,
            current,
            baseline_rect=current,
            budget=90,
            thresholds=thresholds,
        )
        ys = sorted({candidate[1] for candidate in candidates})
        self.assertIn(40, ys)
        self.assertIn(100, ys)
        self.assertNotIn(160, ys)

    def test_build_participant_rect_includes_labels(self):
        rects = {"Task_1": (100, 100, 180, 80)}
        nodes = {"Task_1": {"process_id": "Process_1"}}
        label_rects = {"Task_1": [80, 40, 120, 20]}
        participant_rect = LAYOUT.build_participant_rect("Process_1", rects, nodes, label_rects=label_rects, margin=40)
        self.assertEqual(participant_rect, (40, 0, 280, 220))

    def test_build_participant_rect_uses_policy_backed_margin(self):
        rects = {"Task_1": (100, 100, 180, 80)}
        nodes = {"Task_1": {"process_id": "Process_1"}}
        default_rect = LAYOUT.build_participant_rect("Process_1", rects, nodes, thresholds=DEFAULT_MAIN_THRESHOLDS)
        roomy_thresholds = dict(DEFAULT_MAIN_THRESHOLDS, participant_band_margin=90)
        roomy_rect = LAYOUT.build_participant_rect("Process_1", rects, nodes, thresholds=roomy_thresholds)
        self.assertEqual(default_rect, (60, 60, 260, 160))
        self.assertEqual(roomy_rect, (10, 10, 360, 260))

    def test_build_process_envelope_includes_labels(self):
        rects = {"Task_1": (100, 100, 180, 80)}
        nodes = {"Task_1": {"process_id": "Process_1"}}
        label_rects = {"Task_1": [80, 40, 120, 20]}
        process_rect = LAYOUT.build_process_envelope(
            "Process_1",
            rects,
            nodes,
            label_rects=label_rects,
            thresholds=DEFAULT_MAIN_THRESHOLDS,
        )
        self.assertEqual(process_rect, (40, 0, 280, 220))

    def test_prune_channels_limits_candidates(self):
        channels = list(range(0, 500, 20))
        pruned = LAYOUT.prune_channels(channels, 100, 180, margin=80, outer_count=1, limit=6)
        self.assertLessEqual(len(pruned), 6)
        self.assertIn(100, pruned)

    def test_nudge_rect_toward_prefers_target(self):
        candidate = LAYOUT.nudge_rect_toward((0, 0, 100, 80), (60, 40, 100, 80), baseline_rect=(0, 0, 100, 80), budget=120)
        self.assertEqual(candidate, (20, 20, 100, 80))

    def test_nudge_rect_toward_pushes_away_from_overlap(self):
        current = (100, 100, 100, 80)
        blocker = (150, 100, 100, 80)
        candidate = LAYOUT.nudge_rect_toward(
            current,
            current,
            baseline_rect=current,
            budget=120,
            avoid_rects=[blocker],
        )
        self.assertNotEqual(candidate, current)
        self.assertFalse(LAYOUT.rect_intersect(candidate, blocker))

    def test_compute_separation_vector(self):
        rect_a = (100, 100, 100, 80)
        rect_b = (150, 100, 100, 80)
        dx, dy = LAYOUT.compute_separation_vector(rect_a, rect_b, 20)
        candidate = LAYOUT.apply_separation(rect_a, (dx, dy))
        self.assertFalse(LAYOUT.rect_intersect(candidate, rect_b, pad=20))

    def test_resolve_all_overlaps(self):
        rects = {
            "A": (100, 100, 100, 80),
            "B": (130, 120, 100, 80),
        }
        canonical = {
            "A": (100, 100, 100, 80),
            "B": (260, 120, 100, 80),
        }
        resolved = LAYOUT.resolve_all_overlaps(rects, canonical, {"A": rects["A"]}, budget=120, min_gap=0)
        self.assertEqual(LAYOUT.find_all_overlaps(resolved), [])

    def test_path_endpoint_direction_violations(self):
        rect_a = (1110, 80, 60, 50)
        rect_b = (1330, 560, 60, 80)
        good = [(1140, 130), (1140, 160), (1120, 160), (1120, 600), (1330, 600)]
        bad = [(1140, 130), (1140, 90), (1120, 90), (1120, 600), (1330, 600)]
        self.assertEqual(LAYOUT.path_endpoint_direction_violations(good, rect_a, rect_b), 0)
        self.assertGreater(LAYOUT.path_endpoint_direction_violations(bad, rect_a, rect_b), 0)

    def test_compact_layout_reduces_excessive_column_gap(self):
        rects = {
            "A": (80, 80, 180, 80),
            "B": (500, 80, 180, 80),
        }
        label_rects = {}
        lane = {"A": 0, "B": 0}
        depth = {"A": 0, "B": 1}
        compacted_rects, compacted_labels = LAYOUT.compact_layout(
            rects, label_rects, {}, [], lane, depth, 80, 130, 100, 40
        )
        gap = compacted_rects["B"][0] - (compacted_rects["A"][0] + compacted_rects["A"][2])
        self.assertLessEqual(gap, 120)
        self.assertGreaterEqual(gap, 80)

    def test_compact_layout_expands_insufficient_column_gap(self):
        rects = {
            "A": (100, 100, 40, 40),
            "B": (200, 80, 100, 80),
            "C": (360, 100, 40, 40),
        }
        label_rects = {}
        lane = {"A": 0, "B": 0, "C": 0}
        depth = {"A": 0, "B": 1, "C": 2}
        compacted_rects, _ = LAYOUT.compact_layout(
            rects,
            label_rects,
            {},
            [],
            lane,
            depth,
            80,
            130,
            100,
            40,
        )
        gap_ab = compacted_rects["B"][0] - (compacted_rects["A"][0] + compacted_rects["A"][2])
        gap_bc = compacted_rects["C"][0] - (compacted_rects["B"][0] + compacted_rects["B"][2])
        self.assertEqual(gap_ab, 80)
        self.assertEqual(gap_bc, 80)

    def test_fanout_shared_source_edges(self):
        flows = [
            {"id": "F1", "source": "Gateway", "target": "Task_A"},
            {"id": "F2", "source": "Gateway", "target": "Task_B"},
        ]
        rects = {
            "Gateway": (1110, 80, 60, 50),
            "Task_A": (1240, 430, 180, 80),
            "Task_B": (1240, 640, 180, 80),
        }
        edge_paths = {
            "F1": [(1140, 80), (1140, 60), (1120, 60), (1120, 430), (1240, 430)],
            "F2": [(1140, 80), (1140, 60), (1120, 60), (1120, 640), (1240, 640)],
        }
        fanout_paths, actions = LAYOUT.fanout_shared_source_edges(flows, edge_paths, rects)
        self.assertNotEqual(fanout_paths["F1"][2][0], fanout_paths["F2"][2][0])
        self.assertTrue(actions)

    def test_count_edge_crossings(self):
        edge_paths = {
            "Flow_A": [(0, 10), (20, 10)],
            "Flow_B": [(10, 0), (10, 20)],
        }
        crossings = LAYOUT.count_edge_crossings("Flow_A", edge_paths["Flow_A"], edge_paths)
        self.assertEqual(crossings, 1)

    def test_score_edge_candidate_prefers_clean_path(self):
        rects = {
            "A": (0, 0, 100, 80),
            "B": (200, 0, 100, 80),
        }
        lane = {"A": 0, "B": 0}
        nodes = {"A": {"type": "serviceTask"}, "B": {"type": "serviceTask"}}
        items = [("shape", "A", rects["A"]), ("shape", "B", rects["B"])]
        edge_paths = {"Flow_1": [(100, 40), (200, 40)]}
        score, hits, crossings, anchor_issues, quality_issues = LAYOUT.score_edge_candidate(
            "Flow_1",
            [(100, 40), (200, 40)],
            "A",
            "B",
            rects,
            items,
            edge_paths,
            [(100, 40), (200, 40)],
            lane,
            nodes,
        )
        self.assertEqual(len(hits), 0)
        self.assertEqual(crossings, 0)
        self.assertEqual(anchor_issues, 0)
        self.assertEqual(quality_issues, 0)
        self.assertEqual(score[0:4], (0, 0, 0, 0))

    def test_collect_direct_container_graph_skips_nested_children(self):
        xml = """
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:serviceTask id="Task_Outer" name="Outer" />
            <bpmn:subProcess id="Sub_1" name="Embedded">
              <bpmn:startEvent id="Start_Inner" />
              <bpmn:serviceTask id="Task_Inner" name="Inner" />
              <bpmn:endEvent id="End_Inner" />
              <bpmn:sequenceFlow id="Flow_I1" sourceRef="Start_Inner" targetRef="Task_Inner" />
              <bpmn:sequenceFlow id="Flow_I2" sourceRef="Task_Inner" targetRef="End_Inner" />
            </bpmn:subProcess>
          </bpmn:process>
        </bpmn:definitions>
        """
        root = ET.fromstring(xml)
        process = root.find(LAYOUT.q("bpmn", "process"))
        nodes, flows, subprocesses = LAYOUT.collect_direct_container_graph(process, "Process_1")
        self.assertIn("Task_Outer", nodes)
        self.assertIn("Sub_1", nodes)
        self.assertNotIn("Task_Inner", nodes)
        self.assertEqual(flows, [])
        self.assertIn("Sub_1", subprocesses)

    def test_build_subprocess_layout_spec_expands_outer_dims(self):
        xml = """
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:subProcess id="Sub_1" name="Embedded">
              <bpmn:startEvent id="Start_Inner" />
              <bpmn:serviceTask id="Task_Inner" name="Inner task" />
              <bpmn:endEvent id="End_Inner" />
              <bpmn:sequenceFlow id="Flow_I1" sourceRef="Start_Inner" targetRef="Task_Inner" />
              <bpmn:sequenceFlow id="Flow_I2" sourceRef="Task_Inner" targetRef="End_Inner" />
            </bpmn:subProcess>
          </bpmn:process>
        </bpmn:definitions>
        """
        root = ET.fromstring(xml)
        process = root.find(LAYOUT.q("bpmn", "process"))
        subprocess = process.find(LAYOUT.q("bpmn", "subProcess"))
        spec = LAYOUT.build_subprocess_layout_spec(subprocess, "Process_1", {}, {}, {}, DEFAULT_NESTED_THRESHOLDS)
        self.assertTrue(spec["expanded"])
        self.assertGreaterEqual(spec["outer_dims"][0], 300)
        self.assertGreaterEqual(spec["outer_dims"][1], 150)

    def test_build_subprocess_layout_spec_uses_mode_specific_nested_thresholds(self):
        xml = """
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:subProcess id="Sub_1" name="Embedded">
              <bpmn:startEvent id="Start_Inner" />
              <bpmn:serviceTask id="Task_Inner" name="Inner task" />
              <bpmn:endEvent id="End_Inner" />
              <bpmn:sequenceFlow id="Flow_I1" sourceRef="Start_Inner" targetRef="Task_Inner" />
              <bpmn:sequenceFlow id="Flow_I2" sourceRef="Task_Inner" targetRef="End_Inner" />
            </bpmn:subProcess>
          </bpmn:process>
        </bpmn:definitions>
        """
        root = ET.fromstring(xml)
        process = root.find(LAYOUT.q("bpmn", "process"))
        subprocess = process.find(LAYOUT.q("bpmn", "subProcess"))
        tight_thresholds = {
            "margin_x": 30,
            "margin_y": 50,
            "gap_x": 60,
            "gap_y": 90,
            "subrow_gap": 80,
            "max_shape_shift": 120,
            "max_label_shift": 80,
            "container_padding_x": 20,
            "container_padding_y": 20,
        }
        roomy_thresholds = {
            "margin_x": 30,
            "margin_y": 50,
            "gap_x": 60,
            "gap_y": 90,
            "subrow_gap": 80,
            "max_shape_shift": 120,
            "max_label_shift": 80,
            "container_padding_x": 140,
            "container_padding_y": 100,
        }
        tight_spec = LAYOUT.build_subprocess_layout_spec(subprocess, "Process_1", {}, {}, {}, tight_thresholds)
        roomy_spec = LAYOUT.build_subprocess_layout_spec(subprocess, "Process_1", {}, {}, {}, roomy_thresholds)
        self.assertNotEqual(tight_spec["outer_dims"], roomy_spec["outer_dims"])
        self.assertGreater(roomy_spec["outer_dims"][0], tight_spec["outer_dims"][0])
        self.assertGreater(roomy_spec["outer_dims"][1], tight_spec["outer_dims"][1])

    def test_build_transaction_layout_spec_expands_outer_dims(self):
        xml = """
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:transaction id="Txn_1" name="Embedded transaction">
              <bpmn:startEvent id="Start_Inner" />
              <bpmn:serviceTask id="Task_Inner" name="Inner task" />
              <bpmn:endEvent id="End_Inner" />
              <bpmn:sequenceFlow id="Flow_I1" sourceRef="Start_Inner" targetRef="Task_Inner" />
              <bpmn:sequenceFlow id="Flow_I2" sourceRef="Task_Inner" targetRef="End_Inner" />
            </bpmn:transaction>
          </bpmn:process>
        </bpmn:definitions>
        """
        root = ET.fromstring(xml)
        process = root.find(LAYOUT.q("bpmn", "process"))
        transaction = process.find(LAYOUT.q("bpmn", "transaction"))
        spec = LAYOUT.build_subprocess_layout_spec(transaction, "Process_1", {}, {}, {}, DEFAULT_NESTED_THRESHOLDS)
        self.assertTrue(spec["expanded"])
        self.assertGreaterEqual(spec["outer_dims"][0], 300)
        self.assertGreaterEqual(spec["outer_dims"][1], 150)

    def test_apply_nested_subprocess_layouts_offsets_inner_nodes(self):
        xml = """
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:subProcess id="Sub_1" name="Embedded">
              <bpmn:startEvent id="Start_Inner" />
              <bpmn:serviceTask id="Task_Inner" name="Inner task" />
              <bpmn:endEvent id="End_Inner" />
              <bpmn:sequenceFlow id="Flow_I1" sourceRef="Start_Inner" targetRef="Task_Inner" />
              <bpmn:sequenceFlow id="Flow_I2" sourceRef="Task_Inner" targetRef="End_Inner" />
            </bpmn:subProcess>
          </bpmn:process>
        </bpmn:definitions>
        """
        root = ET.fromstring(xml)
        process = root.find(LAYOUT.q("bpmn", "process"))
        subprocess = process.find(LAYOUT.q("bpmn", "subProcess"))
        spec = LAYOUT.build_subprocess_layout_spec(subprocess, "Process_1", {}, {}, {}, DEFAULT_NESTED_THRESHOLDS)
        rects = {"Sub_1": (400, 200, spec["outer_dims"][0], spec["outer_dims"][1])}
        labels = {}
        edge_paths = {}
        nodes = {"Sub_1": {"id": "Sub_1", "type": "subProcess", "process_id": "Process_1", "container_id": "Process_1"}}
        flows = []
        notes = []
        LAYOUT.apply_nested_subprocess_layouts(
            {"Sub_1": spec},
            rects,
            labels,
            edge_paths,
            nodes,
            flows,
            notes,
            DEFAULT_LAYOUT_POLICY["policy"]["fallback_profile"],
            DEFAULT_NESTED_THRESHOLDS,
        )
        self.assertIn("Task_Inner", rects)
        self.assertGreater(rects["Task_Inner"][0], rects["Sub_1"][0])
        self.assertGreater(rects["Task_Inner"][1], rects["Sub_1"][1])
        self.assertIn("Flow_I1", edge_paths)
        self.assertTrue(notes)

    def test_apply_nested_subprocess_layouts_uses_mode_specific_thresholds(self):
        spec = {
            "container_id": "Sub_1",
            "expanded": True,
            "nodes": {},
            "flows": [],
            "lane": {},
            "dims": {},
            "subprocess_specs": {},
        }
        nested_thresholds = {
            "margin_x": 45,
            "margin_y": 55,
            "gap_x": 75,
            "gap_y": 95,
            "subrow_gap": 85,
            "max_shape_shift": 125,
            "max_label_shift": 82,
        }
        with patch.object(
            LAYOUT,
            "run_layout_pipeline",
            return_value={
                "rects": {},
                "label_rects": {},
                "edge_paths": {},
                "metrics": {},
                "actions": [],
                "depth": {},
                "slot": {},
                "shape_baseline": {},
                "label_baseline": {},
            },
        ) as mocked_pipeline:
            LAYOUT.apply_nested_subprocess_layouts(
                {"Sub_1": spec},
                {"Sub_1": (100, 100, 220, 120)},
                {},
                {},
                {"Sub_1": {"id": "Sub_1", "type": "subProcess", "process_id": "Process_1", "container_id": "Process_1"}},
                [],
                [],
                "native_repair_escalated",
                nested_thresholds,
            )
        args = mocked_pipeline.call_args.args
        self.assertEqual(args[0], "native_repair_escalated")
        self.assertEqual(args[8], nested_thresholds)

    def test_attach_boundary_events_places_event_on_host_border(self):
        rects = {
            "Task_1": (200, 100, 180, 80),
            "Boundary_1": (260, 160, 36, 36),
        }
        nodes = {
            "Task_1": {"type": "userTask"},
            "Boundary_1": {"type": "boundaryEvent", "attached_to": "Task_1"},
        }
        attached, _ = LAYOUT.attach_boundary_events(rects, nodes, baseline_rects=rects)
        bx, by, bw, bh = attached["Boundary_1"]
        self.assertEqual(by, LAYOUT.snap(100 + 80 - bh / 2.0))
        self.assertGreaterEqual(bx, 200)
        self.assertLessEqual(bx + bw, 200 + 180)

    def test_verify_and_report_ignores_attached_boundary_overlap(self):
        rects = {
            "Task_1": (200, 100, 180, 80),
            "Boundary_1": (272, 162, 36, 36),
        }
        nodes = {
            "Task_1": {"type": "userTask"},
            "Boundary_1": {"type": "boundaryEvent", "attached_to": "Task_1"},
        }
        metrics = LAYOUT.verify_and_report(
            rects,
            {},
            {},
            [],
            {"Task_1": 0, "Boundary_1": 0},
            {"Task_1": 0, "Boundary_1": 0},
            nodes,
            {},
            {},
            120,
            80,
        )
        self.assertEqual(metrics["shape_shape"], 0)

    def test_verify_and_report_splits_drift_channels(self):
        rects = {
            "Task_1": (100, 100, 180, 80),
            "Task_2": (340, 100, 180, 80),
        }
        label_rects = {
            "Task_1": [100, 190, 80, 20],
        }
        nodes = {
            "Task_1": {"type": "userTask"},
            "Task_2": {"type": "serviceTask"},
        }
        metrics = LAYOUT.verify_and_report(
            rects,
            label_rects,
            {},
            [],
            {"Task_1": 0, "Task_2": 1},
            {"Task_1": 0, "Task_2": 0},
            nodes,
            {
                "Task_1": (100, 100, 180, 80),
                "Task_2": (300, 100, 180, 80),
            },
            {
                "Task_1": [100, 170, 80, 20],
            },
            120,
            80,
            participant_lane_bounds={"Participant_1": (40, 40, 600, 260)},
            existing_participant_lane_bounds={"Participant_1": (20, 40, 600, 260)},
        )
        self.assertEqual(metrics["shape_move_total"], 40.0)
        self.assertEqual(metrics["label_move_total"], 20.0)
        self.assertEqual(metrics["drift_channels"]["untouched_shapes"]["count"], 1)
        self.assertEqual(metrics["drift_channels"]["untouched_shapes"]["moved"], 0)
        self.assertEqual(metrics["drift_channels"]["untouched_shapes"]["budget"], 0.0)
        self.assertEqual(metrics["drift_channels"]["untouched_shapes"]["violations"], 0)
        self.assertEqual(metrics["drift_channels"]["touched_repaired_shapes"]["count"], 1)
        self.assertEqual(metrics["drift_channels"]["touched_repaired_shapes"]["moved"], 1)
        self.assertEqual(metrics["drift_channels"]["touched_repaired_shapes"]["total"], 40.0)
        self.assertEqual(metrics["drift_channels"]["touched_repaired_shapes"]["budget"], 120.0)
        self.assertEqual(metrics["drift_channels"]["touched_repaired_shapes"]["violations"], 0)
        self.assertEqual(metrics["drift_channels"]["participant_lane_bounds"]["count"], 1)
        self.assertEqual(metrics["drift_channels"]["participant_lane_bounds"]["moved"], 1)
        self.assertEqual(metrics["drift_channels"]["participant_lane_bounds"]["total"], 20.0)
        self.assertEqual(metrics["drift_channels"]["participant_lane_bounds"]["budget"], 120.0)
        self.assertEqual(metrics["drift_channels"]["participant_lane_bounds"]["violations"], 0)
        self.assertEqual(metrics["drift_channels"]["labels"]["count"], 1)
        self.assertEqual(metrics["drift_channels"]["labels"]["moved"], 1)
        self.assertEqual(metrics["drift_channels"]["labels"]["budget"], 80.0)
        self.assertEqual(metrics["drift_channels"]["labels"]["violations"], 0)

    def test_verify_and_report_tracks_per_channel_budget_overruns(self):
        metrics = LAYOUT.verify_and_report(
            {"Task_1": (260, 100, 180, 80)},
            {"Task_1": [100, 310, 80, 20]},
            {},
            [],
            {"Task_1": 0},
            {"Task_1": 0},
            {"Task_1": {"type": "userTask"}},
            {"Task_1": (100, 100, 180, 80)},
            {"Task_1": [100, 170, 80, 20]},
            120,
            80,
            participant_lane_budget=15,
            participant_lane_bounds={"Participant_1": (60, 40, 600, 260)},
            existing_participant_lane_bounds={"Participant_1": (20, 40, 600, 260)},
        )
        self.assertEqual(metrics["shape_budget_violations"], 1)
        self.assertEqual(metrics["label_budget_violations"], 1)
        self.assertEqual(metrics["participant_lane_budget_violations"], 1)
        self.assertEqual(metrics["drift_channels"]["touched_repaired_shapes"]["violations"], 1)
        self.assertEqual(metrics["drift_channels"]["touched_repaired_shapes"]["max_over_budget"], 40.0)
        self.assertEqual(metrics["drift_channels"]["labels"]["violations"], 1)
        self.assertEqual(metrics["drift_channels"]["labels"]["max_over_budget"], 60.0)
        self.assertEqual(metrics["drift_channels"]["participant_lane_bounds"]["violations"], 1)
        self.assertEqual(metrics["drift_channels"]["participant_lane_bounds"]["max_over_budget"], 25.0)
        self.assertTrue(LAYOUT.has_violations(metrics))
        self.assertFalse(LAYOUT.has_violations(metrics, include_budget_violations=False))

    def test_verify_and_report_uses_gap_violation_tolerances_from_thresholds(self):
        rects = {
            "Task_A": (100, 100, 180, 80),
            "Task_B": (380, 280, 180, 80),
        }
        nodes = {
            "Task_A": {"type": "userTask"},
            "Task_B": {"type": "serviceTask"},
        }
        metrics = LAYOUT.verify_and_report(
            rects,
            {},
            {},
            [],
            {"Task_A": 0, "Task_B": 1},
            {"Task_A": 0, "Task_B": 1},
            nodes,
            {},
            {},
            120,
            80,
            thresholds={
                "column_gap_violation_tolerance": 0,
                "lane_gap_violation_tolerance": 0,
            },
        )
        self.assertEqual(metrics["column_gap_violations"], 1)
        self.assertEqual(metrics["lane_gap_violations"], 1)

    def test_run_layout_pipeline_can_report_against_original_baseline(self):
        nodes = {
            "Task_1": {"type": "userTask"},
        }
        result = LAYOUT.run_layout_pipeline(
            "native_greenfield",
            nodes,
            [],
            {"Task_1": 0},
            {"Task_1": (180, 80)},
            {},
            {},
            {},
            DEFAULT_MAIN_THRESHOLDS,
            report_shape_baseline={"Task_1": (300, 100, 180, 80)},
            report_label_baseline={},
        )
        self.assertEqual(result["shape_baseline"]["Task_1"], (300, 100, 180, 80))
        self.assertGreater(result["metrics"]["shape_move_total"], 0.0)

    def test_verify_and_report_emits_typed_issue_schema(self):
        metrics = LAYOUT.verify_and_report(
            {"Task_A": (100, 100, 100, 80), "Task_B": (150, 120, 100, 80)},
            {},
            {},
            [],
            {"Task_A": 0, "Task_B": 1},
            {"Task_A": 0, "Task_B": 0},
            {"Task_A": {"type": "userTask"}, "Task_B": {"type": "serviceTask"}},
            {"Task_A": (0, 0, 100, 80)},
            {},
            50,
            80,
            thresholds=DEFAULT_MAIN_THRESHOLDS,
        )
        self.assertTrue(metrics["typed_issues"])
        issue = metrics["typed_issues"][0]
        self.assertEqual(set(issue.keys()), {"target_type", "element_id", "secondary_element_id", "bbox", "severity", "code"})
        self.assertIsInstance(issue["bbox"], list)

    def test_conflict_fixture_02_edge_label_issue_is_typed(self):
        rects = {
            "Start_1": (100, 100, 36, 36),
            "Task_Mid": (200, 80, 180, 80),
            "End_1": (320, 100, 36, 36),
        }
        label_rects = {
            "Task_Mid": [190, 110, 80, 20],
        }
        flows = [{"id": "Flow_1", "source": "Start_1", "target": "End_1"}]
        edge_paths = {"Flow_1": [(136, 118), (320, 118)]}
        metrics = LAYOUT.verify_and_report(
            rects,
            label_rects,
            edge_paths,
            flows,
            {"Start_1": 0, "Task_Mid": 0, "End_1": 1},
            {"Start_1": 0, "Task_Mid": 0, "End_1": 0},
            {"Start_1": {"type": "startEvent"}, "Task_Mid": {"type": "serviceTask"}, "End_1": {"type": "endEvent"}},
            {},
            {"Task_Mid": [190, 110, 80, 20]},
            120,
            80,
            thresholds=DEFAULT_MAIN_THRESHOLDS,
        )
        codes = {issue["code"] for issue in metrics["typed_issues"]}
        self.assertIn("edge_label_collision", codes)

    def test_conflict_fixture_03_edge_crossing_pair_issue_is_typed(self):
        rects = {
            "A": (0, 0, 100, 80),
            "B": (200, 0, 100, 80),
            "C": (0, 200, 100, 80),
            "D": (200, 200, 100, 80),
        }
        flows = [
            {"id": "F1", "source": "A", "target": "D"},
            {"id": "F2", "source": "C", "target": "B"},
        ]
        edge_paths = {
            "F1": [(100, 40), (150, 40), (150, 240), (200, 240)],
            "F2": [(100, 240), (150, 240), (150, 40), (200, 40)],
        }
        metrics = LAYOUT.verify_and_report(
            rects,
            {},
            edge_paths,
            flows,
            {"A": 0, "B": 1, "C": 0, "D": 1},
            {"A": 0, "B": 0, "C": 1, "D": 1},
            {node_id: {"type": "serviceTask"} for node_id in rects},
            {},
            {},
            120,
            80,
            thresholds=DEFAULT_MAIN_THRESHOLDS,
        )
        pair_issues = [issue for issue in metrics["typed_issues"] if issue["target_type"] == "pair"]
        self.assertTrue(any(issue["code"] == "edge_edge_intersection" for issue in pair_issues))

    def test_verify_and_report_emits_global_issue_class(self):
        rects = {
            "A": (80, 80, 180, 80),
            "B": (700, 80, 180, 80),
        }
        metrics = LAYOUT.verify_and_report(
            rects,
            {},
            {},
            [],
            {"A": 0, "B": 1},
            {"A": 0, "B": 0},
            {"A": {"type": "serviceTask"}, "B": {"type": "serviceTask"}},
            {},
            {},
            120,
            80,
            thresholds=DEFAULT_MAIN_THRESHOLDS,
        )
        self.assertTrue(any(issue["target_type"] == "global" for issue in metrics["typed_issues"]))

    def test_resolve_conflicts_with_policy_gateway_label_sequence(self):
        rects = {
            "Gateway_1": (100, 100, 50, 50),
            "Task_1": (100, 10, 180, 80),
        }
        label_rects = {
            "Gateway_1": [90, 60, 80, 20],
        }
        rects_after, labels_after, edge_paths_after, metrics, actions = LAYOUT.resolve_conflicts_with_policy(
            "native_preserve_existing",
            rects,
            label_rects,
            {},
            {
                "Gateway_1": {"type": "exclusiveGateway"},
                "Task_1": {"type": "serviceTask"},
            },
            [],
            {"Gateway_1": 0, "Task_1": 0},
            {"Gateway_1": 0, "Task_1": 0},
            {"Gateway_1": (100, 100, 50, 50), "Task_1": (100, 10, 180, 80)},
            {},
            {},
            DEFAULT_MAIN_THRESHOLDS,
        )
        self.assertNotEqual(labels_after["Gateway_1"], [90, 60, 80, 20])
        self.assertIn("phase_4a_local_branch_label_move", actions[0])
        self.assertFalse(LAYOUT.has_unresolved_hard_conflicts(metrics))

    def test_resolve_conflicts_with_policy_raises_on_unresolved_hard_conflicts(self):
        with patch.object(LAYOUT, "place_label_guaranteed", return_value=([90, 60, 80, 20], 1, 80)):
            with patch.object(LAYOUT, "reclaim_node_space", return_value=(
                {"Gateway_1": (100, 100, 50, 50), "Task_1": (80, 10, 180, 80)},
                {"Gateway_1": [90, 60, 80, 20]},
                [],
            )):
                with patch.object(LAYOUT, "has_unresolved_hard_conflicts", return_value=True):
                    with self.assertRaises(LAYOUT.LayoutError):
                        LAYOUT.resolve_conflicts_with_policy(
                            "native_preserve_existing",
                            {"Gateway_1": (100, 100, 50, 50), "Task_1": (80, 10, 180, 80)},
                            {"Gateway_1": [90, 60, 80, 20]},
                            {},
                            {
                                "Gateway_1": {"type": "exclusiveGateway"},
                                "Task_1": {"type": "serviceTask"},
                            },
                            [],
                            {"Gateway_1": 0, "Task_1": 0},
                            {"Gateway_1": 0, "Task_1": 1},
                            {"Gateway_1": (100, 100, 50, 50), "Task_1": (80, 10, 180, 80)},
                            {},
                            {},
                            DEFAULT_MAIN_THRESHOLDS,
                        )

    def test_resolve_conflicts_with_policy_raises_on_real_shape_overlap_conflict(self):
        rects = {
            "Gateway_1": (100, 100, 50, 50),
            "Task_1": (120, 120, 180, 80),
        }
        labels = {"Gateway_1": [90, 60, 80, 20]}
        with patch.object(LAYOUT, "place_label_guaranteed", return_value=([90, 60, 80, 20], 1, 80)):
            with patch.object(LAYOUT, "reclaim_node_space", return_value=(rects, labels, [])):
                with self.assertRaises(LAYOUT.LayoutError):
                    LAYOUT.resolve_conflicts_with_policy(
                        "native_preserve_existing",
                        rects,
                        labels,
                        {},
                        {
                            "Gateway_1": {"type": "exclusiveGateway"},
                            "Task_1": {"type": "serviceTask"},
                        },
                        [],
                        {"Gateway_1": 0, "Task_1": 0},
                        {"Gateway_1": 0, "Task_1": 0},
                        rects,
                        {},
                        {},
                        DEFAULT_MAIN_THRESHOLDS,
                    )

    def test_main_reports_no_hint_defaults_when_feature_is_not_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.bpmn"
            output_path = Path(temp_dir) / "output.bpmn"
            report_path = Path(temp_dir) / "report.md"
            input_path.write_text(self._simple_process_xml(), encoding="utf-8")
            argv = [
                "apply_bpmn_layout_policy.py",
                str(input_path),
                "--output",
                str(output_path),
                "--report",
                str(report_path),
            ]
            with patch.object(sys, "argv", argv):
                LAYOUT.main()
            report = report_path.read_text(encoding="utf-8")
        self.assertIn("- layout_hint_source: none", report)
        self.assertIn("- hint_applied: false", report)

    def test_main_writes_exact_anchor_waypoints_without_grid_snap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.bpmn"
            output_path = Path(temp_dir) / "output.bpmn"
            report_path = Path(temp_dir) / "report.md"
            input_path.write_text(self._simple_process_xml(), encoding="utf-8")
            argv = [
                "apply_bpmn_layout_policy.py",
                str(input_path),
                "--output",
                str(output_path),
                "--report",
                str(report_path),
            ]
            with patch.object(sys, "argv", argv):
                LAYOUT.main()

            root = ET.parse(output_path).getroot()
            ns = {
                "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
                "dc": "http://www.omg.org/spec/DD/20100524/DC",
                "di": "http://www.omg.org/spec/DD/20100524/DI",
            }

            def shape_rect(element_id):
                shape = root.find(f".//bpmndi:BPMNShape[@bpmnElement='{element_id}']", ns)
                bounds = shape.find("dc:Bounds", ns)
                return (
                    int(round(float(bounds.get("x")))),
                    int(round(float(bounds.get("y")))),
                    int(round(float(bounds.get("width")))),
                    int(round(float(bounds.get("height")))),
                )

            edge = root.find(".//bpmndi:BPMNEdge[@bpmnElement='Flow_1']", ns)
            waypoints = edge.findall("di:waypoint", ns)
            first = (int(round(float(waypoints[0].get("x")))), int(round(float(waypoints[0].get("y")))))
            last = (int(round(float(waypoints[-1].get("x")))), int(round(float(waypoints[-1].get("y")))))

            start_rect = shape_rect("Start_1")
            end_rect = shape_rect("End_1")
            start_anchors = {LAYOUT.anchor(start_rect, side) for side in ("left", "right", "top", "bottom")}
            end_anchors = {LAYOUT.anchor(end_rect, side) for side in ("left", "right", "top", "bottom")}

        self.assertIn(first, start_anchors)
        self.assertIn(last, end_anchors)
        self.assertTrue(
            any(value % 10 != 0 for value in first + last),
            "Expected at least one off-grid endpoint coordinate for event anchors",
        )

    def test_main_ignores_hint_payload_when_flag_is_disabled(self):
        hints_payload = {
            "profiles": {
                "native_preserve_existing": {
                    "main": {
                        "label_conflict_padding": 7,
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.bpmn"
            output_path = Path(temp_dir) / "output.bpmn"
            report_path = Path(temp_dir) / "report.md"
            hints_path = Path(temp_dir) / "layout_hints.json"
            input_path.write_text(self._simple_process_xml(), encoding="utf-8")
            hints_path.write_text(json.dumps(hints_payload), encoding="utf-8")
            argv = [
                "apply_bpmn_layout_policy.py",
                str(input_path),
                "--output",
                str(output_path),
                "--report",
                str(report_path),
                "--layout-hints-json",
                str(hints_path),
            ]
            with patch.object(sys, "argv", argv):
                LAYOUT.main()
            report = report_path.read_text(encoding="utf-8")
        self.assertIn("- layout_hint_source: disabled", report)
        self.assertIn("- hint_applied: false", report)

    def test_main_applies_hint_payload_when_feature_flag_is_enabled(self):
        hints_payload = {
            "profiles": {
                "native_preserve_existing": {
                    "main": {
                        "label_conflict_padding": 7,
                    },
                    "nested": {
                        "label_conflict_padding": 7,
                    },
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.bpmn"
            output_path = Path(temp_dir) / "output.bpmn"
            report_path = Path(temp_dir) / "report.md"
            hints_path = Path(temp_dir) / "layout_hints.json"
            input_path.write_text(self._simple_process_xml(), encoding="utf-8")
            hints_path.write_text(json.dumps(hints_payload), encoding="utf-8")
            argv = [
                "apply_bpmn_layout_policy.py",
                str(input_path),
                "--output",
                str(output_path),
                "--report",
                str(report_path),
                "--enable-layout-hints",
                "--layout-hints-json",
                str(hints_path),
            ]
            with patch.object(sys, "argv", argv):
                LAYOUT.main()
            report = report_path.read_text(encoding="utf-8")
        self.assertIn("- layout_hint_source: file_json", report)
        self.assertIn("- hint_applied: true", report)

    def test_main_reports_final_status_from_serialized_geometry_after_nested_expansion(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:subProcess id="Sub_1" name="Embedded">
              <bpmn:startEvent id="Start_Inner" />
              <bpmn:serviceTask id="Task_Inner" name="Inner task" />
              <bpmn:endEvent id="End_Inner" />
              <bpmn:sequenceFlow id="Flow_I1" sourceRef="Start_Inner" targetRef="Task_Inner" />
              <bpmn:sequenceFlow id="Flow_I2" sourceRef="Task_Inner" targetRef="End_Inner" />
            </bpmn:subProcess>
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Sub_1" />
            <bpmn:sequenceFlow id="Flow_2" sourceRef="Sub_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """

        def inject_nested_overlap(subprocess_specs, rects, label_rects, edge_paths, nodes, flows, notes, nested_profile_name, nested_thresholds):
            rects["Nested_A"] = (120, 120, 100, 80)
            rects["Nested_B"] = (140, 140, 100, 80)
            nodes["Nested_A"] = {"id": "Nested_A", "type": "serviceTask", "process_id": "Process_1", "container_id": "Sub_1"}
            nodes["Nested_B"] = {"id": "Nested_B", "type": "serviceTask", "process_id": "Process_1", "container_id": "Sub_1"}
            notes.append(f"injected_nested_overlap:{nested_profile_name}:{nested_thresholds['gap_x']}")

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.bpmn"
            output_path = Path(temp_dir) / "output.bpmn"
            report_path = Path(temp_dir) / "report.md"
            input_path.write_text(xml, encoding="utf-8")
            argv = [
                "apply_bpmn_layout_policy.py",
                str(input_path),
                "--output",
                str(output_path),
                "--report",
                str(report_path),
            ]
            with patch.object(LAYOUT, "apply_nested_subprocess_layouts", side_effect=inject_nested_overlap):
                with patch.object(sys, "argv", argv):
                    LAYOUT.main()
            report = report_path.read_text(encoding="utf-8")
        self.assertRegex(report, r"- shape_shape: [1-9]\d*")
        self.assertIn("Final status: FAIL", report)

    def test_main_passes_original_baseline_into_fallback_drift_accounting(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                          xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                          xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                          xmlns:di="http://www.omg.org/spec/DD/20100524/DI">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
          <bpmndi:BPMNDiagram id="BPMNDiagram_1">
            <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1">
              <bpmndi:BPMNShape id="Shape_Start_1" bpmnElement="Start_1">
                <dc:Bounds x="100" y="100" width="36" height="36" />
              </bpmndi:BPMNShape>
              <bpmndi:BPMNShape id="Shape_End_1" bpmnElement="End_1">
                <dc:Bounds x="300" y="100" width="36" height="36" />
              </bpmndi:BPMNShape>
              <bpmndi:BPMNEdge id="Edge_Flow_1" bpmnElement="Flow_1">
                <di:waypoint x="136" y="118" />
                <di:waypoint x="300" y="118" />
              </bpmndi:BPMNEdge>
            </bpmndi:BPMNPlane>
          </bpmndi:BPMNDiagram>
        </bpmn:definitions>
        """

        call_records = []

        def fake_run_layout_pipeline(mode, nodes, flows, lane, dims, shape_baseline, label_baseline, edge_baseline, thresholds, **kwargs):
            call_records.append(
                {
                    "mode": mode,
                    "shape_baseline": dict(shape_baseline),
                    "report_shape_baseline": dict(kwargs.get("report_shape_baseline") or {}),
                }
            )
            first_rect = next(iter(shape_baseline.values()), (80, 80, 36, 36))
            result_rects = {}
            for index, node_id in enumerate(sorted(nodes.keys())):
                result_rects[node_id] = (first_rect[0] + index * 200, first_rect[1], dims[node_id][0], dims[node_id][1])
            metrics = {
                "shape_shape": 1 if mode != "native_greenfield" else 0,
                "label_shape": 0,
                "label_label": 0,
                "edge_bbox_collisions_detected": 0,
                "invalid_edge_edge_intersections": 0,
                "endpoint_anchor_mismatch": 0,
                "route_quality_violations": 0,
                "shape_budget_violations": 0,
                "label_budget_violations": 0,
                "participant_lane_budget_violations": 0,
                "column_gap_violations": 0,
                "lane_gap_violations": 0,
                "shape_move_total": 0.0,
                "shape_move_max": 0.0,
                "label_move_total": 0.0,
                "label_move_max": 0.0,
                "drift_channels": {},
            }
            return {
                "mode": mode,
                "rects": result_rects,
                "label_rects": {},
                "edge_paths": {flow["id"]: [(result_rects[flow["source"]][0] + result_rects[flow["source"]][2], result_rects[flow["source"]][1] + 20), (result_rects[flow["target"]][0], result_rects[flow["target"]][1] + 20)] for flow in flows},
                "canonical_rects": result_rects,
                "metrics": metrics,
                "actions": [],
                "depth": {node_id: index for index, node_id in enumerate(sorted(nodes.keys()))},
                "slot": {node_id: 0 for node_id in nodes},
                "shape_baseline": dict(kwargs.get("report_shape_baseline") or shape_baseline),
                "label_baseline": dict(kwargs.get("report_label_baseline") or label_baseline),
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.bpmn"
            output_path = Path(temp_dir) / "output.bpmn"
            report_path = Path(temp_dir) / "report.md"
            input_path.write_text(xml, encoding="utf-8")
            argv = [
                "apply_bpmn_layout_policy.py",
                str(input_path),
                "--output",
                str(output_path),
                "--report",
                str(report_path),
            ]
            with patch.object(LAYOUT, "run_layout_pipeline", side_effect=fake_run_layout_pipeline):
                with patch.object(sys, "argv", argv):
                    LAYOUT.main()

        self.assertEqual([record["mode"] for record in call_records], ["native_preserve_existing", "native_repair_escalated", "native_greenfield"])
        self.assertEqual(call_records[2]["shape_baseline"], {})
        self.assertIn("Start_1", call_records[2]["report_shape_baseline"])
        self.assertEqual(call_records[2]["report_shape_baseline"]["Start_1"], (100, 100, 40, 40))

    def test_main_uses_fallback_on_unresolved_conflicts(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """

        def fake_conflicts(mode, rects, label_rects, edge_paths, nodes, flows, lane, depth, canonical_rects, existing_rects, existing_labels, thresholds):
            if mode != "native_greenfield":
                raise LAYOUT.LayoutError("Unresolved hard conflicts after policy sequence")
            metrics = LAYOUT.verify_and_report(
                rects,
                label_rects,
                edge_paths,
                flows,
                depth,
                lane,
                nodes,
                existing_rects,
                existing_labels,
                thresholds["max_shape_shift"],
                thresholds["max_label_shift"],
                gap_x=thresholds["gap_x"],
                gap_y=thresholds["gap_y"],
                participant_lane_budget=thresholds["max_participant_lane_shift"],
                thresholds=thresholds,
            )
            return rects, label_rects, edge_paths, metrics, ["phase_4d_fallback_escalation: clear"]

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.bpmn"
            output_path = Path(temp_dir) / "output.bpmn"
            report_path = Path(temp_dir) / "report.md"
            input_path.write_text(xml, encoding="utf-8")
            argv = [
                "apply_bpmn_layout_policy.py",
                str(input_path),
                "--output",
                str(output_path),
                "--report",
                str(report_path),
            ]
            with patch.object(LAYOUT, "resolve_conflicts_with_policy", side_effect=fake_conflicts):
                with patch.object(sys, "argv", argv):
                    LAYOUT.main()
            report = report_path.read_text(encoding="utf-8")
        self.assertIn("- escalated_repair_error: Unresolved hard conflicts after policy sequence", report)
        self.assertIn("- final_mode: native_greenfield", report)

    def test_main_preserve_existing_di_strict_blocks_greenfield_fallback(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        call_records = []

        def fake_run_layout_pipeline(mode, *args, **kwargs):
            call_records.append(mode)
            raise LAYOUT.LayoutError(f"forced-{mode}")

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.bpmn"
            output_path = Path(temp_dir) / "output.bpmn"
            report_path = Path(temp_dir) / "report.md"
            input_path.write_text(xml, encoding="utf-8")
            argv = [
                "apply_bpmn_layout_policy.py",
                str(input_path),
                "--output",
                str(output_path),
                "--report",
                str(report_path),
                "--preserve-existing-di-strict",
            ]
            with patch.object(LAYOUT, "run_layout_pipeline", side_effect=fake_run_layout_pipeline):
                with patch.object(sys, "argv", argv):
                    with self.assertRaises(LAYOUT.LayoutError):
                        LAYOUT.main()
            report = report_path.read_text(encoding="utf-8")

        self.assertEqual(call_records, ["native_preserve_existing", "native_repair_escalated"])
        self.assertIn("- strict_preserve_chain_status: fail_no_greenfield_fallback", report)
        self.assertNotIn("- final_mode: native_greenfield", report)
        self.assertIn("Final status: FAIL", report)

    def test_real_usable_originals_pass_without_native_greenfield_fallback(self):
        fixture_dir = SCRIPT_PATH.parent / "fixtures" / "original"
        for fixture_name in ("01_original.bpmn", "02_original.bpmn"):
            with self.subTest(fixture=fixture_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    input_path = fixture_dir / fixture_name
                    output_path = Path(temp_dir) / "output.bpmn"
                    report_path = Path(temp_dir) / "report.md"
                    argv = [
                        "apply_bpmn_layout_policy.py",
                        str(input_path),
                        "--output",
                        str(output_path),
                        "--report",
                        str(report_path),
                    ]
                    with patch.object(sys, "argv", argv):
                        LAYOUT.main()
                    report = report_path.read_text(encoding="utf-8")

                self.assertIn("Final status: PASS", report)
                self.assertNotIn("- final_mode: native_greenfield", report)

    def test_main_simple_postprocess_requires_complete_edge_di(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.bpmn"
            output_path = Path(temp_dir) / "output.bpmn"
            report_path = Path(temp_dir) / "report.md"
            input_path.write_text(self._simple_process_xml(), encoding="utf-8")
            argv = [
                "apply_bpmn_layout_policy.py",
                str(input_path),
                "--output",
                str(output_path),
                "--report",
                str(report_path),
                "--simple-postprocess",
            ]
            with patch.object(
                LAYOUT,
                "edge_di_completeness_summary",
                return_value={
                    "sequence_flow_count": 1,
                    "bpmn_edge_count": 0,
                    "edge_without_two_waypoints_count": 0,
                    "missing_edge_ids": ["Flow_1"],
                    "short_waypoint_edge_ids": [],
                    "ok": False,
                },
            ):
                with patch.object(sys, "argv", argv):
                    with self.assertRaises(LAYOUT.LayoutError):
                        LAYOUT.main()
            report = report_path.read_text(encoding="utf-8")

        self.assertIn("## Simple Postprocess DI Completeness", report)
        self.assertIn("- strict_preserve_chain: false", report)
        self.assertIn("- edge_di_complete: false", report)
        self.assertIn("- missing_edge_ids: Flow_1", report)
        self.assertIn("Final status: FAIL", report)

    def test_simple_postprocess_uses_simple_profile_family(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.bpmn"
            output_path = Path(temp_dir) / "output.bpmn"
            report_path = Path(temp_dir) / "report.md"
            report_json_path = Path(temp_dir) / "report.json"
            input_path.write_text(self._simple_process_xml(), encoding="utf-8")
            argv = [
                "apply_bpmn_layout_policy.py",
                str(input_path),
                "--output",
                str(output_path),
                "--report",
                str(report_path),
                "--report-json",
                str(report_json_path),
                "--simple-postprocess",
            ]
            with patch.object(sys, "argv", argv):
                LAYOUT.main()
            report = report_path.read_text(encoding="utf-8")
            report_json = json.loads(report_json_path.read_text(encoding="utf-8"))

        self.assertIn("- layout_profile_family: simple_postprocess", report)
        self.assertIn("- policy_default_profile: simple_postprocess_refine", report)
        self.assertNotIn("preserve_existing_di_error", report)
        self.assertNotIn("escalated_repair_error", report)
        self.assertIn("simple_postprocess_mode", report_json)
        self.assertTrue(report_json["simple_postprocess_mode"])
        self.assertEqual(report_json["layout_profile_family"], "simple_postprocess")

    def test_report_json_written_with_expected_shape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.bpmn"
            output_path = Path(temp_dir) / "output.bpmn"
            report_path = Path(temp_dir) / "report.md"
            report_json_path = Path(temp_dir) / "report.json"
            input_path.write_text(self._simple_process_xml(), encoding="utf-8")
            argv = [
                "apply_bpmn_layout_policy.py",
                str(input_path),
                "--output",
                str(output_path),
                "--report",
                str(report_path),
                "--report-json",
                str(report_json_path),
            ]
            with patch.object(sys, "argv", argv):
                LAYOUT.main()
            payload = json.loads(report_json_path.read_text(encoding="utf-8"))

        expected_keys = {
            "schema_version",
            "final_status",
            "final_mode",
            "layout_profile_family",
            "simple_postprocess_mode",
            "budget_violations_hard",
            "shape_budget_violations",
            "label_budget_violations",
            "participant_lane_budget_violations",
            "typed_issue_count",
            "warning_issue_count",
            "error_issue_count",
            "diagram_width_px",
            "diagram_height_px",
            "aspect_ratio_x100",
            "max_depth_columns",
            "max_edge_span_columns",
            "consecutive_gateway_chain_length",
            "readability_violations",
            "layout_requires_decomposition",
            "advisory_only",
            "hint_applied",
            "layout_hint_source",
        }
        self.assertEqual(set(payload.keys()), expected_keys)
        self.assertIn(payload["final_status"], {"PASS", "FAIL"})

    def test_readability_gate_flags_overwide_diagram(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "wide_input.bpmn"
            output_path = Path(temp_dir) / "output.bpmn"
            report_path = Path(temp_dir) / "report.md"
            report_json_path = Path(temp_dir) / "report.json"
            input_path.write_text(self._wide_chain_process_xml(task_count=35), encoding="utf-8")
            argv = [
                "apply_bpmn_layout_policy.py",
                str(input_path),
                "--output",
                str(output_path),
                "--report",
                str(report_path),
                "--report-json",
                str(report_json_path),
            ]
            with patch.object(sys, "argv", argv):
                LAYOUT.main()
            payload = json.loads(report_json_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["final_status"], "FAIL")
        self.assertTrue(payload["layout_requires_decomposition"])
        self.assertGreater(payload["readability_violations"], 0)
        self.assertGreater(payload["diagram_width_px"], 1800)

    def test_extract_lane_definitions(self):
        xml = """
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:laneSet id="LaneSet_1">
              <bpmn:lane id="Lane_A" name="Front">
                <bpmn:flowNodeRef>Task_A</bpmn:flowNodeRef>
              </bpmn:lane>
            </bpmn:laneSet>
          </bpmn:process>
        </bpmn:definitions>
        """
        root = ET.fromstring(xml)
        process = root.find(LAYOUT.q("bpmn", "process"))
        lanes = LAYOUT.extract_lane_definitions(process)
        self.assertEqual(lanes[0]["id"], "Lane_A")
        self.assertEqual(lanes[0]["node_refs"], ["Task_A"])

    def test_ensure_collaboration_for_lane_processes_creates_pool_participant(self):
        xml = """
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1" name="Main Process">
            <bpmn:laneSet id="LaneSet_1">
              <bpmn:lane id="Lane_A" name="Front">
                <bpmn:flowNodeRef>Task_A</bpmn:flowNodeRef>
              </bpmn:lane>
            </bpmn:laneSet>
          </bpmn:process>
        </bpmn:definitions>
        """
        root = ET.fromstring(xml)
        process = root.find(LAYOUT.q("bpmn", "process"))
        lane_defs_by_process = {process.get("id"): LAYOUT.extract_lane_definitions(process)}
        collaboration, participants, created = LAYOUT.ensure_collaboration_for_lane_processes(
            root,
            [process],
            None,
            [],
            lane_defs_by_process,
        )
        self.assertTrue(created)
        self.assertIsNotNone(collaboration)
        self.assertEqual(len(participants), 1)
        self.assertEqual(participants[0]["processRef"], "Process_1")
        self.assertEqual(
            root.find(".//" + LAYOUT.q("bpmn", "participant")).get("processRef"),
            "Process_1",
        )

    def test_ensure_collaboration_for_lane_processes_skips_when_no_lanes(self):
        xml = """
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1" name="Main Process" />
        </bpmn:definitions>
        """
        root = ET.fromstring(xml)
        process = root.find(LAYOUT.q("bpmn", "process"))
        lane_defs_by_process = {process.get("id"): []}
        collaboration, participants, created = LAYOUT.ensure_collaboration_for_lane_processes(
            root,
            [process],
            None,
            [],
            lane_defs_by_process,
        )
        self.assertFalse(created)
        self.assertIsNone(collaboration)
        self.assertEqual(participants, [])

    def test_collect_direct_container_graph_captures_sequence_flow_name(self):
        xml = """
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:startEvent id="Start_1" />
            <bpmn:endEvent id="End_1" />
            <bpmn:sequenceFlow id="Flow_1" name="Order Management Change" sourceRef="Start_1" targetRef="End_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        root = ET.fromstring(xml)
        process = root.find(LAYOUT.q("bpmn", "process"))
        _, flows, _ = LAYOUT.collect_direct_container_graph(process, "Process_1")
        self.assertEqual(flows[0]["name"], "Order Management Change")

    def test_build_contiguous_lane_rects_has_no_vertical_gaps(self):
        lane_defs = [
            {"id": "Lane_A", "node_refs": ["Task_A"], "name": "A"},
            {"id": "Lane_B", "node_refs": ["Task_B"], "name": "B"},
            {"id": "Lane_C", "node_refs": ["Task_C"], "name": "C"},
        ]
        rects = {
            "Task_A": (200, 120, 180, 80),
            "Task_B": (200, 420, 180, 80),
            "Task_C": (200, 760, 180, 80),
        }
        process_rect = (100, 80, 1200, 1200)
        lane_rects = LAYOUT.build_contiguous_lane_rects(lane_defs, rects, process_rect)
        self.assertEqual(lane_rects["Lane_A"][1] + lane_rects["Lane_A"][3], lane_rects["Lane_B"][1])
        self.assertEqual(lane_rects["Lane_B"][1] + lane_rects["Lane_B"][3], lane_rects["Lane_C"][1])

    def test_build_contiguous_lane_rects_uses_policy_backed_framing(self):
        lane_defs = [
            {"id": "Lane_A", "node_refs": ["Task_A"], "name": "A"},
            {"id": "Lane_B", "node_refs": ["Task_B"], "name": "B"},
        ]
        rects = {
            "Task_A": (200, 160, 180, 80),
            "Task_B": (200, 460, 180, 80),
        }
        process_rect = (100, 80, 900, 700)
        default_rects = LAYOUT.build_contiguous_lane_rects(
            lane_defs,
            rects,
            process_rect,
            thresholds=DEFAULT_MAIN_THRESHOLDS,
        )
        roomy_thresholds = dict(
            DEFAULT_MAIN_THRESHOLDS,
            lane_band_margin=40,
            lane_inset_x=30,
            lane_inset_y=20,
            lane_min_height=140,
            lane_min_height_floor=60,
        )
        roomy_rects = LAYOUT.build_contiguous_lane_rects(
            lane_defs,
            rects,
            process_rect,
            thresholds=roomy_thresholds,
        )
        self.assertEqual(default_rects["Lane_A"][0], 110)
        self.assertEqual(default_rects["Lane_A"][1], 90)
        self.assertEqual(default_rects["Lane_A"][2], 880)
        self.assertEqual(roomy_rects["Lane_A"][0], 130)
        self.assertEqual(roomy_rects["Lane_A"][1], 100)
        self.assertEqual(roomy_rects["Lane_A"][2], 840)

    def test_regenerated_di_element_ids_contains_pool_and_lane_ids(self):
        participants = [{"id": "Participant_Main", "processRef": "Process_1"}]
        lane_defs_by_process = {
            "Process_1": [
                {"id": "Lane_Frontline", "node_refs": ["Task_1"]},
                {"id": "Lane_Sales", "node_refs": ["Task_2"]},
            ]
        }
        ids = LAYOUT.regenerated_di_element_ids(participants, lane_defs_by_process)
        self.assertIn("Participant_Main", ids)
        self.assertIn("Lane_Frontline", ids)
        self.assertIn("Lane_Sales", ids)

    def test_choose_flow_label_rect_prefers_branch_horizontal_segment(self):
        path = [(2730, 165), (2845, 165), (2845, 540), (2960, 540)]
        rect = LAYOUT.choose_flow_label_rect(path, "Special Exception Case")
        self.assertIsNotNone(rect)
        _, ly, _, _ = rect
        self.assertLess(ly, 540)
        self.assertGreater(ly, 480)

    def test_resolve_edge_label_overlaps_nudges_colliding_labels(self):
        labels = {
            "Flow_A": [100, 100, 80, 20],
            "Flow_B": [105, 102, 80, 20],
        }
        resolved = LAYOUT.resolve_edge_label_overlaps(labels)
        a = tuple(resolved["Flow_A"])
        b = tuple(resolved["Flow_B"])
        self.assertFalse(LAYOUT.rect_intersect(a, b, pad=4))

    def test_fanin_shared_target_edges_offsets_approach_lines(self):
        flows = [
            {"id": "F1", "source": "Task_A", "target": "End_1"},
            {"id": "F2", "source": "Task_B", "target": "End_1"},
        ]
        rects = {
            "Task_A": (100, 100, 180, 80),
            "Task_B": (100, 260, 180, 80),
            "End_1": (500, 180, 36, 36),
        }
        edge_paths = {
            "F1": [(280, 140), (400, 140), (400, 198), (500, 198)],
            "F2": [(280, 300), (400, 300), (400, 198), (500, 198)],
        }
        original = {fid: list(path) for fid, path in edge_paths.items()}
        adjusted, actions = LAYOUT.fanin_shared_target_edges(flows, edge_paths, rects)
        self.assertTrue(actions)
        self.assertNotEqual(adjusted["F1"], original["F1"])
        self.assertNotEqual(adjusted["F2"], original["F2"])

    def test_route_free_edge_builds_orthogonal_path(self):
        path = LAYOUT.route_free_edge((0, 0, 100, 80), (200, 0, 100, 80))
        self.assertEqual(path[0], (100, 40))
        self.assertEqual(path[-1], (200, 40))
        self.assertTrue(all(path[i][0] == path[i + 1][0] or path[i][1] == path[i + 1][1] for i in range(len(path) - 1)))

    def test_orthogonalize_path_splits_diagonal_segment(self):
        path = [(680, 390), (680, 380), (550, 380), (870, 1360)]
        orth = LAYOUT.orthogonalize_path(path)
        self.assertGreater(len(orth), len(path))
        self.assertTrue(all(orth[i][0] == orth[i + 1][0] or orth[i][1] == orth[i + 1][1] for i in range(len(orth) - 1)))

    def test_fanout_path_near_source_keeps_short_path_orthogonal(self):
        path = [(480, 390), (480, 90), (670, 90), (590, 120)]
        adjusted = LAYOUT.fanout_path_near_source(path, "top", 40)
        self.assertEqual(adjusted, path)

    def test_place_artifacts_creates_rects_and_association(self):
        artifacts = [{"id": "Note_1", "type": "textAnnotation", "name": "Call back", "process_id": "Process_1"}]
        associations = [{"id": "Assoc_1", "source": "Note_1", "target": "Task_1", "process_id": "Process_1"}]
        rects = {"Task_1": (100, 100, 180, 80)}
        nodes = {"Task_1": {"process_id": "Process_1"}}
        artifact_rects, association_paths = LAYOUT.place_artifacts(artifacts, associations, rects, nodes, {})
        self.assertIn("Note_1", artifact_rects)
        self.assertIn("Assoc_1", association_paths)

    def test_group_artifact_is_extracted_and_positioned(self):
        xml = """
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
          <bpmn:process id="Process_1">
            <bpmn:group id="Group_1" categoryValueRef="Category_1" />
          </bpmn:process>
        </bpmn:definitions>
        """
        root = ET.fromstring(xml)
        process = root.find(LAYOUT.q("bpmn", "process"))
        artifacts, associations = LAYOUT.extract_artifacts(process)
        self.assertEqual(associations, [])
        self.assertEqual(artifacts[0]["type"], "group")
        artifact_rects, _ = LAYOUT.place_artifacts(
            artifacts,
            [],
            {"Task_1": (100, 100, 180, 80)},
            {"Task_1": {"process_id": "Process_1"}},
            {},
        )
        self.assertIn("Group_1", artifact_rects)


if __name__ == "__main__":
    unittest.main()
