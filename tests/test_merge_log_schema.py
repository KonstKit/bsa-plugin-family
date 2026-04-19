"""Unit tests for discovery->main merge_log.schema.json (US-S3-02).

The schema describes one JSONL line of
``analysis/canonical/merge_logs/discovery_to_main_merge_log.jsonl``.
Each line is a single merge event emitted by ``bsa-orchestrator`` when
running the discovery->Stage-1 bridge. Full contract lives in
``skills/bsa-orchestrator/references/discovery_to_main_merge.md``.

These tests verify:

1. The schema is a valid JSON Schema 2020-12 document.
2. Canonical happy-path entries for each ``event`` value validate.
3. Required-field conditionals fire correctly: hard_blocked events
   must carry ``a51_ref`` + ``conflict_detail``; every event type has
   its expected minimum field set.
4. Required-shape violations (missing run_id, wrong event_id pattern,
   bad A51Ref form, unknown event value) are rejected.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = (
    REPO_ROOT
    / "skills"
    / "bsa-orchestrator"
    / "references"
    / "merge_log.schema.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator() -> "jsonschema.Draft202012Validator":
    return jsonschema.Draft202012Validator(_load(SCHEMA_PATH))


def _base_entry(**overrides) -> dict:
    entry = {
        "event_id": "MRG-000001",
        "event": "source_reused",
        "emitted_at": "2026-04-19T17:00:00Z",
        "run_id": "run-2026-04-19-A",
        "canon_policy_version": "0.95",
        "resolution": "informational",
        "discovery_id": "S-001",
        "main_id": "S-001",
    }
    entry.update(overrides)
    return entry


# ---- meta-schema conformance -------------------------------------------


def test_schema_is_valid_2020_12() -> None:
    jsonschema.Draft202012Validator.check_schema(_load(SCHEMA_PATH))


# ---- happy-path per event ---------------------------------------------


def test_source_reused_validates() -> None:
    _validator().validate(_base_entry())


def test_source_new_validates() -> None:
    # source_new does not require discovery_id — drop it and ensure schema accepts.
    entry = _base_entry(event="source_new", main_id="S-042")
    entry.pop("discovery_id")
    _validator().validate(entry)


def test_excerpt_reused_validates() -> None:
    _validator().validate(
        _base_entry(
            event="excerpt_reused",
            discovery_id="E-003",
            main_id="E-003",
        )
    )


def test_claim_lineage_validates() -> None:
    _validator().validate(
        _base_entry(
            event="claim_lineage",
            discovery_id="D-C-005",
            main_id="C-012",
        )
    )


def test_a60_lineage_validates() -> None:
    _validator().validate(
        _base_entry(
            event="a60_lineage",
            discovery_id="D-C-005",
            main_id="C-012",
        )
    )


def test_claim_conflict_validates_with_required_fields() -> None:
    _validator().validate(
        _base_entry(
            event="claim_conflict",
            resolution="hard_blocked",
            discovery_id="D-C-005",
            main_id="C-012",
            a51_ref="A51-042",
            conflict_detail={
                "field": "Statement",
                "discovery_value": "~15%",
                "main_value": "~30%",
            },
        )
    )


def test_excerpt_text_conflict_validates_with_required_fields() -> None:
    _validator().validate(
        _base_entry(
            event="excerpt_text_conflict",
            resolution="hard_blocked",
            discovery_id="E-003",
            main_id="E-003",
            a51_ref="A51-043",
            conflict_detail={
                "locator": "source_001.md:L5-L8",
                "field": "ExcerptText",
                "discovery_value": "Tickets arrive via three channels...",
                "main_value": "Tickets arrive via four channels...",
            },
        )
    )


def test_source_tier_mismatch_validates() -> None:
    _validator().validate(
        _base_entry(
            event="source_tier_mismatch",
            resolution="soft_resolved",
            discovery_id="S-001",
            main_id="S-001",
            conflict_detail={
                "field": "ReliabilityTier",
                "discovery_value": "T3",
                "main_value": "T2",
            },
        )
    )


# ---- negative cases ---------------------------------------------------


def test_bad_event_id_pattern_rejected() -> None:
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(_base_entry(event_id="something-else"))


def test_unknown_event_rejected() -> None:
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(_base_entry(event="not_a_real_event"))


def test_missing_run_id_rejected() -> None:
    entry = _base_entry()
    entry.pop("run_id")
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(entry)


def test_bad_a51_ref_pattern_rejected() -> None:
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(
            _base_entry(
                event="claim_conflict",
                resolution="hard_blocked",
                discovery_id="D-C-005",
                main_id="C-012",
                a51_ref="not-an-a51-ref",
                conflict_detail={
                    "field": "Statement",
                    "discovery_value": "a",
                    "main_value": "b",
                },
            )
        )


def test_hard_blocked_requires_a51_ref() -> None:
    """A hard_blocked resolution without an a51_ref must be rejected."""
    entry = _base_entry(
        event="claim_conflict",
        resolution="hard_blocked",
        discovery_id="D-C-005",
        main_id="C-012",
        conflict_detail={
            "field": "Statement",
            "discovery_value": "a",
            "main_value": "b",
        },
    )
    # No a51_ref.
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(entry)


def test_hard_blocked_requires_conflict_detail() -> None:
    entry = _base_entry(
        event="claim_conflict",
        resolution="hard_blocked",
        discovery_id="D-C-005",
        main_id="C-012",
        a51_ref="A51-042",
    )
    # No conflict_detail.
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(entry)


def test_claim_lineage_without_discovery_id_rejected() -> None:
    entry = _base_entry(event="claim_lineage", main_id="C-012")
    entry.pop("discovery_id")
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(entry)


def test_source_new_without_main_id_rejected() -> None:
    entry = _base_entry(event="source_new")
    entry.pop("discovery_id")
    entry.pop("main_id")
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(entry)


def test_unknown_top_level_field_rejected() -> None:
    entry = _base_entry(extra_field="oops")
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(entry)


def test_invalid_resolution_rejected() -> None:
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(_base_entry(resolution="maybe"))


def test_canon_policy_version_accepts_hash_suffix() -> None:
    """Forward-compat with Sprint-3 US-S3-04 semver+hash form."""
    _validator().validate(
        _base_entry(canon_policy_version="1.0.0+hash:abc123def456")
    )


def test_canon_policy_version_rejects_garbage() -> None:
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(_base_entry(canon_policy_version="not a version"))


# ---- integration: sample .jsonl round-trip -----------------------------


def test_sample_merge_log_jsonl_validates_line_by_line(tmp_path: Path) -> None:
    """Write a synthetic multi-event .jsonl and validate every line.

    Exercises the per-line model that downstream tooling will follow.
    """
    validator = _validator()
    events = [
        _base_entry(event_id="MRG-000001", event="source_reused"),
        _base_entry(
            event_id="MRG-000002",
            event="excerpt_reused",
            discovery_id="E-001",
            main_id="E-001",
        ),
        _base_entry(
            event_id="MRG-000003",
            event="claim_lineage",
            discovery_id="D-C-001",
            main_id="C-001",
        ),
        _base_entry(
            event_id="MRG-000004",
            event="source_tier_mismatch",
            resolution="soft_resolved",
            conflict_detail={
                "field": "ReliabilityTier",
                "discovery_value": "T3",
                "main_value": "T2",
            },
        ),
        _base_entry(
            event_id="MRG-000005",
            event="claim_conflict",
            resolution="hard_blocked",
            discovery_id="D-C-002",
            main_id="C-002",
            a51_ref="A51-007",
            conflict_detail={
                "field": "Statement",
                "discovery_value": "X",
                "main_value": "Y",
            },
        ),
    ]
    log_path = tmp_path / "discovery_to_main_merge_log.jsonl"
    with log_path.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
    with log_path.open("r", encoding="utf-8") as fh:
        for line_num, line in enumerate(fh, start=1):
            data = json.loads(line)
            validator.validate(data)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
