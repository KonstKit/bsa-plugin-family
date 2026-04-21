"""Schema loader for BSA canonical artifacts (F4, Sprint 5).

Single source of truth for schema discovery. Both validators (offline)
and hooks (write-time) access schemas through this module to avoid
ad-hoc ``json.load`` calls scattered across the repo.

Public API:
    load_schema(name)           -> dict                        (raw JSON Schema)
    list_schemas()              -> list[str]                   (available schema names)
    marker_id_alphabet()        -> set[str]                    (allowed marker_id values)
    audit_pass_sequence(chain)  -> tuple[str, ...]             ("main" | "discovery")
    ready_markers()             -> set[str]                    (stage*.ready alphabet)
    end_state_markers()         -> set[str]                    (handoff.ready, pipeline.complete)
    bridge_markers()            -> set[str]                    (bsa.stage1.entry.enabled)
    decision_markers()          -> set[str]                    (discovery.go/pivot/more_research/no_go)

Stdlib-only at import time. ``jsonschema`` is imported lazily by
callers that actually validate (loader itself never validates).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMAS_DIR = Path(__file__).parent

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


def load_schema(name: str) -> dict[str, Any]:
    """Load a schema by name (no ``.schema.json`` suffix). Cached."""
    if name in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[name]
    schema_path = SCHEMAS_DIR / f"{name}.schema.json"
    if not schema_path.is_file():
        available = ", ".join(list_schemas()) or "<none>"
        raise FileNotFoundError(
            f"Schema not found: {schema_path}. Available: {available}"
        )
    with schema_path.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    _SCHEMA_CACHE[name] = schema
    return schema


def list_schemas() -> list[str]:
    """List available schema names (sorted)."""
    return sorted(
        p.name[: -len(".schema.json")]
        for p in SCHEMAS_DIR.glob("*.schema.json")
    )


def marker_id_alphabet() -> set[str]:
    """Full set of allowed ``marker_id`` values from ``marker.schema.json``.

    This replaces hard-coded sequences in ``validate_marker_chain.py``.
    New markers are added by editing the schema, not by editing multiple
    script-local tuples.
    """
    schema = load_schema("marker")
    return set(schema["properties"]["marker_id"]["enum"])


def audit_pass_sequence(chain: str) -> tuple[str, ...]:
    """Return the audit-pass sequence for ``chain`` (``"main"`` or ``"discovery"``).

    This is the gating sequence used by the chain validator. NOT the
    full alphabet — only the mandatory PASS markers that form the
    promotion chain. Stage-ready markers and end-state markers are in
    the alphabet but not the gating sequence.
    """
    if chain not in ("main", "discovery"):
        raise ValueError(f"chain must be 'main' or 'discovery', got {chain!r}")
    schema = load_schema("marker")
    sequences = schema.get("x-bsa-audit-pass-sequence", {})
    return tuple(sequences.get(chain, []))


def ready_markers() -> set[str]:
    """Stage-ready marker alphabet (stage*.ready + discovery.d*.ready)."""
    schema = load_schema("marker")
    return set(schema.get("x-bsa-ready-markers", {}).get("enum", []))


def end_state_markers() -> set[str]:
    """Terminal markers (``handoff.ready``, ``pipeline.complete``)."""
    schema = load_schema("marker")
    return set(schema.get("x-bsa-end-state-markers", {}).get("enum", []))


def bridge_markers() -> set[str]:
    """Cross-chain bridge markers (``bsa.stage1.entry.enabled``)."""
    schema = load_schema("marker")
    return set(schema.get("x-bsa-bridge-markers", {}).get("enum", []))


def decision_markers() -> set[str]:
    """Discovery-exit decision markers. Exactly one emitted at D-Exit."""
    schema = load_schema("marker")
    return set(schema.get("x-bsa-decision-markers", {}).get("enum", []))
