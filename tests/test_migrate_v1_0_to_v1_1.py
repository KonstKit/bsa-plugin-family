"""Unit tests for scripts/migrate_v1.0_to_v1.1.py (Pilot-1 drift bundle).

Covers the four mechanical fixes (markers / a50-priority / a50-reliability-tier /
a50-source-id-prefix) and the four report-only checks (verdict-caveats /
a50-access-status-partial / a60-header-mismatch / a51-reconciliation), all
both in dry-run and (where applicable) apply mode. Idempotency, backup
preservation, JSONL log schema, and error / preflight paths are also covered.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "migrate_v1.0_to_v1.1.py"


# ---- helpers -----------------------------------------------------------


def run_migration(workspace: Path, *flags: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), f"--workspace={workspace}", *flags]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def read_log(workspace: Path) -> list[dict]:
    log = workspace / "runtime" / "migration_log_v1.0_to_v1.1.jsonl"
    if not log.exists():
        return []
    records: list[dict] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "analysis"
    ws.mkdir()
    (ws / "runtime" / "ready").mkdir(parents=True)
    (ws / "canonical" / "core_controls").mkdir(parents=True)
    return ws


def write_marker(ws: Path, name: str, payload: dict) -> Path:
    p = ws / "runtime" / "ready" / name
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p


def write_csv(ws: Path, rel_path: str, header: list[str], rows: list[list[str]]) -> Path:
    p = ws / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return p


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


# ---- preflight + invocation -------------------------------------------


def test_missing_workspace_returns_2(tmp_path: Path) -> None:
    result = run_migration(tmp_path / "nonexistent", "--all-mechanical")
    assert result.returncode == 2
    assert "does not exist" in result.stderr


def test_workspace_not_directory_returns_2(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("hello", encoding="utf-8")
    result = run_migration(not_a_dir, "--all-mechanical")
    assert result.returncode == 2
    assert "not a directory" in result.stderr


def test_no_action_flag_returns_2(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    result = run_migration(ws)
    assert result.returncode == 2
    assert "nothing to do" in result.stderr


# ---- mechanical: markers ----------------------------------------------


def test_markers_dry_run_reports_planned(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_marker(ws, "stage1.ready.json", {
        "marker": "stage1.ready",
        "stage": "stage1",
        "emittedAt": "2026-04-22T00:00:00Z",
        "canonPolicyVersion": "1.0.0",
    })
    result = run_migration(ws, "--markers-only")
    assert result.returncode == 0, result.stderr
    assert "dry-run" in result.stdout
    # File NOT modified yet
    payload = json.loads((ws / "runtime/ready/stage1.ready.json").read_text())
    assert "marker" in payload
    assert "marker_id" not in payload
    # Log records
    records = read_log(ws)
    assert any(r["fix_kind"] == "markers" and r["mode"] == "planned" for r in records)


def test_markers_apply_renames_camelcase(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_marker(ws, "stage1.ready.json", {
        "marker": "stage1.ready",
        "stage": "stage1",
        "emittedAt": "2026-04-22T00:00:00Z",
        "canonPolicyVersion": "1.0.0",
    })
    result = run_migration(ws, "--markers-only", "--apply")
    assert result.returncode == 0, result.stderr
    payload = json.loads((ws / "runtime/ready/stage1.ready.json").read_text())
    assert "marker" not in payload
    assert payload["marker_id"] == "stage1.ready"
    assert "emittedAt" not in payload
    assert payload["timestamp"] == "2026-04-22T00:00:00Z"
    assert "canonPolicyVersion" not in payload
    assert payload["canon_policy_version"] == "1.0.0"
    # Verdict was missing — TODO injected with PASS hint (since *.ready.json → READY default)
    assert payload["verdict"].startswith("<MIGRATION_TODO_VERDICT")
    assert "READY" in payload["verdict"]
    # Backup preserved
    assert (ws / "runtime/ready/stage1.ready.json.pre-v1.1.bak").exists()


def test_markers_idempotent(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_marker(ws, "stage1.ready.json", {
        "marker_id": "stage1.ready",
        "stage": "stage1",
        "verdict": "READY",
        "timestamp": "2026-04-22T00:00:00Z",
        "canon_policy_version": "1.1.0",
    })
    # Already canonical: should skip
    result = run_migration(ws, "--markers-only", "--apply")
    assert result.returncode == 0
    records = read_log(ws)
    assert all(r["mode"] != "applied" for r in records if r["fix_kind"] == "markers")
    assert any(r["mode"] == "skipped" for r in records if r["fix_kind"] == "markers")


def test_markers_verdict_inferred_from_pass_filename(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_marker(ws, "stage3.citation_audit.pass.json", {
        "marker": "stage3.citation_audit.pass",
        "stage": "stage3",
        "emittedAt": "2026-04-22T00:00:00Z",
        "canonPolicyVersion": "1.0.0",
    })
    run_migration(ws, "--markers-only", "--apply")
    payload = json.loads((ws / "runtime/ready/stage3.citation_audit.pass.json").read_text())
    assert "PASS" in payload["verdict"]


# ---- mechanical: A50 Priority ----------------------------------------


def test_a50_priority_apply_strips_jira_prefix(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A50_source_register.csv",
              ["SourceID", "Priority", "ReliabilityTier"],
              [
                  ["S-001", "P1_high", "T2"],
                  ["S-002", "P2_medium", "T3"],
                  ["S-003", "P3_low", "T4"],
                  ["S-004", "high", "T1"],  # already canonical
              ])
    result = run_migration(ws, "--a50-priority", "--apply")
    assert result.returncode == 0, result.stderr
    _, rows = read_csv_rows(ws / "canonical/core_controls/A50_source_register.csv")
    assert rows[0]["Priority"] == "high"
    assert rows[1]["Priority"] == "medium"
    assert rows[2]["Priority"] == "low"
    assert rows[3]["Priority"] == "high"  # untouched


def test_a50_priority_p0_critical_inserts_todo_marker(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A50_source_register.csv",
              ["SourceID", "Priority"],
              [["S-001", "P0_critical"]])
    run_migration(ws, "--a50-priority", "--apply")
    _, rows = read_csv_rows(ws / "canonical/core_controls/A50_source_register.csv")
    # P0_critical → TODO marker (not auto-mapped because A50 schema lacks 'critical')
    assert rows[0]["Priority"].startswith("<MIGRATION_TODO_PRIORITY")


def test_a50_priority_no_priority_column_skipped(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A50_source_register.csv",
              ["SourceID", "Title"], [["S-001", "Some source"]])
    result = run_migration(ws, "--a50-priority", "--apply")
    assert result.returncode == 0
    records = read_log(ws)
    assert any(r["fix_kind"] == "a50-priority" and r["mode"] == "skipped" for r in records)


# ---- mechanical: A50 ReliabilityTier ---------------------------------


def test_a50_reliability_tier_strips_descriptor(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A50_source_register.csv",
              ["SourceID", "ReliabilityTier", "Notes"],
              [
                  ["S-001", "T1_primary_recording", ""],
                  ["S-002", "T2_primary_notes", "existing note"],
                  ["S-003", "T3", "no change needed"],
              ])
    result = run_migration(ws, "--a50-reliability-tier", "--apply")
    assert result.returncode == 0, result.stderr
    _, rows = read_csv_rows(ws / "canonical/core_controls/A50_source_register.csv")
    assert rows[0]["ReliabilityTier"] == "T1"
    assert "primary recording" in rows[0]["Notes"]
    assert rows[1]["ReliabilityTier"] == "T2"
    assert rows[1]["Notes"].startswith("existing note;")
    assert "primary notes" in rows[1]["Notes"]
    assert rows[2]["ReliabilityTier"] == "T3"
    assert rows[2]["Notes"] == "no change needed"


def test_a50_reliability_tier_creates_notes_column_if_missing(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A50_source_register.csv",
              ["SourceID", "ReliabilityTier"],
              [["S-001", "T1_primary_recording"]])
    result = run_migration(ws, "--a50-reliability-tier", "--apply")
    assert result.returncode == 0
    fieldnames, rows = read_csv_rows(ws / "canonical/core_controls/A50_source_register.csv")
    assert "Notes" in fieldnames
    assert rows[0]["ReliabilityTier"] == "T1"
    assert "primary recording" in rows[0]["Notes"]


# ---- mechanical: A50 SourceID prefix + crossref ----------------------


def test_a50_source_id_prefix_rewrites_a50_and_crossrefs(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A50_source_register.csv",
              ["SourceID", "Title"],
              [
                  ["CALL-001", "Call recording 1"],
                  ["CALL-002", "Call recording 2"],
                  ["S-EMAIL-001", "Email already canonical"],
              ])
    write_csv(ws, "canonical/core_controls/A58_evidence_excerpts.csv",
              ["ExcerptID", "SourceID", "ExcerptText"],
              [
                  ["E-001", "CALL-001", "First excerpt"],
                  ["E-002", "CALL-002", "Second excerpt"],
              ])
    write_csv(ws, "canonical/core_controls/A59_claim_register.csv",
              ["ClaimID", "SourceID", "Statement"],
              [
                  ["C-001", "CALL-001;CALL-002", "Multi-source claim"],
                  ["C-002", "S-EMAIL-001", "Already canonical"],
              ])
    result = run_migration(ws, "--a50-source-id-prefix", "--apply")
    assert result.returncode == 0, result.stderr

    _, a50_rows = read_csv_rows(ws / "canonical/core_controls/A50_source_register.csv")
    assert a50_rows[0]["SourceID"] == "S-CALL-001"
    assert a50_rows[1]["SourceID"] == "S-CALL-002"
    assert a50_rows[2]["SourceID"] == "S-EMAIL-001"  # untouched

    _, a58_rows = read_csv_rows(ws / "canonical/core_controls/A58_evidence_excerpts.csv")
    assert a58_rows[0]["SourceID"] == "S-CALL-001"
    assert a58_rows[1]["SourceID"] == "S-CALL-002"

    _, a59_rows = read_csv_rows(ws / "canonical/core_controls/A59_claim_register.csv")
    # multi-source preserved with delimiter
    assert "S-CALL-001" in a59_rows[0]["SourceID"]
    assert "S-CALL-002" in a59_rows[0]["SourceID"]
    assert a59_rows[1]["SourceID"] == "S-EMAIL-001"


def test_a50_source_id_prefix_idempotent(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A50_source_register.csv",
              ["SourceID"],
              [["S-CALL-001"], ["S-EMAIL-001"]])
    result = run_migration(ws, "--a50-source-id-prefix", "--apply")
    assert result.returncode == 0
    _, rows = read_csv_rows(ws / "canonical/core_controls/A50_source_register.csv")
    assert rows[0]["SourceID"] == "S-CALL-001"
    assert rows[1]["SourceID"] == "S-EMAIL-001"


# ---- report: verdict caveats ------------------------------------------


def test_report_verdict_caveats_finds_pass_with_caveats(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_marker(ws, "stage3.audit.pass.json", {
        "marker_id": "stage3.audit.pass",
        "stage": "stage3",
        "verdict": "PASS (with caveats)",
        "timestamp": "2026-04-22T00:00:00Z",
        "canon_policy_version": "1.0.0",
    })
    write_marker(ws, "stage1.ready.json", {
        "marker_id": "stage1.ready",
        "stage": "stage1",
        "verdict": "READY",  # canonical — should NOT be flagged
        "timestamp": "2026-04-22T00:00:00Z",
        "canon_policy_version": "1.0.0",
    })
    result = run_migration(ws, "--report", "verdict-caveats")
    assert result.returncode == 0, result.stderr
    assert "PASS (with caveats)" in result.stdout
    assert "stage1.ready.json" not in result.stdout  # canonical not flagged


def test_report_skips_migration_todo_verdict(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_marker(ws, "stage1.ready.json", {
        "marker_id": "stage1.ready",
        "stage": "stage1",
        "verdict": "<MIGRATION_TODO_VERDICT verdict_hint=READY>",
        "timestamp": "2026-04-22T00:00:00Z",
        "canon_policy_version": "1.0.0",
    })
    result = run_migration(ws, "--report", "verdict-caveats")
    # TODO markers are NOT flagged by verdict-caveats — they're already known via --markers-only
    assert "MIGRATION_TODO" not in result.stdout


# ---- report: A50 AccessStatus partial ---------------------------------


def test_report_a50_access_status_partial_finds_non_canonical(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A50_source_register.csv",
              ["SourceID", "AccessStatus"],
              [
                  ["S-001", "readable"],     # canonical — skip
                  ["S-002", "readable_partial"],  # non-canonical — flag
                  ["S-003", "denied"],       # canonical — skip
                  ["S-004", "unreadable_binary"],  # non-canonical — flag
              ])
    result = run_migration(ws, "--report", "a50-access-status-partial")
    assert result.returncode == 0
    assert "readable_partial" in result.stdout
    assert "unreadable_binary" in result.stdout
    # Confirm canonical values not flagged
    findings = [r for r in read_log(ws) if r["fix_kind"] == "report-a50-access-status-partial"]
    assert len(findings) == 2


# ---- report: A60 header mismatch -------------------------------------


def test_report_a60_header_mismatch_prints_diff(tmp_path: Path) -> None:
    """Canonical A60 has 7 cols (NegEvID, SourceID, ExcerptRef,
    RelatedClaimID, NegativeFinding, A51Ref, Notes). A pilot file
    using totally different column names must surface every missing
    required col AND every extra col."""
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A60_negative_evidence_register.csv",
              ["NegID", "PathFamily", "NegativeClaim"],  # totally different
              [["N-001", "auth", "A user without role"]])
    result = run_migration(ws, "--report", "a60-header-mismatch")
    assert result.returncode == 0
    assert "missing" in result.stdout
    assert "extra" in result.stdout
    # All 7 canonical required columns must appear in the missing set
    for canonical_col in ("NegEvID", "SourceID", "ExcerptRef", "RelatedClaimID", "NegativeFinding", "A51Ref", "Notes"):
        assert canonical_col in result.stdout, f"missing canonical col {canonical_col} not in output"


def test_report_a60_canonical_header_no_finding(tmp_path: Path) -> None:
    """Canonical A60 has 7 columns (per governance/schemas/a60.schema.json).
    A header containing exactly that set should NOT produce a finding."""
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A60_negative_evidence_register.csv",
              ["NegEvID", "SourceID", "ExcerptRef", "RelatedClaimID", "NegativeFinding", "A51Ref", "Notes"],
              [["N-001", "S-001", "E-001", "C-001", "Counter-evidence", "", ""]])
    result = run_migration(ws, "--report", "a60-header-mismatch")
    assert result.returncode == 0
    findings = [r for r in read_log(ws) if r["fix_kind"] == "report-a60-header-mismatch"]
    assert len(findings) == 0


def test_report_a60_extra_columns_flags(tmp_path: Path) -> None:
    """A60 with all canonical columns PLUS an extra column should also
    produce a finding (exact-set semantics, matching schema validator)."""
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A60_negative_evidence_register.csv",
              ["NegEvID", "SourceID", "ExcerptRef", "RelatedClaimID", "NegativeFinding", "A51Ref", "Notes", "Extra"],
              [["N-001", "S-001", "E-001", "C-001", "x", "", "", "leak"]])
    result = run_migration(ws, "--report", "a60-header-mismatch")
    assert result.returncode == 0
    assert "extra" in result.stdout.lower()
    assert "Extra" in result.stdout


# ---- report: A51 reconciliation --------------------------------------


def test_report_a51_reconciliation_finds_mismatch(tmp_path: Path) -> None:
    """The reconciliation report delegates to scripts/validate_a51_reconciliation,
    which uses the schema loader — so the test fixture must use the full
    9-column canonical A51 column set (incl. RelatedSourceID + RelatedClaimID)."""
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A51_issue_route_register.csv",
              ["A51Ref", "IssueType", "Severity", "BlockingStatus", "RaisedByStage",
               "RelatedSourceID", "RelatedClaimID", "NextAction", "ResolutionStatus"],
              [
                  ["A51-MISS-010", "missing_source", "medium", "soft", "stage1", "", "", "do x", "open"],
                  ["A51-MISS-011", "missing_source", "low", "informational", "stage1", "", "", "do y", "resolved"],  # not flagged
              ])
    write_marker(ws, "stage5.ready.json", {
        "marker_id": "stage5.ready",
        "stage": "stage5",
        "verdict": "READY",
        "timestamp": "2026-04-22T00:00:00Z",
        "canon_policy_version": "1.0.0",
        "notes": "A51-MISS-010 was resolved by remediation in stage 4",
    })
    result = run_migration(ws, "--report", "a51-reconciliation")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "A51-MISS-010" in result.stdout
    findings = [r for r in read_log(ws) if r["fix_kind"] == "report-a51-reconciliation"]
    # Only A51-MISS-010 (open + appears in marker with "resolved" keyword)
    assert any("A51-MISS-010" in r["detail"] for r in findings)
    assert not any("A51-MISS-011" in r["detail"] for r in findings)


def test_report_a51_reconciliation_picks_up_synonyms(tmp_path: Path) -> None:
    """Parity check: the upstream auditor recognizes synonyms beyond
    just resolved/remediated/closed (also: fixed, completed, done,
    obsolete, superseded). A pre-fix custom regex would miss these.
    """
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A51_issue_route_register.csv",
              ["A51Ref", "IssueType", "Severity", "BlockingStatus", "RaisedByStage",
               "RelatedSourceID", "RelatedClaimID", "NextAction", "ResolutionStatus"],
              [
                  ["A51-001", "uncertainty", "medium", "soft", "stage1", "", "", "do x", "open"],
                  ["A51-002", "uncertainty", "medium", "soft", "stage1", "", "", "do y", "open"],
                  ["A51-003", "uncertainty", "medium", "soft", "stage1", "", "", "do z", "open"],
              ])
    write_marker(ws, "stage5.ready.json", {
        "marker_id": "stage5.ready",
        "stage": "stage5",
        "verdict": "READY",
        "timestamp": "2026-04-22T00:00:00Z",
        "canon_policy_version": "1.0.0",
        "fixed_in_stage_4": "A51-001 was fixed in stage 4",
        "completed_remediations": "A51-002 was completed during this run",
        "done": "A51-003 is done — wrap up",
    })
    result = run_migration(ws, "--report", "a51-reconciliation")
    assert result.returncode == 0
    # All three synonyms should be picked up (fixed / completed / done)
    findings = [r for r in read_log(ws) if r["fix_kind"] == "report-a51-reconciliation"]
    refs_flagged = {ref for r in findings for ref in ("A51-001", "A51-002", "A51-003") if ref in r["detail"]}
    assert refs_flagged == {"A51-001", "A51-002", "A51-003"}, (
        f"expected all 3 refs flagged via synonyms; got {refs_flagged}"
    )


# ---- combined / log schema -------------------------------------------


def test_log_schema_records_carry_required_fields(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_marker(ws, "stage1.ready.json", {
        "marker": "stage1.ready",
        "stage": "stage1",
        "emittedAt": "2026-04-22T00:00:00Z",
        "canonPolicyVersion": "1.0.0",
    })
    run_migration(ws, "--markers-only", "--apply")
    records = read_log(ws)
    assert records, "expected at least one log record"
    for r in records:
        assert {"timestamp", "migration", "fix_kind", "target_path", "detail", "mode", "dry_run"}.issubset(r.keys())
        assert r["migration"] == "v1.0_to_v1.1"


def test_all_mechanical_runs_all_four_fixes(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_marker(ws, "stage1.ready.json", {
        "marker": "stage1.ready",
        "stage": "stage1",
        "emittedAt": "2026-04-22T00:00:00Z",
        "canonPolicyVersion": "1.0.0",
    })
    write_csv(ws, "canonical/core_controls/A50_source_register.csv",
              ["SourceID", "Priority", "ReliabilityTier"],
              [["CALL-001", "P1_high", "T2_primary_notes"]])
    write_csv(ws, "canonical/core_controls/A58_evidence_excerpts.csv",
              ["ExcerptID", "SourceID"], [["E-001", "CALL-001"]])
    result = run_migration(ws, "--all-mechanical", "--apply")
    assert result.returncode == 0, result.stderr
    payload = json.loads((ws / "runtime/ready/stage1.ready.json").read_text())
    assert "marker_id" in payload
    _, a50_rows = read_csv_rows(ws / "canonical/core_controls/A50_source_register.csv")
    assert a50_rows[0]["Priority"] == "high"
    assert a50_rows[0]["ReliabilityTier"] == "T2"
    assert a50_rows[0]["SourceID"] == "S-CALL-001"
    _, a58_rows = read_csv_rows(ws / "canonical/core_controls/A58_evidence_excerpts.csv")
    assert a58_rows[0]["SourceID"] == "S-CALL-001"


# ---- new behaviors covering Codex round-1 v1.1.2 fixes -----------------


def test_a50_priority_headerless_csv_surfaces_error(tmp_path: Path) -> None:
    """A headerless A50 CSV (csv.DictReader treats first data row as header)
    must surface as an error, not be silently downgraded to no-column skip."""
    ws = make_workspace(tmp_path)
    p = ws / "canonical/core_controls/A50_source_register.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    # Headerless: first line is data, no `SourceID,Priority,...` header row
    p.write_text("CALL-001,P1_high,T2\nCALL-002,P2_medium,T3\n", encoding="utf-8")
    result = run_migration(ws, "--a50-priority")
    # With header validation, this should now produce an error record
    records = read_log(ws)
    a50_errors = [r for r in records if r["fix_kind"] == "a50-priority" and r["mode"] == "error"]
    assert a50_errors, "headerless A50 CSV should surface as error"
    assert "header" in a50_errors[0]["reason"].lower()


def test_source_id_prefix_phase3_logs_applied_only_after_write(tmp_path: Path) -> None:
    """The phase-3 write step must log `applied` records AFTER the actual
    csv.write succeeds — not at planning time. Verifies the v1.1.2
    Codex round-1 fix."""
    ws = make_workspace(tmp_path)
    write_csv(ws, "canonical/core_controls/A50_source_register.csv",
              ["SourceID"], [["CALL-001"]])
    write_csv(ws, "canonical/core_controls/A58_evidence_excerpts.csv",
              ["ExcerptID", "SourceID"], [["E-001", "CALL-001"]])
    result = run_migration(ws, "--a50-source-id-prefix", "--apply")
    assert result.returncode == 0, result.stdout + result.stderr
    records = read_log(ws)
    # Phase 1+2 emit `planned`; Phase 3 emits `applied` per file.
    planned = [r for r in records if r["mode"] == "planned" and "source-id-prefix" in r["fix_kind"]]
    applied = [r for r in records if r["mode"] == "applied" and "source-id-prefix" in r["fix_kind"]]
    assert planned, f"expected planned records: {records}"
    assert applied, f"expected applied records (post-write): {records}"
    # Every applied record carries the post-write detail
    for r in applied:
        assert "phase-3 write" in r["detail"]


def test_report_only_does_not_mutate_data_files(tmp_path: Path) -> None:
    """Pure --report runs must leave the workspace data files byte-identical."""
    ws = make_workspace(tmp_path)
    a50_path = write_csv(
        ws, "canonical/core_controls/A50_source_register.csv",
        ["SourceID", "AccessStatus"], [["S-001", "readable_partial"]],
    )
    marker_path = write_marker(ws, "stage3.audit.pass.json", {
        "marker_id": "stage3.audit.pass",
        "stage": "stage3",
        "verdict": "PASS (with caveats)",
        "timestamp": "2026-04-22T00:00:00Z",
        "canon_policy_version": "1.0.0",
    })
    a50_before = a50_path.read_bytes()
    marker_before = marker_path.read_bytes()
    result = run_migration(ws, "--report", "verdict-caveats", "--report", "a50-access-status-partial")
    assert result.returncode == 0
    # Files unchanged byte-for-byte
    assert a50_path.read_bytes() == a50_before, "A50 CSV mutated by report-only run"
    assert marker_path.read_bytes() == marker_before, "marker mutated by report-only run"
    # No backup files created either
    assert not list(ws.rglob("*.pre-v1.1.bak")), "report-only must not create backups"


def test_parent_workspace_mode_works(tmp_path: Path) -> None:
    """--workspace=<dir containing analysis/> should also work — i.e., the
    operator can point at the workspace root instead of the analysis/
    subdirectory directly. The script and the upstream auditor must
    both handle this."""
    # tmp_path is the parent; tmp_path/analysis is the workspace.
    (tmp_path / "analysis" / "runtime" / "ready").mkdir(parents=True)
    (tmp_path / "analysis" / "canonical" / "core_controls").mkdir(parents=True)
    write_marker(tmp_path / "analysis", "stage1.ready.json", {
        "marker": "stage1.ready",
        "stage": "stage1",
        "emittedAt": "2026-04-22T00:00:00Z",
        "canonPolicyVersion": "1.0.0",
    })
    # Pass parent dir as workspace
    result = run_migration(tmp_path, "--markers-only", "--apply")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads((tmp_path / "analysis/runtime/ready/stage1.ready.json").read_text())
    assert "marker_id" in payload, "marker rename should work in parent-workspace mode"


def test_report_all_kinds_produces_findings(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_marker(ws, "stage3.audit.pass.json", {
        "marker_id": "stage3.audit.pass",
        "stage": "stage3",
        "verdict": "PASS (with caveats)",
        "timestamp": "2026-04-22T00:00:00Z",
        "canon_policy_version": "1.0.0",
        "a51_ref": "A51-001 was resolved",
    })
    write_csv(ws, "canonical/core_controls/A50_source_register.csv",
              ["SourceID", "AccessStatus"], [["S-001", "readable_partial"]])
    write_csv(ws, "canonical/core_controls/A60_negative_evidence_register.csv",
              ["NegID", "Other"], [["N-001", "x"]])
    write_csv(ws, "canonical/core_controls/A51_issue_route_register.csv",
              ["A51Ref", "IssueType", "Severity", "BlockingStatus", "RaisedByStage",
               "RelatedSourceID", "RelatedClaimID", "NextAction", "ResolutionStatus"],
              [["A51-001", "missing_source", "medium", "soft", "stage1", "", "", "x", "open"]])
    result = run_migration(ws, "--report", "all-reports")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS (with caveats)" in result.stdout
    assert "readable_partial" in result.stdout
    assert "NegEvID" in result.stdout  # A60 header mismatch
    assert "A51-001" in result.stdout
