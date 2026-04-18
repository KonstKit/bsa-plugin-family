#!/usr/bin/env python3
import argparse
from collections import Counter
import importlib.util
import json
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


FAILURE_PROJECTION_GENERATION = "projection_generation_failed"
FAILURE_HELPER_LAUNCH = "helper_launch_failed"
FAILURE_HELPER_RUNTIME = "helper_runtime_failed"
FAILURE_HELPER_INVALID_OUTPUT = "helper_invalid_output"
FAILURE_PROJECTION_REHYDRATION = "projection_rehydration_failed"
FAILURE_NAMESPACE_LOSS = "namespace_loss_detected"
FAILURE_EXTENSION_LOSS = "extension_loss_detected"
FAILURE_ID_MISMATCH = "id_mismatch_detected"

PROJECTION_CONTRACT_VERSION = "1.0"
HELPER_DIAGNOSTICS_VERSION = "1.0"
SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
PROJECTION_SIDECAR_SCHEMA = "projection_sidecar.schema.json"
HELPER_DIAGNOSTICS_SCHEMA = "helper_diagnostics.schema.json"

BPMN_MODEL_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
CAMUNDA_NS = "http://camunda.org/schema/1.0/bpmn"
ZEEBE_NS = "http://camunda.org/schema/zeebe/1.0"
RUNTIME_NAMESPACE_PREFIXES = {
    CAMUNDA_NS: "camunda",
    ZEEBE_NS: "zeebe",
}
QUALIFIED_NAME_PREFIXES = {
    BPMN_MODEL_NS: "bpmn",
    CAMUNDA_NS: "camunda",
    ZEEBE_NS: "zeebe",
    "http://www.omg.org/spec/BPMN/20100524/DI": "bpmndi",
    "http://www.omg.org/spec/DD/20100524/DC": "dc",
    "http://www.omg.org/spec/DD/20100524/DI": "di",
}
SEMANTIC_BPMN_TAGS = {
    "process",
    "subProcess",
    "transaction",
    "adHocSubProcess",
    "task",
    "userTask",
    "serviceTask",
    "sendTask",
    "receiveTask",
    "manualTask",
    "businessRuleTask",
    "scriptTask",
    "callActivity",
    "exclusiveGateway",
    "parallelGateway",
    "inclusiveGateway",
    "complexGateway",
    "eventBasedGateway",
    "startEvent",
    "endEvent",
    "intermediateThrowEvent",
    "intermediateCatchEvent",
    "boundaryEvent",
    "sequenceFlow",
}

_VALIDATOR_MODULE = None


class BridgeContractError(RuntimeError):
    def __init__(self, failure_code, message, violations=None):
        super().__init__(message)
        self.failure_code = failure_code
        self.violations = list(violations or [message])


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _load_json(path):
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_validator_module():
    global _VALIDATOR_MODULE
    if _VALIDATOR_MODULE is None:
        script_path = Path(__file__).resolve().parent / "validate_run_manifest.py"
        spec = importlib.util.spec_from_file_location("simple_mode_bridge_validate_run_manifest", script_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"unable to load validator helpers from {script_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _VALIDATOR_MODULE = module
    return _VALIDATOR_MODULE


def _load_schema(schema_name):
    validator = _load_validator_module()
    return validator.load_json(SCHEMA_DIR / schema_name)


def _validate_helper_diagnostics_contract(payload):
    errors = []
    status = payload.get("status")
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    sequence_flow_count = output.get("sequence_flow_count")
    bpmn_shape_count = output.get("bpmn_shape_count")
    bpmn_edge_count = output.get("bpmn_edge_count")
    edge_without_two_waypoints_count = output.get("edge_without_two_waypoints_count")
    edge_di_complete = output.get("edge_di_complete")
    di_quality = output.get("di_quality")
    derived_di_quality = "no_di"
    if (
        isinstance(sequence_flow_count, int)
        and isinstance(bpmn_shape_count, int)
        and isinstance(bpmn_edge_count, int)
        and isinstance(edge_without_two_waypoints_count, int)
    ):
        if bpmn_shape_count > 0 or bpmn_edge_count > 0:
            if sequence_flow_count > 0 and (
                bpmn_edge_count < sequence_flow_count or edge_without_two_waypoints_count > 0
            ):
                derived_di_quality = "partial_di"
            elif sequence_flow_count == 0 or edge_di_complete:
                derived_di_quality = "usable_di"
            else:
                derived_di_quality = "partial_di"
    if status == "PASS":
        if payload.get("failure_code"):
            errors.append("$.failure_code: PASS diagnostics must not declare failure_code")
        if not output.get("bpmn_written"):
            errors.append("$.output.bpmn_written: PASS diagnostics require bpmn_written=true")
    if status == "FAIL" and not payload.get("errors"):
        errors.append("$.errors: FAIL diagnostics require at least one error entry")
    for key, value in (
        ("sequence_flow_count", sequence_flow_count),
        ("bpmn_shape_count", bpmn_shape_count),
        ("bpmn_edge_count", bpmn_edge_count),
        ("edge_without_two_waypoints_count", edge_without_two_waypoints_count),
    ):
        if not isinstance(value, int) or value < 0:
            errors.append(f"$.output.{key}: must be a non-negative integer")
    if not isinstance(edge_di_complete, bool):
        errors.append("$.output.edge_di_complete: must be boolean")
    if di_quality not in {"no_di", "partial_di", "usable_di"}:
        errors.append("$.output.di_quality: must be one of 'no_di', 'partial_di', 'usable_di'")
    elif derived_di_quality and di_quality != derived_di_quality:
        errors.append(
            f"$.output.di_quality: expected {derived_di_quality!r} from counts, got {di_quality!r}"
        )
    elif (
        edge_di_complete
        and isinstance(sequence_flow_count, int)
        and isinstance(bpmn_edge_count, int)
        and isinstance(edge_without_two_waypoints_count, int)
        and (bpmn_edge_count < sequence_flow_count or edge_without_two_waypoints_count > 0)
    ):
        errors.append(
            "$.output.edge_di_complete: true is invalid when BPMNEdge count is below sequenceFlow count or waypoint coverage is incomplete"
        )
    return errors


def _validate_json_payload(payload, schema_name):
    validator = _load_validator_module()
    errors = validator.validate_instance(payload, _load_schema(schema_name))
    if schema_name == HELPER_DIAGNOSTICS_SCHEMA:
        errors.extend(_validate_helper_diagnostics_contract(payload))
    return errors


def _namespace_uri(name):
    if isinstance(name, str) and name.startswith("{") and "}" in name:
        return name[1:].split("}", 1)[0]
    return ""


def _local_name(name):
    if isinstance(name, str) and name.startswith("{") and "}" in name:
        return name.split("}", 1)[1]
    return name


def _qualified_name(name):
    uri = _namespace_uri(name)
    local = _local_name(name)
    prefix = QUALIFIED_NAME_PREFIXES.get(uri)
    return f"{prefix}:{local}" if prefix else local


def _string_list(value):
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _merge_unique_strings(*values):
    merged = []
    seen = set()
    for value in values:
        for item in _string_list(value):
            if item in seen:
                continue
            seen.add(item)
            merged.append(item)
    return merged


def _non_negative_int(value, fallback=0):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and value >= 0:
        return value
    return fallback


def _normalize_runtime_target(base_runtime_target, runtime_target):
    base_runtime_target = base_runtime_target if isinstance(base_runtime_target, dict) else {}
    return {
        "namespace_uris_detected": sorted(
            set(_string_list(base_runtime_target.get("namespace_uris_detected")))
        ),
        "requires_namespace_preservation": bool(
            base_runtime_target.get("requires_namespace_preservation")
        ),
        "requires_extension_preservation": bool(
            base_runtime_target.get("requires_extension_preservation")
        ),
    }


def _build_diagnostics_payload(
    status,
    runtime_target,
    *,
    command=None,
    timeout_seconds=None,
    returncode=None,
    stdout=None,
    stderr=None,
    bpmn_written=False,
    sequence_flow_count=None,
    bpmn_shape_count=None,
    bpmn_edge_count=None,
    edge_without_two_waypoints_count=None,
    edge_di_complete=None,
    base=None,
    failure_code=None,
    invariant_violations=None,
):
    base = base if isinstance(base, dict) else {}
    helper_base = base.get("helper") if isinstance(base.get("helper"), dict) else {}
    output_base = base.get("output") if isinstance(base.get("output"), dict) else {}

    helper = {
        "launched": bool(helper_base.get("launched", command is not None)),
    }
    helper_command = helper_base.get("command")
    if isinstance(command, list):
        helper["command"] = list(command)
    elif isinstance(helper_command, list) and all(isinstance(item, str) and item for item in helper_command):
        helper["command"] = helper_command
    if isinstance(timeout_seconds, int):
        helper["timeout_seconds"] = timeout_seconds
    elif isinstance(helper_base.get("timeout_seconds"), int):
        helper["timeout_seconds"] = helper_base["timeout_seconds"]
    if isinstance(returncode, int):
        helper["returncode"] = returncode
    elif isinstance(helper_base.get("returncode"), int):
        helper["returncode"] = helper_base["returncode"]

    output_sequence_flow_count = _non_negative_int(
        sequence_flow_count if sequence_flow_count is not None else output_base.get("sequence_flow_count"),
        fallback=0,
    )
    output_bpmn_shape_count = _non_negative_int(
        bpmn_shape_count if bpmn_shape_count is not None else output_base.get("bpmn_shape_count"),
        fallback=0,
    )
    output_bpmn_edge_count = _non_negative_int(
        bpmn_edge_count if bpmn_edge_count is not None else output_base.get("bpmn_edge_count"),
        fallback=0,
    )
    output_edge_without_two_waypoints_count = _non_negative_int(
        edge_without_two_waypoints_count
        if edge_without_two_waypoints_count is not None
        else output_base.get("edge_without_two_waypoints_count"),
        fallback=0,
    )
    output_edge_di_complete = (
        bool(edge_di_complete)
        if edge_di_complete is not None
        else bool(output_base.get("edge_di_complete", False))
    )
    if output_sequence_flow_count > 0 and output_bpmn_edge_count < output_sequence_flow_count:
        output_edge_di_complete = False
    if output_edge_without_two_waypoints_count > 0:
        output_edge_di_complete = False
    output_di_quality = output_base.get("di_quality")
    derived_di_quality = "no_di"
    if output_sequence_flow_count <= 0 and output_bpmn_shape_count <= 0 and output_bpmn_edge_count <= 0:
        derived_di_quality = "no_di"
    elif output_edge_di_complete and (
        output_sequence_flow_count == 0 or output_bpmn_edge_count >= output_sequence_flow_count
    ):
        derived_di_quality = "usable_di"
    else:
        derived_di_quality = "partial_di"
    if not isinstance(output_di_quality, str) or output_di_quality.strip() not in {"no_di", "partial_di", "usable_di"}:
        output_di_quality = derived_di_quality
    else:
        output_di_quality = output_di_quality.strip()

    output = {
        "bpmn_written": bool(bpmn_written or output_base.get("bpmn_written")),
        "sequence_flow_count": output_sequence_flow_count,
        "bpmn_shape_count": output_bpmn_shape_count,
        "bpmn_edge_count": output_bpmn_edge_count,
        "edge_without_two_waypoints_count": output_edge_without_two_waypoints_count,
        "edge_di_complete": output_edge_di_complete,
        "di_quality": output_di_quality,
    }

    payload = {
        "version": HELPER_DIAGNOSTICS_VERSION,
        "status": status,
        "errors": _merge_unique_strings(base.get("errors"), [failure_code] if failure_code else []),
        "warnings": _string_list(base.get("warnings")),
        "helper": helper,
        "output": output,
        "runtime_target": _normalize_runtime_target(base.get("runtime_target"), runtime_target),
    }

    stdout_value = stdout if isinstance(stdout, str) else base.get("stdout")
    stderr_value = stderr if isinstance(stderr, str) else base.get("stderr")
    if isinstance(stdout_value, str):
        payload["stdout"] = stdout_value
    if isinstance(stderr_value, str):
        payload["stderr"] = stderr_value
    if failure_code:
        payload["failure_code"] = failure_code
    if invariant_violations:
        payload["invariant_violations"] = list(invariant_violations)
    if base:
        payload["raw_helper_diagnostics"] = base
    return payload


def _load_optional_json(path):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return _load_json(path)
    except (OSError, json.JSONDecodeError):
        return None


def _failure_result(
    code,
    diagnostics_path,
    diagnostics,
    artifacts,
    *,
    runtime_target,
    command=None,
    timeout_seconds=None,
    returncode=None,
    stdout=None,
    stderr=None,
    bpmn_written=False,
    invariant_violations=None,
):
    payload = _build_diagnostics_payload(
        "FAIL",
        runtime_target,
        command=command,
        timeout_seconds=timeout_seconds,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        bpmn_written=bpmn_written,
        base=diagnostics,
        failure_code=code,
        invariant_violations=invariant_violations,
    )
    _write_json(diagnostics_path, payload)
    return {
        "ok": False,
        "failure_code": code,
        "helper_returncode": returncode,
        "layout_ready": False,
        "diagnostics": payload,
        "diagnostics_path": str(diagnostics_path),
        "artifacts": {key: str(value) for key, value in artifacts.items()},
        "final_bpmn_path": None,
    }


def _iter_declared_namespaces(path):
    try:
        for _, item in ET.iterparse(str(path), events=("start-ns",)):
            yield item
    except ET.ParseError as exc:
        raise ValueError(f"invalid XML ({exc})") from exc


def _collect_runtime_signals(root):
    runtime_attributes = Counter()
    runtime_elements = Counter()

    def visit(element, current_owner=None):
        owner = current_owner
        element_id = element.get("id")
        if element_id:
            owner = (_qualified_name(element.tag), element_id)
        owner_tag, owner_id = owner if owner else (_qualified_name(element.tag), element_id or "")

        for attr_name, attr_value in sorted(element.attrib.items()):
            if _namespace_uri(attr_name) in RUNTIME_NAMESPACE_PREFIXES:
                signal = (owner_tag, owner_id, _qualified_name(element.tag), _qualified_name(attr_name), attr_value)
                runtime_attributes[signal] += 1
        if _namespace_uri(element.tag) in RUNTIME_NAMESPACE_PREFIXES:
            attr_signature = tuple(
                sorted((_qualified_name(name), value) for name, value in element.attrib.items())
            )
            signal = (owner_tag, owner_id, _qualified_name(element.tag), attr_signature)
            runtime_elements[signal] += 1

        for child in list(element):
            visit(child, owner)

    visit(root)
    return {
        "attributes": runtime_attributes,
        "elements": runtime_elements,
    }


def _inspect_bpmn_contract(path, failure_code):
    path = Path(path)
    try:
        tree = ET.parse(path)
    except (OSError, FileNotFoundError) as exc:
        raise BridgeContractError(failure_code, f"unable to read BPMN file: {exc}") from exc
    except ET.ParseError as exc:
        raise BridgeContractError(failure_code, f"invalid BPMN XML: {exc}") from exc

    root = tree.getroot()
    namespaces = {}
    try:
        for prefix, uri in _iter_declared_namespaces(path):
            namespaces[prefix or ""] = uri
    except ValueError as exc:
        raise BridgeContractError(failure_code, str(exc)) from exc

    semantic_ids = sorted(
        {
            element.get("id")
            for element in root.iter()
            if _namespace_uri(element.tag) == BPMN_MODEL_NS
            and _local_name(element.tag) in SEMANTIC_BPMN_TAGS
            and element.get("id")
        }
    )
    runtime_signals = _collect_runtime_signals(root)
    runtime_namespaces = sorted(
        {uri for uri in namespaces.values() if uri in RUNTIME_NAMESPACE_PREFIXES}
    )
    return {
        "path": str(path),
        "semantic_ids": semantic_ids,
        "runtime_namespaces": runtime_namespaces,
        "runtime_signals": runtime_signals,
    }


def _format_attribute_signal(signal):
    owner_tag, owner_id, element_name, attr_name, attr_value = signal
    owner = f"{owner_tag}#{owner_id}" if owner_id else owner_tag
    return f"{owner}:{element_name}[{attr_name}={attr_value}]"


def _format_runtime_element_signal(signal):
    owner_tag, owner_id, element_name, attr_signature = signal
    owner = f"{owner_tag}#{owner_id}" if owner_id else owner_tag
    if not attr_signature:
        return f"{owner}:{element_name}"
    attrs = ", ".join(f"{name}={value}" for name, value in attr_signature)
    return f"{owner}:{element_name}[{attrs}]"


def _runtime_target_from_contract(contract):
    return {
        "namespace_uris_detected": list(contract["runtime_namespaces"]),
        "requires_namespace_preservation": bool(contract["runtime_namespaces"]),
        "requires_extension_preservation": bool(
            contract["runtime_signals"]["attributes"] or contract["runtime_signals"]["elements"]
        ),
    }


def _build_projection_sidecar(input_path, input_contract):
    return {
        "version": PROJECTION_CONTRACT_VERSION,
        "source_bpmn": str(input_path),
        "projection_mode": "passthrough_projection",
        "excluded_constructs": [],
        "id_map": {
            "strategy": "identity",
            "semantic_id_count": len(input_contract["semantic_ids"]),
            "semantic_ids": list(input_contract["semantic_ids"]),
            "mapping_complete": True,
        },
        "runtime_target": {
            "helper_contract": "bpmn_in_bpmn_out",
            **_runtime_target_from_contract(input_contract),
        },
    }


def _verify_rehydration_invariants(input_contract, output_contract):
    input_ids = set(input_contract["semantic_ids"])
    output_ids = set(output_contract["semantic_ids"])
    if input_ids != output_ids:
        missing_ids = sorted(input_ids - output_ids)
        extra_ids = sorted(output_ids - input_ids)
        violations = []
        if missing_ids:
            violations.append("missing semantic IDs in output: " + ", ".join(missing_ids))
        if extra_ids:
            violations.append("unexpected semantic IDs in output: " + ", ".join(extra_ids))
        raise BridgeContractError(FAILURE_ID_MISMATCH, "semantic BPMN ID set changed", violations)

    missing_namespaces = sorted(
        set(input_contract["runtime_namespaces"]) - set(output_contract["runtime_namespaces"])
    )
    if missing_namespaces:
        raise BridgeContractError(
            FAILURE_NAMESPACE_LOSS,
            "runtime namespace declarations were lost",
            [f"missing runtime namespace URI: {uri}" for uri in missing_namespaces],
        )

    input_attributes = input_contract["runtime_signals"]["attributes"]
    output_attributes = output_contract["runtime_signals"]["attributes"]
    input_elements = input_contract["runtime_signals"]["elements"]
    output_elements = output_contract["runtime_signals"]["elements"]

    missing_attributes = []
    for signal, count in sorted(input_attributes.items()):
        output_count = output_attributes.get(signal, 0)
        if output_count < count:
            missing_attributes.extend([signal] * (count - output_count))

    missing_elements = []
    for signal, count in sorted(input_elements.items()):
        output_count = output_elements.get(signal, 0)
        if output_count < count:
            missing_elements.extend([signal] * (count - output_count))
    if missing_attributes or missing_elements:
        violations = [
            f"missing runtime attribute: {_format_attribute_signal(signal)}"
            for signal in missing_attributes
        ]
        violations.extend(
            f"missing runtime element: {_format_runtime_element_signal(signal)}"
            for signal in missing_elements
        )
        raise BridgeContractError(
            FAILURE_EXTENSION_LOSS,
            "runtime extension signals were lost",
            violations,
        )


def evaluate_projection_rehydration_contract(input_bpmn, output_bpmn):
    try:
        input_contract = _inspect_bpmn_contract(input_bpmn, FAILURE_PROJECTION_REHYDRATION)
        output_contract = _inspect_bpmn_contract(output_bpmn, FAILURE_PROJECTION_REHYDRATION)
        _verify_rehydration_invariants(input_contract, output_contract)
    except BridgeContractError as exc:
        return {
            "ok": False,
            "failure_code": exc.failure_code,
            "violations": list(exc.violations),
        }
    return {
        "ok": True,
        "failure_code": None,
        "violations": [],
    }


def run_simple_mode_bridge(input_bpmn, work_dir, helper_command, timeout_seconds=30):
    input_path = Path(input_bpmn)
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)

    helper_input = work_path / "helper_input.bpmn"
    helper_output = work_path / "helper_output.bpmn"
    projection_sidecar = work_path / "projection_sidecar.json"
    diagnostics_path = work_path / "helper_diagnostics.json"
    rehydrated_output = work_path / "simple_bridge_output.bpmn"
    artifacts = {
        "helper_input": helper_input,
        "helper_output": helper_output,
        "projection_sidecar": projection_sidecar,
        "helper_diagnostics": diagnostics_path,
        "rehydrated_output": rehydrated_output,
    }

    try:
        input_contract = _inspect_bpmn_contract(input_path, FAILURE_PROJECTION_GENERATION)
        projection_payload = _build_projection_sidecar(input_path, input_contract)
        projection_errors = _validate_json_payload(projection_payload, PROJECTION_SIDECAR_SCHEMA)
        if projection_errors:
            raise BridgeContractError(
                FAILURE_PROJECTION_GENERATION,
                "projection sidecar did not match schema",
                projection_errors,
            )
        shutil.copyfile(input_path, helper_input)
        _write_json(projection_sidecar, projection_payload)
    except BridgeContractError as exc:
        return _failure_result(
            exc.failure_code,
            diagnostics_path,
            {"errors": list(exc.violations)},
            artifacts,
            runtime_target={
                "namespace_uris_detected": [],
                "requires_namespace_preservation": False,
                "requires_extension_preservation": False,
            },
            timeout_seconds=timeout_seconds,
            invariant_violations=exc.violations,
        )
    except OSError as exc:
        return _failure_result(
            FAILURE_PROJECTION_GENERATION,
            diagnostics_path,
            {"errors": [str(exc)]},
            artifacts,
            runtime_target=_runtime_target_from_contract(input_contract),
            timeout_seconds=timeout_seconds,
            invariant_violations=[str(exc)],
        )

    runtime_target = _runtime_target_from_contract(input_contract)

    command = shlex.split(helper_command) if isinstance(helper_command, str) else list(helper_command)
    if not command:
        return _failure_result(
            FAILURE_HELPER_LAUNCH,
            diagnostics_path,
            {"errors": ["helper command is empty"]},
            artifacts,
            runtime_target=runtime_target,
            timeout_seconds=timeout_seconds,
            invariant_violations=["helper command is empty"],
        )

    command = command + [
        "--input",
        str(helper_input),
        "--output",
        str(helper_output),
        "--diagnostics",
        str(diagnostics_path),
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return _failure_result(
            FAILURE_HELPER_LAUNCH,
            diagnostics_path,
            {"errors": [str(exc)]},
            artifacts,
            runtime_target=runtime_target,
            command=command,
            timeout_seconds=timeout_seconds,
            stderr=str(exc),
            invariant_violations=[str(exc)],
        )

    if completed.returncode != 0:
        return _failure_result(
            FAILURE_HELPER_RUNTIME,
            diagnostics_path,
            _load_optional_json(diagnostics_path) or {"errors": ["helper exited with non-zero status"]},
            artifacts,
            runtime_target=runtime_target,
            command=command,
            timeout_seconds=timeout_seconds,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            bpmn_written=helper_output.exists(),
            invariant_violations=[f"helper exited with return code {completed.returncode}"],
        )

    if not diagnostics_path.exists():
        diagnostics = _build_diagnostics_payload(
            "PASS",
            runtime_target,
            command=command,
            timeout_seconds=timeout_seconds,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            bpmn_written=helper_output.exists(),
        )
        _write_json(diagnostics_path, diagnostics)
    else:
        try:
            diagnostics = _load_json(diagnostics_path)
        except (OSError, json.JSONDecodeError) as exc:
            return _failure_result(
                FAILURE_HELPER_INVALID_OUTPUT,
                diagnostics_path,
                {"errors": [str(exc)]},
                artifacts,
                runtime_target=runtime_target,
                command=command,
                timeout_seconds=timeout_seconds,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                bpmn_written=helper_output.exists(),
                invariant_violations=[str(exc)],
            )

    diagnostics_errors = _validate_json_payload(diagnostics, HELPER_DIAGNOSTICS_SCHEMA)
    if diagnostics_errors:
        return _failure_result(
            FAILURE_HELPER_INVALID_OUTPUT,
            diagnostics_path,
            diagnostics,
            artifacts,
            runtime_target=runtime_target,
            command=command,
            timeout_seconds=timeout_seconds,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            bpmn_written=helper_output.exists(),
            invariant_violations=diagnostics_errors,
        )

    if diagnostics.get("status") != "PASS":
        return _failure_result(
            FAILURE_HELPER_RUNTIME,
            diagnostics_path,
            diagnostics,
            artifacts,
            runtime_target=runtime_target,
            command=command,
            timeout_seconds=timeout_seconds,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            bpmn_written=helper_output.exists(),
            invariant_violations=_string_list(diagnostics.get("errors")) or ["helper reported FAIL status"],
        )

    # Keep runtime target deterministic for successful runs: bridge-derived requirements are authoritative.
    diagnostics["runtime_target"] = _normalize_runtime_target(
        runtime_target,
        diagnostics.get("runtime_target"),
    )

    if not helper_output.exists():
        return _failure_result(
            FAILURE_HELPER_INVALID_OUTPUT,
            diagnostics_path,
            diagnostics,
            artifacts,
            runtime_target=runtime_target,
            command=command,
            timeout_seconds=timeout_seconds,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            bpmn_written=False,
            invariant_violations=["helper output BPMN file was not created"],
        )

    try:
        output_contract = _inspect_bpmn_contract(helper_output, FAILURE_HELPER_INVALID_OUTPUT)
        _verify_rehydration_invariants(input_contract, output_contract)
    except BridgeContractError as exc:
        return _failure_result(
            exc.failure_code,
            diagnostics_path,
            diagnostics,
            artifacts,
            runtime_target=runtime_target,
            command=command,
            timeout_seconds=timeout_seconds,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            bpmn_written=helper_output.exists(),
            invariant_violations=exc.violations,
        )

    try:
        shutil.copyfile(helper_output, rehydrated_output)
    except OSError as exc:
        return _failure_result(
            FAILURE_PROJECTION_REHYDRATION,
            diagnostics_path,
            diagnostics,
            artifacts,
            runtime_target=runtime_target,
            command=command,
            timeout_seconds=timeout_seconds,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            bpmn_written=True,
            invariant_violations=[str(exc)],
        )

    _write_json(diagnostics_path, diagnostics)
    helper_layout_ready = bool(diagnostics.get("output", {}).get("edge_di_complete"))
    return {
        "ok": True,
        "failure_code": None,
        "helper_returncode": completed.returncode,
        "layout_ready": helper_layout_ready,
        "helper_edge_di_complete": helper_layout_ready,
        "helper_di_quality": diagnostics.get("output", {}).get("di_quality", "no_di"),
        "diagnostics": diagnostics,
        "diagnostics_path": str(diagnostics_path),
        "artifacts": {key: str(value) for key, value in artifacts.items()},
        "final_bpmn_path": str(rehydrated_output),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the simple-mode helper bridge.")
    parser.add_argument("input")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--helper-command", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args(argv)

    result = run_simple_mode_bridge(
        args.input,
        args.work_dir,
        args.helper_command,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
