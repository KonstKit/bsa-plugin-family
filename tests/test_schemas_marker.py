"""Schema-conformance tests for ``governance/schemas/marker.schema.json`` (F4, Sprint 5).

Covers four groups:

1. **Schema meta-validity** — the schema itself is a valid JSON Schema
   Draft 2020-12 document.
2. **Positive cases** — real markers from the golden fixtures pass
   validation.
3. **Negative cases** — the ``automated_results``-style camelCase markers
   (``marker``/``emittedAt``/``canonPolicyVersion``) MUST fail. This is a
   regression guard against the Pilot-1 engagement drift that motivated
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
    """Pilot-1 engagement drift shape MUST fail.

    This is the actual shape observed in
    /<operator-local-path>/<pilot-1>/automated_results/
    discovery/runtime/ready/discovery.d1.ready.json — produced by v1.0.0
    of the plugin without write-time enforcement. After F5 lands this
    shape will also be blocked at the hook layer, but the schema is the
    first line of defense.
    """
    legacy = {
        "marker": "discovery.d1.ready",
        "runId": "PILOT1-OD-DISC-20260420-001",
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


def test_marker_schema_accepts_partial_verdict_with_by_platform(marker_validator) -> None:
    """v1.3.7: phase3.backlog_exported under --platform=all may emit
    verdict=PARTIAL when some platforms succeeded and others failed.
    The PARTIAL marker MUST carry by_platform[] enumerating per-target
    outcomes so the operator knows which exports landed and which to
    retry. Pre-v1.3.7 the verdict enum was {PASS, FAIL, READY, MERGED,
    GO, PIVOT, MORE_RESEARCH, NO_GO} — PARTIAL was rejected and the
    skill had to choose between hiding partial success (verdict=FAIL,
    operator loses the successful exports) or hiding partial failure
    (verdict=PASS, missing platform silently masked)."""
    marker = {
        "marker_id": "phase3.backlog_exported",
        "stage": "phase3.backlog",
        "verdict": "PARTIAL",
        "timestamp": "2026-04-26T16:30:00Z",
        "canon_policy_version": "1.3.3",
        "by_platform": [
            {"platform": "jira", "verdict": "PASS"},
            {"platform": "linear", "verdict": "PASS"},
            {
                "platform": "generic",
                "verdict": "FAIL",
                "reason": "F5 write-validator rejected backlog_export_generic.csv: row STORY-007 missing SourceClaimIDs",
            },
        ],
    }
    errors = sorted(marker_validator.iter_errors(marker), key=lambda e: e.path)
    assert not errors, (
        f"Valid PARTIAL marker rejected: {[e.message for e in errors]}"
    )


def test_marker_schema_rejects_unknown_platform_in_by_platform(marker_validator) -> None:
    """The platform enum in by_platform[] is closed (jira/linear/generic/github).
    A typo'd platform name MUST be rejected so an operator can't accidentally
    invent a target."""
    marker = {
        "marker_id": "phase3.backlog_exported",
        "stage": "phase3.backlog",
        "verdict": "PARTIAL",
        "timestamp": "2026-04-26T16:30:00Z",
        "canon_policy_version": "1.3.3",
        "by_platform": [
            {"platform": "jira", "verdict": "PASS"},
            {"platform": "azure-devops", "verdict": "PASS"},  # not in enum
        ],
    }
    errors = list(marker_validator.iter_errors(marker))
    assert errors, "Unknown platform must be rejected"


def test_marker_schema_rejects_partial_without_by_platform(marker_validator) -> None:
    """v1.3.7 R1: PARTIAL verdict MUST be paired with by_platform[].
    Pre-R1 the schema accepted PARTIAL with no breakdown, defeating the
    point of the verdict (operator wouldn't know what failed)."""
    marker = {
        "marker_id": "phase3.backlog_exported",
        "stage": "phase3.backlog",
        "verdict": "PARTIAL",
        "timestamp": "2026-04-26T16:30:00Z",
        "canon_policy_version": "1.3.3",
        # by_platform deliberately omitted
    }
    errors = list(marker_validator.iter_errors(marker))
    assert errors, "PARTIAL without by_platform must be rejected"


def test_marker_schema_rejects_partial_on_non_backlog_marker(marker_validator) -> None:
    """v1.3.7 R1: PARTIAL is only valid for phase3.backlog_exported (the
    only multi-target marker today). Emitting it on a single-target
    audit-pass marker is a contract violation."""
    marker = {
        "marker_id": "stage1.ready",
        "stage": "stage1",
        "verdict": "PARTIAL",
        "timestamp": "2026-04-26T16:30:00Z",
        "canon_policy_version": "1.3.3",
        "by_platform": [
            {"platform": "jira", "verdict": "PASS"},
            {"platform": "linear", "verdict": "FAIL"},
        ],
    }
    errors = list(marker_validator.iter_errors(marker))
    assert errors, "PARTIAL on non-backlog marker must be rejected"


def test_marker_schema_rejects_by_platform_on_unrelated_marker(marker_validator) -> None:
    """v1.3.7 R1: by_platform is forbidden on any marker except
    phase3.backlog_exported. A stray field on stage1.ready would
    otherwise silently masquerade as a backlog gate."""
    marker = {
        "marker_id": "stage1.ready",
        "stage": "stage1",
        "verdict": "READY",
        "timestamp": "2026-04-26T16:30:00Z",
        "canon_policy_version": "1.3.3",
        "by_platform": [
            {"platform": "jira", "verdict": "PASS"},
        ],
    }
    errors = list(marker_validator.iter_errors(marker))
    assert errors, "by_platform on unrelated marker must be rejected"


def test_marker_schema_rejects_partial_when_all_by_platform_pass(marker_validator) -> None:
    """v1.3.7 R1: PARTIAL means MIXED — at least one PASS and at least
    one FAIL must appear in by_platform. All-PASS with verdict=PARTIAL
    is a contract drift (operator should set verdict=PASS instead)."""
    marker = {
        "marker_id": "phase3.backlog_exported",
        "stage": "phase3.backlog",
        "verdict": "PARTIAL",
        "timestamp": "2026-04-26T16:30:00Z",
        "canon_policy_version": "1.3.3",
        "by_platform": [
            {"platform": "jira", "verdict": "PASS"},
            {"platform": "linear", "verdict": "PASS"},
        ],
    }
    errors = list(marker_validator.iter_errors(marker))
    assert errors, "PARTIAL with all-PASS must be rejected"


def test_marker_schema_rejects_partial_when_all_by_platform_fail(marker_validator) -> None:
    """Mirror of the all-PASS case: all-FAIL with verdict=PARTIAL is a
    contract drift (use FAIL)."""
    marker = {
        "marker_id": "phase3.backlog_exported",
        "stage": "phase3.backlog",
        "verdict": "PARTIAL",
        "timestamp": "2026-04-26T16:30:00Z",
        "canon_policy_version": "1.3.3",
        "by_platform": [
            {"platform": "jira", "verdict": "FAIL", "reason": "auth"},
            {"platform": "linear", "verdict": "FAIL", "reason": "F5 reject"},
        ],
    }
    errors = list(marker_validator.iter_errors(marker))
    assert errors, "PARTIAL with all-FAIL must be rejected"


def test_marker_schema_rejects_by_platform_inner_unknown_verdict(marker_validator) -> None:
    """by_platform[].verdict is restricted to PASS/FAIL — no READY,
    no PARTIAL (PARTIAL only makes sense at the top level, never per-
    platform), no GO, etc."""
    marker = {
        "marker_id": "phase3.backlog_exported",
        "stage": "phase3.backlog",
        "verdict": "PARTIAL",
        "timestamp": "2026-04-26T16:30:00Z",
        "canon_policy_version": "1.3.3",
        "by_platform": [
            {"platform": "jira", "verdict": "PARTIAL"},  # not allowed
        ],
    }
    errors = list(marker_validator.iter_errors(marker))
    assert errors, "by_platform[].verdict=PARTIAL must be rejected"


def test_marker_schema_accepts_readiness_profile_field(marker_validator) -> None:
    """v1.4.0 #3.4: marker may carry an optional `readiness_profile`
    field on Stage-7 / Stage-8 / handoff / pipeline.complete markers
    so retroactive review can reconstruct WHICH profile was active."""
    marker = {
        "marker_id": "stage8.no_new_claims.pass",
        "stage": "stage8",
        "verdict": "PASS",
        "timestamp": "2026-04-28T12:00:00Z",
        "canon_policy_version": "1.4.0",
        "readiness_profile": "compliance",
    }
    errors = sorted(marker_validator.iter_errors(marker), key=lambda e: e.path)
    assert not errors, (
        f"valid readiness_profile rejected: {[e.message for e in errors]}"
    )


@pytest.mark.parametrize("profile", ["default", "compliance", "dev-handoff", "discovery"])
def test_marker_schema_accepts_all_readiness_profile_values(marker_validator, profile) -> None:
    marker = {
        "marker_id": "stage7.skeptical_review.pass",
        "stage": "stage7",
        "verdict": "PASS",
        "timestamp": "2026-04-28T12:00:00Z",
        "canon_policy_version": "1.4.0",
        "readiness_profile": profile,
    }
    errors = list(marker_validator.iter_errors(marker))
    assert not errors


def test_marker_schema_rejects_unknown_readiness_profile(marker_validator) -> None:
    marker = {
        "marker_id": "stage8.no_new_claims.pass",
        "stage": "stage8",
        "verdict": "PASS",
        "timestamp": "2026-04-28T12:00:00Z",
        "canon_policy_version": "1.4.0",
        "readiness_profile": "custom-profile",  # not in enum
    }
    errors = list(marker_validator.iter_errors(marker))
    assert errors, "unknown readiness_profile must be rejected"


def test_audit_pass_sequences_are_subset_of_alphabet() -> None:
    """Gating sequences must be drawn from the marker_id alphabet."""
    from governance.schemas import loader

    alphabet = loader.marker_id_alphabet()
    for chain in ("main", "discovery"):
        seq = loader.audit_pass_sequence(chain)
        missing = [mid for mid in seq if mid not in alphabet]
        assert not missing, f"{chain} sequence has markers not in alphabet: {missing}"
