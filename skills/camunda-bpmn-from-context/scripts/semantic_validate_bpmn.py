#!/usr/bin/env python3
import argparse
import shlex
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict

NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
}

CAMUNDA7_NS = "http://camunda.org/schema/1.0/bpmn"
ZEEBE_NS = "http://camunda.org/schema/zeebe/1.0"


def q(tag):
    return "{" + NS["bpmn"] + "}" + tag


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
FLOW_NODE_TYPES = TASK_TYPES | GATEWAY_TYPES | EVENT_TYPES
PARTIAL_SUPPORT_TYPES = {
    "subProcess",
    "eventBasedGateway",
    "complexGateway",
    "intermediateCatchEvent",
    "intermediateThrowEvent",
    "boundaryEvent",
}
PARTIAL_AUTOGEN_TYPES = {
    "group",
    "transaction",
    "adHocSubProcess",
}
PRESERVE_ONLY_TYPES = set()
UNSUPPORTED_AUTOGEN_TYPES = {
    "choreography",
    "choreographyTask",
    "subChoreography",
    "callChoreography",
    "conversation",
    "conversationNode",
    "globalConversation",
}
PARTIAL_EVENT_DEFINITION_TYPES = {
    "errorEventDefinition",
    "escalationEventDefinition",
    "conditionalEventDefinition",
}
MANUAL_REVIEW_EVENT_DEFINITION_TYPES = {
    "terminateEventDefinition",
    "cancelEventDefinition",
    "compensateEventDefinition",
    "linkEventDefinition",
    "multipleEventDefinition",
}
VALID_FORM_BINDING_TYPES = {"deployment", "versionTag", "latest"}
VALID_LISTENER_EVENT_TYPES = {"creating", "assigning", "updating", "completing", "canceling"}
VALID_CALLED_DECISION_BINDING_TYPES = VALID_FORM_BINDING_TYPES
ALLOWED_EVENT_SUBPROCESS_START_TYPES = {
    "timerEventDefinition",
    "messageEventDefinition",
    "errorEventDefinition",
    "signalEventDefinition",
    "escalationEventDefinition",
}
SUBPROCESS_LIKE_TYPES = {"subProcess", "transaction", "adHocSubProcess"}
EMBEDDED_SCOPE_TYPES = {"embeddedSubProcess", "transaction"}


def tag_name(element):
    return element.tag.split("}")[-1]


def element_label(element):
    element_id = element.get("id")
    if element_id:
        return f"`{element_id}`"
    return f"<{tag_name(element)}>"


def ns_attr(ns_uri, local_name):
    return "{" + ns_uri + "}" + local_name


def find_extension(element, ns_uri, local_name):
    return element.find(".//" + ns_attr(ns_uri, local_name))


def has_event_definition(element, definition_names):
    return any(element.find(q(definition_name)) is not None for definition_name in definition_names)


def plain_attr_value(element, attr_name):
    value = element.get(attr_name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def find_child_text(element, child_name):
    if element is None:
        return None
    child = element.find(q(child_name))
    if child is None:
        return None
    if child.text is None:
        return None
    text = child.text.strip()
    return text or None


def build_signal_lookup(root):
    signals = {}
    for signal in root.findall(q("signal")):
        signal_id = signal.get("id")
        if signal_id:
            signals[signal_id] = signal
    return signals


def is_non_negative_integer(value):
    if value is None:
        return False
    try:
        return str(int(value)) == value.strip()
    except ValueError:
        return False


def is_non_negative_integer_or_expression(value):
    if value is None:
        return False
    value = value.strip()
    if is_feel_expression(value):
        return True
    if not is_non_negative_integer(value):
        return False
    return True


def is_int_between_zero_and_hundred(value):
    if value is None:
        return False
    value = value.strip()
    if is_feel_expression(value):
        return True
    if not is_non_negative_integer(value):
        return False
    return 0 <= int(value) <= 100


def is_feel_expression(value):
    return bool(value and value.strip().startswith("="))


def get_camunda7_extension(element, local_name):
    return plain_attr_value(element, ns_attr(CAMUNDA7_NS, local_name))


def detect_back_edges(nodes, outgoing):
    back_edges = set()
    state = {}
    for node_id in sorted(nodes.keys()):
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


def collect_duplicate_ids(root):
    counts = defaultdict(int)
    for element in root.iter():
        element_id = element.get("id")
        if element_id:
            counts[element_id] += 1
    return {element_id: count for element_id, count in counts.items() if count > 1}


def build_message_lookup(root):
    messages = {}
    for message in root.findall(q("message")):
        message_id = message.get("id")
        if message_id:
            messages[message_id] = message
    return messages


def used_namespaces(root):
    namespaces = set()
    for element in root.iter():
        if element.tag.startswith("{"):
            namespaces.add(element.tag[1:].split("}")[0])
        for attr_name in element.attrib:
            if attr_name.startswith("{"):
                namespaces.add(attr_name[1:].split("}")[0])
    return namespaces


def event_definition_elements(element):
    return [child for child in list(element) if tag_name(child).endswith("EventDefinition")]


def event_definition_names(element):
    return [tag_name(child) for child in event_definition_elements(element)]


def classify_start_event(start_event):
    definitions = event_definition_names(start_event)
    if not definitions:
        return "none"
    if len(definitions) == 1:
        return definitions[0]
    return "multiple"


def container_kind(container_element):
    tag = tag_name(container_element)
    if tag == "process":
        return "process"
    if tag == "subProcess" and container_element.get("triggeredByEvent") == "true":
        return "eventSubProcess"
    if tag == "transaction":
        return "transaction"
    if tag == "adHocSubProcess":
        return "adHocSubProcess"
    return "embeddedSubProcess"


def container_label(container):
    kind = container["kind"]
    cid = container["id"]
    if kind == "process":
        return f"process `{cid}`"
    if kind == "eventSubProcess":
        return f"event subprocess `{cid}`"
    if kind == "transaction":
        return f"transaction `{cid}`"
    if kind == "adHocSubProcess":
        return f"ad-hoc subprocess `{cid}`"
    return f"embedded subprocess `{cid}`"


def direct_start_nodes(container):
    return [node for node in container["nodes"].values() if node["type"] == "startEvent"]


def direct_end_nodes(container):
    return [node for node in container["nodes"].values() if node["type"] == "endEvent"]


def count_non_none_start_events(start_nodes):
    return sum(1 for node in start_nodes if classify_start_event(node["element"]) != "none")


def build_container_tree(process):
    process_id = process.get("id", "<anonymous-process>")
    containers = {}
    all_nodes = {}
    node_to_container = {}
    container_children = defaultdict(list)

    def register_node(container, element):
        node_id = element.get("id")
        if not node_id:
            return
        record = {
            "id": node_id,
            "type": tag_name(element),
            "name": element.get("name", ""),
            "process_id": process_id,
            "container_id": container["id"],
            "element": element,
        }
        container["nodes"][node_id] = record
        all_nodes[node_id] = record
        node_to_container[node_id] = container["id"]

    def visit(container_element, parent_container_id=None):
        cid = container_element.get("id", process_id if tag_name(container_element) == "process" else "<anonymous-container>")
        container = {
            "id": cid,
            "kind": container_kind(container_element),
            "process_id": process_id,
            "parent_id": parent_container_id,
            "element": container_element,
            "nodes": {},
            "flows": [],
        }
        containers[cid] = container
        if parent_container_id:
            container_children[parent_container_id].append(cid)

        for child in list(container_element):
            tag = tag_name(child)
            if tag == "sequenceFlow":
                flow_id = child.get("id")
                if flow_id:
                    container["flows"].append(
                        {
                            "id": flow_id,
                            "sourceRef": child.get("sourceRef"),
                            "targetRef": child.get("targetRef"),
                            "element": child,
                        }
                    )
                continue

            if tag in SUBPROCESS_LIKE_TYPES:
                if tag == "subProcess" and child.get("triggeredByEvent") == "true":
                    visit(child, cid)
                else:
                    register_node(container, child)
                    visit(child, cid)
                continue

            if tag in FLOW_NODE_TYPES:
                register_node(container, child)

        return cid

    root_container_id = visit(process, None)
    return root_container_id, containers, container_children, all_nodes, node_to_container


def collect_construct_warnings(process, process_id):
    warnings = []
    for element in process.iter():
        tag = tag_name(element)
        if tag in PARTIAL_AUTOGEN_TYPES:
            warnings.append(f"{process_id}: `{tag}` on {element_label(element)} uses partial-support generation; review manually")
        elif tag in PRESERVE_ONLY_TYPES:
            warnings.append(f"{process_id}: `{tag}` on {element_label(element)} is preserve-only; automatic generation is not supported")
        elif tag in UNSUPPORTED_AUTOGEN_TYPES:
            warnings.append(f"{process_id}: `{tag}` on {element_label(element)} is unsupported for automatic generation")
        elif tag in PARTIAL_SUPPORT_TYPES and tag != "subProcess":
            warnings.append(f"{process_id}: `{tag}` on {element_label(element)} uses partial-support generation; review manually")
        elif tag in PARTIAL_EVENT_DEFINITION_TYPES:
            warnings.append(f"{process_id}: `{tag}` on {element_label(element)} uses partial-support generation; review manually")
        elif tag in MANUAL_REVIEW_EVENT_DEFINITION_TYPES:
            warnings.append(f"{process_id}: advanced BPMN event definition `{tag}` on {element_label(element)} requires manual modeling review")

        if tag == "subProcess" and element.get("triggeredByEvent") == "true":
            warnings.append(f"{process_id}: event subprocess {element_label(element)} uses partial-support generation; review manually")

        if tag in TASK_TYPES | {"subProcess"} and element.find(q("multiInstanceLoopCharacteristics")) is not None:
            warnings.append(f"{process_id}: multi-instance semantics on {element_label(element)} require manual review")
    return warnings


def validate_container_start_rules(process_id, container, errors):
    start_nodes = direct_start_nodes(container)
    if container["kind"] == "process":
        if not start_nodes:
            errors.append(f"{process_id}: process `{container['id']}` is missing a top-level startEvent")
        return

    if container["kind"] in EMBEDDED_SCOPE_TYPES:
        if len(start_nodes) != 1:
            label = "transaction" if container["kind"] == "transaction" else "embedded subprocess"
            errors.append(f"{process_id}: {label} `{container['id']}` must have exactly one direct startEvent")
            return
        start_kind = classify_start_event(start_nodes[0]["element"])
        if start_kind == "multiple":
            label = "transaction" if container["kind"] == "transaction" else "embedded subprocess"
            errors.append(f"{process_id}: {label} `{container['id']}` startEvent has multiple event definitions")
        elif start_kind != "none":
            label = "transaction" if container["kind"] == "transaction" else "embedded subprocess"
            errors.append(f"{process_id}: {label} `{container['id']}` must use exactly one none startEvent")
        return

    if container["kind"] == "adHocSubProcess":
        return

    if len(start_nodes) != 1:
        errors.append(f"{process_id}: event subprocess `{container['id']}` must have exactly one direct startEvent")
        return
    start_kind = classify_start_event(start_nodes[0]["element"])
    if start_kind == "multiple":
        errors.append(f"{process_id}: event subprocess `{container['id']}` startEvent has multiple event definitions")
    elif start_kind not in ALLOWED_EVENT_SUBPROCESS_START_TYPES:
        errors.append(
            f"{process_id}: event subprocess `{container['id']}` startEvent must be timer/message/error/signal/escalation, not `{start_kind}`"
        )


def validate_container_graph(process_id, container, all_nodes, errors):
    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    sequence_by_id = {}
    nodes = container["nodes"]

    for flow in container["flows"]:
        flow_id = flow["id"]
        sequence_by_id[flow_id] = flow
        source_ref = flow.get("sourceRef")
        target_ref = flow.get("targetRef")

        if not source_ref:
            errors.append(f"{process_id}: {flow_id} has invalid sourceRef")
        elif source_ref not in nodes:
            if source_ref in all_nodes:
                errors.append(f"{process_id}: {flow_id} sourceRef `{source_ref}` crosses the boundary of {container_label(container)}")
            else:
                errors.append(f"{process_id}: {flow_id} has invalid sourceRef")

        if not target_ref:
            errors.append(f"{process_id}: {flow_id} has invalid targetRef")
        elif target_ref not in nodes:
            if target_ref in all_nodes:
                errors.append(f"{process_id}: {flow_id} targetRef `{target_ref}` crosses the boundary of {container_label(container)}")
            else:
                errors.append(f"{process_id}: {flow_id} has invalid targetRef")

        if source_ref in nodes and target_ref in nodes:
            outgoing[source_ref].append(flow)
            incoming[target_ref].append(flow)

    return sequence_by_id, incoming, outgoing


def validate_boundary_event(process_id, element_id, element, sibling_nodes, errors):
    attached_to = element.get("attachedToRef")
    if not attached_to:
        errors.append(f"{process_id}: boundaryEvent `{element_id}` is missing attachedToRef")
        return
    if attached_to not in sibling_nodes:
        errors.append(f"{process_id}: boundaryEvent `{element_id}` attachedToRef `{attached_to}` does not exist in the same container")
        return
    host_tag = sibling_nodes[attached_to]["type"]
    if host_tag in {"startEvent", "endEvent", "boundaryEvent"}:
        errors.append(f"{process_id}: boundaryEvent `{element_id}` attachedToRef `{attached_to}` is not a valid host")


def validate_message_definition(
    process_id,
    owner_id,
    definition_element,
    messages,
    errors,
    require_name=False,
    require_subscription=False,
):
    message_ref = plain_attr_value(definition_element, "messageRef")
    if not message_ref:
        errors.append(f"{process_id}: `{owner_id}` messageEventDefinition is missing messageRef")
        return None
    message = messages.get(message_ref)
    if message is None:
        errors.append(f"{process_id}: `{owner_id}` references missing message `{message_ref}`")
        return None
    if require_name and not plain_attr_value(message, "name"):
        errors.append(f"{process_id}: `{owner_id}` referenced message `{message_ref}` is missing name")
    if require_subscription:
        subscription = find_extension(message, ZEEBE_NS, "subscription")
        if subscription is None:
            errors.append(f"{process_id}: `{owner_id}` referenced message `{message_ref}` is missing zeebe:subscription")
        elif not plain_attr_value(subscription, "correlationKey"):
            errors.append(f"{process_id}: `{owner_id}` referenced message `{message_ref}` zeebe:subscription is missing correlationKey")
    return message


def validate_signal_definition(process_id, owner_id, definition_element, signals, errors):
    signal_ref = plain_attr_value(definition_element, "signalRef")
    if not signal_ref:
        errors.append(f"{process_id}: `{owner_id}` signalEventDefinition is missing signalRef")
        return None
    signal = signals.get(signal_ref)
    if signal is None:
        errors.append(f"{process_id}: `{owner_id}` references missing signal `{signal_ref}`")
        return None
    if not plain_attr_value(signal, "name"):
        errors.append(f"{process_id}: `{owner_id}` references signal `{signal_ref}` is missing name")
    return signal


def trigger_uniqueness_scope(container, node):
    node_type = node.get("type")
    if node_type == "startEvent":
        return f"start scope of {container_label(container)}"
    if node_type == "boundaryEvent":
        host_id = node["element"].get("attachedToRef") or "<unattached>"
        return f"boundary scope of {container_label(container)} host `{host_id}`"
    return None


def validate_start_boundary_trigger_name_unique(process_id, container, node, trigger_name, trigger_type, seen_names, errors):
    scope_label = trigger_uniqueness_scope(container, node)
    if not scope_label or not trigger_name:
        return
    validate_trigger_name_unique(process_id, scope_label, trigger_name, trigger_type, node["id"], seen_names, errors)


def validate_trigger_name_unique(process_id, scope_label, trigger_name, trigger_type, node_id, seen_names, errors):
    scope_seen = seen_names.setdefault(scope_label, {})
    seen = scope_seen.setdefault(trigger_type, {})
    if trigger_name in seen:
        errors.append(
            f"{process_id}: duplicate {trigger_type} `{trigger_name}` in {scope_label} between events "
            f"`{seen[trigger_name]}` and `{node_id}`"
        )
        return
    seen[trigger_name] = node_id


def timer_definition_values(timer_definition):
    values = []
    for child_name in ("timeDate", "timeDuration", "timeCycle"):
        child = timer_definition.find(q(child_name))
        if child is not None and (child.text or "").strip():
            values.append(child_name)
    return values


def validate_timer_definition(process_id, context, node, timer_definition, errors):
    node_type = node["type"]
    node_id = node["id"]
    container_kind_name = context.get("kind") if isinstance(context, dict) else context

    is_event_based_target = (
        isinstance(context, dict) and context.get("kind") == "eventBasedGatewayTarget"
    ) or context == "eventBasedGatewayTarget"

    if node_type not in {"startEvent", "intermediateCatchEvent", "boundaryEvent"}:
        return

    values = timer_definition_values(timer_definition)
    if len(values) != 1:
        errors.append(
            f"{process_id}: `{node_id}` timerEventDefinition must define exactly one of timeDate/timeDuration/timeCycle"
        )
        return

    timer_value = values[0]
    element = node["element"]

    if node_type == "startEvent":
        if container_kind_name not in {"process", "eventSubProcess"}:
            errors.append(f"{process_id}: startEvent `{node_id}` timerEventDefinition must have a process-level scope")
            return
        if timer_value not in {"timeDate", "timeCycle"}:
            errors.append(f"{process_id}: startEvent `{node_id}` timerEventDefinition must use timeDate or timeCycle")
        return

    if node_type == "intermediateCatchEvent" or is_event_based_target:
        if timer_value not in {"timeDate", "timeDuration"}:
            errors.append(
                f"{process_id}: intermediateCatchEvent `{node_id}` timerEventDefinition for event-based waits must use timeDate or timeDuration"
            )
        return

    if node_type == "boundaryEvent":
        is_non_interrupting = element.get("cancelActivity") == "false"
        if is_non_interrupting:
            if timer_value not in {"timeDate", "timeDuration", "timeCycle"}:
                errors.append(
                    f"{process_id}: boundaryEvent `{node_id}` timerEventDefinition cannot use `{timer_value}` in non-interrupting mode"
                )
            return
        if timer_value not in {"timeDate", "timeDuration"}:
            errors.append(
                f"{process_id}: boundaryEvent `{node_id}` timerEventDefinition must use timeDate or timeDuration when interrupting"
            )


def validate_event_semantics(process_id, container, node, messages, signals, seen_trigger_names, errors, camunda_version):
    definitions = event_definition_elements(node["element"])
    if len(definitions) > 1:
        errors.append(f"{process_id}: `{node['id']}` has multiple event definitions")
        return
    if not definitions:
        return

    definition = definitions[0]
    definition_tag = tag_name(definition)
    node_id = node["id"]
    node_type = node["type"]
    if definition_tag == "messageEventDefinition":
        message = validate_message_definition(
            process_id,
            node_id,
            definition,
            messages,
            errors,
            require_name=camunda_version == "8",
            require_subscription=(camunda_version == "8" and node_type != "startEvent"),
        )
        if camunda_version == "8" and message is not None:
            message_name = plain_attr_value(message, "name")
            if node_type in {"startEvent", "boundaryEvent"}:
                validate_start_boundary_trigger_name_unique(
                    process_id,
                    container,
                    node,
                    message_name,
                    "message",
                    seen_trigger_names,
                    errors,
                )
    elif definition_tag == "timerEventDefinition":
        validate_timer_definition(process_id, container, node, definition, errors)
    elif definition_tag == "errorEventDefinition":
        if node_type == "boundaryEvent" and node["element"].get("cancelActivity") == "false":
            errors.append(f"{process_id}: error boundaryEvent `{node_id}` must be interrupting")
        if node_type == "startEvent" and container["kind"] == "eventSubProcess" and node["element"].get("isInterrupting") == "false":
            errors.append(f"{process_id}: error event subprocess `{container['id']}` must be interrupting")
    elif definition_tag == "signalEventDefinition":
        signal = validate_signal_definition(
            process_id,
            node_id,
            definition,
            signals,
            errors,
        )
        if camunda_version == "8" and signal is not None:
            signal_name = plain_attr_value(signal, "name")
            if node_type in {"startEvent", "boundaryEvent"}:
                validate_start_boundary_trigger_name_unique(
                    process_id,
                    container,
                    node,
                    signal_name,
                    "signal",
                    seen_trigger_names,
                    errors,
                )


def validate_error_catch_uniqueness(process_id, container, containers, children, errors):
    seen_error_refs = set()
    catch_all_seen = False

    def register(error_ref, owner_label):
        nonlocal catch_all_seen
        if error_ref:
            if error_ref in seen_error_refs:
                errors.append(f"{process_id}: duplicate error catch for errorRef `{error_ref}` in the scope of {container_label(container)}")
            seen_error_refs.add(error_ref)
        else:
            if catch_all_seen:
                errors.append(f"{process_id}: multiple error catch-all events exist in the scope of {container_label(container)}")
            catch_all_seen = True

    for node in container["nodes"].values():
        if node["type"] != "boundaryEvent":
            continue
        definitions = event_definition_elements(node["element"])
        if len(definitions) == 1 and tag_name(definitions[0]) == "errorEventDefinition":
            register(plain_attr_value(definitions[0], "errorRef"), node["id"])

    for child_id in children.get(container["id"], []):
        child = containers[child_id]
        if child["kind"] != "eventSubProcess":
            continue
        start_nodes = direct_start_nodes(child)
        if len(start_nodes) != 1:
            continue
        definitions = event_definition_elements(start_nodes[0]["element"])
        if len(definitions) == 1 and tag_name(definitions[0]) == "errorEventDefinition":
            register(plain_attr_value(definitions[0], "errorRef"), child_id)


def validate_camunda7_profile(process_id, element_id, tag, element, errors, warnings):
    if tag == "serviceTask":
        implementation_attrs = [
            plain_attr_value(element, ns_attr(CAMUNDA7_NS, attr))
            for attr in ("class", "delegateExpression", "type", "expression")
        ]
        has_impl = any(implementation_attrs)
        impl_count = sum(1 for value in implementation_attrs if value)
        if impl_count > 1:
            errors.append(
                f"{process_id}: Camunda 7 serviceTask `{element_id}` defines multiple execution implementation attributes"
            )
        elif not has_impl:
            errors.append(f"{process_id}: Camunda 7 serviceTask `{element_id}` is missing execution implementation attributes")
        if impl_count == 0:
            return

        task_type = plain_attr_value(element, ns_attr(CAMUNDA7_NS, "type"))
        topic = plain_attr_value(element, ns_attr(CAMUNDA7_NS, "topic"))
        if task_type == "external" and not topic:
            errors.append(f"{process_id}: Camunda 7 external serviceTask `{element_id}` is missing camunda:topic")
        elif task_type != "external" and topic:
            errors.append(f"{process_id}: Camunda 7 serviceTask `{element_id}` sets camunda:topic but type is not `external`")
        if plain_attr_value(element, ns_attr(CAMUNDA7_NS, "resultVariable")) and not plain_attr_value(
            element, ns_attr(CAMUNDA7_NS, "expression")
        ):
            errors.append(f"{process_id}: Camunda 7 serviceTask `{element_id}` sets camunda:resultVariable without camunda:expression")
        if plain_attr_value(element, ns_attr(CAMUNDA7_NS, "taskPriority")) and task_type != "external":
            errors.append(f"{process_id}: Camunda 7 serviceTask `{element_id}` sets camunda:taskPriority but type is not `external`")

    if tag == "userTask":
        if plain_attr_value(element, ns_attr(CAMUNDA7_NS, "assignee")) and element.find(q("humanPerformer")) is not None:
            errors.append(f"{process_id}: Camunda 7 userTask `{element_id}` uses both camunda:assignee and humanPerformer")
        has_assignment = any(
            element.get(ns_attr(CAMUNDA7_NS, attr))
            for attr in ("assignee", "candidateUsers", "candidateGroups")
        )
        has_form = bool(element.get(ns_attr(CAMUNDA7_NS, "formKey")))
        form_data_count = len(element.findall(f"{q('extensionElements')}/{ns_attr(CAMUNDA7_NS, 'formData')}"))
        if form_data_count > 1:
            errors.append(f"{process_id}: Camunda 7 userTask `{element_id}` has multiple camunda:formData entries")
        if not (has_assignment or has_form):
            warnings.append(f"{process_id}: Camunda 7 userTask `{element_id}` has no assignment or form metadata")


def validate_camunda8_user_task(process_id, element_id, element, errors, warnings):
    has_user_task = find_extension(element, ZEEBE_NS, "userTask") is not None
    task_definition = find_extension(element, ZEEBE_NS, "taskDefinition")
    priority_definition = find_extension(element, ZEEBE_NS, "priorityDefinition")
    form_definition = find_extension(element, ZEEBE_NS, "formDefinition")
    assignment_definition = find_extension(element, ZEEBE_NS, "assignmentDefinition")
    task_schedule = find_extension(element, ZEEBE_NS, "taskSchedule")
    task_listeners = find_extension(element, ZEEBE_NS, "taskListeners")
    task_headers = find_extension(element, ZEEBE_NS, "taskHeaders")

    if has_user_task:
        if task_definition is not None:
            warnings.append(
                f"{process_id}: Camunda 8 userTask `{element_id}` mixes zeebe:userTask and legacy/job-worker taskDefinition metadata"
            )
    else:
        if task_definition is not None:
            warnings.append(f"{process_id}: Camunda 8 userTask `{element_id}` uses legacy/job-worker implementation; review manually")
        else:
            warnings.append(f"{process_id}: Camunda 8 userTask `{element_id}` is missing zeebe:userTask metadata")

    if task_definition is not None:
        task_definition_type = plain_attr_value(task_definition, "type")
        if not task_definition_type:
            errors.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:taskDefinition is missing type")
        retries = plain_attr_value(task_definition, "retries")
        if retries is not None and retries != "" and not (
            is_feel_expression(retries) or (is_non_negative_integer(retries) and int(retries) >= 0)
        ):
            errors.append(
                f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:taskDefinition retries must be non-negative integer or FEEL expression"
            )

    if priority_definition is not None:
        priority = plain_attr_value(priority_definition, "priority")
        if priority is None:
            warnings.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:priorityDefinition is missing priority")
        elif not is_int_between_zero_and_hundred(priority):
            errors.append(
                f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:priorityDefinition priority must be integer 0..100 or FEEL expression"
            )

    if form_definition is None:
        warnings.append(f"{process_id}: Camunda 8 userTask `{element_id}` has no zeebe:formDefinition")
    else:
        if not any(plain_attr_value(form_definition, attr) for attr in ("formId", "externalReference", "formKey")):
            warnings.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:formDefinition has no formId/externalReference/formKey")
        binding = plain_attr_value(form_definition, "bindingType") or plain_attr_value(form_definition, "binding")
        version_tag = plain_attr_value(form_definition, "versionTag")
        if binding is not None and binding not in VALID_FORM_BINDING_TYPES:
            errors.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:formDefinition has invalid bindingType `{binding}`")
        if binding == "versionTag" and not version_tag:
            errors.append(
                f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:formDefinition uses bindingType=versionTag but is missing versionTag"
            )
        if binding is None and version_tag:
            errors.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:formDefinition has versionTag but no bindingType")

    if assignment_definition is not None and not any(
        plain_attr_value(assignment_definition, attr) for attr in ("assignee", "candidateUsers", "candidateGroups")
    ):
        errors.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:assignmentDefinition is empty")

    if task_schedule is not None and not any(
        plain_attr_value(task_schedule, attr) for attr in ("dueDate", "followUpDate")
    ):
        errors.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:taskSchedule is empty")

    if task_listeners is not None:
        listeners = task_listeners.findall(ns_attr(ZEEBE_NS, "taskListener"))
        if not listeners:
            errors.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:taskListeners has no taskListener entries")
        for listener in listeners:
            event_type = plain_attr_value(listener, "eventType")
            if not event_type:
                errors.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:taskListener is missing eventType")
            elif event_type not in VALID_LISTENER_EVENT_TYPES:
                errors.append(
                    f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:taskListener has invalid eventType `{event_type}`"
                )
            if not plain_attr_value(listener, "type"):
                errors.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:taskListener is missing type")
            retries = listener.get("retries")
            if retries is not None and not retries.strip():
                errors.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:taskListener has blank retries")
            if retries is not None and retries.strip() and not (
                is_feel_expression(retries.strip()) or (is_non_negative_integer(retries.strip()) and int(retries.strip()) >= 0)
            ):
                errors.append(
                    f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:taskListener retries must be non-negative integer or FEEL expression"
                )

    if task_headers is not None:
        headers = task_headers.findall(ns_attr(ZEEBE_NS, "header"))
        if not headers:
            errors.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:taskHeaders has no header entries")
        seen_keys = set()
        for header in headers:
            header_key = plain_attr_value(header, "key")
            if not header_key:
                errors.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:taskHeader is missing key")
                continue
            if header_key in seen_keys:
                errors.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:taskHeader has duplicate key `{header_key}`")
            seen_keys.add(header_key)
            if not plain_attr_value(header, "value"):
                errors.append(f"{process_id}: Camunda 8 userTask `{element_id}` zeebe:taskHeader is missing value")


def validate_event_based_gateway_targets(process_id, element_id, outgoing_flows, nodes, messages, errors):
    for flow in outgoing_flows:
        target_ref = flow.get("targetRef")
        target = nodes.get(target_ref)
        if target is None:
            continue
        target_tag = target["type"]
        if target_tag != "intermediateCatchEvent":
            errors.append(
                f"{process_id}: Camunda 8 eventBasedGateway `{element_id}` must lead to intermediateCatchEvent, not `{target_tag}`"
            )
            continue
        definitions = event_definition_elements(target["element"])
        if len(definitions) != 1:
            errors.append(f"{process_id}: Camunda 8 eventBasedGateway `{element_id}` target `{target_ref}` must have exactly one event definition")
            continue
        definition = definitions[0]
        definition_tag = tag_name(definition)
        if definition_tag == "messageEventDefinition":
            validate_message_definition(
                process_id,
                target_ref,
                definition,
                messages,
                errors,
                require_name=True,
                require_subscription=True,
            )
        elif definition_tag == "timerEventDefinition":
            validate_timer_definition(process_id, {"kind": "eventBasedGatewayTarget"}, target, definition, errors)
        elif definition_tag != "signalEventDefinition":
            errors.append(
                f"{process_id}: Camunda 8 eventBasedGateway `{element_id}` target `{target_ref}` needs message/timer/signal event definition"
            )


def validate_camunda8_profile(process_id, element_id, tag, element, container, incoming_count, outgoing_flows, nodes, messages, errors, warnings):
    task_definition = find_extension(element, ZEEBE_NS, "taskDefinition")
    called_decision = find_extension(element, ZEEBE_NS, "calledDecision")
    script_extension = find_extension(element, ZEEBE_NS, "script")

    if tag in {"serviceTask", "sendTask"} and task_definition is None:
        errors.append(f"{process_id}: Camunda 8 {tag} `{element_id}` is missing zeebe:taskDefinition")
    if tag in {"serviceTask", "sendTask"}:
        if task_definition is not None and not plain_attr_value(task_definition, "type"):
            errors.append(f"{process_id}: Camunda 8 {tag} `{element_id}` zeebe:taskDefinition is missing type")
        if task_definition is not None:
            retries = plain_attr_value(task_definition, "retries")
            if retries is not None and retries != "" and not (
                is_feel_expression(retries) or (is_non_negative_integer(retries) and int(retries) >= 0)
            ):
                errors.append(
                    f"{process_id}: Camunda 8 {tag} `{element_id}` zeebe:taskDefinition retries must be non-negative integer or FEEL expression"
                )

    if tag == "receiveTask":
        message_ref = plain_attr_value(element, "messageRef")
        if not message_ref:
            errors.append(f"{process_id}: Camunda 8 receiveTask `{element_id}` is missing messageRef")
        else:
            message = messages.get(message_ref)
            if message is None:
                errors.append(f"{process_id}: Camunda 8 receiveTask `{element_id}` messageRef `{message_ref}` does not exist")
            else:
                if not plain_attr_value(message, "name"):
                    errors.append(f"{process_id}: Camunda 8 receiveTask `{element_id}` referenced message `{message_ref}` is missing name")
                subscription = find_extension(message, ZEEBE_NS, "subscription")
                if subscription is None:
                    errors.append(f"{process_id}: Camunda 8 receiveTask `{element_id}` referenced message `{message_ref}` is missing zeebe:subscription")
                elif not plain_attr_value(subscription, "correlationKey"):
                    errors.append(f"{process_id}: Camunda 8 receiveTask `{element_id}` referenced message `{message_ref}` zeebe:subscription is missing correlationKey")

    if tag == "businessRuleTask" and not (called_decision is not None or task_definition is not None):
        errors.append(f"{process_id}: Camunda 8 businessRuleTask `{element_id}` needs zeebe:calledDecision or zeebe:taskDefinition")
    if tag == "businessRuleTask" and called_decision is not None:
        if not plain_attr_value(called_decision, "decisionId"):
            errors.append(f"{process_id}: Camunda 8 businessRuleTask `{element_id}` zeebe:calledDecision is missing decisionId")
        if not plain_attr_value(called_decision, "resultVariable"):
            errors.append(f"{process_id}: Camunda 8 businessRuleTask `{element_id}` zeebe:calledDecision is missing resultVariable")
        binding = plain_attr_value(called_decision, "bindingType") or plain_attr_value(called_decision, "binding")
        version_tag = plain_attr_value(called_decision, "versionTag")
        if binding is not None and binding not in VALID_CALLED_DECISION_BINDING_TYPES:
            errors.append(
                f"{process_id}: Camunda 8 businessRuleTask `{element_id}` zeebe:calledDecision has invalid bindingType `{binding}`"
            )
        if binding == "versionTag" and not version_tag:
            errors.append(
                f"{process_id}: Camunda 8 businessRuleTask `{element_id}` zeebe:calledDecision uses bindingType=versionTag but is missing versionTag"
            )
        if binding is None and version_tag:
            errors.append(
                f"{process_id}: Camunda 8 businessRuleTask `{element_id}` zeebe:calledDecision has versionTag but no bindingType"
            )
    if tag == "businessRuleTask" and task_definition is not None and not plain_attr_value(task_definition, "type"):
        errors.append(f"{process_id}: Camunda 8 businessRuleTask `{element_id}` zeebe:taskDefinition is missing type")

    if tag == "scriptTask" and not (script_extension is not None or task_definition is not None):
        errors.append(f"{process_id}: Camunda 8 scriptTask `{element_id}` needs zeebe:script or zeebe:taskDefinition")
    if tag == "scriptTask" and script_extension is not None:
        if not plain_attr_value(script_extension, "expression"):
            errors.append(f"{process_id}: Camunda 8 scriptTask `{element_id}` zeebe:script is missing expression")
        if not plain_attr_value(script_extension, "resultVariable"):
            errors.append(f"{process_id}: Camunda 8 scriptTask `{element_id}` zeebe:script is missing resultVariable")
        if task_definition is not None:
            errors.append(f"{process_id}: Camunda 8 scriptTask `{element_id}` cannot define both zeebe:script and zeebe:taskDefinition")
    if tag == "scriptTask" and task_definition is not None and not plain_attr_value(task_definition, "type"):
        errors.append(f"{process_id}: Camunda 8 scriptTask `{element_id}` zeebe:taskDefinition is missing type")
    if tag == "scriptTask" and task_definition is not None:
        headers = element.find("./" + ns_attr(ZEEBE_NS, "taskHeaders"))
        if headers is not None:
            task_headers = headers.findall(ns_attr(ZEEBE_NS, "header"))
            for header in task_headers:
                header_key = plain_attr_value(header, "key")
                header_value = plain_attr_value(header, "value")
                if not header_key:
                    errors.append(f"{process_id}: Camunda 8 scriptTask `{element_id}` zeebe:taskHeader is missing key")
                if not header_value:
                    errors.append(f"{process_id}: Camunda 8 scriptTask `{element_id}` zeebe:taskHeader is missing value")

    if tag == "userTask":
        validate_camunda8_user_task(process_id, element_id, element, errors, warnings)

    if tag == "eventBasedGateway":
        if len(outgoing_flows) < 2:
            errors.append(f"{process_id}: {element_id} has insufficient outgoing sequenceFlow")
        validate_event_based_gateway_targets(process_id, element_id, outgoing_flows, nodes, messages, errors)


def validate_collaboration(root, process_ids, participant_ids, known_node_ids, node_to_participant, errors, warnings):
    message_flows = []
    for collaboration in root.findall(q("collaboration")):
        for participant in collaboration.findall(q("participant")):
            participant_id = participant.get("id", "<anonymous-participant>")
            process_ref = participant.get("processRef")
            if process_ref and process_ref not in process_ids:
                errors.append(f"{participant_id}: participant processRef `{process_ref}` does not exist")
            elif not process_ref:
                warnings.append(f"{participant_id}: participant has no processRef and is treated as a black-box participant")
        message_flows.extend(collaboration.findall(q("messageFlow")))

    valid_message_refs = set(participant_ids) | set(known_node_ids)
    for message_flow in message_flows:
        flow_id = message_flow.get("id", "<anonymous-messageFlow>")
        source_ref = message_flow.get("sourceRef")
        target_ref = message_flow.get("targetRef")
        if not source_ref or source_ref not in valid_message_refs:
            errors.append(f"{flow_id}: invalid messageFlow sourceRef")
            continue
        if not target_ref or target_ref not in valid_message_refs:
            errors.append(f"{flow_id}: invalid messageFlow targetRef")
            continue

        source_participant = source_ref if source_ref in participant_ids else node_to_participant.get(source_ref)
        target_participant = target_ref if target_ref in participant_ids else node_to_participant.get(target_ref)

        if not source_participant or not target_participant:
            warnings.append(f"{flow_id}: messageFlow endpoint is not mapped to a participant")
            continue
        if source_participant == target_participant:
            errors.append(f"{flow_id}: messageFlow must cross participant boundaries")


def validate_process(process, analysis_mode, detail_level, camunda_version, messages, signals, errors, warnings):
    process_id = process.get("id", "<anonymous-process>")
    root_container_id, containers, children, all_nodes, node_to_container = build_container_tree(process)
    root_container = containers[root_container_id]

    warnings.extend(collect_construct_warnings(process, process_id))
    seen_start_boundary_names = {}

    flow_node_count = len(all_nodes)
    if flow_node_count < 3:
        warnings.append(f"{process_id}: process has fewer than 3 flow nodes")
    if detail_level == "overview" and flow_node_count > 15:
        warnings.append(f"{process_id}: overview detail level exceeded with {flow_node_count} flow nodes")
    elif detail_level == "detailed" and flow_node_count > 35:
        warnings.append(f"{process_id}: detailed level exceeded with {flow_node_count} flow nodes; consider decomposition")
    elif detail_level == "technical" and flow_node_count < 8:
        warnings.append(f"{process_id}: technical detail level selected, but the process may be too coarse with only {flow_node_count} flow nodes")

    for container in containers.values():
        validate_container_start_rules(process_id, container, errors)
        if container["kind"] == "process" and not direct_end_nodes(container):
            warnings.append(f"{process_id}: missing endEvent")

        sequence_by_id, incoming, outgoing = validate_container_graph(process_id, container, all_nodes, errors)

        graph = {node_id: [] for node_id in container["nodes"]}
        for flow in container["flows"]:
            source_ref = flow.get("sourceRef")
            target_ref = flow.get("targetRef")
            if source_ref in container["nodes"] and target_ref in container["nodes"]:
                graph[source_ref].append(target_ref)
        back_edges = detect_back_edges(container["nodes"], graph)
        if back_edges:
            warnings.append(f"{process_id}: detected {len(back_edges)} loop back-edge(s) in {container_label(container)}")

        for element_id, node in sorted(container["nodes"].items()):
            tag = node["type"]
            element = node["element"]
            incoming_count = len(incoming[element_id])
            outgoing_flows = outgoing[element_id]
            outgoing_count = len(outgoing_flows)
            skip_flow_connectivity_warnings = container["kind"] == "adHocSubProcess"

            if tag in TASK_TYPES and not (element.get("name") or "").strip():
                warnings.append(f"{process_id}: task `{element_id}` is missing a name")

            if analysis_mode == "to-be" and tag == "manualTask":
                warnings.append(f"{process_id}: manualTask `{element_id}` appears in TO-BE mode; justify it or convert it")

            if tag == "boundaryEvent":
                validate_boundary_event(process_id, element_id, element, container["nodes"], errors)

            if not skip_flow_connectivity_warnings and tag not in {"startEvent", "boundaryEvent"} and incoming_count == 0:
                warnings.append(f"{process_id}: `{element_id}` has no incoming sequenceFlow")
            if (
                not skip_flow_connectivity_warnings
                and tag != "endEvent"
                and outgoing_count == 0
                and not (tag == "subProcess" and node["element"].get("triggeredByEvent") == "true")
            ):
                warnings.append(f"{process_id}: `{element_id}` has no outgoing sequenceFlow")

            validate_event_semantics(
                process_id, container, node, messages, signals, seen_start_boundary_names, errors, camunda_version
            )

            if tag in GATEWAY_TYPES:
                default_flow = element.get("default")
                outgoing_flow_ids = {flow.get("id") for flow in outgoing_flows if flow.get("id")}
                if default_flow and default_flow not in sequence_by_id:
                    errors.append(f"{process_id}: gateway `{element_id}` default flow `{default_flow}` does not exist")
                elif default_flow and default_flow not in outgoing_flow_ids:
                    errors.append(f"{process_id}: gateway `{element_id}` default flow `{default_flow}` is not an outgoing sequenceFlow")

                if tag == "exclusiveGateway":
                    if outgoing_count < 2 and not (outgoing_count == 1 and default_flow):
                        errors.append(f"{process_id}: {element_id} has insufficient outgoing sequenceFlow")
                elif tag == "eventBasedGateway" and camunda_version != "8" and outgoing_count < 2:
                    warnings.append(f"{process_id}: {element_id} has fewer than 2 outgoing sequenceFlow")
                elif tag in {"parallelGateway", "inclusiveGateway"} and outgoing_count < 2:
                    warnings.append(f"{process_id}: {element_id} has fewer than 2 outgoing sequenceFlow")

                if tag in {"exclusiveGateway", "inclusiveGateway"} and outgoing_count > 1:
                    for flow in outgoing_flows:
                        flow_id = flow.get("id", "<anonymous-sequenceFlow>")
                        if flow_id == default_flow:
                            continue
                        has_name = bool((flow["element"].get("name") or "").strip())
                        condition = flow["element"].find(q("conditionExpression"))
                        has_condition = bool(condition is not None and (condition.text or "").strip())
                        if not has_name and not has_condition:
                            warnings.append(
                                f"{process_id}: outgoing branch `{flow_id}` from gateway `{element_id}` has no name or conditionExpression"
                            )

            if camunda_version == "7":
                validate_camunda7_profile(process_id, element_id, tag, element, errors, warnings)
            elif camunda_version == "8":
                validate_camunda8_profile(
                    process_id,
                    element_id,
                    tag,
                    element,
                    container,
                    incoming_count,
                    outgoing_flows,
                    container["nodes"],
                    messages,
                    errors,
                    warnings,
                )

        validate_error_catch_uniqueness(process_id, container, containers, children, errors)

    return all_nodes, node_to_container


def build_participant_lookup(root, processes):
    process_ids = {process.get("id") for process in processes if process.get("id")}
    participant_ids = set()
    node_to_participant = {}
    known_node_ids = set()

    process_to_participant = {}
    for collaboration in root.findall(q("collaboration")):
        for participant in collaboration.findall(q("participant")):
            participant_id = participant.get("id")
            process_ref = participant.get("processRef")
            if participant_id:
                participant_ids.add(participant_id)
            if participant_id and process_ref and process_ref in process_ids:
                process_to_participant[process_ref] = participant_id

    for process in processes:
        process_id = process.get("id")
        participant_id = process_to_participant.get(process_id)
        _, _, _, all_nodes, _ = build_container_tree(process)
        for node_id in all_nodes:
            known_node_ids.add(node_id)
            if participant_id:
                node_to_participant[node_id] = participant_id

    return process_ids, participant_ids, known_node_ids, node_to_participant


def dedupe_messages(messages):
    seen = set()
    unique = []
    for message in messages:
        if message in seen:
            continue
        seen.add(message)
        unique.append(message)
    return unique


def validate_bpmn(path, analysis_mode="unspecified", detail_level="detailed", camunda_version="unspecified"):
    root = ET.parse(path).getroot()
    processes = root.findall(q("process"))
    errors = []
    warnings = []

    duplicate_ids = collect_duplicate_ids(root)
    for element_id, count in sorted(duplicate_ids.items()):
        errors.append(f"Duplicate id `{element_id}` appears {count} times")

    if not processes:
        errors.append("No bpmn:process found")
        return errors, warnings

    namespaces = used_namespaces(root)
    if camunda_version == "7":
        if ZEEBE_NS in namespaces:
            errors.append("Camunda 7 target selected, but zeebe:* extensions are present")
        elif CAMUNDA7_NS not in namespaces:
            warnings.append("Camunda 7 target selected, but no camunda:* extensions were found; output may be documentation-only")
    elif camunda_version == "8":
        if CAMUNDA7_NS in namespaces:
            errors.append("Camunda 8 target selected, but camunda:* extensions are present")
        elif ZEEBE_NS not in namespaces:
            warnings.append("Camunda 8 target selected, but no zeebe:* extensions were found; output may be documentation-only")

    messages = build_message_lookup(root)
    signals = build_signal_lookup(root)
    for process in processes:
        validate_process(process, analysis_mode, detail_level, camunda_version, messages, signals, errors, warnings)

    process_ids, participant_ids, known_node_ids, node_to_participant = build_participant_lookup(root, processes)
    validate_collaboration(root, process_ids, participant_ids, known_node_ids, node_to_participant, errors, warnings)

    return dedupe_messages(errors), dedupe_messages(warnings)


def main():
    parser = argparse.ArgumentParser(description="Run lightweight BPMN semantic validation")
    parser.add_argument("input")
    parser.add_argument("--analysis-mode", choices=["unspecified", "as-is", "to-be"], default="unspecified")
    parser.add_argument("--detail-level", choices=["overview", "detailed", "technical"], default="detailed")
    parser.add_argument("--camunda-version", choices=["unspecified", "7", "8"], default="unspecified")
    args = parser.parse_args()

    errors, warnings = validate_bpmn(
        args.input,
        analysis_mode=args.analysis_mode,
        detail_level=args.detail_level,
        camunda_version=args.camunda_version,
    )

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")

    if errors:
        raise SystemExit(1)
    print("BPMN semantic validation passed")


if __name__ == "__main__":
    main()
