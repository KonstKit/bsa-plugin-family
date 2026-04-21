"""Schema-conformance tests for ``governance/schemas/marker.schema.json`` (F4, Sprint 5).

Covers four groups:

1. **Schema meta-validity** — the schema itself is a valid JSON Schema
   Draft 2020-12 document.
2. **Positive cases** — real markers from the golden fixtures pass
   validation.
3. **Negative cases** — the ``automated_results``-style camelCase markers
   (``marker``/``emittedAt``/``canonPolicyVersion``) MUST fail. This is a
   regression guard against the Sysco-engagement drift that motivated
   this schema in the first place.
4. **Alphabet sync** — every marker_id listed in
   ``skills/bsa-orchestrator/references/runtime-marker-schema.md`` is in
   the schema enum, and vice versa (prevents doc-vs-code drift).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "governance" / "schemas"
MARKER_SCHEMA_PATH = SCHEMAS_DIR / "marker.schema.json"
MARKER_SCHEMA_DOC = (
    REPO_ROOT / "skills" / "bsa-orchestrator" / "references" / "runtime-marker-schema.md"
)


@pytest.fixture(scope="module")
def marker_schema() -> dict:
    return json.loads(MARKER_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def marker_validator(marker_schema: dict) -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(marker_schema)


# ---- 1. Schema meta-validity -------------------------------------------


def test_marker_schema_is_valid_draft_2020_12(marker_schema: dict) -> None:
    """The schema document itself is a valid JSON Schema 2020-12."""
    jsonschema.Draft202012Validator.check_schema(marker_schema)


def test_loader_exposes_expected_api() -> None:
    """Loader public API returns usable data."""
    from governance.schemas import loader

    alphabet = loader.marker_id_alphabet()
    assert "stage1.excerpts.merged" in alphabet
    assert "discovery.go" in alphabet
    assert "bsa.stage1.entry.enabled" in alphabet

    main_seq = loader.audit_pass_sequence("main")
    assert main_seq[0] == "stage1.excerpts.merged"
    assert main_seq[-1] == "stage8.no_new_claims.pass"
    assert "stage4" not in " ".join(main_seq)  # stage 4 has no audit marker

    discovery_seq = loader.audit_pass_sequence("discovery")
    assert discovery_seq[0] == "discovery.d1.ready"
    assert discovery_seq[-1] == "discovery.go"

    assert "stage1.ready" in loader.ready_markers()
    assert "handoff.ready" in loader.end_state_markers()
    assert "bsa.stage1.entry.enabled" in loader.bridge_markers()
    assert loader.decision_markers() == {
        "discovery.go",
        "discovery.pivot",
        "discovery.more_research",
        "discovery.no_go",
    }


def test_loader_rejects_unknown_chain() -> None:
    from governance.schemas import loader

    with pytest.raises(ValueError, match="chain must be"):
        loader.audit_pass_sequence("invalid")


def test_loader_rejects_unknown_schema_name() -> None:
    from governance.schemas import loader

    with pytest.raises(FileNotFoundError):
        loader.load_schema("does-not-exist")


# ---- 2. Positive cases ------------------------------------------------


@pytest.mark.parametrize(
    "marker",
    [
        {
            "marker_id": "stage1.excerpts.merged",
            "stage": "stage1",
            "verdict": "PASS",
            "timestamp": "2026-04-20T10:00:00Z",
            "canon_policy_version": "1.0.0+hash:abc1234",
            "canon_policy_version_hash": "abc1234",
        },
        {
            "marker_id": "stage1.ready",
            "stage": "stage1",
            "verdict": "READY",
            "timestamp": "2026-04-20T10:00:00Z",
            "canon_policy_version": "1.0.0",
        },
        {
            "marker_id": "discovery.go",
            "stage": "discovery.exit",
            "verdict": "GO",
            "timestamp": "2026-04-20T10:00:00Z",
            "canon_policy_version": "0.95",
        },
        {
            "marker_id": "bsa.stage1.entry.enabled",
            "stage": "discovery.bridge",
            "verdict": "READY",
            "timestamp": "2026-04-20T10:00:00Z",
            "canon_policy_version": "1.0.0-rc1+hash:deadbeef",
            "canon_policy_version_hash": "deadbeef",
        },
        {
            "marker_id": "pipeline.complete",
            "stage": "pipeline",
            "verdict": "PASS",
            "timestamp": "2026-04-20T12:00:00Z",
            "canon_policy_version": "1.0.0",
        },
    ],
    ids=[
        "stage1-audit-pass",
        "stage1-ready",
        "discovery-go",
        "bridge-marker",
        "pipeline-complete",
    ],
)
def test_marker_schema_accepts_valid_marker(
    marker_validator: "jsonschema.Draft202012Validator", marker: dict
) -> None:
    errors = sorted(marker_validator.iter_errors(marker), key=lambda e: e.path)
    assert not errors, f"Valid marker rejected: {[e.message for e in errors]}"


def test_marker_schema_accepts_golden_fixture_markers() -> None:
    """Every marker in fixtures/golden/*/expected_markers/ must validate."""
    from governance.schemas import loader

    schema = loader.load_schema("marker")
    validator = jsonschema.Draft202012Validator(schema)
    fixture_markers: list[Path] = []
    for glob in (
        "fixtures/golden/*/expected_markers/*.json",
        "fixtures/golden/*/expected_markers/**/*.json",
    ):
        fixture_markers.extend(REPO_ROOT.glob(glob))
    # Filter out any manifest/metadata files by content shape:
    # only marker-shaped dicts (with "marker_id" or "marker" field) are in scope.
    assert fixture_markers, "No fixture markers discovered — test setup bug"
    failures: list[tuple[Path, list[str]]] = []
    for path in sorted(set(fixture_markers)):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(doc, dict):
            continue
        if "marker_id" not in doc and "marker" not in doc:
            # Not a marker shape (could be a manifest or summary file).
            continue
        errors = list(validator.iter_errors(doc))
        if errors:
            failures.append((path, [e.message for e in errors]))
    assert not failures, (
        "Golden fixture markers failed schema validation:\n"
        + "\n".join(f"  {p}: {msgs}" for p, msgs in failures)
    )


# ---- 3. Negative cases (regression guards) ----------------------------


def test_marker_schema_rejects_camelcase_legacy(
    marker_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Sysco-engagement drift shape MUST fail.

    This is the actual shape observed in
    /Users/kkitanin/Documents/_-_PROJECTS/Sysco/Order&Deliver/automated_results/
    discovery/runtime/ready/discovery.d1.ready.json — produced by v1.0.0
    of the plugin without write-time enforcement. After F5 lands this
    shape will also be blocked at the hook layer, but the schema is the
    first line of defense.
    """
    legacy = {
        "marker": "discovery.d1.ready",
        "runId": "SYSCO-OD-DISC-20260420-001",
        "mode": "discovery_then_bsa",
        "emittedAt": "2026-04-20T00:00:00Z",
        "emittedBy": "bsa-orchestrator",
        "canonPolicyVersion": "1.0.0",
    }
    errors = list(marker_validator.iter_errors(legacy))
    assert errors, "Legacy camelCase marker must fail validation"
    # Core required fields are missing (snake_case versions).
    err_text = " ".join(e.message for e in errors)
    assert "marker_id" in err_text
    assert "timestamp" in err_text or "'timestamp'" in err_text


def test_marker_schema_rejects_unknown_marker_id(
    marker_validator: "jsonschema.Draft202012Validator",
) -> None:
    marker = {
        "marker_id": "stage9.synthesize.pass",  # does not exist
        "stage": "stage8",
        "verdict": "PASS",
        "timestamp": "2026-04-20T10:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    errors = list(marker_validator.iter_errors(marker))
    assert errors, "Unknown marker_id must be rejected"


def test_marker_schema_rejects_legacy_no_new_facts_name(
    marker_validator: "jsonschema.Draft202012Validator",
) -> None:
    """Sprint 2 rename: ``no_new_facts`` filename is banned from valid output."""
    marker = {
        "marker_id": "discovery.d5.no_new_facts.pass",  # pre-Sprint-2 name
        "stage": "d5",
        "verdict": "PASS",
        "timestamp": "2026-04-20T10:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    errors = list(marker_validator.iter_errors(marker))
    assert errors, "Legacy no_new_facts marker id must be rejected"


def test_marker_schema_rejects_unknown_verdict(
    marker_validator: "jsonschema.Draft202012Validator",
) -> None:
    marker = {
        "marker_id": "stage1.ready",
        "stage": "stage1",
        "verdict": "OK",  # not in enum
        "timestamp": "2026-04-20T10:00:00Z",
        "canon_policy_version": "1.0.0",
    }
    errors = list(marker_validator.iter_errors(marker))
    assert errors


def test_marker_schema_rejects_malformed_canon_version(
    marker_validator: "jsonschema.Draft202012Validator",
) -> None:
    marker = {
        "marker_id": "stage1.ready",
        "stage": "stage1",
        "verdict": "READY",
        "timestamp": "2026-04-20T10:00:00Z",
        "canon_policy_version": "v1 release",  # not semver-ish
    }
    errors = list(marker_validator.iter_errors(marker))
    assert errors


def test_marker_schema_rejects_bad_hash(
    marker_validator: "jsonschema.Draft202012Validator",
) -> None:
    marker = {
        "marker_id": "stage1.ready",
        "stage": "stage1",
        "verdict": "READY",
        "timestamp": "2026-04-20T10:00:00Z",
        "canon_policy_version": "1.0.0",
        "canon_policy_version_hash": "NotHexAtAll!",
    }
    errors = list(marker_validator.iter_errors(marker))
    assert errors


# ---- 4. Alphabet sync with runtime-marker-schema.md -------------------


def _extract_marker_ids_from_doc() -> set[str]:
    """Parse the marker IDs from the runtime-marker-schema.md markdown table."""
    text = MARKER_SCHEMA_DOC.read_text(encoding="utf-8")
    # Bullet lines of shape "- `marker.id.here.json`"
    pattern = re.compile(r"-\s+`([a-z][a-z0-9._]+)\.json`")
    found: set[str] = set()
    for match in pattern.finditer(text):
        mid = match.group(1)
        # Skip legacy aliases explicitly called out as read-only.
        if "no_new_facts" in mid:
            continue
        found.add(mid)
    return found


def test_schema_alphabet_matches_doc() -> None:
    """Every marker documented in runtime-marker-schema.md is in the schema, and vice versa.

    This is the drift gate. If someone adds a marker to the doc but not
    to the schema, this test fails and forces them to update both.
    """
    from governance.schemas import loader

    schema_alphabet = loader.marker_id_alphabet()
    doc_alphabet = _extract_marker_ids_from_doc()

    only_in_doc = doc_alphabet - schema_alphabet
    only_in_schema = schema_alphabet - doc_alphabet

    msg_parts: list[str] = []
    if only_in_doc:
        msg_parts.append(
            f"Documented in runtime-marker-schema.md but missing from schema: {sorted(only_in_doc)}"
        )
    if only_in_schema:
        msg_parts.append(
            f"In schema but not documented in runtime-marker-schema.md: {sorted(only_in_schema)}"
        )
    assert not msg_parts, " | ".join(msg_parts)


def test_audit_pass_sequences_are_subset_of_alphabet() -> None:
    """Gating sequences must be drawn from the marker_id alphabet."""
    from governance.schemas import loader

    alphabet = loader.marker_id_alphabet()
    for chain in ("main", "discovery"):
        seq = loader.audit_pass_sequence(chain)
        missing = [mid for mid in seq if mid not in alphabet]
        assert not missing, f"{chain} sequence has markers not in alphabet: {missing}"
