#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
import json
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
BPMN_MODEL_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
GENERATOR_VERSION = "1"
LINEAGE_SCHEMA_VERSION = "1"
COLLABORATION_TAGS = ("collaboration", "participant", "process", "laneSet", "lane")


def _load_simple_bridge_module():
    spec = importlib.util.spec_from_file_location("simple_mode_bridge_for_fixture_strip", SCRIPT_DIR / "simple_mode_bridge.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SIMPLE_BRIDGE = _load_simple_bridge_module()


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _namespace_uri(tag_name):
    if isinstance(tag_name, str) and tag_name.startswith("{") and "}" in tag_name:
        return tag_name[1:].split("}", 1)[0]
    return ""


def _local_name(tag_name):
    if isinstance(tag_name, str) and tag_name.startswith("{") and "}" in tag_name:
        return tag_name.split("}", 1)[1]
    return str(tag_name)


def _remove_bpmndi_elements(root):
    removed = 0
    for parent in list(root.iter()):
        for child in list(parent):
            if _namespace_uri(child.tag) == BPMNDI_NS:
                parent.remove(child)
                removed += 1
    return removed


def _contains_bpmndi(path):
    tree = ET.parse(path)
    root = tree.getroot()
    for element in root.iter():
        if _namespace_uri(element.tag) == BPMNDI_NS:
            return True
    return False


def _canonical_tree_xml(root):
    tree = ET.ElementTree(root)
    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass
    return ET.tostring(root, encoding="utf-8", xml_declaration=False)


def _collect_collaboration_semantics(path):
    tree = ET.parse(path)
    root = tree.getroot()
    entities = {}
    for tag in COLLABORATION_TAGS:
        ids = sorted(
            element.get("id")
            for element in root.iter()
            if _namespace_uri(element.tag) == BPMN_MODEL_NS
            and _local_name(element.tag) == tag
            and element.get("id")
        )
        entities[tag] = {
            "count": len(ids),
            "ids": ids,
        }

    lane_flow_refs = {}
    for lane in root.iter():
        if _namespace_uri(lane.tag) != BPMN_MODEL_NS or _local_name(lane.tag) != "lane":
            continue
        lane_id = lane.get("id")
        if not lane_id:
            continue
        refs = sorted(
            (child.text or "").strip()
            for child in list(lane)
            if _namespace_uri(child.tag) == BPMN_MODEL_NS
            and _local_name(child.tag) == "flowNodeRef"
            and (child.text or "").strip()
        )
        lane_flow_refs[lane_id] = refs

    return {
        "entities": entities,
        "lane_flow_refs": lane_flow_refs,
    }


def _resolve_within_root(fixtures_root, relative_path, field_name):
    fixtures_root = Path(fixtures_root).resolve()
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise RuntimeError(f"inventory.{field_name} must be relative to fixtures-root, got absolute path: {candidate}")
    resolved = (fixtures_root / candidate).resolve()
    try:
        resolved.relative_to(fixtures_root)
    except ValueError as exc:
        raise RuntimeError(
            f"inventory.{field_name} escapes fixtures-root via path traversal: {relative_path}"
        ) from exc
    return resolved


def strip_fixture(source_path, output_path, fixture_id=None):
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"source fixture does not exist: {source_path}")

    tree = ET.parse(source_path)
    source_root = tree.getroot()
    stripped_root = deepcopy(source_root)
    removed_bpmndi_elements = _remove_bpmndi_elements(stripped_root)

    try:
        ET.indent(ET.ElementTree(stripped_root), space="  ")
    except AttributeError:
        pass

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(stripped_root).write(output_path, encoding="utf-8", xml_declaration=True)

    if _contains_bpmndi(output_path):
        raise RuntimeError(f"BPMNDI elements still present in stripped fixture: {output_path}")

    source_without_di = deepcopy(source_root)
    _remove_bpmndi_elements(source_without_di)
    remove_bpmndi_only = _canonical_tree_xml(source_without_di) == _canonical_tree_xml(stripped_root)
    if not remove_bpmndi_only:
        raise RuntimeError(
            "stripped fixture changed semantics outside BPMNDI removal: "
            f"{source_path} -> {output_path}"
        )

    invariant_result = SIMPLE_BRIDGE.evaluate_projection_rehydration_contract(source_path, output_path)
    if not invariant_result.get("ok"):
        raise RuntimeError(
            "projection/rehydration invariant check failed for stripped fixture "
            f"{source_path} -> {output_path}: "
            f"{invariant_result.get('failure_code')} {invariant_result.get('violations')}"
        )

    source_collab = _collect_collaboration_semantics(source_path)
    stripped_collab = _collect_collaboration_semantics(output_path)
    collaboration_semantics_preserved = source_collab == stripped_collab
    if not collaboration_semantics_preserved:
        raise RuntimeError(
            "collaboration/process/lane semantics changed during strip: "
            f"{source_path} -> {output_path}"
        )

    return {
        "fixture_id": fixture_id or source_path.stem,
        "source_path": str(source_path),
        "stripped_path": str(output_path),
        "source_sha256": _sha256(source_path),
        "stripped_sha256": _sha256(output_path),
        "removed_bpmndi_elements": removed_bpmndi_elements,
        "invariants_ok": True,
        "invariants": {
            "remove_bpmndi_only": True,
            "runtime_contract_preserved": True,
            "collaboration_semantics_preserved": True,
        },
        "generator_version": GENERATOR_VERSION,
    }


def _load_json(path):
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def generate_from_inventory(inventory_path, fixtures_root, lineage_out):
    inventory = _load_json(inventory_path)
    fixtures_root = Path(fixtures_root).resolve()
    entries = []
    for fixture in sorted(inventory.get("fixtures", []), key=lambda item: item.get("fixture_id", "")):
        strip_to = fixture.get("strip_to")
        source_rel = fixture.get("path")
        fixture_id = fixture.get("fixture_id")
        if not source_rel or not strip_to or not fixture_id:
            continue
        source_path = _resolve_within_root(fixtures_root, source_rel, "path")
        output_path = _resolve_within_root(fixtures_root, strip_to, "strip_to")
        entry = strip_fixture(source_path, output_path, fixture_id=fixture_id)
        entry["source_fixture_id"] = fixture_id
        entry["stripped_fixture_id"] = Path(strip_to).stem
        entry["source_path"] = str(Path(source_rel))
        entry["stripped_path"] = str(Path(strip_to))
        entries.append(entry)

    lineage_payload = {
        "schema_version": LINEAGE_SCHEMA_VERSION,
        "generator": "scripts/make_stripped_fixture.py",
        "entries": entries,
    }
    _write_json(lineage_out, lineage_payload)
    return lineage_payload


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Generate stripped fixtures (remove BPMNDI only) with lineage metadata.")
    parser.add_argument("--source", help="Single-source BPMN fixture path")
    parser.add_argument("--output", help="Single-output stripped BPMN fixture path")
    parser.add_argument("--fixture-id", help="Fixture identifier for single mode")
    parser.add_argument("--inventory", help="Fixture inventory JSON for batch generation")
    parser.add_argument("--fixtures-root", default=str(PACKAGE_ROOT / "scripts" / "fixtures"), help="Root dir for inventory-relative fixture paths")
    parser.add_argument("--lineage-out", default=str(PACKAGE_ROOT / "scripts" / "fixtures" / "fixture_lineage.json"), help="Path to lineage manifest JSON")
    args = parser.parse_args(argv)
    if args.inventory:
        return args
    if not args.source or not args.output:
        parser.error("--source and --output are required in single mode when --inventory is not provided")
    return args


def main(argv=None):
    args = parse_args(argv)
    lineage_out = Path(args.lineage_out).resolve()
    if args.inventory:
        result = generate_from_inventory(args.inventory, args.fixtures_root, lineage_out)
    else:
        entry = strip_fixture(args.source, args.output, fixture_id=args.fixture_id)
        result = {
            "schema_version": LINEAGE_SCHEMA_VERSION,
            "generator": "scripts/make_stripped_fixture.py",
            "entries": [entry],
        }
        _write_json(lineage_out, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
