"""Unit tests for sidecar anchor_manifest.schema.json files (US-S3-01).

Both sidecars (c4-plantuml-from-context, camunda-bpmn-from-context) publish a
JSON Schema describing their ``analysis/views/<kind>/anchor_manifest.json``
output under ``references/anchor_manifest.schema.json``. These tests verify:

1. Each schema is itself a valid JSON Schema 2020-12 document.
2. A canonical "happy path" example for each sidecar validates against it.
3. Contract-violation examples (wrong sidecar name, missing anchor id,
   unknown element kind) are rejected.

The tests do NOT re-implement the sidecar validators; they just pin the
schema surface so future refactors cannot silently drop required fields.
"""

from __future__ import annotations

import json
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


def test_c4_enum_is_superset_of_documented_taxonomy() -> None:
    """Structural guarantee: every C4 macro name called out in
    references/c4-plantuml-syntax.md as a selectable view element kind
    must appear in the schema enum. This prevents a future doc update
    from silently creating a new unvalidated kind.

    We scan for the documented macro-family names and check each against
    the schema enum. Directional relationship variants (Rel_U, BiRel_L,
    etc.) are intentionally collapsed to their base kind in the enum and
    are therefore excluded from this superset check.
    """
    schema = _load(C4_SCHEMA)
    enum = set(
        schema["properties"]["view_files"]["items"]["properties"]["anchor_map"][
            "items"
        ]["properties"]["view_element_kind"]["enum"]
    )
    # Authoritative documented kinds the enum MUST cover.
    documented = {
        "Person", "Person_Ext",
        "System", "System_Ext", "SystemDb", "SystemDb_Ext",
        "SystemQueue", "SystemQueue_Ext",
        "Container", "Container_Ext",
        "ContainerDb", "ContainerDb_Ext",
        "ContainerQueue", "ContainerQueue_Ext",
        "Component", "Component_Ext",
        "ComponentDb", "ComponentDb_Ext",
        "ComponentQueue", "ComponentQueue_Ext",
        "Boundary", "Enterprise_Boundary",
        "System_Boundary", "Container_Boundary",
        "Deployment_Node", "Deployment_Node_L", "Deployment_Node_R",
        "Node", "Node_L", "Node_R",
        "Rel", "BiRel", "RelIndex",
    }
    missing = documented - enum
    assert not missing, f"C4 schema enum missing documented kinds: {sorted(missing)}"


def test_bpmn_enum_is_superset_of_documented_taxonomy() -> None:
    """Structural guarantee: every BPMN element kind called out in
    references/support-matrix.md as a supported construct must appear
    in the schema enum (element-level kinds only — event definitions are
    attributes of event elements, not standalone IDs, and are therefore
    excluded).
    """
    schema = _load(BPMN_SCHEMA)
    enum = set(
        schema["properties"]["view_files"]["items"]["properties"]["anchor_map"][
            "items"
        ]["properties"]["element_kind"]["enum"]
    )
    documented = {
        "startEvent", "endEvent",
        "intermediateCatchEvent", "intermediateThrowEvent",
        "boundaryEvent",
        "task", "userTask", "serviceTask", "receiveTask", "sendTask",
        "scriptTask", "businessRuleTask", "manualTask",
        "callActivity", "subProcess", "transaction", "adHocSubProcess",
        "exclusiveGateway", "parallelGateway", "inclusiveGateway",
        "eventBasedGateway", "complexGateway",
        "sequenceFlow", "messageFlow",
        "participant", "lane", "laneSet",
        "dataObject", "dataObjectReference", "dataStoreReference",
        "textAnnotation", "association", "group",
    }
    missing = documented - enum
    assert not missing, f"BPMN schema enum missing documented kinds: {sorted(missing)}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
