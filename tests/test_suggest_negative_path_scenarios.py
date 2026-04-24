"""Tests for `scripts/suggest_negative_path_scenarios.py` (v1.2.5, T4).

Pins the contract documented in the script + skill TODO closure:

  * Three pattern classes detected: temporal / boundary / comparison.
  * Each class produces a deterministic suggestion string.
  * Patterns don't double-match overlapping spans (e.g., "no more
    than N" must NOT also match COMPARISON's "more than N").
  * A70 with no measurable language → 0 suggestions, clean report.
  * Multi-pattern story (e.g., one criterion with both temporal
    AND boundary) → both suggestions emitted, source order preserved.
  * Header validation: missing required column → exit 2.
  * CLI: missing workspace / missing A70 / `--json` / `--print-only`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "suggest_negative_path_scenarios.py"
SAMPLE_FIXTURE = REPO_ROOT / "fixtures/golden/project_0001/expected_outputs/canonical/core_controls/A70_story_register.csv"


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location("suggest_negative_path_scenarios", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_workspace(tmp_path: Path, a70_body: str | None = None) -> Path:
    target = tmp_path / "analysis/canonical/core_controls"
    target.mkdir(parents=True, exist_ok=True)
    a70 = target / "A70_story_register.csv"
    if a70_body is None:
        a70.write_text(SAMPLE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        a70.write_text(a70_body, encoding="utf-8")
    return tmp_path


# ---- detect_patterns: TEMPORAL ------------------------------------


def test_detect_temporal_within_seconds(helper) -> None:
    matches = helper.detect_patterns("Initial response within 240 seconds")
    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_class == "temporal"
    assert m.quantity == "240"
    assert m.unit.startswith("second")
    assert "240" in m.suggestion


def test_detect_temporal_within_minutes(helper) -> None:
    matches = helper.detect_patterns("escalation within 60 minutes")
    assert len(matches) == 1
    assert matches[0].pattern_class == "temporal"
    assert matches[0].quantity == "60"
    assert "minute" in matches[0].unit.lower()


def test_detect_temporal_business_days(helper) -> None:
    matches = helper.detect_patterns("response within 2 business days")
    assert len(matches) == 1
    assert matches[0].pattern_class == "temporal"
    assert matches[0].quantity == "2"
    assert "business" in matches[0].unit.lower()


def test_detect_temporal_short_unit_aliases(helper) -> None:
    """`m` and `h` and `s` and `ms` short forms must match too."""
    matches = helper.detect_patterns("page within 30 s")
    assert len(matches) == 1
    assert matches[0].quantity == "30"


# ---- detect_patterns: BOUNDARY ------------------------------------


def test_detect_boundary_at_least(helper) -> None:
    matches = helper.detect_patterns("at least 3 retries before alert")
    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_class == "boundary"
    assert m.quantity == "3"
    assert "boundary" in m.suggestion.lower() or "at-least" in m.suggestion.lower()


def test_detect_boundary_at_most(helper) -> None:
    matches = helper.detect_patterns("at most 100 records returned")
    assert len(matches) == 1
    assert matches[0].pattern_class == "boundary"
    assert matches[0].quantity == "100"


def test_detect_boundary_exactly(helper) -> None:
    matches = helper.detect_patterns("exactly 5 approval signatures required")
    assert len(matches) == 1
    assert matches[0].pattern_class == "boundary"
    assert "exactly" in matches[0].suggestion.lower()


def test_detect_boundary_no_more_than_does_not_double_match(helper) -> None:
    """v1.2.5 design pin: 'no more than N' MUST match BOUNDARY only —
    NOT also COMPARISON's 'more than N' substring. Without the
    seen_spans guard this would emit 2 false matches."""
    matches = helper.detect_patterns("no more than 50 retries allowed")
    classes = [m.pattern_class for m in matches]
    assert classes == ["boundary"], (
        f"expected only boundary; got {classes}. seen_spans guard failed?"
    )


def test_detect_boundary_no_fewer_than_does_not_double_match(helper) -> None:
    """Same anti-double-match for 'no fewer than N' (must not also
    trigger COMPARISON's 'fewer than N')."""
    matches = helper.detect_patterns("no fewer than 3 reviewers")
    classes = [m.pattern_class for m in matches]
    assert classes == ["boundary"]


def test_detect_boundary_both_no_more_and_no_fewer_in_one_cell(helper) -> None:
    """v1.2.5 round-1 Codex regression: a single AC cell containing BOTH
    'no more than N' AND 'no fewer than M' must yield exactly two
    BOUNDARY matches and ZERO COMPARISON matches — i.e., neither
    embedded `more than N` nor `fewer than M` may leak through."""
    text = "no more than 50 retries AND no fewer than 3 reviewers"
    matches = helper.detect_patterns(text)
    classes = [m.pattern_class for m in matches]
    assert classes == ["boundary", "boundary"], (
        f"expected exactly two boundaries; got {classes}. "
        f"Multi-phrase overlap guard failed?"
    )
    qtys = sorted(m.quantity for m in matches)
    assert qtys == ["3", "50"]


# ---- Decimal-boundary off-by-one (Codex round-1 regression) -------


def test_detect_boundary_decimal_at_least(helper) -> None:
    """v1.2.5 round-1 Codex regression: 'at least 99.9' must NOT
    suggest 98 as the just-below example (which `int(float(qty))-1`
    would produce). Decimal-shaped qty → symbolic ε."""
    matches = helper.detect_patterns("uptime at least 99.9 percent")
    assert len(matches) == 1
    suggestion = matches[0].suggestion
    assert "98" not in suggestion, (
        f"int-truncation bug: suggestion contains '98' for qty=99.9. "
        f"Got: {suggestion}"
    )
    assert "99.9" in suggestion
    # Symbolic ε is the chosen render — exact glyph U+03B5.
    assert "\u03b5" in suggestion


def test_detect_boundary_decimal_at_most(helper) -> None:
    matches = helper.detect_patterns("response time at most 0.5 seconds")
    assert len(matches) == 1
    suggestion = matches[0].suggestion
    assert "1" not in suggestion.split("→")[1] if "→" in suggestion else True
    # More precise: the "+1" arithmetic would yield "1" — make sure
    # we did NOT emit the integer 1 as the just-above example.
    assert "0.5 + \u03b5" in suggestion or "0.5+\u03b5" in suggestion
    assert "0.5" in suggestion


def test_detect_boundary_integer_still_uses_arithmetic(helper) -> None:
    """Integer-shaped qty MUST keep the literal arithmetic example
    (don't regress integers to symbolic ε just because we fixed
    the decimal case)."""
    matches = helper.detect_patterns("at least 5 retries")
    assert len(matches) == 1
    assert "4" in matches[0].suggestion  # 5 - 1
    assert "\u03b5" not in matches[0].suggestion


def test_detect_boundary_exactly_decimal(helper) -> None:
    """`exactly 0.5` must emit BOTH N-ε and N+ε symbolic — never the
    integer-rounded 0 / 1 that a naive int() cast would produce."""
    matches = helper.detect_patterns("exactly 0.5 quota allocation")
    assert len(matches) == 1
    suggestion = matches[0].suggestion
    assert "\u03b5" in suggestion
    # Both directions must be visible in the suggestion text.
    assert "0.5 - \u03b5" in suggestion or "0.5-\u03b5" in suggestion
    assert "0.5 + \u03b5" in suggestion or "0.5+\u03b5" in suggestion


def test_off_by_one_large_integer_keeps_precision(helper) -> None:
    """v1.2.5 round-2 Codex regression: an earlier `int(float(qty))`
    integer-shape check silently lost precision past 2**53. The
    fix detects integer shape lexically (regex), so arbitrarily-large
    quantities round-trip exactly through `int()`.

    Spot value: 2**53 + 1 = 9007199254740993 (the smallest integer
    where IEEE 754 double precision starts rounding). Pre-fix this
    yielded `9007199254740991` (= 2**53 - 1) for just-below;
    post-fix MUST yield `9007199254740992` (= 2**53)."""
    big = 2 ** 53 + 1  # 9007199254740993
    matches = helper.detect_patterns(f"at least {big} attempts")
    assert len(matches) == 1
    suggestion = matches[0].suggestion
    expected_just_below = str(big - 1)  # 9007199254740992
    assert expected_just_below in suggestion, (
        f"large-int precision loss: expected '{expected_just_below}' "
        f"in suggestion but got: {suggestion}"
    )
    # And NOT the buggy `2**53 - 1` value the float path would have produced.
    bug_value = str(2 ** 53 - 1)  # 9007199254740991
    assert bug_value not in suggestion, (
        f"float round-trip bug regressed: '{bug_value}' appeared in "
        f"suggestion: {suggestion}"
    )


def test_off_by_one_int_with_trailing_zero_decimal(helper) -> None:
    """`5.0` / `100.000` are integer-shaped — must use arithmetic,
    not symbolic ε."""
    # Pattern detector requires quantity in regex form `\d+(?:\.\d+)?`,
    # so `5.0` is a legal capture; `_off_by_one()` must recognise it
    # as integer-shaped.
    matches = helper.detect_patterns("at least 5.0 retries")
    assert len(matches) == 1
    suggestion = matches[0].suggestion
    assert "4" in suggestion  # 5 - 1
    assert "\u03b5" not in suggestion


# ---- detect_patterns: COMPARISON ----------------------------------


def test_detect_comparison_more_than(helper) -> None:
    matches = helper.detect_patterns("more than 10 errors per hour")
    assert len(matches) == 1
    assert matches[0].pattern_class == "comparison"
    assert matches[0].quantity == "10"


def test_detect_comparison_symbolic(helper) -> None:
    matches = helper.detect_patterns("uptime >= 99.9 percent")
    assert len(matches) == 1
    assert matches[0].pattern_class == "comparison"
    assert matches[0].quantity == "99.9"


def test_detect_comparison_unicode_symbols(helper) -> None:
    """Unicode ≥ ≤ symbols must match too."""
    matches = helper.detect_patterns("score ≥ 80")
    assert len(matches) == 1
    assert matches[0].pattern_class == "comparison"
    assert matches[0].quantity == "80"


# ---- Multi-pattern + ordering -------------------------------------


def test_multi_pattern_in_one_criterion(helper) -> None:
    """One criterion with both temporal AND boundary phrases →
    both emitted, source order preserved."""
    text = "deliver within 60 minutes AND at least 3 retries"
    matches = helper.detect_patterns(text)
    assert len(matches) == 2
    classes = [m.pattern_class for m in matches]
    assert "temporal" in classes
    assert "boundary" in classes


def test_no_measurable_language_returns_zero_matches(helper) -> None:
    matches = helper.detect_patterns("user-friendly login flow with intuitive UX")
    assert matches == []


# ---- A70 parsing + report -----------------------------------------


def test_read_a70_real_fixture(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    stories, errors = helper._read_a70(workspace / helper.A70_REL)
    assert not errors
    assert len(stories) >= 1
    # Real fixture STORY-001 has "within 4 hours" temporal pattern.
    story_001 = next(s for s in stories if s.story_id == "STORY-001")
    assert any(m.pattern_class == "temporal" for m in story_001.matches)


def test_read_a70_missing_required_column_returns_error(helper, tmp_path) -> None:
    csv_body = (
        "StoryID,Title\n"  # missing AcceptanceCriteria
        "STORY-001,Test\n"
    )
    workspace = _make_workspace(tmp_path, csv_body)
    stories, errors = helper._read_a70(workspace / helper.A70_REL)
    assert not stories
    assert any("AcceptanceCriteria" in e for e in errors)


def test_read_a70_blank_required_cell_returns_error(helper, tmp_path) -> None:
    """v1.2.5 round-1 Codex regression: stripped-empty required cell
    is fail-CLOSED, not silently dropped."""
    csv_body = (
        "StoryID,Title,AcceptanceCriteria\n"
        "STORY-001,Login,within 60 seconds\n"
        "STORY-002,,response within 5 minutes\n"  # blank Title
        "  ,Some Title,Some AC\n"  # whitespace-only StoryID
        ",,\n"  # all blank
    )
    workspace = _make_workspace(tmp_path, csv_body)
    stories, errors = helper._read_a70(workspace / helper.A70_REL)
    # Only STORY-001 survives.
    assert len(stories) == 1
    assert stories[0].story_id == "STORY-001"
    # Three error lines for the three malformed rows.
    blank_errs = [e for e in errors if "blank required cell" in e]
    assert len(blank_errs) == 3, (
        f"expected 3 blank-cell errors; got {len(blank_errs)}: {errors}"
    )


def test_read_a70_extra_field_overflow_returns_error(helper, tmp_path) -> None:
    """v1.2.5 round-1 Codex regression: a row with MORE cells than
    columns (unescaped comma) is fail-CLOSED, not silently dropped.
    Same overflow guard as a71_runnable_export.py."""
    csv_body = (
        "StoryID,Title,AcceptanceCriteria\n"
        # Extra cell — mimics an unescaped comma in AC text.
        "STORY-001,Login,within 60 seconds,unexpected-overflow\n"
        # Sane row should still be ingested.
        "STORY-002,Logout,at most 100 sessions\n"
    )
    workspace = _make_workspace(tmp_path, csv_body)
    stories, errors = helper._read_a70(workspace / helper.A70_REL)
    assert len(stories) == 1
    assert stories[0].story_id == "STORY-002"
    overflow_errs = [e for e in errors if "extra cell" in e]
    assert len(overflow_errs) == 1


def test_format_markdown_escapes_inline_specials(helper) -> None:
    """v1.2.5 round-1 Codex recommendation: backticks / pipes / HTML
    in AC text must be escaped so the report stays well-formed."""
    story = helper.StorySuggestion(
        story_id="STORY-001",
        title="Login `flow` <strong>",
        acceptance_criteria="must respond within 60 seconds | <script>alert(1)</script>",
        matches=helper.detect_patterns(
            "must respond within 60 seconds | <script>alert(1)</script>"
        ),
    )
    body = helper.format_markdown_report([story])
    # The raw HTML/markdown metacharacters must NOT appear unescaped.
    assert "<script>" not in body
    assert "<strong>" not in body
    # And the escaped form must appear.
    assert "\\<script\\>" in body or "\\<" in body
    # The literal backtick from the title must be escaped.
    assert "\\`flow\\`" in body or "\\`" in body


def test_format_markdown_report_includes_summary_and_per_story(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    stories, _ = helper._read_a70(workspace / helper.A70_REL)
    body = helper.format_markdown_report(stories)
    assert "Negative-Path Scenario Suggestions" in body
    assert "Stories scanned:" in body
    assert "STORY-001" in body
    assert "TEMPORAL" in body  # uppercase per format


def test_format_markdown_no_matches_says_so_explicitly(helper) -> None:
    """When zero stories have measurable language, the report MUST
    still produce a clean summary + a clear 'no matches' note (not
    a half-rendered dangling section header)."""
    body = helper.format_markdown_report([])
    assert "Stories scanned: **0**" in body
    assert "No measurable language detected" in body


def test_format_json_report_is_machine_readable(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    stories, _ = helper._read_a70(workspace / helper.A70_REL)
    body = helper.format_json_report(stories)
    parsed = json.loads(body)
    assert "stories_scanned" in parsed
    assert "stories" in parsed
    assert isinstance(parsed["stories"], list)
    if parsed["stories"]:
        first = parsed["stories"][0]
        assert "story_id" in first
        assert "matches" in first


# ---- CLI -------------------------------------------------------------


def test_main_returns_2_on_missing_workspace(helper, tmp_path) -> None:
    rc = helper.main(["--workspace", str(tmp_path / "absent")])
    assert rc == 2


def test_main_returns_2_on_missing_a70(helper, tmp_path) -> None:
    (tmp_path / "analysis").mkdir()
    rc = helper.main(["--workspace", str(tmp_path)])
    assert rc == 2


def test_main_writes_default_output_path(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    rc = helper.main(["--workspace", str(workspace), "--quiet"])
    assert rc == 0
    target = workspace / helper.DEFAULT_OUTPUT_REL
    assert target.is_file()
    body = target.read_text(encoding="utf-8")
    assert "Negative-Path" in body


def test_main_print_only_does_not_write(helper, tmp_path, capsys) -> None:
    workspace = _make_workspace(tmp_path)
    rc = helper.main(["--workspace", str(workspace), "--print-only"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Negative-Path" in out
    target = workspace / helper.DEFAULT_OUTPUT_REL
    assert not target.exists()


def test_main_json_flag_emits_json(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    rc = helper.main([
        "--workspace", str(workspace), "--json", "--quiet",
    ])
    assert rc == 0
    target = workspace / helper.DEFAULT_OUTPUT_REL
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert "stories_scanned" in parsed
