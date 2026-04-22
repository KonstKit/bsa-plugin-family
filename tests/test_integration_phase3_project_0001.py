"""Sprint 8 US-S8-03 — end-to-end integration test on the project_0001
golden fixture.

Asserts that the full main-cycle + Phase-3 chain holds together for
the support-ticket triage scenario:

    D (skipped — direct mode) → Stage 1..8 → phase3.nfr → phase3.story
    → phase3.test_scenario → phase3.traceability

The fixture was extended at US-S8-03 to include A62/A70/A71/A72 +
the four phase3.*.pass markers. This file is the EXECUTABLE side of
the regression: every Phase-3 artifact passes F5 schema validation,
every phase3 marker passes H-sec-4 binding, and the cross-artifact
join is internally consistent (A70.SourceClaimIDs resolves in A59;
A70.RelatedNFRIDs resolves in A62; A71.SourceStoryID resolves in A70;
A71.RelatedNFRID resolves in A62 when non-empty; A72.StoryID/ClaimID/
SourceID resolve in A70/A59/A50; A59[ClaimID].SourceID equals
A72.SourceID for ALL rows including a51-routed; every A71 scenario
links back to claim+source through the matrix).

The headline acceptance criterion from docs/phase_3_plan.md US-S8-03:
"every test scenario links back to claim + source through the matrix"
— pinned by `test_every_a71_scenario_resolves_through_a72`.

The audit_expectations.json file declares the COUNT + invariant
expectations; this test parses it and asserts each expectation
mechanically. Drift between the fixture state on disk and the
audit_expectations.json declaration fails the test.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "golden" / "project_0001"
EXPECTED_OUTPUTS = FIXTURE_ROOT / "expected_outputs"
EXPECTED_MARKERS = FIXTURE_ROOT / "expected_markers"
CORE_CONTROLS = EXPECTED_OUTPUTS / "canonical" / "core_controls"


# ---- Fixtures --------------------------------------------------------


@pytest.fixture(scope="module")
def expectations() -> dict:
    return json.loads((FIXTURE_ROOT / "audit_expectations.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def a50_rows() -> list[dict]:
    return _read_csv(CORE_CONTROLS / "A50_source_register.csv")


@pytest.fixture(scope="module")
def a59_rows() -> list[dict]:
    return _read_csv(CORE_CONTROLS / "A59_claim_register.csv")


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


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _split_ids(value: str) -> list[str]:
    """Split a SourceClaimIDs / RelatedNFRIDs / A51Ref cell into a list."""
    if not value:
        return []
    parts: list[str] = []
    for chunk in value.replace("/", ";").split(";"):
        s = chunk.strip()
        if s:
            parts.append(s)
    return parts


# ---- 1. Phase-3 artifact F5 schema validation ------------------------


@pytest.mark.parametrize(
    "filename,schema_name",
    [
        ("A62_nfr_register.csv", "a62"),
        ("A70_story_register.csv", "a70"),
        ("A71_test_scenario_register.csv", "a71"),
        ("A72_traceability_matrix.csv", "a72"),
    ],
)
def test_phase3_artifact_passes_f5_validation(filename: str, schema_name: str) -> None:
    """Every Phase-3 canonical CSV in the fixture passes the F5
    write-validator dispatch (same path the pre_write_canonical.sh
    hook invokes at /bsa-promote)."""
    from governance.schemas.write_validator import (
        _dispatch,
        validate_canonical_write,
    )

    rel = f"analysis/canonical/core_controls/{filename}"
    dispatch = _dispatch(rel)
    assert dispatch is not None, f"dispatcher missing entry for {rel}"
    routed_schema, _fn = dispatch
    assert routed_schema == schema_name, (
        f"{rel} routed to {routed_schema!r}; expected {schema_name!r}"
    )
    content = (CORE_CONTROLS / filename).read_text(encoding="utf-8")
    ok, msgs = validate_canonical_write(rel, content)
    assert ok, f"{filename} F5 violations:\n" + "\n".join(msgs)


@pytest.mark.parametrize(
    "marker_filename",
    [
        "phase3.nfr.pass.json",
        "phase3.story.pass.json",
        "phase3.test_scenario.pass.json",
        "phase3.traceability.pass.json",
    ],
)
def test_phase3_marker_passes_f5_validation(marker_filename: str) -> None:
    """Every phase3.*.pass.json marker in the fixture passes F5
    marker validation, including H-sec-4 (filename↔marker_id
    binding + marker_id↔stage/verdict implication)."""
    from governance.schemas.write_validator import validate_canonical_write

    rel = f"analysis/runtime/ready/{marker_filename}"
    content = (EXPECTED_MARKERS / marker_filename).read_text(encoding="utf-8")
    ok, msgs = validate_canonical_write(rel, content)
    assert ok, f"{marker_filename} F5 violations:\n" + "\n".join(msgs)


# ---- 2. Cross-artifact integrity (Phase-3 join) ----------------------


def test_a70_source_claim_ids_resolve_in_a59(
    a70_rows: list[dict], a59_rows: list[dict]
) -> None:
    """INV-08 part 1: every A70 SourceClaimIDs entry resolves to an
    existing A59 ClaimID. Empty SourceClaimIDs is allowed when
    RelatedNFRIDs is non-empty (covered by the schema's
    x-bsa-provenance-rules)."""
    a59_ids = {row["ClaimID"] for row in a59_rows}
    for story in a70_rows:
        for claim_id in _split_ids(story["SourceClaimIDs"]):
            assert claim_id in a59_ids, (
                f"A70 row {story['StoryID']} references C-id {claim_id!r} "
                f"that doesn't exist in A59"
            )


def test_a70_related_nfr_ids_resolve_in_a62(
    a70_rows: list[dict], a62_rows: list[dict]
) -> None:
    """INV-08 part 2 + Phase-3 FK: every A70 RelatedNFRIDs entry
    resolves to an existing A62 NFRID."""
    a62_ids = {row["NFRID"] for row in a62_rows}
    for story in a70_rows:
        for nfr_id in _split_ids(story["RelatedNFRIDs"]):
            assert nfr_id in a62_ids, (
                f"A70 row {story['StoryID']} references NFR-id {nfr_id!r} "
                f"that doesn't exist in A62"
            )


def test_a62_source_claim_ids_resolve_in_a59(
    a62_rows: list[dict], a59_rows: list[dict]
) -> None:
    """Cross-artifact FK: every A62 SourceClaimIDs entry resolves
    to an existing A59 ClaimID."""
    a59_ids = {row["ClaimID"] for row in a59_rows}
    for nfr in a62_rows:
        for claim_id in _split_ids(nfr["SourceClaimIDs"]):
            assert claim_id in a59_ids, (
                f"A62 row {nfr['NFRID']} references C-id {claim_id!r} "
                f"that doesn't exist in A59"
            )


def test_a71_source_story_id_resolves_in_a70(
    a71_rows: list[dict], a70_rows: list[dict]
) -> None:
    """INV-10: every A71 SourceStoryID resolves to an existing A70
    StoryID. Schema enforces non-empty + singular pattern; this
    test adds the cross-artifact FK check."""
    a70_ids = {row["StoryID"] for row in a70_rows}
    for scenario in a71_rows:
        sid = scenario["SourceStoryID"]
        assert sid in a70_ids, (
            f"A71 row {scenario['ScenarioID']} references "
            f"SourceStoryID {sid!r} that doesn't exist in A70"
        )


def test_a71_related_nfr_id_resolves_in_a62(
    a71_rows: list[dict], a62_rows: list[dict]
) -> None:
    """When RelatedNFRID is non-empty, it must resolve in A62."""
    a62_ids = {row["NFRID"] for row in a62_rows}
    for scenario in a71_rows:
        nid = scenario["RelatedNFRID"]
        if not nid:
            continue
        assert nid in a62_ids, (
            f"A71 row {scenario['ScenarioID']} references "
            f"RelatedNFRID {nid!r} that doesn't exist in A62"
        )


def test_a72_foreign_keys_resolve(
    a72_rows: list[dict],
    a70_rows: list[dict],
    a59_rows: list[dict],
    a50_rows: list[dict],
) -> None:
    """A72 FK integrity (per x-bsa-foreign-key-rules.applies_to_all_rows):
    every row's StoryID/ClaimID/SourceID resolves in A70/A59/A50.
    Applies to all LinkType values including a51-routed."""
    a70_ids = {row["StoryID"] for row in a70_rows}
    a59_ids = {row["ClaimID"] for row in a59_rows}
    a50_ids = {row["SourceID"] for row in a50_rows}
    for trace in a72_rows:
        assert trace["StoryID"] in a70_ids, (
            f"A72 {trace['TraceID']} StoryID {trace['StoryID']!r} not in A70"
        )
        assert trace["ClaimID"] in a59_ids, (
            f"A72 {trace['TraceID']} ClaimID {trace['ClaimID']!r} not in A59"
        )
        assert trace["SourceID"] in a50_ids, (
            f"A72 {trace['TraceID']} SourceID {trace['SourceID']!r} not in A50"
        )


def test_a72_claim_source_consistency(
    a72_rows: list[dict], a59_rows: list[dict]
) -> None:
    """Per x-bsa-foreign-key-rules.claim_source_consistency: for
    EVERY A72 row (including LinkType='a51-routed'), the row's
    SourceID MUST equal A59[ClaimID].SourceID. The matrix is a
    JOIN; an internally inconsistent join defeats traceability."""
    by_cid = {row["ClaimID"]: row for row in a59_rows}
    for trace in a72_rows:
        a59_row = by_cid.get(trace["ClaimID"])
        assert a59_row is not None, (
            f"A72 {trace['TraceID']} ClaimID {trace['ClaimID']!r} not in A59"
        )
        a59_source_id = a59_row["SourceID"]
        assert a59_source_id == trace["SourceID"], (
            f"A72 {trace['TraceID']} SourceID drift: row says {trace['SourceID']!r}, "
            f"A59[{trace['ClaimID']}].SourceID says {a59_source_id!r}"
        )


def test_a72_row_identity_uniqueness(a72_rows: list[dict]) -> None:
    """One row per (StoryID, ClaimID, SourceID) triple — no duplicates
    differing only in LinkType (US-S8-02 round-2 invariant)."""
    triples = [
        (row["StoryID"], row["ClaimID"], row["SourceID"]) for row in a72_rows
    ]
    assert len(triples) == len(set(triples)), (
        f"duplicate (Story, Claim, Source) triples in A72: "
        f"{[t for t in triples if triples.count(t) > 1]}"
    )


def test_a72_a51_routed_rows_have_a51_ref(a72_rows: list[dict]) -> None:
    """x-bsa-deferral-rules: LinkType='a51-routed' MUST co-populate A51Ref."""
    for trace in a72_rows:
        if trace["LinkType"] == "a51-routed":
            assert trace["A51Ref"], (
                f"A72 {trace['TraceID']} is a51-routed but A51Ref is empty"
            )


# ---- 3. Headline US-S8-03 acceptance: every scenario traces ---------


def test_every_a71_scenario_resolves_through_a72(
    a71_rows: list[dict], a72_rows: list[dict]
) -> None:
    """HEADLINE US-S8-03 ACCEPTANCE CRITERION (per docs/phase_3_plan.md):
    "every test scenario links back to claim + source through the matrix".

    For every A71 row, find at least one A72 row with the same StoryID.
    Via that A72's ClaimID + SourceID, the scenario's provenance chain
    reaches all the way back to the source.

    This is the single most important test in this file — it pins
    the END-TO-END Phase-3 traceability claim mechanically."""
    by_story = {trace["StoryID"]: [] for trace in a72_rows}
    for trace in a72_rows:
        by_story[trace["StoryID"]].append(trace)
    for scenario in a71_rows:
        sid = scenario["SourceStoryID"]
        traces = by_story.get(sid, [])
        assert traces, (
            f"A71 scenario {scenario['ScenarioID']} (story {sid}) has NO "
            f"A72 row — the test scenario does not trace back to claim + "
            f"source through the matrix. This breaks the headline US-S8-03 "
            f"acceptance criterion."
        )
        # Every trace must have non-empty ClaimID + SourceID (already
        # asserted in test_a72_foreign_keys_resolve, but we re-check
        # here so the failure message points at the SCENARIO, not the
        # raw matrix row).
        for trace in traces:
            assert trace["ClaimID"], (
                f"A72 {trace['TraceID']} (reached from scenario "
                f"{scenario['ScenarioID']}) has empty ClaimID"
            )
            assert trace["SourceID"], (
                f"A72 {trace['TraceID']} (reached from scenario "
                f"{scenario['ScenarioID']}) has empty SourceID"
            )


# ---- 4. Audit-expectations declarations match fixture state ---------


def test_expected_phase3_counts_match_fixture(
    expectations: dict,
    a62_rows: list[dict],
    a70_rows: list[dict],
    a71_rows: list[dict],
    a72_rows: list[dict],
) -> None:
    """The audit_expectations.json file declares the row count for
    each Phase-3 artifact; this test asserts the live fixture
    matches. Drift between the declaration and the on-disk content
    fails the test (forces a deliberate update of one or the other)."""
    declared = expectations["expected_phase3_counts"]
    assert declared["a62_nfrs"] == len(a62_rows)
    assert declared["a70_stories"] == len(a70_rows)
    assert declared["a71_scenarios"] == len(a71_rows)
    assert declared["a72_traces"] == len(a72_rows)


def test_expected_a59_orphans_match_fixture(
    expectations: dict, a59_rows: list[dict], a72_rows: list[dict]
) -> None:
    """Pin the declared set of A59 claims that have no A72 row.
    These are the "claims that no story derived a row from" — the
    orphans the bsa-traceability-matrix skill would record in
    `traceability_orphans.md`."""
    declared = set(expectations["expected_orphans"]["a59_claims_without_a72_row"])
    in_matrix = {trace["ClaimID"] for trace in a72_rows}
    a59_all = {row["ClaimID"] for row in a59_rows}
    actual_orphans = a59_all - in_matrix
    assert actual_orphans == declared, (
        f"A59 orphan set drifted. declared - actual = "
        f"{declared - actual_orphans}; actual - declared = "
        f"{actual_orphans - declared}"
    )


def test_expected_phase3_verdicts_present_in_marker_files(
    expectations: dict,
) -> None:
    """The phase3.* verdicts declared in expected_verdicts must each
    have a corresponding expected_markers/<marker_id>.json file with
    the matching verdict in its payload."""
    for marker_id, expected_verdict in expectations["expected_verdicts"].items():
        if not marker_id.startswith("phase3."):
            continue
        marker_path = EXPECTED_MARKERS / f"{marker_id}.json"
        assert marker_path.is_file(), (
            f"declared verdict for {marker_id} but no marker file at "
            f"{marker_path}"
        )
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
        assert payload["verdict"] == expected_verdict, (
            f"{marker_id} verdict drift: marker payload says "
            f"{payload['verdict']!r}; audit_expectations says "
            f"{expected_verdict!r}"
        )


# ---- 5. INV-09 / INV-10 / KPI-006 spot pins -------------------------


def test_inv_09_quantitative_nfrs_have_metric_and_target(
    a62_rows: list[dict],
) -> None:
    """INV-09 (Phase 3): every A62 row of category
    performance/availability/scalability MUST have non-empty
    Metric AND non-empty Target. (write_validator.
    _apply_measurability_rules enforces at hook time; this test
    asserts the fixture itself respects the invariant.)"""
    quantitative = {"performance", "availability", "scalability"}
    for nfr in a62_rows:
        if nfr["NFRCategory"] in quantitative:
            assert nfr["Metric"], f"NFR {nfr['NFRID']} ({nfr['NFRCategory']}) has empty Metric"
            assert nfr["Target"], f"NFR {nfr['NFRID']} ({nfr['NFRCategory']}) has empty Target"


def test_inv_10_every_a71_row_has_source_story_id(a71_rows: list[dict]) -> None:
    """INV-10: every A71 row carries a non-empty SourceStoryID.
    (Schema enforces via required + pattern; this test is a sanity
    pin against future schema relaxation.)"""
    for scenario in a71_rows:
        assert scenario["SourceStoryID"], (
            f"A71 scenario {scenario['ScenarioID']} has empty SourceStoryID — "
            f"violates INV-10"
        )


def test_kpi_006_story_to_claim_coverage_in_declared_bounds(
    expectations: dict, a70_rows: list[dict], a72_rows: list[dict]
) -> None:
    """KPI-006: |stories with at least one A72 row| / |stories|.
    Verify the live ratio falls within the bounds declared in
    audit_expectations.json (and that the declared `actual` matches
    the live computation)."""
    declared = expectations["expected_kpi_bounds"]["KPI-006_story_to_claim_coverage"]
    a72_story_ids = {trace["StoryID"] for trace in a72_rows}
    a70_story_ids = {row["StoryID"] for row in a70_rows}
    assert a70_story_ids, "fixture has zero stories — can't compute KPI-006"
    covered = a70_story_ids & a72_story_ids
    actual = len(covered) / len(a70_story_ids)
    assert declared["min"] <= actual <= declared["max"], (
        f"KPI-006 = {actual:.2f} out of bounds [{declared['min']}, {declared['max']}]"
    )
    assert abs(actual - declared["actual"]) < 0.01, (
        f"KPI-006 declared actual {declared['actual']} != live {actual:.2f}"
    )


# ---- 6. No-net-new-claims discipline (Codex round-1 finding) -------
# bsa-story-writer + bsa-test-scenario-builder are RESHAPE skills
# (per skills/bsa-story-writer/SKILL.md and INV-03 spirit) — they
# must NOT introduce subjects, verbs, conditions, or numeric
# specifics absent from upstream A59 / A62. The first US-S8-03 draft
# silently violated this by inventing "60 seconds" paging deadline,
# "non-empty repro-steps field" enforcement mechanism, "threshold X"
# / "ground-truth audit" / "candidate parent ticket" duplicate-
# detection details — all absent from any A59 claim or A62 NFR.
# This test set guards against such drift in the fixture itself.


import re

# Standalone numeric tokens — NOT IDs like C-003, STORY-001, A51-002,
# NFR-PERF-001, TS-001, TR-005. The (?<![-A-Z]) negative lookbehind
# excludes tokens that are part of a category-prefix-NNN identifier;
# the (?![-A-Z]) negative lookahead excludes those that prefix one.
_NUMERIC_TOKEN_RE = re.compile(r"(?<![-A-Z])\b\d+(?:\.\d+)?\b(?![-A-Z])")
# Tokens that are conventional / always allowed (HTTP status codes,
# percentages used for rate framing, etc.). NOT including domain-
# specific times / counts that need explicit upstream grounding.
_ALWAYS_ALLOWED_NUMERICS = frozenset({"0", "1", "2", "3", "100"})


def _upstream_text_corpus(
    a59_rows: list[dict], a62_rows: list[dict], a51_rows: list[dict] | None = None
) -> str:
    """Concatenated upstream text the Phase-3 fixture must stay grounded
    in: A59.Statement + A59.JustificationRationale + A62.Statement +
    A62.Metric + A62.Target + A62.TestabilityNotes + A51.NextAction
    if available. Whitespace-collapsed."""
    parts: list[str] = []
    for c in a59_rows:
        parts.append(c.get("Statement", ""))
        parts.append(c.get("JustificationRationale", ""))
    for n in a62_rows:
        parts.append(n.get("Statement", ""))
        parts.append(n.get("Metric", ""))
        parts.append(n.get("Target", ""))
        parts.append(n.get("TestabilityNotes", ""))
    if a51_rows:
        for r in a51_rows:
            parts.append(r.get("NextAction", ""))
    return " ".join(parts)


def _upstream_numeric_token_set(
    a59_rows: list[dict], a62_rows: list[dict], a51_rows: list[dict] | None = None
) -> set[str]:
    """Extract the SET of standalone numeric tokens from the upstream
    corpus using the same _NUMERIC_TOKEN_RE that examines downstream
    A70/A71. Round-2 fix: token-to-token comparison defeats the
    substring-membership false-positive (e.g., '24' would have
    falsely passed when upstream contained only '240' under raw
    `in corpus` substring check)."""
    corpus = _upstream_text_corpus(a59_rows, a62_rows, a51_rows)
    return set(_NUMERIC_TOKEN_RE.findall(corpus))


def _ungrounded_numeric_tokens(
    downstream_text: str, upstream_tokens: set[str]
) -> list[str]:
    """Return the list of numeric tokens in `downstream_text` that
    are NOT in the upstream token set (excluding the always-allowed
    set). Used by both the production grounding tests and the
    round-3 regression pin — single source of truth for the
    grounding semantic, so the pin test exercises the SAME code
    path the production tests exercise."""
    out: list[str] = []
    for token in _NUMERIC_TOKEN_RE.findall(downstream_text):
        if token in _ALWAYS_ALLOWED_NUMERICS:
            continue
        if token not in upstream_tokens:
            out.append(token)
    return out


@pytest.fixture(scope="module")
def a51_rows() -> list[dict]:
    return _read_csv(CORE_CONTROLS / "A51_issue_route_register.csv")


def test_a70_acceptance_criteria_numerics_grounded_in_upstream(
    a70_rows: list[dict],
    a59_rows: list[dict],
    a62_rows: list[dict],
    a51_rows: list[dict],
) -> None:
    """Codex round-1 finding (no-net-new-claims): every numeric token
    in A70.AcceptanceCriteria MUST appear AS A WHOLE TOKEN in the
    upstream A59/A62/A51 corpus (exempting trivial 0/1/2/3/100).
    Catches the Sprint 8 US-S8-03 drift where invented "60 seconds"
    / "100% of the time" slipped into the fixture.

    Round-2 fix: use token-set membership (not substring lookup)
    so '24' doesn't falsely pass when corpus contains only '240'.
    Round-3: routes through `_ungrounded_numeric_tokens` so the
    regression pin (`test_ungrounded_helper_rejects_substring_only`)
    exercises THE SAME function — a future reversion to substring
    matching would fail BOTH this test AND the pin."""
    upstream_tokens = _upstream_numeric_token_set(a59_rows, a62_rows, a51_rows)
    for story in a70_rows:
        ungrounded = _ungrounded_numeric_tokens(
            story["AcceptanceCriteria"], upstream_tokens
        )
        assert not ungrounded, (
            f"A70 row {story['StoryID']} AcceptanceCriteria carries "
            f"numeric token(s) {ungrounded!r} not present in upstream "
            f"A59/A62/A51 token set. The bsa-story-writer contract "
            f"forbids inventing new conditions/numbers; either ground "
            f"the token(s) in upstream (or in an A51 route) or remove "
            f"them from the acceptance criterion. Upstream token set: "
            f"{sorted(upstream_tokens)}"
        )


def test_a71_then_clause_numerics_grounded_in_upstream(
    a71_rows: list[dict],
    a59_rows: list[dict],
    a62_rows: list[dict],
    a51_rows: list[dict],
) -> None:
    """Same anti-drift discipline applied to A71.Then-clauses.
    bsa-test-scenario-builder is also a reshape skill; the Then-
    clause MUST NOT introduce numeric specifics absent from
    upstream. NB: the NFR-coverage rule (TS-001 contains the
    literal Target string from NFR-PERF-001 which is itself in
    upstream A62) is naturally satisfied by this token-set check.

    Round-2 fix: token-set membership (not substring).
    Round-3: routes through `_ungrounded_numeric_tokens` (shared
    with the A70 grounding test + the regression pin)."""
    upstream_tokens = _upstream_numeric_token_set(a59_rows, a62_rows, a51_rows)
    for scenario in a71_rows:
        ungrounded = _ungrounded_numeric_tokens(scenario["Then"], upstream_tokens)
        assert not ungrounded, (
            f"A71 row {scenario['ScenarioID']} Then-clause carries "
            f"numeric token(s) {ungrounded!r} not present in upstream "
            f"A59/A62/A51 token set. The bsa-test-scenario-builder "
            f"contract forbids inventing new conditions/numbers; either "
            f"ground the token(s) in upstream (typically the linked NFR's "
            f"Target) or remove them from the Then-clause. Upstream "
            f"token set: {sorted(upstream_tokens)}"
        )


def test_ungrounded_helper_rejects_substring_only() -> None:
    """Round-3 pin: exercise the SAME helper the production grounding
    tests use (`_ungrounded_numeric_tokens`) with a synthetic case
    that distinguishes substring-vs-token semantics. Constructed so
    a future reversion to substring matching (e.g., `assert token in
    corpus_string`) would FAIL this pin in addition to the production
    tests — single source of truth.

    Synthetic input:
      - Upstream token set: {'240'}
      - Downstream text: 'within 24 minutes' (token '24' is a
        substring of '240' but NOT a whole-token member of the
        upstream set).
      - Correct (token-set) behavior: '24' is reported as ungrounded.
      - Buggy (substring) behavior: '24' would be considered grounded
        because '24' appears inside '240' in the corpus string.
    """
    upstream_tokens = {"240"}
    downstream = "within 24 minutes of arrival"
    ungrounded = _ungrounded_numeric_tokens(downstream, upstream_tokens)
    assert ungrounded == ["24"], (
        f"_ungrounded_numeric_tokens regressed to substring semantics: "
        f"expected ['24'] (the synthetic prefix that should NOT be "
        f"grounded by '240'), got {ungrounded!r}. A revert to "
        f"`token in corpus_string` would silently false-pass this case."
    )

    # Conversely, a true whole-token match should be grounded:
    grounded_text = "within 240 minutes of arrival"
    ungrounded2 = _ungrounded_numeric_tokens(grounded_text, upstream_tokens)
    assert ungrounded2 == [], (
        f"_ungrounded_numeric_tokens incorrectly rejected the grounded "
        f"token '240': got {ungrounded2!r}"
    )

    # Always-allowed tokens are exempt regardless of upstream:
    allowed_text = "exactly 1 retry within 100% of cases (0 failures)"
    ungrounded3 = _ungrounded_numeric_tokens(allowed_text, upstream_tokens)
    assert ungrounded3 == [], (
        f"_ungrounded_numeric_tokens did not exempt the always-allowed "
        f"set {{0,1,2,3,100}}: got {ungrounded3!r}"
    )


def test_a70_a71_no_invented_mechanism_keywords(
    a70_rows: list[dict], a71_rows: list[dict]
) -> None:
    """Lexical pin against specific Codex-flagged phrases that
    represent invented MECHANISMS (vs evidence-grounded outcomes):
    'threshold X', 'ground-truth audit', 'candidate parent ticket'.
    Catches future drift toward LLM-style elaboration that has no
    source in the fixture. List is small + curated — extend when
    new drift classes surface."""
    banned = (
        "threshold X",
        "ground-truth audit",
        "candidate parent ticket",
        "non-empty repro-steps",
        "100% of the time",
    )
    for story in a70_rows:
        text = story["AcceptanceCriteria"] + " " + story["StoryText"]
        for phrase in banned:
            assert phrase not in text, (
                f"A70 {story['StoryID']} contains banned drift phrase "
                f"{phrase!r} (invented mechanism not in upstream). "
                f"See US-S8-03 round-1 Codex finding."
            )
    for scenario in a71_rows:
        text = " ".join(
            (scenario.get("Given", ""), scenario.get("When", ""), scenario.get("Then", ""))
        )
        for phrase in banned:
            assert phrase not in text, (
                f"A71 {scenario['ScenarioID']} contains banned drift phrase "
                f"{phrase!r} (invented mechanism not in upstream). "
                f"See US-S8-03 round-1 Codex finding."
            )


# ---- 7. NFR-coverage rule (documentary) — fixture sanity -----------


def test_a71_nfr_bound_scenario_then_clause_references_target(
    a71_rows: list[dict], a62_rows: list[dict]
) -> None:
    """x-bsa-nfr-coverage-rules (documentary at schema layer): when
    A71 RelatedNFRID is non-empty, the Then-clause MUST reference
    the NFR's Metric (paraphrase OK) AND contain the literal Target
    string from A62. Skill-level enforcement; this test asserts
    the fixture ITSELF respects the rule (so the fixture is a
    valid template for downstream consumers)."""
    by_nfr = {row["NFRID"]: row for row in a62_rows}
    for scenario in a71_rows:
        nid = scenario["RelatedNFRID"]
        if not nid:
            continue
        nfr = by_nfr.get(nid)
        assert nfr is not None, (
            f"A71 scenario {scenario['ScenarioID']} references NFR {nid!r} "
            f"that doesn't exist in A62"
        )
        target = nfr["Target"]
        if not target:
            # Qualitative NFRs may have empty Target — skip the check.
            continue
        then_clause = scenario["Then"]
        assert target in then_clause, (
            f"A71 scenario {scenario['ScenarioID']} (NFR {nid}) Then-clause "
            f"does not contain the literal Target {target!r}. Then-clause: "
            f"{then_clause!r}"
        )
