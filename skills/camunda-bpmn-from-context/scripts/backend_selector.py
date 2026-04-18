#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
SELECTOR_CONFIG_PATH = PACKAGE_ROOT / "config" / "backend_selector_config.yaml"


def _require_mapping(value, context):
    if not isinstance(value, dict):
        raise RuntimeError(f"backend selector config expected mapping for {context}")
    return value


def _require_string(value, context):
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"backend selector config expected non-empty string for {context}")
    return value.strip()


def _require_bool(value, context):
    if isinstance(value, bool):
        return value
    raise RuntimeError(f"backend selector config expected boolean for {context}")


def _parse_forced_native_rule(value, context):
    if isinstance(value, bool):
        return {"kind": "constant", "value": value}
    expression = _require_string(value, context)
    if not expression.startswith("requested_mode=="):
        raise RuntimeError(f"backend selector config unsupported expression for {context}: {expression!r}")
    mode = expression.split("==", 1)[1].strip().lower()
    if not mode:
        raise RuntimeError(f"backend selector config invalid requested_mode expression for {context}: {expression!r}")
    return {"kind": "requested_mode_equals", "value": mode}


def _evaluate_forced_native_rule(rule_spec, requested_mode):
    kind = rule_spec["kind"]
    if kind == "constant":
        return bool(rule_spec["value"])
    if kind == "requested_mode_equals":
        return str(requested_mode).strip().lower() == rule_spec["value"]
    raise RuntimeError(f"backend selector config unknown forced_native rule kind: {kind!r}")


def _load_selector_runtime_config(path=SELECTOR_CONFIG_PATH):
    if not Path(path).exists():
        raise RuntimeError(f"backend selector config is missing: {path}")
    try:
        with Path(path).open("r", encoding="utf-8") as fh:
            raw_config = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise RuntimeError(f"backend selector config invalid YAML: {path}") from exc

    root = _require_mapping(raw_config, "root")
    selector = _require_mapping(root.get("selector"), "selector")
    valid_modes_raw = selector.get("valid_modes")
    if not isinstance(valid_modes_raw, list) or not valid_modes_raw:
        raise RuntimeError("backend selector config selector.valid_modes must be a non-empty list")
    valid_modes = {_require_string(mode, f"selector.valid_modes[{idx}]").lower() for idx, mode in enumerate(valid_modes_raw)}

    hard_exclusion_raw = selector.get("hard_exclusion_order")
    if not isinstance(hard_exclusion_raw, list) or not hard_exclusion_raw:
        raise RuntimeError("backend selector config selector.hard_exclusion_order must be a non-empty list")
    hard_exclusion_order = []
    seen_fact_keys = set()
    normalized_fact_keys = set(_normalize_facts({}).keys())
    for index, item in enumerate(hard_exclusion_raw):
        row = _require_mapping(item, f"selector.hard_exclusion_order[{index}]")
        fact_key = _require_string(row.get("fact_key"), f"selector.hard_exclusion_order[{index}].fact_key")
        reason_code = _require_string(row.get("reason_code"), f"selector.hard_exclusion_order[{index}].reason_code")
        if fact_key not in normalized_fact_keys:
            raise RuntimeError(
                "backend selector config selector.hard_exclusion_order["
                f"{index}].fact_key unknown fact_key {fact_key!r}; "
                f"expected one of {sorted(normalized_fact_keys)}"
            )
        if fact_key in seen_fact_keys:
            raise RuntimeError(f"backend selector config duplicate fact_key in hard_exclusion_order: {fact_key}")
        seen_fact_keys.add(fact_key)
        hard_exclusion_order.append((fact_key, reason_code))

    precedence_raw = selector.get("precedence")
    if not isinstance(precedence_raw, list) or not precedence_raw:
        raise RuntimeError("backend selector config selector.precedence must be a non-empty list")
    precedence_by_id = {}
    for index, item in enumerate(precedence_raw):
        row = _require_mapping(item, f"selector.precedence[{index}]")
        precedence_id = row.get("id")
        if isinstance(precedence_id, bool) or not isinstance(precedence_id, int):
            raise RuntimeError(f"backend selector config selector.precedence[{index}].id must be an integer")
        if precedence_id in precedence_by_id:
            raise RuntimeError(f"backend selector config duplicate precedence id: {precedence_id}")
        precedence_by_id[precedence_id] = row

    def _rule_by_id(rule_id):
        rule = precedence_by_id.get(rule_id)
        if rule is None:
            raise RuntimeError(f"backend selector config missing precedence rule id={rule_id}")
        return rule

    logic_only_rule = _rule_by_id(1)
    full_relayout_override_rule = _rule_by_id(2)
    preserve_existing_rule = _rule_by_id(3)
    hard_exclusion_rule = _rule_by_id(4)
    no_hard_exclusion_rule = _rule_by_id(5)

    logic_only_reason = _require_string(logic_only_rule.get("reason_code"), "selector.precedence[id=1].reason_code")
    full_relayout_override_reason = _require_string(
        full_relayout_override_rule.get("reason_code"),
        "selector.precedence[id=2].reason_code",
    )
    preserve_existing_reason = _require_string(
        preserve_existing_rule.get("reason_code"),
        "selector.precedence[id=3].reason_code",
    )
    requested_mode_reason_template = _require_string(
        no_hard_exclusion_rule.get("reason_code"),
        "selector.precedence[id=5].reason_code",
    )
    if "{mode}" not in requested_mode_reason_template:
        raise RuntimeError("backend selector config selector.precedence[id=5].reason_code must include '{mode}'")

    logic_only_runtime = {
        "eligibility_class": _require_string(
            logic_only_rule.get("eligibility_class"),
            "selector.precedence[id=1].eligibility_class",
        ),
        "forced_native": _require_bool(
            logic_only_rule.get("forced_native"),
            "selector.precedence[id=1].forced_native",
        ),
        "forced_skip_layout": _require_bool(
            logic_only_rule.get("forced_skip_layout"),
            "selector.precedence[id=1].forced_skip_layout",
        ),
    }
    preserve_existing_runtime = {
        "eligibility_class": _require_string(
            preserve_existing_rule.get("eligibility_class"),
            "selector.precedence[id=3].eligibility_class",
        ),
        "forced_native": _require_bool(
            preserve_existing_rule.get("forced_native"),
            "selector.precedence[id=3].forced_native",
        ),
        "forced_skip_layout": _require_bool(
            preserve_existing_rule.get("forced_skip_layout"),
            "selector.precedence[id=3].forced_skip_layout",
        ),
    }
    hard_exclusion_runtime = {
        "eligibility_class": _require_string(
            hard_exclusion_rule.get("eligibility_class"),
            "selector.precedence[id=4].eligibility_class",
        ),
        "forced_native": _require_bool(
            hard_exclusion_rule.get("forced_native"),
            "selector.precedence[id=4].forced_native",
        ),
        "forced_skip_layout": _require_bool(
            hard_exclusion_rule.get("forced_skip_layout"),
            "selector.precedence[id=4].forced_skip_layout",
        ),
    }
    no_hard_exclusion_runtime = {
        "eligibility_class": _require_string(
            no_hard_exclusion_rule.get("eligibility_class"),
            "selector.precedence[id=5].eligibility_class",
        ),
        "forced_native_rule": _parse_forced_native_rule(
            no_hard_exclusion_rule.get("forced_native"),
            "selector.precedence[id=5].forced_native",
        ),
        "forced_skip_layout": _require_bool(
            no_hard_exclusion_rule.get("forced_skip_layout"),
            "selector.precedence[id=5].forced_skip_layout",
        ),
    }

    return {
        "valid_modes": valid_modes,
        "hard_exclusion_order": tuple(hard_exclusion_order),
        "logic_only_reason": logic_only_reason,
        "full_relayout_override_reason": full_relayout_override_reason,
        "preserve_existing_reason": preserve_existing_reason,
        "requested_mode_reason_template": requested_mode_reason_template,
        "logic_only_runtime": logic_only_runtime,
        "preserve_existing_runtime": preserve_existing_runtime,
        "hard_exclusion_runtime": hard_exclusion_runtime,
        "no_hard_exclusion_runtime": no_hard_exclusion_runtime,
    }


def _counted_flag(facts, name):
    value = facts.get(name, 0)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value > 0
    return bool(value)


def _normalize_facts(facts):
    facts = dict(facts or {})
    constructs = set(str(item).strip() for item in facts.get("constructs", []) if str(item).strip())
    participant_count = facts.get("participant_count", 0)
    if isinstance(participant_count, bool):
        participant_count = int(participant_count)
    elif not isinstance(participant_count, int):
        participant_count = 0
    return {
        "multi_participant_collaboration": participant_count > 1 or bool(facts.get("has_multiple_participants")),
        "message_flow": "messageFlow" in constructs or _counted_flag(facts, "message_flow_count") or bool(facts.get("has_message_flow")),
        "text_annotation": "textAnnotation" in constructs or _counted_flag(facts, "text_annotation_count") or bool(facts.get("has_text_annotation")),
        "association": "association" in constructs or _counted_flag(facts, "association_count") or bool(facts.get("has_association")),
        "complex_gateway": "complexGateway" in constructs or _counted_flag(facts, "complex_gateway_count") or bool(facts.get("has_complex_gateway")),
        "group": "group" in constructs or _counted_flag(facts, "group_count") or bool(facts.get("has_group")),
        "boundary_event": "boundaryEvent" in constructs or _counted_flag(facts, "boundary_event_count") or bool(facts.get("has_boundary_event")),
        "event_subprocess": "eventSubProcess" in constructs or _counted_flag(facts, "event_subprocess_count") or bool(facts.get("has_event_subprocess")),
        "expanded_subprocess": "expandedSubProcess" in constructs or _counted_flag(facts, "expanded_subprocess_count") or bool(facts.get("has_expanded_subprocess")),
    }


SELECTOR_RUNTIME_CONFIG = _load_selector_runtime_config()
VALID_MODES = SELECTOR_RUNTIME_CONFIG["valid_modes"]
HARD_EXCLUSION_ORDER = SELECTOR_RUNTIME_CONFIG["hard_exclusion_order"]
LOGIC_ONLY_REASON = SELECTOR_RUNTIME_CONFIG["logic_only_reason"]
FULL_RELAYOUT_OVERRIDE_REASON = SELECTOR_RUNTIME_CONFIG["full_relayout_override_reason"]
PRESERVE_EXISTING_REASON = SELECTOR_RUNTIME_CONFIG["preserve_existing_reason"]
REQUESTED_MODE_REASON_TEMPLATE = SELECTOR_RUNTIME_CONFIG["requested_mode_reason_template"]
LOGIC_ONLY_RUNTIME = SELECTOR_RUNTIME_CONFIG["logic_only_runtime"]
PRESERVE_EXISTING_RUNTIME = SELECTOR_RUNTIME_CONFIG["preserve_existing_runtime"]
HARD_EXCLUSION_RUNTIME = SELECTOR_RUNTIME_CONFIG["hard_exclusion_runtime"]
NO_HARD_EXCLUSION_RUNTIME = SELECTOR_RUNTIME_CONFIG["no_hard_exclusion_runtime"]


def classify_eligibility(
    requested_mode="auto",
    logic_only=False,
    preserve_existing_di=False,
    full_relayout=False,
    facts=None,
):
    requested_mode = str(requested_mode or "auto").strip().lower()
    if requested_mode not in VALID_MODES:
        raise ValueError(f"requested_mode must be one of {sorted(VALID_MODES)}, got {requested_mode!r}")

    reasons = []
    normalized_facts = _normalize_facts(facts)

    if logic_only:
        reasons.append(LOGIC_ONLY_REASON)
        return {
            "requested_mode": requested_mode,
            "logic_only": True,
            "preserve_existing_di": bool(preserve_existing_di),
            "full_relayout": bool(full_relayout),
            "eligibility_class": LOGIC_ONLY_RUNTIME["eligibility_class"],
            "eligibility_reasons": reasons,
            "forced_native": LOGIC_ONLY_RUNTIME["forced_native"],
            "forced_skip_layout": LOGIC_ONLY_RUNTIME["forced_skip_layout"],
            "hard_exclusions": [],
            "normalized_facts": normalized_facts,
            "primary_reason": reasons[0],
        }

    if full_relayout and preserve_existing_di:
        reasons.append(FULL_RELAYOUT_OVERRIDE_REASON)

    if preserve_existing_di and not full_relayout:
        reasons.append(PRESERVE_EXISTING_REASON)
        return {
            "requested_mode": requested_mode,
            "logic_only": False,
            "preserve_existing_di": True,
            "full_relayout": False,
            "eligibility_class": PRESERVE_EXISTING_RUNTIME["eligibility_class"],
            "eligibility_reasons": reasons,
            "forced_native": PRESERVE_EXISTING_RUNTIME["forced_native"],
            "forced_skip_layout": PRESERVE_EXISTING_RUNTIME["forced_skip_layout"],
            "hard_exclusions": [],
            "normalized_facts": normalized_facts,
            "primary_reason": reasons[0],
        }

    hard_exclusions = [
        reason_code
        for fact_key, reason_code in HARD_EXCLUSION_ORDER
        if normalized_facts[fact_key]
    ]
    if hard_exclusions:
        reasons.extend(hard_exclusions)
        return {
            "requested_mode": requested_mode,
            "logic_only": False,
            "preserve_existing_di": bool(preserve_existing_di),
            "full_relayout": bool(full_relayout),
            "eligibility_class": HARD_EXCLUSION_RUNTIME["eligibility_class"],
            "eligibility_reasons": reasons,
            "forced_native": HARD_EXCLUSION_RUNTIME["forced_native"],
            "forced_skip_layout": HARD_EXCLUSION_RUNTIME["forced_skip_layout"],
            "hard_exclusions": hard_exclusions,
            "normalized_facts": normalized_facts,
            "primary_reason": hard_exclusions[0],
        }

    reasons.append(REQUESTED_MODE_REASON_TEMPLATE.format(mode=requested_mode))
    forced_native = _evaluate_forced_native_rule(
        NO_HARD_EXCLUSION_RUNTIME["forced_native_rule"],
        requested_mode=requested_mode,
    )
    return {
        "requested_mode": requested_mode,
        "logic_only": False,
        "preserve_existing_di": bool(preserve_existing_di),
        "full_relayout": bool(full_relayout),
        "eligibility_class": NO_HARD_EXCLUSION_RUNTIME["eligibility_class"],
        "eligibility_reasons": reasons,
        "forced_native": forced_native,
        "forced_skip_layout": NO_HARD_EXCLUSION_RUNTIME["forced_skip_layout"],
        "hard_exclusions": [],
        "normalized_facts": normalized_facts,
        "primary_reason": reasons[0],
    }


def _load_facts(raw_value):
    if not raw_value:
        return {}
    candidate = Path(raw_value)
    if candidate.exists():
        with candidate.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        data = json.loads(raw_value)
    if not isinstance(data, dict):
        raise ValueError("facts JSON must be an object")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description="Classify BPMN backend eligibility.")
    parser.add_argument("--requested-mode", default="auto", choices=sorted(VALID_MODES))
    parser.add_argument("--logic-only", action="store_true")
    parser.add_argument("--preserve-existing-di", action="store_true")
    parser.add_argument("--full-relayout", action="store_true")
    parser.add_argument("--facts-json", help="Inline JSON object or path to a JSON file")
    args = parser.parse_args(argv)

    result = classify_eligibility(
        requested_mode=args.requested_mode,
        logic_only=args.logic_only,
        preserve_existing_di=args.preserve_existing_di,
        full_relayout=args.full_relayout,
        facts=_load_facts(args.facts_json),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
