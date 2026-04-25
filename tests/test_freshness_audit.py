"""Tests for `scripts/freshness_audit.py` (v1.2.16).

Covers:
  * Pure unit: EffectiveDate parser (ok / unknown / missing / malformed).
  * Pure unit: SourceID multi-value splitter (`;` / `/` / mixed).
  * Snapshot: verdict policy (n/a / pass / warn).
  * Snapshot: threshold boundary behavior + future-dated rows.
  * Snapshot: A59 dependent-claim join (multi-value SourceID).
  * Snapshot: tier-blind policy (T1..T5 weighted equally).
  * Backward compat: pre-v1.2.16 A50 rows without EffectiveDate stay valid.
  * CLI: --print-only / --threshold-days / --today / --quiet / --output-path /
    --report-path / error paths (uninit workspace / bad threshold / bad today).
  * Atomic write: tmpfile cleaned up on success; report file written.
  * A51 suggestion: omitted when no dependents; populated when dependents exist.
  * Markdown rendering: stale rows table + A51 suggestion block.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "freshness_audit.py"
A50_REL = "analysis/canonical/core_controls/A50_source_register.csv"
A59_REL = "analysis/canonical/core_controls/A59_claim_register.csv"


# ---- Module loader --------------------------------------------------


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location(
        "freshness_audit", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- Workspace helpers ----------------------------------------------

A50_HEADER = (
    "SourceID,SourceType,Title,Origin,AccessStatus,ReliabilityTier,"
    "Priority,Language,DateOrVersion,EffectiveDate,Notes\n"
)
A50_HEADER_NO_EFFECTIVE = (
    "SourceID,SourceType,Title,Origin,AccessStatus,ReliabilityTier,"
    "Priority,Language,DateOrVersion,Notes\n"
)
A59_HEADER = (
    "ClaimID,SourceID,ExcerptID,ClaimType,Statement,"
    "JustificationRationale,A51Ref,ClaimStrength,Criticality,Notes\n"
)


def _write_a50(workspace: Path, rows: list[dict], *, header: str = A50_HEADER) -> None:
    cols = header.strip().split(",")
    target = workspace / A50_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        fh.write(header)
        for r in rows:
            fh.write(",".join(r.get(c, "") for c in cols) + "\n")


def _write_a59(workspace: Path, rows: list[dict]) -> None:
    cols = A59_HEADER.strip().split(",")
    target = workspace / A59_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        fh.write(A59_HEADER)
        for r in rows:
            fh.write(",".join(r.get(c, "") for c in cols) + "\n")


def _make_workspace(tmp_path: Path) -> Path:
    (tmp_path / "analysis").mkdir(exist_ok=True)
    return tmp_path


def _row_a50(
    sid: str,
    *,
    effective: str = "",
    tier: str = "T2",
    source_type: str = "document",
) -> dict:
    return {
        "SourceID": sid,
        "SourceType": source_type,
        "Title": f"Source {sid}",
        "Origin": "test",
        "AccessStatus": "readable",
        "ReliabilityTier": tier,
        "Priority": "medium",
        "Language": "en",
        "DateOrVersion": "v1",
        "EffectiveDate": effective,
        "Notes": "",
    }


def _row_a59(claim_id: str, source_id: str) -> dict:
    return {
        "ClaimID": claim_id,
        "SourceID": source_id,
        "ExcerptID": "E-001",
        "ClaimType": "direct",
        "Statement": "test",
        "JustificationRationale": "",
        "A51Ref": "",
        "ClaimStrength": "0.85",
        "Criticality": "level-2",
        "Notes": "",
    }


# ---- Pure unit: EffectiveDate parser --------------------------------


def test_parse_effective_date_iso_returns_ok(helper) -> None:
    parsed, status = helper._parse_effective_date("2025-08-10")
    assert status == "ok"
    assert parsed == date(2025, 8, 10)


def test_parse_effective_date_unknown_returns_unknown(helper) -> None:
    parsed, status = helper._parse_effective_date("unknown")
    assert status == "unknown"
    assert parsed is None


def test_parse_effective_date_unknown_case_insensitive(helper) -> None:
    parsed, status = helper._parse_effective_date("Unknown")
    assert status == "unknown"
    assert parsed is None


def test_parse_effective_date_empty_returns_missing(helper) -> None:
    parsed, status = helper._parse_effective_date("")
    assert status == "missing"
    assert parsed is None


def test_parse_effective_date_whitespace_returns_missing(helper) -> None:
    parsed, status = helper._parse_effective_date("   ")
    assert status == "missing"
    assert parsed is None


def test_parse_effective_date_none_returns_missing(helper) -> None:
    parsed, status = helper._parse_effective_date(None)
    assert status == "missing"
    assert parsed is None


def test_parse_effective_date_slash_separator_rejected(helper) -> None:
    parsed, status = helper._parse_effective_date("2025/08/10")
    assert status == "malformed"
    assert parsed is None


def test_parse_effective_date_short_year_rejected(helper) -> None:
    parsed, status = helper._parse_effective_date("25-08-10")
    assert status == "malformed"
    assert parsed is None


def test_parse_effective_date_strict_two_digit_month(helper) -> None:
    """`2024-3-1` is NOT YYYY-MM-DD strict → malformed (length check)."""
    parsed, status = helper._parse_effective_date("2024-3-1")
    assert status == "malformed"
    assert parsed is None


def test_parse_effective_date_invalid_calendar_date(helper) -> None:
    parsed, status = helper._parse_effective_date("2025-02-30")
    assert status == "malformed"
    assert parsed is None


# ---- Pure unit: SourceID splitter -----------------------------------


def test_split_source_ids_semicolon(helper) -> None:
    assert helper._split_source_ids("S-001;S-002") == ["S-001", "S-002"]


def test_split_source_ids_slash(helper) -> None:
    assert helper._split_source_ids("S-001/S-002") == ["S-001", "S-002"]


def test_split_source_ids_mixed(helper) -> None:
    assert helper._split_source_ids("S-001;S-002/S-003") == [
        "S-001",
        "S-002",
        "S-003",
    ]


def test_split_source_ids_single(helper) -> None:
    assert helper._split_source_ids("S-001") == ["S-001"]


def test_split_source_ids_empty(helper) -> None:
    assert helper._split_source_ids("") == []


def test_split_source_ids_whitespace_around_tokens(helper) -> None:
    assert helper._split_source_ids(" S-001 ; S-002 ") == [
        "S-001",
        "S-002",
    ]


# ---- Snapshot: verdict policy ---------------------------------------


def test_snapshot_no_a50_returns_na(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["verdict"] == "n/a"
    assert snap["summary"]["rows_total"] == 0


def test_snapshot_empty_a50_returns_na(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [])
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["verdict"] == "n/a"
    assert snap["summary"]["rows_total"] == 0


def test_snapshot_all_missing_effective_date_returns_na(
    helper, tmp_path
) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace,
        [_row_a50("S-001"), _row_a50("S-002")],
    )
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["verdict"] == "n/a"
    assert snap["summary"]["rows_total"] == 2
    assert snap["summary"]["rows_with_effective_date"] == 0
    assert snap["summary"]["rows_na"] == 2


def test_snapshot_unknown_treated_as_na(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(workspace, [_row_a50("S-001", effective="unknown")])
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["verdict"] == "n/a"
    assert snap["summary"]["rows_na"] == 1


def test_snapshot_fresh_row_passes(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace, [_row_a50("S-001", effective="2026-01-01")]
    )
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["verdict"] == "pass"
    assert snap["summary"]["rows_fresh"] == 1
    assert snap["summary"]["rows_stale"] == 0


def test_snapshot_stale_row_no_dependents_passes(
    helper, tmp_path
) -> None:
    """Stale source with NO dependent claims → still `pass` (the
    contract's gate behavior section is explicit on this)."""
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace, [_row_a50("S-001", effective="2025-01-01")]
    )
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["verdict"] == "pass"
    assert snap["summary"]["rows_stale"] == 1
    assert snap["summary"]["stale_rows_with_dependent_claims"] == 0
    # Stale row IS reported even if non-blocking.
    assert len(snap["stale_rows"]) == 1
    # No A51 suggestion when no dependents.
    assert snap["stale_rows"][0]["suggested_a51"] is None


def test_snapshot_stale_row_with_dependent_warns(
    helper, tmp_path
) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace, [_row_a50("S-001", effective="2025-01-01")]
    )
    _write_a59(workspace, [_row_a59("CL-001", "S-001")])
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["verdict"] == "warn"
    assert snap["summary"]["stale_rows_with_dependent_claims"] == 1
    sr = snap["stale_rows"][0]
    assert sr["dependent_claim_count"] == 1
    assert sr["dependent_claim_ids"] == ["CL-001"]
    assert sr["suggested_a51"] is not None
    a51 = sr["suggested_a51"]
    # v1.2.16 R1 fix: A51Ref placeholder included so the row is shape-
    # complete vs A51 schema's required[]. Operator replaces the literal
    # before promotion (it intentionally fails A51 pattern match).
    assert a51["A51Ref"] == "<assign-on-create>"
    assert a51["IssueType"] == "boundary_risk"
    assert a51["Severity"] == "medium"
    assert a51["RelatedSourceID"] == "S-001"
    assert a51["RelatedClaimID"] == "CL-001"


def test_a51_suggestion_placeholder_carries_required_a51_fields(
    helper, tmp_path
) -> None:
    """Shape-check the suggestion against A51 schema's required[].
    A51Ref is a placeholder (won't match the schema's pattern by design),
    but every other required field MUST be present so the operator
    only has one literal to replace."""
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace, [_row_a50("S-001", effective="2025-01-01")]
    )
    _write_a59(workspace, [_row_a59("CL-001", "S-001")])
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    a51 = snap["stale_rows"][0]["suggested_a51"]
    a51_required = {
        "A51Ref", "IssueType", "Severity", "BlockingStatus",
        "RaisedByStage", "NextAction", "ResolutionStatus",
    }
    assert a51_required <= set(a51.keys()), (
        f"missing A51-required fields: {sorted(a51_required - set(a51.keys()))}"
    )


# ---- Snapshot: threshold boundary -----------------------------------


def test_threshold_boundary_at_limit_fresh(helper, tmp_path) -> None:
    """Age == threshold_days → fresh (boundary inclusive)."""
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace, [_row_a50("S-001", effective="2025-10-27")]
    )
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["summary"]["rows_fresh"] == 1
    assert snap["summary"]["rows_stale"] == 0


def test_threshold_boundary_one_day_over_stale(
    helper, tmp_path
) -> None:
    """Age == threshold_days + 1 → stale."""
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace, [_row_a50("S-001", effective="2025-10-26")]
    )
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["summary"]["rows_stale"] == 1


def test_future_dated_treated_as_fresh(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace, [_row_a50("S-001", effective="2027-01-01")]
    )
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["summary"]["rows_fresh"] == 1
    assert snap["summary"]["rows_stale"] == 0


# ---- Snapshot: A59 join, multi-value SourceID -----------------------


def test_a59_multi_value_source_id_split(helper, tmp_path) -> None:
    """A59 row with `SourceID="S-001;S-002"` counts as a dependent for
    BOTH S-001 and S-002. Mirrors v1.2.14 multi-FK semantics."""
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace,
        [
            _row_a50("S-001", effective="2025-01-01"),
            _row_a50("S-002", effective="2025-01-01"),
        ],
    )
    _write_a59(workspace, [_row_a59("CL-001", "S-001;S-002")])
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["verdict"] == "warn"
    assert snap["summary"]["stale_rows_with_dependent_claims"] == 2
    deps = {sr["source_id"]: sr["dependent_claim_ids"] for sr in snap["stale_rows"]}
    assert deps["S-001"] == ["CL-001"]
    assert deps["S-002"] == ["CL-001"]


def test_a59_slash_separator_dependents_counted(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace,
        [_row_a50("S-001", effective="2025-01-01")],
    )
    _write_a59(workspace, [_row_a59("CL-001", "S-001/S-099")])
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    sr = next(s for s in snap["stale_rows"] if s["source_id"] == "S-001")
    assert sr["dependent_claim_count"] == 1


# ---- Snapshot: tier-blindness (contract rule) -----------------------


@pytest.mark.parametrize("tier", ["T1", "T2", "T3", "T4", "T5"])
def test_tier_blind_freshness(helper, tmp_path, tier) -> None:
    """All tiers use the SAME threshold per contract — tier is NOT a
    freshness multiplier."""
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace,
        [_row_a50("S-001", effective="2025-01-01", tier=tier)],
    )
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["summary"]["rows_stale"] == 1, (
        f"tier {tier} should also report stale; threshold is tier-blind"
    )


# ---- Backward compat ------------------------------------------------


def test_pre_v1216_a50_without_effective_date_column_is_valid(
    helper, tmp_path
) -> None:
    """Pre-v1.2.16 A50 CSVs (no EffectiveDate column) must still load
    without errors and audit must report n/a."""
    workspace = _make_workspace(tmp_path)
    rows = [
        {
            "SourceID": "S-001",
            "SourceType": "document",
            "Title": "Old fixture",
            "Origin": "test",
            "AccessStatus": "readable",
            "ReliabilityTier": "T2",
            "Priority": "medium",
            "Language": "en",
            "DateOrVersion": "v1",
            "Notes": "pre-v1.2.16 row",
        }
    ]
    _write_a50(workspace, rows, header=A50_HEADER_NO_EFFECTIVE)
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["verdict"] == "n/a"
    assert snap["summary"]["rows_total"] == 1
    assert snap["summary"]["rows_na"] == 1


def test_a50_with_empty_effective_date_validates_against_schema(
    tmp_path,
) -> None:
    """Pin v1.2.16 R1 fix: schema's EffectiveDate pattern allows the
    empty string so a row-by-row backfill works (some rows have a
    real date, others have empty cell). Without this, write_validator
    rejects the half-backfilled CSV at promote-gate."""
    import json
    from pathlib import Path
    REPO_ROOT_LOCAL = Path(__file__).resolve().parent.parent
    schema = json.loads(
        (REPO_ROOT_LOCAL / "governance/schemas/a50.schema.json").read_text(
            encoding="utf-8"
        )
    )
    pattern = schema["properties"]["EffectiveDate"]["pattern"]
    import re
    rx = re.compile(pattern)
    assert rx.fullmatch("") is not None, (
        f"empty string must validate against EffectiveDate pattern; "
        f"got pattern={pattern!r}"
    )
    assert rx.fullmatch("unknown") is not None
    assert rx.fullmatch("2025-08-10") is not None
    assert rx.fullmatch("not-a-date") is None


def test_a50_invalid_calendar_date_rejected_by_write_validator(
    tmp_path,
) -> None:
    """Pin v1.2.16 R2 fix: shape regex alone (`YYYY-MM-DD`) accepts
    impossible dates like `2025-02-30` or `2025-13-99`. The new
    `x-bsa-strict-date-rules` extension + `_apply_strict_date_rules`
    handler closes the gap so a "backfilled" row with a fake date
    fails F5 promotion instead of silently surviving canonical
    validation only to be downgraded to `n/a` by freshness_audit
    later."""
    import subprocess
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace,
        [
            _row_a50("S-001", effective="2025-02-30"),  # invalid calendar
        ],
    )
    target = workspace / "analysis/canonical/core_controls/A50_source_register.csv"
    proc = subprocess.run(
        [sys.executable, "-m", "governance.schemas.write_validator",
         "analysis/canonical/core_controls/A50_source_register.csv"],
        input=target.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert proc.returncode != 0, (
        f"invalid calendar date 2025-02-30 must be rejected by F5; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    combined = (proc.stdout + proc.stderr).lower()
    assert "invalid calendar date" in combined or "2025-02-30" in combined


def test_a50_shape_invalid_effective_date_emits_only_one_violation(
    tmp_path,
) -> None:
    """Pin v1.2.16 R3 fix: a shape-invalid value like `not-a-date`
    must produce ONLY the schema's regex pattern violation, not also
    the strict-date handler's "regex shape passes but date does not
    exist" message (which would be a misleading double-violation)."""
    import subprocess
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace,
        [_row_a50("S-001", effective="not-a-date")],
    )
    target = workspace / "analysis/canonical/core_controls/A50_source_register.csv"
    proc = subprocess.run(
        [sys.executable, "-m", "governance.schemas.write_validator",
         "analysis/canonical/core_controls/A50_source_register.csv"],
        input=target.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert proc.returncode != 0
    combined = (proc.stdout + proc.stderr)
    # Schema pattern violation should fire (mention 'pattern' or
    # 'EffectiveDate' from the JSON Schema error).
    assert "EffectiveDate" in combined
    # Strict-date handler MUST NOT also fire — that would be a
    # double-violation. The handler's signature phrase is
    # "regex shape passes but date does not exist".
    assert "regex shape passes" not in combined, (
        f"strict-date handler produced redundant violation for "
        f"shape-invalid input; combined output:\n{combined}"
    )


def test_a50_whitespace_padded_effective_date_emits_only_one_violation(
    tmp_path,
) -> None:
    """Pin v1.2.16 R5 fix: a value padded with leading/trailing
    whitespace (`" 2025-02-30 "`) is rejected by the schema's regex
    (anchored, no whitespace allowed), but pre-R5 the strict-date
    handler stripped before its shape check, accepting the stripped
    `"2025-02-30"`, failing strptime, and producing the same redundant
    second violation R3/R4 chain was meant to eliminate. The R5 fix
    drops the strip so the handler's reach matches the schema regex
    exactly."""
    import subprocess
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace,
        [_row_a50("S-001", effective=" 2025-02-30 ")],
    )
    target = workspace / "analysis/canonical/core_controls/A50_source_register.csv"
    proc = subprocess.run(
        [sys.executable, "-m", "governance.schemas.write_validator",
         "analysis/canonical/core_controls/A50_source_register.csv"],
        input=target.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert proc.returncode != 0
    combined = (proc.stdout + proc.stderr)
    assert "EffectiveDate" in combined
    # Strict-date handler MUST NOT also fire — schema regex already
    # rejected the whitespace-padded value, handler should silently
    # skip (R5 fix: shape-gate runs on raw, not stripped, value).
    assert "regex shape passes" not in combined, (
        f"strict-date handler stripped whitespace and re-emitted; "
        f"R5 fix regressed; combined output:\n{combined}"
    )


def test_a50_unicode_digit_effective_date_emits_only_one_violation(
    tmp_path,
) -> None:
    """Pin v1.2.16 R4 fix: Python's `\\d` matches non-ASCII digit
    categories (Arabic-Indic ٠١٢…, fullwidth ０１２…, etc.), but the
    schema property pattern uses ASCII-exact `[0-9]`. If the strict-
    date handler used `\\d`, a Unicode-digit input would match the
    handler's gate, fail `strptime`, and produce the same redundant
    second violation R3 was meant to remove. The R4 fix tightens the
    gate to ASCII-exact `[0-9]` so the handler's reach matches the
    property's regex exactly."""
    import subprocess
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace,
        # Arabic-Indic digits — schema regex `[0-9]` rejects this.
        [_row_a50("S-001", effective="٢٠٢٥-٠٢-٣٠")],
    )
    target = workspace / "analysis/canonical/core_controls/A50_source_register.csv"
    proc = subprocess.run(
        [sys.executable, "-m", "governance.schemas.write_validator",
         "analysis/canonical/core_controls/A50_source_register.csv"],
        input=target.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert proc.returncode != 0
    combined = (proc.stdout + proc.stderr)
    assert "EffectiveDate" in combined
    # Strict-date handler MUST NOT also fire — would be double violation.
    assert "regex shape passes" not in combined, (
        f"strict-date handler used `\\d` and matched Unicode digits — "
        f"R4 ASCII-exact gate regressed; combined output:\n{combined}"
    )


def test_a50_csv_with_mixed_effective_date_validates_via_write_validator(
    tmp_path,
) -> None:
    """End-to-end pin: a real A50 CSV with EffectiveDate column where
    SOME rows have a date and SOME are blank passes the F5
    write-validator. This is the v1.2.16 R1 backward-compat target —
    operators backfilling EffectiveDate row-by-row must not break
    canonical promotion."""
    import subprocess
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace,
        [
            _row_a50("S-001", effective="2025-08-10"),
            _row_a50("S-002", effective=""),  # backfill not yet done
            _row_a50("S-003", effective="unknown"),
        ],
    )
    target = workspace / "analysis/canonical/core_controls/A50_source_register.csv"
    proc = subprocess.run(
        [sys.executable, "-m", "governance.schemas.write_validator",
         "analysis/canonical/core_controls/A50_source_register.csv"],
        input=target.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert proc.returncode == 0, (
        f"mixed-EffectiveDate A50 must pass write_validator; "
        f"stderr=\n{proc.stderr}"
    )


def test_dateorversion_not_used_for_freshness(helper, tmp_path) -> None:
    """`DateOrVersion` is free-form provenance; the audit must NOT
    parse it as a fallback for EffectiveDate (operator-authority rule
    in contract)."""
    workspace = _make_workspace(tmp_path)
    rows = [_row_a50("S-001")]
    rows[0]["DateOrVersion"] = "2020-01-01"  # parseable but ignored
    _write_a50(workspace, rows)
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    assert snap["verdict"] == "n/a"
    assert snap["summary"]["rows_na"] == 1


# ---- CLI ------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_print_only_does_not_write(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace, [_row_a50("S-001", effective="2026-01-01")]
    )
    result = _run_cli(
        "--workspace", str(workspace),
        "--print-only",
        "--today", "2026-04-25",
    )
    assert result.returncode == 0
    snap = json.loads(result.stdout)
    assert snap["verdict"] == "pass"
    assert not (workspace / "analysis/canonical/stage1/freshness_audit.json").exists()
    assert not (workspace / "analysis/canonical/stage1/freshness_audit.md").exists()


def test_cli_writes_marker_and_report(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace, [_row_a50("S-001", effective="2026-01-01")]
    )
    result = _run_cli(
        "--workspace", str(workspace),
        "--today", "2026-04-25",
        "--quiet",
    )
    assert result.returncode == 0
    marker = workspace / "analysis/canonical/stage1/freshness_audit.json"
    report = workspace / "analysis/canonical/stage1/freshness_audit.md"
    assert marker.exists()
    assert report.exists()
    snap = json.loads(marker.read_text(encoding="utf-8"))
    assert snap["verdict"] == "pass"
    md = report.read_text(encoding="utf-8")
    assert "# Freshness Audit" in md
    assert "verdict: **pass**" in md


def test_cli_threshold_days_override(tmp_path) -> None:
    """Same fixture; threshold=30 → stale, threshold=365 → fresh."""
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace, [_row_a50("S-001", effective="2025-12-01")]
    )
    r_strict = _run_cli(
        "--workspace", str(workspace),
        "--threshold-days", "30",
        "--today", "2026-04-25",
        "--print-only",
    )
    assert r_strict.returncode == 0
    snap_strict = json.loads(r_strict.stdout)
    assert snap_strict["summary"]["rows_stale"] == 1

    r_lax = _run_cli(
        "--workspace", str(workspace),
        "--threshold-days", "365",
        "--today", "2026-04-25",
        "--print-only",
    )
    assert r_lax.returncode == 0
    snap_lax = json.loads(r_lax.stdout)
    assert snap_lax["summary"]["rows_stale"] == 0


def test_cli_workspace_not_initialized_returns_2(tmp_path) -> None:
    """Workspace without analysis/ → exit 2."""
    result = _run_cli(
        "--workspace", str(tmp_path),
        "--today", "2026-04-25",
        "--print-only",
    )
    assert result.returncode == 2
    assert "not initialized" in result.stderr


def test_cli_invalid_threshold_returns_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(workspace),
        "--threshold-days", "0",
        "--print-only",
    )
    assert result.returncode == 2
    assert "threshold-days" in result.stderr


def test_cli_invalid_today_returns_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(workspace),
        "--today", "not-a-date",
        "--print-only",
    )
    assert result.returncode == 2


def test_cli_negative_threshold_returns_2(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(workspace),
        "--threshold-days", "-5",
        "--print-only",
    )
    assert result.returncode == 2


# ---- Markdown rendering ---------------------------------------------


def test_markdown_renders_stale_rows_table(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace,
        [_row_a50("S-001", effective="2025-01-01")],
    )
    _write_a59(workspace, [_row_a59("CL-001", "S-001")])
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    md = helper.render_markdown(snap)
    assert "## Stale rows" in md
    assert "`S-001`" in md
    assert "## Suggested A51 routes" in md
    assert "boundary_risk" in md
    # v1.2.16 R2 fix: explicit operator guidance to replace placeholder
    # before promoting (placeholder fails A51 validation by design).
    assert "`<assign-on-create>`" in md
    assert "replace" in md.lower()


def test_markdown_no_stale_rows_section_when_clean(
    helper, tmp_path
) -> None:
    workspace = _make_workspace(tmp_path)
    _write_a50(
        workspace, [_row_a50("S-001", effective="2026-01-01")]
    )
    snap = helper.build_snapshot(
        workspace, threshold_days=180, today_utc=date(2026, 4, 25)
    )
    md = helper.render_markdown(snap)
    assert "No stale rows." in md
    assert "## Stale rows" not in md
