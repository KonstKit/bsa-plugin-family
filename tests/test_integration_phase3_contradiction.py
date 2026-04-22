"""Sprint 9 US-S9-04 — Phase-3 contradictory-evidence regression test.

Asserts the chain (A59 → A60 → A51 → A62 → A70 → A71 → A72)
propagates the upstream contradiction as A51-routed deferrals at
every layer rather than silently picking one side of the
disagreement.

Fixture: fixtures/golden/adversarial_nfr_claim_contradiction_001/.
Two sources disagree on a measurable target (High-severity
initial-response SLA: 4h vs 30min). Headline assertion:
`test_contradiction_propagates_to_every_phase3_artifact` —
every Phase-3 artifact has the contradiction surfaced as a
deferred A51 route.

Sister test to tests/test_integration_phase3_project_0001.py
(US-S8-03 happy-path) — together the two fixtures cover both
the clean Phase-3 chain AND the adversarial-evidence chain.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = (
    REPO_ROOT / "fixtures" / "golden" / "adversarial_nfr_claim_contradiction_001"
)
EXPECTED_OUTPUTS = FIXTURE_ROOT / "expected_outputs"
EXPECTED_MARKERS = FIXTURE_ROOT / "expected_markers"
CORE_CONTROLS = EXPECTED_OUTPUTS / "canonical" / "core_controls"

CONTRADICTION_A51_REF = "A51-CONFL-001"


# ---- Fixtures --------------------------------------------------------


@pytest.fixture(scope="module")
def expectations() -> dict:
    return json.loads((FIXTURE_ROOT / "audit_expectations.json").read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def a51_rows() -> list[dict]:
    return _read_csv(CORE_CONTROLS / "A51_issue_route_register.csv")


@pytest.fixture(scope="module")
def a59_rows() -> list[dict]:
    return _read_csv(CORE_CONTROLS / "A59_claim_register.csv")


@pytest.fixture(scope="module")
def a60_rows() -> list[dict]:
    return _read_csv(CORE_CONTROLS / "A60_negative_evidence_register.csv")


@pytest.fixture(scope="module")
def a62_rows() -> list[dict]:
    return _read_csv(CORE_CONTROLS / "A62_nfr_register.csv")


@pytest.fixture(scope="module")
def a70_rows() -> list[dict]:
    return _read_csv(CORE_CONTROLS / "A70_story_register.csv")


@pytest.fixture(scope="module")
def a71_rows() -> list[dict]:
    return _read_csv(CORE_CONTROLS / "A71_test_scenario_register.csv")


@pytest.fixture(scope="module")
def a72_rows() -> list[dict]:
    return _read_csv(CORE_CONTROLS / "A72_traceability_matrix.csv")


# ---- 1. F5 schema validation passes for every fixture artifact ----


@pytest.mark.parametrize(
    "filename,schema_name",
    [
        ("A50_source_register.csv", "a50"),
        ("A51_issue_route_register.csv", "a51"),
        ("A58_evidence_excerpts.csv", "a58"),
        ("A59_claim_register.csv", "a59"),
        ("A60_negative_evidence_register.csv", "a60"),
        ("A62_nfr_register.csv", "a62"),
        ("A70_story_register.csv", "a70"),
        ("A71_test_scenario_register.csv", "a71"),
        ("A72_traceability_matrix.csv", "a72"),
    ],
)
def test_fixture_artifact_passes_f5_validation(filename: str, schema_name: str) -> None:
    """The contradicted-evidence fixture must still pass every
    canonical F5 schema check — the contract is "surface as A51",
    not "fail on contradiction"."""
    from governance.schemas.write_validator import (
        _dispatch,
        validate_canonical_write,
    )

    rel = f"analysis/canonical/core_controls/{filename}"
    dispatch = _dispatch(rel)
    assert dispatch is not None
    routed_schema, _fn = dispatch
    assert routed_schema == schema_name
    content = (CORE_CONTROLS / filename).read_text(encoding="utf-8")
    ok, msgs = validate_canonical_write(rel, content)
    assert ok, f"{filename} F5 violations:\n" + "\n".join(msgs)


def test_fixture_a48_passes_f5_validation() -> None:
    from governance.schemas.write_validator import validate_canonical_write

    content = (CORE_CONTROLS / "A48_run_context_card.md").read_text(encoding="utf-8")
    ok, msgs = validate_canonical_write(
        "analysis/canonical/core_controls/A48_run_context_card.md", content
    )
    assert ok, msgs


@pytest.mark.parametrize(
    "marker_filename",
    [
        "phase3.nfr.pass.json",
        "phase3.story.pass.json",
        "phase3.test_scenario.pass.json",
        "phase3.traceability.pass.json",
    ],
)
def test_fixture_phase3_marker_passes_f5_validation(marker_filename: str) -> None:
    from governance.schemas.write_validator import validate_canonical_write

    rel = f"analysis/runtime/ready/{marker_filename}"
    content = (EXPECTED_MARKERS / marker_filename).read_text(encoding="utf-8")
    ok, msgs = validate_canonical_write(rel, content)
    assert ok, msgs


# ---- 2. Contradiction captured in A51 + A60 -------------------------


def test_a51_has_contradiction_route(a51_rows: list[dict]) -> None:
    """The A51 register MUST have at least one IssueType=contradiction
    row (the actual contradiction A51-CONFL-001)."""
    contradictions = [r for r in a51_rows if r["IssueType"] == "contradiction"]
    assert contradictions, "A51 register has no contradiction route"
    assert any(r["A51Ref"] == CONTRADICTION_A51_REF for r in contradictions), (
        f"A51 contradiction route {CONTRADICTION_A51_REF} not found"
    )


def test_a51_contradiction_route_references_both_claims(a51_rows: list[dict]) -> None:
    """The contradiction route must reference both contradicted ClaimIDs
    so a downstream consumer can trace the disagreement."""
    route = next(r for r in a51_rows if r["A51Ref"] == CONTRADICTION_A51_REF)
    related = route["RelatedClaimID"]
    assert "C-001" in related
    assert "C-002" in related


def test_a51_contradiction_route_is_hard_blocking(a51_rows: list[dict]) -> None:
    """Round-1 fix: pin BlockingStatus=hard on the contradiction
    route. A future downgrade from `hard` to `soft` would silently
    let downstream skills proceed on contradicted evidence (defeats
    the entire propagation contract). Pin so the downgrade fails
    this test loudly."""
    route = next(r for r in a51_rows if r["A51Ref"] == CONTRADICTION_A51_REF)
    assert route["BlockingStatus"] == "hard", (
        f"Contradiction route {CONTRADICTION_A51_REF} BlockingStatus is "
        f"{route['BlockingStatus']!r}; expected 'hard'. A non-hard "
        f"contradiction lets downstream skills proceed on contradicted "
        f"evidence — defeats the propagation contract."
    )
    assert route["Severity"] == "high", (
        f"Contradiction route {CONTRADICTION_A51_REF} Severity is "
        f"{route['Severity']!r}; expected 'high' (a contradiction on a "
        f"measurable target is not low/medium severity)."
    )


def test_a60_has_cross_link_for_each_contradicted_claim(a60_rows: list[dict]) -> None:
    """A60 negative-evidence register: each contradicted claim should
    appear as a `RelatedClaimID` of a cross-link entry pointing at
    the OTHER claim's source."""
    related_claims = {r["RelatedClaimID"] for r in a60_rows}
    assert "C-001" in related_claims, "A60 missing cross-link for C-001"
    assert "C-002" in related_claims, "A60 missing cross-link for C-002"


def test_a60_cross_links_carry_the_a51_route(a60_rows: list[dict]) -> None:
    """Every contradiction-related A60 cross-link must reference the
    A51 contradiction route so the routing trail is preserved."""
    for row in a60_rows:
        if row["RelatedClaimID"] in ("C-001", "C-002"):
            assert row["A51Ref"] == CONTRADICTION_A51_REF, (
                f"A60 row {row['NegEvID']} for {row['RelatedClaimID']} "
                f"missing A51-CONFL-001 reference"
            )


# ---- 3. Headline US-S9-04 acceptance: contradiction propagates ----


def test_a59_contradicted_claims_carry_a51_ref(a59_rows: list[dict]) -> None:
    """Both contradicted claims (C-001 + C-002) must reference the
    A51 contradiction route via their A51Ref column."""
    for cid in ("C-001", "C-002"):
        claim = next(r for r in a59_rows if r["ClaimID"] == cid)
        assert claim["A51Ref"] == CONTRADICTION_A51_REF, (
            f"A59 claim {cid} missing A51-CONFL-001 reference"
        )


def test_a59_contradicted_claims_have_zero_strength(a59_rows: list[dict]) -> None:
    """Round-5 fix: per a59 schema's ClaimStrength description and
    reliability_tier_spec, contradiction-routed claims (same-tier
    disagreement that doesn't auto-resolve) MUST have ClaimStrength=0.0
    (the contradiction neutralizes the tier-derived strength). A
    future drift that keeps the tier-derived 0.85 would pass without
    this pin."""
    for cid in ("C-001", "C-002"):
        claim = next(r for r in a59_rows if r["ClaimID"] == cid)
        assert claim["ClaimStrength"] == "0.0", (
            f"A59 claim {cid} ClaimStrength is {claim['ClaimStrength']!r}; "
            f"expected '0.0' per a59 schema's contradiction-routed value "
            f"(same-tier contradiction neutralizes the tier-derived strength)."
        )


def test_a62_quantitative_nfr_defers_target_via_a51(a62_rows: list[dict]) -> None:
    """The A62 NFR derived from contradicted claims MUST have empty
    Target AND non-empty A51Ref — INV-09 satisfied via the
    A51-route alternative (per measurability-rules: Metric+Target
    OR A51Ref non-empty).

    Note: Metric (the WHAT — 'first response minutes') is NOT
    contested by the source disagreement; only Target (the THRESHOLD
    — 4h vs 30min) is. So the correct A62 shape is Metric non-empty,
    Target empty, A51Ref set. This is the round-1 fix — earlier
    audit_expectations.json claimed Metric+Target both empty which
    was over-strict and contradicted by the actual fixture content."""
    perf_nfrs = [r for r in a62_rows if r["NFRCategory"] == "performance"]
    assert perf_nfrs, "fixture missing the contradicted performance NFR"
    nfr = perf_nfrs[0]
    # Target must be empty (contradicted; can't pick a single value).
    assert not nfr["Target"].strip(), (
        f"NFR {nfr['NFRID']} Target is non-empty ({nfr['Target']!r}) — "
        f"the chain silently picked one side of the contradiction"
    )
    # Metric must be non-empty (the WHAT is uncontested).
    assert nfr["Metric"].strip(), (
        f"NFR {nfr['NFRID']} Metric is empty — the WHAT (first-response-minutes) "
        f"is uncontested by the source disagreement; only the threshold value "
        f"is contested. Empty Metric over-defers and obscures the partial-grounding."
    )
    # A51Ref must point at the contradiction route.
    assert CONTRADICTION_A51_REF in nfr["A51Ref"]


def test_a70_story_invest_deferred_with_a51(a70_rows: list[dict]) -> None:
    """Every story whose acceptance depends on a contradicted claim
    MUST carry INVESTStatus=needs-negotiation + non-empty A51Ref
    (per x-bsa-invest-rules)."""
    for story in a70_rows:
        # Find stories that reference a contradicted claim.
        if any(cid in story["SourceClaimIDs"] for cid in ("C-001", "C-002")):
            assert story["INVESTStatus"] == "needs-negotiation", (
                f"Story {story['StoryID']} touches contradicted claim "
                f"but INVESTStatus is {story['INVESTStatus']!r}; "
                f"expected 'needs-negotiation'"
            )
            assert CONTRADICTION_A51_REF in story["A51Ref"]


def test_a71_scenario_automation_deferred_with_a51(a71_rows: list[dict]) -> None:
    """Every scenario verifying a contradicted target MUST carry
    AutomationStatus=deferred + non-empty A51Ref (per
    x-bsa-deferral-rules)."""
    for scenario in a71_rows:
        # In this fixture all A71 rows are downstream of the contradiction.
        assert scenario["AutomationStatus"] == "deferred", (
            f"Scenario {scenario['ScenarioID']} AutomationStatus is "
            f"{scenario['AutomationStatus']!r}; expected 'deferred'"
        )
        assert CONTRADICTION_A51_REF in scenario["A51Ref"]


def test_a71_then_clause_preserves_both_contradicted_literals(
    a71_rows: list[dict],
) -> None:
    """The Then-clause MUST preserve BOTH contradicted target literals
    (4 hours / 30 minutes) — never silently pick one. Pin: future
    drift toward "let's just pick the higher-tier" silently fails
    this test."""
    for scenario in a71_rows:
        then_clause = scenario["Then"]
        # Both numeric literals from the contradiction must appear.
        assert "4 hours" in then_clause, (
            f"Scenario {scenario['ScenarioID']} Then-clause does not "
            f"preserve the C-001 literal '4 hours'; possibly silent "
            f"picking of one side. Then: {then_clause!r}"
        )
        assert "30 minutes" in then_clause, (
            f"Scenario {scenario['ScenarioID']} Then-clause does not "
            f"preserve the C-002 literal '30 minutes'; possibly silent "
            f"picking of one side. Then: {then_clause!r}"
        )


def test_a72_all_rows_a51_routed_with_a51_ref(a72_rows: list[dict]) -> None:
    """Every A72 trace row touching a contradicted claim MUST carry
    LinkType=a51-routed + non-empty A51Ref (per x-bsa-deferral-rules
    with status_field=LinkType override)."""
    for trace in a72_rows:
        if trace["ClaimID"] in ("C-001", "C-002"):
            assert trace["LinkType"] == "a51-routed", (
                f"Trace {trace['TraceID']} touches contradicted claim "
                f"{trace['ClaimID']} but LinkType is {trace['LinkType']!r}; "
                f"expected 'a51-routed'"
            )
            assert CONTRADICTION_A51_REF in trace["A51Ref"]


def test_contradiction_propagates_to_every_phase3_artifact(
    expectations: dict,
    a59_rows: list[dict],
    a62_rows: list[dict],
    a70_rows: list[dict],
    a71_rows: list[dict],
    a72_rows: list[dict],
) -> None:
    """HEADLINE US-S9-04 ACCEPTANCE: the contradiction surfaces in
    EVERY Phase-3 artifact via the A51 route. This is the single
    most important test in this file — it pins the end-to-end
    contradiction-propagation contract mechanically.

    Drift in any of these paths means the chain silently picked one
    side or dropped the contradiction entirely."""
    cprop = expectations["expected_contradiction_propagation"]

    # A59: both contradicted claims reference the A51 route.
    for cid in ("C-001", "C-002"):
        claim = next(r for r in a59_rows if r["ClaimID"] == cid)
        assert claim["A51Ref"] == cprop["a51_route_id"]

    # A62: NFR Target empty (Metric non-empty — the WHAT is uncontested)
    # AND A51Ref set.
    perf_nfr = next(r for r in a62_rows if r["NFRCategory"] == "performance")
    assert cprop["a62_target_empty"] is True
    assert cprop["a62_metric_non_empty"] is True
    assert not perf_nfr["Target"].strip(), (
        f"A62 Target should be empty (contradicted); got {perf_nfr['Target']!r}"
    )
    assert perf_nfr["Metric"].strip(), (
        f"A62 Metric should be non-empty (uncontested WHAT); got {perf_nfr['Metric']!r}"
    )
    assert cprop["a51_route_id"] in perf_nfr["A51Ref"]

    # A70: INVESTStatus matches expected + A51Ref set.
    story = a70_rows[0]
    assert story["INVESTStatus"] == cprop["a70_invest_status"]
    assert cprop["a51_route_id"] in story["A51Ref"]

    # A71: AutomationStatus matches expected + A51Ref set.
    scenario = a71_rows[0]
    assert scenario["AutomationStatus"] == cprop["a71_automation_status"]
    assert cprop["a51_route_id"] in scenario["A51Ref"]

    # A72: every row LinkType matches expected + A51Ref set.
    for trace in a72_rows:
        assert trace["LinkType"] == cprop["a72_link_type_all_rows"]
        assert cprop["a51_route_id"] in trace["A51Ref"]


# ---- 4. Audit-expectations declarations match fixture state -------


def test_expected_phase3_counts_match_fixture(
    expectations: dict,
    a59_rows: list[dict],
    a60_rows: list[dict],
    a62_rows: list[dict],
    a70_rows: list[dict],
    a71_rows: list[dict],
    a72_rows: list[dict],
) -> None:
    declared = expectations["expected_phase3_counts"]
    assert declared["a59_claims"] == len(a59_rows)
    assert declared["a60_negative_evidence_rows"] == len(a60_rows)
    assert declared["a62_nfrs"] == len(a62_rows)
    assert declared["a70_stories"] == len(a70_rows)
    assert declared["a71_scenarios"] == len(a71_rows)
    assert declared["a72_traces"] == len(a72_rows)


def test_expected_a51_issue_types_present(
    expectations: dict, a51_rows: list[dict]
) -> None:
    declared = set(expectations["expected_a51_issue_types_present"])
    actual = {r["IssueType"] for r in a51_rows}
    missing = declared - actual
    assert not missing, f"declared A51 IssueTypes missing from fixture: {sorted(missing)}"


def test_expected_a51_routes_match_fixture(
    expectations: dict, a51_rows: list[dict]
) -> None:
    declared = set(expectations["expected_a51_routes"])
    actual = {r["A51Ref"] for r in a51_rows}
    assert actual == declared, (
        f"A51 route set drift. declared - actual = {declared - actual}; "
        f"actual - declared = {actual - declared}"
    )


# ---- 5. No-net-new-claims discipline (round-1 fix; mirrors S8-03) --
# bsa-story-writer + bsa-test-scenario-builder are RESHAPE skills.
# Same anti-drift discipline as the project_0001 happy-path fixture
# (tests/test_integration_phase3_project_0001.py section 6) applied
# to the adversarial fixture. The adversarial case is MORE prone to
# drift because the LLM might "average" the contradicted values
# (e.g., 'within 2 hours, 15 minutes' = 4h+30min averaged) — which
# would invent a numeric not in either source.


import re

_NUMERIC_TOKEN_RE = re.compile(r"(?<![-A-Z])\b\d+(?:\.\d+)?\b(?![-A-Z])")
_ALWAYS_ALLOWED_NUMERICS = frozenset({"0", "1", "2", "3", "100"})


def _read_input_corpus() -> str:
    """Concatenated text of the fixture's input files (the original
    sources). Downstream A70/A71 numerics MUST appear here verbatim."""
    parts: list[str] = []
    inputs_dir = FIXTURE_ROOT / "inputs"
    for f in sorted(inputs_dir.iterdir()):
        if f.is_file():
            parts.append(f.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _upstream_numeric_token_set(corpus: str) -> set[str]:
    return set(_NUMERIC_TOKEN_RE.findall(corpus))


def _ungrounded_numeric_tokens(text: str, upstream: set[str]) -> list[str]:
    out = []
    for tok in _NUMERIC_TOKEN_RE.findall(text):
        if tok in _ALWAYS_ALLOWED_NUMERICS:
            continue
        if tok not in upstream:
            out.append(tok)
    return out


def test_a70_acceptance_criteria_numerics_grounded_in_inputs(
    a70_rows: list[dict],
) -> None:
    """Adversarial-fixture variant: A70 AcceptanceCriteria numerics
    MUST appear in the original input source files verbatim. The
    contradiction case is especially drift-prone — the LLM might
    average the values (e.g., 2h15min from (4h+30min)/2) which would
    silently corrupt the contradiction.
    """
    upstream = _upstream_numeric_token_set(_read_input_corpus())
    for story in a70_rows:
        ungrounded = _ungrounded_numeric_tokens(story["AcceptanceCriteria"], upstream)
        assert not ungrounded, (
            f"A70 row {story['StoryID']} AcceptanceCriteria carries "
            f"numeric token(s) {ungrounded!r} not present in upstream "
            f"input files. Upstream tokens: {sorted(upstream)}"
        )


def test_a71_then_clause_numerics_grounded_in_inputs(
    a71_rows: list[dict],
) -> None:
    """Same anti-drift on A71.Then-clauses. Both contradicted literals
    (4 / 30) must be in the upstream token set, AND the Then-clause
    must use exactly those tokens (no averages, no new numerics)."""
    upstream = _upstream_numeric_token_set(_read_input_corpus())
    for scenario in a71_rows:
        ungrounded = _ungrounded_numeric_tokens(scenario["Then"], upstream)
        assert not ungrounded, (
            f"A71 row {scenario['ScenarioID']} Then-clause carries "
            f"numeric token(s) {ungrounded!r} not present in upstream "
            f"input files (would indicate the LLM averaged or invented "
            f"a value rather than preserving the contradiction). "
            f"Upstream tokens: {sorted(upstream)}"
        )


def test_ungrounded_helper_rejects_substring_only_for_contradiction_fixture() -> None:
    """Round-2 Should: mirror the US-S8-03 round-3 substring-vs-token
    regression pin in the adversarial-fixture suite. Ensures a future
    revert to substring matching (`assert tok in corpus_string`)
    fails the production grounding tests AND this pin (because both
    route through `_ungrounded_numeric_tokens`).

    NB: synthetic tokens are deliberately OUTSIDE _ALWAYS_ALLOWED_NUMERICS
    ({0,1,2,3,100}) so the grounding logic actually exercises — '5'
    is a substring of '50' AND not in the always-allowed set."""
    upstream = {"50"}  # only one whole-token upstream
    # '5' is a substring of '50' but NOT a whole-token; must be flagged.
    out = _ungrounded_numeric_tokens("within 5 minutes", upstream)
    assert out == ["5"], (
        f"_ungrounded_numeric_tokens regressed to substring semantics: "
        f"expected ['5'] (synthetic prefix that should NOT be grounded "
        f"by '50'); got {out!r}"
    )
    # Whole-token '50' is grounded.
    assert _ungrounded_numeric_tokens("within 50 minutes", upstream) == []
    # Always-allowed exempt regardless.
    assert _ungrounded_numeric_tokens("at least 1 retry within 100% cases", upstream) == []


def test_a72_foreign_keys_resolve_for_contradicted_traces(
    a72_rows: list[dict],
    a70_rows: list[dict],
    a59_rows: list[dict],
) -> None:
    """Round-2 Should: a51-routed rows still subject to FK integrity
    (US-S8-02 round-2 invariant `applies_to_all_rows: true`). Pin so
    a future drift that exempts a51-routed from FK checks would fail.
    Mirrors test_a72_foreign_keys_resolve in the happy-path suite."""
    a70_ids = {row["StoryID"] for row in a70_rows}
    a59_ids = {row["ClaimID"] for row in a59_rows}
    # Read A50 directly (not in module fixtures yet).
    a50_rows = _read_csv(CORE_CONTROLS / "A50_source_register.csv")
    a50_ids = {row["SourceID"] for row in a50_rows}
    for trace in a72_rows:
        assert trace["StoryID"] in a70_ids, (
            f"A72 {trace['TraceID']} StoryID {trace['StoryID']!r} not in A70 "
            f"(LinkType={trace['LinkType']} — FK integrity applies regardless)"
        )
        assert trace["ClaimID"] in a59_ids, (
            f"A72 {trace['TraceID']} ClaimID {trace['ClaimID']!r} not in A59"
        )
        assert trace["SourceID"] in a50_ids, (
            f"A72 {trace['TraceID']} SourceID {trace['SourceID']!r} not in A50"
        )


def test_a72_claim_source_consistency_for_contradicted_traces(
    a72_rows: list[dict], a59_rows: list[dict]
) -> None:
    """Round-2 Should: claim-source consistency MUST hold even for
    a51-routed rows (the US-S8-02 round-2 fix removed the earlier
    LinkType-class exemption). For every trace, A59[ClaimID].SourceID
    must equal the trace's SourceID — defection would mean the matrix
    is internally inconsistent. Mirrors the happy-path suite."""
    by_cid = {row["ClaimID"]: row for row in a59_rows}
    for trace in a72_rows:
        a59_row = by_cid.get(trace["ClaimID"])
        assert a59_row is not None
        assert a59_row["SourceID"] == trace["SourceID"], (
            f"A72 {trace['TraceID']} (LinkType={trace['LinkType']}) "
            f"SourceID drift: row says {trace['SourceID']!r}, "
            f"A59[{trace['ClaimID']}].SourceID says {a59_row['SourceID']!r}. "
            f"a51-routed rows must satisfy claim-source consistency too "
            f"(applies_to_all_rows=true)."
        )


def test_a70_a71_no_invented_mechanism_keywords(
    a70_rows: list[dict], a71_rows: list[dict]
) -> None:
    """Lexical pin against averaging or middle-ground phrases the
    LLM might emit on a contradiction case."""
    banned = (
        "compromise window",
        "agreed window of approximately",
        "averaged SLA",
        "middle ground",
        "approximately 2 hours",  # (4h + 30min averaged)
        "within roughly",
    )
    for story in a70_rows:
        text = story["AcceptanceCriteria"] + " " + story["StoryText"]
        for phrase in banned:
            assert phrase not in text, (
                f"A70 {story['StoryID']} contains banned drift phrase "
                f"{phrase!r} (LLM averaging/compromise on a contradiction)"
            )
    for scenario in a71_rows:
        text = " ".join(
            (scenario.get("Given", ""), scenario.get("When", ""), scenario.get("Then", ""))
        )
        for phrase in banned:
            assert phrase not in text, (
                f"A71 {scenario['ScenarioID']} contains banned drift phrase "
                f"{phrase!r} (LLM averaging/compromise on a contradiction)"
            )
