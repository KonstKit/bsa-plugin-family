#!/usr/bin/env python3
import argparse
import copy
import datetime as dt
import json
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from itertools import combinations
from pathlib import Path

import yaml

NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
}

for k, v in NS.items():
    ET.register_namespace(k, v)


class LayoutError(RuntimeError):
    pass


NATIVE_LAYOUT_PROFILES = (
    "native_greenfield",
    "native_preserve_existing",
    "native_repair_escalated",
)
SIMPLE_PROFILE_FALLBACKS = {
    "simple_postprocess_refine": "native_preserve_existing",
    "simple_postprocess_repair": "native_repair_escalated",
    "simple_postprocess_greenfield": "native_greenfield",
}
LAYOUT_SUMMARY_SCHEMA_VERSION = "1"
CANONICAL_LAYOUT_PROFILE_ALIASES = {
    "greenfield_canonical": "native_greenfield",
    "preserve_existing": "native_preserve_existing",
    "repair_escalated": "native_repair_escalated",
}
LAYOUT_PROFILE_ALIASES = {**CANONICAL_LAYOUT_PROFILE_ALIASES}
REQUIRED_POLICY_KEYS = (
    "default_profile",
    "fallback_profile",
    "escalated_profile",
)
SIMPLE_POLICY_KEYS = (
    "simple_default_profile",
    "simple_escalated_profile",
    "simple_fallback_profile",
)
SIMPLE_POLICY_DEFAULTS = {
    "simple_default_profile": "simple_postprocess_refine",
    "simple_escalated_profile": "simple_postprocess_repair",
    "simple_fallback_profile": "simple_postprocess_greenfield",
}
REQUIRED_THRESHOLD_KEYS = (
    "margin_x",
    "margin_y",
    "gap_x",
    "gap_y",
    "subrow_gap",
    "max_shape_shift",
    "max_label_shift",
)
OPTIONAL_THRESHOLD_DEFAULTS = {
    "participant_band_margin": 40,
    "lane_band_margin": 20,
    "lane_inset_x": 10,
    "lane_inset_y": 10,
    "lane_min_height": 80,
    "lane_min_height_floor": 40,
    "container_padding_x": 30,
    "container_padding_y": 30,
    "compaction_margin": 40,
    "participant_label_offset_x": 10,
    "participant_label_offset_y": 10,
    "lane_label_offset_x": 10,
    "lane_label_offset_y": 10,
    "max_participant_lane_shift": 120,
    "label_zone_gap": 8,
    "label_zone_alternate_gap": 12,
    "label_conflict_padding": 2,
    "label_conflict_budget_step": 40,
    "label_conflict_max_budget": 200,
    "label_conflict_shift_step": 20,
    "label_conflict_shift_levels": 4,
    "edge_label_overlap_step": 18,
    "edge_label_overlap_levels": 5,
    "edge_corridor_thickness": 10,
    "edge_reroute_collision_padding": 2,
    "edge_reroute_channel_minor_offset": 20,
    "edge_reroute_channel_major_offset": 40,
    "edge_reroute_outer_offset": 60,
    "edge_reroute_channel_margin": 160,
    "edge_reroute_outer_count": 2,
    "edge_reroute_channel_limit": 8,
    "edge_reroute_max_passes": 5,
    "edge_branch_fanout_step": 20,
    "edge_branch_fanout_top_multiplier": 2,
    "conflict_local_reclaim_clearance": 20,
    "conflict_local_reclaim_max_passes": 1,
    "conflict_report_issue_limit": 20,
    "column_gap_violation_tolerance": 40,
    "lane_gap_violation_tolerance": 60,
    "boundary_event_fanout_offset": 40,
    "edge_route_same_lane_knee_offset": 20,
    "edge_route_vertical_mid_offset": 30,
    "edge_route_horizontal_mid_offset": 40,
    "edge_route_backtrack_tolerance": 40,
    "edge_route_long_horizontal_soft_limit": 720,
    "edge_route_long_horizontal_penalty_weight": 1,
    "max_diagram_width_px": 1800,
    "max_diagram_height_px": 2400,
    "max_aspect_ratio_x100": 700,
    "max_depth_columns": 18,
    "max_edge_span_columns": 10,
    "max_gateway_chain_length": 6,
}

LAYOUT_HINT_SOURCE_NONE = "none"
LAYOUT_HINT_SOURCE_DISABLED = "disabled"
LAYOUT_HINT_SOURCE_INLINE_JSON = "inline_json"
LAYOUT_HINT_SOURCE_FILE_JSON = "file_json"
LAYOUT_HINT_ALLOWED_THRESHOLD_KEYS = set(REQUIRED_THRESHOLD_KEYS) | set(OPTIONAL_THRESHOLD_DEFAULTS.keys())


def q(ns, tag):
    return "{" + NS[ns] + "}" + tag


def tag_name(element):
    return element.tag.split("}")[-1]


TASK_TYPES = {
    "task",
    "serviceTask",
    "userTask",
    "manualTask",
    "scriptTask",
    "businessRuleTask",
    "sendTask",
    "receiveTask",
    "callActivity",
    "subProcess",
    "transaction",
    "adHocSubProcess",
}
GATEWAY_TYPES = {
    "exclusiveGateway",
    "parallelGateway",
    "inclusiveGateway",
    "eventBasedGateway",
    "complexGateway",
}
EVENT_TYPES = {
    "startEvent",
    "endEvent",
    "intermediateCatchEvent",
    "intermediateThrowEvent",
    "boundaryEvent",
}
SUPPORTED_NODE_TYPES = TASK_TYPES | GATEWAY_TYPES | EVENT_TYPES
SUBPROCESS_LIKE_TYPES = {"subProcess", "transaction", "adHocSubProcess"}


GRID_STEP = 10


def snap(v, grid=GRID_STEP):
    return int(round(v / grid) * grid)


def coord(v):
    return int(round(v))


def normalize_point(point):
    return (coord(point[0]), coord(point[1]))


def points_equal(left, right, epsilon=0):
    return abs(left[0] - right[0]) <= epsilon and abs(left[1] - right[1]) <= epsilon


def rect_intersect(a, b, pad=0):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax + aw + pad <= bx
        or bx + bw + pad <= ax
        or ay + ah + pad <= by
        or by + bh + pad <= ay
    )


def seg_hits_rect(p1, p2, r, pad=0):
    x1, y1 = p1
    x2, y2 = p2
    rx, ry, rw, rh = r
    rx -= pad
    ry -= pad
    rw += 2 * pad
    rh += 2 * pad

    if x1 == x2:
        x = x1
        y0, y1s = sorted((y1, y2))
        return (rx <= x <= rx + rw) and not (y1s < ry or y0 > ry + rh)
    if y1 == y2:
        y = y1
        x0, x1s = sorted((x1, x2))
        return (ry <= y <= ry + rh) and not (x1s < rx or x0 > rx + rw)
    return False


def anchor(rect, side):
    x, y, w, h = rect
    if side == "left":
        return (coord(x), coord(y + h / 2.0))
    if side == "right":
        return (coord(x + w), coord(y + h / 2.0))
    if side == "top":
        return (coord(x + w / 2.0), coord(y))
    if side == "bottom":
        return (coord(x + w / 2.0), coord(y + h))
    raise ValueError(side)


def dedupe_points(points):
    out = []
    for p in points:
        p = normalize_point(p)
        if not out or out[-1] != p:
            out.append(p)
    return out


def orthogonalize_path(points):
    if not points:
        return []
    out = [normalize_point(points[0])]
    for raw in points[1:]:
        point = normalize_point(raw)
        prev = out[-1]
        if prev[0] != point[0] and prev[1] != point[1]:
            corner = (prev[0], point[1])
            if len(out) >= 2:
                prev_prev = out[-2]
                if prev_prev[1] == prev[1]:
                    corner = (point[0], prev[1])
            out.append(normalize_point(corner))
        out.append(point)
    return dedupe_points(out)


def path_non_orthogonal_segments(points):
    return sum(1 for p1, p2 in zip(points, points[1:]) if p1[0] != p2[0] and p1[1] != p2[1])


def estimate_line_count(text, width, char_px=7, padding=24):
    usable = max(1, int((width - padding) // char_px))
    if not text:
        return 1
    return max(1, (len(text) + usable - 1) // usable)


def load_json_file(path):
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def load_layout_hint_payload(raw_value):
    if not raw_value:
        return {}, LAYOUT_HINT_SOURCE_NONE
    candidate = Path(str(raw_value)).expanduser()
    if candidate.exists():
        return load_json_file(candidate), LAYOUT_HINT_SOURCE_FILE_JSON
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise LayoutError(f"Layout hints must be valid JSON or existing file path: {exc}") from exc
    if not isinstance(payload, dict):
        raise LayoutError("Layout hints payload must be a JSON object")
    return payload, LAYOUT_HINT_SOURCE_INLINE_JSON


def resolve_layout_hint_overrides(layout_hints, profile_name, scope):
    if not layout_hints:
        return {}
    if not isinstance(layout_hints, dict):
        raise LayoutError("Layout hints payload must be a JSON object")
    raw_profiles = layout_hints.get("profiles")
    if raw_profiles is None:
        return {}
    profiles = require_mapping(raw_profiles, "layout_hints.profiles")

    profile_context = None
    profile_payload = None
    for raw_profile_name, raw_profile_payload in profiles.items():
        resolved_profile_name = resolve_layout_profile_name(raw_profile_name)
        if resolved_profile_name != profile_name:
            continue
        if profile_payload is not None:
            raise LayoutError(
                f"Layout hints contain duplicate profile entries after alias resolution for {profile_name!r}"
            )
        profile_context = f"layout_hints.profiles.{raw_profile_name}"
        profile_payload = require_mapping(raw_profile_payload, profile_context)

    if profile_payload is None:
        return {}

    scope_payload = profile_payload.get(scope)
    if scope_payload is None:
        return {}
    scope_mapping = require_mapping(scope_payload, f"{profile_context}.{scope}")

    overrides = {}
    for key, value in scope_mapping.items():
        if key not in LAYOUT_HINT_ALLOWED_THRESHOLD_KEYS:
            continue
        overrides[key] = parse_threshold_value(value, f"{profile_context}.{scope}.{key}")
    return overrides


def apply_layout_hint_overrides(thresholds, layout_hints, profile_name, scope):
    updated_thresholds = dict(thresholds)
    overrides = resolve_layout_hint_overrides(layout_hints, profile_name, scope)
    if not overrides:
        return updated_thresholds, False
    updated_thresholds.update(overrides)
    return updated_thresholds, True


def resolve_layout_profile_name(profile_name):
    profile_name = str(profile_name)
    return LAYOUT_PROFILE_ALIASES.get(profile_name, profile_name)


def default_layout_config_path():
    return Path(__file__).resolve().parent.parent / "config" / "layout_thresholds.yaml"


def load_yaml_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise LayoutError(f"Expected YAML mapping in {path}")
    return data


def require_mapping(value, context):
    if not isinstance(value, dict):
        raise LayoutError(f"Layout policy config expected mapping for {context}")
    return value


def parse_threshold_value(value, context):
    if isinstance(value, bool):
        raise LayoutError(f"Layout policy config expected integer value for {context}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise LayoutError(f"Layout policy config expected integer value for {context}")
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped.lstrip("+-").isdigit():
            return int(stripped)
    raise LayoutError(f"Layout policy config expected integer value for {context}")


def normalize_thresholds(raw_thresholds, context):
    thresholds = require_mapping(raw_thresholds, context)
    missing = [key for key in REQUIRED_THRESHOLD_KEYS if key not in thresholds]
    if missing:
        joined = ", ".join(missing)
        raise LayoutError(f"Layout policy config missing required keys for {context}: {joined}")

    normalized = {}
    for key in REQUIRED_THRESHOLD_KEYS:
        normalized[key] = parse_threshold_value(thresholds[key], f"{context}.{key}")
    for key, default_value in OPTIONAL_THRESHOLD_DEFAULTS.items():
        normalized[key] = parse_threshold_value(thresholds.get(key, default_value), f"{context}.{key}")
    return normalized


def load_layout_policy_config(path=None):
    config_path = Path(path).resolve() if path else default_layout_config_path()
    raw = load_yaml_file(config_path)

    policy = require_mapping(raw.get("policy"), "policy")
    profiles = require_mapping(raw.get("profiles"), "profiles")
    missing_policy_keys = [key for key in REQUIRED_POLICY_KEYS if key not in policy]
    if missing_policy_keys:
        joined = ", ".join(missing_policy_keys)
        raise LayoutError(f"Layout policy config missing required keys for policy: {joined}")

    normalized_profiles = {}
    for profile_name, profile_value in profiles.items():
        resolved_profile_name = resolve_layout_profile_name(profile_name)
        profile_context = f"profiles.{profile_name}"
        profile_mapping = require_mapping(profile_value, profile_context)
        if resolved_profile_name in normalized_profiles:
            raise LayoutError(
                f"Layout policy config defines duplicate profile after alias resolution: {profile_name}"
            )
        normalized_profiles[resolved_profile_name] = {
            "main": normalize_thresholds(profile_mapping.get("main"), f"{profile_context}.main"),
            "nested": normalize_thresholds(profile_mapping.get("nested"), f"{profile_context}.nested"),
        }

    for profile_name in NATIVE_LAYOUT_PROFILES:
        if profile_name not in normalized_profiles:
            raise LayoutError(f"Layout policy config missing required profile: {profile_name}")

    resolved_policy = {}
    for key in REQUIRED_POLICY_KEYS:
        profile_name = resolve_layout_profile_name(policy[key])
        if profile_name not in normalized_profiles:
            raise LayoutError(f"Layout policy config references unknown profile for policy.{key}: {profile_name}")
        resolved_policy[key] = profile_name

    for key in SIMPLE_POLICY_KEYS:
        raw_value = policy.get(key, SIMPLE_POLICY_DEFAULTS[key])
        profile_name = resolve_layout_profile_name(raw_value)
        fallback_profile = SIMPLE_PROFILE_FALLBACKS.get(profile_name)
        if profile_name not in normalized_profiles and (
            fallback_profile is None or fallback_profile not in normalized_profiles
        ):
            raise LayoutError(
                f"Layout policy config references unknown profile for policy.{key}: {profile_name}"
            )
        resolved_policy[key] = profile_name

    return {
        "path": str(config_path),
        "policy": resolved_policy,
        "profiles": normalized_profiles,
    }


def resolve_threshold_profile(layout_policy, profile_name, scope="main"):
    profile_name = resolve_layout_profile_name(profile_name)
    profiles = layout_policy["profiles"]
    if profile_name not in profiles:
        fallback_profile = SIMPLE_PROFILE_FALLBACKS.get(profile_name)
        if fallback_profile and fallback_profile in profiles:
            profile_name = fallback_profile
        else:
            raise LayoutError(f"Unknown layout profile: {profile_name}")
    if scope not in ("main", "nested"):
        raise LayoutError(f"Unknown layout profile scope: {scope}")
    return dict(profiles[profile_name][scope])


def threshold_value(thresholds, key, fallback=None):
    if thresholds and key in thresholds:
        return thresholds[key]
    if fallback is not None:
        return fallback
    return OPTIONAL_THRESHOLD_DEFAULTS[key]


def rect_to_bbox(rect):
    if rect is None:
        return None
    return [snap(rect[0]), snap(rect[1]), snap(rect[2]), snap(rect[3])]


def bbox_union(*rects):
    valid = [rect for rect in rects if rect is not None]
    if not valid:
        return None
    min_x = min(rect[0] for rect in valid)
    min_y = min(rect[1] for rect in valid)
    max_x = max(rect[0] + rect[2] for rect in valid)
    max_y = max(rect[1] + rect[3] for rect in valid)
    return [snap(min_x), snap(min_y), snap(max_x - min_x), snap(max_y - min_y)]


def path_bbox(points, pad=0):
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x = min(xs) - pad
    min_y = min(ys) - pad
    max_x = max(xs) + pad
    max_y = max(ys) + pad
    return [coord(min_x), coord(min_y), coord(max(max_x - min_x, 1)), coord(max(max_y - min_y, 1))]


def make_typed_issue(target_type, element_id, secondary_element_id=None, bbox=None, severity="error", code="unknown"):
    return {
        "target_type": target_type,
        "element_id": element_id,
        "secondary_element_id": secondary_element_id,
        "bbox": bbox,
        "severity": severity,
        "code": code,
    }


def issue_count_by_code(issues):
    counts = defaultdict(int)
    for issue in issues:
        counts[issue["code"]] += 1
    return dict(sorted(counts.items()))


def build_subprocess_layouts_for_profile(processes, process_lane_map, external_lane_map, type_config, nested_thresholds):
    top_level_subprocess_specs = {}
    for process in processes:
        _, _, process_subprocess_elements = collect_direct_container_graph(process, process.get("id"))
        for subprocess_id, subprocess_element in process_subprocess_elements.items():
            top_level_subprocess_specs[subprocess_id] = build_subprocess_layout_spec(
                subprocess_element,
                process.get("id"),
                process_lane_map,
                external_lane_map,
                type_config,
                nested_thresholds,
            )
    return top_level_subprocess_specs, flatten_subprocess_specs(top_level_subprocess_specs)


def build_layout_dims(nodes, flattened_subprocess_specs, type_config):
    dims = {}
    for nid, meta in nodes.items():
        if nid in flattened_subprocess_specs:
            default_dims = node_dims(meta["type"], meta["name"], type_config)
            child_dims = flattened_subprocess_specs[nid]["outer_dims"]
            dims[nid] = (max(default_dims[0], child_dims[0]), max(default_dims[1], child_dims[1]))
        else:
            dims[nid] = node_dims(meta["type"], meta["name"], type_config)
    return dims


def build_participant_rect(process_id, rects, nodes, label_rects=None, thresholds=None, margin=None):
    margin = threshold_value(thresholds, "participant_band_margin", fallback=margin)
    process_nodes = [rects[nid] for nid, meta in nodes.items() if meta.get("process_id") == process_id and nid in rects]
    process_labels = [
        tuple(label_rects[nid])
        for nid, meta in nodes.items()
        if label_rects and meta.get("process_id") == process_id and nid in label_rects
    ]
    envelopes = process_nodes + process_labels
    if not envelopes:
        return None
    min_x = min(rect[0] for rect in envelopes) - margin
    min_y = min(rect[1] for rect in envelopes) - margin
    max_x = max(rect[0] + rect[2] for rect in envelopes) + margin
    max_y = max(rect[1] + rect[3] for rect in envelopes) + margin
    return (snap(min_x), snap(min_y), snap(max_x - min_x), snap(max_y - min_y))


def is_allowed_shape_overlap(left_id, right_id, nodes):
    left = nodes.get(left_id, {})
    right = nodes.get(right_id, {})
    return (
        left.get("type") == "boundaryEvent" and left.get("attached_to") == right_id
    ) or (
        right.get("type") == "boundaryEvent" and right.get("attached_to") == left_id
    )


def boundary_preferred_side(boundary_rect, host_rect):
    if not boundary_rect:
        return "bottom"
    bx = boundary_rect[0] + boundary_rect[2] / 2.0
    by = boundary_rect[1] + boundary_rect[3] / 2.0
    hx, hy, hw, hh = host_rect
    distances = {
        "top": abs(by - hy),
        "bottom": abs(by - (hy + hh)),
        "left": abs(bx - hx),
        "right": abs(bx - (hx + hw)),
    }
    return min(distances.items(), key=lambda item: (item[1], item[0]))[0]


def boundary_rect_on_host(host_rect, boundary_rect, side, offset=0):
    hx, hy, hw, hh = host_rect
    _, _, bw, bh = boundary_rect
    if side == "top":
        return (snap(hx + hw / 2.0 - bw / 2.0 + offset), snap(hy - bh / 2.0), bw, bh)
    if side == "bottom":
        return (snap(hx + hw / 2.0 - bw / 2.0 + offset), snap(hy + hh - bh / 2.0), bw, bh)
    if side == "left":
        return (snap(hx - bw / 2.0), snap(hy + hh / 2.0 - bh / 2.0 + offset), bw, bh)
    if side == "right":
        return (snap(hx + hw - bw / 2.0), snap(hy + hh / 2.0 - bh / 2.0 + offset), bw, bh)
    return boundary_rect


def attach_boundary_events(rects, nodes, baseline_rects=None, label_rects=None, thresholds=None):
    rects = {nid: tuple(rect) for nid, rect in rects.items()}
    boundary_groups = defaultdict(list)
    for nid, meta in nodes.items():
        if meta.get("type") == "boundaryEvent" and meta.get("attached_to") in rects:
            boundary_groups[meta["attached_to"]].append(nid)

    for host_id, boundary_ids in boundary_groups.items():
        host_rect = rects[host_id]
        ordered = sorted(
            boundary_ids,
            key=lambda nid: (
                boundary_preferred_side((baseline_rects or {}).get(nid) or rects[nid], host_rect),
                nid,
            ),
        )
        side_buckets = defaultdict(list)
        offset_step = threshold_value(thresholds, "boundary_event_fanout_offset")
        for nid in ordered:
            baseline_rect = (baseline_rects or {}).get(nid) or rects[nid]
            side_buckets[boundary_preferred_side(baseline_rect, host_rect)].append(nid)

        for side, bucket in side_buckets.items():
            count = len(bucket)
            for index, nid in enumerate(bucket):
                offset = snap((index - (count - 1) / 2.0) * offset_step)
                old_rect = rects[nid]
                rects[nid] = boundary_rect_on_host(host_rect, old_rect, side, offset=offset)
                if label_rects is not None and nid in label_rects:
                    dx = rects[nid][0] - old_rect[0]
                    dy = rects[nid][1] - old_rect[1]
                    lx, ly, lw, lh = label_rects[nid]
                    label_rects[nid] = [snap(lx + dx), snap(ly + dy), lw, lh]

    return rects, label_rects


def extract_lane_definitions(process):
    lanes = []
    for lane in process.findall(".//" + q("bpmn", "lane")):
        node_refs = [ref.text for ref in lane.findall(q("bpmn", "flowNodeRef")) if ref.text]
        lanes.append(
            {
                "id": lane.get("id"),
                "name": lane.get("name", ""),
                "process_id": process.get("id"),
                "node_refs": node_refs,
            }
        )
    return lanes


def extract_message_flows(collaboration):
    message_flows = []
    if collaboration is None:
        return message_flows
    for child in list(collaboration):
        if tag_name(child) != "messageFlow":
            continue
        message_flows.append(
            {
                "id": child.get("id"),
                "name": child.get("name", ""),
                "source": child.get("sourceRef"),
                "target": child.get("targetRef"),
            }
        )
    return message_flows


def collect_ids(root):
    ids = set()
    for element in root.iter():
        element_id = element.get("id")
        if element_id:
            ids.add(element_id)
    return ids


def unique_id(base, used_ids):
    if base not in used_ids:
        used_ids.add(base)
        return base
    index = 2
    while f"{base}_{index}" in used_ids:
        index += 1
    result = f"{base}_{index}"
    used_ids.add(result)
    return result


def ensure_collaboration_for_lane_processes(root, processes, collaboration, participants, lane_defs_by_process):
    if collaboration is not None:
        return collaboration, participants, False
    if not any(lane_defs_by_process.get(process.get("id")) for process in processes):
        return collaboration, participants, False

    used_ids = collect_ids(root)
    collaboration_id = unique_id("Collaboration_1", used_ids)
    new_collaboration = ET.Element(q("bpmn", "collaboration"), {"id": collaboration_id})

    created_participants = []
    for process in processes:
        process_id = process.get("id")
        if not process_id:
            continue
        participant_id = unique_id(f"Participant_{process_id}", used_ids)
        participant_name = process.get("name", "") or process_id
        participant_element = ET.SubElement(
            new_collaboration,
            q("bpmn", "participant"),
            {
                "id": participant_id,
                "name": participant_name,
                "processRef": process_id,
            },
        )
        created_participants.append(
            {
                "id": participant_element.get("id"),
                "name": participant_element.get("name", ""),
                "processRef": participant_element.get("processRef"),
            }
        )

    first_diagram = root.find(q("bpmndi", "BPMNDiagram"))
    if first_diagram is None:
        root.append(new_collaboration)
    else:
        root.insert(list(root).index(first_diagram), new_collaboration)
    return new_collaboration, created_participants, True


def extract_artifacts(process):
    artifacts = []
    associations = []
    for child in list(process):
        tag = tag_name(child)
        if tag in {"dataObjectReference", "dataStoreReference", "textAnnotation", "group"}:
            artifacts.append(
                {
                    "id": child.get("id"),
                    "type": tag,
                    "name": (
                        child.get("name", "")
                        if tag not in {"textAnnotation", "group"}
                        else (child.get("name", "") or child.get("categoryValueRef", "") or "".join(child.itertext()).strip())
                    ),
                    "process_id": process.get("id"),
                }
            )
        elif tag == "association":
            associations.append(
                {
                    "id": child.get("id"),
                    "source": child.get("sourceRef"),
                    "target": child.get("targetRef"),
                    "process_id": process.get("id"),
                }
            )
    return artifacts, associations


def artifact_dims(artifact_type, text):
    if artifact_type == "group":
        width = 180
        max_width = 320
        while width <= max_width:
            lines = estimate_line_count(text or "", width, char_px=6, padding=20)
            if lines <= 2:
                return (snap(width), snap(max(70, 30 + lines * 18)))
            width += 20
        return (snap(max_width), 90)
    if artifact_type == "textAnnotation":
        width = 140
        max_width = 240
        while width <= max_width:
            lines = estimate_line_count(text or "", width, char_px=6, padding=16)
            if lines <= 3:
                return (snap(width), snap(max(40, 20 + lines * 16)))
            width += 20
        lines = estimate_line_count(text or "", max_width, char_px=6, padding=16)
        return (snap(max_width), snap(max(40, 20 + lines * 16)))
    if artifact_type == "dataStoreReference":
        return (50, 60)
    return (36, 50)


def build_process_envelope(process_id, rects, nodes, label_rects=None, thresholds=None, margin=None):
    margin = threshold_value(thresholds, "participant_band_margin", fallback=margin)
    process_nodes = [rects[nid] for nid, meta in nodes.items() if meta.get("process_id") == process_id and nid in rects]
    process_labels = [
        tuple(label_rects[nid])
        for nid, meta in nodes.items()
        if label_rects and meta.get("process_id") == process_id and nid in label_rects
    ]
    envelopes = process_nodes + process_labels
    if not envelopes:
        return None
    min_x = min(rect[0] for rect in envelopes) - margin
    min_y = min(rect[1] for rect in envelopes) - margin
    max_x = max(rect[0] + rect[2] for rect in envelopes) + margin
    max_y = max(rect[1] + rect[3] for rect in envelopes) + margin
    return (snap(min_x), snap(min_y), snap(max_x - min_x), snap(max_y - min_y))


def build_lane_rect(lane_def, rects, process_rect, thresholds=None, margin=None):
    margin = threshold_value(thresholds, "lane_band_margin", fallback=margin)
    lane_inset_x = threshold_value(thresholds, "lane_inset_x")
    lane_inset_y = threshold_value(thresholds, "lane_inset_y")
    lane_min_height = threshold_value(thresholds, "lane_min_height")
    member_rects = [rects[nid] for nid in lane_def["node_refs"] if nid in rects]
    if not member_rects or process_rect is None:
        return None
    x = process_rect[0] + lane_inset_x
    w = max(100, process_rect[2] - lane_inset_x * 2)
    min_y = min(rect[1] for rect in member_rects) - margin
    max_y = max(rect[1] + rect[3] for rect in member_rects) + margin
    y = max(process_rect[1] + lane_inset_y, min_y)
    h = min(process_rect[1] + process_rect[3] - y - lane_inset_y, max_y - y)
    return (snap(x), snap(y), snap(w), snap(max(h, lane_min_height)))


def build_contiguous_lane_rects(lane_defs, rects, process_rect, thresholds=None, margin=None, min_height=None):
    if not lane_defs or process_rect is None:
        return {}

    margin = threshold_value(thresholds, "lane_band_margin", fallback=margin)
    lane_inset_x = threshold_value(thresholds, "lane_inset_x")
    lane_inset_y = threshold_value(thresholds, "lane_inset_y")
    configured_min_height = threshold_value(thresholds, "lane_min_height", fallback=min_height)
    min_height_floor = threshold_value(thresholds, "lane_min_height_floor")

    x = process_rect[0] + lane_inset_x
    w = max(100, process_rect[2] - lane_inset_x * 2)
    top = process_rect[1] + lane_inset_y
    bottom = process_rect[1] + process_rect[3] - lane_inset_y
    available = max(0, bottom - top)
    lane_count = len(lane_defs)
    if lane_count == 0 or available <= 0:
        return {}

    effective_min_height = configured_min_height
    if available < configured_min_height * lane_count:
        effective_min_height = max(min_height_floor, available // lane_count)

    desired_heights = []
    for lane_def in lane_defs:
        member_rects = [rects[nid] for nid in lane_def["node_refs"] if nid in rects]
        if member_rects:
            min_y = min(rect[1] for rect in member_rects) - margin
            max_y = max(rect[1] + rect[3] for rect in member_rects) + margin
            desired_heights.append(max(effective_min_height, snap(max_y - min_y)))
        else:
            desired_heights.append(effective_min_height)

    desired_total = sum(desired_heights)
    if desired_total <= 0:
        desired_heights = [effective_min_height] * lane_count
        desired_total = sum(desired_heights)
    scale = available / desired_total if desired_total else 1.0

    heights = [max(effective_min_height, snap(height * scale)) for height in desired_heights]
    current_total = sum(heights)
    if current_total > available:
        overflow = current_total - available
        for idx in sorted(range(lane_count), key=lambda i: heights[i] - effective_min_height, reverse=True):
            if overflow <= 0:
                break
            slack = heights[idx] - effective_min_height
            if slack <= 0:
                continue
            cut = min(slack, overflow)
            heights[idx] -= cut
            overflow -= cut
    elif current_total < available:
        heights[-1] += available - current_total

    lane_rects = {}
    cursor = top
    for idx, lane_def in enumerate(lane_defs):
        lane_id = lane_def.get("id")
        if not lane_id:
            cursor += heights[idx]
            continue
        if idx == lane_count - 1:
            h = max(effective_min_height, bottom - cursor)
        else:
            h = heights[idx]
        lane_rects[lane_id] = (snap(x), snap(cursor), snap(w), snap(h))
        cursor += h
    return lane_rects


def regenerated_di_element_ids(participants, lane_defs_by_process):
    regenerated = set()
    for participant in participants:
        participant_id = participant.get("id")
        if participant_id:
            regenerated.add(participant_id)
    for lane_defs in lane_defs_by_process.values():
        for lane_def in lane_defs:
            lane_id = lane_def.get("id")
            if lane_id:
                regenerated.add(lane_id)
    return regenerated


def route_free_edge(source_rect, target_rect):
    sx, sy, sw, sh = source_rect
    tx, ty, tw, th = target_rect
    if sx + sw <= tx:
        start = anchor(source_rect, "right")
        end = anchor(target_rect, "left")
        mid_x = coord((start[0] + end[0]) / 2.0)
        return dedupe_points([start, (mid_x, start[1]), (mid_x, end[1]), end])
    if tx + tw <= sx:
        start = anchor(source_rect, "left")
        end = anchor(target_rect, "right")
        mid_x = coord((start[0] + end[0]) / 2.0)
        return dedupe_points([start, (mid_x, start[1]), (mid_x, end[1]), end])
    if sy + sh <= ty:
        start = anchor(source_rect, "bottom")
        end = anchor(target_rect, "top")
        mid_y = coord((start[1] + end[1]) / 2.0)
        return dedupe_points([start, (start[0], mid_y), (end[0], mid_y), end])
    start = anchor(source_rect, "top")
    end = anchor(target_rect, "bottom")
    mid_y = coord((start[1] + end[1]) / 2.0)
    return dedupe_points([start, (start[0], mid_y), (end[0], mid_y), end])


def place_artifacts(artifacts, associations, rects, nodes, participant_rects, label_rects=None, thresholds=None):
    artifact_rects = {}
    association_paths = {}
    linked_items = defaultdict(list)
    for association in associations:
        linked_items[association["source"]].append(association["target"])
        linked_items[association["target"]].append(association["source"])

    process_envelopes = {}
    placement_counters = defaultdict(int)
    for artifact in artifacts:
        process_id = artifact["process_id"]
        process_envelopes[process_id] = process_envelopes.get(process_id) or build_process_envelope(
            process_id,
            rects,
            nodes,
            label_rects=label_rects,
            thresholds=thresholds,
        )
        w, h = artifact_dims(artifact["type"], artifact["name"])
        links = linked_items.get(artifact["id"], [])
        anchor_id = next((ref for ref in links if ref in rects or ref in participant_rects), None)
        if anchor_id in rects:
            ax, ay, aw, ah = rects[anchor_id]
        elif anchor_id in participant_rects:
            ax, ay, aw, ah = participant_rects[anchor_id]
        else:
            envelope = process_envelopes[process_id]
            if envelope is None:
                continue
            ax, ay, aw, ah = envelope

        index = placement_counters[(process_id, anchor_id)]
        placement_counters[(process_id, anchor_id)] += 1
        x = snap(ax + aw + 40)
        y = snap(ay + index * 70)
        if artifact["type"] == "group":
            envelope = process_envelopes[process_id]
            x = snap(envelope[0] + 10)
            y = snap(envelope[1] + envelope[3] + 40 + index * 100)
            w = max(w, snap(envelope[2] - 20))
        elif artifact["type"] == "dataStoreReference":
            envelope = process_envelopes[process_id]
            x = snap(envelope[0] + envelope[2] + 40)
            y = snap(ay + index * 80)
        artifact_rects[artifact["id"]] = (x, y, w, h)

    for association in associations:
        source_ref = association["source"]
        target_ref = association["target"]
        source_rect = artifact_rects.get(source_ref) or rects.get(source_ref) or participant_rects.get(source_ref)
        target_rect = artifact_rects.get(target_ref) or rects.get(target_ref) or participant_rects.get(target_ref)
        if source_rect and target_rect:
            association_paths[association["id"]] = route_free_edge(source_rect, target_rect)

    return artifact_rects, association_paths


def node_dims(node_type, name, type_config=None):
    if type_config and node_type in type_config:
        entry = type_config[node_type]
        if isinstance(entry, dict):
            width = snap(entry.get("width", 180))
            height = snap(entry.get("height", 80))
            return (width, height)

    if node_type in TASK_TYPES:
        width = 180
        if node_type in {"callActivity"} | SUBPROCESS_LIKE_TYPES:
            width = 220
        max_width = 360
        while width <= max_width:
            lines = estimate_line_count(name or "", width)
            if lines <= 2:
                min_height = 100 if node_type in SUBPROCESS_LIKE_TYPES else 80
                return (snap(width), max(min_height, snap(40 + lines * 18)))
            width += 20
        lines = estimate_line_count(name or "", max_width)
        min_height = 100 if node_type in SUBPROCESS_LIKE_TYPES else 80
        height = max(min_height, snap(40 + lines * 18))
        return (snap(max_width), height)
    if node_type in GATEWAY_TYPES:
        return (50, 50)
    if node_type in EVENT_TYPES:
        return (36, 36)
    return (180, 80)


def label_dims(text):
    width = 60
    max_width = 160
    while width <= max_width:
        lines = estimate_line_count(text or "", width, char_px=6, padding=12)
        if lines <= 2:
            return (snap(width), snap(max(14, lines * 14)))
        width += 20
    lines = estimate_line_count(text or "", max_width, char_px=6, padding=12)
    return (snap(max_width), snap(max(14, lines * 14)))


def choose_flow_label_rect(path, flow_name):
    if not flow_name:
        return None
    if not path or len(path) < 2:
        return None

    lw, lh = label_dims(flow_name)
    segments = []
    for i in range(len(path) - 1):
        x1, y1 = path[i]
        x2, y2 = path[i + 1]
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        length = max(dx, dy)
        if length < 8:
            continue
        kind = "h" if dx >= dy else "v"
        segments.append((i, kind, length, x1, y1, x2, y2))

    if not segments:
        return None

    span_count = len(segments)
    chosen = max(
        segments,
        key=lambda seg: (
            seg[1] == "h",
            seg[2] >= max(80, lw + 30),
            0 < seg[0] < span_count - 1,
            seg[2],
            seg[0],
        ),
    )

    _, kind, _, x1, y1, x2, y2 = chosen
    if kind == "h":
        mid_x = (x1 + x2) / 2.0
        y = y1
        lx = snap(mid_x - lw / 2.0)
        ly = snap(y - lh - 8)
        if ly < 0:
            ly = snap(y + 8)
    else:
        x = x1
        mid_y = (y1 + y2) / 2.0
        lx = snap(x + 8)
        ly = snap(mid_y - lh / 2.0)
    return [lx, ly, lw, lh]


def resolve_edge_label_overlaps(label_rects, thresholds=None):
    if not label_rects:
        return {}
    resolved = {}
    placed = []
    ordered = sorted(label_rects.items(), key=lambda item: (item[1][1], item[1][0], item[0]))
    step = threshold_value(thresholds, "edge_label_overlap_step")
    levels = threshold_value(thresholds, "edge_label_overlap_levels")
    offsets = [0]
    for level in range(1, levels + 1):
        offsets.extend([-step * level, step * level])
    for flow_id, rect in ordered:
        x, y, w, h = rect
        candidate = [x, y, w, h]
        found = False
        for offset in offsets:
            test = (snap(x), snap(y + offset), w, h)
            if all(not rect_intersect(test, other, pad=4) for other in placed):
                candidate = [test[0], test[1], w, h]
                found = True
                break
        if not found:
            candidate = [snap(x), snap(y), w, h]
        resolved[flow_id] = candidate
        placed.append(tuple(candidate))
    return resolved


def infer_lane(node_id):
    lowered = (node_id or "").lower()
    if any(token in lowered for token in ("error", "failure", "exception")):
        return 3
    if any(token in lowered for token in ("escalat", "handoff", "manual-review")):
        return 2
    if any(token in lowered for token in ("approval", "approve", "reject")):
        return 1
    return 0


def load_lane_map(path):
    raw = load_json_file(path)
    lane_map = {}
    for key, value in raw.items():
        lane_map[str(key)] = int(value)
    return lane_map


def collect_direct_container_graph(container, process_id):
    nodes = {}
    flows = []
    subprocess_elements = {}
    container_id = container.get("id", process_id)
    for child in list(container):
        tag = tag_name(child)
        if tag in SUPPORTED_NODE_TYPES:
            nid = child.get("id")
            if not nid:
                continue
            nodes[nid] = {
                "id": nid,
                "type": tag,
                "name": child.get("name", ""),
                "process_id": process_id,
                "container_id": container_id,
                "is_event_subprocess": tag == "subProcess" and child.get("triggeredByEvent") == "true",
                "attached_to": child.get("attachedToRef") if tag == "boundaryEvent" else None,
                "cancel_activity": child.get("cancelActivity") if tag == "boundaryEvent" else None,
            }
            if tag in SUBPROCESS_LIKE_TYPES:
                subprocess_elements[nid] = child
        elif tag == "sequenceFlow":
            fid = child.get("id")
            source = child.get("sourceRef")
            target = child.get("targetRef")
            if fid and source and target:
                flows.append(
                    {
                        "id": fid,
                        "source": source,
                        "target": target,
                        "name": child.get("name", ""),
                    }
                )
    return nodes, flows, subprocess_elements


def resolve_lane_assignments(nodes, process_lane_map, external_lane_map, existing_rects=None):
    lane = {}
    lane_from_existing = infer_lanes_from_existing_layout(existing_rects or {})
    for nid in nodes:
        if nid in external_lane_map:
            lane[nid] = external_lane_map[nid]
        elif nid in process_lane_map:
            lane[nid] = process_lane_map[nid]
        elif nid in lane_from_existing:
            lane[nid] = lane_from_existing[nid]
        else:
            lane[nid] = infer_lane(nid)
    return lane


def extract_lane_membership(process):
    lane_membership = {}
    ordered_lanes = []
    for idx, lane in enumerate(process.findall(".//" + q("bpmn", "lane"))):
        lane_id = lane.get("id", f"lane_{idx}")
        ordered_lanes.append(lane_id)
        for ref in lane.findall(q("bpmn", "flowNodeRef")):
            if ref.text:
                lane_membership[ref.text] = lane_id
    lane_index = {lane_id: i for i, lane_id in enumerate(ordered_lanes)}
    return {nid: lane_index[lid] for nid, lid in lane_membership.items() if lid in lane_index}


def infer_lanes_from_existing_layout(existing_rects, tolerance=70):
    if not existing_rects:
        return {}
    ordered = sorted(
        ((nid, rect[1] + rect[3] / 2.0) for nid, rect in existing_rects.items()),
        key=lambda item: item[1],
    )
    bands = []
    for nid, center_y in ordered:
        placed = False
        for band in bands:
            if abs(center_y - band["mean"]) <= tolerance:
                band["nodes"].append(nid)
                band["sum"] += center_y
                band["mean"] = band["sum"] / len(band["nodes"])
                placed = True
                break
        if not placed:
            bands.append({"nodes": [nid], "sum": center_y, "mean": center_y})
    lane_map = {}
    for lane_idx, band in enumerate(bands):
        for nid in band["nodes"]:
            lane_map[nid] = lane_idx
    return lane_map


def detect_back_edges(nodes, outgoing, roots):
    back_edges = set()
    state = {}
    ordered_roots = list(dict.fromkeys(roots + sorted(nodes.keys())))

    for node_id in ordered_roots:
        if state.get(node_id, 0) != 0:
            continue
        stack = [(node_id, iter(sorted(outgoing.get(node_id, []))))]
        state[node_id] = 1
        while stack:
            current, children = stack[-1]
            try:
                target = next(children)
            except StopIteration:
                state[current] = 2
                stack.pop()
                continue

            target_state = state.get(target, 0)
            if target_state == 0:
                state[target] = 1
                stack.append((target, iter(sorted(outgoing.get(target, [])))))
            elif target_state == 1:
                back_edges.add((current, target))
    return back_edges


def compute_depths(nodes, flows):
    outgoing = defaultdict(list)
    indeg = {nid: 0 for nid in nodes}
    for f in flows:
        s = f["source"]
        t = f["target"]
        if s in nodes and t in nodes:
            outgoing[s].append(t)
            indeg[t] += 1

    roots = [
        nid for nid, meta in nodes.items() if meta["type"] == "startEvent"
    ] or [nid for nid, deg in indeg.items() if deg == 0]
    back_edges = detect_back_edges(nodes, outgoing, roots)

    dag_indeg = {nid: 0 for nid in nodes}
    for source, targets in outgoing.items():
        for target in targets:
            if (source, target) not in back_edges:
                dag_indeg[target] += 1

    qn = deque([n for n, d in dag_indeg.items() if d == 0])
    topo = []
    while qn:
        n = qn.popleft()
        topo.append(n)
        for t in outgoing[n]:
            if (n, t) in back_edges:
                continue
            dag_indeg[t] -= 1
            if dag_indeg[t] == 0:
                qn.append(t)

    if len(topo) < len(nodes):
        seen = set(topo)
        topo.extend(nid for nid in sorted(nodes.keys()) if nid not in seen)

    depth = {nid: 0 for nid in nodes}
    for n in topo:
        for t in outgoing[n]:
            if (n, t) in back_edges:
                continue
            depth[t] = max(depth[t], depth[n] + 1)

    for nid, meta in nodes.items():
        if meta["type"] == "startEvent":
            depth[nid] = 0

    return depth


def load_existing_di(root, node_ids, flow_ids):
    rects = {}
    labels = {}
    edges = {}
    extras = []
    plane = root.find(".//" + q("bpmndi", "BPMNPlane"))
    if plane is None:
        return rects, labels, edges, extras, None, None, None

    for shape in plane.findall(q("bpmndi", "BPMNShape")):
        element_id = shape.get("bpmnElement")
        bounds = shape.find(q("dc", "Bounds"))
        if bounds is None or element_id is None:
            continue
        rect = (
            snap(float(bounds.get("x"))),
            snap(float(bounds.get("y"))),
            snap(float(bounds.get("width"))),
            snap(float(bounds.get("height"))),
        )
        if element_id in node_ids:
            rects[element_id] = rect
            label = shape.find(q("bpmndi", "BPMNLabel"))
            if label is not None:
                lb = label.find(q("dc", "Bounds"))
                if lb is not None:
                    labels[element_id] = [
                        snap(float(lb.get("x"))),
                        snap(float(lb.get("y"))),
                        snap(float(lb.get("width"))),
                        snap(float(lb.get("height"))),
                    ]
        else:
            extras.append(copy.deepcopy(shape))

    for edge in plane.findall(q("bpmndi", "BPMNEdge")):
        element_id = edge.get("bpmnElement")
        if element_id not in flow_ids:
            extras.append(copy.deepcopy(edge))
            continue
        waypoints = []
        for wp in edge.findall(q("di", "waypoint")):
            waypoints.append((coord(float(wp.get("x"))), coord(float(wp.get("y")))))
        if waypoints:
            edges[element_id] = orthogonalize_path(dedupe_points(waypoints))

    existing_diagram = root.find(".//" + q("bpmndi", "BPMNDiagram"))
    return (
        rects,
        labels,
        edges,
        extras,
        existing_diagram.get("id") if existing_diagram is not None else None,
        plane.get("id"),
        plane.get("bpmnElement"),
    )


def rect_distance(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def path_displacement(points, baseline):
    if not baseline:
        return 0
    shared = min(len(points), len(baseline))
    dist = 0
    for idx in range(shared):
        dist += abs(points[idx][0] - baseline[idx][0]) + abs(points[idx][1] - baseline[idx][1])
    dist += abs(len(points) - len(baseline)) * 40
    return dist


def segment_length(p1, p2):
    return abs(p2[0] - p1[0]) + abs(p2[1] - p1[1])


def path_anchor_mismatches(points, srect, trect, epsilon=0):
    if not points:
        return 2
    source_anchors = [anchor(srect, side) for side in ("left", "right", "top", "bottom")]
    target_anchors = [anchor(trect, side) for side in ("left", "right", "top", "bottom")]
    mismatches = 0
    if not any(points_equal(points[0], ref, epsilon=epsilon) for ref in source_anchors):
        mismatches += 1
    if not any(points_equal(points[-1], ref, epsilon=epsilon) for ref in target_anchors):
        mismatches += 1
    return mismatches


def infer_anchor_side(rect, point, epsilon=0):
    for side in ("left", "right", "top", "bottom"):
        if points_equal(anchor(rect, side), point, epsilon=epsilon):
            return side
    return None


def gateway_anchor_preference_penalty(src, tgt, points, rects, lane, nodes):
    src_meta = nodes.get(src, {})
    tgt_meta = nodes.get(tgt, {})
    src_type = src_meta.get("type")
    tgt_type = tgt_meta.get("type")

    src_side = infer_anchor_side(rects[src], points[0])
    tgt_side = infer_anchor_side(rects[tgt], points[-1])
    if src_side is None or tgt_side is None:
        return 0

    same_lane = lane.get(src) == lane.get(tgt)
    moving_lr = rects[src][0] <= rects[tgt][0]
    src_cy = rects[src][1] + rects[src][3] / 2.0
    tgt_cy = rects[tgt][1] + rects[tgt][3] / 2.0
    penalty = 0

    if same_lane:
        if src_type in GATEWAY_TYPES:
            preferred = "right" if moving_lr else "left"
            if src_side != preferred:
                penalty += 1
        if tgt_type in GATEWAY_TYPES:
            preferred = "left" if moving_lr else "right"
            if tgt_side != preferred:
                penalty += 1
    else:
        if src_type in GATEWAY_TYPES:
            preferred = "bottom" if tgt_cy > src_cy else "top"
            if src_side != preferred:
                penalty += 1
        if tgt_type in GATEWAY_TYPES:
            preferred = "top" if src_cy < tgt_cy else "bottom"
            if tgt_side != preferred:
                penalty += 1

    return penalty


def path_endpoint_direction_violations(points, srect, trect):
    if len(points) < 2:
        return 2

    violations = 0
    source_side = infer_anchor_side(srect, points[0])
    target_side = infer_anchor_side(trect, points[-1])
    first = points[1]
    last = points[-2]

    if source_side == "right":
        if first[1] != points[0][1] or first[0] < points[0][0]:
            violations += 1
    elif source_side == "left":
        if first[1] != points[0][1] or first[0] > points[0][0]:
            violations += 1
    elif source_side == "top":
        if first[0] != points[0][0] or first[1] > points[0][1]:
            violations += 1
    elif source_side == "bottom":
        if first[0] != points[0][0] or first[1] < points[0][1]:
            violations += 1

    if target_side == "left":
        if last[0] > points[-1][0]:
            violations += 1
    elif target_side == "right":
        if last[0] < points[-1][0]:
            violations += 1
    elif target_side == "top":
        if last[1] > points[-1][1]:
            violations += 1
    elif target_side == "bottom":
        if last[1] < points[-1][1]:
            violations += 1

    return violations


def path_backtrack_violations(points, tolerance=None, thresholds=None):
    if len(points) < 2:
        return 0
    tolerance = threshold_value(thresholds, "edge_route_backtrack_tolerance", fallback=tolerance)
    start_x = points[0][0]
    end_x = points[-1][0]
    xs = [pt[0] for pt in points]
    if start_x <= end_x:
        return int(min(xs) < start_x - tolerance or max(xs) > end_x + tolerance)
    return int(max(xs) > start_x + tolerance or min(xs) < end_x - tolerance)


def path_quality_violations(points, thresholds=None):
    violations = 0
    violations += path_non_orthogonal_segments(points) * 3
    bends = path_bends(points)
    if bends > 3:
        violations += bends - 3
    for idx in range(1, len(points) - 2):
        if segment_length(points[idx], points[idx + 1]) < 20:
            violations += 1
    violations += path_backtrack_violations(points, thresholds=thresholds)
    return violations


def edge_segments(points):
    segments = []
    for idx in range(len(points) - 1):
        p1 = points[idx]
        p2 = points[idx + 1]
        if p1 != p2:
            segments.append((p1, p2))
    return segments


def segment_intersection_invalid(seg_a, seg_b):
    (a1, a2) = seg_a
    (b1, b2) = seg_b
    a_vertical = a1[0] == a2[0]
    b_vertical = b1[0] == b2[0]

    if a_vertical and b_vertical:
        if a1[0] != b1[0]:
            return False
        ay0, ay1 = sorted((a1[1], a2[1]))
        by0, by1 = sorted((b1[1], b2[1]))
        low = max(ay0, by0)
        high = min(ay1, by1)
        if low > high:
            return False
        if low == high:
            point = (a1[0], low)
            return not (point in (a1, a2) and point in (b1, b2))
        return True

    if (not a_vertical) and (not b_vertical):
        if a1[1] != b1[1]:
            return False
        ax0, ax1 = sorted((a1[0], a2[0]))
        bx0, bx1 = sorted((b1[0], b2[0]))
        low = max(ax0, bx0)
        high = min(ax1, bx1)
        if low > high:
            return False
        if low == high:
            point = (low, a1[1])
            return not (point in (a1, a2) and point in (b1, b2))
        return True

    if a_vertical:
        vx = a1[0]
        hy = b1[1]
        ay0, ay1 = sorted((a1[1], a2[1]))
        bx0, bx1 = sorted((b1[0], b2[0]))
        point = (vx, hy)
        if ay0 <= hy <= ay1 and bx0 <= vx <= bx1:
            return not (point in (a1, a2) and point in (b1, b2))
        return False

    return segment_intersection_invalid(seg_b, seg_a)


def is_shared_terminal_overlap(edge_a_id, edge_b_id, seg_a_idx, seg_b_idx, path_a, path_b, flows_by_id):
    if not flows_by_id:
        return False
    flow_a = flows_by_id.get(edge_a_id)
    flow_b = flows_by_id.get(edge_b_id)
    if not flow_a or not flow_b:
        return False
    if flow_a["source"] == flow_b["source"]:
        shared_prefix = 0
        for index in range(min(len(path_a), len(path_b)) - 1):
            if path_a[index] == path_b[index] and path_a[index + 1] == path_b[index + 1]:
                shared_prefix += 1
            else:
                break
        if seg_a_idx == seg_b_idx and seg_a_idx < shared_prefix:
            return True
    if flow_a["target"] == flow_b["target"]:
        shared_suffix = 0
        limit = min(len(path_a), len(path_b)) - 1
        for offset in range(1, limit + 1):
            if path_a[-offset - 1] == path_b[-offset - 1] and path_a[-offset] == path_b[-offset]:
                shared_suffix += 1
            else:
                break
        if seg_a_idx == seg_b_idx and (len(path_a) - 2 - seg_a_idx) < shared_suffix and (len(path_b) - 2 - seg_b_idx) < shared_suffix:
            return True
    return False


def edge_edge_intersections(edge_paths, flows_by_id=None):
    invalid = set()
    edge_items = sorted(edge_paths.items())
    for (edge_a, path_a), (edge_b, path_b) in combinations(edge_items, 2):
        segments_a = edge_segments(path_a)
        segments_b = edge_segments(path_b)
        for seg_a_idx, seg_a in enumerate(segments_a):
            for seg_b_idx, seg_b in enumerate(segments_b):
                if segment_intersection_invalid(seg_a, seg_b):
                    if is_shared_terminal_overlap(edge_a, edge_b, seg_a_idx, seg_b_idx, path_a, path_b, flows_by_id):
                        continue
                    invalid.add((edge_a, edge_b))
                    break
            if (edge_a, edge_b) in invalid:
                    break
    return invalid


def count_edge_crossings(edge_id, candidate_path, edge_paths, flows_by_id=None):
    crossings = 0
    for other_edge_id, other_path in edge_paths.items():
        if other_edge_id == edge_id:
            continue
        found = False
        segments_a = edge_segments(candidate_path)
        segments_b = edge_segments(other_path)
        for seg_a_idx, seg_a in enumerate(segments_a):
            for seg_b_idx, seg_b in enumerate(segments_b):
                if segment_intersection_invalid(seg_a, seg_b):
                    if is_shared_terminal_overlap(edge_id, other_edge_id, seg_a_idx, seg_b_idx, candidate_path, other_path, flows_by_id):
                        continue
                    crossings += 1
                    found = True
                    break
            if found:
                break
    return crossings


def prune_channels(channels, low, high, margin=120, outer_count=2, limit=8):
    ordered = sorted(set(channels))
    inside = [value for value in ordered if low - margin <= value <= high + margin]
    outside_left = [value for value in ordered if value < low - margin][-outer_count:]
    outside_right = [value for value in ordered if value > high + margin][:outer_count]
    pruned = sorted(set(inside + outside_left + outside_right))
    return pruned[:limit]


def default_label_rect(node_type, rect, lw, lh, alternate=False, thresholds=None):
    x, y, w, h = rect
    lx = snap(x + (w - lw) / 2.0)
    zone_gap = threshold_value(thresholds, "label_zone_gap")
    alternate_gap = threshold_value(thresholds, "label_zone_alternate_gap")
    if node_type in GATEWAY_TYPES:
        ly = y + h + zone_gap if alternate else y - (lh + alternate_gap)
        return [lx, snap(ly), lw, lh]
    ly = y - (lh + alternate_gap) if alternate else y + h + zone_gap
    return [lx, snap(ly), lw, lh]


def label_candidate_rects(node_type, rect, current_rect, baseline_rect=None, budget=80, thresholds=None):
    lw, lh = current_rect[2], current_rect[3]
    candidates = []
    if baseline_rect is not None:
        candidates.append([baseline_rect[0], baseline_rect[1], lw, lh])
    candidates.append([current_rect[0], current_rect[1], lw, lh])

    primary = default_label_rect(node_type, rect, lw, lh, alternate=False, thresholds=thresholds)
    alternate = default_label_rect(node_type, rect, lw, lh, alternate=True, thresholds=thresholds)
    candidates.append(primary)
    candidates.append(alternate)

    shift_step = threshold_value(thresholds, "label_conflict_shift_step")
    shift_levels = threshold_value(thresholds, "label_conflict_shift_levels")
    for base in (primary, alternate):
        for shift in range(shift_step, shift_step * shift_levels + 1, shift_step):
            candidates.append([base[0], snap(base[1] - shift), lw, lh])
            candidates.append([base[0], snap(base[1] + shift), lw, lh])

    uniq = []
    seen = set()
    for candidate in candidates:
        key = tuple(candidate)
        if key in seen:
            continue
        seen.add(key)
        if baseline_rect is not None and rect_distance(candidate, baseline_rect) > budget:
            continue
        uniq.append(candidate)
    return uniq


def step_toward(current, target, delta=20):
    if current < target:
        return min(current + delta, target)
    if current > target:
        return max(current - delta, target)
    return current


def rect_overlap_count(candidate_rect, avoid_rects, pad=0):
    return sum(1 for rect in avoid_rects if rect_intersect(candidate_rect, rect, pad=pad))


def within_budget(candidate_rect, baseline_rect, budget):
    if baseline_rect is None:
        return True
    return rect_distance(candidate_rect, baseline_rect) <= budget


def apply_separation(rect, vector):
    x, y, w, h = rect
    dx, dy = vector
    return (snap(x + dx), snap(y + dy), w, h)


def compute_separation_vector(rect_a, rect_b, min_gap):
    ax, ay, aw, ah = rect_a
    bx, by, bw, bh = rect_b

    options = []
    move_left = (bx - min_gap - aw) - ax
    move_right = (bx + bw + min_gap) - ax
    move_up = (by - min_gap - ah) - ay
    move_down = (by + bh + min_gap) - ay

    for dx, dy in ((move_left, 0), (move_right, 0), (0, move_up), (0, move_down)):
        candidate = apply_separation(rect_a, (dx, dy))
        if not rect_intersect(candidate, rect_b, pad=min_gap):
            options.append((snap(dx), snap(dy), abs(dx) + abs(dy)))

    if not options:
        return (0, 0)
    dx, dy, _ = min(options, key=lambda item: item[2])
    return (dx, dy)


def offset_from_canonical(canonical_rect, blocker_rect, min_gap):
    return apply_separation(canonical_rect, compute_separation_vector(canonical_rect, blocker_rect, min_gap))


def find_all_overlaps(rects, min_gap=0):
    overlaps = []
    node_ids = list(rects.keys())
    for idx, left in enumerate(node_ids):
        for right in node_ids[idx + 1:]:
            if rect_intersect(rects[left], rects[right], pad=min_gap):
                overlaps.append((left, right))
    return overlaps


def pick_mover(id_a, id_b, rects, canonical, existing_rects):
    def rank(nid):
        return (
            nid in existing_rects,
            rect_distance(rects[nid], canonical[nid]),
            rects[nid][0],
            rects[nid][1],
            nid,
        )

    return max((id_a, id_b), key=rank)


def nudge_rect_toward(current_rect, target_rect, baseline_rect=None, budget=120, avoid_rects=None, clearance=20):
    x, y, w, h = current_rect
    tx, ty, _, _ = target_rect
    avoid_rects = list(avoid_rects or [])
    candidates = [
        (snap(step_toward(x, tx)), snap(step_toward(y, ty)), w, h),
        (snap(step_toward(x, tx)), y, w, h),
        (x, snap(step_toward(y, ty)), w, h),
    ]

    for bx, by, bw, bh in avoid_rects:
        if not rect_intersect(current_rect, (bx, by, bw, bh), pad=0):
            continue
        candidates.extend(
            [
                (snap(bx - w - clearance), y, w, h),
                (snap(bx + bw + clearance), y, w, h),
                (x, snap(by - h - clearance), w, h),
                (x, snap(by + bh + clearance), w, h),
                (snap(bx - w - clearance), snap(by - h - clearance), w, h),
                (snap(bx + bw + clearance), snap(by + bh + clearance), w, h),
            ]
        )

    candidates.extend(
        [
            (x, snap(y - 20), w, h),
            (x, snap(y + 20), w, h),
            (snap(x - 20), y, w, h),
            (snap(x + 20), y, w, h),
        ]
    )

    current_score = (
        rect_overlap_count(current_rect, avoid_rects, pad=0),
        rect_distance(current_rect, target_rect),
        rect_distance(current_rect, baseline_rect) if baseline_rect is not None else 0,
        0,
    )
    best = current_rect
    best_score = current_score
    seen = {current_rect}
    for candidate in candidates:
        candidate = (snap(candidate[0]), snap(candidate[1]), w, h)
        if candidate in seen:
            continue
        seen.add(candidate)
        if baseline_rect is not None and rect_distance(candidate, baseline_rect) > budget:
            continue
        score = (
            rect_overlap_count(candidate, avoid_rects, pad=0),
            rect_distance(candidate, target_rect),
            rect_distance(candidate, baseline_rect) if baseline_rect is not None else 0,
            rect_distance(candidate, current_rect),
        )
        if score < best_score:
            best = candidate
            best_score = score
    return best


def initial_route(srect, trect, src_lane, tgt_lane, thresholds=None):
    sr = anchor(srect, "right")
    sl = anchor(srect, "left")
    st = anchor(srect, "top")
    sb = anchor(srect, "bottom")
    tl = anchor(trect, "left")
    tr = anchor(trect, "right")
    tt = anchor(trect, "top")
    tb = anchor(trect, "bottom")

    same_lane_knee_offset = threshold_value(thresholds, "edge_route_same_lane_knee_offset")
    vertical_mid_offset = threshold_value(thresholds, "edge_route_vertical_mid_offset")
    horizontal_mid_offset = threshold_value(thresholds, "edge_route_horizontal_mid_offset")

    if src_lane == tgt_lane and srect[0] + srect[2] <= trect[0]:
        knee_x = sr[0] + same_lane_knee_offset
        return dedupe_points([sr, (knee_x, sr[1]), (knee_x, tl[1]), tl])

    if tgt_lane > src_lane:
        mid_y = sb[1] + vertical_mid_offset
        return dedupe_points([sb, (sb[0], mid_y), (tt[0], mid_y), tt])

    if tgt_lane < src_lane:
        mid_y = st[1] - vertical_mid_offset
        return dedupe_points([st, (st[0], mid_y), (tb[0], mid_y), tb])

    if trect[0] + trect[2] <= srect[0]:
        knee_x = sl[0] - same_lane_knee_offset
        return dedupe_points([sl, (knee_x, sl[1]), (knee_x, tr[1]), tr])

    mid_x = max(sr[0], tl[0]) + horizontal_mid_offset
    return dedupe_points([sr, (mid_x, sr[1]), (mid_x, tl[1]), tl])


def route_with_outer_channel(srect, trect, outer_y, channel_x):
    sr = anchor(srect, "right")
    tl = anchor(trect, "left")
    return dedupe_points([
        sr,
        (sr[0], outer_y),
        (channel_x, outer_y),
        (channel_x, tl[1]),
        tl,
    ])


def route_via_h_channel(srect, trect, source_side, target_side, y_channel):
    s = anchor(srect, source_side)
    t = anchor(trect, target_side)
    return dedupe_points([s, (s[0], y_channel), (t[0], y_channel), t])


def route_via_v_channel(srect, trect, source_side, target_side, x_channel):
    s = anchor(srect, source_side)
    t = anchor(trect, target_side)
    return dedupe_points([s, (x_channel, s[1]), (x_channel, t[1]), t])


def route_via_yx_channels(srect, trect, source_side, target_side, y_channel, x_channel):
    s = anchor(srect, source_side)
    t = anchor(trect, target_side)
    return dedupe_points([s, (s[0], y_channel), (x_channel, y_channel), (x_channel, t[1]), t])


def route_via_xy_channels(srect, trect, source_side, target_side, x_channel, y_channel):
    s = anchor(srect, source_side)
    t = anchor(trect, target_side)
    return dedupe_points([s, (x_channel, s[1]), (x_channel, y_channel), (t[0], y_channel), t])


def edge_channel_candidates(srect, trect, base, ideal, base_x_channels, base_y_channels, thresholds=None):
    sx, sy = anchor(srect, "right")
    tx, ty = anchor(trect, "left")
    pair_min_x = min(srect[0], trect[0])
    pair_max_x = max(srect[0] + srect[2], trect[0] + trect[2])
    pair_min_y = min(srect[1], trect[1])
    pair_max_y = max(srect[1] + srect[3], trect[1] + trect[3])

    minor_offset = threshold_value(thresholds, "edge_reroute_channel_minor_offset")
    major_offset = threshold_value(thresholds, "edge_reroute_channel_major_offset")
    channel_margin = threshold_value(thresholds, "edge_reroute_channel_margin")
    outer_count = threshold_value(thresholds, "edge_reroute_outer_count")
    channel_limit = threshold_value(thresholds, "edge_reroute_channel_limit")
    local_x = {
        coord(value)
        for anchor_x in (sx, tx)
        for value in (anchor_x - major_offset, anchor_x - minor_offset, anchor_x, anchor_x + minor_offset, anchor_x + major_offset)
    }
    local_y = {
        coord(value)
        for anchor_y in (sy, ty)
        for value in (anchor_y - major_offset, anchor_y - minor_offset, anchor_y, anchor_y + minor_offset, anchor_y + major_offset)
    }
    x_candidates = set(base_x_channels) | local_x | {pt[0] for pt in base} | {pt[0] for pt in ideal}
    y_candidates = set(base_y_channels) | local_y | {pt[1] for pt in base} | {pt[1] for pt in ideal}
    x_channels = sorted(
        prune_channels(x_candidates, pair_min_x, pair_max_x, margin=channel_margin, outer_count=outer_count, limit=channel_limit),
        key=lambda x: (min(abs(x - sx), abs(x - tx)), abs(x - tx)),
    )
    y_channels = sorted(
        prune_channels(y_candidates, pair_min_y, pair_max_y, margin=channel_margin, outer_count=outer_count, limit=channel_limit),
        key=lambda y: (min(abs(y - sy), abs(y - ty)), abs(y - ty)),
    )
    return x_channels, y_channels


def build_edge_candidates(srect, trect, base, ideal, x_channels, y_channels):
    candidates = [(base, "baseline"), (ideal, "ideal")]
    source_sides = ("right", "bottom", "top", "left")
    target_sides = ("left", "top", "bottom", "right")

    for ych in y_channels:
        for ss in source_sides:
            for ts in target_sides:
                candidates.append((route_via_h_channel(srect, trect, ss, ts, ych), f"h@{ych}:{ss}->{ts}"))

    for xch in x_channels:
        for ss in source_sides:
            for ts in target_sides:
                candidates.append((route_via_v_channel(srect, trect, ss, ts, xch), f"v@{xch}:{ss}->{ts}"))

    for ych in y_channels:
        for xch in x_channels:
            for ss in source_sides:
                for ts in target_sides:
                    candidates.append((route_via_yx_channels(srect, trect, ss, ts, ych, xch), f"yx@{ych},{xch}:{ss}->{ts}"))
                    candidates.append((route_via_xy_channels(srect, trect, ss, ts, xch, ych), f"xy@{xch},{ych}:{ss}->{ts}"))

    uniq = []
    seen = set()
    for pts, tag in candidates:
        normalized = orthogonalize_path(pts)
        key = tuple(normalized)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((normalized, tag))
    return uniq


def score_edge_candidate(
    fid,
    pts,
    src,
    tgt,
    rects,
    items,
    edge_paths,
    baseline_path,
    lane,
    nodes,
    flows_by_id=None,
    thresholds=None,
):
    pts = orthogonalize_path(pts)
    baseline_path = orthogonalize_path(baseline_path or [])
    hits = path_collision_items(pts, src, tgt, items, pad=threshold_value(thresholds, "edge_reroute_collision_padding"))
    crossings = count_edge_crossings(fid, pts, edge_paths, flows_by_id=flows_by_id)
    anchor_issues = path_anchor_mismatches(pts, rects[src], rects[tgt])
    endpoint_direction = path_endpoint_direction_violations(pts, rects[src], rects[tgt])
    quality_issues = path_quality_violations(pts, thresholds=thresholds) + endpoint_direction
    long_horizontal_penalty = path_long_horizontal_segment_penalty(pts, thresholds=thresholds)
    gateway_penalty = gateway_anchor_preference_penalty(src, tgt, pts, rects, lane, nodes)
    score = (
        len(hits),
        crossings,
        anchor_issues,
        quality_issues,
        long_horizontal_penalty,
        gateway_penalty,
        path_displacement(pts, baseline_path),
        path_bends(pts),
        path_manhattan_length(pts),
    )
    return score, hits, crossings, anchor_issues, quality_issues


def choose_best_edge_path(
    fid,
    src,
    tgt,
    rects,
    lane,
    nodes,
    items,
    edge_paths,
    baseline_edge_paths,
    base_x_channels,
    base_y_channels,
    flows_by_id=None,
    thresholds=None,
):
    fallback = orthogonalize_path(
        baseline_edge_paths.get(fid, initial_route(rects[src], rects[tgt], lane[src], lane[tgt], thresholds=thresholds))
    )
    base = orthogonalize_path(edge_paths.get(fid, fallback))
    baseline_path = orthogonalize_path(baseline_edge_paths.get(fid, base))
    ideal = orthogonalize_path(initial_route(rects[src], rects[tgt], lane[src], lane[tgt], thresholds=thresholds))
    x_channels, y_channels = edge_channel_candidates(
        rects[src],
        rects[tgt],
        base,
        ideal,
        base_x_channels,
        base_y_channels,
        thresholds=thresholds,
    )
    candidates = build_edge_candidates(rects[src], rects[tgt], base, ideal, x_channels, y_channels)

    best_path = base
    best_tag = "baseline"
    best_score, best_hits, best_crossings, best_anchor_issues, best_quality_issues = score_edge_candidate(
        fid,
        base,
        src,
        tgt,
        rects,
        items,
        edge_paths,
        baseline_path,
        lane,
        nodes,
        flows_by_id=flows_by_id,
        thresholds=thresholds,
    )

    for pts, tag in candidates:
        score, hits, crossings, anchor_issues, quality_issues = score_edge_candidate(
            fid,
            pts,
            src,
            tgt,
            rects,
            items,
            edge_paths,
            baseline_path,
            lane,
            nodes,
            flows_by_id=flows_by_id,
            thresholds=thresholds,
        )
        if score < best_score:
            best_path = orthogonalize_path(pts)
            best_tag = tag
            best_score = score
            best_hits = hits
            best_crossings = crossings
            best_anchor_issues = anchor_issues
            best_quality_issues = quality_issues
            if score[0] == 0 and score[1] == 0 and score[2] == 0 and score[3] == 0:
                break

    return {
        "path": best_path,
        "tag": best_tag,
        "score": best_score,
        "hits": best_hits,
        "crossings": best_crossings,
        "anchor_issues": best_anchor_issues,
        "quality_issues": best_quality_issues,
    }


def compute_slots(nodes, depth, lane):
    buckets = defaultdict(list)
    for nid in nodes:
        buckets[(depth[nid], lane[nid])].append(nid)
    slot = {}
    for key, ids in buckets.items():
        for index, nid in enumerate(sorted(ids)):
            slot[nid] = index
    return slot


def compute_column_widths(nodes, depth, dims):
    col_width = defaultdict(int)
    for nid in nodes:
        col_width[depth[nid]] = max(col_width[depth[nid]], dims[nid][0])
    return col_width


def compute_column_positions(col_width, gap_x, margin_x):
    col_left = {}
    cursor = margin_x
    max_depth = max(col_width.keys()) if col_width else -1
    for depth_value in range(max_depth + 1):
        col_left[depth_value] = cursor
        cursor += col_width[depth_value] + gap_x
    return col_left


def compute_lane_heights(nodes, lane, slot, dims, subrow_gap):
    lane_height = {}
    for lane_id in sorted(set(lane.values())):
        lane_nodes = [nid for nid in nodes if lane[nid] == lane_id]
        max_h = max(dims[nid][1] for nid in lane_nodes)
        max_slot = max(slot[nid] for nid in lane_nodes)
        lane_height[lane_id] = max_h + max_slot * subrow_gap
    return lane_height


def compute_lane_positions(lane_height, gap_y, margin_y):
    lane_top = {}
    cursor = margin_y
    for lane_id in sorted(lane_height.keys()):
        lane_top[lane_id] = cursor
        cursor += lane_height[lane_id] + gap_y
    return lane_top


def compute_canonical_rects(nodes, depth, lane, slot, dims, gap_x, gap_y, subrow_gap, margin_x, margin_y):
    col_width = compute_column_widths(nodes, depth, dims)
    col_left = compute_column_positions(col_width, gap_x, margin_x)
    lane_height = compute_lane_heights(nodes, lane, slot, dims, subrow_gap)
    lane_top = compute_lane_positions(lane_height, gap_y, margin_y)

    canonical = {}
    for nid in nodes:
        w, h = dims[nid]
        x = col_left[depth[nid]] + (col_width[depth[nid]] - w) // 2
        y = lane_top[lane[nid]] + slot[nid] * subrow_gap
        canonical[nid] = (snap(x), snap(y), w, h)
    return canonical, col_width, col_left, lane_height, lane_top


def estimate_container_outer_dims(
    nodes,
    flows,
    lane,
    dims,
    gap_x,
    gap_y,
    subrow_gap,
    margin_x,
    margin_y,
    default_dims,
    thresholds=None,
):
    if not nodes:
        return default_dims
    depth = compute_depths(nodes, flows)
    slot = compute_slots(nodes, depth, lane)
    canonical, _, _, _, _ = compute_canonical_rects(
        nodes, depth, lane, slot, dims, gap_x, gap_y, subrow_gap, margin_x, margin_y
    )
    max_right = max(rect[0] + rect[2] for rect in canonical.values())
    max_bottom = max(rect[1] + rect[3] for rect in canonical.values())
    container_padding_x = threshold_value(thresholds, "container_padding_x")
    container_padding_y = threshold_value(thresholds, "container_padding_y")
    width = max(default_dims[0], snap(max_right + margin_x + container_padding_x))
    height = max(default_dims[1], snap(max_bottom + container_padding_y))
    return (width, height)


def build_subprocess_layout_spec(subprocess_element, process_id, process_lane_map, external_lane_map, type_config, nested_thresholds):
    nodes, flows, nested_elements = collect_direct_container_graph(subprocess_element, process_id)
    nested_specs = {}
    dims = {}

    for nid, meta in nodes.items():
        if meta["type"] in SUBPROCESS_LIKE_TYPES:
            nested_specs[nid] = build_subprocess_layout_spec(
                nested_elements[nid],
                process_id,
                process_lane_map,
                external_lane_map,
                type_config,
                nested_thresholds,
            )
            default_dims = node_dims(meta["type"], meta["name"], type_config)
            child_dims = nested_specs[nid]["outer_dims"]
            dims[nid] = (max(default_dims[0], child_dims[0]), max(default_dims[1], child_dims[1]))
        else:
            dims[nid] = node_dims(meta["type"], meta["name"], type_config)

    lane = resolve_lane_assignments(nodes, process_lane_map, external_lane_map, {})
    outer_dims = estimate_container_outer_dims(
        nodes,
        flows,
        lane,
        dims,
        gap_x=nested_thresholds["gap_x"],
        gap_y=nested_thresholds["gap_y"],
        subrow_gap=nested_thresholds["subrow_gap"],
        margin_x=nested_thresholds["margin_x"],
        margin_y=nested_thresholds["margin_y"],
        default_dims=node_dims(tag_name(subprocess_element), subprocess_element.get("name", ""), type_config),
        thresholds=nested_thresholds,
    )

    return {
        "container_id": subprocess_element.get("id"),
        "process_id": process_id,
        "nodes": nodes,
        "flows": flows,
        "lane": lane,
        "dims": dims,
        "subprocess_specs": nested_specs,
        "outer_dims": outer_dims,
        "expanded": bool(nodes),
    }


def flatten_subprocess_specs(specs, flat=None):
    flat = flat or {}
    for subprocess_id, spec in specs.items():
        flat[subprocess_id] = spec
        flatten_subprocess_specs(spec["subprocess_specs"], flat)
    return flat


def resolve_all_overlaps(rects, canonical, existing_rects, budget, min_gap, max_passes=10):
    rects = {nid: tuple(rect) for nid, rect in rects.items()}
    for _ in range(max_passes):
        overlaps = find_all_overlaps(rects, min_gap=min_gap)
        if not overlaps:
            return rects

        progressed = False
        for id_a, id_b in overlaps:
            mover = pick_mover(id_a, id_b, rects, canonical, existing_rects)
            stayer = id_b if mover == id_a else id_a

            canonical_candidate = canonical[mover]
            if not rect_intersect(canonical_candidate, rects[stayer], pad=min_gap) and within_budget(
                canonical_candidate, existing_rects.get(mover), budget
            ):
                rects[mover] = canonical_candidate
                progressed = True
                continue

            separation = compute_separation_vector(rects[mover], rects[stayer], min_gap)
            if separation != (0, 0):
                candidate = apply_separation(rects[mover], separation)
                if within_budget(candidate, existing_rects.get(mover), budget):
                    rects[mover] = candidate
                    progressed = True
                    continue

            offset_candidate = offset_from_canonical(canonical[mover], rects[stayer], min_gap)
            if within_budget(offset_candidate, existing_rects.get(mover), budget):
                rects[mover] = offset_candidate
                progressed = True
                continue

            if mover in existing_rects:
                rects[mover] = canonical[mover]
                progressed = True

        if not progressed:
            break

    overlaps = find_all_overlaps(rects, min_gap=min_gap)
    if overlaps:
        raise LayoutError(f"Cannot resolve {len(overlaps)} overlaps")
    return rects


def find_disallowed_overlaps(rects, nodes=None, min_gap=0):
    overlaps = find_all_overlaps(rects, min_gap=min_gap)
    if not nodes:
        return overlaps
    return [pair for pair in overlaps if not is_allowed_shape_overlap(pair[0], pair[1], nodes)]


def constraint_placement(
    nodes,
    depth,
    lane,
    slot,
    dims,
    existing_rects,
    gap_x,
    gap_y,
    subrow_gap,
    margin_x,
    margin_y,
    max_shape_shift,
):
    canonical_rects, col_width, col_left, lane_height, lane_top = compute_canonical_rects(
        nodes, depth, lane, slot, dims, gap_x, gap_y, subrow_gap, margin_x, margin_y
    )
    rects = {}
    for nid in nodes:
        rects[nid] = tuple(existing_rects[nid]) if nid in existing_rects else canonical_rects[nid]

    rects = resolve_all_overlaps(rects, canonical_rects, existing_rects, max_shape_shift, min_gap=0)
    return rects, canonical_rects, col_width, col_left, lane_height, lane_top


def label_collision_count(candidate, label_id, items, thresholds=None):
    padding = threshold_value(thresholds, "label_conflict_padding")
    total = 0
    for kind, oid, rect in items:
        if kind == "label" and oid == label_id:
            continue
        if rect_intersect(tuple(candidate), rect, pad=padding):
            total += 1
    return total


def place_label_guaranteed(nid, node_type, rect, current_rect, baseline_rect, items, initial_budget=80, max_budget=200, thresholds=None):
    best = list(current_rect)
    best_collisions = label_collision_count(best, nid, items, thresholds=thresholds)
    best_distance = rect_distance(best, baseline_rect) if baseline_rect is not None else 0
    budget_step = threshold_value(thresholds, "label_conflict_budget_step")
    resolved_max_budget = max(max_budget, initial_budget)

    for budget in range(initial_budget, resolved_max_budget + 1, budget_step):
        for candidate in label_candidate_rects(
            node_type,
            rect,
            current_rect,
            baseline_rect=baseline_rect,
            budget=budget,
            thresholds=thresholds,
        ):
            collisions = label_collision_count(candidate, nid, items, thresholds=thresholds)
            distance = rect_distance(candidate, baseline_rect) if baseline_rect is not None else 0
            score = (collisions, distance)
            if score < (best_collisions, best_distance):
                best = list(candidate)
                best_collisions = collisions
                best_distance = distance
                if collisions == 0:
                    return best, 0, budget
    return best, best_collisions, resolved_max_budget


def place_all_labels(nodes, rects, existing_labels, initial_budget=80, max_budget=200, thresholds=None):
    label_rects = {}
    warnings = []
    max_budget = max(max_budget, threshold_value(thresholds, "label_conflict_max_budget"))

    for nid, meta in nodes.items():
        if meta["type"] not in (GATEWAY_TYPES | EVENT_TYPES):
            continue
        if nid not in existing_labels and not (meta["name"] or "").strip():
            continue

        if nid in existing_labels:
            lx, ly, lw, lh = existing_labels[nid]
            current = [snap(lx), snap(ly), snap(lw), snap(lh)]
        else:
            lw, lh = label_dims(meta["name"])
            current = default_label_rect(meta["type"], rects[nid], lw, lh, alternate=False, thresholds=thresholds)

        baseline = tuple(current)
        items = build_rect_items(rects, label_rects)
        placed, collisions, used_budget = place_label_guaranteed(
            nid,
            meta["type"],
            rects[nid],
            current,
            baseline,
            items,
            initial_budget=initial_budget,
            max_budget=max_budget,
            thresholds=thresholds,
        )
        label_rects[nid] = placed
        if collisions > 0:
            warnings.append(f"label:{nid} unresolved_collisions={collisions}")
        elif used_budget > initial_budget:
            warnings.append(f"label:{nid} budget_expanded_to={used_budget}")
    return label_rects, warnings


def build_rect_items(rects, label_rects):
    items = [("shape", nid, tuple(rect)) for nid, rect in rects.items()]
    items.extend(("label", nid, tuple(rect)) for nid, rect in label_rects.items())
    return items


def build_edge_corridor_items(edge_paths, thickness=10):
    items = []
    half = max(1, thickness // 2)
    for edge_id, path in edge_paths.items():
        for index, (p1, p2) in enumerate(edge_segments(path)):
            if p1[0] == p2[0]:
                x = min(p1[0], p2[0]) - half
                y = min(p1[1], p2[1])
                w = thickness
                h = abs(p2[1] - p1[1])
            else:
                x = min(p1[0], p2[0])
                y = min(p1[1], p2[1]) - half
                w = abs(p2[0] - p1[0])
                h = thickness
            items.append(("edge", f"{edge_id}:{index}", (coord(x), coord(y), coord(max(w, 1)), coord(max(h, 1)))))
    return items


def build_conflict_items(rects, label_rects, edge_paths, thresholds=None):
    items = build_rect_items(rects, label_rects)
    items.extend(
        build_edge_corridor_items(
            edge_paths,
            thickness=threshold_value(thresholds, "edge_corridor_thickness"),
        )
    )
    return items


def collect_conflict_label_ids(issues, label_rects):
    label_ids = set()
    for issue in issues:
        for candidate in (issue.get("element_id"), issue.get("secondary_element_id")):
            if candidate in label_rects:
                label_ids.add(candidate)
    return label_ids


def reclaim_node_space(rects, label_rects, issues, existing_rects, thresholds):
    moved_nodes = []
    reclaim_clearance = threshold_value(thresholds, "conflict_local_reclaim_clearance")
    reclaim_passes = threshold_value(thresholds, "conflict_local_reclaim_max_passes")

    for _ in range(reclaim_passes):
        progress = False
        for issue in issues:
            if issue["code"] != "label_shape_overlap":
                continue
            label_id = issue["element_id"]
            blocker_id = issue["secondary_element_id"]
            if label_id not in label_rects or blocker_id not in rects:
                continue
            blocker_rect = rects[blocker_id]
            label_rect = tuple(label_rects[label_id])
            candidate = apply_separation(blocker_rect, compute_separation_vector(blocker_rect, label_rect, reclaim_clearance))
            if candidate == blocker_rect:
                continue
            if not within_budget(candidate, existing_rects.get(blocker_id), threshold_value(thresholds, "max_shape_shift")):
                continue
            if rect_intersect(candidate, label_rect, pad=reclaim_clearance):
                continue
            dx = candidate[0] - blocker_rect[0]
            dy = candidate[1] - blocker_rect[1]
            rects[blocker_id] = candidate
            if blocker_id in label_rects:
                label_rects[blocker_id] = list(shift_rect(tuple(label_rects[blocker_id]), dx=dx, dy=dy))
            moved_nodes.append(blocker_id)
            progress = True
        if not progress:
            break
    return rects, label_rects, sorted(set(moved_nodes))


def sort_flows_by_priority(flows, depth, lane):
    def priority(flow):
        src = flow["source"]
        tgt = flow["target"]
        same_lane = int(lane[src] == lane[tgt])
        forward = int(depth[tgt] >= depth[src])
        back_edge = int(depth[tgt] < depth[src])
        return (-forward, -same_lane, back_edge, depth[src], depth[tgt], flow["id"])

    return sorted(flows, key=priority)


def routing_channels(items, thresholds=None):
    min_left = min(r[0] for _, _, r in items)
    min_top = min(r[1] for _, _, r in items)
    max_right = max(r[0] + r[2] for _, _, r in items)
    max_bottom = max(r[1] + r[3] for _, _, r in items)

    outer_offset = threshold_value(thresholds, "edge_reroute_outer_offset")
    major_offset = threshold_value(thresholds, "edge_reroute_channel_major_offset")
    channel_limit = threshold_value(thresholds, "edge_reroute_channel_limit")
    collision_padding = threshold_value(thresholds, "edge_reroute_collision_padding")

    top_channels = [snap(min_top - outer_offset - i * major_offset) for i in range(channel_limit // 2)]
    bottom_channels = [snap(max_bottom + outer_offset + i * major_offset) for i in range(channel_limit // 2)]
    left_channels = [snap(min_left - outer_offset - i * major_offset) for i in range(channel_limit // 2)]
    right_channels = [snap(max_right + outer_offset + i * major_offset) for i in range(channel_limit // 2)]

    base_x_channels = set(left_channels + right_channels)
    base_y_channels = set(top_channels + bottom_channels)
    for _, _, r in items:
        rx, ry, rw, rh = r
        base_x_channels.add(snap(rx - collision_padding * 10))
        base_x_channels.add(snap(rx + rw + collision_padding * 10))
        base_y_channels.add(snap(ry - collision_padding * 10))
        base_y_channels.add(snap(ry + rh + collision_padding * 10))
    return sorted(base_x_channels), sorted(base_y_channels)


def find_all_crossing_pairs(edge_paths, flows_by_id=None):
    return sorted(edge_edge_intersections(edge_paths, flows_by_id=flows_by_id))


def pick_reroute_target(edge_a, edge_b, edge_paths, flows_by_id=None):
    crossings_a = count_edge_crossings(edge_a, edge_paths[edge_a], edge_paths, flows_by_id=flows_by_id)
    crossings_b = count_edge_crossings(edge_b, edge_paths[edge_b], edge_paths, flows_by_id=flows_by_id)
    if crossings_a != crossings_b:
        return edge_a if crossings_a > crossings_b else edge_b
    bends_a = path_bends(edge_paths[edge_a])
    bends_b = path_bends(edge_paths[edge_b])
    if bends_a != bends_b:
        return edge_a if bends_a >= bends_b else edge_b
    return max(edge_a, edge_b)


def fanout_path_near_source(path, source_side, offset):
    if offset == 0 or len(path) < 4:
        return path

    new_path = [tuple(point) for point in path]
    if source_side in {"top", "bottom"}:
        if len(new_path) < 5:
            return path
        if not (new_path[0][0] == new_path[1][0] and new_path[1][1] == new_path[2][1]):
            return path
        old_x = new_path[2][0]
        new_x = coord(old_x + offset)
        for index in range(2, len(new_path) - 1):
            if new_path[index][0] == old_x:
                new_path[index] = (new_x, new_path[index][1])
            else:
                break
        return orthogonalize_path(dedupe_points(new_path))

    if source_side in {"left", "right"}:
        if len(new_path) < 5:
            return path
        if not (new_path[0][1] == new_path[1][1] and new_path[1][0] == new_path[2][0]):
            return path
        old_y = new_path[2][1]
        new_y = coord(old_y + offset)
        for index in range(2, len(new_path) - 1):
            if new_path[index][1] == old_y:
                new_path[index] = (new_path[index][0], new_y)
            else:
                break
        return orthogonalize_path(dedupe_points(new_path))

    return path


def fanout_shared_source_edges(flows, edge_paths, rects, thresholds=None):
    groups = defaultdict(list)
    for flow in flows:
        groups[flow["source"]].append(flow)

    actions = []
    for source_id, group in groups.items():
        if len(group) < 2:
            continue
        source_rect = rects[source_id]
        ordered = sorted(
            group,
            key=lambda flow: (
                rects[flow["target"]][1] + rects[flow["target"]][3] / 2.0,
                rects[flow["target"]][0],
                flow["id"],
            ),
        )
        center = len(ordered) - 1
        fanout_step = threshold_value(thresholds, "edge_branch_fanout_step")
        top_multiplier = threshold_value(thresholds, "edge_branch_fanout_top_multiplier")
        for index, flow in enumerate(ordered):
            offset = snap((index * 2 - center) * fanout_step)
            current = edge_paths[flow["id"]]
            source_side = infer_anchor_side(source_rect, current[0])
            if source_side == "top":
                offset = snap(-offset * top_multiplier)
            candidate = fanout_path_near_source(current, source_side, offset)
            if candidate != current:
                edge_paths[flow["id"]] = candidate
                actions.append(f"edge:{flow['id']} source_fanout={offset}")
    return edge_paths, actions


def fanin_path_near_target(path, target_side, offset):
    if offset == 0 or len(path) < 4:
        return path

    new_path = [tuple(point) for point in path]
    if target_side in {"top", "bottom"}:
        if len(new_path) < 5:
            return path
        if not (new_path[-1][0] == new_path[-2][0] and new_path[-2][1] == new_path[-3][1]):
            return path
        old_x = new_path[-3][0]
        new_x = coord(old_x + offset)
        for index in range(len(new_path) - 3, 0, -1):
            if new_path[index][0] == old_x:
                new_path[index] = (new_x, new_path[index][1])
            else:
                break
        return orthogonalize_path(dedupe_points(new_path))

    if target_side in {"left", "right"}:
        if len(new_path) < 4:
            return path
        if not (new_path[-1][1] == new_path[-2][1] and new_path[-2][0] == new_path[-3][0]):
            return path
        old_y = new_path[-3][1]
        new_y = coord(old_y + offset)
        for index in range(len(new_path) - 3, 0, -1):
            if new_path[index][1] == old_y:
                new_path[index] = (new_path[index][0], new_y)
            else:
                break
        return orthogonalize_path(dedupe_points(new_path))

    return path


def fanin_shared_target_edges(flows, edge_paths, rects, thresholds=None):
    groups = defaultdict(list)
    for flow in flows:
        groups[flow["target"]].append(flow)

    actions = []
    for target_id, group in groups.items():
        if len(group) < 2:
            continue
        target_rect = rects[target_id]
        ordered = sorted(
            group,
            key=lambda flow: (
                rects[flow["source"]][1] + rects[flow["source"]][3] / 2.0,
                rects[flow["source"]][0],
                flow["id"],
            ),
        )
        center = len(ordered) - 1
        fanout_step = threshold_value(thresholds, "edge_branch_fanout_step")
        top_multiplier = threshold_value(thresholds, "edge_branch_fanout_top_multiplier")
        for index, flow in enumerate(ordered):
            offset = snap((index * 2 - center) * fanout_step)
            current = edge_paths[flow["id"]]
            target_side = infer_anchor_side(target_rect, current[-1])
            if target_side == "top":
                offset = snap(-offset * top_multiplier)
            candidate = fanin_path_near_target(current, target_side, offset)
            if candidate != current:
                edge_paths[flow["id"]] = candidate
                actions.append(f"edge:{flow['id']} target_fanin={offset}")
    return edge_paths, actions


def minimize_crossings(edge_paths, flows_by_id, rects, label_rects, lane, nodes, baseline_edges, depth, max_passes=5, thresholds=None):
    items = build_rect_items(rects, label_rects)
    base_x_channels, base_y_channels = routing_channels(items, thresholds=thresholds)
    for _ in range(max_passes):
        crossing_pairs = find_all_crossing_pairs(edge_paths, flows_by_id=flows_by_id)
        if not crossing_pairs:
            return edge_paths, 0

        improved = 0
        for edge_a, edge_b in crossing_pairs:
            reroute_target = pick_reroute_target(edge_a, edge_b, edge_paths, flows_by_id=flows_by_id)
            flow = flows_by_id[reroute_target]
            temp_paths = {edge_id: path for edge_id, path in edge_paths.items() if edge_id != reroute_target}
            current_crossings = count_edge_crossings(reroute_target, edge_paths[reroute_target], temp_paths, flows_by_id=flows_by_id)
            best = choose_best_edge_path(
                reroute_target,
                flow["source"],
                flow["target"],
                rects,
                lane,
                nodes,
                items,
                temp_paths,
                baseline_edges,
                base_x_channels,
                base_y_channels,
                flows_by_id=flows_by_id,
                thresholds=thresholds,
            )
            if best["crossings"] < current_crossings and not best["hits"]:
                edge_paths[reroute_target] = best["path"]
                improved += 1
        if improved == 0:
            return edge_paths, len(find_all_crossing_pairs(edge_paths, flows_by_id=flows_by_id))
    return edge_paths, len(find_all_crossing_pairs(edge_paths, flows_by_id=flows_by_id))


def route_all_edges(flows, rects, label_rects, lane, baseline_edges, depth, nodes, thresholds=None):
    items = build_rect_items(rects, label_rects)
    base_x_channels, base_y_channels = routing_channels(items, thresholds=thresholds)
    sorted_flows = sort_flows_by_priority(flows, depth, lane)
    flows_by_id = {flow["id"]: flow for flow in flows}
    edge_paths = {}
    actions = []

    for flow in sorted_flows:
        fid = flow["id"]
        src = flow["source"]
        tgt = flow["target"]
        base = baseline_edges.get(fid, initial_route(rects[src], rects[tgt], lane[src], lane[tgt], thresholds=thresholds))
        edge_paths[fid] = base
        best = choose_best_edge_path(
            fid,
            src,
            tgt,
            rects,
            lane,
            nodes,
            items,
            edge_paths,
            baseline_edges,
            base_x_channels,
            base_y_channels,
            flows_by_id=flows_by_id,
            thresholds=thresholds,
        )
        edge_paths[fid] = best["path"]
        if best["path"] != base:
            actions.append(f"edge:{fid} reroute via {best['tag']}")

    edge_paths, fanout_actions = fanout_shared_source_edges(sorted_flows, edge_paths, rects, thresholds=thresholds)
    actions.extend(fanout_actions)
    edge_paths, fanin_actions = fanin_shared_target_edges(sorted_flows, edge_paths, rects, thresholds=thresholds)
    actions.extend(fanin_actions)

    edge_paths, remaining_crossings = minimize_crossings(
        edge_paths,
        flows_by_id,
        rects,
        label_rects,
        lane,
        nodes,
        baseline_edges,
        depth,
        max_passes=threshold_value(thresholds, "edge_reroute_max_passes"),
        thresholds=thresholds,
    )
    edge_paths, post_fanout_actions = fanout_shared_source_edges(sorted_flows, edge_paths, rects, thresholds=thresholds)
    actions.extend(post_fanout_actions)
    edge_paths, post_fanin_actions = fanin_shared_target_edges(sorted_flows, edge_paths, rects, thresholds=thresholds)
    actions.extend(post_fanin_actions)
    remaining_crossings = len(find_all_crossing_pairs(edge_paths, flows_by_id=flows_by_id))
    if remaining_crossings:
        actions.append(f"crossings_remaining={remaining_crossings}")
    for flow_id, path in list(edge_paths.items()):
        edge_paths[flow_id] = orthogonalize_path(path)
    return edge_paths, actions


def group_by_depth(rects, depth):
    groups = defaultdict(list)
    for nid in rects:
        if nid not in depth:
            continue
        groups[depth[nid]].append(nid)
    return groups


def group_by_lane(rects, lane):
    groups = defaultdict(list)
    for nid in rects:
        if nid not in lane:
            continue
        groups[lane[nid]].append(nid)
    return groups


def shift_nodes(rects, node_ids, dx=0, dy=0):
    for nid in node_ids:
        x, y, w, h = rects[nid]
        rects[nid] = (snap(x + dx), snap(y + dy), w, h)


def shift_labels(label_rects, node_ids, dx=0, dy=0):
    for nid in node_ids:
        if nid not in label_rects:
            continue
        lx, ly, lw, lh = label_rects[nid]
        label_rects[nid] = [snap(lx + dx), snap(ly + dy), lw, lh]


def expand_undersized_column_gaps(rects, label_rects, depth, gap_x):
    rects = {nid: tuple(rect) for nid, rect in rects.items()}
    label_rects = {nid: list(rect) for nid, rect in label_rects.items()}
    columns = group_by_depth(rects, depth)
    max_depth = max(depth.values()) if depth else -1
    expanded_steps = 0
    for depth_value in range(1, max_depth + 1):
        if not columns.get(depth_value) or not columns.get(depth_value - 1):
            continue
        prev_right = max(rects[nid][0] + rects[nid][2] for nid in columns[depth_value - 1])
        curr_left = min(rects[nid][0] for nid in columns[depth_value])
        actual_gap = curr_left - prev_right
        if actual_gap >= gap_x:
            continue
        shift = snap(gap_x - actual_gap)
        if shift <= 0:
            continue
        expanded_steps += 1
        for depth_shift in range(depth_value, max_depth + 1):
            node_ids = columns.get(depth_shift, [])
            shift_nodes(rects, node_ids, dx=shift)
            shift_labels(label_rects, node_ids, dx=shift)
    return rects, label_rects, expanded_steps


def compact_layout(rects, label_rects, edge_paths, flows, lane, depth, gap_x, gap_y, subrow_gap, margin, nodes=None, thresholds=None):
    tolerance_x = threshold_value(thresholds, "column_gap_violation_tolerance")
    tolerance_y = threshold_value(thresholds, "lane_gap_violation_tolerance")
    rects = {nid: tuple(rect) for nid, rect in rects.items()}
    label_rects = {nid: list(rect) for nid, rect in label_rects.items()}

    columns = group_by_depth(rects, depth)
    max_depth = max(depth.values()) if depth else -1
    for depth_value in range(1, max_depth + 1):
        if not columns.get(depth_value) or not columns.get(depth_value - 1):
            continue
        prev_right = max(rects[nid][0] + rects[nid][2] for nid in columns[depth_value - 1])
        curr_left = min(rects[nid][0] for nid in columns[depth_value])
        actual_gap = curr_left - prev_right
        if actual_gap > gap_x + tolerance_x:
            shift = snap(actual_gap - gap_x)
            for depth_shift in range(depth_value, max_depth + 1):
                node_ids = columns.get(depth_shift, [])
                shift_nodes(rects, node_ids, dx=-shift)
                shift_labels(label_rects, node_ids, dx=-shift)

    # Keep a single implementation for undersized-gap repair to avoid drift
    # between compaction and preserve conflict-resolution phases.
    rects, label_rects, _ = expand_undersized_column_gaps(rects, label_rects, depth, gap_x)

    lanes = group_by_lane(rects, lane)
    lane_ids = sorted(lanes.keys())
    for index in range(1, len(lane_ids)):
        prev_lane = lane_ids[index - 1]
        curr_lane = lane_ids[index]
        prev_bottom = max(rects[nid][1] + rects[nid][3] for nid in lanes[prev_lane])
        for nid in lanes[prev_lane]:
            if nid in label_rects:
                prev_bottom = max(prev_bottom, label_rects[nid][1] + label_rects[nid][3])
        curr_top = min(rects[nid][1] for nid in lanes[curr_lane])
        actual_gap = curr_top - prev_bottom
        if actual_gap > gap_y + tolerance_y:
            shift = snap(actual_gap - gap_y)
            for lane_shift in lane_ids[index:]:
                node_ids = lanes[lane_shift]
                shift_nodes(rects, node_ids, dy=-shift)
                shift_labels(label_rects, node_ids, dy=-shift)

    min_x = min(rect[0] for rect in rects.values())
    min_y = min(rect[1] for rect in rects.values())
    shift_x = margin - min_x if min_x < margin else 0
    shift_y = margin - min_y if min_y < margin else 0
    if shift_x or shift_y:
        shift_nodes(rects, list(rects.keys()), dx=shift_x, dy=shift_y)
        shift_labels(label_rects, list(rects.keys()), dx=shift_x, dy=shift_y)

    if find_disallowed_overlaps(rects, nodes=nodes, min_gap=0):
        raise LayoutError("Compaction introduced overlaps")
    return rects, label_rects


def shift_rect(rect, dx=0, dy=0):
    x, y, w, h = rect
    return (snap(x + dx), snap(y + dy), w, h)


def shift_path(points, dx=0, dy=0):
    return [(coord(x + dx), coord(y + dy)) for x, y in points]


def edge_di_completeness_summary(flows, edge_paths):
    flow_ids = {flow.get("id") for flow in flows if flow.get("id")}
    missing = sorted(flow_id for flow_id in flow_ids if flow_id not in edge_paths)
    short_waypoint = sorted(
        flow_id for flow_id in flow_ids if flow_id in edge_paths and len(edge_paths[flow_id]) < 2
    )
    return {
        "sequence_flow_count": len(flow_ids),
        "bpmn_edge_count": sum(1 for flow_id in flow_ids if flow_id in edge_paths),
        "edge_without_two_waypoints_count": len(short_waypoint),
        "missing_edge_ids": missing,
        "short_waypoint_edge_ids": short_waypoint,
        "ok": not missing and not short_waypoint,
    }


HARD_CONFLICT_CODES = {
    "shape_overlap",
    "label_shape_overlap",
    "label_label_overlap",
    "edge_shape_collision",
    "edge_label_collision",
    "edge_edge_intersection",
    "edge_anchor_mismatch",
    "edge_route_quality",
    "column_gap_violation",
    "lane_gap_violation",
}


def has_unresolved_hard_conflicts(metrics):
    return any(issue["code"] in HARD_CONFLICT_CODES for issue in metrics.get("typed_issues", []))


def resolve_conflicts_with_policy(
    mode,
    rects,
    label_rects,
    edge_paths,
    nodes,
    flows,
    lane,
    depth,
    canonical_rects,
    existing_rects,
    existing_labels,
    thresholds,
):
    actions = []
    current_metrics = verify_and_report(
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
    actions.append(f"phase_4a_local_branch_label_move: issues_before={len(current_metrics['typed_issues'])}")

    conflict_label_ids = collect_conflict_label_ids(current_metrics["typed_issues"], label_rects)
    moved_labels = 0
    if conflict_label_ids:
        for label_id in sorted(conflict_label_ids):
            if label_id not in label_rects:
                continue
            current = list(label_rects[label_id])
            baseline = tuple(existing_labels.get(label_id, current))
            items = build_conflict_items(rects, label_rects, edge_paths, thresholds=thresholds)
            placed, _, _ = place_label_guaranteed(
                label_id,
                nodes[label_id]["type"],
                rects[label_id],
                current,
                baseline,
                items,
                initial_budget=thresholds["max_label_shift"],
                max_budget=thresholds["label_conflict_max_budget"],
                thresholds=thresholds,
            )
            if placed != current:
                label_rects[label_id] = placed
                moved_labels += 1
    current_metrics = verify_and_report(
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
    actions.append(f"phase_4a_local_branch_label_move_result: moved_labels={moved_labels} issues_after={len(current_metrics['typed_issues'])}")

    reroute_actions = []
    if flows:
        edge_paths, reroute_actions = route_all_edges(
            flows,
            rects,
            label_rects,
            lane,
            edge_paths,
            depth,
            nodes,
            thresholds=thresholds,
        )
    current_metrics = verify_and_report(
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
    actions.append(f"phase_4b_edge_waypoint_adjustment: reroute_actions={len(reroute_actions)} issues_after={len(current_metrics['typed_issues'])}")
    actions.extend(reroute_actions)

    rects, label_rects, reclaimed_nodes = reclaim_node_space(
        rects,
        label_rects,
        current_metrics["typed_issues"],
        existing_rects,
        thresholds,
    )
    if reclaimed_nodes and flows:
        edge_paths, reclaim_reroute_actions = route_all_edges(
            flows,
            rects,
            label_rects,
            lane,
            edge_paths,
            depth,
            nodes,
            thresholds=thresholds,
        )
        actions.extend(reclaim_reroute_actions)
    current_metrics = verify_and_report(
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
    actions.append(
        f"phase_4c_local_node_space_reclaim: moved_nodes={len(reclaimed_nodes)} issues_after={len(current_metrics['typed_issues'])}"
    )

    if current_metrics.get("column_gap_violations", 0):
        rects, label_rects, expanded_steps = expand_undersized_column_gaps(
            rects,
            label_rects,
            depth,
            thresholds["gap_x"],
        )
        if expanded_steps:
            reroute_actions = []
            if flows:
                edge_paths, reroute_actions = route_all_edges(
                    flows,
                    rects,
                    label_rects,
                    lane,
                    edge_paths,
                    depth,
                    nodes,
                    thresholds=thresholds,
                )
            current_metrics = verify_and_report(
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
            actions.append(
                "phase_4c1_column_gap_normalization: "
                f"expanded_steps={expanded_steps} reroute_actions={len(reroute_actions)} "
                f"issues_after={len(current_metrics['typed_issues'])}"
            )
            actions.extend(reroute_actions)

    if has_unresolved_hard_conflicts(current_metrics):
        actions.append("phase_4d_fallback_escalation: unresolved_hard_conflicts")
        issue_codes = [
            issue.get("code")
            for issue in current_metrics.get("typed_issues", [])
            if issue.get("code") in HARD_CONFLICT_CODES
        ]
        issue_summary = ", ".join(sorted(set(code for code in issue_codes if code))) or "unknown"
        raise LayoutError(
            f"Unresolved hard conflicts after policy sequence in {mode}: {issue_summary}"
        )

    actions.append("phase_4d_fallback_escalation: clear")
    return rects, label_rects, edge_paths, current_metrics, actions


def run_layout_pipeline(
    mode,
    nodes,
    flows,
    lane,
    dims,
    shape_baseline,
    label_baseline,
    edge_baseline,
    thresholds,
    report_shape_baseline=None,
    report_label_baseline=None,
    budget_violation_severity="error",
):
    phase_actions = []
    gap_x = thresholds["gap_x"]
    gap_y = thresholds["gap_y"]
    subrow_gap = thresholds["subrow_gap"]
    margin_x = thresholds["margin_x"]
    margin_y = thresholds["margin_y"]
    max_shape_shift = thresholds["max_shape_shift"]
    max_label_shift = thresholds["max_label_shift"]
    compaction_margin = thresholds["compaction_margin"]
    report_shape_baseline = shape_baseline if report_shape_baseline is None else report_shape_baseline
    report_label_baseline = label_baseline if report_label_baseline is None else report_label_baseline
    depth = compute_depths(nodes, flows) if nodes else {}
    slot = compute_slots(nodes, depth, lane) if nodes else {}

    rects, canonical_rects, _, _, _, _ = constraint_placement(
        nodes,
        depth,
        lane,
        slot,
        dims,
        shape_baseline,
        gap_x,
        gap_y,
        subrow_gap,
        margin_x,
        margin_y,
        max_shape_shift,
    )
    rects, _ = attach_boundary_events(rects, nodes, baseline_rects=shape_baseline, thresholds=thresholds)
    phase_actions.append(f"phase_2_constraint_placement: shapes={len(rects)}")

    label_rects, label_notes = place_all_labels(
        nodes,
        rects,
        label_baseline,
        initial_budget=max_label_shift,
        max_budget=thresholds["label_conflict_max_budget"],
        thresholds=thresholds,
    )
    phase_actions.append(f"phase_3_label_placement: labels={len(label_rects)}")
    phase_actions.extend(label_notes)

    if flows:
        edge_paths, route_actions = route_all_edges(
            flows,
            rects,
            label_rects,
            lane,
            edge_baseline,
            depth,
            nodes,
            thresholds=thresholds,
        )
        phase_actions.append("phase_4_edge_routing")
        phase_actions.extend(route_actions)

        rects, label_rects, edge_paths, conflict_metrics, conflict_actions = resolve_conflicts_with_policy(
            mode,
            rects,
            label_rects,
            edge_paths,
            nodes,
            flows,
            lane,
            depth,
            canonical_rects,
            shape_baseline,
            label_baseline,
            thresholds,
        )
        phase_actions.extend(conflict_actions)

        rects, label_rects = compact_layout(
            rects,
            label_rects,
            edge_paths,
            flows,
            lane,
            depth,
            gap_x,
            gap_y,
            subrow_gap,
            compaction_margin,
            nodes=nodes,
            thresholds=thresholds,
        )
        rects, label_rects = attach_boundary_events(
            rects,
            nodes,
            baseline_rects=shape_baseline,
            label_rects=label_rects,
            thresholds=thresholds,
        )
        phase_actions.append("phase_5_compaction")

        edge_paths, reroute_actions = route_all_edges(
            flows,
            rects,
            label_rects,
            lane,
            edge_paths,
            depth,
            nodes,
            thresholds=thresholds,
        )
        phase_actions.append("phase_5_post_compaction_reroute")
        phase_actions.extend(reroute_actions)
    else:
        edge_paths = {}
        phase_actions.append("phase_4_edge_routing: skipped_no_flows")

    metrics = verify_and_report(
        rects,
        label_rects,
        edge_paths,
        flows,
        depth,
        lane,
        nodes,
        report_shape_baseline,
        report_label_baseline,
        max_shape_shift,
        max_label_shift,
        gap_x=gap_x,
        gap_y=gap_y,
        participant_lane_budget=thresholds["max_participant_lane_shift"],
        thresholds=thresholds,
        budget_violation_severity=budget_violation_severity,
    )

    return {
        "mode": mode,
        "rects": rects,
        "label_rects": label_rects,
        "edge_paths": edge_paths,
        "canonical_rects": canonical_rects,
        "metrics": metrics,
        "actions": phase_actions,
        "depth": depth,
        "slot": slot,
        "shape_baseline": dict(report_shape_baseline),
        "label_baseline": {nid: list(rect) for nid, rect in report_label_baseline.items()},
    }


def apply_nested_subprocess_layouts(
    subprocess_specs,
    rects,
    label_rects,
    edge_paths,
    nodes,
    flows,
    notes,
    nested_profile_name,
    nested_thresholds,
):
    if not subprocess_specs:
        return

    def visit(spec):
        subprocess_id = spec["container_id"]
        if subprocess_id not in rects or not spec["expanded"]:
            return

        local = run_layout_pipeline(
            nested_profile_name,
            spec["nodes"],
            spec["flows"],
            spec["lane"],
            spec["dims"],
            {},
            {},
            {},
            nested_thresholds,
        )

        dx, dy, _, _ = rects[subprocess_id]
        for nid, rect in local["rects"].items():
            rects[nid] = shift_rect(rect, dx=dx, dy=dy)
            nodes[nid] = spec["nodes"][nid]
        for nid, rect in local["label_rects"].items():
            label_rects[nid] = list(shift_rect(rect, dx=dx, dy=dy))
        for fid, path in local["edge_paths"].items():
            edge_paths[fid] = shift_path(path, dx=dx, dy=dy)
        flows.extend(spec["flows"])
        notes.append(f"subprocess:{subprocess_id} nested_layout nodes={len(local['rects'])} flows={len(local['edge_paths'])}")

        for child_spec in spec["subprocess_specs"].values():
            visit(child_spec)

    for spec in subprocess_specs.values():
        visit(spec)


def compute_column_gap_violations(rects, depth, lane, target_gap, tolerance):
    violations = 0
    columns = group_by_depth(rects, depth)
    sorted_depths = sorted(columns.keys())
    for left_depth, right_depth in zip(sorted_depths, sorted_depths[1:]):
        left_right = max(rects[nid][0] + rects[nid][2] for nid in columns[left_depth])
        right_left = min(rects[nid][0] for nid in columns[right_depth])
        gap = right_left - left_right
        if gap < target_gap or gap > target_gap + tolerance:
            violations += 1
    return violations


def compute_lane_gap_violations(rects, label_rects, lane, target_gap, tolerance):
    violations = 0
    lanes = group_by_lane(rects, lane)
    lane_ids = sorted(lanes.keys())
    for left, right in zip(lane_ids, lane_ids[1:]):
        prev_bottom = max(rects[nid][1] + rects[nid][3] for nid in lanes[left])
        for nid in lanes[left]:
            if nid in label_rects:
                prev_bottom = max(prev_bottom, label_rects[nid][1] + label_rects[nid][3])
        curr_top = min(rects[nid][1] for nid in lanes[right])
        gap = curr_top - prev_bottom
        if gap < target_gap or gap > target_gap + tolerance:
            violations += 1
    return violations


def compute_diagram_bbox(rects, label_rects, edge_paths):
    min_x = None
    min_y = None
    max_x = None
    max_y = None

    def include_point(x, y):
        nonlocal min_x, min_y, max_x, max_y
        if min_x is None:
            min_x = x
            min_y = y
            max_x = x
            max_y = y
            return
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        max_x = max(max_x, x)
        max_y = max(max_y, y)

    def include_rect(rect):
        if rect is None:
            return
        x, y, w, h = rect
        include_point(x, y)
        include_point(x + w, y + h)

    for rect in rects.values():
        include_rect(rect)
    for rect in label_rects.values():
        include_rect(rect)
    for points in edge_paths.values():
        for x, y in points:
            include_point(x, y)

    if min_x is None:
        return [0, 0, 0, 0]
    width = max(1, coord(max_x - min_x))
    height = max(1, coord(max_y - min_y))
    return [coord(min_x), coord(min_y), width, height]


def compute_max_edge_span_columns(flows, depth):
    max_span = 0
    for flow in flows:
        src = flow.get("source")
        tgt = flow.get("target")
        if src not in depth or tgt not in depth:
            continue
        max_span = max(max_span, abs(depth[tgt] - depth[src]))
    return int(max_span)


def compute_consecutive_gateway_chain_length(nodes, flows, depth):
    gateway_ids = {nid for nid, meta in nodes.items() if meta.get("type") in GATEWAY_TYPES}
    if not gateway_ids:
        return 0
    outgoing = defaultdict(list)
    for flow in flows:
        src = flow.get("source")
        tgt = flow.get("target")
        if src in nodes and tgt in nodes:
            outgoing[src].append(tgt)
    chain = {nid: 1 for nid in gateway_ids}
    for nid in sorted(gateway_ids, key=lambda value: (depth.get(value, 0), value)):
        for tgt in outgoing.get(nid, []):
            if tgt not in gateway_ids:
                continue
            if depth.get(tgt, 0) < depth.get(nid, 0):
                continue
            chain[tgt] = max(chain.get(tgt, 1), chain.get(nid, 1) + 1)
    return int(max(chain.values(), default=0))


def compute_readability_metrics(rects, label_rects, edge_paths, flows, depth, nodes, thresholds=None):
    bbox = compute_diagram_bbox(rects, label_rects, edge_paths)
    diagram_width_px = int(bbox[2])
    diagram_height_px = int(bbox[3])
    aspect_ratio_x100 = int(round((diagram_width_px * 100.0) / max(diagram_height_px, 1)))
    max_depth_columns = int(max(depth.values()) + 1 if depth else 0)
    max_edge_span_columns = compute_max_edge_span_columns(flows, depth)
    consecutive_gateway_chain_length = compute_consecutive_gateway_chain_length(nodes, flows, depth)

    width_limit = max(0, threshold_value(thresholds, "max_diagram_width_px"))
    height_limit = max(0, threshold_value(thresholds, "max_diagram_height_px"))
    aspect_limit = max(1, threshold_value(thresholds, "max_aspect_ratio_x100"))
    depth_limit = max(0, threshold_value(thresholds, "max_depth_columns"))
    edge_span_limit = max(0, threshold_value(thresholds, "max_edge_span_columns"))
    gateway_chain_limit = max(0, threshold_value(thresholds, "max_gateway_chain_length"))

    diagram_width_violations = int(diagram_width_px > width_limit)
    diagram_height_violations = int(diagram_height_px > height_limit)
    diagram_aspect_ratio_violations = int(aspect_ratio_x100 > aspect_limit)
    depth_columns_violations = int(max_depth_columns > depth_limit)
    edge_span_columns_violations = int(max_edge_span_columns > edge_span_limit)
    gateway_chain_violations = int(consecutive_gateway_chain_length > gateway_chain_limit)
    readability_violations = (
        diagram_width_violations
        + diagram_height_violations
        + diagram_aspect_ratio_violations
        + depth_columns_violations
        + edge_span_columns_violations
        + gateway_chain_violations
    )
    return {
        "diagram_bbox": bbox,
        "diagram_width_px": diagram_width_px,
        "diagram_height_px": diagram_height_px,
        "aspect_ratio_x100": aspect_ratio_x100,
        "max_depth_columns": max_depth_columns,
        "max_edge_span_columns": int(max_edge_span_columns),
        "consecutive_gateway_chain_length": int(consecutive_gateway_chain_length),
        "diagram_width_violations": int(diagram_width_violations),
        "diagram_height_violations": int(diagram_height_violations),
        "diagram_aspect_ratio_violations": int(diagram_aspect_ratio_violations),
        "depth_columns_violations": int(depth_columns_violations),
        "edge_span_columns_violations": int(edge_span_columns_violations),
        "gateway_chain_violations": int(gateway_chain_violations),
        "readability_violations": int(readability_violations),
        "layout_requires_decomposition": bool(readability_violations > 0),
    }


def empty_drift_channel(budget):
    return {
        "count": 0,
        "moved": 0,
        "total": 0.0,
        "max": 0.0,
        "budget": float(budget),
        "violations": 0,
        "total_over_budget": 0.0,
        "max_over_budget": 0.0,
    }


def record_drift(channel, delta):
    channel["count"] += 1
    channel["total"] += delta
    channel["max"] = max(channel["max"], delta)
    if delta > 0:
        channel["moved"] += 1
    over_budget = max(0.0, delta - channel["budget"])
    channel["total_over_budget"] += over_budget
    channel["max_over_budget"] = max(channel["max_over_budget"], over_budget)
    if over_budget > 0:
        channel["violations"] += 1


def compute_drift_channels(
    rects,
    label_rects,
    existing_rects,
    existing_labels,
    shape_budget,
    label_budget,
    participant_lane_budget,
    participant_lane_bounds=None,
    existing_participant_lane_bounds=None,
):
    drift_channels = {
        "untouched_shapes": empty_drift_channel(0),
        "touched_repaired_shapes": empty_drift_channel(shape_budget),
        "participant_lane_bounds": empty_drift_channel(participant_lane_budget),
        "labels": empty_drift_channel(label_budget),
    }

    for nid, baseline_rect in existing_rects.items():
        if nid not in rects:
            continue
        delta = rect_distance(rects[nid], baseline_rect)
        channel_name = "untouched_shapes" if delta == 0 else "touched_repaired_shapes"
        record_drift(drift_channels[channel_name], delta)

    for nid, baseline_rect in existing_labels.items():
        if nid not in label_rects:
            continue
        delta = rect_distance(tuple(label_rects[nid]), tuple(baseline_rect))
        record_drift(drift_channels["labels"], delta)

    for element_id, baseline_rect in (existing_participant_lane_bounds or {}).items():
        if element_id not in (participant_lane_bounds or {}):
            continue
        delta = rect_distance(participant_lane_bounds[element_id], baseline_rect)
        record_drift(drift_channels["participant_lane_bounds"], delta)

    return drift_channels


def verify_and_report(
    rects,
    label_rects,
    edge_paths,
    flows,
    depth,
    lane,
    nodes,
    existing_rects,
    existing_labels,
    shape_budget,
    label_budget,
    gap_x=80,
    gap_y=130,
    participant_lane_budget=None,
    participant_lane_bounds=None,
    existing_participant_lane_bounds=None,
    thresholds=None,
    budget_violation_severity="error",
):
    items = build_rect_items(rects, label_rects)
    flows_by_id = {flow["id"]: flow for flow in flows}
    participant_lane_budget = shape_budget if participant_lane_budget is None else participant_lane_budget
    column_gap_tolerance = threshold_value(thresholds, "column_gap_violation_tolerance")
    lane_gap_tolerance = threshold_value(thresholds, "lane_gap_violation_tolerance")
    drift_channels = compute_drift_channels(
        rects,
        label_rects,
        existing_rects,
        existing_labels,
        shape_budget,
        label_budget,
        participant_lane_budget,
        participant_lane_bounds=participant_lane_bounds,
        existing_participant_lane_bounds=existing_participant_lane_bounds,
    )
    metrics = {
        "shape_shape": 0,
        "label_shape": 0,
        "label_label": 0,
        "edge_bbox_collisions_detected": 0,
        "invalid_edge_edge_intersections": len(edge_edge_intersections(edge_paths, flows_by_id=flows_by_id)),
        "endpoint_anchor_mismatch": 0,
        "route_quality_violations": 0,
        "shape_budget_violations": 0,
        "label_budget_violations": 0,
        "participant_lane_budget_violations": drift_channels["participant_lane_bounds"]["violations"],
        "shape_move_total": 0.0,
        "shape_move_max": 0.0,
        "label_move_total": 0.0,
        "label_move_max": 0.0,
        "column_gap_violations": compute_column_gap_violations(rects, depth, lane, gap_x, column_gap_tolerance),
        "lane_gap_violations": compute_lane_gap_violations(rects, label_rects, lane, gap_y, lane_gap_tolerance),
        "diagram_bbox": [0, 0, 0, 0],
        "diagram_width_px": 0,
        "diagram_height_px": 0,
        "aspect_ratio_x100": 0,
        "max_depth_columns": 0,
        "max_edge_span_columns": 0,
        "consecutive_gateway_chain_length": 0,
        "diagram_width_violations": 0,
        "diagram_height_violations": 0,
        "diagram_aspect_ratio_violations": 0,
        "depth_columns_violations": 0,
        "edge_span_columns_violations": 0,
        "gateway_chain_violations": 0,
        "readability_violations": 0,
        "layout_requires_decomposition": False,
        "drift_channels": drift_channels,
        "typed_issues": [],
        "issue_counts": {},
    }
    metrics.update(compute_readability_metrics(rects, label_rects, edge_paths, flows, depth, nodes, thresholds=thresholds))
    typed_issues = []

    node_ids = list(rects.keys())
    for index, left in enumerate(node_ids):
        for right in node_ids[index + 1:]:
            if is_allowed_shape_overlap(left, right, nodes):
                continue
            if rect_intersect(rects[left], rects[right], pad=0):
                metrics["shape_shape"] += 1
                typed_issues.append(
                    make_typed_issue(
                        "pair",
                        left,
                        secondary_element_id=right,
                        bbox=bbox_union(rects[left], rects[right]),
                        severity="error",
                        code="shape_overlap",
                    )
                )

    label_ids = list(label_rects.keys())
    for index, label_id in enumerate(label_ids):
        label_rect = tuple(label_rects[label_id])
        for node_id in node_ids:
            if node_id == label_id:
                continue
            if rect_intersect(label_rect, rects[node_id], pad=0):
                metrics["label_shape"] += 1
                typed_issues.append(
                    make_typed_issue(
                        "label",
                        label_id,
                        secondary_element_id=node_id,
                        bbox=bbox_union(label_rect, rects[node_id]),
                        severity="error",
                        code="label_shape_overlap",
                    )
                )
        for other in label_ids[index + 1:]:
            if rect_intersect(label_rect, tuple(label_rects[other]), pad=0):
                metrics["label_label"] += 1
                typed_issues.append(
                    make_typed_issue(
                        "pair",
                        label_id,
                        secondary_element_id=other,
                        bbox=bbox_union(label_rect, tuple(label_rects[other])),
                        severity="error",
                        code="label_label_overlap",
                    )
                )

    for flow in flows:
        fid = flow["id"]
        src = flow["source"]
        tgt = flow["target"]
        path = edge_paths[fid]
        collisions = path_collision_items(path, src, tgt, items, pad=threshold_value(thresholds, "edge_reroute_collision_padding"))
        metrics["edge_bbox_collisions_detected"] += int(bool(collisions))
        for kind, hit_id in sorted(collisions):
            typed_issues.append(
                make_typed_issue(
                    "edge",
                    fid,
                    secondary_element_id=hit_id,
                    bbox=path_bbox(path),
                    severity="error",
                    code=f"edge_{kind}_collision",
                )
            )
        anchor_issues = path_anchor_mismatches(path, rects[src], rects[tgt])
        metrics["endpoint_anchor_mismatch"] += anchor_issues
        if anchor_issues:
            typed_issues.append(
                make_typed_issue(
                    "edge",
                    fid,
                    bbox=path_bbox(path),
                    severity="error",
                    code="edge_anchor_mismatch",
                )
            )
        route_quality = path_quality_violations(path, thresholds=thresholds)
        endpoint_direction = path_endpoint_direction_violations(path, rects[src], rects[tgt])
        metrics["route_quality_violations"] += route_quality
        metrics["route_quality_violations"] += endpoint_direction
        if route_quality or endpoint_direction:
            typed_issues.append(
                make_typed_issue(
                    "edge",
                    fid,
                    bbox=path_bbox(path),
                    severity="error",
                    code="edge_route_quality",
                )
            )

    for edge_a, edge_b in edge_edge_intersections(edge_paths, flows_by_id=flows_by_id):
        typed_issues.append(
            make_typed_issue(
                "pair",
                edge_a,
                secondary_element_id=edge_b,
                bbox=bbox_union(path_bbox(edge_paths[edge_a]), path_bbox(edge_paths[edge_b])),
                severity="error",
                code="edge_edge_intersection",
            )
        )

    for nid in node_ids:
        if nid in existing_rects:
            delta = rect_distance(rects[nid], existing_rects[nid])
            metrics["shape_move_total"] += delta
            metrics["shape_move_max"] = max(metrics["shape_move_max"], delta)
            if delta > shape_budget:
                metrics["shape_budget_violations"] += 1
                typed_issues.append(
                    make_typed_issue(
                        "shape",
                        nid,
                        bbox=rect_to_bbox(rects[nid]),
                        severity=budget_violation_severity,
                        code="shape_budget_violation",
                    )
                )

    for nid in label_ids:
        if nid in existing_labels:
            delta = rect_distance(tuple(label_rects[nid]), tuple(existing_labels[nid]))
            metrics["label_move_total"] += delta
            metrics["label_move_max"] = max(metrics["label_move_max"], delta)
            if delta > label_budget:
                metrics["label_budget_violations"] += 1
                typed_issues.append(
                    make_typed_issue(
                        "label",
                        nid,
                        bbox=rect_to_bbox(label_rects[nid]),
                        severity=budget_violation_severity,
                        code="label_budget_violation",
                    )
                )

    for element_id, baseline_rect in (existing_participant_lane_bounds or {}).items():
        if element_id not in (participant_lane_bounds or {}):
            continue
        delta = rect_distance(participant_lane_bounds[element_id], baseline_rect)
        if delta > participant_lane_budget:
            typed_issues.append(
                make_typed_issue(
                    "shape",
                    element_id,
                    bbox=rect_to_bbox(participant_lane_bounds[element_id]),
                    severity=budget_violation_severity,
                    code="participant_lane_budget_violation",
                )
            )

    if metrics["column_gap_violations"]:
        typed_issues.append(
            make_typed_issue(
                "global",
                "layout",
                bbox=None,
                severity="error",
                code="column_gap_violation",
            )
        )
    if metrics["lane_gap_violations"]:
        typed_issues.append(
            make_typed_issue(
                "global",
                "layout",
                bbox=None,
                severity="error",
                code="lane_gap_violation",
            )
        )
    if metrics["diagram_width_violations"]:
        typed_issues.append(
            make_typed_issue(
                "global",
                "layout",
                bbox=metrics["diagram_bbox"],
                severity="error",
                code="diagram_width_violation",
            )
        )
    if metrics["diagram_height_violations"]:
        typed_issues.append(
            make_typed_issue(
                "global",
                "layout",
                bbox=metrics["diagram_bbox"],
                severity="error",
                code="diagram_height_violation",
            )
        )
    if metrics["diagram_aspect_ratio_violations"]:
        typed_issues.append(
            make_typed_issue(
                "global",
                "layout",
                bbox=metrics["diagram_bbox"],
                severity="error",
                code="diagram_aspect_ratio_violation",
            )
        )
    if metrics["depth_columns_violations"]:
        typed_issues.append(
            make_typed_issue(
                "global",
                "layout",
                bbox=metrics["diagram_bbox"],
                severity="error",
                code="depth_columns_violation",
            )
        )
    if metrics["edge_span_columns_violations"]:
        typed_issues.append(
            make_typed_issue(
                "global",
                "layout",
                bbox=metrics["diagram_bbox"],
                severity="error",
                code="edge_span_columns_violation",
            )
        )
    if metrics["gateway_chain_violations"]:
        typed_issues.append(
            make_typed_issue(
                "global",
                "layout",
                bbox=metrics["diagram_bbox"],
                severity="error",
                code="gateway_chain_violation",
            )
        )

    metrics["typed_issues"] = typed_issues
    metrics["issue_counts"] = issue_count_by_code(typed_issues)
    return metrics


def has_violations(metrics, include_budget_violations=True):
    hard_keys = [
        "shape_shape",
        "label_shape",
        "label_label",
        "edge_bbox_collisions_detected",
        "invalid_edge_edge_intersections",
        "endpoint_anchor_mismatch",
        "route_quality_violations",
        "column_gap_violations",
        "lane_gap_violations",
        "diagram_width_violations",
        "diagram_height_violations",
        "diagram_aspect_ratio_violations",
        "depth_columns_violations",
        "edge_span_columns_violations",
        "gateway_chain_violations",
        "readability_violations",
    ]
    if include_budget_violations:
        hard_keys.extend(
            [
                "shape_budget_violations",
                "label_budget_violations",
                "participant_lane_budget_violations",
            ]
        )
    return any(metrics[key] > 0 for key in hard_keys)


def ordered_unique(values):
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def severity_counts(metrics):
    counts = Counter()
    for issue in metrics.get("typed_issues", []):
        severity = str(issue.get("severity") or "").strip().lower() or "unknown"
        counts[severity] += 1
    return {
        "error": int(counts.get("error", 0)),
        "warning": int(counts.get("warning", 0)),
        "info": int(counts.get("info", 0)),
    }


def build_layout_summary_payload(
    *,
    final_status,
    final_mode,
    layout_profile_family,
    simple_postprocess_mode,
    budget_violations_hard,
    metrics,
    hint_applied,
    layout_hint_source,
):
    metrics = metrics or {}
    sev = severity_counts(metrics)
    typed_issue_count = len(metrics.get("typed_issues", []))
    advisory_only = (
        final_status == "PASS"
        and sev["error"] == 0
        and typed_issue_count > 0
    )
    return {
        "schema_version": LAYOUT_SUMMARY_SCHEMA_VERSION,
        "final_status": str(final_status),
        "final_mode": str(final_mode),
        "layout_profile_family": str(layout_profile_family),
        "simple_postprocess_mode": bool(simple_postprocess_mode),
        "budget_violations_hard": bool(budget_violations_hard),
        "shape_budget_violations": int(metrics.get("shape_budget_violations", 0)),
        "label_budget_violations": int(metrics.get("label_budget_violations", 0)),
        "participant_lane_budget_violations": int(metrics.get("participant_lane_budget_violations", 0)),
        "typed_issue_count": int(typed_issue_count),
        "warning_issue_count": int(sev["warning"]),
        "error_issue_count": int(sev["error"]),
        "diagram_width_px": int(metrics.get("diagram_width_px", 0)),
        "diagram_height_px": int(metrics.get("diagram_height_px", 0)),
        "aspect_ratio_x100": int(metrics.get("aspect_ratio_x100", 0)),
        "max_depth_columns": int(metrics.get("max_depth_columns", 0)),
        "max_edge_span_columns": int(metrics.get("max_edge_span_columns", 0)),
        "consecutive_gateway_chain_length": int(metrics.get("consecutive_gateway_chain_length", 0)),
        "readability_violations": int(metrics.get("readability_violations", 0)),
        "layout_requires_decomposition": bool(metrics.get("layout_requires_decomposition", False)),
        "advisory_only": bool(advisory_only),
        "hint_applied": bool(hint_applied),
        "layout_hint_source": str(layout_hint_source),
    }


def write_layout_summary(path, payload):
    if not path:
        return
    report_json_path = Path(path)
    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    with report_json_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def path_collision_items(points, src, tgt, items, pad=2):
    hits = set()
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]
        for kind, oid, r in items:
            if oid in (src, tgt):
                continue
            if seg_hits_rect(p1, p2, r, pad=pad):
                hits.add((kind, oid))
    return hits


def path_manhattan_length(points):
    total = 0
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        total += abs(x2 - x1) + abs(y2 - y1)
    return total


def path_long_horizontal_segment_penalty(points, thresholds=None):
    soft_limit = max(1, threshold_value(thresholds, "edge_route_long_horizontal_soft_limit"))
    weight = max(1, threshold_value(thresholds, "edge_route_long_horizontal_penalty_weight"))
    penalty = 0
    for p1, p2 in edge_segments(points):
        if p1[1] != p2[1]:
            continue
        length = abs(p2[0] - p1[0])
        if length <= soft_limit:
            continue
        penalty += weight + int((length - soft_limit) // soft_limit)
    return penalty


def path_bends(points):
    if len(points) < 3:
        return 0
    bends = 0
    prev_dir = None
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        curr_dir = "h" if y1 == y2 else "v"
        if prev_dir is not None and curr_dir != prev_dir:
            bends += 1
        prev_dir = curr_dir
    return bends


def extract_shape_bounds(di_elements, allowed_ids=None):
    rects = {}
    allowed_ids = set(allowed_ids or [])
    for element in di_elements:
        if tag_name(element) != "BPMNShape":
            continue
        element_id = element.get("bpmnElement")
        if not element_id:
            continue
        if allowed_ids and element_id not in allowed_ids:
            continue
        bounds = element.find(q("dc", "Bounds"))
        if bounds is None:
            continue
        rects[element_id] = (
            snap(float(bounds.get("x"))),
            snap(float(bounds.get("y"))),
            snap(float(bounds.get("width"))),
            snap(float(bounds.get("height"))),
        )
    return rects


def main():
    parser = argparse.ArgumentParser(description="Apply strict BPMN layout policy")
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--report-json")
    parser.add_argument("--lane-map")
    parser.add_argument("--type-config")
    parser.add_argument("--layout-config")
    parser.add_argument("--enable-layout-hints", action="store_true")
    parser.add_argument("--layout-hints-json")
    parser.add_argument("--simple-postprocess", action="store_true")
    parser.add_argument("--preserve-existing-di-strict", action="store_true")
    args = parser.parse_args()
    strict_preserve_chain = bool(args.preserve_existing_di_strict)

    tree = ET.parse(args.input)
    root = tree.getroot()

    processes = root.findall(q("bpmn", "process"))
    if not processes:
        raise RuntimeError("No bpmn:process found")

    primary_process = processes[0]
    type_config = load_json_file(args.type_config)
    external_lane_map = load_lane_map(args.lane_map) if args.lane_map else {}
    layout_policy = load_layout_policy_config(args.layout_config)
    layout_hints = {}
    layout_hint_source = LAYOUT_HINT_SOURCE_NONE
    if args.enable_layout_hints:
        layout_hints, layout_hint_source = load_layout_hint_payload(args.layout_hints_json)
    elif args.layout_hints_json:
        layout_hint_source = LAYOUT_HINT_SOURCE_DISABLED
    if args.simple_postprocess:
        layout_profile_family = "simple_postprocess"
        preserve_profile_name = layout_policy["policy"]["simple_default_profile"]
        fallback_profile_name = layout_policy["policy"]["simple_fallback_profile"]
        escalated_profile_name = layout_policy["policy"]["simple_escalated_profile"]
    else:
        layout_profile_family = "native"
        preserve_profile_name = layout_policy["policy"]["default_profile"]
        fallback_profile_name = layout_policy["policy"]["fallback_profile"]
        escalated_profile_name = layout_policy["policy"]["escalated_profile"]
    active_profile_names = ordered_unique(
        [preserve_profile_name, escalated_profile_name, fallback_profile_name]
    )
    main_hint_applied_by_profile = {}
    preserve_thresholds, main_hint_applied_by_profile[preserve_profile_name] = apply_layout_hint_overrides(
        resolve_threshold_profile(layout_policy, preserve_profile_name, scope="main"),
        layout_hints,
        preserve_profile_name,
        "main",
    )
    escalated_thresholds, main_hint_applied_by_profile[escalated_profile_name] = apply_layout_hint_overrides(
        resolve_threshold_profile(layout_policy, escalated_profile_name, scope="main"),
        layout_hints,
        escalated_profile_name,
        "main",
    )
    fallback_thresholds, main_hint_applied_by_profile[fallback_profile_name] = apply_layout_hint_overrides(
        resolve_threshold_profile(layout_policy, fallback_profile_name, scope="main"),
        layout_hints,
        fallback_profile_name,
        "main",
    )
    nested_thresholds_by_profile = {}
    nested_hint_applied_by_profile = {}
    for profile_name in active_profile_names:
        nested_thresholds, applied = apply_layout_hint_overrides(
            resolve_threshold_profile(layout_policy, profile_name, scope="nested"),
            layout_hints,
            profile_name,
            "nested",
        )
        nested_thresholds_by_profile[profile_name] = nested_thresholds
        nested_hint_applied_by_profile[profile_name] = applied

    lane_from_bpmn = {}
    lane_defs_by_process = {}
    artifacts = []
    associations = []
    for process in processes:
        lane_from_bpmn.update(extract_lane_membership(process))
        lane_defs_by_process[process.get("id")] = extract_lane_definitions(process)
        process_artifacts, process_associations = extract_artifacts(process)
        artifacts.extend(process_artifacts)
        associations.extend(process_associations)

    collaboration = root.find(q("bpmn", "collaboration"))
    participants = []
    if collaboration is not None:
        for child in list(collaboration):
            tag = child.tag.split("}")[-1]
            if tag == "participant":
                participants.append(
                    {
                        "id": child.get("id"),
                        "name": child.get("name", ""),
                        "processRef": child.get("processRef"),
                    }
                )
    collaboration, participants, auto_created_collaboration = ensure_collaboration_for_lane_processes(
        root,
        processes,
        collaboration,
        participants,
        lane_defs_by_process,
    )
    message_flows = extract_message_flows(collaboration)

    nodes = {}
    flows = []
    for process in processes:
        process_nodes, process_flows, _ = collect_direct_container_graph(process, process.get("id"))
        nodes.update(process_nodes)
        flows.extend(process_flows)

    subprocess_specs_by_profile = {}
    flattened_subprocess_specs_by_profile = {}
    for profile_name, nested_thresholds in nested_thresholds_by_profile.items():
        top_level_subprocess_specs, flattened_subprocess_specs = build_subprocess_layouts_for_profile(
            processes,
            lane_from_bpmn,
            external_lane_map,
            type_config,
            nested_thresholds,
        )
        subprocess_specs_by_profile[profile_name] = top_level_subprocess_specs
        flattened_subprocess_specs_by_profile[profile_name] = flattened_subprocess_specs

    flattened_subprocess_specs = flattened_subprocess_specs_by_profile[preserve_profile_name]
    nested_node_ids = {
        node_id
        for spec in flattened_subprocess_specs.values()
        for node_id in spec["nodes"].keys()
    }
    nested_flow_ids = {
        flow["id"]
        for spec in flattened_subprocess_specs.values()
        for flow in spec["flows"]
    }

    if not nodes:
        raise RuntimeError("Missing flow nodes")

    node_ids = set(nodes.keys()) | nested_node_ids
    flow_ids = {f["id"] for f in flows} | nested_flow_ids
    (
        existing_rects,
        existing_labels,
        existing_edges,
        existing_plane_extras,
        existing_diagram_id,
        existing_plane_id,
        existing_plane_element,
    ) = load_existing_di(root, node_ids, flow_ids)

    lane = resolve_lane_assignments(nodes, lane_from_bpmn, external_lane_map, existing_rects)
    preserve_dims = build_layout_dims(nodes, flattened_subprocess_specs_by_profile[preserve_profile_name], type_config)
    escalated_dims = build_layout_dims(nodes, flattened_subprocess_specs_by_profile[escalated_profile_name], type_config)
    fallback_dims = build_layout_dims(nodes, flattened_subprocess_specs_by_profile[fallback_profile_name], type_config)

    report = []
    report.append("# BPMN Layout Report")
    report.append("")
    report.append(f"- input: `{args.input}`")
    report.append(f"- output: `{args.output}`")
    report.append(f"- generated_at: {dt.datetime.now().isoformat(timespec='seconds')}")
    report.append(f"- layout_policy_config: `{layout_policy['path']}`")
    report.append(f"- layout_profile_family: {layout_profile_family}")
    report.append(f"- policy_default_profile: {preserve_profile_name}")
    report.append(f"- policy_escalated_profile: {escalated_profile_name}")
    report.append(f"- policy_fallback_profile: {fallback_profile_name}")
    report.append(f"- strict_preserve_chain: {'true' if strict_preserve_chain else 'false'}")
    report.append(f"- simple_postprocess_mode: {'true' if args.simple_postprocess else 'false'}")
    report.append(f"- nodes: {len(nodes)}")
    report.append(f"- flows: {len(flows)}")
    report.append(f"- nested_subprocesses: {len(flattened_subprocess_specs)}")
    if auto_created_collaboration:
        report.append("- collaboration_auto_created_for_lanes: true")
    report.append("")

    top_shape_baseline = {nid: rect for nid, rect in existing_rects.items() if nid in nodes}
    top_label_baseline = {nid: rect for nid, rect in existing_labels.items() if nid in nodes}
    top_edge_baseline = {fid: path for fid, path in existing_edges.items() if fid in {flow["id"] for flow in flows}}
    result = None
    preserved_error = None
    escalated_error = None
    budget_violation_severity = "warning" if args.simple_postprocess else "error"
    try:
        result = run_layout_pipeline(
            preserve_profile_name,
            nodes,
            flows,
            lane,
            preserve_dims,
            top_shape_baseline,
            top_label_baseline,
            top_edge_baseline,
            preserve_thresholds,
            budget_violation_severity=budget_violation_severity,
        )
    except LayoutError as exc:
        preserved_error = str(exc)

    strict_chain_reason = None
    budget_violations_hard = not args.simple_postprocess
    report.append(f"- budget_violations_hard: {'true' if budget_violations_hard else 'false'}")
    if args.simple_postprocess:
        baseline_error_field = "simple_refine_error"
        baseline_status_field = "simple_refine_status"
        escalated_mode_field = "simple_repair_mode"
        escalated_error_field = "simple_repair_error"
        escalated_status_field = "simple_repair_status"
    else:
        baseline_error_field = "preserve_existing_di_error"
        baseline_status_field = "preserve_existing_di_status"
        escalated_mode_field = "escalated_repair_mode"
        escalated_error_field = "escalated_repair_error"
        escalated_status_field = "escalated_repair_status"

    if preserved_error or has_violations(
        result["metrics"],
        include_budget_violations=budget_violations_hard,
    ):
        report.append(f"- baseline_mode: {preserve_profile_name}")
        if preserved_error:
            report.append(f"- {baseline_error_field}: {preserved_error}")
        else:
            report.append(f"- {baseline_status_field}: violations_detected -> escalate:{escalated_profile_name}")
        try:
            result = run_layout_pipeline(
                escalated_profile_name,
                nodes,
                flows,
                lane,
                escalated_dims,
                top_shape_baseline,
                top_label_baseline,
                top_edge_baseline,
                escalated_thresholds,
                budget_violation_severity=budget_violation_severity,
            )
        except LayoutError as exc:
            escalated_error = str(exc)

        if escalated_error or has_violations(
            result["metrics"],
            include_budget_violations=budget_violations_hard,
        ):
            report.append(f"- {escalated_mode_field}: {escalated_profile_name}")
            if escalated_error:
                report.append(f"- {escalated_error_field}: {escalated_error}")
                strict_chain_reason = escalated_error
            else:
                report.append(f"- {escalated_status_field}: violations_detected -> fallback:{fallback_profile_name}")
                strict_chain_reason = "escalated_profile_unresolved_hard_conflicts"
            if strict_preserve_chain:
                report.append("- strict_preserve_chain_status: fail_no_greenfield_fallback")
            else:
                result = run_layout_pipeline(
                    fallback_profile_name,
                    nodes,
                    flows,
                    lane,
                    fallback_dims,
                    {},
                    {},
                    {},
                    fallback_thresholds,
                    report_shape_baseline=top_shape_baseline,
                    report_label_baseline=top_label_baseline,
                    budget_violation_severity=budget_violation_severity,
                )
    else:
        report.append(f"- baseline_mode: {preserve_profile_name}")

    if strict_preserve_chain and strict_chain_reason:
        report.append("")
        report.append("Final status: FAIL")
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write("\n".join(report) + "\n")
        summary_payload = build_layout_summary_payload(
            final_status="FAIL",
            final_mode=(result or {}).get("mode", escalated_profile_name),
            layout_profile_family=layout_profile_family,
            simple_postprocess_mode=args.simple_postprocess,
            budget_violations_hard=budget_violations_hard,
            metrics=(result or {}).get("metrics", {}),
            hint_applied=False,
            layout_hint_source=layout_hint_source,
        )
        write_layout_summary(args.report_json, summary_payload)
        raise LayoutError(f"Strict preserve chain failed without greenfield fallback: {strict_chain_reason}")

    rects = result["rects"]
    label_rects = result["label_rects"]
    edge_paths = result["edge_paths"]
    canonical_rects = result["canonical_rects"]
    metrics = result["metrics"]
    depth = result["depth"]
    slot = result["slot"]
    all_nodes = dict(nodes)
    all_flows = list(flows)
    all_rects = dict(rects)
    all_label_rects = {nid: list(rect) for nid, rect in label_rects.items()}
    all_edge_paths = {fid: list(path) for fid, path in edge_paths.items()}
    nested_notes = []
    apply_nested_subprocess_layouts(
        subprocess_specs_by_profile[result["mode"]],
        all_rects,
        all_label_rects,
        all_edge_paths,
        all_nodes,
        all_flows,
        nested_notes,
        result["mode"],
        nested_thresholds_by_profile[result["mode"]],
    )
    expanded_subprocess_ids = {
        subprocess_id
        for subprocess_id, spec in flattened_subprocess_specs_by_profile[result["mode"]].items()
        if spec["expanded"]
    }
    hint_applied = bool(main_hint_applied_by_profile.get(result["mode"], False)) or bool(
        nested_hint_applied_by_profile.get(result["mode"], False)
    )

    report.append(f"- final_mode: {result['mode']}")
    report.append(f"- layout_hint_source: {layout_hint_source}")
    report.append(f"- hint_applied: {'true' if hint_applied else 'false'}")
    if len(nodes) < 3:
        report.append("- warnings: process has fewer than 3 modeled nodes; verify that the BPMN is intentionally minimal")
    report.append("")
    report.append("## Phase Summary")
    for action in result["actions"]:
        report.append(f"- {action}")
    for action in nested_notes:
        report.append(f"- {action}")
    report.append("")

    plane_target = existing_plane_element or (collaboration.get("id") if collaboration is not None else primary_process.get("id"))
    diagram_id = existing_diagram_id or f"BPMNDiagram_{plane_target}"
    plane_id = existing_plane_id or f"BPMNPlane_{plane_target}"

    diagram = root.find(q("bpmndi", "BPMNDiagram"))
    if diagram is None:
        diagram = ET.SubElement(root, q("bpmndi", "BPMNDiagram"), {"id": diagram_id})
    else:
        diagram.set("id", diagram_id)

    plane = diagram.find(q("bpmndi", "BPMNPlane"))
    if plane is None:
        plane = ET.SubElement(diagram, q("bpmndi", "BPMNPlane"))
    for c in list(plane):
        plane.remove(c)
    plane.set("id", plane_id)
    plane.set("bpmnElement", plane_target)

    regenerated_di_ids = regenerated_di_element_ids(participants, lane_defs_by_process)
    existing_participant_lane_bounds = extract_shape_bounds(existing_plane_extras, allowed_ids=regenerated_di_ids)
    generated_participant_lane_bounds = {}
    existing_extra_ids = set()
    replaced_existing_pool_or_lane_di = 0
    for extra in existing_plane_extras:
        element_id = extra.get("bpmnElement")
        if element_id in regenerated_di_ids:
            replaced_existing_pool_or_lane_di += 1
            continue
        if element_id:
            existing_extra_ids.add(element_id)
        plane.append(copy.deepcopy(extra))
    if replaced_existing_pool_or_lane_di:
        report.append(f"- replaced_existing_pool_or_lane_di: {replaced_existing_pool_or_lane_di}")

    final_thresholds = resolve_threshold_profile(layout_policy, result["mode"], scope="main")
    participant_rects = {}
    participant_label_offset_x = final_thresholds["participant_label_offset_x"]
    participant_label_offset_y = final_thresholds["participant_label_offset_y"]
    lane_label_offset_x = final_thresholds["lane_label_offset_x"]
    lane_label_offset_y = final_thresholds["lane_label_offset_y"]
    for participant in participants:
        participant_id = participant["id"]
        if not participant_id:
            continue
        participant_rect = build_participant_rect(
            participant.get("processRef"),
            all_rects,
            all_nodes,
            label_rects=all_label_rects,
            thresholds=final_thresholds,
        )
        if participant_rect is None:
            continue
        participant_rects[participant_id] = participant_rect
        generated_participant_lane_bounds[participant_id] = participant_rect
        if participant_id in existing_extra_ids:
            continue
        shape = ET.SubElement(plane, q("bpmndi", "BPMNShape"), {"id": f"Shape_{participant_id}", "bpmnElement": participant_id, "isHorizontal": "true"})
        x, y, w, h = participant_rect
        ET.SubElement(shape, q("dc", "Bounds"), {"x": str(x), "y": str(y), "width": str(w), "height": str(h)})
        if participant.get("name"):
            lw, lh = label_dims(participant["name"])
            lab = ET.SubElement(shape, q("bpmndi", "BPMNLabel"))
            ET.SubElement(
                lab,
                q("dc", "Bounds"),
                {
                    "x": str(x + participant_label_offset_x),
                    "y": str(y + participant_label_offset_y),
                    "width": str(lw),
                    "height": str(lh),
                },
            )

    for participant in participants:
        participant_id = participant["id"]
        participant_rect = participant_rects.get(participant_id)
        process_id = participant.get("processRef")
        if participant_rect is None:
            participant_rect = build_process_envelope(
                process_id,
                all_rects,
                all_nodes,
                label_rects=all_label_rects,
                thresholds=final_thresholds,
            )
        lane_defs = lane_defs_by_process.get(process_id, [])
        lane_rects = build_contiguous_lane_rects(lane_defs, all_rects, participant_rect, thresholds=final_thresholds)
        for lane_def in lane_defs:
            lane_id = lane_def["id"]
            lane_rect = lane_rects.get(lane_id)
            if lane_rect is None:
                continue
            generated_participant_lane_bounds[lane_id] = lane_rect
            if not lane_id or lane_id in existing_extra_ids:
                continue
            shape = ET.SubElement(
                plane,
                q("bpmndi", "BPMNShape"),
                {"id": f"Shape_{lane_id}", "bpmnElement": lane_id, "isHorizontal": "true"},
            )
            x, y, w, h = lane_rect
            ET.SubElement(shape, q("dc", "Bounds"), {"x": str(x), "y": str(y), "width": str(w), "height": str(h)})
            if lane_def.get("name"):
                lw, lh = label_dims(lane_def["name"])
                lab = ET.SubElement(shape, q("bpmndi", "BPMNLabel"))
                ET.SubElement(
                    lab,
                    q("dc", "Bounds"),
                    {
                        "x": str(x + lane_label_offset_x),
                        "y": str(y + lane_label_offset_y),
                        "width": str(lw),
                        "height": str(lh),
                    },
                )

    for process in processes:
        process_id = process.get("id")
        if any(participant.get("processRef") == process_id for participant in participants):
            continue
        process_rect = build_process_envelope(
            process_id,
            all_rects,
            all_nodes,
            label_rects=all_label_rects,
            thresholds=final_thresholds,
        )
        lane_defs = lane_defs_by_process.get(process_id, [])
        lane_rects = build_contiguous_lane_rects(lane_defs, all_rects, process_rect, thresholds=final_thresholds)
        for lane_def in lane_defs:
            lane_id = lane_def["id"]
            lane_rect = lane_rects.get(lane_id)
            if lane_rect is None:
                continue
            generated_participant_lane_bounds[lane_id] = lane_rect
            if not lane_id or lane_id in existing_extra_ids:
                continue
            shape = ET.SubElement(
                plane,
                q("bpmndi", "BPMNShape"),
                {"id": f"Shape_{lane_id}", "bpmnElement": lane_id, "isHorizontal": "true"},
            )
            x, y, w, h = lane_rect
            ET.SubElement(shape, q("dc", "Bounds"), {"x": str(x), "y": str(y), "width": str(w), "height": str(h)})
            if lane_def.get("name"):
                lw, lh = label_dims(lane_def["name"])
                lab = ET.SubElement(shape, q("bpmndi", "BPMNLabel"))
                ET.SubElement(
                    lab,
                    q("dc", "Bounds"),
                    {
                        "x": str(x + lane_label_offset_x),
                        "y": str(y + lane_label_offset_y),
                        "width": str(lw),
                        "height": str(lh),
                    },
                )

    if args.simple_postprocess:
        di_summary = edge_di_completeness_summary(all_flows, all_edge_paths)
        report.append("## Simple Postprocess DI Completeness")
        report.append(f"- sequence_flow_count: {di_summary['sequence_flow_count']}")
        report.append(f"- bpmn_shape_count: {len(all_nodes)}")
        report.append(f"- bpmn_edge_count: {di_summary['bpmn_edge_count']}")
        report.append(f"- edge_without_two_waypoints_count: {di_summary['edge_without_two_waypoints_count']}")
        report.append(f"- edge_di_complete: {'true' if di_summary['ok'] else 'false'}")
        if di_summary["missing_edge_ids"]:
            report.append(f"- missing_edge_ids: {','.join(di_summary['missing_edge_ids'])}")
        if di_summary["short_waypoint_edge_ids"]:
            report.append(f"- short_waypoint_edge_ids: {','.join(di_summary['short_waypoint_edge_ids'])}")
        report.append("")
        if not di_summary["ok"]:
            report.append("")
            report.append("Final status: FAIL")
            with open(args.report, "w", encoding="utf-8") as fh:
                fh.write("\n".join(report) + "\n")
            summary_payload = build_layout_summary_payload(
                final_status="FAIL",
                final_mode=result["mode"],
                layout_profile_family=layout_profile_family,
                simple_postprocess_mode=args.simple_postprocess,
                budget_violations_hard=budget_violations_hard,
                metrics=result.get("metrics", {}),
                hint_applied=hint_applied,
                layout_hint_source=layout_hint_source,
            )
            write_layout_summary(args.report_json, summary_payload)
            raise LayoutError("Simple postprocess requires complete BPMNEdge coverage for all sequenceFlow elements")

    metrics = verify_and_report(
        all_rects,
        all_label_rects,
        all_edge_paths,
        all_flows,
        depth,
        lane,
        all_nodes,
        result["shape_baseline"],
        result["label_baseline"],
        final_thresholds["max_shape_shift"],
        final_thresholds["max_label_shift"],
        gap_x=final_thresholds["gap_x"],
        gap_y=final_thresholds["gap_y"],
        participant_lane_budget=final_thresholds["max_participant_lane_shift"],
        participant_lane_bounds=generated_participant_lane_bounds,
        existing_participant_lane_bounds=existing_participant_lane_bounds,
        thresholds=final_thresholds,
        budget_violation_severity=budget_violation_severity,
    )
    result["metrics"] = metrics

    report.append("## Final Metrics")
    for key in (
        "shape_shape",
        "label_shape",
        "label_label",
        "edge_bbox_collisions_detected",
        "invalid_edge_edge_intersections",
        "endpoint_anchor_mismatch",
        "route_quality_violations",
        "shape_budget_violations",
        "label_budget_violations",
        "participant_lane_budget_violations",
        "column_gap_violations",
        "lane_gap_violations",
        "diagram_width_px",
        "diagram_height_px",
        "aspect_ratio_x100",
        "max_depth_columns",
        "max_edge_span_columns",
        "consecutive_gateway_chain_length",
        "diagram_width_violations",
        "diagram_height_violations",
        "diagram_aspect_ratio_violations",
        "depth_columns_violations",
        "edge_span_columns_violations",
        "gateway_chain_violations",
        "readability_violations",
        "layout_requires_decomposition",
        "shape_move_total",
        "shape_move_max",
        "label_move_total",
        "label_move_max",
    ):
        value = round(metrics[key], 1) if isinstance(metrics[key], float) else metrics[key]
        report.append(f"- {key}: {value}")
    for channel_name, channel_metrics in metrics["drift_channels"].items():
        report.append(
            f"- drift.{channel_name}: count={channel_metrics['count']} moved={channel_metrics['moved']} "
            f"total={round(channel_metrics['total'], 1)} max={round(channel_metrics['max'], 1)} "
            f"budget={round(channel_metrics['budget'], 1)} violations={channel_metrics['violations']} "
            f"total_over_budget={round(channel_metrics['total_over_budget'], 1)} "
            f"max_over_budget={round(channel_metrics['max_over_budget'], 1)}"
        )
    report.append(f"- typed_issue_count: {len(metrics['typed_issues'])}")
    for code, count in metrics["issue_counts"].items():
        report.append(f"- issue_code.{code}: {count}")
    issue_limit = final_thresholds["conflict_report_issue_limit"]
    for issue in metrics["typed_issues"][:issue_limit]:
        bbox_value = issue["bbox"] if issue["bbox"] is not None else "none"
        report.append(
            f"- issue: code={issue['code']} severity={issue['severity']} target_type={issue['target_type']} "
            f"element_id={issue['element_id']} secondary_element_id={issue['secondary_element_id']} bbox={bbox_value}"
        )
    final_status = "PASS" if not has_violations(metrics, include_budget_violations=budget_violations_hard) else "FAIL"
    report.append("")
    report.append(f"Final status: {final_status}")

    def shape_sort_key(nid):
        if nid in depth:
            return (0, depth[nid], lane[nid], slot[nid], nid)
        meta = all_nodes[nid]
        return (1, meta.get("process_id", ""), meta.get("container_id", ""), nid)

    for nid in sorted(all_nodes.keys(), key=shape_sort_key):
        shape = ET.SubElement(plane, q("bpmndi", "BPMNShape"), {"id": f"Shape_{nid}", "bpmnElement": nid})
        if all_nodes[nid]["type"] in GATEWAY_TYPES:
            shape.set("isMarkerVisible", "true")
        if nid in expanded_subprocess_ids:
            shape.set("isExpanded", "true")
        x, y, w, h = all_rects[nid]
        ET.SubElement(shape, q("dc", "Bounds"), {"x": str(x), "y": str(y), "width": str(w), "height": str(h)})

        if nid in all_label_rects:
            lx, ly, lw, lh = all_label_rects[nid]
            lab = ET.SubElement(shape, q("bpmndi", "BPMNLabel"))
            ET.SubElement(lab, q("dc", "Bounds"), {"x": str(lx), "y": str(ly), "width": str(lw), "height": str(lh)})

    artifact_rects, association_paths = place_artifacts(
        artifacts,
        associations,
        all_rects,
        all_nodes,
        participant_rects,
        label_rects=all_label_rects,
        thresholds=final_thresholds,
    )

    for artifact in artifacts:
        artifact_id = artifact["id"]
        if not artifact_id or artifact_id in existing_extra_ids or artifact_id not in artifact_rects:
            continue
        shape = ET.SubElement(plane, q("bpmndi", "BPMNShape"), {"id": f"Shape_{artifact_id}", "bpmnElement": artifact_id})
        x, y, w, h = artifact_rects[artifact_id]
        ET.SubElement(shape, q("dc", "Bounds"), {"x": str(x), "y": str(y), "width": str(w), "height": str(h)})
        if artifact["type"] != "textAnnotation" and artifact.get("name"):
            lw, lh = label_dims(artifact["name"])
            lab = ET.SubElement(shape, q("bpmndi", "BPMNLabel"))
            ET.SubElement(lab, q("dc", "Bounds"), {"x": str(x + 10), "y": str(y + h + 10), "width": str(lw), "height": str(lh)})

    all_flows_by_id = {flow["id"]: flow for flow in all_flows}
    flow_label_rects = {}
    for fid in sorted(all_flows_by_id.keys()):
        flow = all_flows_by_id[fid]
        flow_name = (flow.get("name") or "").strip()
        if not flow_name:
            continue
        path = all_edge_paths.get(fid)
        if not path:
            continue
        rect = choose_flow_label_rect(path, flow_name)
        if rect is not None:
            flow_label_rects[fid] = rect
    flow_label_rects = resolve_edge_label_overlaps(flow_label_rects, thresholds=final_thresholds)

    for fid in sorted(all_flows_by_id.keys()):
        f = all_flows_by_id[fid]
        fid = f["id"]
        edge = ET.SubElement(plane, q("bpmndi", "BPMNEdge"), {"id": f"Edge_{fid}", "bpmnElement": fid})
        path = all_edge_paths[fid]
        for x, y in path:
            ET.SubElement(edge, q("di", "waypoint"), {"x": str(coord(x)), "y": str(coord(y))})
        if fid in flow_label_rects:
            lx, ly, lw, lh = flow_label_rects[fid]
            lab = ET.SubElement(edge, q("bpmndi", "BPMNLabel"))
            ET.SubElement(lab, q("dc", "Bounds"), {"x": str(lx), "y": str(ly), "width": str(lw), "height": str(lh)})

    for message_flow in message_flows:
        flow_id = message_flow["id"]
        if not flow_id or flow_id in existing_extra_ids:
            continue
        source_rect = all_rects.get(message_flow["source"]) or participant_rects.get(message_flow["source"])
        target_rect = all_rects.get(message_flow["target"]) or participant_rects.get(message_flow["target"])
        if not source_rect or not target_rect:
            continue
        edge = ET.SubElement(plane, q("bpmndi", "BPMNEdge"), {"id": f"Edge_{flow_id}", "bpmnElement": flow_id})
        for x, y in route_free_edge(source_rect, target_rect):
            ET.SubElement(edge, q("di", "waypoint"), {"x": str(coord(x)), "y": str(coord(y))})

    for association in associations:
        association_id = association["id"]
        if not association_id or association_id in existing_extra_ids or association_id not in association_paths:
            continue
        edge = ET.SubElement(plane, q("bpmndi", "BPMNEdge"), {"id": f"Edge_{association_id}", "bpmnElement": association_id})
        for x, y in association_paths[association_id]:
            ET.SubElement(edge, q("di", "waypoint"), {"x": str(coord(x)), "y": str(coord(y))})

    tree.write(args.output, encoding="UTF-8", xml_declaration=True)

    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write("\n".join(report) + "\n")
    summary_payload = build_layout_summary_payload(
        final_status=final_status,
        final_mode=result["mode"],
        layout_profile_family=layout_profile_family,
        simple_postprocess_mode=args.simple_postprocess,
        budget_violations_hard=budget_violations_hard,
        metrics=metrics,
        hint_applied=hint_applied,
        layout_hint_source=layout_hint_source,
    )
    write_layout_summary(args.report_json, summary_payload)


if __name__ == "__main__":
    main()
