"""Unit tests for sidecar anchor_manifest.schema.json files (US-S3-01).

Both sidecars (c4-plantuml-from-context, camunda-bpmn-from-context) publish a
JSON Schema describing their ``analysis/views/<kind>/anchor_manifest.json``
output under ``references/anchor_manifest.schema.json``. These tests verify:

1. Each schema is itself a valid JSON Schema 2020-12 document.
2. A canonical "happy path" example for each sidecar validates against it.
3. Contract-violation examples (wrong sidecar name, missing anchor id,
   unknown element kind) are rejected.
4. The schema enum is a superset of the kinds documented in each sidecar's
   reference corpus (c4-plantuml-syntax.md / support-matrix.md). Parsing
   runs against the committed documents at test time so a future doc
   update that introduces a new kind without a matching schema update is
   caught on the next CI run (US-S3-01 review round 2).

The tests do NOT re-implement the sidecar validators; they just pin the
schema surface so future refactors cannot silently drop required fields.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
C4_SCHEMA = (
    REPO_ROOT
    / "skills"
    / "c4-plantuml-from-context"
    / "references"
    / "anchor_manifest.schema.json"
)
BPMN_SCHEMA = (
    REPO_ROOT
    / "skills"
    / "camunda-bpmn-from-context"
    / "references"
    / "anchor_manifest.schema.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _c4_happy_path() -> dict:
    return {
        "manifest_version": "1.0",
        "generated_at": "2026-04-19T17:00:00Z",
        "sidecar": "c4-plantuml-from-context",
        "sidecar_version": "1.0.0",
        "canon_policy_version": "0.95",
        "view_files": [
            {
                "path": "analysis/views/c4/system_context.puml",
                "diagram_type": "System Context",
                "anchor_map": [
                    {
                        "view_element_id": "support_desk",
                        "view_element_kind": "System",
                        "a61_anchor_id": "ANC-SYS-001",
                        "notes": "Primary system in scope",
                    },
                    {
                        "view_element_id": "agent",
                        "view_element_kind": "Person",
                        "a61_anchor_id": "ANC-ACTOR-001",
                    },
                ],
            }
        ],
    }


def _bpmn_happy_path() -> dict:
    return {
        "manifest_version": "1.0",
        "generated_at": "2026-04-19T17:00:00Z",
        "sidecar": "camunda-bpmn-from-context",
        "sidecar_version": "1.0.0",
        "canon_policy_version": "0.95",
        "view_files": [
            {
                "path": "analysis/views/bpmn/ticket_intake.bpmn",
                "bpmn_profile": "documentation",
                "anchor_map": [
                    {
                        "element_id": "StartEvent_intake",
                        "element_kind": "startEvent",
                        "a61_anchor_id": "ANC-EVT-001",
                    },
                    {
                        "element_id": "Task_assign_severity",
                        "element_kind": "task",
                        "a61_anchor_id": "ANC-TASK-002",
                    },
                    {
                        "element_id": "SequenceFlow_high_to_page",
                        "element_kind": "sequenceFlow",
                        "a61_anchor_id": "ANC-FLOW-003",
                    },
                ],
            }
        ],
    }


# Kinds previously flagged by codex round 1 as "documented but missing from
# schema enum"; these tests pin them as accepted so the enum/taxonomy gap
# cannot reopen silently.
C4_PREVIOUSLY_MISSING_KINDS = (
    "Person_Ext",
    "SystemDb",
    "SystemQueue",
    "ContainerDb",
    "ContainerQueue",
    "ComponentDb",
    "ComponentQueue",
    "Boundary",
    "Deployment_Node_L",
    "Deployment_Node_R",
    "Node",
    "Node_L",
    "Node_R",
    "BiRel",
    "RelIndex",
)

BPMN_PREVIOUSLY_MISSING_KINDS = (
    "complexGateway",
    "laneSet",
    "dataObjectReference",
    "dataStoreReference",
    "textAnnotation",
    "association",
    "group",
    "transaction",
    "adHocSubProcess",
    # Top-level containers and declarations added in review round 2 after
    # the doc-driven test revealed they were documented but absent from
    # the enum.
    "collaboration",
    "process",
    "choreography",
    "message",
    "signal",
)


# ---- meta-schema conformance --------------------------------------------


def test_c4_schema_is_valid_2020_12() -> None:
    schema = _load(C4_SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)


def test_bpmn_schema_is_valid_2020_12() -> None:
    schema = _load(BPMN_SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)


# ---- happy-path validation ---------------------------------------------


def test_c4_happy_path_validates() -> None:
    schema = _load(C4_SCHEMA)
    jsonschema.Draft202012Validator(schema).validate(_c4_happy_path())


def test_bpmn_happy_path_validates() -> None:
    schema = _load(BPMN_SCHEMA)
    jsonschema.Draft202012Validator(schema).validate(_bpmn_happy_path())


def test_c4_happy_path_accepts_policy_hash_suffix() -> None:
    """canon_policy_version accepts the semver+hash form landed in Sprint 3."""
    schema = _load(C4_SCHEMA)
    doc = _c4_happy_path()
    doc["canon_policy_version"] = "1.0.0+hash:abc123def456"
    jsonschema.Draft202012Validator(schema).validate(doc)


def test_bpmn_happy_path_accepts_policy_hash_suffix() -> None:
    schema = _load(BPMN_SCHEMA)
    doc = _bpmn_happy_path()
    doc["canon_policy_version"] = "1.0.0+hash:deadbeefcafe"
    jsonschema.Draft202012Validator(schema).validate(doc)


# ---- negative cases ----------------------------------------------------


def test_c4_rejects_wrong_sidecar_name() -> None:
    schema = _load(C4_SCHEMA)
    doc = _c4_happy_path()
    doc["sidecar"] = "camunda-bpmn-from-context"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(doc)


def test_bpmn_rejects_wrong_sidecar_name() -> None:
    schema = _load(BPMN_SCHEMA)
    doc = _bpmn_happy_path()
    doc["sidecar"] = "c4-plantuml-from-context"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(doc)


def test_c4_rejects_unknown_element_kind() -> None:
    schema = _load(C4_SCHEMA)
    doc = _c4_happy_path()
    doc["view_files"][0]["anchor_map"][0]["view_element_kind"] = "SomeMadeUpKind"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(doc)


def test_bpmn_rejects_unknown_element_kind() -> None:
    schema = _load(BPMN_SCHEMA)
    doc = _bpmn_happy_path()
    doc["view_files"][0]["anchor_map"][0]["element_kind"] = "NotARealBPMNThing"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(doc)


def test_c4_rejects_bad_anchor_id_pattern() -> None:
    schema = _load(C4_SCHEMA)
    doc = _c4_happy_path()
    doc["view_files"][0]["anchor_map"][0]["a61_anchor_id"] = "not-an-anchor-id"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(doc)


def test_bpmn_rejects_bad_anchor_id_pattern() -> None:
    schema = _load(BPMN_SCHEMA)
    doc = _bpmn_happy_path()
    doc["view_files"][0]["anchor_map"][0]["a61_anchor_id"] = "wrong_format_anchor"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(doc)


def test_c4_rejects_missing_view_files() -> None:
    schema = _load(C4_SCHEMA)
    doc = _c4_happy_path()
    doc["view_files"] = []
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(doc)


def test_bpmn_rejects_missing_view_files() -> None:
    schema = _load(BPMN_SCHEMA)
    doc = _bpmn_happy_path()
    doc["view_files"] = []
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(doc)


def test_c4_rejects_path_without_puml_suffix() -> None:
    schema = _load(C4_SCHEMA)
    doc = _c4_happy_path()
    doc["view_files"][0]["path"] = "analysis/views/c4/system_context.txt"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(doc)


def test_bpmn_rejects_path_without_bpmn_suffix() -> None:
    schema = _load(BPMN_SCHEMA)
    doc = _bpmn_happy_path()
    doc["view_files"][0]["path"] = "analysis/views/bpmn/ticket_intake.xml"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(doc)


def test_c4_rejects_unknown_top_level_field() -> None:
    schema = _load(C4_SCHEMA)
    doc = _c4_happy_path()
    doc["extra_field_not_in_schema"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(doc)


def test_bpmn_rejects_unknown_top_level_field() -> None:
    schema = _load(BPMN_SCHEMA)
    doc = _bpmn_happy_path()
    doc["extra_field_not_in_schema"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(doc)


# ---- enum completeness regression (US-S3-01 review round 1) ------------
#
# Codex round 1 flagged that the initial schema enums dropped documented
# taxonomy entries (Person_Ext / ContainerDb / ... / complexGateway / ...),
# which would silently reject valid manifests. These tests pin every
# previously-missing kind as accepted and also guarantee the schema enum
# stays a strict superset of the documented taxonomy.


@pytest.mark.parametrize("kind", C4_PREVIOUSLY_MISSING_KINDS)
def test_c4_schema_accepts_previously_missing_kind(kind: str) -> None:
    """Pin every previously-missing C4 macro kind as schema-accepted."""
    schema = _load(C4_SCHEMA)
    doc = _c4_happy_path()
    doc["view_files"][0]["anchor_map"].append(
        {
            "view_element_id": f"probe_{kind}",
            "view_element_kind": kind,
            "a61_anchor_id": "ANC-PROBE-001",
        }
    )
    jsonschema.Draft202012Validator(schema).validate(doc)


@pytest.mark.parametrize("kind", BPMN_PREVIOUSLY_MISSING_KINDS)
def test_bpmn_schema_accepts_previously_missing_kind(kind: str) -> None:
    """Pin every previously-missing BPMN element kind as schema-accepted."""
    schema = _load(BPMN_SCHEMA)
    doc = _bpmn_happy_path()
    doc["view_files"][0]["anchor_map"].append(
        {
            "element_id": f"probe_{kind}",
            "element_kind": kind,
            "a61_anchor_id": "ANC-PROBE-001",
        }
    )
    jsonschema.Draft202012Validator(schema).validate(doc)


C4_SYNTAX_DOC = (
    REPO_ROOT
    / "skills"
    / "c4-plantuml-from-context"
    / "references"
    / "c4-plantuml-syntax.md"
)
BPMN_SUPPORT_DOC = (
    REPO_ROOT
    / "skills"
    / "camunda-bpmn-from-context"
    / "references"
    / "support-matrix.md"
)


def _schema_enum(schema_path: Path, kind_field: str) -> set[str]:
    schema = _load(schema_path)
    return set(
        schema["properties"]["view_files"]["items"]["properties"]["anchor_map"][
            "items"
        ]["properties"][kind_field]["enum"]
    )


def _parse_c4_doc_kinds() -> set[str]:
    """Extract C4 element + relationship kinds from the committed syntax doc.

    Scoped to "## Core Element Macros" (elements) + "## Relationship Macros"
    (base Rel / BiRel / RelIndex only). Directional variants (Rel_U,
    BiRel_Left, etc.) are intentionally collapsed to their base kind in
    the schema and are not present in the doc as macros-with-arg-lists,
    so they are excluded naturally. Layout / tagging helpers (Index(),
    SHOW_LEGEND, LAYOUT_*) live in other sections and are out of scope.
    """
    text = C4_SYNTAX_DOC.read_text(encoding="utf-8")
    core_start = text.index("## Core Element Macros")
    rel_start = text.index("## Relationship Macros")
    support_start = text.index("## Support Matrix")
    element_scope = text[core_start:rel_start]
    rel_scope = text[rel_start:support_start]
    element_macros = set(
        re.findall(r"^- `([A-Z][A-Za-z0-9_]*)\(", element_scope, flags=re.MULTILINE)
    )
    rel_macros = set(
        re.findall(r"^- `(Rel|BiRel|RelIndex)\(", rel_scope, flags=re.MULTILINE)
    )
    return element_macros | rel_macros


_BPMN_NON_ELEMENT_TOKENS = frozenset(
    {
        # Status-matrix vocabulary that happens to get backticked.
        "yes",
        "no",
        "partial",
        "n",
        "a",
        "preserve",
        "full",
        "exactly",
        # Event-attribute refs (attached to events, not element kinds).
        "messageRef",
        "signalRef",
        "errorRef",
        "escalationRef",
        "correlationKey",
        # Runtime attributes of events / tasks (attribute, not element).
        "timeDate",
        "timeCycle",
        "timeDuration",
        "name",
        "id",
        "type",
        "retries",
        "priorityDefinition",
        "subscription",
        "assignmentDefinition",
        "taskSchedule",
        "taskListeners",
        "taskHeaders",
        "taskDefinition",
        "eventType",
        "boundary",
        # Resource roles and reference attributes (attribute on an activity).
        "humanPerformer",
        "processRef",
        # "undefinedTask" is the doc's informal alias for a bare <task>; the
        # spec XML tag is still <task>, so we treat this as already covered
        # by the 'task' kind rather than a separate element.
        "undefinedTask",
        # Non-BPMN vocabulary that happens to be backticked in prose.
        "smoke",
        "greenfield",
        "adjudication",
    }
)


def _parse_bpmn_doc_kinds() -> set[str]:
    """Extract BPMN element kinds from the committed support matrix.

    Element kinds are matched by shape (camelCase, lowercase-first) and
    filtered against a known set of non-element tokens: event definitions
    (``*EventDefinition``), event-attribute refs (``*Ref``, ``correlationKey``),
    runtime attributes (``timeDate``, ``retries``, ``priorityDefinition``, ...),
    resource roles (``humanPerformer``), and status keywords. The filter
    list lives in ``_BPMN_NON_ELEMENT_TOKENS`` above.
    """
    text = BPMN_SUPPORT_DOC.read_text(encoding="utf-8")
    tokens = set(re.findall(r"`([a-zA-Z][a-zA-Z0-9_]*)`", text))

    def is_element(t: str) -> bool:
        if not re.match(r"^[a-z][a-zA-Z0-9]*$", t):
            return False
        if t.endswith("Definition"):
            return False
        if t in _BPMN_NON_ELEMENT_TOKENS:
            return False
        return True

    return {t for t in tokens if is_element(t)}


def test_c4_enum_is_superset_of_documented_taxonomy() -> None:
    """Every C4 macro backticked with an arg-list in c4-plantuml-syntax.md
    must appear in the schema enum. Parsing runs against the committed
    doc at test time, so a future doc update that introduces a new macro
    without extending the schema enum fails on the next CI run."""
    enum = _schema_enum(C4_SCHEMA, "view_element_kind")
    documented = _parse_c4_doc_kinds()
    assert documented, "parser returned empty set — parse heuristic broke"
    missing = documented - enum
    assert not missing, (
        f"C4 schema enum missing documented macros: {sorted(missing)}. "
        f"Either add them to references/anchor_manifest.schema.json or "
        f"justify their exclusion in the schema description."
    )


def test_bpmn_enum_is_superset_of_documented_taxonomy() -> None:
    """Every BPMN element kind backticked in support-matrix.md (after
    filtering out event definitions, event-attribute refs, runtime
    attributes, resource roles, and status keywords) must appear in the
    schema enum. Parsing runs against the committed doc at test time, so
    a future doc update that introduces a new kind without extending the
    schema enum fails on the next CI run.

    Note: the schema enum intentionally includes a few kinds the doc
    references only via narrative phrases (e.g., 'XOR/AND/OR gateways'
    covers exclusive/parallel/inclusive Gateway, 'core tasks' covers
    manualTask). Those are 'extra in schema' relative to the parse and
    are therefore permitted by the superset direction of this check."""
    enum = _schema_enum(BPMN_SCHEMA, "element_kind")
    documented = _parse_bpmn_doc_kinds()
    assert documented, "parser returned empty set — parse heuristic broke"
    missing = documented - enum
    assert not missing, (
        f"BPMN schema enum missing documented kinds: {sorted(missing)}. "
        f"Either add them to references/anchor_manifest.schema.json, or "
        f"add the token to _BPMN_NON_ELEMENT_TOKENS with justification "
        f"(if it is actually an attribute rather than an element kind)."
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
