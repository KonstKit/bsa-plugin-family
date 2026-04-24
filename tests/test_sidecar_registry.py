"""Tests for `config/sidecar_registry.yaml`,
`governance/schemas/sidecar_anchor_manifest.base.schema.json`, and
`scripts/sidecar_registry_lint.py` (v1.1.18, S1+S2).

Pins the contract documented in the registry header + base schema:

  * Committed registry lints clean.
  * Both currently-shipping sidecars (c4-plantuml, camunda-bpmn) are
    listed in the registry with correct metadata.
  * Each registered sidecar's anchor schema includes ALL base-schema
    required fields (manifest_version, generated_at, sidecar,
    canon_policy_version, view_files).
  * Each registered sidecar's f5_path_prefix is OUTSIDE POLICY_GLOBS
    (canon-neutrality).
  * Per-check unit triggers on synthetic broken inputs (C1 missing
    skill dir, C2 missing contract, C3 missing schema, C3 base
    violation, C4 path inside POLICY_GLOBS, C5 duplicate name,
    C7 unknown status).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LINT_PATH = REPO_ROOT / "scripts" / "sidecar_registry_lint.py"
REGISTRY_PATH = REPO_ROOT / "config" / "sidecar_registry.yaml"
BASE_SCHEMA_PATH = (
    REPO_ROOT / "governance" / "schemas" / "sidecar_anchor_manifest.base.schema.json"
)


@pytest.fixture(scope="module")
def lint():
    spec = importlib.util.spec_from_file_location("sidecar_registry_lint", LINT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def yaml_module():
    return pytest.importorskip("yaml")


# ---- Committed-state pins -------------------------------------------


def test_base_schema_exists_and_has_required_fields() -> None:
    """v1.1.18 (S1) added the base schema. Pin its presence + the
    5 required fields the operator-facing contract advertises."""
    assert BASE_SCHEMA_PATH.is_file(), f"missing {BASE_SCHEMA_PATH}"
    schema = json.loads(BASE_SCHEMA_PATH.read_text(encoding="utf-8"))
    required = set(schema.get("required", []))
    expected = {
        "manifest_version", "generated_at", "sidecar",
        "canon_policy_version", "view_files",
    }
    assert expected <= required, (
        f"base schema missing required fields. Expected {expected}, got {required}."
    )


def test_committed_registry_lints_clean(lint) -> None:
    passed, findings = lint.run_lint()
    assert passed, "registry has findings:\n" + "\n".join(
        f"  {f.format()}" for f in findings
    )


def test_committed_registry_lists_all_shipping_sidecars(yaml_module) -> None:
    """Pre-v1.2.11: 2 sidecars (c4 + bpmn). v1.2.11 adds dbml-from-context
    as the third (status=experimental). v1.2.11 half-closes the
    pre-v1.2.11 'DBML / sequence-diagram sidecars' follow-up at
    docs/sidecar_inventory.md — sequence-diagram remains open."""
    doc = yaml_module.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    names = {e["name"] for e in doc["sidecars"]}
    assert "c4-plantuml-from-context" in names
    assert "camunda-bpmn-from-context" in names
    assert "dbml-from-context" in names  # v1.2.11


def test_committed_registry_dbml_sidecar_is_experimental(yaml_module) -> None:
    """v1.2.11 ships DBML with status=experimental (first-release
    convention). A future real-pilot validation pass flips it to
    ``stable`` — pin so a premature stability bump without paired
    pilot data surfaces here."""
    doc = yaml_module.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    dbml = next(
        (e for e in doc["sidecars"] if e["name"] == "dbml-from-context"),
        None,
    )
    assert dbml is not None, "dbml-from-context entry missing from registry"
    assert dbml["status"] == "experimental", (
        f"DBML sidecar status MUST be `experimental` until real-pilot "
        f"pass; got {dbml['status']!r}"
    )
    assert dbml["added_in"] == "v1.2.11"


def test_committed_registry_each_anchor_schema_inherits_base_required(
    yaml_module,
) -> None:
    """Defense in depth: even with the lint passing, double-check
    that each per-sidecar anchor schema's `required` list is a
    superset of the base schema's. If a future maintainer drops a
    required field from a per-sidecar schema, this test catches it
    independent of whether the lint is invoked."""
    base = json.loads(BASE_SCHEMA_PATH.read_text(encoding="utf-8"))
    base_required = set(base.get("required", []))
    doc = yaml_module.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    for entry in doc["sidecars"]:
        schema_path = REPO_ROOT / entry["anchor_manifest_schema"]
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        per_sidecar_required = set(schema.get("required", []))
        missing = base_required - per_sidecar_required
        assert not missing, (
            f"{entry['name']}'s anchor schema {schema_path} misses base-required "
            f"fields {sorted(missing)}"
        )


# ---- Per-check unit coverage (synthetic broken examples) ----------


def _baseline_entry() -> dict:
    return {
        "name": "c4-plantuml-from-context",
        "output_format": "test",
        "f5_path_prefix": "analysis/views/c4/",
        "integration_contract": "skills/c4-plantuml-from-context/references/integration-contract.md",
        "anchor_manifest_schema": "skills/c4-plantuml-from-context/references/anchor_manifest.schema.json",
        "status": "stable",
        "added_in": "v1.0.0",
        "summary": "test",
    }


def test_C1_skill_dir_missing(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["name"] = "bsa-not-a-real-sidecar"
    lint.check_skill_dir_exists(entry, findings)
    assert any(f.code == "C1_SKILL_DIR_MISSING" for f in findings)


def test_C2_integration_contract_missing(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["integration_contract"] = "skills/nope/references/integration-contract.md"
    lint.check_integration_contract_exists(entry, findings)
    assert any(f.code == "C2_INTEGRATION_CONTRACT_MISSING" for f in findings)


_FAKE_BASE = {
    "required": ["manifest_version", "generated_at", "sidecar",
                 "canon_policy_version", "view_files"],
}


def test_C3_anchor_schema_missing(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["anchor_manifest_schema"] = "skills/nope/anchor_manifest.schema.json"
    lint.check_anchor_schema_conforms_to_base(entry, _FAKE_BASE, findings)
    assert any(f.code == "C3_ANCHOR_SCHEMA_MISSING" for f in findings)


def test_C3_anchor_schema_base_violation_required_missing(
    lint, tmp_path,
) -> None:
    """A per-sidecar schema that omits a base-required field MUST
    trigger C3_ANCHOR_SCHEMA_BASE_VIOLATION."""
    findings: list = []
    fake_schema = tmp_path / "fake_anchor.schema.json"
    fake_schema.write_text(json.dumps({
        "type": "object",
        "required": ["sidecar"],  # missing manifest_version, view_files, etc.
        "properties": {
            "view_files": {"type": "array", "minItems": 1, "items": {
                "required": ["path", "anchor_map"],
            }},
        },
    }), encoding="utf-8")
    import unittest.mock as mock
    with mock.patch.object(lint, "REPO_ROOT", tmp_path):
        entry = _baseline_entry()
        entry["anchor_manifest_schema"] = "fake_anchor.schema.json"
        lint.check_anchor_schema_conforms_to_base(entry, _FAKE_BASE, findings)
    assert any(f.code == "C3_ANCHOR_SCHEMA_BASE_VIOLATION" for f in findings)


def test_C3_view_files_not_defined(lint, tmp_path) -> None:
    """v1.1.18 round-2 (Codex HIGH): C3 must catch the case where a
    per-sidecar schema lists view_files in `required` but never
    declares its shape under `properties`. Earlier round-1 fix only
    ran structural checks when properties.view_files existed → a
    schema with `required:[view_files]` + no `properties` would
    silently bypass."""
    findings: list = []
    fake_schema = tmp_path / "fake_anchor.schema.json"
    fake_schema.write_text(json.dumps({
        "required": _FAKE_BASE["required"],
        "properties": {
            "manifest_version": {"type": "string"},
            # NOTE: view_files MISSING from properties entirely
        },
    }), encoding="utf-8")
    import unittest.mock as mock
    with mock.patch.object(lint, "REPO_ROOT", tmp_path):
        entry = _baseline_entry()
        entry["anchor_manifest_schema"] = "fake_anchor.schema.json"
        lint.check_anchor_schema_conforms_to_base(entry, _FAKE_BASE, findings)
    assert any(
        f.code == "C3_ANCHOR_SCHEMA_VIEW_FILES_NOT_DEFINED" for f in findings
    ), f"expected NOT_DEFINED; got {[f.code for f in findings]}"
    # AND the deeper structural checks should NOT also fire (they're
    # short-circuited by the absence — avoid noise in the diagnostic).
    deeper_codes = {
        "C3_ANCHOR_SCHEMA_VIEW_FILES_NOT_ARRAY",
        "C3_ANCHOR_SCHEMA_VIEW_FILES_ALLOWS_EMPTY",
        "C3_ANCHOR_SCHEMA_VIEW_FILES_ITEM_MISSING_REQUIRED",
    }
    assert not any(f.code in deeper_codes for f in findings), (
        f"deeper checks should be skipped when view_files isn't defined; "
        f"got {[f.code for f in findings]}"
    )


def test_C3_view_files_not_array(lint, tmp_path) -> None:
    """v1.1.18 round-1 (Codex HIGH): C3 must catch the case where a
    per-sidecar schema mutates view_files to a non-array type. Earlier
    impl only checked top-level required-key overlap, missing this."""
    findings: list = []
    fake_schema = tmp_path / "fake_anchor.schema.json"
    fake_schema.write_text(json.dumps({
        "required": _FAKE_BASE["required"],
        "properties": {
            "view_files": {"type": "object"},  # WRONG: should be array
        },
    }), encoding="utf-8")
    import unittest.mock as mock
    with mock.patch.object(lint, "REPO_ROOT", tmp_path):
        entry = _baseline_entry()
        entry["anchor_manifest_schema"] = "fake_anchor.schema.json"
        lint.check_anchor_schema_conforms_to_base(entry, _FAKE_BASE, findings)
    assert any(
        f.code == "C3_ANCHOR_SCHEMA_VIEW_FILES_NOT_ARRAY" for f in findings
    ), f"expected NOT_ARRAY; got {[f.code for f in findings]}"


def test_C3_view_files_allows_empty(lint, tmp_path) -> None:
    """v1.1.18 round-1 (Codex HIGH): C3 must catch a per-sidecar
    schema that allows view_files to be empty (no minItems)."""
    findings: list = []
    fake_schema = tmp_path / "fake_anchor.schema.json"
    fake_schema.write_text(json.dumps({
        "required": _FAKE_BASE["required"],
        "properties": {
            "view_files": {
                "type": "array",
                # MISSING minItems → allows empty array
                "items": {"required": ["path", "anchor_map"]},
            },
        },
    }), encoding="utf-8")
    import unittest.mock as mock
    with mock.patch.object(lint, "REPO_ROOT", tmp_path):
        entry = _baseline_entry()
        entry["anchor_manifest_schema"] = "fake_anchor.schema.json"
        lint.check_anchor_schema_conforms_to_base(entry, _FAKE_BASE, findings)
    assert any(
        f.code == "C3_ANCHOR_SCHEMA_VIEW_FILES_ALLOWS_EMPTY" for f in findings
    ), f"expected ALLOWS_EMPTY; got {[f.code for f in findings]}"


def test_C3_view_files_item_missing_required(lint, tmp_path) -> None:
    """v1.1.18 round-1 (Codex HIGH): C3 must catch a per-sidecar
    schema where view_files[] items don't require path + anchor_map."""
    findings: list = []
    fake_schema = tmp_path / "fake_anchor.schema.json"
    fake_schema.write_text(json.dumps({
        "required": _FAKE_BASE["required"],
        "properties": {
            "view_files": {
                "type": "array",
                "minItems": 1,
                "items": {"required": ["path"]},  # MISSING anchor_map
            },
        },
    }), encoding="utf-8")
    import unittest.mock as mock
    with mock.patch.object(lint, "REPO_ROOT", tmp_path):
        entry = _baseline_entry()
        entry["anchor_manifest_schema"] = "fake_anchor.schema.json"
        lint.check_anchor_schema_conforms_to_base(entry, _FAKE_BASE, findings)
    assert any(
        f.code == "C3_ANCHOR_SCHEMA_VIEW_FILES_ITEM_MISSING_REQUIRED"
        for f in findings
    ), f"expected ITEM_MISSING_REQUIRED; got {[f.code for f in findings]}"


def test_C4_f5_path_inside_policy_globs(lint) -> None:
    """A registered sidecar f5_path_prefix that contains a POLICY_GLOBS
    entry inside it would mean canonical state under sidecar paths —
    forbidden."""
    findings: list = []
    entry = _baseline_entry()
    entry["f5_path_prefix"] = "governance/"
    lint.check_f5_path_outside_policy_globs(
        entry,
        policy_globs=["governance/immutable_invariants.md"],
        findings=findings,
    )
    assert any(f.code == "C4_F5_PATH_INSIDE_POLICY_GLOBS" for f in findings)


def test_C4_f5_path_outside_policy_globs_safe(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["f5_path_prefix"] = "analysis/views/c4/"  # safely outside
    lint.check_f5_path_outside_policy_globs(
        entry,
        policy_globs=["governance/immutable_invariants.md"],
        findings=findings,
    )
    assert not findings


def test_C5_duplicate_name(lint) -> None:
    findings: list = []
    entries = [_baseline_entry(), _baseline_entry()]
    lint.check_unique_names(entries, findings)
    assert any(f.code == "C5_DUPLICATE_NAME" for f in findings)


def test_C6_required_field_missing(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    del entry["status"]
    lint.check_required_fields(entry, findings)
    assert any(f.code == "C6_MISSING_FIELD" and "status" in f.message for f in findings)


def test_C7_status_unknown(lint) -> None:
    findings: list = []
    entry = _baseline_entry()
    entry["status"] = "yolo"
    lint.check_status_value(entry, findings)
    assert any(f.code == "C7_STATUS_UNKNOWN" for f in findings)


# ---- POLICY_GLOBS reader contract ----------------------------------


def test_read_policy_globs_returns_nonempty(lint) -> None:
    """Smoke: the reader actually finds POLICY_GLOBS in the canon-hash
    script. If this fails, scripts/compute_canon_hash.py was refactored
    and scripts/sidecar_registry_lint.py needs updating in lockstep."""
    globs = lint._read_policy_globs()
    assert globs
    assert "governance/immutable_invariants.md" in globs
