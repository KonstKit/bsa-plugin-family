"""Tests for `scripts/compare_doctor_outputs.py` (v1.1.15, Section K prep).

Pins the contract documented in `docs/pilot_2nd_pass_runbook.md`:

  * `parse_doctor_output()` correctly handles the 4 status types
    (OK / FAIL / ERROR / SKIP) + multi-line detail bodies + trailing
    content on the status line itself (e.g., "(3 of 22 files)").
  * `compare()` correctly classifies all 7 deltas:
    - CLOSED (FAIL→OK)
    - NEW (OK→FAIL — REGRESSION)
    - PERSISTED (FAIL→FAIL with no detail change)
    - CHANGED (FAIL→FAIL with detail change — partial progress)
    - STILL_OK (OK→OK)
    - DROPPED (only in pre)
    - ADDED (only in post)
  * Exit code 1 fires when at least one section is NEW (regression).
  * The CLI smokes end-to-end against tiny captured outputs.
  * Reporters (text + JSON) produce non-empty output of the right shape.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "compare_doctor_outputs.py"


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location("compare_doctor_outputs", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- Parser ---------------------------------------------------------


def test_parse_simple_ok(helper) -> None:
    body = "  privacy scan: OK\n"
    parsed = helper.parse_doctor_output(body)
    assert "privacy scan" in parsed
    assert parsed["privacy scan"].status == "OK"
    assert parsed["privacy scan"].detail == ""


def test_parse_fail_with_detail_lines(helper) -> None:
    body = (
        "  marker chain (main): FAIL\n"
        "      marker[0]: missing required field 'verdict'\n"
        "      marker[1]: missing required field 'canon_policy_version'\n"
    )
    parsed = helper.parse_doctor_output(body)
    section = parsed["marker chain (main)"]
    assert section.status == "FAIL"
    assert "missing required field 'verdict'" in section.detail
    assert "missing required field 'canon_policy_version'" in section.detail


def test_parse_fail_with_trailing_count_on_status_line(helper) -> None:
    """v1.1.15 bug-fix: trailing content on the status line MUST land
    in `detail` so a pre→post finding-count change is classified
    CHANGED, not PERSISTED."""
    body = "  content validation: FAIL (3 of 22 files)\n"
    parsed = helper.parse_doctor_output(body)
    assert parsed["content validation"].detail == "(3 of 22 files)"


def test_parse_skip_with_reason(helper) -> None:
    body = "  no-new-stories: SKIP (no A70 yet — Phase 3 not run)\n"
    parsed = helper.parse_doctor_output(body)
    assert parsed["no-new-stories"].status == "SKIP"
    assert "no A70" in parsed["no-new-stories"].detail


def test_parse_error_invocation_failed(helper) -> None:
    body = (
        "  fixture-runner: ERROR (validator invocation failed)\n"
        "      ImportError: missing yaml\n"
    )
    parsed = helper.parse_doctor_output(body)
    section = parsed["fixture-runner"]
    assert section.status == "ERROR"
    assert "ImportError" in section.detail


def test_parse_skips_non_section_lines(helper) -> None:
    """Header lines, blank lines, summary lines must NOT be treated as
    sections."""
    body = (
        "[bsa doctor] /tmp/pilot1\n"
        "\n"
        "  privacy scan: OK\n"
        "\n"
        "doctor: 1 finding(s) total.\n"
    )
    parsed = helper.parse_doctor_output(body)
    assert set(parsed.keys()) == {"privacy scan"}


def test_parse_empty_input_returns_empty(helper) -> None:
    assert helper.parse_doctor_output("") == {}


# ---- Compare classifications ----------------------------------------


def _section(helper, label: str, status: str, detail: str = "") -> "object":
    return helper.Section(label=label, status=status, detail=detail)


def test_compare_closed_fail_to_ok(helper) -> None:
    pre = {"x": _section(helper, "x", "FAIL", "5 findings")}
    post = {"x": _section(helper, "x", "OK", "")}
    deltas = helper.compare(pre, post)
    assert len(deltas) == 1
    assert deltas[0].classification == "CLOSED"


def test_compare_new_ok_to_fail_is_regression(helper) -> None:
    """The headline "did the migration regress anything" check."""
    pre = {"x": _section(helper, "x", "OK", "")}
    post = {"x": _section(helper, "x", "FAIL", "new finding")}
    deltas = helper.compare(pre, post)
    assert deltas[0].classification == "NEW"


def test_compare_persisted_no_progress(helper) -> None:
    """Same status, same detail → PERSISTED (operator made no
    progress on this section)."""
    pre = {"x": _section(helper, "x", "FAIL", "same details")}
    post = {"x": _section(helper, "x", "FAIL", "same details")}
    deltas = helper.compare(pre, post)
    assert deltas[0].classification == "PERSISTED"


def test_compare_changed_partial_progress(helper) -> None:
    """Same status but detail changed → CHANGED (e.g., went from
    21/22 to 3/22 files — partial progress, still failing)."""
    pre = {"x": _section(helper, "x", "FAIL", "21 of 22 files")}
    post = {"x": _section(helper, "x", "FAIL", "3 of 22 files")}
    deltas = helper.compare(pre, post)
    assert deltas[0].classification == "CHANGED"
    assert deltas[0].detail_changed is True


def test_compare_changed_status_swap(helper) -> None:
    """FAIL → ERROR (or vice versa) is also CHANGED — same problem
    bucket but the validator outcome shifted."""
    pre = {"x": _section(helper, "x", "FAIL", "")}
    post = {"x": _section(helper, "x", "ERROR", "")}
    deltas = helper.compare(pre, post)
    assert deltas[0].classification == "CHANGED"


def test_compare_still_ok(helper) -> None:
    pre = {"x": _section(helper, "x", "OK", "")}
    post = {"x": _section(helper, "x", "OK", "")}
    deltas = helper.compare(pre, post)
    assert deltas[0].classification == "STILL_OK"


def test_compare_still_ok_includes_skip(helper) -> None:
    """SKIP→SKIP is also STILL_OK (both are non-problem statuses)."""
    pre = {"x": _section(helper, "x", "SKIP", "no A70")}
    post = {"x": _section(helper, "x", "SKIP", "no A70")}
    deltas = helper.compare(pre, post)
    assert deltas[0].classification == "STILL_OK"


def test_compare_dropped_section_only_in_pre(helper) -> None:
    pre = {"x": _section(helper, "x", "OK", "")}
    post: dict = {}
    deltas = helper.compare(pre, post)
    assert deltas[0].classification == "DROPPED"
    assert deltas[0].pre_status == "OK"
    assert deltas[0].post_status is None


def test_compare_added_section_only_in_post(helper) -> None:
    pre: dict = {}
    post = {"x": _section(helper, "x", "OK", "")}
    deltas = helper.compare(pre, post)
    assert deltas[0].classification == "ADDED"
    assert deltas[0].pre_status is None
    assert deltas[0].post_status == "OK"


def test_compare_returns_sorted_by_label(helper) -> None:
    pre = {
        "z": _section(helper, "z", "OK", ""),
        "a": _section(helper, "a", "OK", ""),
    }
    post = {
        "z": _section(helper, "z", "OK", ""),
        "a": _section(helper, "a", "OK", ""),
    }
    deltas = helper.compare(pre, post)
    assert [d.label for d in deltas] == ["a", "z"]


# ---- Report formatting ----------------------------------------------


def test_text_report_includes_summary_and_attention(helper) -> None:
    pre = {
        "alpha": _section(helper, "alpha", "FAIL", "f1"),  # CLOSED
        "beta": _section(helper, "beta", "OK", ""),        # NEW
        "gamma": _section(helper, "gamma", "FAIL", "g"),   # PERSISTED
    }
    post = {
        "alpha": _section(helper, "alpha", "OK", ""),
        "beta": _section(helper, "beta", "FAIL", "regression!"),
        "gamma": _section(helper, "gamma", "FAIL", "g"),
    }
    deltas = helper.compare(pre, post)
    report = helper.format_text_report(deltas)
    assert "Doctor output comparison (3 sections)" in report
    assert "## Summary" in report
    assert "CLOSED" in report
    assert "NEW" in report
    assert "PERSISTED" in report
    assert "## Sections needing attention" in report
    assert "[NEW] beta" in report
    assert "## Sections closed by the migration" in report
    assert "[CLOSED] alpha" in report


def test_json_report_is_machine_readable(helper) -> None:
    pre = {"x": _section(helper, "x", "FAIL", "")}
    post = {"x": _section(helper, "x", "OK", "")}
    deltas = helper.compare(pre, post)
    body = helper.format_json_report(deltas)
    parsed = json.loads(body)
    assert isinstance(parsed, list)
    assert parsed[0]["label"] == "x"
    assert parsed[0]["classification"] == "CLOSED"
    assert parsed[0]["pre_status"] == "FAIL"
    assert parsed[0]["post_status"] == "OK"


# ---- CLI ------------------------------------------------------------


def test_main_returns_0_on_clean_progress(helper, tmp_path) -> None:
    pre = tmp_path / "pre.txt"
    post = tmp_path / "post.txt"
    pre.write_text("  privacy scan: FAIL\n      bad token\n", encoding="utf-8")
    post.write_text("  privacy scan: OK\n", encoding="utf-8")
    rc = helper.main([str(pre), str(post)])
    assert rc == 0


def test_main_returns_1_on_regression(helper, tmp_path, capsys) -> None:
    """The headline contract: any NEW section means exit 1, alerting
    the operator BEFORE they declare the migration successful."""
    pre = tmp_path / "pre.txt"
    post = tmp_path / "post.txt"
    pre.write_text("  privacy scan: OK\n", encoding="utf-8")
    post.write_text("  privacy scan: FAIL\n      bad token leaked\n", encoding="utf-8")
    rc = helper.main([str(pre), str(post)])
    assert rc == 1


def test_main_returns_2_on_missing_file(helper, tmp_path) -> None:
    pre = tmp_path / "pre.txt"
    pre.write_text("  privacy scan: OK\n", encoding="utf-8")
    missing = tmp_path / "absent.txt"
    rc = helper.main([str(pre), str(missing)])
    assert rc == 2


def test_main_returns_2_on_unrecognisable_input(helper, tmp_path) -> None:
    """Catches the case where the operator captures the wrong thing
    (e.g., the doctor command line, or a totally unrelated file)."""
    pre = tmp_path / "pre.txt"
    post = tmp_path / "post.txt"
    pre.write_text("just some random text\n", encoding="utf-8")
    post.write_text("more random text\n", encoding="utf-8")
    rc = helper.main([str(pre), str(post)])
    assert rc == 2


def test_main_returns_2_when_only_one_side_is_malformed(helper, tmp_path) -> None:
    """v1.1.15 round-1 (Codex): previously exit 2 fired only when BOTH
    sides parsed empty. If exactly one side was malformed, the helper
    silently reported everything as DROPPED/ADDED, actively misleading
    the operator. Now either empty side → exit 2."""
    pre = tmp_path / "pre.txt"
    post = tmp_path / "post.txt"
    pre.write_text("  privacy scan: OK\n", encoding="utf-8")
    post.write_text("not a doctor output\n", encoding="utf-8")
    rc = helper.main([str(pre), str(post)])
    assert rc == 2
    # Also the reverse: malformed pre + healthy post.
    pre.write_text("garbage\n", encoding="utf-8")
    post.write_text("  privacy scan: OK\n", encoding="utf-8")
    rc = helper.main([str(pre), str(post)])
    assert rc == 2


def test_parse_content_validation_block_preserves_file_list(helper) -> None:
    """v1.1.15 round-1 (Codex): the `content validation` section uses a
    specific 4-space + 8-space indent form (per scripts/bsa_cli.py:929-931),
    not the standard 6-space _indent_detail() form. The parser must
    collect those nested lines so a pre→post file-count change (e.g.,
    21/22 → 3/22) with same per-file error body becomes CHANGED, not
    PERSISTED. The round-1 bug would have silently collapsed real
    progress into PERSISTED and told the operator 'migration didn't
    fix it' when it did."""
    body = (
        "  content validation: FAIL (3 of 22 files flagged)\n"
        "    - [FAIL]  analysis/canonical/core_controls/A59_claim_register.csv\n"
        "        row 5: missing required field 'Criticality'\n"
        "    - [FAIL]  analysis/canonical/core_controls/A51_issue_route_register.csv\n"
        "        row 2: ResolutionStatus out of enum\n"
    )
    parsed = helper.parse_doctor_output(body)
    assert "content validation" in parsed
    section = parsed["content validation"]
    assert section.status == "FAIL"
    # The count AND all file/error lines must land in detail.
    assert "(3 of 22 files flagged)" in section.detail
    assert "A59_claim_register.csv" in section.detail
    assert "A51_issue_route_register.csv" in section.detail
    assert "Criticality" in section.detail
    assert "ResolutionStatus" in section.detail


def test_content_validation_count_change_classifies_as_CHANGED(helper) -> None:
    """Round-1 Codex: file-count shifts across the content-validation
    block must surface as CHANGED (partial progress), not PERSISTED.
    Pinned with the same kind of fake blocks the operator would see."""
    pre_body = (
        "  content validation: FAIL (21 of 22 files flagged)\n"
        "    - [FAIL]  analysis/canonical/core_controls/A50_source_register.csv\n"
        "        row 1: enum drift\n"
    )
    post_body = (
        "  content validation: FAIL (3 of 22 files flagged)\n"
        "    - [FAIL]  analysis/canonical/core_controls/A50_source_register.csv\n"
        "        row 1: enum drift\n"
    )
    pre = helper.parse_doctor_output(pre_body)
    post = helper.parse_doctor_output(post_body)
    deltas = helper.compare(pre, post)
    assert len(deltas) == 1
    assert deltas[0].label == "content validation"
    assert deltas[0].classification == "CHANGED", (
        f"expected CHANGED (partial progress — 21/22 → 3/22) but got "
        f"{deltas[0].classification}. The round-1 parser ignored the "
        f"4-space + 8-space block form and collapsed this into "
        f"PERSISTED."
    )


def test_main_json_flag_emits_json(helper, tmp_path, capsys) -> None:
    pre = tmp_path / "pre.txt"
    post = tmp_path / "post.txt"
    pre.write_text("  privacy scan: FAIL\n", encoding="utf-8")
    post.write_text("  privacy scan: OK\n", encoding="utf-8")
    helper.main([str(pre), str(post), "--json"])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed[0]["classification"] == "CLOSED"
