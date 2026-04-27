"""Tests for `skills/proto-from-context/scripts/generate_proto.py` +
`references/anchor_manifest.schema.json` (v1.3.2, proto3 exporter
skeleton).

Mirrors v1.3.0 OpenAPI + v1.3.1 AsyncAPI exporter test suites with
proto-shape adjustments (Service + Rpc instead of PathItem +
Operation/Channel + Operation, proto3 format const, rpc-collision
reason, NEW proto-identifier synthesis pass). All R1-R5 + R1-R3 lessons
from prior exporter retros baked in pre-Codex.

Pins:
  * Pure unit: `_classify_anchor` for each gate (non_contract / shape /
    traversal / bad_anchor_id / ready) + `_to_pascal_case` +
    `_synthesize_service_method`.
  * Path-shape regex: ASCII-exact, no `%` (closes recursive-decode
    attack); rejects URL-encoded / dot-style / unbalanced templates;
    accepts OpenAPI-style path templates.
  * Brace-balance scan + parameter-name charset (v1.3.1 R2 lesson):
    rejects `{tenant.id}`, `{user id}`, `{order/sub}`.
  * Proto-identifier synthesis: rejects all-template, root, leading-
    digit segments; defaults method to `Invoke` when only one literal
    segment.
  * `build_bundle`: empty input → empty services + messages; happy
    path; mixed (ready + skipped + unmapped); duplicate rpc collision
    (first wins); service deduplication.
  * Manifest validates against schema (jsonschema).
  * proto3 file has the v1.3.2 minimal-valid shape (syntax, package,
    services with rpcs, messages).
  * Anchor map: 1 Service entry per distinct service + 1 Rpc entry per
    materialized anchor.
  * CLI: --workspace, --input (bypasses workspace guard for fixture
    mode), --output-dir (implicit-permissive, explicit-rejected,
    outside-workspace records absolute), --package (default + custom +
    invalid), --print-only, --quiet.
  * Safety boundary: script source NEVER imports subprocess; outputs
    stay inside output_dir; no `.tmp` leftovers; idempotent .proto.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT_PATH = (
    REPO_ROOT / "skills" / "proto-from-context" / "scripts"
    / "generate_proto.py"
)
SCHEMA_PATH = (
    REPO_ROOT / "skills" / "proto-from-context" / "references"
    / "anchor_manifest.schema.json"
)


# ---- Module loaders -------------------------------------------------


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location(
        "proto_generate", SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def jsonschema_module():
    return pytest.importorskip("jsonschema")


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---- Workspace + fixture builders -----------------------------------


A61_HEADER = (
    "AnchorID,Stage,ElementType,ElementID,AnchorClass,"
    "ClaimID,A51Ref,CanonicalSource,AnchorStatus\n"
)


def _make_workspace(tmp_path: Path) -> Path:
    (tmp_path / "analysis" / "canonical" / "stage6").mkdir(
        parents=True, exist_ok=True,
    )
    return tmp_path


def _write_a61(workspace: Path, rows: list[dict]) -> Path:
    cols = A61_HEADER.strip().split(",")
    target = workspace / "analysis/canonical/stage6/A61_anchor_map.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        fh.write(A61_HEADER)
        for r in rows:
            fh.write(",".join(r.get(c, "") for c in cols) + "\n")
    return target


def _row(
    anchor_id: str,
    *,
    anchor_class: str = "contract",
    element_id: str = "/orders/created",
    claim_id: str = "C-001",
    a51_ref: str = "",
    element_type: str = "rpc_method",
) -> dict:
    return {
        "AnchorID": anchor_id,
        "Stage": "stage6",
        "ElementType": element_type,
        "ElementID": element_id,
        "AnchorClass": anchor_class,
        "ClaimID": claim_id,
        "A51Ref": a51_ref,
        "CanonicalSource": "stage6/interface_contract_model.md",
        "AnchorStatus": "promoted",
    }


# ---- Pure unit: _classify_anchor ------------------------------------


def test_classify_ready_happy_path(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/created"),
    ) == "ready"


def test_classify_ready_with_path_template(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-002", element_id="/orders/{order_id}/created"),
    ) == "ready"


def test_classify_ready_with_root(helper) -> None:
    """Root path passes shape gate; synthesis will reject it later."""
    assert helper._classify_anchor(
        _row("ANC-003", element_id="/"),
    ) == "ready"


def test_classify_skipped_non_contract(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-004", anchor_class="actor"),
    ) == "skipped_non_contract"


def test_classify_skipped_dot_style_address(helper) -> None:
    """v1.3.2 supports only path-style; dot-style → shape reject."""
    assert helper._classify_anchor(
        _row("ANC-005", element_id="OrderService.CreateOrder"),
    ) == "skipped_shape"


def test_classify_skipped_dot_style_simple(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-006", element_id="orders.created"),
    ) == "skipped_shape"


def test_classify_skipped_shape_no_leading_slash(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-007", element_id="orders/created"),
    ) == "skipped_shape"


def test_classify_skipped_shape_with_space(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-008", element_id="/orders with space"),
    ) == "skipped_shape"


def test_classify_skipped_shape_with_backslash(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-009", element_id="/orders\\admin"),
    ) == "skipped_shape"


def test_classify_skipped_traversal_literal(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-010", element_id="/foo/../bar"),
    ) == "skipped_traversal"


def test_classify_skipped_bad_anchor_id_lowercase(helper) -> None:
    assert helper._classify_anchor(_row("anc-011")) == "skipped_bad_anchor_id"


def test_classify_skipped_bad_anchor_id_no_prefix(helper) -> None:
    assert helper._classify_anchor(_row("XXX-012")) == "skipped_bad_anchor_id"


def test_classify_skipped_bad_anchor_id_empty(helper) -> None:
    assert helper._classify_anchor(_row("")) == "skipped_bad_anchor_id"


# ---- Pure unit: _to_pascal_case -------------------------------------


def test_pascal_case_simple_word(helper) -> None:
    assert helper._to_pascal_case("orders") == "Orders"


def test_pascal_case_snake_case(helper) -> None:
    assert helper._to_pascal_case("order_event") == "OrderEvent"


def test_pascal_case_kebab_case(helper) -> None:
    assert helper._to_pascal_case("order-event") == "OrderEvent"


def test_pascal_case_mixed_separators(helper) -> None:
    assert helper._to_pascal_case("foo_bar-baz.qux") == "FooBarBazQux"


def test_pascal_case_empty(helper) -> None:
    assert helper._to_pascal_case("") == ""


def test_pascal_case_only_separators(helper) -> None:
    assert helper._to_pascal_case("___") == ""


def test_pascal_case_preserves_internal_caps(helper) -> None:
    assert helper._to_pascal_case("orderID") == "OrderID"


# ---- Pure unit: _synthesize_service_method --------------------------


def test_synthesize_simple_two_segment_path(helper) -> None:
    result = helper._synthesize_service_method("/orders/created")
    assert result == ("Orders", "Created", [])


def test_synthesize_template_in_middle(helper) -> None:
    result = helper._synthesize_service_method(
        "/orders/{order_id}/created"
    )
    assert result == ("Orders", "Created", ["order_id"])


def test_synthesize_multi_template(helper) -> None:
    result = helper._synthesize_service_method(
        "/users/{user_id}/orders/{order_id}/items/{item_id}"
    )
    assert result == (
        "Users", "OrdersItems",
        ["user_id", "order_id", "item_id"],
    )


def test_synthesize_single_segment_defaults_to_invoke(helper) -> None:
    result = helper._synthesize_service_method("/orders")
    assert result == ("Orders", "Invoke", [])


def test_synthesize_single_segment_with_template_defaults_to_invoke(
    helper,
) -> None:
    """`/orders/{id}` has only one literal segment; method = Invoke."""
    result = helper._synthesize_service_method("/orders/{id}")
    assert result == ("Orders", "Invoke", ["id"])


def test_synthesize_root_returns_none(helper) -> None:
    assert helper._synthesize_service_method("/") is None


def test_synthesize_all_template_returns_none(helper) -> None:
    assert helper._synthesize_service_method("/{a}/{b}") is None


def test_synthesize_leading_digit_returns_none(helper) -> None:
    """`/123abc/foo` PascalCases to `123abc` → invalid proto identifier."""
    assert helper._synthesize_service_method("/123abc/foo") is None


def test_synthesize_method_leading_digit_returns_none(helper) -> None:
    """`/orders/9bad` → method `9bad` → invalid proto identifier."""
    assert helper._synthesize_service_method("/orders/9bad") is None


def test_synthesize_dedupes_repeated_template(helper) -> None:
    """`/parent/{id}/child/{id}` — same `{id}` twice; param list has
    one entry only."""
    result = helper._synthesize_service_method("/parent/{id}/child/{id}")
    assert result == ("Parent", "Child", ["id"])


def test_synthesize_handles_double_slash(helper) -> None:
    """`/users//orders` — empty middle segment is filtered out."""
    result = helper._synthesize_service_method("/users//orders")
    assert result == ("Users", "Orders", [])


def test_synthesize_snake_case_to_pascal(helper) -> None:
    result = helper._synthesize_service_method(
        "/user_events/signed_up"
    )
    assert result == ("UserEvents", "SignedUp", [])


# ---- _read_a61_rows defensive paths ---------------------------------


def test_read_a61_missing_file(helper, tmp_path) -> None:
    rows, err = helper._read_a61_rows(tmp_path / "no.csv")
    assert rows == []
    assert err is not None
    assert "not found" in err


def test_read_a61_missing_required_column(helper, tmp_path) -> None:
    target = tmp_path / "bad.csv"
    target.write_text(
        "AnchorID,Stage\nANC-001,stage6\n",
        encoding="utf-8",
    )
    rows, err = helper._read_a61_rows(target)
    assert rows == []
    assert err is not None
    assert "missing required columns" in err


def test_read_a61_well_formed(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [
        _row("ANC-001"),
        _row("ANC-002", element_id="/orders/cancelled"),
    ])
    rows, err = helper._read_a61_rows(
        workspace / "analysis/canonical/stage6/A61_anchor_map.csv"
    )
    assert err is None
    assert len(rows) == 2


# ---- build_bundle ---------------------------------------------------


def test_build_bundle_empty_rows(helper) -> None:
    proto_doc, manifest = helper.build_bundle(
        [], package="bsa.contracts", proto_path_str="services.proto",
    )
    assert proto_doc["syntax"] == "proto3"
    assert proto_doc["package"] == "bsa.contracts"
    assert proto_doc["services"] == {}
    assert proto_doc["messages"] == {}
    view_file = manifest["view_files"][0]
    assert view_file["anchor_map"] == []
    assert view_file["unmapped_anchors"] == []
    assert view_file["format"] == "proto3"


def test_build_bundle_happy_path_emits_service_and_rpc(helper) -> None:
    """Each materialized anchor → 1 Rpc entry + (1 Service entry only
    when first-seen for that service); 1 rpc in proto + 2 messages."""
    rows = [_row("ANC-001", element_id="/orders/created")]
    proto_doc, manifest = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    assert "Orders" in proto_doc["services"]
    rpcs = proto_doc["services"]["Orders"]
    assert len(rpcs) == 1
    assert rpcs[0]["method"] == "Created"
    assert rpcs[0]["request_msg"] == "OrdersCreatedRequest"
    assert rpcs[0]["response_msg"] == "OrdersCreatedResponse"
    assert rpcs[0]["tag_provenance"] == "C-001"
    assert proto_doc["messages"]["OrdersCreatedRequest"] == []
    assert proto_doc["messages"]["OrdersCreatedResponse"] == []
    am = manifest["view_files"][0]["anchor_map"]
    kinds = [e["view_element_kind"] for e in am]
    assert kinds == ["Service", "Rpc"]


def test_build_bundle_template_param_becomes_request_field(helper) -> None:
    """`/orders/{order_id}/created` — template name promoted to a
    request-message string field with tag = 1."""
    rows = [_row("ANC-001", element_id="/orders/{order_id}/created")]
    proto_doc, _ = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    fields = proto_doc["messages"]["OrdersCreatedRequest"]
    assert fields == [{"name": "order_id", "type": "string", "tag": 1}]


def test_build_bundle_multi_template_emits_sequential_tags(helper) -> None:
    """3 templates → 3 fields with tags 1, 2, 3."""
    rows = [_row(
        "ANC-001",
        element_id="/users/{user_id}/orders/{order_id}/items/{item_id}",
    )]
    proto_doc, _ = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    fields = proto_doc["messages"]["UsersOrdersItemsRequest"]
    assert fields == [
        {"name": "user_id", "type": "string", "tag": 1},
        {"name": "order_id", "type": "string", "tag": 2},
        {"name": "item_id", "type": "string", "tag": 3},
    ]


def test_classify_rejects_template_with_hyphen(helper) -> None:
    """v1.3.2 R1 lesson: `{order-id}` is legal AsyncAPI/OpenAPI but
    illegal proto3 field name (`ident = letter ( letter | digit | "_"
    )*`). Pre-R1 the brace-balance scan accepted hyphens (charset copied
    from v1.3.1 AsyncAPI exporter), and the synthesis emitted
    `string order-id = 1;` — invalid proto3. Post-R1 the gate's
    template-name charset matches the downstream consumer (proto3
    field grammar) atomically; hyphens surface as
    `element_id_not_path_shaped` at gate time so the operator can
    rename their A61 ElementID to `{order_id}`."""
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/{order-id}/created"),
    ) == "skipped_shape"


def test_classify_rejects_template_with_leading_digit(helper) -> None:
    """v1.3.2 R1 lesson: `{9id}` would render `string 9id = 1;` —
    invalid proto3 field name (must start with letter or underscore).
    Pre-R1 the gate accepted digits-anywhere; post-R1 the proto3
    field grammar `^[A-Za-z_][A-Za-z0-9_]*$` rejects leading digits."""
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/{9id}/created"),
    ) == "skipped_shape"


def test_build_bundle_underscore_template_becomes_field(helper) -> None:
    """Snake_case template names ARE legal proto3 field names; the
    promotion path is preserved post-R1 fix for the underscore form
    (only hyphens / leading-digits / dots / spaces / slashes were
    tightened)."""
    rows = [_row("ANC-001", element_id="/orders/{order_id}/created")]
    proto_doc, _ = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    fields = proto_doc["messages"]["OrdersCreatedRequest"]
    assert fields == [{"name": "order_id", "type": "string", "tag": 1}]


def test_build_bundle_service_dedup_across_anchors(helper) -> None:
    """Two anchors → same service `Orders`. The service block has 2
    rpcs; manifest has 1 Service entry + 2 Rpc entries (Service
    deduplicated)."""
    rows = [
        _row("ANC-001", element_id="/orders/created"),
        _row("ANC-002", element_id="/orders/cancelled"),
    ]
    proto_doc, manifest = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    assert len(proto_doc["services"]) == 1
    assert "Orders" in proto_doc["services"]
    assert len(proto_doc["services"]["Orders"]) == 2
    methods = [r["method"] for r in proto_doc["services"]["Orders"]]
    assert methods == ["Created", "Cancelled"]
    am = manifest["view_files"][0]["anchor_map"]
    kinds = [e["view_element_kind"] for e in am]
    assert kinds == ["Service", "Rpc", "Rpc"]
    # Service entry traces to first anchor that contributed.
    service_entry = next(e for e in am if e["view_element_kind"] == "Service")
    assert service_entry["a61_anchor_id"] == "ANC-001"


def test_build_bundle_distinct_services_emit_separate_blocks(helper) -> None:
    """Two anchors with different services → two service blocks +
    two Service entries."""
    rows = [
        _row("ANC-001", element_id="/orders/created"),
        _row("ANC-002", element_id="/users/registered"),
    ]
    proto_doc, manifest = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    assert set(proto_doc["services"].keys()) == {"Orders", "Users"}
    am = manifest["view_files"][0]["anchor_map"]
    services = sorted(
        e["view_element_id"] for e in am if e["view_element_kind"] == "Service"
    )
    assert services == ["Orders", "Users"]


def test_build_bundle_synthesis_failure_routes_to_unmapped(helper) -> None:
    """Path passes shape but synthesis fails (all-template)."""
    rows = [_row("ANC-001", element_id="/{a}/{b}")]
    proto_doc, manifest = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    assert proto_doc["services"] == {}
    unmapped = manifest["view_files"][0]["unmapped_anchors"]
    assert len(unmapped) == 1
    assert unmapped[0]["reason"] == "proto_identifier_synthesis_failed"
    assert unmapped[0]["a61_anchor_id"] == "ANC-001"


def test_build_bundle_root_path_routes_to_synthesis_failure(helper) -> None:
    """Root `/` passes shape but synthesis returns None."""
    rows = [_row("ANC-001", element_id="/")]
    _, manifest = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    unmapped = manifest["view_files"][0]["unmapped_anchors"]
    assert len(unmapped) == 1
    assert unmapped[0]["reason"] == "proto_identifier_synthesis_failed"


def test_build_bundle_emits_anchor_status_candidate(helper) -> None:
    """v1.3.7: every materialized anchor_map entry MUST carry
    anchor_status='candidate' so CI / release-readiness gates can grep
    for un-promoted skeletons."""
    rows = [
        _row("ANC-001", element_id="/orders/created"),
        _row("ANC-002", element_id="/users/registered"),
    ]
    _, manifest = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    am = manifest["view_files"][0]["anchor_map"]
    statuses = [e.get("anchor_status") for e in am]
    assert statuses, "anchor_map must not be empty"
    assert all(s == "candidate" for s in statuses), (
        f"every anchor_map entry must carry anchor_status='candidate'; "
        f"got {statuses}"
    )


def test_build_bundle_a51_ref_used_when_no_claim_id(helper) -> None:
    rows = [_row(
        "ANC-001", element_id="/orders/created",
        claim_id="", a51_ref="A51-005",
    )]
    proto_doc, _ = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    rpcs = proto_doc["services"]["Orders"]
    assert rpcs[0]["tag_provenance"] == "A51-005"


def test_build_bundle_skipped_anchors_in_unmapped(helper) -> None:
    rows = [
        _row("ANC-001", element_id="/orders/created"),  # ready
        _row("ANC-002", anchor_class="actor"),  # non_contract
        _row("ANC-003", element_id="orders.created"),  # shape (dot-style)
        _row("ANC-004", element_id="/foo/../bar"),  # traversal
        _row("ANC-005", element_id="/{a}/{b}"),  # synth failure
    ]
    proto_doc, manifest = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    assert len(proto_doc["services"]) == 1
    unmapped = manifest["view_files"][0]["unmapped_anchors"]
    reasons = {u["reason"] for u in unmapped}
    assert reasons == {
        "non_contract_anchor_class",
        "element_id_not_path_shaped",
        "element_id_path_traversal",
        "proto_identifier_synthesis_failed",
    }


def test_build_bundle_duplicate_rpc_collision(helper) -> None:
    rows = [
        _row("ANC-001", element_id="/orders/created"),
        _row("ANC-002", element_id="/orders/created"),
    ]
    proto_doc, manifest = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    rpcs = proto_doc["services"]["Orders"]
    assert len(rpcs) == 1
    unmapped = manifest["view_files"][0]["unmapped_anchors"]
    assert len(unmapped) == 1
    assert unmapped[0]["reason"] == "duplicate_rpc_collision"
    assert unmapped[0]["a61_anchor_id"] == "ANC-002"


def test_build_bundle_distinct_paths_same_synthesized_rpc_collide(
    helper,
) -> None:
    """Two anchors with different parameter sets but same
    Service.Method synthesis → second collides as duplicate_rpc."""
    rows = [
        _row("ANC-001", element_id="/orders/{order_id}/created"),
        _row("ANC-002", element_id="/orders/{customer_id}/created"),
    ]
    _, manifest = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    unmapped = manifest["view_files"][0]["unmapped_anchors"]
    assert len(unmapped) == 1
    assert unmapped[0]["reason"] == "duplicate_rpc_collision"


def test_build_bundle_bad_anchor_id_silently_dropped(helper) -> None:
    """Bad AnchorIDs dropped from BOTH services AND unmapped_anchors
    (would fail manifest schema if surfaced)."""
    rows = [
        _row("anc-001", element_id="/orders/created"),  # bad
        _row("ANC-002", element_id="/orders/created"),  # ok
    ]
    proto_doc, manifest = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    assert len(proto_doc["services"]) == 1
    unmapped = manifest["view_files"][0]["unmapped_anchors"]
    assert all(u["a61_anchor_id"] != "anc-001" for u in unmapped)
    assert all(u["a61_anchor_id"] != "" for u in unmapped)


# ---- Manifest schema conformance ------------------------------------


def test_manifest_validates_against_schema(
    helper, jsonschema_module, schema,
) -> None:
    rows = [
        _row("ANC-001", element_id="/orders/created"),
        _row("ANC-002", element_id="/orders/{order_id}/cancelled"),
        _row("ANC-003", anchor_class="actor"),
        _row("ANC-004", element_id="/{a}/{b}"),
    ]
    _, manifest = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    validator = jsonschema_module.Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(manifest),
        key=lambda e: list(e.absolute_path),
    )
    assert errors == [], "\n".join(
        f"{e.absolute_path}: {e.message}" for e in errors
    )


def test_manifest_empty_bundle_validates(
    helper, jsonschema_module, schema,
) -> None:
    _, manifest = helper.build_bundle(
        [], package="bsa.contracts", proto_path_str="services.proto",
    )
    validator = jsonschema_module.Draft202012Validator(schema)
    errors = list(validator.iter_errors(manifest))
    assert errors == []


def test_schema_pins_sidecar_literal(schema) -> None:
    assert schema["properties"]["sidecar"]["const"] == "proto-from-context"


def test_schema_pins_format_discriminator(schema) -> None:
    view_file_schema = schema["properties"]["view_files"]["items"]
    assert view_file_schema["properties"]["format"]["const"] == "proto3"


def test_schema_pins_view_element_kind_enum(schema) -> None:
    item = schema["properties"]["view_files"]["items"]
    am_item = item["properties"]["anchor_map"]["items"]
    assert set(am_item["properties"]["view_element_kind"]["enum"]) == {
        "Service", "Rpc", "Message", "Enum",
    }


def test_schema_pins_unmapped_reason_enum(schema) -> None:
    item = schema["properties"]["view_files"]["items"]
    um_item = item["properties"]["unmapped_anchors"]["items"]
    assert set(um_item["properties"]["reason"]["enum"]) == {
        "non_contract_anchor_class",
        "element_id_not_path_shaped",
        "element_id_path_traversal",
        "duplicate_rpc_collision",
        "proto_identifier_synthesis_failed",
    }


def test_schema_pins_view_element_id_pattern(schema) -> None:
    """v1.3.2 R1 fix: schema enforces the proto3 identifier shape
    `^[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)?$` for
    view_element_id. Reach equality across synthesis-output charset =
    proto3 grammar = manifest constraint."""
    item = schema["properties"]["view_files"]["items"]
    am_item = item["properties"]["anchor_map"]["items"]
    pattern = am_item["properties"]["view_element_id"]["pattern"]
    rx = re.compile(pattern)
    # Service shape (single identifier).
    assert rx.fullmatch("Orders")
    assert rx.fullmatch("UserService")
    assert rx.fullmatch("_Internal")
    # Rpc shape (two dot-joined identifiers).
    assert rx.fullmatch("Orders.Created")
    assert rx.fullmatch("UserService.SignUp")
    # Reject illegal proto identifiers (R1 lesson).
    assert not rx.fullmatch("9Bad")  # leading digit
    assert not rx.fullmatch("order-service")  # hyphen
    assert not rx.fullmatch("Orders.Created.Extra")  # 3-part
    assert not rx.fullmatch("Orders.")  # trailing dot
    assert not rx.fullmatch(".Created")  # leading dot
    assert not rx.fullmatch("")  # empty


def test_schema_pins_path_extension_pattern(schema) -> None:
    view_file_schema = schema["properties"]["view_files"]["items"]
    pattern = view_file_schema["properties"]["path"]["pattern"]
    rx = re.compile(pattern)
    assert rx.search("foo/services.proto")
    assert rx.search("foo/orders.proto")
    assert not rx.search("foo/services.yaml")
    assert not rx.search("foo/services.json")


# ---- Proto rendering -----------------------------------------------


def test_render_minimal_valid_shape(helper) -> None:
    """proto3 file: syntax declaration, package, service, messages."""
    rows = [_row("ANC-001", element_id="/orders/created")]
    proto_doc, _ = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    text = helper._render_proto(proto_doc)
    assert text.startswith('syntax = "proto3";')
    assert "package bsa.contracts;" in text
    assert "service Orders {" in text
    assert "rpc Created(OrdersCreatedRequest) returns (OrdersCreatedResponse);" in text
    assert "message OrdersCreatedRequest {" in text
    assert "message OrdersCreatedResponse {" in text


def test_render_includes_bsa_anchor_comment(helper) -> None:
    rows = [_row("ANC-001", element_id="/orders/created")]
    proto_doc, _ = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    text = helper._render_proto(proto_doc)
    assert "// bsa-anchor: C-001" in text


def test_render_template_param_renders_as_string_field(helper) -> None:
    rows = [_row("ANC-001", element_id="/orders/{order_id}/created")]
    proto_doc, _ = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    text = helper._render_proto(proto_doc)
    assert "string order_id = 1;" in text


def test_render_multi_rpc_service_groups_under_one_block(helper) -> None:
    """Two rpcs for same service render under a single `service { ... }`."""
    rows = [
        _row("ANC-001", element_id="/orders/created"),
        _row("ANC-002", element_id="/orders/cancelled"),
    ]
    proto_doc, _ = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    text = helper._render_proto(proto_doc)
    # Count: should be exactly one `service Orders {` line.
    assert text.count("service Orders {") == 1
    assert "rpc Created(OrdersCreatedRequest)" in text
    assert "rpc Cancelled(OrdersCancelledRequest)" in text


def test_render_default_unary_no_stream_keyword(helper) -> None:
    """Skeleton emits only unary rpcs; `stream` keyword absent."""
    rows = [_row("ANC-001", element_id="/orders/created")]
    proto_doc, _ = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    text = helper._render_proto(proto_doc)
    rpc_line = next(
        line for line in text.splitlines()
        if line.strip().startswith("rpc ")
    )
    assert " stream " not in rpc_line


def test_render_deterministic_ordering(helper) -> None:
    rows = [_row("ANC-001", element_id="/orders/created")]
    doc1, _ = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    doc2, _ = helper.build_bundle(
        rows, package="bsa.contracts", proto_path_str="services.proto",
    )
    assert helper._render_proto(doc1) == helper._render_proto(doc2)


def test_render_empty_bundle_still_valid(helper) -> None:
    """No anchors → still valid proto3 (syntax + package)."""
    proto_doc, _ = helper.build_bundle(
        [], package="bsa.contracts", proto_path_str="services.proto",
    )
    text = helper._render_proto(proto_doc)
    assert text.startswith('syntax = "proto3";')
    assert "package bsa.contracts;" in text


# ---- Path-shape regex hardening (v1.3.0 R1+R2 lessons) --------------


def test_path_shape_rejects_url_encoded_traversal_lowercase(helper) -> None:
    """v1.3.0 R2 lesson: encoded `..` rejected by regex (`%` not in
    char class), surfaces as `skipped_shape`."""
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/foo/%2e%2e/bar"),
    ) == "skipped_shape"


def test_path_shape_rejects_url_encoded_traversal_uppercase(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/foo/%2E%2E/bar"),
    ) == "skipped_shape"


def test_path_shape_rejects_double_encoded_traversal(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/foo/%252e%252e/bar"),
    ) == "skipped_shape"


def test_path_shape_rejects_triple_encoded_traversal(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/foo/%25252e%25252e/bar"),
    ) == "skipped_shape"


def test_path_shape_rejects_truncated_percent_escape(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/%"),
    ) == "skipped_shape"


def test_path_shape_rejects_invalid_hex_percent_escape(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/%GG"),
    ) == "skipped_shape"


def test_path_shape_rejects_any_percent_in_path(helper) -> None:
    """v1.3.0 R2 lesson: ANY `%` rejected, even legit-looking `%2D`."""
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/foo-%2D/bar"),
    ) == "skipped_shape"


def test_path_shape_rejects_null_byte(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders\x00/admin"),
    ) == "skipped_shape"


def test_path_shape_rejects_unicode_digits(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/٠١٢"),
    ) == "skipped_shape"


# ---- Brace-balance scan (v1.3.0 R1-FIX-2 + v1.3.1 R2) ---------------


def test_brace_rejects_unbalanced_open_brace(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/{id"),
    ) == "skipped_shape"


def test_brace_rejects_unbalanced_close_brace(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/id}"),
    ) == "skipped_shape"


def test_brace_rejects_empty_template(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/{}"),
    ) == "skipped_shape"


def test_brace_rejects_misordered_braces(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/}{"),
    ) == "skipped_shape"


def test_brace_rejects_nested_open_brace(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/{{id}}"),
    ) == "skipped_shape"


def test_brace_rejects_template_with_dot(helper) -> None:
    """v1.3.1 R2 lesson reused: `{tenant.id}` → param-name charset
    rejection."""
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/{tenant.id}/created"),
    ) == "skipped_shape"


def test_brace_rejects_template_with_space(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/{user id}/created"),
    ) == "skipped_shape"


def test_brace_rejects_template_with_slash(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/orders/{order/sub}/created"),
    ) == "skipped_shape"


def test_brace_accepts_multi_template(helper) -> None:
    assert helper._classify_anchor(
        _row("ANC-001", element_id="/users/{user_id}/orders/{order_id}/items"),
    ) == "ready"


# ---- CLI ------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_workspace_not_initialized_returns_2(tmp_path) -> None:
    result = _run_cli("--workspace", str(tmp_path), "--print-only")
    assert result.returncode == 2
    assert "not initialized" in result.stderr


def test_cli_missing_a61_returns_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    result = _run_cli("--workspace", str(workspace), "--print-only")
    assert result.returncode == 2
    assert "not found" in result.stderr or "Stage 6" in result.stderr


def test_cli_print_only_emits_manifest_no_writes(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/orders/created")])
    result = _run_cli(
        "--workspace", str(workspace), "--print-only",
    )
    assert result.returncode == 0
    manifest = json.loads(result.stdout)
    assert manifest["sidecar"] == "proto-from-context"
    out_dir = workspace / "analysis/handoff/contracts/proto"
    assert not (out_dir / "services.proto").exists()
    assert not (out_dir / "anchor_manifest.json").exists()


def test_cli_writes_both_files(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/orders/created")])
    result = _run_cli(
        "--workspace", str(workspace), "--quiet",
    )
    assert result.returncode == 0
    out_dir = workspace / "analysis/handoff/contracts/proto"
    assert (out_dir / "services.proto").is_file()
    assert (out_dir / "anchor_manifest.json").is_file()


def test_cli_input_override_works_without_initialized_workspace(
    tmp_path,
) -> None:
    """v1.3.0 R1-FIX-1 lesson baked in pre-Codex: --input bypasses the
    workspace `analysis/` guard so fixture-mode runs without an
    initialized workspace."""
    custom_input = tmp_path / "fixture_a61.csv"
    custom_input.write_text(
        A61_HEADER + ",".join([
            "ANC-FIX-001", "stage6", "rpc_method",
            "/fixture/path", "contract", "C-FIX-001", "", "src.md",
            "promoted",
        ]) + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = _run_cli(
        "--workspace", str(tmp_path),  # uninitialized
        "--input", str(custom_input),
        "--output-dir", str(out_dir),
        "--quiet",
    )
    assert result.returncode == 0, (
        f"--input + --output-dir should work without init; "
        f"stderr={result.stderr!r}"
    )
    assert (out_dir / "services.proto").is_file()
    manifest = json.loads(
        (out_dir / "anchor_manifest.json").read_text(encoding="utf-8")
    )
    am = manifest["view_files"][0]["anchor_map"]
    assert any(e["a61_anchor_id"] == "ANC-FIX-001" for e in am)


def test_cli_output_dir_implicit_missing_permissive(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/orders/created")])
    out_dir = workspace / "analysis/handoff/contracts/proto"
    assert not out_dir.exists()
    result = _run_cli("--workspace", str(workspace), "--quiet")
    assert result.returncode == 0
    assert (out_dir / "services.proto").is_file()


def test_cli_output_dir_explicit_missing_returns_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/orders/created")])
    bogus = tmp_path / "does_not_exist"
    result = _run_cli(
        "--workspace", str(workspace),
        "--output-dir", str(bogus),
        "--print-only",
    )
    assert result.returncode == 2
    assert "does not exist" in result.stderr


def test_cli_output_dir_outside_workspace_records_absolute_path(
    tmp_path,
) -> None:
    """v1.2.19 R1-FIX-2 + v1.3.0/v1.3.1 lesson: outside-workspace
    --output-dir records absolute path in manifest."""
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    workspace = _make_workspace(ws_root)
    _write_a61(workspace, [_row("ANC-001", element_id="/orders/created")])
    external_out = tmp_path / "external"
    external_out.mkdir()
    result = _run_cli(
        "--workspace", str(workspace),
        "--output-dir", str(external_out),
        "--quiet",
    )
    assert result.returncode == 0
    manifest = json.loads(
        (external_out / "anchor_manifest.json").read_text(encoding="utf-8")
    )
    recorded_path = manifest["view_files"][0]["path"]
    assert Path(recorded_path).is_absolute()


def test_cli_default_package(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/orders/created")])
    result = _run_cli("--workspace", str(workspace), "--quiet")
    assert result.returncode == 0
    proto_text = (
        workspace / "analysis/handoff/contracts/proto/services.proto"
    ).read_text(encoding="utf-8")
    assert "package bsa.contracts;" in proto_text


def test_cli_custom_package(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/orders/created")])
    result = _run_cli(
        "--workspace", str(workspace),
        "--package", "my.events.v1",
        "--quiet",
    )
    assert result.returncode == 0
    proto_text = (
        workspace / "analysis/handoff/contracts/proto/services.proto"
    ).read_text(encoding="utf-8")
    assert "package my.events.v1;" in proto_text


def test_cli_invalid_package_returns_2(tmp_path) -> None:
    """`--package` validation: dot-separated identifiers only."""
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/orders/created")])
    result = _run_cli(
        "--workspace", str(workspace),
        "--package", "bad-package-name",  # hyphens not allowed
        "--print-only",
    )
    assert result.returncode == 2
    assert "valid proto3 package name" in result.stderr


def test_cli_invalid_package_leading_digit_returns_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/orders/created")])
    result = _run_cli(
        "--workspace", str(workspace),
        "--package", "1bad.package",
        "--print-only",
    )
    assert result.returncode == 2


# ---- Safety boundary ------------------------------------------------


def test_script_does_not_import_subprocess() -> None:
    """Structural pin: exporter is operator-driven, no shelling out."""
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "subprocess" not in src, (
        "generate_proto.py imported subprocess — verify no "
        "git/commit/push/protoc call slipped in."
    )


def test_no_tmp_files_left_after_write(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/orders/created")])
    result = _run_cli("--workspace", str(workspace), "--quiet")
    assert result.returncode == 0
    out_dir = workspace / "analysis/handoff/contracts/proto"
    leftovers = [
        p.name for p in out_dir.iterdir()
        if p.name.startswith(".proto_exporter_")
    ]
    assert leftovers == [], f"tempfile leftovers: {leftovers}"


def test_exporter_does_not_modify_canonical_state(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/orders/created")])
    canonical_before = {
        p for p in (workspace / "analysis/canonical").rglob("*") if p.is_file()
    }
    result = _run_cli("--workspace", str(workspace), "--quiet")
    assert result.returncode == 0
    canonical_after = {
        p for p in (workspace / "analysis/canonical").rglob("*") if p.is_file()
    }
    assert canonical_before == canonical_after, (
        "exporter modified analysis/canonical/ — INV-02 violation"
    )


def test_idempotent_byte_identical_proto(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/orders/created")])
    _run_cli("--workspace", str(workspace), "--quiet")
    proto_file = (
        workspace / "analysis/handoff/contracts/proto/services.proto"
    )
    first = proto_file.read_text(encoding="utf-8")
    _run_cli("--workspace", str(workspace), "--quiet")
    second = proto_file.read_text(encoding="utf-8")
    assert first == second
