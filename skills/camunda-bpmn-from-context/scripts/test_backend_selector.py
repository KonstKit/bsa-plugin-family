#!/usr/bin/env python3
import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


SCRIPT_PATH = Path(__file__).resolve().parent / "backend_selector.py"
CONFIG_PATH = SCRIPT_PATH.parent.parent / "config" / "backend_selector_config.yaml"
SPEC = importlib.util.spec_from_file_location("backend_selector", SCRIPT_PATH)
SELECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTOR)


class BackendSelectorTests(unittest.TestCase):
    def _selector_config(self):
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def _precedence_by_id(self, cfg):
        return {entry["id"]: entry for entry in cfg["selector"]["precedence"]}

    def _load_runtime_config_from_data(self, data):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "backend_selector_config.yaml"
            config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            return SELECTOR._load_selector_runtime_config(config_path)

    def test_valid_modes_are_loaded_from_config(self):
        cfg = self._selector_config()
        expected = {str(mode).strip().lower() for mode in cfg["selector"]["valid_modes"]}
        self.assertEqual(SELECTOR.VALID_MODES, expected)

    def test_hard_exclusion_order_is_loaded_from_config(self):
        cfg = self._selector_config()
        expected = tuple(
            (entry["fact_key"], entry["reason_code"])
            for entry in cfg["selector"]["hard_exclusion_order"]
        )
        self.assertEqual(SELECTOR.HARD_EXCLUSION_ORDER, expected)

    def test_selector_reason_codes_are_loaded_from_config(self):
        cfg = self._selector_config()
        precedence = self._precedence_by_id(cfg)
        self.assertEqual(SELECTOR.LOGIC_ONLY_REASON, precedence[1]["reason_code"])
        self.assertEqual(
            SELECTOR.FULL_RELAYOUT_OVERRIDE_REASON,
            precedence[2]["reason_code"],
        )
        self.assertEqual(
            SELECTOR.PRESERVE_EXISTING_REASON,
            precedence[3]["reason_code"],
        )
        self.assertEqual(
            SELECTOR.REQUESTED_MODE_REASON_TEMPLATE,
            precedence[5]["reason_code"],
        )

    def test_selector_runtime_semantics_are_loaded_from_config(self):
        cfg = self._selector_config()
        precedence = self._precedence_by_id(cfg)
        self.assertEqual(SELECTOR.LOGIC_ONLY_RUNTIME["eligibility_class"], precedence[1]["eligibility_class"])
        self.assertEqual(SELECTOR.LOGIC_ONLY_RUNTIME["forced_native"], precedence[1]["forced_native"])
        self.assertEqual(SELECTOR.LOGIC_ONLY_RUNTIME["forced_skip_layout"], precedence[1]["forced_skip_layout"])
        self.assertEqual(SELECTOR.PRESERVE_EXISTING_RUNTIME["eligibility_class"], precedence[3]["eligibility_class"])
        self.assertEqual(SELECTOR.PRESERVE_EXISTING_RUNTIME["forced_native"], precedence[3]["forced_native"])
        self.assertEqual(SELECTOR.PRESERVE_EXISTING_RUNTIME["forced_skip_layout"], precedence[3]["forced_skip_layout"])
        self.assertEqual(SELECTOR.HARD_EXCLUSION_RUNTIME["eligibility_class"], precedence[4]["eligibility_class"])
        self.assertEqual(SELECTOR.HARD_EXCLUSION_RUNTIME["forced_native"], precedence[4]["forced_native"])
        self.assertEqual(SELECTOR.HARD_EXCLUSION_RUNTIME["forced_skip_layout"], precedence[4]["forced_skip_layout"])
        self.assertEqual(SELECTOR.NO_HARD_EXCLUSION_RUNTIME["eligibility_class"], precedence[5]["eligibility_class"])
        self.assertEqual(SELECTOR.NO_HARD_EXCLUSION_RUNTIME["forced_skip_layout"], precedence[5]["forced_skip_layout"])
        self.assertEqual(
            SELECTOR.NO_HARD_EXCLUSION_RUNTIME["forced_native_rule"],
            {"kind": "requested_mode_equals", "value": "native"},
        )

    def test_logic_only_forces_skip_layout(self):
        result = SELECTOR.classify_eligibility(
            requested_mode="simple",
            logic_only=True,
            preserve_existing_di=True,
            full_relayout=False,
            facts={"participant_count": 3},
        )
        self.assertEqual(result["eligibility_class"], "logic_only")
        self.assertTrue(result["forced_skip_layout"])
        self.assertFalse(result["forced_native"])

    def test_full_relayout_overrides_preserve_existing_di(self):
        result = SELECTOR.classify_eligibility(
            requested_mode="auto",
            preserve_existing_di=True,
            full_relayout=True,
            facts={},
        )
        self.assertEqual(result["eligibility_class"], "simple_eligible")
        self.assertFalse(result["forced_native"])
        self.assertIn("full_relayout_overrides_preserve_existing_di", result["eligibility_reasons"])

    def test_preserve_existing_di_forces_native_when_not_full_relayout(self):
        result = SELECTOR.classify_eligibility(
            requested_mode="simple",
            preserve_existing_di=True,
            full_relayout=False,
            facts={},
        )
        self.assertEqual(result["eligibility_class"], "native_preserve")
        self.assertTrue(result["forced_native"])
        self.assertEqual(result["primary_reason"], "preserve_existing_di_forces_native")

    def test_effective_inferred_preserve_flag_forces_native_in_auto_mode(self):
        result = SELECTOR.classify_eligibility(
            requested_mode="auto",
            preserve_existing_di=True,
            full_relayout=False,
            facts={"has_existing_di": True},
        )
        self.assertEqual(result["eligibility_class"], "native_preserve")
        self.assertTrue(result["forced_native"])
        self.assertEqual(result["primary_reason"], "preserve_existing_di_forces_native")

    def test_hard_exclusions_force_native(self):
        result = SELECTOR.classify_eligibility(
            requested_mode="simple",
            facts={
                "participant_count": 2,
                "constructs": ["messageFlow", "boundaryEvent", "group"],
            },
        )
        self.assertEqual(result["eligibility_class"], "simple_ineligible")
        self.assertTrue(result["forced_native"])
        self.assertEqual(
            result["hard_exclusions"],
            [
                "multi_participant_collaboration",
                "message_flow_present",
                "group_present",
                "boundary_event_present",
            ],
        )

    def test_complex_gateway_is_hard_exclusion(self):
        result = SELECTOR.classify_eligibility(
            requested_mode="auto",
            facts={"constructs": ["complexGateway"]},
        )
        self.assertEqual(result["eligibility_class"], "simple_ineligible")
        self.assertEqual(result["hard_exclusions"], ["complex_gateway_present"])

    def test_requested_mode_native_is_deterministic(self):
        result = SELECTOR.classify_eligibility(requested_mode="native", facts={})
        self.assertEqual(result["eligibility_class"], "simple_eligible")
        self.assertTrue(result["forced_native"])
        self.assertEqual(result["eligibility_reasons"], ["requested_mode_native"])

    def test_missing_selector_config_path_raises_runtime_error(self):
        missing_path = CONFIG_PATH.parent / "missing_backend_selector_config.yaml"
        with self.assertRaisesRegex(RuntimeError, "config is missing"):
            SELECTOR._load_selector_runtime_config(missing_path)

    def test_malformed_yaml_raises_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "backend_selector_config.yaml"
            config_path.write_text("selector: [", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "invalid YAML"):
                SELECTOR._load_selector_runtime_config(config_path)

    def test_missing_required_precedence_key_raises_runtime_error(self):
        cfg = copy.deepcopy(self._selector_config())
        precedence = self._precedence_by_id(cfg)
        precedence[3].pop("forced_skip_layout")
        cfg["selector"]["precedence"] = list(precedence.values())
        with self.assertRaisesRegex(RuntimeError, "selector\\.precedence\\[id=3\\]\\.forced_skip_layout"):
            self._load_runtime_config_from_data(cfg)

    def test_invalid_requested_mode_template_raises_runtime_error(self):
        cfg = copy.deepcopy(self._selector_config())
        precedence = self._precedence_by_id(cfg)
        precedence[5]["reason_code"] = "requested_mode_native"
        cfg["selector"]["precedence"] = list(precedence.values())
        with self.assertRaisesRegex(RuntimeError, "must include '\\{mode\\}'"):
            self._load_runtime_config_from_data(cfg)

    def test_invalid_forced_native_expression_raises_runtime_error(self):
        cfg = copy.deepcopy(self._selector_config())
        precedence = self._precedence_by_id(cfg)
        precedence[5]["forced_native"] = "requested_mode=native"
        cfg["selector"]["precedence"] = list(precedence.values())
        with self.assertRaisesRegex(RuntimeError, "unsupported expression"):
            self._load_runtime_config_from_data(cfg)

    def test_unknown_hard_exclusion_fact_key_raises_runtime_error_on_load(self):
        cfg = copy.deepcopy(self._selector_config())
        cfg["selector"]["hard_exclusion_order"][1]["fact_key"] = "mesage_flow"
        with self.assertRaisesRegex(
            RuntimeError,
            r"selector\.hard_exclusion_order\[1\]\.fact_key.*mesage_flow",
        ):
            self._load_runtime_config_from_data(cfg)


if __name__ == "__main__":
    unittest.main()
