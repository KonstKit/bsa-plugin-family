"""Sidecar F5-boundary regression tests (v1.1.12, Section I).

Pins the contract documented in `docs/sidecar_inventory.md`:

  * Sidecar output paths (`analysis/views/c4/...`, `analysis/views/bpmn/...`)
    are NON-canonical — the F5 dispatcher MUST NOT match them. A future
    drift that accidentally extended a canonical regex to cover sidecar
    paths would silently break the sidecar's writer-agnostic discipline
    (only `bsa-orchestrator` could emit, breaking standalone mode).

  * Sidecar `anchor_manifest.json` files at canonical-adjacent paths
    (e.g., `analysis/views/c4/anchor_manifest.json`) are also NOT
    F5-dispatched — they're sidecar-internal contract docs, not
    canonical artifacts.

  * Sidecar test scripts under `skills/<sidecar>/scripts/test_*.py`
    ARE picked up by the global pytest run (defense-in-depth: a
    future change to pytest config that excluded the sidecar dirs
    would silently lose ~80 sidecar tests).

  * Each sidecar SKILL.md exists at its expected path (catches the
    case where a sidecar gets accidentally renamed / moved).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SIDECAR_NAMES = ("c4-plantuml-from-context", "camunda-bpmn-from-context")


# ---- F5 dispatcher must NOT claim sidecar paths -----------------------


@pytest.mark.parametrize(
    "sidecar_path",
    [
        "analysis/views/c4/system_context.puml",
        "analysis/views/c4/container.puml",
        "analysis/views/c4/component.puml",
        "analysis/views/c4/anchor_manifest.json",
        "analysis/views/bpmn/process.bpmn",
        "analysis/views/bpmn/anchor_manifest.json",
        "analysis/views/bpmn/preview.svg",
    ],
)
def test_f5_dispatcher_does_not_claim_sidecar_paths(sidecar_path: str) -> None:
    """The F5 dispatcher MUST return None for every sidecar output path.
    A non-None match would mean the path is treated as canonical and
    routed through the single-writer hook — breaking standalone mode
    for the sidecars."""
    from governance.schemas.write_validator import _dispatch
    dispatch = _dispatch(sidecar_path)
    assert dispatch is None, (
        f"F5 dispatcher unexpectedly claims sidecar path {sidecar_path!r}. "
        f"Sidecar output is non-canonical (per docs/sidecar_inventory.md); "
        f"a match here would break the writer-agnostic discipline."
    )


@pytest.mark.parametrize("sidecar_path", [
    "analysis/views/c4/anchor_manifest.json",
    "analysis/views/bpmn/anchor_manifest.json",
])
def test_validate_canonical_write_passes_through_sidecar_anchor_manifest(sidecar_path: str) -> None:
    """validate_canonical_write returns (True, []) for paths the
    dispatcher doesn't match — sidecar anchor manifests fall in
    that bucket and should pass through untouched."""
    from governance.schemas.write_validator import validate_canonical_write
    # Content can be ANYTHING; the dispatcher gates on path, not content.
    ok, msgs = validate_canonical_write(sidecar_path, '{"anchor_view_elements": []}')
    assert ok, f"sidecar manifest path was unexpectedly validated: {msgs}"
    # No schema matched → empty messages (per the validate_canonical_write contract).
    assert msgs == [], (
        f"sidecar manifest path produced unexpected validation messages: {msgs}"
    )


# ---- Sidecar SKILL.md presence + structure ----------------------------


@pytest.mark.parametrize("sidecar_name", SIDECAR_NAMES)
def test_sidecar_skill_md_exists(sidecar_name: str) -> None:
    skill_path = REPO_ROOT / "skills" / sidecar_name / "SKILL.md"
    assert skill_path.is_file(), f"sidecar SKILL.md missing: {skill_path}"


@pytest.mark.parametrize("sidecar_name", SIDECAR_NAMES)
def test_sidecar_integration_contract_exists(sidecar_name: str) -> None:
    """Both sidecars MUST have a references/integration-contract.md
    documenting the orchestrated-vs-standalone mode rules."""
    contract_path = REPO_ROOT / "skills" / sidecar_name / "references" / "integration-contract.md"
    assert contract_path.is_file(), (
        f"sidecar integration-contract.md missing: {contract_path}. "
        f"This file is the source of truth for the orchestrated-vs-standalone "
        f"mode rules + anchor manifest schema."
    )


@pytest.mark.parametrize("sidecar_name", SIDECAR_NAMES)
def test_sidecar_anchor_manifest_schema_exists(sidecar_name: str) -> None:
    """Both sidecars MUST have a references/anchor_manifest.schema.json
    (formal schema for the anchor manifest emitted in orchestrated mode).
    Catches drift if a maintainer renames or removes the schema file."""
    schema_path = REPO_ROOT / "skills" / sidecar_name / "references" / "anchor_manifest.schema.json"
    assert schema_path.is_file(), (
        f"sidecar anchor_manifest.schema.json missing: {schema_path}. "
        f"This is the formal schema referenced by the integration contract."
    )


# ---- Sidecar test discovery ------------------------------------------


@pytest.mark.parametrize("sidecar_name", SIDECAR_NAMES)
def test_sidecar_has_test_scripts(sidecar_name: str) -> None:
    """Both sidecars MUST have at least one `scripts/test_*.py` file
    under their directory. v1.1.12 pin: catches the case where a
    future pytest config change excludes sidecar dirs from discovery
    (would silently lose ~80 sidecar tests)."""
    scripts_dir = REPO_ROOT / "skills" / sidecar_name / "scripts"
    assert scripts_dir.is_dir(), f"sidecar scripts dir missing: {scripts_dir}"
    test_files = list(scripts_dir.glob("test_*.py"))
    assert test_files, (
        f"sidecar {sidecar_name} has no test_*.py under scripts/. "
        f"Loss of test discovery would silently regress ~80 sidecar tests."
    )


def test_global_pytest_discovers_sidecar_tests() -> None:
    """Smoke check that EVERY sidecar `scripts/test_*.py` file is
    importable + carries a pytest-discoverable entity. Confirms the
    files aren't silently excluded by pytest config / pyproject /
    conftest changes.

    Codex round-1 critical fix: the earlier version shelled out to
    `pytest --collect-only` which is brittle (fails on env without
    writable tmp dir, captures incomplete output, etc.). Now we
    instead verify each sidecar test file is importable via
    importlib + carries a pytest-discoverable test entity — the
    same contract pytest uses to discover tests, but evaluated
    in-process without re-spawning pytest.

    Codex round-2 follow-up: an earlier round-2 draft only spot-checked
    the FIRST test file per sidecar, which made the docstring overclaim
    what the test catches. v1.1.12 final iterates over ALL test files
    (~30 modules total, <1s on import) so a single broken module is
    caught — not just a sidecar-wide regression.

    Pytest's discovery contract (per the docs) recognises any of:
      * a top-level function named `test_*`
      * a class named `Test*` (no `__init__`)
      * a subclass of `unittest.TestCase` (regardless of class
        name — sidecars use this style with names like
        `BackendSelectorTests`, `ValidateC4PlantUMLTests`, etc.)
    All three are equivalent for collection purposes."""
    import importlib.util
    import inspect
    import unittest
    for sidecar_name in SIDECAR_NAMES:
        scripts_dir = REPO_ROOT / "skills" / sidecar_name / "scripts"
        test_files = sorted(scripts_dir.glob("test_*.py"))
        assert test_files, f"sidecar {sidecar_name} has no test_*.py files"
        for test_file in test_files:
            rel = test_file.relative_to(REPO_ROOT)
            spec = importlib.util.spec_from_file_location(
                f"_sidecar_test_smoke_{sidecar_name}_{test_file.stem}",
                test_file,
            )
            assert spec is not None and spec.loader is not None, (
                f"could not build importlib spec for {rel}"
            )
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception as exc:
                # Module-import errors mean pytest also can't collect it.
                pytest.fail(
                    f"sidecar test module {rel} fails to import: "
                    f"{type(exc).__name__}: {exc}"
                )
            # Find any pytest-discoverable entity per the three rules above.
            test_attrs: list[str] = []
            for name, obj in inspect.getmembers(mod):
                if name.startswith("test_") and inspect.isfunction(obj):
                    test_attrs.append(name)
                elif inspect.isclass(obj):
                    # Skip classes imported from other modules (only count
                    # those defined in THIS test file, not e.g.
                    # unittest.TestCase itself which would otherwise leak
                    # in via `from unittest import TestCase`).
                    if getattr(obj, "__module__", None) != mod.__name__:
                        continue
                    if name.startswith("Test"):
                        test_attrs.append(name)
                    elif issubclass(obj, unittest.TestCase):
                        # Sidecar style: unittest.TestCase subclass with a
                        # domain-specific name (e.g. `BackendSelectorTests`).
                        test_attrs.append(name)
            assert test_attrs, (
                f"sidecar test module {rel} carries no pytest-discoverable "
                f"entity (test_* function, Test* class, or "
                f"unittest.TestCase subclass); pytest would silently skip it."
            )


# ---- Validator scripts ----------------------------------------------


def test_c4_validator_script_exists() -> None:
    validator = REPO_ROOT / "skills" / "c4-plantuml-from-context" / "scripts" / "validate_c4_plantuml.py"
    assert validator.is_file(), f"c4 validator script missing: {validator}"


def test_bpmn_validator_scripts_exist() -> None:
    """BPMN sidecar has multiple validators (semantic + governance + run-manifest)."""
    base = REPO_ROOT / "skills" / "camunda-bpmn-from-context" / "scripts"
    for name in ("semantic_validate_bpmn.py", "validate_governance_docs.py", "validate_run_manifest.py"):
        path = base / name
        assert path.is_file(), f"BPMN validator missing: {path}"


# ---- Sidecar inventory doc cross-reference --------------------------


def test_sidecar_inventory_doc_exists_and_references_both() -> None:
    """v1.1.12 added docs/sidecar_inventory.md as the operator-facing
    summary. Pin that it stays present + references both sidecars."""
    inv_path = REPO_ROOT / "docs" / "sidecar_inventory.md"
    assert inv_path.is_file()
    body = inv_path.read_text(encoding="utf-8")
    for sidecar_name in SIDECAR_NAMES:
        assert sidecar_name in body, (
            f"docs/sidecar_inventory.md does not reference {sidecar_name}"
        )
    # Pin the F5-boundary section explicitly — its absence would mean
    # the boundary discipline is documented elsewhere and could drift.
    assert "F5 boundary" in body or "F5-boundary" in body, (
        "docs/sidecar_inventory.md missing F5-boundary section (was the "
        "non-canonical-path discipline section removed?)"
    )
