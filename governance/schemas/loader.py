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
    parse_a48(path)             -> dict                        (markdown → normalized dict)
    iter_csv_rows(path, ...)    -> Iterator[dict]              (generic CSV row reader)
    iter_a50_rows(path)         -> Iterator[dict]              (A50 source register rows)
    iter_a51_rows(path)         -> Iterator[dict]              (A51 issue route register rows)
    iter_a58_rows(path)         -> Iterator[dict]              (A58 evidence excerpts rows)
    iter_a59_rows(path)         -> Iterator[dict]              (A59 claim register rows)
    iter_a60_rows(path)         -> Iterator[dict]              (A60 negative evidence rows)
    iter_a62_rows(path)         -> Iterator[dict]              (A62 NFR register rows, Phase 3)
    iter_a70_rows(path)         -> Iterator[dict]              (A70 story register rows, Phase 3)
    tier_to_claim_strength(t)   -> float                       (T1..T5 → ClaimStrength)

Stdlib-only at import time. ``jsonschema`` is imported lazily by
callers that actually validate (loader itself never validates).

CLI for shell hooks:
    python3 -m governance.schemas.loader a48-field <path> <field>
        Print the value of <field> from the A48 markdown at <path>.
        Exit 0 on success, 2 on parse/missing-field error.
        Used by hooks/pre_bash_promote.sh in lieu of fragile grep.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

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


# ---- A48 parser -------------------------------------------------------

# Bullet-line shapes recognised by the A48 parser. Each pattern captures
# (field_name, value). Both backtick-delimited and bold-delimited field
# names are supported; the value runs to end-of-line.
_A48_BULLET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # - `Field`: value
    re.compile(r"^-\s+`([A-Za-z][A-Za-z0-9_]*)`\s*:\s*(.*?)\s*$"),
    # - **Field**: value
    re.compile(r"^-\s+\*\*([A-Za-z][A-Za-z0-9_]*)\*\*\s*:\s*(.*?)\s*$"),
    # - Field: value (bare, last-resort)
    re.compile(r"^-\s+([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.*?)\s*$"),
)

# Table-row shape: | Field | Value |
_A48_TABLE_ROW = re.compile(r"^\|\s*([A-Za-z][A-Za-z0-9_]*)\s*\|\s*(.*?)\s*\|\s*$")
# Table separator row to skip: |---|---|
_A48_TABLE_SEPARATOR = re.compile(r"^\|[\s|:-]+\|\s*$")
# Table header row to skip: | Field | Value |
_A48_TABLE_HEADER = re.compile(r"^\|\s*Field\s*\|\s*Value\s*\|\s*$", re.IGNORECASE)

# Backtick-stripping for values like `direct` → direct
_BACKTICK_WRAP = re.compile(r"^`(.+?)`$")


def _strip_value_decoration(value: str) -> str:
    """Normalize a single-line A48 value: strip surrounding backticks/whitespace."""
    value = value.strip()
    match = _BACKTICK_WRAP.match(value)
    if match:
        value = match.group(1)
    return value


def parse_a48(path: Path) -> dict[str, str]:
    """Parse an A48 Run Context Card markdown file into a normalized dict.

    Supports three on-disk shapes:
      - Bullet with backticks:    ``- `Field`: value``
      - Bullet with bold:         ``- **Field**: value``
      - Markdown table:           ``| Field | Value |``

    Multi-line values (nested bullets after a label) are joined with
    ``"; "``. Returns an empty dict only if the file has no recognisable
    fields at all (caller must decide whether to treat as error).

    Stdlib-only.
    """
    if not path.is_file():
        raise FileNotFoundError(f"A48 not found: {path}")
    text = path.read_text(encoding="utf-8")
    fields: dict[str, str] = {}

    # First pass: try table rows.
    in_table = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.startswith("|"):
            in_table = False
            continue
        if _A48_TABLE_HEADER.match(line):
            in_table = True
            continue
        if _A48_TABLE_SEPARATOR.match(line):
            continue
        if in_table:
            m = _A48_TABLE_ROW.match(line)
            if m:
                field, value = m.group(1), _strip_value_decoration(m.group(2))
                fields.setdefault(field, value)

    # Second pass: bullet shapes (also captures multi-line nested children).
    pending_field: str | None = None
    pending_children: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        # Top-level bullet?
        if line.startswith("- "):
            # Flush previous nested-children buffer.
            if pending_field and pending_children:
                joined = "; ".join(pending_children)
                # If the field already has a value (single-line on the
                # bullet itself), append children; else use children as
                # the value.
                existing = fields.get(pending_field, "")
                if existing:
                    fields[pending_field] = (
                        f"{existing}; {joined}" if joined else existing
                    )
                else:
                    fields[pending_field] = joined
            pending_field = None
            pending_children = []
            for pattern in _A48_BULLET_PATTERNS:
                m = pattern.match(line)
                if m:
                    field, value = m.group(1), _strip_value_decoration(m.group(2))
                    fields.setdefault(field, value)
                    if not value:
                        # Empty after the colon → expect nested children.
                        pending_field = field
                    break
        elif pending_field and line.lstrip().startswith("- "):
            # Nested child bullet.
            child = line.lstrip()[2:].strip()
            child = _strip_value_decoration(child)
            if child:
                pending_children.append(child)
        elif pending_field and not line.strip():
            # Blank line ends a nested-children block.
            if pending_children:
                joined = "; ".join(pending_children)
                existing = fields.get(pending_field, "")
                if existing:
                    fields[pending_field] = (
                        f"{existing}; {joined}" if joined else existing
                    )
                else:
                    fields[pending_field] = joined
            pending_field = None
            pending_children = []

    # Final flush.
    if pending_field and pending_children:
        joined = "; ".join(pending_children)
        existing = fields.get(pending_field, "")
        if existing:
            fields[pending_field] = f"{existing}; {joined}" if joined else existing
        else:
            fields[pending_field] = joined

    return fields


# ---- CSV row helpers --------------------------------------------------


def iter_csv_rows(path: Path, expected_columns: list[str] | None = None) -> Iterator[dict[str, str]]:
    """Yield each CSV row as a dict (column name → cell value).

    If ``expected_columns`` is provided, raises ValueError when the
    file's actual column set differs (set comparison, order-insensitive).

    Stdlib-only. Uses csv.DictReader which handles quoted commas,
    embedded newlines, and CRLF line endings correctly.
    """
    if not path.is_file():
        raise FileNotFoundError(f"CSV not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if expected_columns is not None:
            actual = set(reader.fieldnames or [])
            expected_set = set(expected_columns)
            if actual != expected_set:
                missing = expected_set - actual
                extra = actual - expected_set
                msg_parts = []
                if missing:
                    msg_parts.append(f"missing columns: {sorted(missing)}")
                if extra:
                    msg_parts.append(f"unexpected columns: {sorted(extra)}")
                raise ValueError(
                    f"CSV {path} column mismatch — {'; '.join(msg_parts)}"
                )
        for row in reader:
            yield row


def iter_a51_rows(path: Path) -> Iterator[dict[str, str]]:
    """Yield A51 issue-route-register rows as validated dicts.

    Convenience wrapper around iter_csv_rows that also asserts the
    canonical A51 column set is present.
    """
    return _iter_canonical_csv("a51", path)


def iter_a50_rows(path: Path) -> Iterator[dict[str, str]]:
    """Yield A50 source-register rows."""
    return _iter_canonical_csv("a50", path)


def iter_a58_rows(path: Path) -> Iterator[dict[str, str]]:
    """Yield A58 evidence-excerpt rows."""
    return _iter_canonical_csv("a58", path)


def iter_a59_rows(path: Path) -> Iterator[dict[str, str]]:
    """Yield A59 claim-register rows."""
    return _iter_canonical_csv("a59", path)


def iter_a60_rows(path: Path) -> Iterator[dict[str, str]]:
    """Yield A60 negative-evidence-register rows."""
    return _iter_canonical_csv("a60", path)


def iter_a62_rows(path: Path) -> Iterator[dict[str, str]]:
    """Yield A62 NFR-register rows (Phase 3, US-S6-01)."""
    return _iter_canonical_csv("a62", path)


def iter_a70_rows(path: Path) -> Iterator[dict[str, str]]:
    """Yield A70 story-register rows (Phase 3, US-S7-01)."""
    return _iter_canonical_csv("a70", path)


def _iter_canonical_csv(schema_name: str, path: Path) -> Iterator[dict[str, str]]:
    """Shared body for the iter_aNN_rows family.

    Reads ``x-bsa-csv-columns-order.order`` from the named schema and
    delegates to ``iter_csv_rows`` for the column-set assertion.
    """
    schema = load_schema(schema_name)
    expected = schema["x-bsa-csv-columns-order"]["order"]
    yield from iter_csv_rows(path, expected_columns=expected)


def tier_to_claim_strength(tier: str) -> float:
    """Look up the canonical ClaimStrength for a ReliabilityTier (T1..T5).

    Returns the float from a50.schema.json's x-bsa-tier-claim-strength
    extension. Raises KeyError on unknown tier.
    """
    mapping = load_schema("a50").get("x-bsa-tier-claim-strength", {})
    if tier not in mapping:
        raise KeyError(
            f"Unknown ReliabilityTier {tier!r}. Known: {sorted(k for k in mapping if not k.startswith('_'))}"
        )
    return float(mapping[tier])


# ---- CLI for shell hooks ----------------------------------------------


def _cli_a48_field(argv: list[str]) -> int:
    """``python3 -m governance.schemas.loader a48-field <path> <field>``"""
    if len(argv) != 2:
        sys.stderr.write("usage: a48-field <path> <field>\n")
        return 2
    path_str, field = argv
    try:
        fields = parse_a48(Path(path_str))
    except FileNotFoundError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    if field not in fields:
        sys.stderr.write(
            f"A48 at {path_str} does not declare field '{field}'. "
            f"Found: {sorted(fields.keys())}\n"
        )
        return 2
    value = fields[field]
    if not value:
        sys.stderr.write(
            f"A48 at {path_str} declares '{field}' but value is empty.\n"
        )
        return 2
    print(value)
    return 0


def _main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write("usage: python3 -m governance.schemas.loader <subcommand> [args...]\n")
        sys.stderr.write("subcommands: a48-field\n")
        return 2
    sub, *rest = argv
    if sub == "a48-field":
        return _cli_a48_field(rest)
    sys.stderr.write(f"unknown subcommand: {sub}\n")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
