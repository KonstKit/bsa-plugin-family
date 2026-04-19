"""Tests for ReliabilityTier -> ClaimStrength propagation (US-S3-03).

The authoritative contract is
``skills/bsa-evidence-intake/references/reliability_tier_spec.md``.
These tests pin the two most-referenced invariants of the contract:

1. The five tier weights are exactly T1=1.00 / T2=0.85 / T3=0.65 /
   T4=0.45 / T5=0.20, and are referenced consistently across the KPI
   definition, the tier spec, and any skill that propagates
   ClaimStrength.
2. On the committed project_0001 fixture, every direct/inference A59
   row's ClaimStrength equals the max supporting-source tier weight
   (with decay_factor=0 in Sprint 3).

The tests stay stdlib-only (csv + re); the tier weights are parsed from
the committed spec so a future weight change requires editing the spec,
not a constant.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TIER_SPEC = (
    REPO_ROOT
    / "skills"
    / "bsa-evidence-intake"
    / "references"
    / "reliability_tier_spec.md"
)
FIXTURE_A50 = (
    REPO_ROOT
    / "fixtures"
    / "golden"
    / "project_0001"
    / "expected_outputs"
    / "canonical"
    / "core_controls"
    / "A50_source_register.csv"
)
FIXTURE_A59 = (
    REPO_ROOT
    / "fixtures"
    / "golden"
    / "project_0001"
    / "expected_outputs"
    / "canonical"
    / "core_controls"
    / "A59_claim_register.csv"
)


def _parse_tier_weights() -> dict[str, float]:
    """Parse the tier weights table out of the committed spec.

    The tier table has the form:
      | **T1** | empirical | ... | **1.00** |
      | **T2** | ...       | ... | **0.85** |
      ...
    We extract the tier code (T1..T5) and its bold weight.
    """
    text = TIER_SPEC.read_text(encoding="utf-8")
    # Capture lines like "| **T1** | ... | **1.00** |"
    pattern = re.compile(
        r"\|\s*\*\*(T[1-5])\*\*\s*\|[^\n]*\|\s*\*\*(\d+\.\d+)\*\*\s*\|",
        re.MULTILINE,
    )
    matches = pattern.findall(text)
    return {tier: float(weight) for tier, weight in matches}


def test_tier_weights_exist_and_match_spec() -> None:
    weights = _parse_tier_weights()
    assert weights == {
        "T1": 1.00,
        "T2": 0.85,
        "T3": 0.65,
        "T4": 0.45,
        "T5": 0.20,
    }, f"unexpected tier weights parsed from spec: {weights}"


def test_kpi_definition_references_tier_spec() -> None:
    """KPI-001 must link to the tier spec so reviewers can find the
    weighted-coverage formula without guessing."""
    kpi_doc = (
        REPO_ROOT
        / "skills"
        / "bsa-orchestrator"
        / "references"
        / "kpi-definitions.md"
    )
    text = kpi_doc.read_text(encoding="utf-8")
    assert "reliability_tier_spec.md" in text
    assert "ClaimStrength" in text
    # The 0.75 target landed in Sprint 3 US-S3-03.
    assert ">= 0.75" in text


def test_citation_auditor_has_epistemic_insufficiency_rule() -> None:
    """bsa-citation-auditor SKILL.md must describe the EpistemicInsufficiency
    finding and its four sub-types."""
    skill = (
        REPO_ROOT
        / "skills"
        / "bsa-citation-auditor"
        / "SKILL.md"
    )
    text = skill.read_text(encoding="utf-8")
    for sub_type in (
        "EpistemicInsufficiency / low_tier_only",
        "EpistemicInsufficiency / not_independent",
        "EpistemicInsufficiency / anecdotal_only",
        "EpistemicInsufficiency / judgment_on_low_tier",
    ):
        assert sub_type in text, f"missing EpistemicInsufficiency sub-type: {sub_type}"


def test_fixture_claim_strength_matches_source_tier() -> None:
    """Every direct/inference A59 row in project_0001 must have
    ClaimStrength equal to the max tier weight across its supporting A50
    rows (decay_factor=0). analyst_judgment rows MUST have blank
    ClaimStrength."""
    weights = _parse_tier_weights()

    a50_rows = list(csv.DictReader(FIXTURE_A50.read_text().splitlines()))
    source_tier = {row["SourceID"]: row["ReliabilityTier"] for row in a50_rows}

    a59_rows = list(csv.DictReader(FIXTURE_A59.read_text().splitlines()))
    for row in a59_rows:
        ctype = row["ClaimType"]
        strength = row["ClaimStrength"].strip()
        if ctype == "analyst_judgment":
            assert strength == "", (
                f"analyst_judgment row {row['ClaimID']} must have blank "
                f"ClaimStrength per reliability_tier_spec.md §'ClaimType interaction'"
            )
            continue
        # direct / inference
        src = row["SourceID"]
        assert src in source_tier, (
            f"A59 row {row['ClaimID']} references SourceID {src} not in A50"
        )
        tier = source_tier[src]
        assert tier in weights, (
            f"A50 row for {src} has ReliabilityTier={tier!r}, "
            f"expected one of {sorted(weights)}"
        )
        expected = weights[tier]
        assert abs(float(strength) - expected) < 1e-9, (
            f"A59 row {row['ClaimID']}: ClaimStrength={strength} does not "
            f"match tier {tier} weight={expected} for SourceID {src}"
        )


def test_fixture_a50_has_tier_assigned_on_every_row() -> None:
    """reliability_tier_spec.md requires exactly one tier per row; no
    blank values permitted."""
    a50_rows = list(csv.DictReader(FIXTURE_A50.read_text().splitlines()))
    for row in a50_rows:
        tier = row["ReliabilityTier"].strip()
        assert tier in {"T1", "T2", "T3", "T4", "T5"}, (
            f"A50 row {row.get('SourceID', '?')}: ReliabilityTier={tier!r} "
            f"must be one of T1..T5 per reliability_tier_spec.md"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
