"""End-to-end sidecar fixture test (v1.2.6 / Sprint 3 / S3).

Closes the open follow-up at ``docs/sidecar_inventory.md`` (pre-v1.2.6
section "Open follow-ups (post-v1.1.x)" line 108):

    End-to-end test fixture that exercises an orchestrated sidecar
    invocation against a project_NNNN/ happy-path fixture. Today the
    sidecars are tested in isolation; a full-pipeline-with-sidecar
    test would catch orchestrator integration drift.

Pre-v1.2.6 sidecar test coverage was schema-shape-only:
  * tests/test_sidecar_anchor_manifest_schema.py — JSON Schema validity
    + per-sidecar minimal happy-path doc + contract-violation negatives.
  * tests/test_sidecar_f5_boundary.py — F5/POLICY_GLOBS boundary check.
  * tests/test_sidecar_registry.py — config/sidecar_registry.yaml lint.

What was missing: a single end-to-end pass that takes a real-shaped
A61 register, a real-shaped sidecar manifest pointing back at it, AND
a real view file (``.puml`` / ``.bpmn``) referencing the manifest's
element IDs, then walks the full chain and asserts every cross-
reference resolves. This module provides that.

Fixture: ``fixtures/golden/project_0004_sidecar_e2e/`` — see its
README.md for the per-surface coverage table.

The test deliberately does NOT invoke any sidecar emitter live (no
Claude in the loop). It walks the static representation of what an
orchestrated pass WOULD have emitted. A live-run fixture is a Sprint
4.5+ deliverable.

Codex review (round 1) drove three structural decisions pinned here:

* **Negative tests share helpers with positives.** The three negative-
  path regressions call the SAME ``_check_*`` / ``_validate_*``
  helpers as the positive tests (just asserting non-empty results).
  This means a future weakening of the positive assertions also
  weakens the negatives — the regressions can't silently green.
* **Relationship coverage** (closed in v1.2.9). C4-PlantUML relationships
  (``Rel``, ``BiRel``, ``RelIndex`` and their directional / Neighbor /
  Back_Neighbor variants) ARE anchorable per the integration contract +
  per the JSON Schema's ``view_element_kind`` enum. v1.2.9 closes the
  v1.2.6-deferred relationship-ID gap by documenting a deterministic
  ``rel_<from>_<connector>_<to>`` derivation in
  ``skills/c4-plantuml-from-context/references/integration-contract.md``
  §"Relationship view_element_id convention". The fixture's ``.puml``
  now ships two ``Rel(...)`` calls (anchored to ANC-REL-001 +
  ANC-REL-002 in A61). The loader's ``_derive_c4_relationship_ids``
  applies the convention at extraction time so the orphan-view-element
  cross-ref check covers relationships too.
* **Path-prefix is asserted explicitly**, not inferred from disk
  existence. Per the orchestrated-mode contract every manifest
  ``view_files[].path`` MUST start with ``analysis/views/<sidecar>/``.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")


# ---- Format checker (custom, RFC-3339 strict) --------------------
#
# `jsonschema.FormatChecker()` supports `date-time` only when an extra
# rfc3339 lib is installed (rfc3339-validator / strict-rfc3339 /
# isoduration). The repo is stdlib-only by convention, so we register
# a hand-rolled `date-time` check.
#
# Codex round-2 found: delegating straight to `datetime.fromisoformat`
# is too permissive — it accepts both naive timestamps
# (``2026-04-25T00:00:00`` with no UTC offset) and the RFC-3339-illegal
# space separator (``2026-04-25 00:00:00+00:00``). RFC 3339 §5.6
# requires the literal ``T`` separator AND a UTC offset (``Z`` or
# ``[+-]HH:MM``). This regex enforces those preconditions BEFORE
# delegating to `fromisoformat` for the actual date/time parse —
# `fromisoformat` is good at calendar-validity checks (rejects
# 2026-02-30, 2026-13-01, etc.) but does not enforce the format
# preconditions we need.

_FORMAT_CHECKER = jsonschema.FormatChecker()

# RFC-3339 §5.6 date-time grammar (strict subset accepted here):
#   full-date "T" full-time
#   full-date  = 4DIGIT "-" 2DIGIT "-" 2DIGIT
#   full-time  = partial-time time-offset
#   partial-time = 2DIGIT ":" 2DIGIT ":" 2DIGIT [ "." 1*DIGIT ]
#   time-offset  = "Z" / ("+" / "-") 2DIGIT ":" 2DIGIT
_RFC3339_DATE_TIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


@_FORMAT_CHECKER.checks("date-time", raises=ValueError)
def _check_date_time_rfc3339(instance: object) -> bool:
    if not isinstance(instance, str):
        return True  # type-check is not this checker's job
    if not _RFC3339_DATE_TIME_RE.match(instance):
        raise ValueError(
            f"value {instance!r} is not RFC-3339 date-time "
            f"(requires ``T`` separator + ``Z`` or ``[+-]HH:MM`` offset)"
        )
    # Calendar-validity check: rejects 2026-02-30, 2026-13-01, etc.
    candidate = instance
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    dt.datetime.fromisoformat(candidate)
    return True


# ---- Fixture geometry ---------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "golden" / "project_0004_sidecar_e2e"
FIXTURE_OUTPUTS = FIXTURE_ROOT / "expected_outputs"
A61_PATH = FIXTURE_OUTPUTS / "canonical" / "core_controls" / "A61_anchor_map.csv"

C4_VIEW_PATH = FIXTURE_OUTPUTS / "views" / "c4" / "system_context.puml"
C4_MANIFEST_PATH = FIXTURE_OUTPUTS / "views" / "c4" / "anchor_manifest.json"
C4_PATH_PREFIX = "analysis/views/c4/"
C4_SCHEMA_PATH = (
    REPO_ROOT
    / "skills"
    / "c4-plantuml-from-context"
    / "references"
    / "anchor_manifest.schema.json"
)

BPMN_VIEW_PATH = FIXTURE_OUTPUTS / "views" / "bpmn" / "ticket_intake.bpmn"
BPMN_MANIFEST_PATH = FIXTURE_OUTPUTS / "views" / "bpmn" / "anchor_manifest.json"
BPMN_PATH_PREFIX = "analysis/views/bpmn/"
BPMN_SCHEMA_PATH = (
    REPO_ROOT
    / "skills"
    / "camunda-bpmn-from-context"
    / "references"
    / "anchor_manifest.schema.json"
)

ANCHOR_ID_RE = re.compile(r"^ANC-[A-Z0-9_-]+$")

# BPMN-spec namespace; ET tag names show up as `{ns}localname`.
BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

# BPMN tag local-names whose `id="..."` attribute MUST appear in the
# manifest's anchor_map. Process containers, definition envelopes, and
# diagram-interchange (DI) elements are excluded — the orchestrator's
# anchor-mapping requirement is per declaring element, not per
# container envelope.
BPMN_DECL_LOCALNAMES = frozenset({
    "startEvent", "endEvent",
    "intermediateCatchEvent", "intermediateThrowEvent", "boundaryEvent",
    "task", "userTask", "serviceTask", "receiveTask", "sendTask",
    "scriptTask", "businessRuleTask", "manualTask",
    "callActivity", "subProcess",
    "exclusiveGateway", "parallelGateway", "inclusiveGateway",
    "eventBasedGateway", "complexGateway",
    "sequenceFlow", "messageFlow",
})


# ---- Loaders -------------------------------------------------------


def _load_a61_anchor_ids() -> set[str]:
    """Load AnchorID column from the fixture's A61 register.

    Pre-v1.2.6 there is no formal ``governance/schemas/a61.schema.json``,
    so this loader hand-rolls header validation + per-row pattern
    enforcement. Returns the SET of anchor IDs.
    """
    assert A61_PATH.is_file(), f"fixture missing A61 register at {A61_PATH}"
    ids: list[str] = []
    with A61_PATH.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames is not None, "A61 register has no header"
        assert "AnchorID" in reader.fieldnames, (
            f"A61 register header missing AnchorID column. "
            f"Found: {reader.fieldnames!r}"
        )
        for row_no, row in enumerate(reader, start=2):
            anchor_id = (row.get("AnchorID") or "").strip()
            assert anchor_id, f"A61:row {row_no}: blank AnchorID"
            assert ANCHOR_ID_RE.match(anchor_id), (
                f"A61:row {row_no}: AnchorID {anchor_id!r} does not match "
                f"{ANCHOR_ID_RE.pattern} (sidecar contract requirement)"
            )
            ids.append(anchor_id)
    return set(ids)


def _load_c4_view_elements() -> set[str]:
    """Extract every C4-PlantUML view-element identifier from the .puml.

    Covers declaration-side macros (Person/System/Container/etc. — the
    first positional arg is the alias) AND relationship macros
    (``Rel``, ``BiRel``, ``RelIndex`` and their directional variants —
    the synthetic ``rel_<from>_<connector>_<to>`` derivation per
    `skills/c4-plantuml-from-context/references/integration-contract.md`
    §"Relationship view_element_id convention" added in v1.2.9).

    Pre-v1.2.9 the loader skipped relationship macros entirely (the
    fixture shipped without ``Rel(...)`` calls because the convention
    was not yet documented — Codex round-1 critical scope-down on
    v1.2.6). v1.2.9 documents the convention + extends the fixture
    + extends this loader together.
    """
    assert C4_VIEW_PATH.is_file(), f"fixture missing C4 view at {C4_VIEW_PATH}"
    text = C4_VIEW_PATH.read_text(encoding="utf-8")
    decl_macros = (
        r"Person|Person_Ext"
        r"|System|System_Ext|SystemDb|SystemDb_Ext|SystemQueue|SystemQueue_Ext"
        r"|System_Boundary|Enterprise_Boundary|Container_Boundary|Boundary"
        r"|Container|Container_Ext|ContainerDb|ContainerDb_Ext"
        r"|Component|Component_Ext|ComponentDb|ComponentDb_Ext"
        r"|Deployment_Node|Deployment_Node_L|Deployment_Node_R|Node|Node_L|Node_R"
    )
    decl_pattern = re.compile(
        rf"\b(?:{decl_macros})\(\s*([A-Za-z_][A-Za-z0-9_]*)"
    )
    ids: set[str] = set(decl_pattern.findall(text))
    ids |= _derive_c4_relationship_ids(text)
    return ids


# Relationship-derivation regexes for v1.2.9 convention.
#
# Three macro families with three connector tokens:
#   Rel{,_U/_D/_L/_R, _Up/_Down/_Left/_Right,
#       _Back, _Back_Neighbor, _Neighbor}     → connector "to"
#   BiRel{,_U/_D/_L/_R, _Up/_Down/_Left/_Right,
#         _Neighbor}                          → connector "bi"
#   RelIndex{,_U/_D/_L/_R, _Up/_Down/_Left/_Right,
#            _Back, _Back_Neighbor, _Neighbor} → connector "idx_to"
#
# The full macro inventory matches what
# `skills/c4-plantuml-from-context/scripts/validate_c4_plantuml.py`
# tracks in STATIC_RELATIONSHIP_MACROS + DYNAMIC_RELATIONSHIP_MACROS
# — spelled-out direction names AND single-letter forms AND
# Neighbor / Back_Neighbor variants. Codex v1.2.9 round-1 critical
# drove the coverage expansion.
#
# Each pattern captures (from_alias, to_alias). Direction qualifiers
# collapse to the same connector per the integration contract —
# direction is a render-layer concern and rides in the manifest's
# optional `notes` field, not in `view_element_kind` (which stays
# as the collapsed base kind per the anchor_manifest schema's enum).
# RelIndex's leading numeric arg is render-order only; the regex
# skips it.
#
# Alternation order within each macro's name is LONGEST-FIRST so the
# longer variants (e.g., `Rel_Back_Neighbor`) match before the
# shorter prefixes (e.g., `Rel_Back`). Without longest-first, the
# engine would emit a partial match + leave the remainder unmatched.

_REL_NAME = (
    r"Rel_Back_Neighbor|Rel_Back|Rel_Neighbor"
    r"|Rel_Up|Rel_Down|Rel_Left|Rel_Right"
    r"|Rel_U|Rel_D|Rel_L|Rel_R"
    r"|Rel"
)
_BIREL_NAME = (
    r"BiRel_Neighbor"
    r"|BiRel_Up|BiRel_Down|BiRel_Left|BiRel_Right"
    r"|BiRel_U|BiRel_D|BiRel_L|BiRel_R"
    r"|BiRel"
)
_RELINDEX_NAME = (
    r"RelIndex_Back_Neighbor|RelIndex_Back|RelIndex_Neighbor"
    r"|RelIndex_Up|RelIndex_Down|RelIndex_Left|RelIndex_Right"
    r"|RelIndex_U|RelIndex_D|RelIndex_L|RelIndex_R"
    r"|RelIndex"
)

_REL_PATTERN = re.compile(
    rf"\b(?:{_REL_NAME})"
    r"\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)"
)
_BIREL_PATTERN = re.compile(
    rf"\b(?:{_BIREL_NAME})"
    r"\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)"
)
_RELINDEX_PATTERN = re.compile(
    rf"\b(?:{_RELINDEX_NAME})"
    r"\(\s*\d+\s*,\s*"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)"
)


def _derive_c4_relationship_ids(text: str) -> set[str]:
    """Apply the v1.2.9 ``rel_<from>_<connector>_<to>`` convention to a
    `.puml` body. Returns the set of derived `view_element_id` values
    (without per-occurrence suffix in the unique-pair case; with
    `__N` suffix when the same ``(from, to, connector)`` triple
    appears more than once).
    """
    ids: set[str] = set()
    seen_pair_counts: dict[str, int] = {}

    def _record(connector: str, src: str, dst: str) -> None:
        base = f"rel_{src}_{connector}_{dst}"
        n = seen_pair_counts.get(base, 0) + 1
        seen_pair_counts[base] = n
        ids.add(base if n == 1 else f"{base}__{n}")

    # Order matters: BiRel must be matched BEFORE Rel so the broader
    # `Rel...` regex doesn't swallow `BiRel(` as a `Rel` form. Same
    # for RelIndex (starts with "Rel" but is structurally different).
    # We do this by preferring more-specific patterns first AND by
    # masking matched spans before running the next pattern.
    masked = text
    for pat, connector in (
        (_BIREL_PATTERN, "bi"),
        (_RELINDEX_PATTERN, "idx_to"),
        (_REL_PATTERN, "to"),
    ):
        for m in pat.finditer(masked):
            _record(connector, m.group(1), m.group(2))
        # Mask matched spans so a later pattern can't double-match
        # the same source text. Replace match characters with spaces
        # to preserve offsets (regex doesn't care about content here,
        # only that the same pattern-region isn't re-matched).
        masked = pat.sub(lambda m: " " * len(m.group(0)), masked)
    return ids


def _load_bpmn_view_elements() -> set[str]:
    """Extract every BPMN element id="..." attribute from the .bpmn.

    Uses :mod:`xml.etree.ElementTree` so namespacing (`bpmn:startEvent`)
    is handled by ET's `{ns}localname` shape, not by pattern guessing.
    Filtered by :data:`BPMN_DECL_LOCALNAMES` so process / definitions
    / diagram-interchange envelopes do NOT leak into the orphan check.
    """
    assert BPMN_VIEW_PATH.is_file(), f"fixture missing BPMN view at {BPMN_VIEW_PATH}"
    tree = ET.parse(BPMN_VIEW_PATH)
    ids: set[str] = set()
    for elem in tree.iter():
        # ET tag = "{ns}localname" or "localname" if no namespace.
        tag = elem.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag not in BPMN_DECL_LOCALNAMES:
            continue
        elem_id = elem.attrib.get("id")
        if elem_id:
            ids.add(elem_id)
    return ids


def _load_manifest(path: Path) -> dict:
    assert path.is_file(), f"fixture missing manifest at {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_schema(path: Path) -> dict:
    assert path.is_file(), f"sidecar schema missing at {path}"
    return json.loads(path.read_text(encoding="utf-8"))


# ---- Shared cross-ref / validation helpers ------------------------
#
# Codex round-1 critical: the negative-path regression tests below
# reuse THESE helpers, not inline reimplementations of the same set
# logic. That way a future weakening of the positive assertions ALSO
# weakens the negatives — they cannot silently pass.


def _unmapped_anchor_ids(manifest: dict, a61_ids: set[str]) -> set[str]:
    """Anchor IDs referenced by the manifest but absent from A61. Empty set = pass."""
    manifest_ids = {
        entry["a61_anchor_id"]
        for view in manifest["view_files"]
        for entry in view["anchor_map"]
    }
    return manifest_ids - a61_ids


def _orphan_view_elements(view_ids: set[str], manifest: dict, key: str) -> set[str]:
    """View-element ids declared in the .puml/.bpmn but absent from manifest."""
    manifest_view_ids = {
        entry[key]
        for view in manifest["view_files"]
        for entry in view["anchor_map"]
    }
    return view_ids - manifest_view_ids


def _schema_errors(manifest: dict, schema: dict) -> list:
    """Run the JSON Schema validator + return all errors as a list.

    Empty list = pass. Format-checker is enabled so ``date-time`` is
    actually enforced (Draft202012Validator does not check formats by
    default — Codex round-1 recommendation #3).
    """
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=_FORMAT_CHECKER,
    )
    return list(validator.iter_errors(manifest))


# ---- Fixture-integrity checks (sanity) ----------------------------


def test_fixture_metadata_present() -> None:
    meta_path = FIXTURE_ROOT / "fixture_metadata.json"
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["fixture_id"] == "project_0004_sidecar_e2e"
    assert meta["authoring_mode"] == "synthetic_representative"
    assert "sidecar-e2e" in meta["scenario_tags"]


def test_fixture_a61_register_loads() -> None:
    ids = _load_a61_anchor_ids()
    # Fixture is hand-designed to ship 12 anchors:
    # - 5 C4 declaration anchors (system + person + boundary + 2 containers)
    # - 2 C4 relationship anchors (v1.2.9: ANC-REL-001 + ANC-REL-002)
    # - 5 BPMN anchors (start event + task + 2 sequence flows + end event)
    assert len(ids) == 12, f"expected 12 anchors in A61; got {len(ids)}"
    assert "ANC-SYS-001" in ids
    assert "ANC-REL-001" in ids
    assert "ANC-REL-002" in ids
    assert "ANC-EVT-001" in ids


def test_fixture_a61_no_duplicate_anchor_ids() -> None:
    rows: list[str] = []
    with A61_PATH.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append((row.get("AnchorID") or "").strip())
    assert len(rows) == len(set(rows)), (
        f"A61 contains duplicate AnchorID(s): "
        f"{[a for a in rows if rows.count(a) > 1]}"
    )


def test_fixture_a61_validates_against_a61_schema() -> None:
    """v1.2.7 closure: the v1.2.6 fixture's A61 register MUST validate
    against the new ``governance/schemas/a61.schema.json`` (added in
    v1.2.7). Pre-v1.2.7 there was no schema — the fixture's A61 row
    shape was hand-rolled. This test pins the schema-fixture
    alignment so any future schema tightening or fixture refresh is
    caught here."""
    from governance.schemas.loader import iter_a61_rows, load_schema
    schema = load_schema("a61")
    validator = jsonschema.Draft202012Validator(schema)
    rows = list(iter_a61_rows(A61_PATH))
    for row_no, row in enumerate(rows, start=1):
        errors = list(validator.iter_errors(row))
        assert not errors, (
            f"A61:row {row_no} ({row.get('AnchorID', '?')}) failed "
            f"v1.2.7 a61.schema.json validation: "
            f"{[e.message for e in errors]}"
        )


# ---- C4 sidecar e2e --------------------------------------------------


def test_c4_manifest_validates_against_schema() -> None:
    schema = _load_schema(C4_SCHEMA_PATH)
    manifest = _load_manifest(C4_MANIFEST_PATH)
    errors = _schema_errors(manifest, schema)
    assert not errors, (
        f"C4 manifest failed schema validation: "
        f"{[e.message for e in errors]}"
    )


def test_c4_manifest_anchor_ids_resolve_to_a61() -> None:
    """ART-VAL-001-07 unmapped-anchor guard."""
    a61_ids = _load_a61_anchor_ids()
    manifest = _load_manifest(C4_MANIFEST_PATH)
    unmapped = _unmapped_anchor_ids(manifest, a61_ids)
    assert not unmapped, (
        f"C4 manifest references {sorted(unmapped)} but A61 has no such "
        f"anchor row(s). ART-VAL-001-07 hard-fail."
    )


def test_c4_view_elements_all_in_manifest() -> None:
    """ART-VAL-001-07 orphan-view-element guard.

    Note: relationship coverage is deferred — see module docstring.
    """
    view_ids = _load_c4_view_elements()
    manifest = _load_manifest(C4_MANIFEST_PATH)
    orphans = _orphan_view_elements(view_ids, manifest, "view_element_id")
    assert not orphans, (
        f"C4 view file declares {sorted(orphans)} but the manifest's "
        f"anchor_map has no entry for them. ART-VAL-001-07 hard-fail "
        f"(orphan view elements)."
    )


def test_c4_manifest_view_path_prefix_and_disk_resolve() -> None:
    """Per orchestrated-mode contract every manifest view path MUST
    start with the per-sidecar workspace prefix; AND the underlying
    file MUST exist (the orchestrator can't validate a path it didn't
    write). Codex round-1 recommendation #1 — assert prefix
    explicitly, not just existence."""
    manifest = _load_manifest(C4_MANIFEST_PATH)
    for view in manifest["view_files"]:
        rel = view["path"]
        assert rel.startswith(C4_PATH_PREFIX), (
            f"C4 manifest view path {rel!r} does not start with "
            f"{C4_PATH_PREFIX!r} (orchestrated-mode contract)"
        )
        # Map "analysis/views/c4/..." → fixture's "views/c4/..." subtree.
        target = FIXTURE_OUTPUTS / rel[len("analysis/"):]
        assert target.is_file(), (
            f"C4 manifest references {rel} but {target} does not exist "
            f"on disk in the fixture."
        )


# ---- BPMN sidecar e2e ------------------------------------------------


def test_bpmn_manifest_validates_against_schema() -> None:
    schema = _load_schema(BPMN_SCHEMA_PATH)
    manifest = _load_manifest(BPMN_MANIFEST_PATH)
    errors = _schema_errors(manifest, schema)
    assert not errors, (
        f"BPMN manifest failed schema validation: "
        f"{[e.message for e in errors]}"
    )


def test_bpmn_manifest_anchor_ids_resolve_to_a61() -> None:
    a61_ids = _load_a61_anchor_ids()
    manifest = _load_manifest(BPMN_MANIFEST_PATH)
    unmapped = _unmapped_anchor_ids(manifest, a61_ids)
    assert not unmapped, (
        f"BPMN manifest references {sorted(unmapped)} but A61 has no "
        f"such anchor row(s). ART-VAL-001-07 hard-fail."
    )


def test_bpmn_view_elements_all_in_manifest() -> None:
    view_ids = _load_bpmn_view_elements()
    manifest = _load_manifest(BPMN_MANIFEST_PATH)
    orphans = _orphan_view_elements(view_ids, manifest, "element_id")
    assert not orphans, (
        f"BPMN view file declares {sorted(orphans)} but the manifest's "
        f"anchor_map has no entry for them. ART-VAL-001-07 hard-fail "
        f"(orphan view elements)."
    )


def test_bpmn_manifest_view_path_prefix_and_disk_resolve() -> None:
    manifest = _load_manifest(BPMN_MANIFEST_PATH)
    for view in manifest["view_files"]:
        rel = view["path"]
        assert rel.startswith(BPMN_PATH_PREFIX), (
            f"BPMN manifest view path {rel!r} does not start with "
            f"{BPMN_PATH_PREFIX!r} (orchestrated-mode contract)"
        )
        target = FIXTURE_OUTPUTS / rel[len("analysis/"):]
        assert target.is_file(), (
            f"BPMN manifest references {rel} but {target} does not exist "
            f"on disk in the fixture."
        )


# ---- Cross-sidecar invariants ----------------------------------------


def test_a61_partitions_cleanly_across_sidecars() -> None:
    """A61 anchors are shared across both sidecars (single source of
    truth) but the fixture is hand-designed so the C4 anchors and BPMN
    anchors don't collide."""
    c4 = _load_manifest(C4_MANIFEST_PATH)
    bpmn = _load_manifest(BPMN_MANIFEST_PATH)
    c4_ids = {
        e["a61_anchor_id"]
        for v in c4["view_files"]
        for e in v["anchor_map"]
    }
    bpmn_ids = {
        e["a61_anchor_id"]
        for v in bpmn["view_files"]
        for e in v["anchor_map"]
    }
    overlap = c4_ids & bpmn_ids
    assert not overlap, (
        f"fixture-integrity: C4 + BPMN manifests share anchor IDs "
        f"{sorted(overlap)}. Hand-design intent was disjoint; refresh "
        f"the fixture or update this test if the partitioning changed."
    )


def test_a61_fully_consumed_by_combined_sidecars() -> None:
    """Every A61 row in the fixture MUST be referenced by at least one
    sidecar manifest. Unconsumed A61 rows would be dead weight."""
    a61 = _load_a61_anchor_ids()
    c4 = _load_manifest(C4_MANIFEST_PATH)
    bpmn = _load_manifest(BPMN_MANIFEST_PATH)
    referenced = {
        e["a61_anchor_id"]
        for m in (c4, bpmn)
        for v in m["view_files"]
        for e in v["anchor_map"]
    }
    unconsumed = a61 - referenced
    assert not unconsumed, (
        f"fixture-integrity: A61 rows {sorted(unconsumed)} are not "
        f"referenced by ANY sidecar manifest. Either remove them from "
        f"A61 or add a manifest entry."
    )


# ---- Negative-path regression pins -----------------------------------
#
# Each negative test calls the SAME helper that the corresponding
# positive test calls, then asserts the helper returns a non-empty
# result. Codex round-1 critical: this prevents a future silent-pass
# regression where weakening the positive helper would also weaken
# the negative.


def test_negative_unmapped_anchor_fails_cross_ref() -> None:
    """Mutate the C4 manifest in-memory to point at an A61 row that
    doesn't exist; the SAME helper used by the positive cross-ref
    test MUST return the synthetic unmapped ID."""
    a61_ids = _load_a61_anchor_ids()
    manifest = deepcopy(_load_manifest(C4_MANIFEST_PATH))
    manifest["view_files"][0]["anchor_map"][0]["a61_anchor_id"] = "ANC-DOES-NOT-EXIST"
    unmapped = _unmapped_anchor_ids(manifest, a61_ids)
    assert unmapped == {"ANC-DOES-NOT-EXIST"}, (
        f"negative path failed to surface the synthetic unmapped "
        f"anchor — got unmapped={unmapped}. Cross-ref helper is too "
        f"loose."
    )


def test_negative_orphan_view_element_fails_cross_ref() -> None:
    """Drop one anchor_map entry from the C4 manifest; the .puml's
    corresponding view element MUST surface as an orphan via the
    SAME helper used by the positive view-element test."""
    view_ids = _load_c4_view_elements()
    manifest = deepcopy(_load_manifest(C4_MANIFEST_PATH))
    dropped = manifest["view_files"][0]["anchor_map"].pop(0)
    dropped_view_id = dropped["view_element_id"]
    orphans = _orphan_view_elements(view_ids, manifest, "view_element_id")
    assert dropped_view_id in orphans, (
        f"negative path failed to surface the synthetic orphan "
        f"({dropped_view_id!r}). Got orphans={orphans}."
    )


def test_negative_wrong_sidecar_value_fails_schema() -> None:
    """Mutate the C4 manifest's `sidecar` field to the BPMN literal;
    the SAME schema-validation helper used by the positive test MUST
    return at least one error (proves schema validation is doing
    real work, not just JSON-parsing)."""
    schema = _load_schema(C4_SCHEMA_PATH)
    manifest = deepcopy(_load_manifest(C4_MANIFEST_PATH))
    manifest["sidecar"] = "camunda-bpmn-from-context"  # wrong sidecar
    errors = _schema_errors(manifest, schema)
    assert errors, (
        "schema accepted wrong sidecar literal — schema check is too "
        "loose."
    )


def test_negative_bad_timestamp_fails_format_check() -> None:
    """Codex round-1 recommendation #3: the JSON Schema's `generated_at`
    field is `format: date-time`, but Draft202012Validator does not
    enforce formats unless a FormatChecker is wired in. The shared
    helper now passes one. This test mutates `generated_at` to a
    non-RFC-3339 string and asserts the helper rejects it; without
    the FormatChecker the helper would silently accept."""
    schema = _load_schema(C4_SCHEMA_PATH)
    manifest = deepcopy(_load_manifest(C4_MANIFEST_PATH))
    manifest["generated_at"] = "not-a-real-timestamp"
    errors = _schema_errors(manifest, schema)
    assert errors, (
        "FormatChecker not wired in — schema accepted "
        "non-RFC-3339 generated_at value."
    )


def test_negative_naive_timestamp_fails_format_check() -> None:
    """Codex round-2 regression: an earlier `_check_date_time_rfc3339`
    delegated straight to `datetime.fromisoformat`, which silently
    accepts timezone-less timestamps like `2026-04-25T00:00:00`. RFC
    3339 §5.6 requires a UTC offset (``Z`` or ``[+-]HH:MM``). The
    strict-regex precheck rejects this; pin so a future revert
    surfaces immediately."""
    schema = _load_schema(C4_SCHEMA_PATH)
    manifest = deepcopy(_load_manifest(C4_MANIFEST_PATH))
    manifest["generated_at"] = "2026-04-25T00:00:00"  # naive — no offset
    errors = _schema_errors(manifest, schema)
    assert errors, (
        "format-checker accepted naive (no-offset) timestamp; "
        "RFC-3339 §5.6 precheck has been weakened."
    )


def test_negative_space_separator_timestamp_fails_format_check() -> None:
    """Codex round-2 regression: `datetime.fromisoformat` ALSO accepts
    the space separator (`2026-04-25 00:00:00+00:00`), which RFC
    3339 §5.6 forbids — only the literal ``T`` is legal. Pin so a
    future revert of the strict-regex precheck surfaces immediately."""
    schema = _load_schema(C4_SCHEMA_PATH)
    manifest = deepcopy(_load_manifest(C4_MANIFEST_PATH))
    manifest["generated_at"] = "2026-04-25 00:00:00+00:00"  # space, not T
    errors = _schema_errors(manifest, schema)
    assert errors, (
        "format-checker accepted space-separator timestamp; "
        "RFC-3339 §5.6 precheck has been weakened (T separator "
        "is mandatory)."
    )


# ---- v1.2.9: relationship-coverage convention pins ----------------
#
# Closes the v1.2.6 round-1 scope-down. The convention is documented
# in skills/c4-plantuml-from-context/references/integration-contract.md
# §"Relationship view_element_id convention". These tests pin
# `_derive_c4_relationship_ids` (the loader-side implementation of
# the convention) against representative shapes from the contract's
# worked-examples table, plus pin the multi-occurrence suffix rule.


def test_derive_rel_basic_to_connector() -> None:
    """Per the contract: ``Rel(agent, web_ui, "Triages")`` →
    ``rel_agent_to_web_ui``. The simplest case."""
    ids = _derive_c4_relationship_ids('Rel(agent, web_ui, "Triages tickets via")')
    assert ids == {"rel_agent_to_web_ui"}


def test_derive_rel_directional_variants_collapse_to_to_connector() -> None:
    """Direction qualifiers (`_U` / `_D` / `_L` / `_R`) record the
    render hint in `view_element_kind`; the bridge-layer
    `view_element_id` collapses to the same `to` connector — pinned
    in the contract's "Direction-agnostic" rationale."""
    text = (
        'Rel_U(client_a, server_b, "queries")\n'
        'Rel_D(client_c, server_d, "queries")\n'
        'Rel_L(client_e, server_f, "queries")\n'
        'Rel_R(client_g, server_h, "queries")\n'
    )
    ids = _derive_c4_relationship_ids(text)
    assert ids == {
        "rel_client_a_to_server_b",
        "rel_client_c_to_server_d",
        "rel_client_e_to_server_f",
        "rel_client_g_to_server_h",
    }


def test_derive_birel_uses_bi_connector() -> None:
    """Per the contract worked-examples table:
    ``BiRel(svc_a, svc_b, "Exchanges")`` → ``rel_svc_a_bi_svc_b``."""
    ids = _derive_c4_relationship_ids(
        'BiRel(svc_a, svc_b, "Exchanges health checks")'
    )
    assert ids == {"rel_svc_a_bi_svc_b"}


def test_derive_birel_directional_variants_collapse_to_bi() -> None:
    """BiRel_Up / _Left / etc. ALSO collapse to `bi`."""
    text = (
        'BiRel_Up(svc_a, svc_b, "x")\n'
        'BiRel_Left(svc_c, svc_d, "y")\n'
    )
    ids = _derive_c4_relationship_ids(text)
    assert ids == {"rel_svc_a_bi_svc_b", "rel_svc_c_bi_svc_d"}


def test_derive_relindex_uses_idx_to_connector_skipping_index() -> None:
    """Per the contract: ``RelIndex(1, agent, ui, "step 1")`` →
    ``rel_agent_idx_to_ui`` — the numeric index is a render-order
    hint and is NOT part of the ID."""
    ids = _derive_c4_relationship_ids('RelIndex(1, agent, ui, "step 1")')
    assert ids == {"rel_agent_idx_to_ui"}


def test_derive_multiple_relationships_same_pair_get_occurrence_suffix() -> None:
    """Per the contract: multiple `(from, to, connector)` triples with
    the same shape suffix `__N` starting at `__2`. First occurrence
    keeps the unsuffixed form."""
    text = (
        'Rel(svc_a, svc_b, "RPC")\n'
        'Rel(svc_a, svc_b, "Webhook")\n'
        'Rel(svc_a, svc_b, "Notification")\n'
    )
    ids = _derive_c4_relationship_ids(text)
    assert ids == {
        "rel_svc_a_to_svc_b",
        "rel_svc_a_to_svc_b__2",
        "rel_svc_a_to_svc_b__3",
    }


def test_derive_distinct_pairs_do_not_collide() -> None:
    """`Rel(a, b)` and `Rel(b, a)` are distinct (different from-to
    direction at the source-text level) → separate IDs, no suffix.
    Pinned because a sloppy implementation that normalised the pair
    (sorted alphabetically) would collide them."""
    text = (
        'Rel(a, b, "forward")\n'
        'Rel(b, a, "backward")\n'
    )
    ids = _derive_c4_relationship_ids(text)
    assert ids == {"rel_a_to_b", "rel_b_to_a"}


def test_derive_birel_does_not_double_match_as_rel() -> None:
    """The Rel pattern starts with ``Rel`` and could naively swallow
    ``BiRel(`` if pattern ordering wasn't deliberate. Pin that the
    masking step prevents this — `BiRel(svc_a, svc_b)` MUST yield
    only `rel_svc_a_bi_svc_b`, never an additional `rel_svc_a_to_svc_b`."""
    text = 'BiRel(svc_a, svc_b, "x")'
    ids = _derive_c4_relationship_ids(text)
    assert ids == {"rel_svc_a_bi_svc_b"}, (
        f"BiRel double-matched as Rel — got: {ids}"
    )


def test_derive_relindex_does_not_double_match_as_rel() -> None:
    """Same masking guard for RelIndex — must NOT also surface as a
    `to` connector. The RelIndex regex is more specific (matches the
    leading numeric index), so the masking step removes it before
    the Rel pattern runs."""
    text = 'RelIndex(2, agent, ui, "step 2")'
    ids = _derive_c4_relationship_ids(text)
    assert ids == {"rel_agent_idx_to_ui"}, (
        f"RelIndex double-matched as Rel — got: {ids}"
    )


def test_fixture_c4_view_now_includes_two_relationship_ids() -> None:
    """v1.2.9 fixture extension: the C4 .puml now has two `Rel(...)`
    calls. The loader MUST extract both via the v1.2.9 convention,
    AND both MUST appear in the manifest's anchor_map (the
    pre-existing test_c4_view_elements_all_in_manifest pins this
    via the orphan-check)."""
    view_ids = _load_c4_view_elements()
    assert "rel_agent_to_web_ui" in view_ids, (
        f"v1.2.9 Rel anchor missing from extracted view ids: {view_ids}"
    )
    assert "rel_web_ui_to_analytics_db" in view_ids, (
        f"v1.2.9 Rel anchor missing from extracted view ids: {view_ids}"
    )
    # Total view ids = 5 declaration + 2 relationship = 7.
    assert len(view_ids) == 7, (
        f"expected 7 C4 view ids (5 decl + 2 rel); got {len(view_ids)}: {view_ids}"
    )


# ---- v1.2.9 round-1 Codex-driven regression tests ----------------
#
# Critical #1 (macro coverage gap): the v1.2.9 round-1 extractor
# missed spelled-out direction names (Rel_Up / Rel_Down / etc.),
# Neighbor variants, Back_Neighbor, and the full RelIndex_* family.
# The round-1 fix expanded `_REL_NAME` / `_BIREL_NAME` /
# `_RELINDEX_NAME` to match the validator's STATIC + DYNAMIC
# inventories (see skills/c4-plantuml-from-context/scripts/
# validate_c4_plantuml.py::STATIC_RELATIONSHIP_MACROS +
# DYNAMIC_RELATIONSHIP_MACROS). These parameterized tests sweep
# the ENTIRE inventory + pin each macro-name → derived-ID
# mapping. A future regression that drops any variant from the
# regex surfaces as a single-parametrize failure.

_ALL_REL_MACROS_TO = [
    # connector "to" (Rel family)
    "Rel", "Rel_U", "Rel_D", "Rel_L", "Rel_R",
    "Rel_Up", "Rel_Down", "Rel_Left", "Rel_Right",
    "Rel_Back", "Rel_Back_Neighbor", "Rel_Neighbor",
]

_ALL_BIREL_MACROS_BI = [
    "BiRel", "BiRel_U", "BiRel_D", "BiRel_L", "BiRel_R",
    "BiRel_Up", "BiRel_Down", "BiRel_Left", "BiRel_Right",
    "BiRel_Neighbor",
]

_ALL_RELINDEX_MACROS_IDX_TO = [
    "RelIndex", "RelIndex_U", "RelIndex_D", "RelIndex_L", "RelIndex_R",
    "RelIndex_Up", "RelIndex_Down", "RelIndex_Left", "RelIndex_Right",
    "RelIndex_Back", "RelIndex_Back_Neighbor", "RelIndex_Neighbor",
]


@pytest.mark.parametrize("macro", _ALL_REL_MACROS_TO)
def test_derive_all_rel_family_variants_use_to_connector(macro: str) -> None:
    """Parameterized sweep over the full Rel family — every variant
    MUST produce the `to` connector. Pins the full macro inventory
    matches `STATIC_RELATIONSHIP_MACROS` + `DYNAMIC_RELATIONSHIP_MACROS`
    in the C4 validator."""
    ids = _derive_c4_relationship_ids(f'{macro}(alpha, beta, "label")')
    assert ids == {"rel_alpha_to_beta"}, (
        f"Rel-family macro {macro!r} produced {ids}; expected "
        f"{{'rel_alpha_to_beta'}} (connector='to')"
    )


@pytest.mark.parametrize("macro", _ALL_BIREL_MACROS_BI)
def test_derive_all_birel_family_variants_use_bi_connector(macro: str) -> None:
    ids = _derive_c4_relationship_ids(f'{macro}(alpha, beta, "label")')
    assert ids == {"rel_alpha_bi_beta"}, (
        f"BiRel-family macro {macro!r} produced {ids}; expected "
        f"{{'rel_alpha_bi_beta'}} (connector='bi')"
    )


@pytest.mark.parametrize("macro", _ALL_RELINDEX_MACROS_IDX_TO)
def test_derive_all_relindex_family_variants_use_idx_to_connector(macro: str) -> None:
    ids = _derive_c4_relationship_ids(f'{macro}(1, alpha, beta, "label")')
    assert ids == {"rel_alpha_idx_to_beta"}, (
        f"RelIndex-family macro {macro!r} produced {ids}; expected "
        f"{{'rel_alpha_idx_to_beta'}} (connector='idx_to')"
    )


# ---- Multiline relationship macros (Rec #2) -----------------------


def test_derive_rel_macro_split_across_lines() -> None:
    """C4-PlantUML allows a relationship macro to span multiple lines
    (common for long tech/label args). Python's ``\\s`` matches
    newlines by default, so the current regex works — pin it so a
    future ``re.compile(..., re.ASCII)`` or bracket-class tweak
    can't silently break multiline parses."""
    text = (
        'Rel(\n'
        '    client_a,\n'
        '    server_b,\n'
        '    "queries",\n'
        '    "HTTPS"\n'
        ')\n'
    )
    ids = _derive_c4_relationship_ids(text)
    assert ids == {"rel_client_a_to_server_b"}, (
        f"multiline Rel macro not extracted: {ids}"
    )


def test_derive_relindex_macro_split_across_lines() -> None:
    """Same multiline guard for RelIndex — the index arg + the two
    aliases can all be on different lines."""
    text = (
        'RelIndex(\n'
        '    1,\n'
        '    agent,\n'
        '    ui,\n'
        '    "step 1"\n'
        ')\n'
    )
    ids = _derive_c4_relationship_ids(text)
    assert ids == {"rel_agent_idx_to_ui"}


# ---- Canon-version pin (Rec #3 + Critical #3) ---------------------


def test_fixture_sidecar_manifests_canon_policy_version_matches_fixture_metadata() -> None:
    """v1.2.9 round-1 Codex Critical #3: the release is canon-bumped to
    1.2.9+hash:4bb99111, but the fixture's sidecar manifests still
    emitted 1.2.5+hash:0eb4093d in the round-1 draft — internally
    inconsistent with the fixture_metadata.json. Round-1 fix refreshed
    both manifests; this test pins the alignment so a future canon
    bump that forgets one of the three files (fixture_metadata +
    c4 manifest + bpmn manifest) surfaces here."""
    meta = json.loads(
        (FIXTURE_ROOT / "fixture_metadata.json").read_text(encoding="utf-8")
    )
    meta_version = meta["canon_policy_version"]
    c4_manifest = _load_manifest(C4_MANIFEST_PATH)
    bpmn_manifest = _load_manifest(BPMN_MANIFEST_PATH)
    assert c4_manifest["canon_policy_version"] == meta_version, (
        f"C4 manifest canon_policy_version {c4_manifest['canon_policy_version']!r} "
        f"!= fixture_metadata {meta_version!r}. Canon-bump drift — the "
        f"fixture's sidecar emission representations got out of sync."
    )
    assert bpmn_manifest["canon_policy_version"] == meta_version, (
        f"BPMN manifest canon_policy_version {bpmn_manifest['canon_policy_version']!r} "
        f"!= fixture_metadata {meta_version!r}."
    )


def test_fixture_metadata_canon_version_matches_plugin_manifest() -> None:
    """Complete the alignment chain: fixture_metadata.canon_policy_version
    MUST match the plugin manifest's canonPolicyVersion (both fields
    are the same `<semver>+hash:<prefix>` shape). Pre-v1.2.9 these
    could drift independently; the three-way pin
    (plugin → fixture_metadata → sidecar manifests) now catches any
    one-step drift."""
    meta = json.loads(
        (FIXTURE_ROOT / "fixture_metadata.json").read_text(encoding="utf-8")
    )
    plugin = json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    canon = plugin["canonPolicyVersion"]
    expected = f"{canon['semver']}+hash:{canon['hash_prefix']}"
    assert meta["canon_policy_version"] == expected, (
        f"fixture_metadata canon_policy_version {meta['canon_policy_version']!r} "
        f"!= plugin.json-derived {expected!r}. Canon-bump drift — a "
        f"canon-bumping release updated plugin.json but not the "
        f"fixture's metadata."
    )
