"""Tests for `skills/asyncapi-from-context/scripts/generate_asyncapi.py` +
`references/anchor_manifest.schema.json` (v1.3.1, AsyncAPI exporter
skeleton).

Mirrors v1.3.0 OpenAPI exporter test suite with AsyncAPI shape
adjustments (Channel + Operation instead of PathItem + Operation,
asyncapi-3.0 format const, channel-collision reason, etc.). All R1-R5
lessons from v1.3.0 retro baked in pre-Codex.

Pins:
  * Pure unit: `_classify_anchor` for each gate (non_contract / shape /
    traversal / bad_anchor_id / ready) + `_sanitize_anchor_id_for_key`.
  * Channel-shape regex: ASCII-exact, no `%` (closes recursive-decode
    attack); rejects URL-encoded / dot-style / unbalanced templates;
    accepts OpenAPI-style path templates.
  * `build_bundle`: empty input → empty channels + operations; happy
    path; mixed (ready + skipped + unmapped); duplicate channel
    collision (first wins).
  * Manifest validates against schema (jsonschema).
  * AsyncAPI YAML has the v1.3.1 minimal-valid shape (asyncapi/info/
    channels/operations).
  * Anchor map has 2 entries per materialized anchor (Channel + Operation).
  * CLI: --workspace, --input (bypasses workspace guard for fixture
    mode), --output-dir (implicit-permissive, explicit-rejected,
    outside-workspace records absolute), --title, --version,
    --print-only, --quiet.
  * Safety boundary: script source NEVER imports subprocess; outputs
    stay inside output_dir; no `.tmp` leftovers; idempotent YAML.
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
    REPO_ROOT / "skills" / "asyncapi-from-context" / "scripts"
    / "generate_asyncapi.py"
)
SCHEMA_PATH = (
    REPO_ROOT / "skills" / "asyncapi-from-context" / "references"
    / "anchor_manifest.schema.json"
)


# ---- Module loaders -------------------------------------------------


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location(
        "asyncapi_generate", SCRIPT_PATH,
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
def yaml_module():
    return pytest.importorskip("yaml")


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
    element_id: str = "/user/signedup",
    claim_id: str = "C-001",
    a51_ref: str = "",
    element_type: str = "event_channel",
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
    status, _ = helper._classify_anchor(_row("ANC-001", element_id="/user/signedup"))
    assert status == "ready"


def test_classify_ready_with_path_template(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-002", element_id="/orders/{order_id}/created")
    )
    assert status == "ready"


def test_classify_ready_with_root(helper) -> None:
    status, _ = helper._classify_anchor(_row("ANC-003", element_id="/"))
    assert status == "ready"


def test_classify_skipped_non_contract(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-004", anchor_class="actor")
    )
    assert status == "skipped_non_contract"


def test_classify_skipped_dot_style_address(helper) -> None:
    """v1.3.1 supports only path-style; dot-style → shape reject."""
    status, _ = helper._classify_anchor(
        _row("ANC-005", element_id="user.signed_up")
    )
    assert status == "skipped_shape"


def test_classify_skipped_dot_style_with_template(helper) -> None:
    """`user.{user_id}.signed_up` — dot-style with template; rejected."""
    status, _ = helper._classify_anchor(
        _row("ANC-006", element_id="user.{user_id}.signed_up")
    )
    assert status == "skipped_shape"


def test_classify_skipped_shape_no_leading_slash(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-007", element_id="user/signedup")
    )
    assert status == "skipped_shape"


def test_classify_skipped_shape_with_space(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-008", element_id="/user with space")
    )
    assert status == "skipped_shape"


def test_classify_skipped_shape_with_backslash(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-009", element_id="/user\\admin")
    )
    assert status == "skipped_shape"


def test_classify_skipped_traversal_literal(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-010", element_id="/foo/../bar")
    )
    assert status == "skipped_traversal"


def test_classify_skipped_bad_anchor_id_lowercase(helper) -> None:
    status, _ = helper._classify_anchor(_row("anc-011"))
    assert status == "skipped_bad_anchor_id"


def test_classify_skipped_bad_anchor_id_no_prefix(helper) -> None:
    status, _ = helper._classify_anchor(_row("XXX-012"))
    assert status == "skipped_bad_anchor_id"


def test_classify_skipped_bad_anchor_id_empty(helper) -> None:
    status, _ = helper._classify_anchor(_row(""))
    assert status == "skipped_bad_anchor_id"


# ---- Pure unit: _sanitize_anchor_id_for_key -------------------------


def test_sanitize_anchor_id_lowercases(helper) -> None:
    assert helper._sanitize_anchor_id_for_key("ANC-001") == "anc_001"


def test_sanitize_anchor_id_replaces_hyphens(helper) -> None:
    assert helper._sanitize_anchor_id_for_key(
        "ANC-USER-EVENT-007"
    ) == "anc_user_event_007"


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
    _write_a61(workspace, [_row("ANC-001"), _row("ANC-002", element_id="/user/login")])
    rows, err = helper._read_a61_rows(
        workspace / "analysis/canonical/stage6/A61_anchor_map.csv"
    )
    assert err is None
    assert len(rows) == 2


# ---- build_bundle ---------------------------------------------------


def test_build_bundle_empty_rows(helper) -> None:
    asyncapi_doc, manifest = helper.build_bundle(
        [], title="Test", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    assert asyncapi_doc["asyncapi"] == "3.0.0"
    assert asyncapi_doc["info"] == {"title": "Test", "version": "1.0.0"}
    assert asyncapi_doc["channels"] == {}
    assert asyncapi_doc["operations"] == {}
    view_file = manifest["view_files"][0]
    assert view_file["anchor_map"] == []
    assert view_file["unmapped_anchors"] == []
    assert view_file["format"] == "asyncapi-3.0"


def test_build_bundle_happy_path_emits_channel_and_operation(helper) -> None:
    """Conservation: each materialized anchor → 2 manifest entries
    (Channel + Operation) + 1 channel + 1 operation in YAML."""
    rows = [_row("ANC-001", element_id="/user/signedup")]
    asyncapi_doc, manifest = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    assert "channel_anc_001" in asyncapi_doc["channels"]
    assert "channel_anc_001" in asyncapi_doc["operations"]
    ch = asyncapi_doc["channels"]["channel_anc_001"]
    assert ch["address"] == "/user/signedup"
    # Non-templated address → no `parameters` field (R1 fix invariant:
    # parameters appears ONLY when address has `{...}` expressions).
    assert "parameters" not in ch
    op = asyncapi_doc["operations"]["channel_anc_001"]
    assert op["action"] == "send"
    assert op["channel"] == {"$ref": "#/channels/channel_anc_001"}
    assert op["tags"] == [{"name": "bsa-anchor:C-001"}]
    am = manifest["view_files"][0]["anchor_map"]
    assert len(am) == 2
    kinds = {e["view_element_kind"] for e in am}
    assert kinds == {"Channel", "Operation"}


def test_build_bundle_templated_address_emits_parameters(helper) -> None:
    """R1 fix: AsyncAPI 3.0 spec requires `channels[*].parameters` for
    every Channel Address Expression `{name}` in the address.
    Pre-R1 the exporter emitted only `address` + `messages`, producing
    a non-conformant document for templated addresses."""
    rows = [_row(
        "ANC-002",
        element_id="/orders/{order_id}/created",
    )]
    asyncapi_doc, _ = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    ch = asyncapi_doc["channels"]["channel_anc_002"]
    assert "parameters" in ch
    assert "order_id" in ch["parameters"]
    assert "description" in ch["parameters"]["order_id"]
    # Operator-readable hint (mentions the original `{name}` and address).
    desc = ch["parameters"]["order_id"]["description"]
    assert "{order_id}" in desc
    assert "/orders/{order_id}/created" in desc


def test_build_bundle_multi_template_emits_all_parameters(helper) -> None:
    """Multiple `{name}` templates → all surface in `parameters`."""
    rows = [_row(
        "ANC-003",
        element_id="/users/{user_id}/orders/{order_id}/items/{item_id}",
    )]
    asyncapi_doc, _ = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    ch = asyncapi_doc["channels"]["channel_anc_003"]
    assert "parameters" in ch
    assert set(ch["parameters"].keys()) == {"user_id", "order_id", "item_id"}


def test_build_bundle_hyphenated_template_emits_parameter(helper) -> None:
    """R2 fix: AsyncAPI 3.0 parameter names allow hyphen
    (`^[A-Za-z0-9_-]+$`). Pre-R2 the brace-balance scan accepted
    `{order-id}` but the extractor's regex `[A-Za-z0-9_]+` (no
    hyphen) silently missed it → parameter never emitted → channel
    non-conformant. Post-R2 both gates share the same charset."""
    rows = [_row(
        "ANC-HYPH-001",
        element_id="/orders/{order-id}/created",
    )]
    asyncapi_doc, _ = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    ch = asyncapi_doc["channels"]["channel_anc_hyph_001"]
    assert "parameters" in ch
    assert "order-id" in ch["parameters"]


def test_classify_rejects_template_with_dot(helper) -> None:
    """R2 fix: AsyncAPI 3.0 parameter names DO NOT allow dot. Pre-R2
    the brace-balance scan accepted `{tenant.id}` because no charset
    check ran inside templates; the channel was emitted as `ready`
    but with no `parameters` entry for `tenant.id` → non-conformant
    document. Post-R2 the brace-balance scan rejects illegal-name
    templates as `skipped_shape`, surfacing the issue at gate time."""
    status, _ = helper._classify_anchor(
        _row("ANC-DOT-001", element_id="/orders/{tenant.id}/created")
    )
    assert status == "skipped_shape"


def test_classify_rejects_template_with_space(helper) -> None:
    """Defensive: parameter name with space would also fail
    `^[A-Za-z0-9_-]+$`. Brace-balance scan rejects."""
    status, _ = helper._classify_anchor(
        _row("ANC-SP-001", element_id="/orders/{user id}/created")
    )
    assert status == "skipped_shape"


def test_classify_rejects_template_with_slash(helper) -> None:
    """Defensive: parameter name with slash (already would be caught
    by brace-balance scan as misordered, but pin the explicit charset
    rejection too)."""
    status, _ = helper._classify_anchor(
        _row("ANC-SL-001", element_id="/orders/{order/sub}/created")
    )
    assert status == "skipped_shape"


def test_build_bundle_repeated_template_dedupes(helper) -> None:
    """If the same `{name}` appears twice in the address (unusual but
    legal under our brace-balance scan), `parameters` should have one
    entry, not two — dict-key dedup is automatic but we pin the
    invariant."""
    rows = [_row(
        "ANC-004",
        element_id="/parent/{id}/child/{id}",
    )]
    asyncapi_doc, _ = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    ch = asyncapi_doc["channels"]["channel_anc_004"]
    assert "parameters" in ch
    assert list(ch["parameters"].keys()) == ["id"]


def test_build_bundle_emits_anchor_status_candidate(helper) -> None:
    """v1.3.7: every materialized anchor_map entry MUST carry
    anchor_status='candidate' so CI / release-readiness gates can grep
    for un-promoted skeletons."""
    rows = [
        _row("ANC-001", element_id="/user/signedup"),
        _row("ANC-002", element_id="/order/created"),
    ]
    _, manifest = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    am = manifest["view_files"][0]["anchor_map"]
    # 2 anchors × 2 entries each (Channel + Operation) = 4 entries
    assert len(am) == 4
    statuses = [e.get("anchor_status") for e in am]
    assert all(s == "candidate" for s in statuses), (
        f"every anchor_map entry must carry anchor_status='candidate'; "
        f"got {statuses}"
    )


def test_build_bundle_a51_ref_used_when_no_claim_id(helper) -> None:
    rows = [_row(
        "ANC-002", element_id="/orders/created",
        claim_id="", a51_ref="A51-005",
    )]
    asyncapi_doc, _ = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    op = asyncapi_doc["operations"]["channel_anc_002"]
    assert op["tags"] == [{"name": "bsa-anchor:A51-005"}]


def test_build_bundle_skipped_anchors_in_unmapped(helper) -> None:
    rows = [
        _row("ANC-001", element_id="/user/signedup"),  # ready
        _row("ANC-002", anchor_class="actor"),  # non_contract
        _row("ANC-003", element_id="user.signed_up"),  # shape (dot-style)
        _row("ANC-004", element_id="/foo/../bar"),  # traversal
    ]
    asyncapi_doc, manifest = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    assert len(asyncapi_doc["channels"]) == 1
    assert len(asyncapi_doc["operations"]) == 1
    unmapped = manifest["view_files"][0]["unmapped_anchors"]
    reasons = {u["reason"] for u in unmapped}
    assert reasons == {
        "non_contract_anchor_class",
        "element_id_not_channel_shaped",
        "element_id_path_traversal",
    }


def test_build_bundle_duplicate_channel_collision(helper) -> None:
    rows = [
        _row("ANC-001", element_id="/user/signedup"),
        _row("ANC-002", element_id="/user/signedup"),
    ]
    asyncapi_doc, manifest = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    assert len(asyncapi_doc["channels"]) == 1
    unmapped = manifest["view_files"][0]["unmapped_anchors"]
    assert len(unmapped) == 1
    assert unmapped[0]["reason"] == "duplicate_channel_collision"
    assert unmapped[0]["a61_anchor_id"] == "ANC-002"


def test_build_bundle_bad_anchor_id_silently_dropped(helper) -> None:
    """Bad AnchorIDs dropped from BOTH channels AND unmapped_anchors
    (would fail manifest schema if surfaced)."""
    rows = [
        _row("anc-001", element_id="/user/signedup"),  # bad
        _row("ANC-002", element_id="/user/signedup"),  # ok
    ]
    asyncapi_doc, manifest = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    assert len(asyncapi_doc["channels"]) == 1
    unmapped = manifest["view_files"][0]["unmapped_anchors"]
    assert all(u["a61_anchor_id"] != "anc-001" for u in unmapped)
    assert all(u["a61_anchor_id"] != "" for u in unmapped)


# ---- Manifest schema conformance ------------------------------------


def test_manifest_validates_against_schema(
    helper, jsonschema_module, schema,
) -> None:
    rows = [
        _row("ANC-001", element_id="/user/signedup"),
        _row("ANC-002", element_id="/orders/{order_id}/created"),
        _row("ANC-003", anchor_class="actor"),
    ]
    _, manifest = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
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
        [], title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    validator = jsonschema_module.Draft202012Validator(schema)
    errors = list(validator.iter_errors(manifest))
    assert errors == []


def test_schema_pins_sidecar_literal(schema) -> None:
    assert schema["properties"]["sidecar"]["const"] == "asyncapi-from-context"


def test_schema_pins_format_discriminator(schema) -> None:
    view_file_schema = schema["properties"]["view_files"]["items"]
    assert view_file_schema["properties"]["format"]["const"] == "asyncapi-3.0"


def test_schema_pins_view_element_kind_enum(schema) -> None:
    item = schema["properties"]["view_files"]["items"]
    am_item = item["properties"]["anchor_map"]["items"]
    assert set(am_item["properties"]["view_element_kind"]["enum"]) == {
        "Channel", "Operation", "Message", "Server",
    }


def test_schema_pins_unmapped_reason_enum(schema) -> None:
    item = schema["properties"]["view_files"]["items"]
    um_item = item["properties"]["unmapped_anchors"]["items"]
    assert set(um_item["properties"]["reason"]["enum"]) == {
        "non_contract_anchor_class",
        "element_id_not_channel_shaped",
        "element_id_path_traversal",
        "duplicate_channel_collision",
    }


def test_schema_pins_path_extension_pattern(schema) -> None:
    view_file_schema = schema["properties"]["view_files"]["items"]
    pattern = view_file_schema["properties"]["path"]["pattern"]
    rx = re.compile(pattern)
    assert rx.search("foo/asyncapi.yaml")
    assert rx.search("foo/asyncapi.yml")
    assert rx.search("foo/asyncapi.json")
    assert not rx.search("foo/asyncapi.txt")


# ---- AsyncAPI YAML rendering ----------------------------------------


def test_yaml_renders_minimal_valid_shape(helper, yaml_module) -> None:
    rows = [_row("ANC-001", element_id="/user/signedup")]
    asyncapi_doc, _ = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    yaml_text = helper._render_yaml(asyncapi_doc)
    parsed = yaml_module.safe_load(yaml_text)
    assert parsed["asyncapi"] == "3.0.0"
    assert "info" in parsed
    assert "channels" in parsed
    assert "operations" in parsed
    assert "channel_anc_001" in parsed["channels"]


def test_yaml_deterministic_ordering(helper) -> None:
    rows = [_row("ANC-001", element_id="/user/signedup")]
    doc1, _ = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    doc2, _ = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="asyncapi.yaml",
    )
    assert helper._render_yaml(doc1) == helper._render_yaml(doc2)


# ---- Channel-shape regex hardening (v1.3.0 R1+R2 lessons) -----------


def test_channel_shape_rejects_url_encoded_traversal_lowercase(helper) -> None:
    """v1.3.0 R2 lesson: encoded `..` rejected by regex (`%` not in
    char class), surfaces as `skipped_shape`."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/foo/%2e%2e/bar")
    )
    assert status == "skipped_shape"


def test_channel_shape_rejects_url_encoded_traversal_uppercase(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/foo/%2E%2E/bar")
    )
    assert status == "skipped_shape"


def test_channel_shape_rejects_double_encoded_traversal(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/foo/%252e%252e/bar")
    )
    assert status == "skipped_shape"


def test_channel_shape_rejects_triple_encoded_traversal(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/foo/%25252e%25252e/bar")
    )
    assert status == "skipped_shape"


def test_channel_shape_rejects_truncated_percent_escape(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/%")
    )
    assert status == "skipped_shape"


def test_channel_shape_rejects_invalid_hex_percent_escape(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/%GG")
    )
    assert status == "skipped_shape"


def test_channel_shape_rejects_any_percent_in_path(helper) -> None:
    """v1.3.0 R2 lesson: ANY `%` rejected, even legit-looking `%2D`."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/foo-%2D/bar")
    )
    assert status == "skipped_shape"


def test_channel_shape_rejects_null_byte(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users\x00/admin")
    )
    assert status == "skipped_shape"


def test_channel_shape_rejects_unicode_digits(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/٠١٢")
    )
    assert status == "skipped_shape"


# ---- Brace-balance scan (v1.3.0 R1-FIX-2 part b) --------------------


def test_channel_shape_rejects_unbalanced_open_brace(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/{id")
    )
    assert status == "skipped_shape"


def test_channel_shape_rejects_unbalanced_close_brace(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/id}")
    )
    assert status == "skipped_shape"


def test_channel_shape_rejects_empty_template(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/{}")
    )
    assert status == "skipped_shape"


def test_channel_shape_rejects_misordered_braces(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/}{")
    )
    assert status == "skipped_shape"


def test_channel_shape_rejects_nested_open_brace(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/{{id}}")
    )
    assert status == "skipped_shape"


def test_channel_shape_accepts_multi_template(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/{user_id}/orders/{order_id}/items")
    )
    assert status == "ready"


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
    _write_a61(workspace, [_row("ANC-001", element_id="/user/signedup")])
    result = _run_cli(
        "--workspace", str(workspace), "--print-only",
    )
    assert result.returncode == 0
    manifest = json.loads(result.stdout)
    assert manifest["sidecar"] == "asyncapi-from-context"
    out_dir = workspace / "analysis/handoff/contracts/asyncapi"
    assert not (out_dir / "asyncapi.yaml").exists()
    assert not (out_dir / "anchor_manifest.json").exists()


def test_cli_writes_both_files(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/user/signedup")])
    result = _run_cli(
        "--workspace", str(workspace), "--quiet",
    )
    assert result.returncode == 0
    out_dir = workspace / "analysis/handoff/contracts/asyncapi"
    assert (out_dir / "asyncapi.yaml").is_file()
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
            "ANC-FIX-001", "stage6", "event_channel",
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
    assert (out_dir / "asyncapi.yaml").is_file()
    manifest = json.loads(
        (out_dir / "anchor_manifest.json").read_text(encoding="utf-8")
    )
    am = manifest["view_files"][0]["anchor_map"]
    assert any(e["a61_anchor_id"] == "ANC-FIX-001" for e in am)


def test_cli_output_dir_implicit_missing_permissive(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/user/signedup")])
    out_dir = workspace / "analysis/handoff/contracts/asyncapi"
    assert not out_dir.exists()
    result = _run_cli("--workspace", str(workspace), "--quiet")
    assert result.returncode == 0
    assert (out_dir / "asyncapi.yaml").is_file()


def test_cli_output_dir_explicit_missing_returns_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/user/signedup")])
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
    """v1.2.19 R1-FIX-2 + v1.3.0 lesson: outside-workspace --output-dir
    records absolute path in manifest."""
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    workspace = _make_workspace(ws_root)
    _write_a61(workspace, [_row("ANC-001", element_id="/user/signedup")])
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


def test_cli_title_and_version(tmp_path, yaml_module) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/user/signedup")])
    result = _run_cli(
        "--workspace", str(workspace),
        "--title", "Custom Events",
        "--version", "2.5.7",
        "--quiet",
    )
    assert result.returncode == 0
    api_yaml = (workspace / "analysis/handoff/contracts/asyncapi/asyncapi.yaml")
    parsed = yaml_module.safe_load(api_yaml.read_text(encoding="utf-8"))
    assert parsed["info"] == {"title": "Custom Events", "version": "2.5.7"}


# ---- Safety boundary ------------------------------------------------


def test_script_does_not_import_subprocess() -> None:
    """Structural pin: exporter is operator-driven, no shelling out."""
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "subprocess" not in src, (
        "generate_asyncapi.py imported subprocess — verify no "
        "git/commit/push call slipped in."
    )


def test_no_tmp_files_left_after_write(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/user/signedup")])
    result = _run_cli("--workspace", str(workspace), "--quiet")
    assert result.returncode == 0
    out_dir = workspace / "analysis/handoff/contracts/asyncapi"
    leftovers = [
        p.name for p in out_dir.iterdir()
        if p.name.startswith(".asyncapi_exporter_")
    ]
    assert leftovers == [], f"tempfile leftovers: {leftovers}"


def test_exporter_does_not_modify_canonical_state(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/user/signedup")])
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


def test_idempotent_byte_identical_yaml(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/user/signedup")])
    _run_cli("--workspace", str(workspace), "--quiet")
    api_yaml = workspace / "analysis/handoff/contracts/asyncapi/asyncapi.yaml"
    first = api_yaml.read_text(encoding="utf-8")
    _run_cli("--workspace", str(workspace), "--quiet")
    second = api_yaml.read_text(encoding="utf-8")
    assert first == second
