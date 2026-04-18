#!/usr/bin/env python3
from __future__ import annotations
import argparse
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

NAMED_ARG_RE = re.compile(r"^\$?[A-Za-z_][A-Za-z0-9_]*$")

INCLUDE_TO_TYPE = {
    "C4_Context": "context",
    "C4_Container": "container",
    "C4_Component": "component",
    "C4_Dynamic": "dynamic",
    "C4_Deployment": "deployment",
    "C4_Sequence": "sequence",
}

PERSON_MACROS = {"Person", "Person_Ext"}
SYSTEM_MACROS = {
    "System",
    "SystemDb",
    "SystemQueue",
    "System_Ext",
    "SystemDb_Ext",
    "SystemQueue_Ext",
}
CONTAINER_MACROS = {
    "Container",
    "ContainerDb",
    "ContainerQueue",
    "Container_Ext",
    "ContainerDb_Ext",
    "ContainerQueue_Ext",
}
COMPONENT_MACROS = {
    "Component",
    "ComponentDb",
    "ComponentQueue",
    "Component_Ext",
    "ComponentDb_Ext",
    "ComponentQueue_Ext",
}
BOUNDARY_MACROS = {
    "Boundary",
    "Enterprise_Boundary",
    "System_Boundary",
    "Container_Boundary",
}
NODE_MACROS = {
    "Deployment_Node",
    "Deployment_Node_L",
    "Deployment_Node_R",
    "Node",
    "Node_L",
    "Node_R",
}
ALL_ELEMENT_MACROS = PERSON_MACROS | SYSTEM_MACROS | CONTAINER_MACROS | COMPONENT_MACROS | BOUNDARY_MACROS | NODE_MACROS
TECH_REQUIRED_MACROS = CONTAINER_MACROS | COMPONENT_MACROS
GENERIC_RELATIONSHIP_LABELS = {
    "uses",
    "use",
    "calls",
    "reads",
    "writes",
    "gets",
    "sends",
    "updates",
    "invokes",
    "communicates with",
}
TITLE_KEYWORDS = {
    "context": {"context", "landscape"},
    "container": {"container"},
    "component": {"component"},
    "dynamic": {"dynamic"},
    "deployment": {"deployment"},
}
INVALID_REL_ENDPOINT_MACROS = BOUNDARY_MACROS | NODE_MACROS
STATIC_RELATIONSHIP_MACROS = {
    "Rel",
    "BiRel",
    "Rel_U",
    "Rel_Up",
    "Rel_D",
    "Rel_Down",
    "Rel_L",
    "Rel_Left",
    "Rel_R",
    "Rel_Right",
    "Rel_Back",
    "Rel_Back_Neighbor",
    "Rel_Neighbor",
    "BiRel_U",
    "BiRel_Up",
    "BiRel_D",
    "BiRel_Down",
    "BiRel_L",
    "BiRel_Left",
    "BiRel_R",
    "BiRel_Right",
    "BiRel_Neighbor",
}
DYNAMIC_RELATIONSHIP_MACROS = {
    "Rel",
    "Rel_U",
    "Rel_Up",
    "Rel_D",
    "Rel_Down",
    "Rel_L",
    "Rel_Left",
    "Rel_R",
    "Rel_Right",
    "Rel_Back",
    "Rel_Back_Neighbor",
    "Rel_Neighbor",
    "RelIndex",
    "RelIndex_U",
    "RelIndex_Up",
    "RelIndex_D",
    "RelIndex_Down",
    "RelIndex_L",
    "RelIndex_Left",
    "RelIndex_R",
    "RelIndex_Right",
    "RelIndex_Back",
    "RelIndex_Back_Neighbor",
    "RelIndex_Neighbor",
}
ALL_RELATIONSHIP_MACROS = STATIC_RELATIONSHIP_MACROS | DYNAMIC_RELATIONSHIP_MACROS
DYNAMIC_ONLY_RELATIONSHIP_MACROS = DYNAMIC_RELATIONSHIP_MACROS - STATIC_RELATIONSHIP_MACROS
DYNAMIC_STANDALONE_HELPERS = {"setIndex", "increment"}
DYNAMIC_INDEX_FUNCTIONS = {"Index", "SetIndex", "LastIndex"}
LEGEND_DIRECTIVE_MACROS = {"LAYOUT_WITH_LEGEND", "SHOW_FLOATING_LEGEND", "SHOW_LEGEND"}
BLOCK_OPENING_MACROS = BOUNDARY_MACROS | NODE_MACROS
SEQUENCE_ONLY_MACROS = {"Boundary_End", "SHOW_ELEMENT_DESCRIPTIONS", "SHOW_FOOT_BOXES", "SHOW_INDEX"}
ALLOWED_TOP_LEVEL_MACROS = {
    "LAYOUT_LEFT_RIGHT",
    "LAYOUT_TOP_DOWN",
    "LAYOUT_LANDSCAPE",
    "LEGEND",
    "Lay_Distance",
    "Lay_U",
    "Lay_Down",
    "Lay_Left",
    "Lay_Right",
    "LAYOUT_AS_SKETCH",
    "SET_SKETCH_STYLE",
    "HIDE_STEREOTYPE",
    "HIDE_PERSON_SPRITE",
    "SHOW_PERSON_SPRITE",
    "SHOW_PERSON_PORTRAIT",
    "SHOW_PERSON_OUTLINE",
    "AddElementTag",
    "AddRelTag",
    "AddBoundaryTag",
    "UpdateElementStyle",
    "UpdateRelStyle",
    "UpdateLegendTitle",
    "SetPropertyHeader",
    "WithoutPropertyHeader",
    "AddProperty",
}
TOP_LEVEL_KNOWN_MACROS = (
    ALL_ELEMENT_MACROS
    | ALL_RELATIONSHIP_MACROS
    | LEGEND_DIRECTIVE_MACROS
    | DYNAMIC_STANDALONE_HELPERS
    | DYNAMIC_INDEX_FUNCTIONS
    | SEQUENCE_ONLY_MACROS
    | ALLOWED_TOP_LEVEL_MACROS
)
TOP_LEVEL_SIGNATURES: dict[str, dict[str, object]] = {
    "LAYOUT_WITH_LEGEND": {"min_args": 0, "max_args": 0, "allowed_named": set()},
    "SHOW_LEGEND": {"min_args": 0, "max_args": 0, "allowed_named": set()},
    "SHOW_FLOATING_LEGEND": {"min_args": 0, "max_args": 0, "allowed_named": set()},
    "LAYOUT_LEFT_RIGHT": {"min_args": 0, "max_args": 0, "allowed_named": set()},
    "LAYOUT_TOP_DOWN": {"min_args": 0, "max_args": 0, "allowed_named": set()},
    "LAYOUT_LANDSCAPE": {"min_args": 0, "max_args": 0, "allowed_named": set()},
    "setIndex": {"min_args": 1, "max_args": 1, "allowed_named": {"new_index", "index"}},
    "increment": {"min_args": 0, "max_args": 1, "allowed_named": {"offset"}},
    "UpdateLegendTitle": {"min_args": 1, "max_args": 1, "allowed_named": {"newTitle", "title"}},
}
RELATIONSHIP_MACROS_BY_DIAGRAM = {
    "context": STATIC_RELATIONSHIP_MACROS,
    "container": STATIC_RELATIONSHIP_MACROS,
    "component": STATIC_RELATIONSHIP_MACROS,
    "dynamic": DYNAMIC_RELATIONSHIP_MACROS,
    "deployment": STATIC_RELATIONSHIP_MACROS,
}
BASE_RELATIONSHIP_NAMED_ARGS = {"from", "to", "label", "techn", "descr", "sprite", "tags", "link"}
RELATIONSHIP_NAMED_ARGS_BY_DIAGRAM = {
    "context": BASE_RELATIONSHIP_NAMED_ARGS,
    "container": BASE_RELATIONSHIP_NAMED_ARGS,
    "component": BASE_RELATIONSHIP_NAMED_ARGS,
    "dynamic": BASE_RELATIONSHIP_NAMED_ARGS | {"index"},
    "deployment": BASE_RELATIONSHIP_NAMED_ARGS,
}
ELEMENT_NAMED_ARGS_BY_MACRO: dict[str, set[str]] = {}
ELEMENT_POSITIONAL_FIELDS_BY_MACRO: dict[str, tuple[str, ...]] = {}
ELEMENT_REQUIRED_FIELDS = {"alias", "label"}

for macro in PERSON_MACROS:
    ELEMENT_NAMED_ARGS_BY_MACRO[macro] = {"alias", "label", "descr", "sprite", "tags", "link", "type"}
    ELEMENT_POSITIONAL_FIELDS_BY_MACRO[macro] = ("alias", "label", "descr", "sprite", "tags", "link", "type")
for macro in {"System", "System_Ext"}:
    ELEMENT_NAMED_ARGS_BY_MACRO[macro] = {"alias", "label", "descr", "sprite", "tags", "link", "type", "baseShape"}
    ELEMENT_POSITIONAL_FIELDS_BY_MACRO[macro] = ("alias", "label", "descr", "sprite", "tags", "link", "type", "baseShape")
for macro in {"SystemDb", "SystemQueue", "SystemDb_Ext", "SystemQueue_Ext"}:
    ELEMENT_NAMED_ARGS_BY_MACRO[macro] = {"alias", "label", "descr", "sprite", "tags", "link", "type"}
    ELEMENT_POSITIONAL_FIELDS_BY_MACRO[macro] = ("alias", "label", "descr", "sprite", "tags", "link", "type")
for macro in {"Container", "Container_Ext", "Component", "Component_Ext"}:
    ELEMENT_NAMED_ARGS_BY_MACRO[macro] = {"alias", "label", "techn", "descr", "sprite", "tags", "link", "baseShape"}
    ELEMENT_POSITIONAL_FIELDS_BY_MACRO[macro] = ("alias", "label", "techn", "descr", "sprite", "tags", "link", "baseShape")
for macro in {"ContainerDb", "ContainerQueue", "ContainerDb_Ext", "ContainerQueue_Ext", "ComponentDb", "ComponentQueue", "ComponentDb_Ext", "ComponentQueue_Ext"}:
    ELEMENT_NAMED_ARGS_BY_MACRO[macro] = {"alias", "label", "techn", "descr", "sprite", "tags", "link"}
    ELEMENT_POSITIONAL_FIELDS_BY_MACRO[macro] = ("alias", "label", "techn", "descr", "sprite", "tags", "link")
ELEMENT_NAMED_ARGS_BY_MACRO["Boundary"] = {"alias", "label", "type", "tags", "link", "descr"}
ELEMENT_POSITIONAL_FIELDS_BY_MACRO["Boundary"] = ("alias", "label", "type", "tags", "link", "descr")
for macro in {"Enterprise_Boundary", "System_Boundary", "Container_Boundary"}:
    ELEMENT_NAMED_ARGS_BY_MACRO[macro] = {"alias", "label", "tags", "link", "descr"}
    ELEMENT_POSITIONAL_FIELDS_BY_MACRO[macro] = ("alias", "label", "tags", "link", "descr")
for macro in NODE_MACROS:
    ELEMENT_NAMED_ARGS_BY_MACRO[macro] = {"alias", "label", "type", "descr", "sprite", "tags", "link"}
    ELEMENT_POSITIONAL_FIELDS_BY_MACRO[macro] = ("alias", "label", "type", "descr", "sprite", "tags", "link")


@dataclass
class ElementCall:
    macro: str
    alias: str
    line_no: int
    args: list[str]


@dataclass
class RelationshipCall:
    macro: str
    source: str | None
    target: str | None
    label: str | None
    technology: str | None
    has_index: bool
    named_args: set[str]
    args: list[str]
    line_no: int


@dataclass
class ValidationResult:
    errors: list[str]
    warnings: list[str]
    plantuml_attempted: bool = False
    plantuml_available: bool = False


def is_single_quote_delimiter(text: str, index: int, quote_char: str | None) -> bool:
    if text[index] != "'":
        return False
    if quote_char == "'":
        return True
    if quote_char is not None:
        return False
    prev_char = text[index - 1] if index > 0 else ""
    next_char = text[index + 1] if index + 1 < len(text) else ""
    if prev_char.isalnum():
        return False
    if not next_char or next_char.isspace():
        return False
    return True


def preprocess_line(line: str, in_block_comment: bool) -> tuple[str, bool]:
    if not in_block_comment and line.lstrip().startswith("'"):
        return "", False

    result = []
    quote_char = None
    escaped = False
    index = 0

    while index < len(line):
        if in_block_comment:
            if line.startswith("'/", index):
                in_block_comment = False
                index += 2
            else:
                index += 1
            continue

        char = line[index]

        if escaped:
            result.append(char)
            escaped = False
            index += 1
            continue

        if char == "\\" and quote_char is not None:
            result.append(char)
            escaped = True
            index += 1
            continue

        if quote_char is None and line.startswith("/'", index):
            in_block_comment = True
            index += 2
            continue

        if char == '"' or is_single_quote_delimiter(line, index, quote_char):
            result.append(char)
            if quote_char is None:
                quote_char = char
            elif quote_char == char:
                quote_char = None
            index += 1
            continue

        result.append(char)
        index += 1

    return "".join(result).rstrip(), in_block_comment


def split_args(args_text: str) -> list[str]:
    args = []
    current = []
    quote_char = None
    escaped = False
    depth = 0
    for char in args_text:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if char in {'"', "'"}:
            current.append(char)
            if quote_char is None:
                quote_char = char
            elif quote_char == char:
                quote_char = None
            continue
        if quote_char is None:
            if char == "(":
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1
            elif char == "," and depth == 0:
                args.append("".join(current).strip())
                current = []
                continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args


def normalize_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    value = value.strip()
    return value or None


def parse_named_arg(args: list[str], names: set[str]) -> str | None:
    for arg in args:
        lhs, sep, rhs = arg.partition("=")
        if sep and lhs.strip() in names:
            return rhs.strip()
    return None


def extract_named_args(args: list[str]) -> dict[str, str]:
    named = {}
    for arg in args:
        lhs, sep, rhs = arg.partition("=")
        key = lhs.strip()
        if sep and NAMED_ARG_RE.match(key):
            named[key] = rhs.strip()
    return named


def extract_named_arg_names(args: list[str]) -> set[str]:
    return {name.lstrip("$") for name in extract_named_args(args)}


def spaced_named_args(args: list[str]) -> set[str]:
    spaced = set()
    for arg in args:
        lhs, sep, _rhs = arg.partition("=")
        key = lhs.strip()
        if sep and NAMED_ARG_RE.match(key) and lhs != lhs.rstrip():
            spaced.add(key.lstrip("$"))
    return spaced


def positional_args(args: list[str]) -> list[str]:
    result = []
    for arg in args:
        lhs, sep, _rhs = arg.partition("=")
        if sep and NAMED_ARG_RE.match(lhs.strip()):
            continue
        result.append(arg.strip())
    return result


def extract_call(statement: str) -> tuple[str, list[str], str] | None:
    match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", statement)
    if not match:
        return None
    name = match.group(1)
    open_paren = statement.find("(", match.start(1))
    if open_paren == -1:
        return None
    quote_char = None
    escaped = False
    depth = 0
    close_paren = -1
    for index in range(open_paren, len(statement)):
        char = statement[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in {'"', "'"}:
            if quote_char is None:
                quote_char = char
            elif quote_char == char:
                quote_char = None
            continue
        if quote_char is not None:
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close_paren = index
                break
            if depth < 0:
                return None
    if close_paren == -1:
        return None
    tail = statement[close_paren + 1 :].strip()
    return name, split_args(statement[open_paren + 1 : close_paren]), tail


def find_call_names(statement: str) -> list[str]:
    names = []
    quote_char = None
    escaped = False
    index = 0

    while index < len(statement):
        char = statement[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if char in {'"', "'"}:
            if quote_char is None:
                quote_char = char
            elif quote_char == char:
                quote_char = None
            index += 1
            continue
        if quote_char is not None:
            index += 1
            continue
        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < len(statement) and (statement[index].isalnum() or statement[index] == "_"):
                index += 1
            end = index
            while index < len(statement) and statement[index].isspace():
                index += 1
            if index < len(statement) and statement[index] == "(":
                names.append(statement[start:end])
            continue
        index += 1

    return names


def normalize_macro_name(name: str) -> str:
    return name.replace("_", "").lower()


def bounded_edit_distance(left: str, right: str, limit: int) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > limit:
        return limit + 1

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        row_min = current[0]
        for right_index, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + cost,
                )
            )
            row_min = min(row_min, current[-1])
        if row_min > limit:
            return limit + 1
        previous = current
    return previous[-1]


def macro_kind(name: str) -> str:
    if name in ALL_ELEMENT_MACROS:
        return "element"
    if name in ALL_RELATIONSHIP_MACROS:
        return "relationship"
    if name in LEGEND_DIRECTIVE_MACROS:
        return "legend/layout directive"
    if name in DYNAMIC_STANDALONE_HELPERS:
        return "dynamic helper"
    if name in DYNAMIC_INDEX_FUNCTIONS:
        return "dynamic helper function"
    return "macro"


def suggest_known_top_level_macro(name: str) -> tuple[str, str] | None:
    normalized = normalize_macro_name(name)
    best_macro = None
    best_kind = None
    best_distance = None

    for candidate in sorted(TOP_LEVEL_KNOWN_MACROS):
        candidate_normalized = normalize_macro_name(candidate)
        limit = 1 if len(candidate_normalized) <= 4 else 2
        distance = bounded_edit_distance(normalized, candidate_normalized, limit)
        if distance > limit:
            continue
        if best_distance is None or distance < best_distance or (distance == best_distance and len(candidate_normalized) < len(normalize_macro_name(best_macro))):
            best_macro = candidate
            best_kind = macro_kind(candidate)
            best_distance = distance

    if best_macro is None:
        return None
    return best_macro, best_kind


def parse_include(statement: str) -> str | None:
    match = re.search(r"C4_(Context|Container|Component|Dynamic|Deployment|Sequence)", statement)
    if not match:
        return None
    return f"C4_{match.group(1)}"


def nested_calls_in_args(args: list[str]) -> list[tuple[str | None, str]]:
    nested = []
    for arg in args:
        lhs, sep, rhs = arg.partition("=")
        if sep and NAMED_ARG_RE.match(lhs.strip()):
            arg_name = lhs.strip().lstrip("$")
            expression = rhs.strip()
        else:
            arg_name = None
            expression = arg.strip()
        for call_name in find_call_names(expression):
            nested.append((arg_name, call_name))
    return nested


def validate_top_level_signature(path: Path, line_no: int, macro: str, args: list[str]) -> list[str]:
    signature = TOP_LEVEL_SIGNATURES.get(macro)
    if signature is None:
        return []

    errors = []

    spaced_named = spaced_named_args(args)
    if spaced_named:
        quoted = ", ".join(f"`{name}`" for name in sorted(spaced_named))
        errors.append(line_message(path, line_no, f"`{macro}` uses named argument(s) with spaces before `=`: {quoted}"))

    named_args = extract_named_arg_names(args)
    allowed_named = signature["allowed_named"]
    unsupported_named = named_args - allowed_named
    if unsupported_named:
        quoted = ", ".join(f"`{name}`" for name in sorted(unsupported_named))
        errors.append(line_message(path, line_no, f"`{macro}` uses unsupported named argument(s): {quoted}"))

    argument_count = len(args)
    min_args = signature["min_args"]
    max_args = signature["max_args"]
    if argument_count < min_args or argument_count > max_args:
        if min_args == max_args:
            expected = f"exactly {min_args}"
        else:
            expected = f"between {min_args} and {max_args}"
        errors.append(
            line_message(
                path,
                line_no,
                f"`{macro}` expects {expected} argument(s), got {argument_count}",
            )
        )
    return errors


def collect_statements(lines: list[str], start_line: int) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    statements = []
    errors = []
    block_comment = False
    block_comment_start = 0
    brace_stack: list[int] = []
    current = []
    current_start = 0
    balance = 0
    title_mode = False
    title_start = 0
    title_lines = []

    for offset, raw_line in enumerate(lines):
        line_no = start_line + offset
        stripped = raw_line.rstrip("\n")
        was_in_block_comment = block_comment
        cleaned, block_comment = preprocess_line(stripped, block_comment)
        if not was_in_block_comment and block_comment:
            block_comment_start = line_no
        elif was_in_block_comment and not block_comment:
            block_comment_start = 0
        cleaned = cleaned.strip()
        if not cleaned:
            continue

        lowered = cleaned.lower()
        if title_mode:
            if lowered == "end title":
                statements.append((title_start, f"title {' '.join(title_lines).strip()}".strip()))
                title_mode = False
                title_lines = []
                continue
            title_lines.append(cleaned)
            continue

        if lowered == "title":
            title_mode = True
            title_start = line_no
            title_lines = []
            continue

        paren_step, paren_min, brace_events = scan_structure(cleaned)
        for event in brace_events:
            if event == "{":
                brace_stack.append(line_no)
            elif brace_stack:
                brace_stack.pop()
            else:
                errors.append((line_no, "unexpected closing `}` or unbalanced braces"))

        if current:
            current.append(cleaned)
            if balance + paren_min < 0:
                errors.append((line_no, "unexpected closing `)` or unbalanced parentheses"))
                current = []
                balance = 0
                continue
            balance += paren_step
            if balance == 0:
                statements.append((current_start, " ".join(current)))
                current = []
                balance = 0
            continue

        if cleaned.startswith("@") or cleaned.startswith("!include") or lowered.startswith("title "):
            statements.append((line_no, cleaned))
            continue

        if "(" in cleaned:
            current = [cleaned]
            current_start = line_no
            if paren_min < 0:
                errors.append((line_no, "unexpected closing `)` or unbalanced parentheses"))
                current = []
                balance = 0
                continue
            balance = paren_step
            if balance == 0:
                statements.append((current_start, " ".join(current)))
                current = []
                balance = 0
            continue

        if paren_min < 0:
            errors.append((line_no, "unexpected closing `)` or unbalanced parentheses"))
        statements.append((line_no, cleaned))

    if current:
        errors.append((current_start, "unterminated macro call or unbalanced parentheses"))
    if title_mode:
        errors.append((title_start, "`title` block is missing `end title`"))
    if block_comment:
        errors.append((block_comment_start or start_line, "block comment is missing closing `'/`"))
    if brace_stack:
        errors.append((brace_stack[-1], "unclosed `{` block; missing closing `}` for a boundary or deployment node"))
    return statements, errors


def extract_blocks(text: str) -> tuple[list[tuple[int, int, list[str]]], list[str]]:
    blocks = []
    errors = []
    lines = text.splitlines()
    current_start = None
    current_lines = []
    in_block_comment = False
    in_title_block = False

    for index, line in enumerate(lines, start=1):
        cleaned, in_block_comment = preprocess_line(line.rstrip("\n"), in_block_comment)
        stripped = cleaned.strip()
        lowered = stripped.lower()

        if current_start is None:
            if stripped.startswith("@startuml"):
                current_start = index
                current_lines = [line]
                in_title_block = False
            elif stripped.startswith("@enduml"):
                errors.append(f"Line {index}: @enduml without matching @startuml")
            continue

        if not in_block_comment and not in_title_block and stripped.startswith("@startuml"):
            errors.append(f"Line {index}: nested @startuml before previous @enduml")
            current_start = index
            current_lines = [line]
            in_block_comment = False
            in_title_block = False
            continue

        current_lines.append(line)

        if in_title_block:
            if lowered == "end title":
                in_title_block = False
            continue

        if lowered == "title":
            in_title_block = True
            continue

        if lowered.startswith("title "):
            continue

        if stripped.startswith("@enduml"):
            blocks.append((current_start, index, current_lines))
            current_start = None
            current_lines = []
            in_title_block = False

    if current_start is not None:
        blocks.append((current_start, len(lines), current_lines))
        errors.append(f"Line {current_start}: @startuml without matching @enduml")
    if not blocks and not errors:
        errors.append("No @startuml/@enduml block found")
    return blocks, errors


def extract_relationship(args: list[str], line_no: int, macro: str) -> RelationshipCall:
    named_args = {name.lstrip("$") for name in extract_named_args(args)}
    positional = positional_args(args)
    source = normalize_value(parse_named_arg(args, {"$from", "from"}))
    target = normalize_value(parse_named_arg(args, {"$to", "to"}))
    label = normalize_value(parse_named_arg(args, {"$label", "label"}))
    technology = normalize_value(parse_named_arg(args, {"$techn", "techn"}))
    has_index = "index" in named_args

    if macro.startswith("RelIndex"):
        has_index = True
        if positional:
            positional = positional[1:]

    if source is None and len(positional) >= 1:
        source = normalize_value(positional[0])
    if target is None and len(positional) >= 2:
        target = normalize_value(positional[1])
    if label is None and len(positional) >= 3:
        label = normalize_value(positional[2])
    if technology is None and len(positional) >= 4:
        technology = normalize_value(positional[3])

    return RelationshipCall(
        macro=macro,
        source=source,
        target=target,
        label=label,
        technology=technology,
        has_index=has_index,
        named_args=named_args,
        args=args,
        line_no=line_no,
    )


def line_message(path: Path, line_no: int, message: str) -> str:
    return f"{path}:{line_no}: {message}"


def looks_like_relationship_macro(name: str) -> bool:
    return name.startswith("Rel") or name.startswith("BiRel")


def invalid_endpoint_kind(macro: str) -> str:
    if macro in BOUNDARY_MACROS:
        return "boundary"
    if macro in NODE_MACROS:
        return "deployment-node"
    return "structural"


def scan_structure(text: str) -> tuple[int, int, list[str]]:
    quote_char = None
    escaped = False
    paren_delta = 0
    paren_min = 0
    brace_events: list[str] = []
    for char in text:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in {'"', "'"}:
            if quote_char is None:
                quote_char = char
            elif quote_char == char:
                quote_char = None
            continue
        if quote_char is not None:
            continue
        if char == "(":
            paren_delta += 1
        elif char == ")":
            paren_delta -= 1
            paren_min = min(paren_min, paren_delta)
        elif char == "{":
            brace_events.append("{")
        elif char == "}":
            brace_events.append("}")
    return paren_delta, paren_min, brace_events


def allowed_element_named_args(macro: str) -> set[str]:
    return ELEMENT_NAMED_ARGS_BY_MACRO.get(macro, set())


def extract_element_fields(macro: str, args: list[str]) -> tuple[dict[str, str | None], set[str]]:
    named_values = {name.lstrip("$"): normalize_value(value) for name, value in extract_named_args(args).items()}
    positional = positional_args(args)
    fields: dict[str, str | None] = {}

    for index, field_name in enumerate(ELEMENT_POSITIONAL_FIELDS_BY_MACRO.get(macro, ())):
        if index < len(positional):
            fields[field_name] = normalize_value(positional[index])
    for field_name, value in named_values.items():
        if field_name in allowed_element_named_args(macro):
            fields[field_name] = value

    return fields, set(named_values)


def analyze_block(
    path: Path,
    block_number: int,
    statements: list[tuple[int, str]],
    require_title: bool,
    require_legend: bool,
    require_technology: bool,
    allow_generic_relationship_labels: bool,
) -> tuple[list[str], list[str], str | None]:
    errors = []
    warnings = []
    includes = []
    title_line = None
    title_text = None
    legend_lines = []
    show_legend_line = None
    element_by_alias: dict[str, ElementCall] = {}
    relationships: list[RelationshipCall] = []
    macro_counts: Counter[str] = Counter()
    statement_parse_error = False
    dynamic_indexing_evidence = False

    relevant_statements = [(line_no, stmt) for line_no, stmt in statements if not stmt.startswith("@")]
    for line_no, statement in relevant_statements:
        if statement.startswith("!include"):
            include = parse_include(statement)
            if include:
                includes.append((line_no, include))

    distinct_includes = {include for _line, include in includes}
    if not distinct_includes:
        errors.append(line_message(path, statements[0][0], f"block {block_number} is missing a C4 include"))
        diagram_type = None
    elif len(distinct_includes) > 1:
        errors.append(line_message(path, includes[0][0], f"block {block_number} mixes multiple C4 includes: {', '.join(sorted(distinct_includes))}"))
        diagram_type = None
    else:
        diagram_type = INCLUDE_TO_TYPE[next(iter(distinct_includes))]

    for line_no, statement in relevant_statements:
        if statement.startswith("!include"):
            continue

        if statement.startswith("title "):
            title_line = line_no
            title_text = statement[6:].strip()
            continue

        parsed = extract_call(statement)
        if not parsed:
            continue
        macro, args, tail = parsed
        nested_calls = nested_calls_in_args(args)

        if macro not in TOP_LEVEL_KNOWN_MACROS:
            suggestion = suggest_known_top_level_macro(macro)
            if suggestion is not None:
                suggested_macro, suggested_kind = suggestion
                errors.append(line_message(path, line_no, f"unknown {suggested_kind} `{macro}`; did you mean `{suggested_macro}`?"))
                continue

        if tail == "{" and macro not in BLOCK_OPENING_MACROS:
            errors.append(line_message(path, line_no, f"unexpected trailing `{{` after non-structural macro `{macro}(...)`"))
            statement_parse_error = True
            continue
        if tail not in {"", "{"}:
            errors.append(line_message(path, line_no, f"unexpected trailing content after `{macro}(...)`: `{tail}`"))
            statement_parse_error = True
            continue

        errors.extend(validate_top_level_signature(path, line_no, macro, args))

        nested_directives = sorted({name for _arg_name, name in nested_calls if name in LEGEND_DIRECTIVE_MACROS})
        for directive in nested_directives:
            errors.append(line_message(path, line_no, f"legend/layout directive `{directive}` must be a standalone top-level statement"))

        if macro in LEGEND_DIRECTIVE_MACROS:
            legend_lines.append(line_no)
            if macro == "SHOW_LEGEND":
                show_legend_line = line_no

        if macro in SEQUENCE_ONLY_MACROS:
            if diagram_type == "sequence":
                errors.append(line_message(path, line_no, f"`{macro}` belongs to `C4_Sequence.puml`, which is out of scope for this skill"))
            else:
                errors.append(line_message(path, line_no, f"sequence-only macro `{macro}` is out of scope for this skill"))
            continue

        if macro in DYNAMIC_INDEX_FUNCTIONS:
            if diagram_type and diagram_type != "dynamic":
                errors.append(line_message(path, line_no, f"dynamic-only helper function `{macro}` is not supported for `{diagram_type}` diagrams"))
            else:
                errors.append(line_message(path, line_no, f"dynamic helper function `{macro}` is only supported inside relationship `index=` in `C4_Dynamic` diagrams"))
            continue

        if macro in DYNAMIC_STANDALONE_HELPERS:
            if diagram_type and diagram_type != "dynamic":
                errors.append(line_message(path, line_no, f"dynamic-only helper `{macro}` is not supported for `{diagram_type}` diagrams"))
            elif diagram_type is None:
                warnings.append(line_message(path, line_no, f"`{macro}` cannot be validated until a single C4 include is resolved"))
            else:
                dynamic_indexing_evidence = True
            continue

        if macro in ALLOWED_TOP_LEVEL_MACROS:
            continue

        if looks_like_relationship_macro(macro) and macro not in ALL_RELATIONSHIP_MACROS:
            errors.append(line_message(path, line_no, f"unknown relationship macro `{macro}`"))
            continue
        macro_counts[macro] += 1

        if macro in ALL_ELEMENT_MACROS:
            element_fields, element_named_args = extract_element_fields(macro, args)
            alias = element_fields.get("alias")
            if not alias:
                errors.append(line_message(path, line_no, f"unable to parse alias for `{macro}`"))
                continue
            label = element_fields.get("label")
            if not label:
                errors.append(line_message(path, line_no, f"`{macro}` is missing a label"))
                continue
            if alias in element_by_alias:
                first_line = element_by_alias[alias].line_no
                errors.append(line_message(path, line_no, f"duplicate alias `{alias}` first declared on line {first_line}"))
                continue
            element = ElementCall(macro=macro, alias=alias, line_no=line_no, args=args)
            element_by_alias[alias] = element

            unsupported_element_named_args = element_named_args - allowed_element_named_args(macro)
            if unsupported_element_named_args:
                quoted = ", ".join(f"`{name}`" for name in sorted(unsupported_element_named_args))
                errors.append(line_message(path, line_no, f"`{macro}` uses unsupported named argument(s): {quoted}"))
            spaced_element_named_args = spaced_named_args(args)
            if spaced_element_named_args:
                quoted = ", ".join(f"`{name}`" for name in sorted(spaced_element_named_args))
                errors.append(line_message(path, line_no, f"`{macro}` uses named argument(s) with spaces before `=`: {quoted}"))

            if require_technology and macro in TECH_REQUIRED_MACROS and not element_fields.get("techn"):
                warnings.append(line_message(path, line_no, f"`{macro}` `{alias}` is missing a technology"))
            if macro in PERSON_MACROS | SYSTEM_MACROS | TECH_REQUIRED_MACROS:
                if not element_fields.get("descr"):
                    warnings.append(line_message(path, line_no, f"`{macro}` `{alias}` is missing a short description"))
            helper_misuses = sorted({name for _arg_name, name in nested_calls if name in DYNAMIC_STANDALONE_HELPERS | DYNAMIC_INDEX_FUNCTIONS})
            for helper_name in helper_misuses:
                if helper_name in DYNAMIC_STANDALONE_HELPERS:
                    if diagram_type and diagram_type != "dynamic":
                        errors.append(line_message(path, line_no, f"dynamic-only helper `{helper_name}` is not supported for `{diagram_type}` diagrams"))
                    else:
                        errors.append(line_message(path, line_no, f"dynamic helper `{helper_name}` must be a standalone top-level statement in `C4_Dynamic` diagrams"))
                else:
                    if diagram_type and diagram_type != "dynamic":
                        errors.append(line_message(path, line_no, f"dynamic-only helper function `{helper_name}` is not supported for `{diagram_type}` diagrams"))
                    else:
                        errors.append(line_message(path, line_no, f"dynamic helper function `{helper_name}` is only supported inside relationship `index=` in `C4_Dynamic` diagrams"))
            continue

        if looks_like_relationship_macro(macro):
            relationships.append(extract_relationship(args, line_no, macro))
            if macro in DYNAMIC_ONLY_RELATIONSHIP_MACROS or "index" in extract_named_arg_names(args):
                dynamic_indexing_evidence = True
            for arg_name, helper_name in nested_calls:
                if helper_name in DYNAMIC_STANDALONE_HELPERS:
                    if diagram_type and diagram_type != "dynamic":
                        errors.append(line_message(path, line_no, f"dynamic-only helper `{helper_name}` is not supported for `{diagram_type}` diagrams"))
                    else:
                        errors.append(line_message(path, line_no, f"dynamic helper `{helper_name}` must be a standalone top-level statement in `C4_Dynamic` diagrams"))
                    continue
                if helper_name in DYNAMIC_INDEX_FUNCTIONS:
                    if diagram_type and diagram_type != "dynamic":
                        errors.append(line_message(path, line_no, f"dynamic-only helper function `{helper_name}` is not supported for `{diagram_type}` diagrams"))
                    elif arg_name == "index":
                        dynamic_indexing_evidence = True
                    else:
                        errors.append(line_message(path, line_no, f"dynamic helper function `{helper_name}` is only supported inside relationship `index=` in `C4_Dynamic` diagrams"))
            continue

    if require_title and title_line is None:
        errors.append(line_message(path, statements[0][0], f"block {block_number} is missing a title"))
    elif title_text and diagram_type:
        title_lower = title_text.lower()
        keywords = TITLE_KEYWORDS.get(diagram_type)
        if keywords is not None and not any(keyword in title_lower for keyword in keywords):
            warnings.append(line_message(path, title_line, f"title does not clearly state the `{diagram_type}` diagram type"))

    if require_legend and not legend_lines:
        errors.append(line_message(path, statements[0][0], f"block {block_number} is missing a legend directive"))

    if show_legend_line is not None:
        last_relevant_line = relevant_statements[-1][0]
        if show_legend_line != last_relevant_line:
            errors.append(line_message(path, show_legend_line, "`SHOW_LEGEND()` must be the last statement before `@enduml`"))

    if diagram_type == "sequence":
        errors.append(line_message(path, statements[0][0], "`C4_Sequence.puml` is out of scope for this skill"))

    if statement_parse_error:
        return errors, warnings, diagram_type

    if diagram_type == "sequence":
        return errors, warnings, diagram_type

    if diagram_type == "context":
        if macro_counts & Counter({macro: 1 for macro in CONTAINER_MACROS | COMPONENT_MACROS | NODE_MACROS}):
            errors.append(line_message(path, statements[0][0], "context/landscape diagram must not include container, component, or deployment-node elements"))
        if not any(macro in macro_counts for macro in {"System", "SystemDb", "SystemQueue"}):
            warnings.append(line_message(path, statements[0][0], "context/landscape diagram has no clear in-scope software system"))
    elif diagram_type == "container":
        if any(macro in macro_counts for macro in COMPONENT_MACROS | NODE_MACROS):
            errors.append(line_message(path, statements[0][0], "container diagram must not include component or deployment-node elements"))
        if not any(macro in macro_counts for macro in {"Container", "ContainerDb", "ContainerQueue"}):
            errors.append(line_message(path, statements[0][0], "container diagram has no in-scope containers"))
    elif diagram_type == "component":
        if any(macro in macro_counts for macro in NODE_MACROS):
            errors.append(line_message(path, statements[0][0], "component diagram must not include deployment-node elements"))
        if not any(macro in macro_counts for macro in {"Component", "ComponentDb", "ComponentQueue"}):
            errors.append(line_message(path, statements[0][0], "component diagram has no components"))
        if macro_counts["Container_Boundary"] == 0:
            warnings.append(line_message(path, statements[0][0], "component diagram should usually anchor components inside a `Container_Boundary`"))
    elif diagram_type == "dynamic":
        if any(macro in macro_counts for macro in NODE_MACROS):
            errors.append(line_message(path, statements[0][0], "dynamic diagram must not include deployment-node elements"))
        if not relationships:
            errors.append(line_message(path, statements[0][0], "dynamic diagram has no relationships"))
        elif not any(rel.has_index for rel in relationships) and not dynamic_indexing_evidence:
            warnings.append(line_message(path, statements[0][0], "dynamic diagram has no indexed relationships"))
    elif diagram_type == "deployment":
        if any(macro in macro_counts for macro in COMPONENT_MACROS):
            errors.append(line_message(path, statements[0][0], "deployment diagram should model container or system instances, not components"))
        if not any(macro in macro_counts for macro in NODE_MACROS):
            errors.append(line_message(path, statements[0][0], "deployment diagram has no deployment nodes"))

    allowed_relationship_macros = RELATIONSHIP_MACROS_BY_DIAGRAM.get(diagram_type, ALL_RELATIONSHIP_MACROS)
    allowed_relationship_named_args = RELATIONSHIP_NAMED_ARGS_BY_DIAGRAM.get(diagram_type, BASE_RELATIONSHIP_NAMED_ARGS)

    for rel in relationships:
        if rel.macro not in ALL_RELATIONSHIP_MACROS:
            errors.append(line_message(path, rel.line_no, f"unknown relationship macro `{rel.macro}`"))
            continue

        if diagram_type and rel.macro not in allowed_relationship_macros:
            if rel.macro in DYNAMIC_ONLY_RELATIONSHIP_MACROS:
                errors.append(line_message(path, rel.line_no, f"dynamic-only relationship macro `{rel.macro}` is not supported for `{diagram_type}` diagrams"))
            else:
                errors.append(line_message(path, rel.line_no, f"relationship macro `{rel.macro}` is not supported for `{diagram_type}` diagrams"))
            continue

        if diagram_type and diagram_type != "dynamic" and "index" in rel.named_args:
            errors.append(line_message(path, rel.line_no, f"dynamic-only named argument `index` is not supported for `{diagram_type}` diagrams"))

        unsupported_named_args = set(rel.named_args) - set(allowed_relationship_named_args)
        if diagram_type == "dynamic" and "rel" in unsupported_named_args:
            errors.append(line_message(path, rel.line_no, "sequence-style named argument `rel` is not supported in dynamic diagrams; `C4_Sequence.puml` is out of scope"))
            unsupported_named_args.remove("rel")
        if unsupported_named_args:
            quoted = ", ".join(f"`{name}`" for name in sorted(unsupported_named_args))
            errors.append(line_message(path, rel.line_no, f"`{rel.macro}` uses unsupported named argument(s): {quoted}"))
        spaced_relationship_named_args = spaced_named_args(rel.args)
        if spaced_relationship_named_args:
            quoted = ", ".join(f"`{name}`" for name in sorted(spaced_relationship_named_args))
            errors.append(line_message(path, rel.line_no, f"`{rel.macro}` uses named argument(s) with spaces before `=`: {quoted}"))

        if not rel.source:
            errors.append(line_message(path, rel.line_no, f"`{rel.macro}` is missing a source alias"))
        elif rel.source not in element_by_alias:
            errors.append(line_message(path, rel.line_no, f"`{rel.macro}` references unknown source alias `{rel.source}`"))
        elif element_by_alias[rel.source].macro in INVALID_REL_ENDPOINT_MACROS:
            endpoint_kind = invalid_endpoint_kind(element_by_alias[rel.source].macro)
            errors.append(line_message(path, rel.line_no, f"`{rel.macro}` uses {endpoint_kind} alias `{rel.source}` as a relationship endpoint"))

        if not rel.target:
            errors.append(line_message(path, rel.line_no, f"`{rel.macro}` is missing a target alias"))
        elif rel.target not in element_by_alias:
            errors.append(line_message(path, rel.line_no, f"`{rel.macro}` references unknown target alias `{rel.target}`"))
        elif element_by_alias[rel.target].macro in INVALID_REL_ENDPOINT_MACROS:
            endpoint_kind = invalid_endpoint_kind(element_by_alias[rel.target].macro)
            errors.append(line_message(path, rel.line_no, f"`{rel.macro}` uses {endpoint_kind} alias `{rel.target}` as a relationship endpoint"))

        if not rel.label:
            errors.append(line_message(path, rel.line_no, f"`{rel.macro}` is missing a relationship label"))
        elif not allow_generic_relationship_labels and rel.label.lower() in GENERIC_RELATIONSHIP_LABELS:
            warnings.append(line_message(path, rel.line_no, f"relationship label `{rel.label}` is too generic for C4"))

        if rel.source in element_by_alias and rel.target in element_by_alias:
            source_macro = element_by_alias[rel.source].macro
            target_macro = element_by_alias[rel.target].macro
            if source_macro in CONTAINER_MACROS and target_macro in CONTAINER_MACROS and not rel.technology:
                warnings.append(line_message(path, rel.line_no, "relationship between containers is missing an explicit technology/protocol"))

    return errors, warnings, diagram_type


def run_plantuml_check(path: Path) -> tuple[bool, bool, str | None]:
    binary = shutil.which("plantuml")
    if not binary:
        return False, False, None
    completed = subprocess.run(
        [binary, "-checkonly", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return True, True, None
    detail = (completed.stdout + completed.stderr).strip() or "plantuml reported a syntax/render error"
    return True, True, detail


def validate_file(
    path: str | Path,
    *,
    require_title: bool = True,
    require_legend: bool = True,
    require_technology: bool = True,
    allow_generic_relationship_labels: bool = False,
    plantuml_mode: str = "auto",
) -> ValidationResult:
    path = Path(path)
    errors = []
    warnings = []

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ValidationResult(errors=[f"{path}: file not found"], warnings=[])
    except UnicodeDecodeError as exc:
        return ValidationResult(errors=[f"{path}: unable to decode UTF-8 content ({exc})"], warnings=[])
    except OSError as exc:
        return ValidationResult(errors=[f"{path}: unable to read file ({exc})"], warnings=[])

    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")

    blocks, block_errors = extract_blocks(text)
    errors.extend(f"{path}: {message}" for message in block_errors)

    for block_index, (start_line, _end_line, lines) in enumerate(blocks, start=1):
        statements, statement_errors = collect_statements(lines, start_line)
        errors.extend(line_message(path, line_no, message) for line_no, message in statement_errors)
        if statement_errors:
            continue
        if not statements:
            errors.append(f"{path}:{start_line}: empty PlantUML block")
            continue
        block_errors, block_warnings, _diagram_type = analyze_block(
            path,
            block_index,
            statements,
            require_title=require_title,
            require_legend=require_legend,
            require_technology=require_technology,
            allow_generic_relationship_labels=allow_generic_relationship_labels,
        )
        errors.extend(block_errors)
        warnings.extend(block_warnings)

    plantuml_attempted = False
    plantuml_available = shutil.which("plantuml") is not None
    if plantuml_mode not in {"auto", "on", "off"}:
        errors.append(f"{path}: unsupported plantuml mode `{plantuml_mode}`")
        return ValidationResult(errors=errors, warnings=warnings)

    if plantuml_mode in {"auto", "on"}:
        if plantuml_available:
            plantuml_attempted, _available, detail = run_plantuml_check(path)
            if detail:
                errors.append(f"{path}: plantuml -checkonly failed: {detail}")
        elif plantuml_mode == "on":
            warnings.append(f"{path}: plantuml binary not available; external syntax check skipped")

    return ValidationResult(
        errors=errors,
        warnings=warnings,
        plantuml_attempted=plantuml_attempted,
        plantuml_available=plantuml_available,
    )


def iter_paths(raw_paths: list[str]) -> list[Path]:
    def should_skip(candidate: Path, root: Path | None) -> bool:
        parts = candidate.parts if root is None else candidate.relative_to(root).parts
        for part in parts:
            if part == "__MACOSX":
                return True
            if part.startswith("._"):
                return True
            if part.startswith("."):
                return True
        return False

    collected = []
    for raw in raw_paths:
        path = Path(raw)
        if path.is_dir():
            for candidate in sorted(path.rglob("*.puml")):
                if should_skip(candidate, path):
                    continue
                collected.append(candidate)
        else:
            collected.append(path)
    return collected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate C4-PlantUML files with opinionated C4 lint rules and optional PlantUML syntax checks.")
    parser.add_argument("paths", nargs="+", help="One or more .puml files or directories")
    parser.add_argument("--plantuml", choices={"auto", "on", "off"}, default="auto", help="Run external plantuml -checkonly if available")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")
    parser.add_argument("--no-require-title", action="store_true", help="Disable the house-style requirement for a diagram title")
    parser.add_argument("--no-require-legend", action="store_true", help="Disable the house-style requirement for a legend directive")
    parser.add_argument("--no-require-technology", action="store_true", help="Do not lint missing technology on containers/components")
    parser.add_argument("--allow-generic-relationship-labels", action="store_true", help="Allow labels such as 'Uses' without warning")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    paths = iter_paths(args.paths)
    if not paths:
        print("No .puml files found", file=sys.stderr)
        return 1

    all_errors = []
    all_warnings = []
    for path in paths:
        result = validate_file(
            path,
            require_title=not args.no_require_title,
            require_legend=not args.no_require_legend,
            require_technology=not args.no_require_technology,
            allow_generic_relationship_labels=args.allow_generic_relationship_labels,
            plantuml_mode=args.plantuml,
        )
        all_errors.extend(result.errors)
        all_warnings.extend(result.warnings)

    for warning in all_warnings:
        print(f"WARN  {warning}")
    for error in all_errors:
        print(f"ERROR {error}")

    if all_errors:
        print(f"Validation failed: {len(all_errors)} error(s), {len(all_warnings)} warning(s)")
        return 1
    if args.strict and all_warnings:
        print(f"Validation failed in strict mode: {len(all_warnings)} warning(s)")
        return 1

    print(f"Validation passed: {len(paths)} file(s), {len(all_warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
