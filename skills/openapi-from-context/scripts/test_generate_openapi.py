"""Tests for `skills/openapi-from-context/scripts/generate_openapi.py` +
`references/anchor_manifest.schema.json` (v1.3.0, OpenAPI exporter
skeleton).

Pins:
  * Pure unit: `_classify_anchor` for each gate (non_contract / shape /
    traversal / bad_anchor_id / ready) + `_sanitize_anchor_id_for_
    operationid` (lowercase + hyphen→underscore).
  * Path-shape regex: accepts OpenAPI-style templates, rejects shell /
    traversal / null / Unicode-broad characters.
  * `build_bundle`: empty input → empty paths + empty manifest entries;
    happy path; mixed (ready + skipped + unmapped); duplicate path
    collision (first wins).
  * Manifest validates against the schema (jsonschema).
  * OpenAPI YAML has the v1.3.0 minimal-valid shape (openapi/info/paths).
  * Anchor map has 2 entries per materialized anchor (PathItem +
    Operation) — pinned conservation invariant.
  * CLI: --workspace, --input, --output-dir (implicit-permissive,
    explicit-rejected), --title, --version, --print-only, --quiet,
    error paths.
  * Safety boundary: script source NEVER imports subprocess; outputs
    stay inside output_dir; no `.tmp` leftovers; atomic writes are
    idempotent (same input → byte-identical bundle modulo timestamp).
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
    REPO_ROOT / "skills" / "openapi-from-context" / "scripts"
    / "generate_openapi.py"
)
SCHEMA_PATH = (
    REPO_ROOT / "skills" / "openapi-from-context" / "references"
    / "anchor_manifest.schema.json"
)


# ---- Module loaders -------------------------------------------------


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location(
        "openapi_generate", SCRIPT_PATH,
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
    """Write a synthetic A61 CSV. Returns the path."""
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
    element_id: str = "/users",
    claim_id: str = "C-001",
    a51_ref: str = "",
    element_type: str = "interface_endpoint",
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
    status, _ = helper._classify_anchor(_row("ANC-001", element_id="/users"))
    assert status == "ready"


def test_classify_ready_with_path_template(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-002", element_id="/users/{id}/orders/{order_id}")
    )
    assert status == "ready"


def test_classify_skipped_non_contract(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-003", anchor_class="actor")
    )
    assert status == "skipped_non_contract"


def test_classify_skipped_non_contract_system(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-004", anchor_class="system")
    )
    assert status == "skipped_non_contract"


def test_classify_skipped_shape_no_leading_slash(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-005", element_id="users")
    )
    assert status == "skipped_shape"


def test_classify_skipped_shape_with_space(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-006", element_id="/users with space")
    )
    assert status == "skipped_shape"


def test_classify_skipped_shape_with_backslash(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-007", element_id="/users\\admin")
    )
    assert status == "skipped_shape"


def test_classify_skipped_traversal(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-008", element_id="/foo/../bar")
    )
    assert status == "skipped_traversal"


def test_classify_skipped_traversal_at_start(helper) -> None:
    """Even with path-shaped chars overall, `..` is rejected. Catches
    the operator typo `/..` (path starting with traversal)."""
    status, _ = helper._classify_anchor(
        _row("ANC-009", element_id="/..")
    )
    assert status == "skipped_traversal"


def test_classify_skipped_bad_anchor_id_lowercase(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("anc-010")  # lowercase — pattern requires uppercase
    )
    assert status == "skipped_bad_anchor_id"


def test_classify_skipped_bad_anchor_id_no_prefix(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("XXX-011")
    )
    assert status == "skipped_bad_anchor_id"


def test_classify_skipped_bad_anchor_id_empty(helper) -> None:
    status, _ = helper._classify_anchor(_row(""))
    assert status == "skipped_bad_anchor_id"


# ---- Pure unit: _sanitize_anchor_id_for_operationid -----------------


def test_sanitize_anchor_id_lowercases(helper) -> None:
    assert helper._sanitize_anchor_id_for_operationid("ANC-001") == "anc_001"


def test_sanitize_anchor_id_replaces_hyphens(helper) -> None:
    assert helper._sanitize_anchor_id_for_operationid(
        "ANC-USER-ENDPOINT-007"
    ) == "anc_user_endpoint_007"


# ---- _read_a61_rows defensive paths ---------------------------------


def test_read_a61_missing_file(helper, tmp_path) -> None:
    rows, err = helper._read_a61_rows(tmp_path / "no.csv")
    assert rows == []
    assert err is not None
    assert "not found" in err


def test_read_a61_missing_required_column(helper, tmp_path) -> None:
    target = tmp_path / "bad.csv"
    target.write_text(
        # Missing AnchorClass / ElementID / ClaimID / A51Ref / ElementType.
        "AnchorID,Stage\nANC-001,stage6\n",
        encoding="utf-8",
    )
    rows, err = helper._read_a61_rows(target)
    assert rows == []
    assert err is not None
    assert "missing required columns" in err


def test_read_a61_well_formed(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001"), _row("ANC-002")])
    rows, err = helper._read_a61_rows(
        workspace / "analysis/canonical/stage6/A61_anchor_map.csv"
    )
    assert err is None
    assert len(rows) == 2


# ---- build_bundle ---------------------------------------------------


def test_build_bundle_empty_rows(helper) -> None:
    openapi_doc, manifest = helper.build_bundle(
        [], title="Test", version="1.0.0", api_path_str="api.yaml",
    )
    assert openapi_doc["openapi"] == "3.1.0"
    assert openapi_doc["info"] == {"title": "Test", "version": "1.0.0"}
    assert openapi_doc["paths"] == {}
    view_file = manifest["view_files"][0]
    assert view_file["anchor_map"] == []
    assert view_file["unmapped_anchors"] == []
    assert view_file["format"] == "openapi-3.1"


def test_build_bundle_happy_path_emits_two_manifest_entries_per_anchor(
    helper,
) -> None:
    """Conservation invariant: each materialized anchor produces
    PathItem + Operation = 2 anchor_map entries."""
    rows = [_row("ANC-001", element_id="/users")]
    openapi_doc, manifest = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="api.yaml",
    )
    assert "/users" in openapi_doc["paths"]
    assert "get" in openapi_doc["paths"]["/users"]
    op = openapi_doc["paths"]["/users"]["get"]
    assert op["operationId"] == "anc_anc_001_get"
    assert op["tags"] == ["bsa-anchor:C-001"]
    assert "200" in op["responses"]
    am = manifest["view_files"][0]["anchor_map"]
    assert len(am) == 2
    kinds = {e["view_element_kind"] for e in am}
    assert kinds == {"PathItem", "Operation"}


def test_build_bundle_a51_ref_used_when_no_claim_id(helper) -> None:
    """Anchor routed via A51 (no ClaimID) → tag uses A51Ref."""
    rows = [_row(
        "ANC-002", element_id="/orders",
        claim_id="", a51_ref="A51-005",
    )]
    openapi_doc, _ = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="api.yaml",
    )
    op = openapi_doc["paths"]["/orders"]["get"]
    assert op["tags"] == ["bsa-anchor:A51-005"]


def test_build_bundle_skipped_anchors_in_unmapped(helper) -> None:
    rows = [
        _row("ANC-001", element_id="/users"),  # ready
        _row("ANC-002", anchor_class="actor"),  # non_contract
        _row("ANC-003", element_id="users"),  # shape
        _row("ANC-004", element_id="/foo/../bar"),  # traversal
    ]
    openapi_doc, manifest = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="api.yaml",
    )
    # 1 path (only ANC-001 materialized).
    assert len(openapi_doc["paths"]) == 1
    # 3 unmapped reasons; bad_anchor_id NOT included (none in input).
    unmapped = manifest["view_files"][0]["unmapped_anchors"]
    reasons = {u["reason"] for u in unmapped}
    assert reasons == {
        "non_contract_anchor_class",
        "element_id_not_path_shaped",
        "element_id_path_traversal",
    }


def test_build_bundle_duplicate_path_collision(helper) -> None:
    rows = [
        _row("ANC-001", element_id="/users"),
        _row("ANC-002", element_id="/users"),  # duplicate
    ]
    openapi_doc, manifest = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="api.yaml",
    )
    assert len(openapi_doc["paths"]) == 1
    unmapped = manifest["view_files"][0]["unmapped_anchors"]
    assert len(unmapped) == 1
    assert unmapped[0]["reason"] == "duplicate_path_collision"
    assert unmapped[0]["a61_anchor_id"] == "ANC-002"  # second one skipped


def test_build_bundle_bad_anchor_id_silently_dropped(helper) -> None:
    """AnchorIDs that fail the schema pattern are silently dropped from
    BOTH paths AND unmapped_anchors (would otherwise pollute manifest
    with non-conformant entries that fail schema validation)."""
    rows = [
        _row("anc-001", element_id="/users"),  # bad: lowercase
        _row("ANC-002", element_id="/users"),  # ok
    ]
    openapi_doc, manifest = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="api.yaml",
    )
    assert len(openapi_doc["paths"]) == 1
    unmapped = manifest["view_files"][0]["unmapped_anchors"]
    # Bad anchor_id NOT in unmapped (would fail manifest schema).
    assert all(u["a61_anchor_id"] != "anc-001" for u in unmapped)
    assert all(u["a61_anchor_id"] != "" for u in unmapped)


# ---- Manifest schema conformance ------------------------------------


def test_manifest_validates_against_schema(
    helper, jsonschema_module, schema,
) -> None:
    rows = [
        _row("ANC-001", element_id="/users"),
        _row("ANC-002", element_id="/products/{id}"),
        _row("ANC-003", anchor_class="actor"),  # → unmapped
    ]
    _, manifest = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="api.yaml",
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
    """Even with zero materialized anchors the manifest must validate."""
    _, manifest = helper.build_bundle(
        [], title="T", version="1.0.0", api_path_str="api.yaml",
    )
    validator = jsonschema_module.Draft202012Validator(schema)
    errors = list(validator.iter_errors(manifest))
    assert errors == []


def test_schema_pins_sidecar_literal(schema) -> None:
    assert schema["properties"]["sidecar"]["const"] == "openapi-from-context"


def test_schema_pins_format_discriminator(schema) -> None:
    view_file_schema = schema["properties"]["view_files"]["items"]
    assert view_file_schema["properties"]["format"]["const"] == "openapi-3.1"


def test_schema_pins_view_element_kind_enum(schema) -> None:
    item = schema["properties"]["view_files"]["items"]
    am_item = item["properties"]["anchor_map"]["items"]
    assert set(am_item["properties"]["view_element_kind"]["enum"]) == {
        "Operation", "PathItem", "Schema", "Tag",
    }


def test_schema_pins_path_extension_pattern(schema) -> None:
    view_file_schema = schema["properties"]["view_files"]["items"]
    pattern = view_file_schema["properties"]["path"]["pattern"]
    assert re.compile(pattern).search("foo/api.yaml")
    assert re.compile(pattern).search("foo/api.yml")
    assert re.compile(pattern).search("foo/api.json")
    assert not re.compile(pattern).search("foo/api.txt")


# ---- OpenAPI YAML rendering -----------------------------------------


def test_yaml_renders_minimal_valid_shape(helper, yaml_module) -> None:
    rows = [_row("ANC-001", element_id="/users")]
    openapi_doc, _ = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="api.yaml",
    )
    yaml_text = helper._render_yaml(openapi_doc)
    parsed = yaml_module.safe_load(yaml_text)
    assert parsed["openapi"] == "3.1.0"
    assert "info" in parsed
    assert "paths" in parsed
    assert "/users" in parsed["paths"]


def test_yaml_deterministic_ordering(helper) -> None:
    """Same input → byte-identical YAML (sort_keys=False + Py3.7+ dict
    ordering). Required for diffing + idempotency tests."""
    rows = [_row("ANC-001", element_id="/users")]
    doc1, _ = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="api.yaml",
    )
    doc2, _ = helper.build_bundle(
        rows, title="T", version="1.0.0", api_path_str="api.yaml",
    )
    assert helper._render_yaml(doc1) == helper._render_yaml(doc2)


# ---- Path-shape regex hardening -------------------------------------


def test_path_shape_regex_rejects_null_byte(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users\x00/admin")
    )
    assert status == "skipped_shape"


def test_path_shape_regex_rejects_unicode_digits(helper) -> None:
    """`\\d` would match Arabic-Indic digits; our regex uses ASCII
    `[A-Za-z0-9]` so non-ASCII digits are rejected. (Lesson from
    v1.2.16 R4.)"""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/٠١٢")
    )
    assert status == "skipped_shape"


def test_path_shape_regex_accepts_template_braces(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/{id}/items/{item_id}")
    )
    assert status == "ready"


def test_path_shape_regex_accepts_root(helper) -> None:
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/")
    )
    assert status == "ready"


# ---- R1 fix: percent-encoded traversal --------------------------------


def test_path_shape_rejects_url_encoded_traversal_lowercase(helper) -> None:
    """R2 fix: `/foo/%2e%2e/bar` is rejected because `%` is no longer
    in the path-shape character class (regex-level reject). Pre-R1 the
    regex permitted `%`; pre-R2 the recursive-decode defense missed
    triple-encoded variants. Post-R2 the regex is the atomic gate."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/foo/%2e%2e/bar")
    )
    assert status == "skipped_shape"


def test_path_shape_rejects_url_encoded_traversal_uppercase(helper) -> None:
    """Uppercase `%2E%2E` — same regex-level reject."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/foo/%2E%2E/bar")
    )
    assert status == "skipped_shape"


def test_path_shape_rejects_double_encoded_traversal(helper) -> None:
    """`%252e%252e` (double-encoded `..`) — regex-level reject."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/foo/%252e%252e/bar")
    )
    assert status == "skipped_shape"


def test_path_shape_rejects_triple_encoded_traversal(helper) -> None:
    """R2 fix specifically: `/foo/%25252e%25252e/bar` (triple-encoded
    `..`) survived two-pass `urllib.parse.unquote` in R1. Post-R2 the
    regex rejects ANY `%` so encoding depth doesn't matter."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/foo/%25252e%25252e/bar")
    )
    assert status == "skipped_shape"


def test_path_shape_rejects_truncated_percent_escape(helper) -> None:
    """R2 fix: `/users/%` (truncated escape — no hex digits) is
    invalid percent-encoding; regex rejects."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/%")
    )
    assert status == "skipped_shape"


def test_path_shape_rejects_invalid_hex_percent_escape(helper) -> None:
    """R2 fix: `/users/%GG` (non-hex chars after %) is invalid
    percent-encoding; regex rejects."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/%GG")
    )
    assert status == "skipped_shape"


def test_path_shape_rejects_any_percent_in_path(helper) -> None:
    """R2 fix: `%` is not in the path-shape character class period.
    Even legitimate-looking encodings like `%20` (space) or `%2D` (`-`)
    are rejected. Operator must use the decoded character directly."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/foo-%2D/bar")
    )
    assert status == "skipped_shape"


# ---- R1 fix: template syntax validation ------------------------------


def test_path_shape_rejects_unbalanced_open_brace(helper) -> None:
    """R1 fix: `/users/{id` (unbalanced `{`) is not OpenAPI 3.1 valid
    template syntax. Pre-R1 the shape regex accepted it; post-R1 the
    explicit balanced-brace check rejects."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/{id")
    )
    assert status == "skipped_shape"


def test_path_shape_rejects_unbalanced_close_brace(helper) -> None:
    """`/users/id}` — close before open."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/id}")
    )
    assert status == "skipped_shape"


def test_path_shape_rejects_empty_template(helper) -> None:
    """`/users/{}` — empty template name."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/{}")
    )
    assert status == "skipped_shape"


def test_path_shape_rejects_misordered_braces(helper) -> None:
    """`/users/}{` — close before open at top level."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/}{")
    )
    assert status == "skipped_shape"


def test_path_shape_rejects_nested_open_brace(helper) -> None:
    """`/users/{{id}}` — nested `{` invalid in OpenAPI templates."""
    status, _ = helper._classify_anchor(
        _row("ANC-001", element_id="/users/{{id}}")
    )
    assert status == "skipped_shape"


def test_path_shape_accepts_multi_template(helper) -> None:
    """Sanity: multiple distinct templates in same path are valid."""
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
    _write_a61(workspace, [_row("ANC-001", element_id="/users")])
    result = _run_cli(
        "--workspace", str(workspace), "--print-only",
    )
    assert result.returncode == 0
    manifest = json.loads(result.stdout)
    assert manifest["sidecar"] == "openapi-from-context"
    assert len(manifest["view_files"]) == 1
    out_dir = workspace / "analysis/handoff/contracts/openapi"
    # --print-only must NOT write anything.
    assert not (out_dir / "api.yaml").exists()
    assert not (out_dir / "anchor_manifest.json").exists()


def test_cli_writes_both_files(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/users")])
    result = _run_cli(
        "--workspace", str(workspace), "--quiet",
    )
    assert result.returncode == 0
    out_dir = workspace / "analysis/handoff/contracts/openapi"
    assert (out_dir / "api.yaml").is_file()
    assert (out_dir / "anchor_manifest.json").is_file()


def test_cli_input_override(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    custom_input = tmp_path / "custom_a61.csv"
    custom_input.write_text(
        A61_HEADER + ",".join([
            "ANC-CUSTOM-001", "stage6", "interface_endpoint",
            "/custom", "contract", "C-CUSTOM-001", "", "src.md",
            "promoted",
        ]) + "\n",
        encoding="utf-8",
    )
    result = _run_cli(
        "--workspace", str(workspace),
        "--input", str(custom_input),
        "--print-only",
    )
    assert result.returncode == 0
    manifest = json.loads(result.stdout)
    am = manifest["view_files"][0]["anchor_map"]
    assert any(e["a61_anchor_id"] == "ANC-CUSTOM-001" for e in am)


def test_cli_input_override_works_without_initialized_workspace(
    tmp_path,
) -> None:
    """R1 fix: --input bypasses the workspace `analysis/` check so
    operators can run the exporter against a fixture CSV outside any
    BSA workspace. Pre-R1 the workspace guard fired before --input was
    even consulted, making the documented fixture-mode impossible."""
    # No `_make_workspace` call → no `analysis/` directory.
    custom_input = tmp_path / "fixture_a61.csv"
    custom_input.write_text(
        A61_HEADER + ",".join([
            "ANC-FIX-001", "stage6", "interface_endpoint",
            "/fixture-path", "contract", "C-FIX-001", "", "src.md",
            "promoted",
        ]) + "\n",
        encoding="utf-8",
    )
    # Output dir must be explicit too (else default would resolve to
    # tmp_path/analysis/handoff/contracts/openapi which we don't want
    # the exporter to auto-create when the workspace is uninitialized).
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = _run_cli(
        "--workspace", str(tmp_path),  # uninitialized
        "--input", str(custom_input),
        "--output-dir", str(out_dir),
        "--quiet",
    )
    assert result.returncode == 0, (
        f"--input + --output-dir should work without initialized "
        f"workspace; stderr={result.stderr!r}"
    )
    assert (out_dir / "api.yaml").is_file()
    manifest = json.loads(
        (out_dir / "anchor_manifest.json").read_text(encoding="utf-8")
    )
    am = manifest["view_files"][0]["anchor_map"]
    assert any(e["a61_anchor_id"] == "ANC-FIX-001" for e in am)


def test_cli_output_dir_implicit_missing_permissive(tmp_path) -> None:
    """Default output dir (no --output-dir) is permissive — created
    on demand. Mirrors v1.2.19 patcher R1-FIX-1 implicit branch."""
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/users")])
    # Note: output dir doesn't exist yet — implicit path.
    out_dir = workspace / "analysis/handoff/contracts/openapi"
    assert not out_dir.exists()
    result = _run_cli("--workspace", str(workspace), "--quiet")
    assert result.returncode == 0
    assert (out_dir / "api.yaml").is_file()


def test_cli_output_dir_explicit_missing_returns_2(tmp_path) -> None:
    """Explicit --output-dir + non-existent path → exit 2 (operator
    typo defense; mirrors v1.2.19 patcher R1-FIX-1 explicit branch)."""
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/users")])
    bogus = tmp_path / "does_not_exist"
    result = _run_cli(
        "--workspace", str(workspace),
        "--output-dir", str(bogus),
        "--print-only",
    )
    assert result.returncode == 2
    assert "does not exist" in result.stderr


def test_cli_output_dir_outside_workspace_relative_to_fallback(
    tmp_path,
) -> None:
    """--output-dir outside workspace must record absolute path in
    manifest (mirrors v1.2.19 patcher R1-FIX-2)."""
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    workspace = _make_workspace(ws_root)
    _write_a61(workspace, [_row("ANC-001", element_id="/users")])
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
    _write_a61(workspace, [_row("ANC-001", element_id="/users")])
    result = _run_cli(
        "--workspace", str(workspace),
        "--title", "Custom Title",
        "--version", "2.5.7",
        "--quiet",
    )
    assert result.returncode == 0
    api_yaml = (workspace / "analysis/handoff/contracts/openapi/api.yaml")
    parsed = yaml_module.safe_load(api_yaml.read_text(encoding="utf-8"))
    assert parsed["info"] == {"title": "Custom Title", "version": "2.5.7"}


# ---- Safety boundary ------------------------------------------------


def test_script_does_not_import_subprocess() -> None:
    """Structural pin: the exporter is operator-driven and must NOT
    shell out (mirrors v1.2.19 patcher's never-list)."""
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "subprocess" not in src, (
        "generate_openapi.py imported subprocess — verify no "
        "git/commit/push call slipped in. Exporter is operator-driven."
    )


def test_no_tmp_files_left_after_write(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/users")])
    result = _run_cli("--workspace", str(workspace), "--quiet")
    assert result.returncode == 0
    out_dir = workspace / "analysis/handoff/contracts/openapi"
    leftovers = [
        p.name for p in out_dir.iterdir()
        if p.name.startswith(".openapi_exporter_")
    ]
    assert leftovers == [], f"tempfile leftovers: {leftovers}"


def test_exporter_does_not_modify_canonical_state(tmp_path) -> None:
    """Snapshot-diff: only handoff/ subtree gets new files."""
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/users")])
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
    """Two consecutive runs on the same A61 produce byte-identical
    api.yaml. Manifest's `generated_at` differs (timestamp), so only
    YAML is checked here."""
    workspace = _make_workspace(tmp_path)
    _write_a61(workspace, [_row("ANC-001", element_id="/users")])
    _run_cli("--workspace", str(workspace), "--quiet")
    api_yaml = workspace / "analysis/handoff/contracts/openapi/api.yaml"
    first = api_yaml.read_text(encoding="utf-8")
    _run_cli("--workspace", str(workspace), "--quiet")
    second = api_yaml.read_text(encoding="utf-8")
    assert first == second
