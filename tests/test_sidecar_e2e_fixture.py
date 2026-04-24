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
* **Relationship coverage deferred.** C4-PlantUML relationships
  (``Rel``, ``BiRel``, ``RelIndex``) ARE anchorable per the integration
  contract + per the JSON Schema's ``view_element_kind`` enum, but
  the contract has no documented convention for the relationship
  ``view_element_id`` (relationships in C4-PlantUML have no explicit
  IDs). The fixture intentionally ships a Container view with NO
  ``Rel(...)`` calls; the relationship-coverage check waits on a
  separate work item to formalise the relationship-ID convention.
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

    Covers declaration-side macros only: Person/Person_Ext, the System
    family, the Container family, the Component family, boundaries,
    and deployment nodes. Relationship macros (``Rel``, ``BiRel``,
    ``RelIndex``) ARE anchorable per the integration contract but have
    no documented relationship-ID convention yet — the fixture
    therefore ships without ``Rel(...)`` calls. When the convention
    lands, extend this loader + the fixture together.
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
    pattern = re.compile(rf"\b(?:{decl_macros})\(\s*([A-Za-z_][A-Za-z0-9_]*)")
    return set(pattern.findall(text))


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
    # Fixture is hand-designed to ship 10 anchors (5 C4 + 5 BPMN).
    assert len(ids) == 10, f"expected 10 anchors in A61; got {len(ids)}"
    assert "ANC-SYS-001" in ids
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
