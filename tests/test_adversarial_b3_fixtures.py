"""B3 adversarial-fixture regression tests (v1.1.5).

Three new adversarial fixtures land in v1.1.5 (B3):

  * `adversarial_multi_way_contradiction_001` — N-way (3-source) same-tier
    contradiction captured as ONE atomic A51 row (not pairwise expansion).
  * `adversarial_tier_delta_auto_resolution_001` — cross-tier (T1 vs T4)
    auto-resolution: higher tier wins silently, lower tier marked
    superseded, NO A51 raised, audit trail in A60.
  * `adversarial_block_on_contradiction_001` — spec-as-fixture for the
    proposed --strict-on-hard-a51 opt-in failure mode (orchestrator
    behavior is NOT implemented yet; the test asserts the canonical
    state is schema-conforming today and pins the proposed BLOCKED
    message shape via mock).

Each test class focuses on the headline behavior unique to its fixture
(the broader Phase-3 propagation chain is covered by
test_integration_phase3_contradiction.py).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "fixtures" / "golden"


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _load_audit_expectations(fixture: Path) -> dict:
    return json.loads((fixture / "audit_expectations.json").read_text(encoding="utf-8"))


def _load_metadata(fixture: Path) -> dict:
    return json.loads((fixture / "fixture_metadata.json").read_text(encoding="utf-8"))


# ---- Multi-way contradiction (N=3) -----------------------------------


class TestMultiWayContradiction:
    FIXTURE = FIXTURES / "adversarial_multi_way_contradiction_001"

    def test_fixture_directory_exists(self) -> None:
        assert self.FIXTURE.is_dir(), "fixture dir missing"

    def test_three_input_files_present(self) -> None:
        inputs = sorted((self.FIXTURE / "inputs").glob("source_*.md"))
        assert len(inputs) == 3, f"expected 3 inputs; found {[p.name for p in inputs]}"

    def test_a50_has_three_sources_all_at_t2(self) -> None:
        _, rows = _read_csv(self.FIXTURE / "expected_outputs/canonical/core_controls/A50_source_register.csv")
        assert len(rows) == 3
        tiers = {row["ReliabilityTier"] for row in rows}
        assert tiers == {"T2"}, f"expected all T2 (same-tier multi-way); got {tiers}"

    def test_a59_has_three_contradicted_claims_all_zero_strength(self) -> None:
        _, rows = _read_csv(self.FIXTURE / "expected_outputs/canonical/core_controls/A59_claim_register.csv")
        assert len(rows) == 3
        assert all(row["ClaimStrength"] == "0.0" for row in rows), (
            "every contradicted claim must carry ClaimStrength=0.0 (symmetric neutralization)"
        )
        assert all(row["A51Ref"] == "A51-CONFL-002" for row in rows), (
            "every contradicted claim must point at the SAME atomic A51 ref"
        )

    def test_a51_has_exactly_one_atomic_multi_way_row(self) -> None:
        _, rows = _read_csv(self.FIXTURE / "expected_outputs/canonical/core_controls/A51_issue_route_register.csv")
        assert len(rows) == 1, f"expected EXACTLY ONE A51 row (atomic); found {len(rows)}"
        row = rows[0]
        assert row["A51Ref"] == "A51-CONFL-002"
        assert row["IssueType"] == "contradiction"
        # Severity=critical because customer-contract is among contradicted sources
        assert row["Severity"] == "critical", (
            "Severity must be 'critical' when customer-facing contract is contradicted"
        )
        assert row["BlockingStatus"] == "hard"
        # Multi-way captured atomically: 3 sources + 3 claims joined by ;
        related_sources = row["RelatedSourceID"].split(";")
        related_claims = row["RelatedClaimID"].split(";")
        assert len(related_sources) == 3
        assert len(related_claims) == 3

    def test_a51_does_not_contain_pairwise_expansion(self) -> None:
        """Negative invariant: NO A51 rows of shape A51-CONFL-002a/b/c
        (pairwise expansion of the multi-way contradiction is forbidden)."""
        _, rows = _read_csv(self.FIXTURE / "expected_outputs/canonical/core_controls/A51_issue_route_register.csv")
        refs = {row["A51Ref"] for row in rows}
        # Only the atomic ref should exist; no pairwise variants
        assert refs == {"A51-CONFL-002"}

    def test_a60_has_six_cross_links_for_three_way(self) -> None:
        """N=3 contradicted claims → N×(N-1) = 6 cross-link rows."""
        _, rows = _read_csv(self.FIXTURE / "expected_outputs/canonical/core_controls/A60_negative_evidence_register.csv")
        assert len(rows) == 6
        assert all(row["A51Ref"] == "A51-CONFL-002" for row in rows)

    def test_audit_expectations_consistent_with_data(self) -> None:
        exp = _load_audit_expectations(self.FIXTURE)
        assert exp["expected_a51_count"] == 1
        assert exp["expected_a51_severity"] == "critical"
        assert exp["expected_a51_related_claim_ids_count"] == 3


# ---- Tier-delta auto-resolution --------------------------------------


class TestTierDeltaAutoResolution:
    FIXTURE = FIXTURES / "adversarial_tier_delta_auto_resolution_001"

    def test_fixture_directory_exists(self) -> None:
        assert self.FIXTURE.is_dir()

    def test_a50_has_two_sources_at_distant_tiers(self) -> None:
        _, rows = _read_csv(self.FIXTURE / "expected_outputs/canonical/core_controls/A50_source_register.csv")
        assert len(rows) == 2
        tiers = sorted(row["ReliabilityTier"] for row in rows)
        # T1 vs T4 → tier-delta = 3, well above the auto-resolution threshold (≥ 2)
        assert tiers == ["T1", "T4"], f"expected T1+T4 (tier-delta 3); got {tiers}"

    def test_a59_winner_has_high_strength_loser_has_zero(self) -> None:
        _, rows = _read_csv(self.FIXTURE / "expected_outputs/canonical/core_controls/A59_claim_register.csv")
        winner = next(r for r in rows if r["ClaimID"] == "C-001")
        loser = next(r for r in rows if r["ClaimID"] == "C-002")
        # Winner inherits T1 tier weight; loser is superseded → 0.0
        assert float(winner["ClaimStrength"]) > 0.5
        assert loser["ClaimStrength"] == "0.0"

    def test_a59_loser_notes_records_supersededby(self) -> None:
        """SupersededBy is encoded in A59 Notes until promoted to a typed
        column (v1.2 candidate). The convention is 'SupersededBy=<ref>'
        within the Notes free-text."""
        _, rows = _read_csv(self.FIXTURE / "expected_outputs/canonical/core_controls/A59_claim_register.csv")
        loser = next(r for r in rows if r["ClaimID"] == "C-002")
        assert "SupersededBy=C-001" in loser["Notes"], (
            "A59[C-002].Notes must document SupersededBy=C-001 for audit trail"
        )

    def test_a59_neither_claim_carries_a51_ref(self) -> None:
        """Auto-resolved cases produce NO A51 — both claims have empty A51Ref."""
        _, rows = _read_csv(self.FIXTURE / "expected_outputs/canonical/core_controls/A59_claim_register.csv")
        for row in rows:
            assert row["A51Ref"] == "", (
                f"auto-resolved case must have empty A51Ref; row {row['ClaimID']} has {row['A51Ref']!r}"
            )

    def test_a51_register_is_empty(self) -> None:
        """The A51 register has the header row only — no contradiction
        rows (auto-resolution by design)."""
        _, rows = _read_csv(self.FIXTURE / "expected_outputs/canonical/core_controls/A51_issue_route_register.csv")
        assert rows == [], f"A51 must be empty for auto-resolved tier-delta; found {len(rows)} rows"

    def test_a60_has_one_audit_trail_row(self) -> None:
        _, rows = _read_csv(self.FIXTURE / "expected_outputs/canonical/core_controls/A60_negative_evidence_register.csv")
        assert len(rows) == 1
        row = rows[0]
        assert row["RelatedClaimID"] == "C-002"
        assert row["A51Ref"] == "", (
            "A60 audit trail row must NOT cross-link to an A51 (none exists for auto-resolved case)"
        )

    def test_audit_expectations_pin_zero_a51(self) -> None:
        exp = _load_audit_expectations(self.FIXTURE)
        assert exp["expected_a51_count"] == 0
        assert exp["expected_a51_routes"] == []


# ---- Block-on-contradiction (spec-only) -------------------------------


class TestBlockOnContradictionSpec:
    FIXTURE = FIXTURES / "adversarial_block_on_contradiction_001"

    def test_fixture_directory_exists(self) -> None:
        assert self.FIXTURE.is_dir()

    def test_metadata_marks_spec_only(self) -> None:
        meta = _load_metadata(self.FIXTURE)
        assert meta.get("spec_only") is True, (
            "this fixture documents an unimplemented contract; spec_only flag REQUIRED"
        )

    def test_canonical_state_has_one_hard_blocking_open_a51(self) -> None:
        """Even though the strict-mode behavior is unimplemented, the
        fixture's canonical state IS schema-conforming today: exactly
        one A51 row with BlockingStatus=hard + ResolutionStatus=open
        that the proposed pre-flight check would catch."""
        _, rows = _read_csv(self.FIXTURE / "expected_outputs/canonical/core_controls/A51_issue_route_register.csv")
        blocking_open = [
            r for r in rows
            if r["BlockingStatus"] == "hard" and r["ResolutionStatus"] == "open"
        ]
        assert len(blocking_open) == 1, (
            f"expected EXACTLY ONE hard-blocking open A51; found {len(blocking_open)}"
        )
        row = blocking_open[0]
        assert row["A51Ref"] == "A51-CONFL-003"

    def test_proposed_strict_mode_preflight_blocks_on_open_hard_a51(self) -> None:
        """Mocks the proposed --strict-on-hard-a51 pre-flight check.
        Asserts the BLOCKED-message shape so that when the real
        implementation lands (v1.2), this regression baseline already
        exists. Implementation: a future patch adds
        scripts/promote_strict_preflight.py that this test will switch
        to invoking directly."""
        a51_path = self.FIXTURE / "expected_outputs/canonical/core_controls/A51_issue_route_register.csv"
        _, rows = _read_csv(a51_path)
        # Proposed pre-flight logic (mocked here, lives in the
        # orchestrator at v1.2): scan for hard+open rows, emit BLOCKED
        # message with each ref.
        blockers = [
            r for r in rows
            if r["BlockingStatus"] == "hard" and r["ResolutionStatus"] == "open"
        ]
        assert blockers, "fixture canonical state must trigger the pre-flight check"
        # BLOCKED message shape (proposed):
        message_keywords = ["BLOCKED", blockers[0]["A51Ref"], "BlockingStatus=hard", "ResolutionStatus=open"]
        proposed_message = (
            f"BLOCKED: /bsa-promote --strict-on-hard-a51 refused canonical write — "
            f"{len(blockers)} unresolved hard-blocking A51 row(s):\n"
        )
        for r in blockers:
            proposed_message += (
                f"  {r['A51Ref']} ({r['IssueType']}, Severity={r['Severity']}, "
                f"BlockingStatus=hard, ResolutionStatus=open) — NextAction: "
                f"{r['NextAction'][:80]}...\n"
            )
        for kw in message_keywords:
            assert kw in proposed_message, f"BLOCKED message missing keyword {kw}"

    def test_audit_expectations_capture_proposed_strict_verdict(self) -> None:
        exp = _load_audit_expectations(self.FIXTURE)
        assert exp.get("spec_only") is True
        assert exp["expected_strict_mode_verdict"]["exit_code"] == 1
        assert "A51-CONFL-003" in exp["expected_strict_mode_verdict"]["blocked_a51_refs"]
        assert exp["expected_default_mode_verdict"]["exit_code"] == 0

    def test_audit_expectations_match_canonical_state(self) -> None:
        exp = _load_audit_expectations(self.FIXTURE)
        _, rows = _read_csv(
            self.FIXTURE / "expected_outputs/canonical/core_controls/A51_issue_route_register.csv"
        )
        assert exp["expected_a51_count"] == len(rows)
        assert exp["expected_a51_routes"] == [r["A51Ref"] for r in rows]


# ---- Cross-fixture invariants ----------------------------------------


@pytest.mark.parametrize(
    "fixture_name",
    [
        "adversarial_multi_way_contradiction_001",
        "adversarial_tier_delta_auto_resolution_001",
        "adversarial_block_on_contradiction_001",
    ],
)
def test_fixture_has_required_artifacts(fixture_name: str) -> None:
    """Every B3 adversarial fixture has README + audit_expectations +
    fixture_metadata + the FIVE canonical CSVs (A50/A58/A59/A60/A51)
    + at least one expected_markers/*.json."""
    f = FIXTURES / fixture_name
    assert (f / "README.md").is_file()
    assert (f / "audit_expectations.json").is_file()
    assert (f / "fixture_metadata.json").is_file()
    core = f / "expected_outputs/canonical/core_controls"
    for csv_name in (
        "A50_source_register.csv",
        "A58_evidence_excerpts.csv",
        "A59_claim_register.csv",
        "A60_negative_evidence_register.csv",  # v1.1.5 round-1 cleanup: was missing
        "A51_issue_route_register.csv",
    ):
        assert (core / csv_name).is_file(), f"{fixture_name}: missing {csv_name}"
    # v1.1.5 round-1 cleanup: also pin expected_markers presence + content.
    markers_dir = f / "expected_markers"
    assert markers_dir.is_dir(), f"{fixture_name}: expected_markers/ dir missing"
    marker_files = sorted(markers_dir.glob("*.json"))
    assert marker_files, f"{fixture_name}: expected_markers/ contains no *.json"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "adversarial_multi_way_contradiction_001",
        "adversarial_tier_delta_auto_resolution_001",
        "adversarial_block_on_contradiction_001",
    ],
)
def test_fixture_metadata_has_required_fields(fixture_name: str) -> None:
    """v1.1.5 round-1 cleanup: pin the 5 fixture_runner-required fields
    (canon_policy_version, plugin_version, model_used, model_version_hash,
    captured_at) — the patch summary claims these are covered but the
    original parametric set didn't actually assert them."""
    meta = _load_metadata(FIXTURES / fixture_name)
    for required in (
        "canon_policy_version", "plugin_version",
        "model_used", "model_version_hash", "captured_at",
    ):
        assert required in meta, f"{fixture_name}: fixture_metadata.json missing '{required}'"


@pytest.mark.parametrize(
    "fixture_name,csv_path,validate_at_path",
    [
        # Each row exercises the live F5 write_validator (jsonschema +
        # cross-field rules), not just the loader's column-set check.
        # validate_at_path is the canonical workspace path the validator
        # uses to dispatch — relative paths are fine here because the
        # validator's content-only check (jsonschema) doesn't need the
        # sibling-cache to fire (cross-artifact rules no-op when the
        # workspace dir doesn't exist on disk; row-level schema rules
        # always run).
        ("adversarial_multi_way_contradiction_001",
         "A50_source_register.csv",
         "analysis/canonical/core_controls/A50_source_register.csv"),
        ("adversarial_multi_way_contradiction_001",
         "A58_evidence_excerpts.csv",
         "analysis/canonical/core_controls/A58_evidence_excerpts.csv"),
        ("adversarial_multi_way_contradiction_001",
         "A59_claim_register.csv",
         "analysis/canonical/core_controls/A59_claim_register.csv"),
        ("adversarial_multi_way_contradiction_001",
         "A60_negative_evidence_register.csv",
         "analysis/canonical/core_controls/A60_negative_evidence_register.csv"),
        ("adversarial_multi_way_contradiction_001",
         "A51_issue_route_register.csv",
         "analysis/canonical/core_controls/A51_issue_route_register.csv"),
        ("adversarial_tier_delta_auto_resolution_001",
         "A50_source_register.csv",
         "analysis/canonical/core_controls/A50_source_register.csv"),
        ("adversarial_tier_delta_auto_resolution_001",
         "A58_evidence_excerpts.csv",
         "analysis/canonical/core_controls/A58_evidence_excerpts.csv"),
        ("adversarial_tier_delta_auto_resolution_001",
         "A59_claim_register.csv",
         "analysis/canonical/core_controls/A59_claim_register.csv"),
        ("adversarial_tier_delta_auto_resolution_001",
         "A60_negative_evidence_register.csv",
         "analysis/canonical/core_controls/A60_negative_evidence_register.csv"),
        # Note: tier-delta A51 is empty (header-only) — the validator
        # accepts it (no rows to violate enums); we still exercise the
        # dispatch + column-set check.
        ("adversarial_tier_delta_auto_resolution_001",
         "A51_issue_route_register.csv",
         "analysis/canonical/core_controls/A51_issue_route_register.csv"),
        ("adversarial_block_on_contradiction_001",
         "A50_source_register.csv",
         "analysis/canonical/core_controls/A50_source_register.csv"),
        ("adversarial_block_on_contradiction_001",
         "A58_evidence_excerpts.csv",
         "analysis/canonical/core_controls/A58_evidence_excerpts.csv"),
        ("adversarial_block_on_contradiction_001",
         "A59_claim_register.csv",
         "analysis/canonical/core_controls/A59_claim_register.csv"),
        ("adversarial_block_on_contradiction_001",
         "A60_negative_evidence_register.csv",
         "analysis/canonical/core_controls/A60_negative_evidence_register.csv"),
        ("adversarial_block_on_contradiction_001",
         "A51_issue_route_register.csv",
         "analysis/canonical/core_controls/A51_issue_route_register.csv"),
    ],
)
def test_fixture_csv_passes_live_write_validator(
    fixture_name: str, csv_path: str, validate_at_path: str,
) -> None:
    """v1.1.5 round-1 cleanup: tighten 'schema validation' from
    column-set-only loader checks to the live F5 write_validator
    (jsonschema row-level enum/regex/cross-field rules). Catches drift
    that the loader's column-set check doesn't (e.g., non-canonical
    Severity, malformed A51Ref, ClaimStrength out of range)."""
    from governance.schemas.write_validator import validate_canonical_write
    csv_full_path = FIXTURES / fixture_name / "expected_outputs" / "canonical" / "core_controls" / csv_path
    content = csv_full_path.read_text(encoding="utf-8")
    ok, msgs = validate_canonical_write(validate_at_path, content)
    assert ok, f"{fixture_name}/{csv_path} failed write_validator: {msgs}"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "adversarial_multi_way_contradiction_001",
        "adversarial_tier_delta_auto_resolution_001",
        "adversarial_block_on_contradiction_001",
    ],
)
def test_fixture_marker_passes_live_write_validator(fixture_name: str) -> None:
    """v1.1.5 round-1 cleanup: every expected_markers/*.json passes the
    live marker validator (marker-id alphabet, payload shape, verdict
    enum)."""
    from governance.schemas.write_validator import validate_canonical_write
    markers_dir = FIXTURES / fixture_name / "expected_markers"
    marker_files = sorted(markers_dir.glob("*.json"))
    assert marker_files, f"{fixture_name}: no marker files to validate"
    for mp in marker_files:
        content = mp.read_text(encoding="utf-8")
        # The live marker validator uses the marker-payload schema. We
        # dispatch via a canonical runtime/ready/ path so the validator
        # routes to the marker validator.
        validate_at = f"analysis/runtime/ready/{mp.name}"
        ok, msgs = validate_canonical_write(validate_at, content)
        assert ok, f"{fixture_name}/{mp.name} failed marker validator: {msgs}"
