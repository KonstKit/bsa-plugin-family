"""Unit tests for scripts/fixture_runner.py (US-S05-01).

Covers fixture validator invariants plus compare-mode stability. Fixture
`project_0001` is used as the baseline; adversarial copies in tmp_path
exercise specific failure paths.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "fixture_runner.py"
BASELINE = REPO_ROOT / "fixtures" / "golden" / "project_0001"


def run_runner(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False,
    )


def clone_fixture(tmp_path: Path, name: str = "project_0001") -> tuple[Path, Path]:
    fx_root = tmp_path / "golden"
    fx_root.mkdir()
    dest = fx_root / name
    shutil.copytree(BASELINE, dest)
    # Align fixture_metadata.fixture_id with the clone's directory name.
    meta_path = dest / "fixture_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["fixture_id"] = name
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    # Align audit_expectations.fixture_id as well.
    exp_path = dest / "audit_expectations.json"
    exp = json.loads(exp_path.read_text(encoding="utf-8"))
    exp["fixture_id"] = name
    exp_path.write_text(json.dumps(exp, indent=2), encoding="utf-8")
    return fx_root, dest


def rewrite_csv(path: Path, mutator) -> None:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        rows = [dict(r) for r in reader]
    rows = mutator(rows)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_baseline_fixture_passes_validate() -> None:
    result = run_runner("--mode=validate")
    assert result.returncode == 0, result.stderr
    assert "PASS project_0001" in result.stdout


def test_baseline_fixture_passes_compare() -> None:
    result = run_runner("--mode=compare")
    assert result.returncode == 0, result.stderr


def test_baseline_fixture_passes_both() -> None:
    result = run_runner("--mode=both")
    assert result.returncode == 0, result.stderr


def test_a59_missing_evidence_binding_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    a59 = clone / "expected_outputs" / "canonical" / "core_controls" / "A59_claim_register.csv"

    def mutator(rows):
        # Strip SourceID+ExcerptID AND A51Ref from C-001 (direct claim).
        for r in rows:
            if r.get("ClaimID") == "C-001":
                r["SourceID"] = ""
                r["ExcerptID"] = ""
                r["A51Ref"] = ""
        return rows

    rewrite_csv(a59, mutator)
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "evidence-binding" in result.stderr


def test_analyst_judgment_without_justification_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    a59 = clone / "expected_outputs" / "canonical" / "core_controls" / "A59_claim_register.csv"

    def mutator(rows):
        for r in rows:
            if r.get("ClaimID") == "C-008":
                r["JustificationRationale"] = ""  # strip rationale
        return rows

    rewrite_csv(a59, mutator)
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "judgment-missing-justification" in result.stderr


def test_analyst_judgment_without_upstream_claim_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    a59 = clone / "expected_outputs" / "canonical" / "core_controls" / "A59_claim_register.csv"

    def mutator(rows):
        for r in rows:
            if r.get("ClaimID") == "C-008":
                r["JustificationRationale"] = "No upstream claim references here."
        return rows

    rewrite_csv(a59, mutator)
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "judgment-missing-upstream-claim" in result.stderr


def test_unknown_claim_type_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    a59 = clone / "expected_outputs" / "canonical" / "core_controls" / "A59_claim_register.csv"

    def mutator(rows):
        for r in rows:
            if r.get("ClaimID") == "C-001":
                r["ClaimType"] = "hearsay"  # not in allowed set
        return rows

    rewrite_csv(a59, mutator)
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "claim-type-closed" in result.stderr


def test_excerpt_not_found_in_a58_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    a59 = clone / "expected_outputs" / "canonical" / "core_controls" / "A59_claim_register.csv"

    def mutator(rows):
        for r in rows:
            if r.get("ClaimID") == "C-001":
                r["ExcerptID"] = "E-999-does-not-exist"
        return rows

    rewrite_csv(a59, mutator)
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "excerpt-not-found" in result.stderr


def test_a51ref_not_found_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    a59 = clone / "expected_outputs" / "canonical" / "core_controls" / "A59_claim_register.csv"

    def mutator(rows):
        for r in rows:
            if r.get("ClaimID") == "C-005":
                r["A51Ref"] = "A51-999-phantom"
        return rows

    rewrite_csv(a59, mutator)
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "a51-ref-not-found" in result.stderr


def test_a51_missing_severity_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    a51 = clone / "expected_outputs" / "canonical" / "core_controls" / "A51_issue_route_register.csv"

    def mutator(rows):
        rows[0]["Severity"] = ""
        return rows

    rewrite_csv(a51, mutator)
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "a51-missing-field" in result.stderr


def test_marker_missing_canon_policy_version_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    marker = clone / "expected_markers" / "stage1.excerpts.merged.json"
    data = json.loads(marker.read_text(encoding="utf-8"))
    data.pop("canon_policy_version", None)
    marker.write_text(json.dumps(data), encoding="utf-8")
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "marker-field" in result.stderr
    assert "canon_policy_version" in result.stderr


def test_metadata_fixture_id_mismatch_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    meta = clone / "fixture_metadata.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["fixture_id"] = "wrong_id"
    meta.write_text(json.dumps(data), encoding="utf-8")
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "metadata-id-mismatch" in result.stderr


def test_missing_fixture_dir_returns_exit_2(tmp_path: Path) -> None:
    result = run_runner(f"--fixtures-dir={tmp_path}/nope")
    assert result.returncode == 2


def test_selected_fixture_missing_returns_exit_2(tmp_path: Path) -> None:
    fx_root, _ = clone_fixture(tmp_path)
    result = run_runner(f"--fixtures-dir={fx_root}", "--fixture=missing_fixture")
    assert result.returncode == 2


def test_analyst_judgment_without_a51ref_fails(tmp_path: Path) -> None:
    """Round-2 codex: analyst_judgment must satisfy INV-01 binding rule too."""
    fx_root, clone = clone_fixture(tmp_path)
    a59 = clone / "expected_outputs" / "canonical" / "core_controls" / "A59_claim_register.csv"

    def mutator(rows):
        for r in rows:
            if r.get("ClaimID") == "C-008":
                r["SourceID"] = ""
                r["ExcerptID"] = ""
                r["A51Ref"] = ""
        return rows

    rewrite_csv(a59, mutator)
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "evidence-binding" in result.stderr


def test_analyst_judgment_self_only_claim_ref_fails(tmp_path: Path) -> None:
    """Round-2 codex: self-reference does not satisfy the upstream requirement."""
    fx_root, clone = clone_fixture(tmp_path)
    a59 = clone / "expected_outputs" / "canonical" / "core_controls" / "A59_claim_register.csv"

    def mutator(rows):
        for r in rows:
            if r.get("ClaimID") == "C-008":
                r["JustificationRationale"] = "Self-referential rationale mentioning C-008 only."
        return rows

    rewrite_csv(a59, mutator)
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "judgment-missing-upstream-claim" in result.stderr


def test_metadata_missing_model_version_hash_fails(tmp_path: Path) -> None:
    """Round-2 codex: model_version_hash presence is required by AC-5."""
    fx_root, clone = clone_fixture(tmp_path)
    meta = clone / "fixture_metadata.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data.pop("model_version_hash", None)
    meta.write_text(json.dumps(data), encoding="utf-8")
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "metadata-field" in result.stderr
    assert "model_version_hash" in result.stderr


def test_metadata_missing_captured_at_fails(tmp_path: Path) -> None:
    """Retro-round codex: captured_at presence is required by AC-5."""
    fx_root, clone = clone_fixture(tmp_path)
    meta = clone / "fixture_metadata.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data.pop("captured_at", None)
    meta.write_text(json.dumps(data), encoding="utf-8")
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "metadata-field" in result.stderr
    assert "captured_at" in result.stderr


def test_locator_out_of_range_fails(tmp_path: Path) -> None:
    """Round-2 codex minor: locator pointing past file length must fail."""
    fx_root, clone = clone_fixture(tmp_path)
    a58 = clone / "expected_outputs" / "canonical" / "core_controls" / "A58_evidence_excerpts.csv"

    def mutator(rows):
        for r in rows:
            if r.get("ExcerptID") == "E-001":
                r["Locator"] = "source_001_ticket_flow.md:L500"
        return rows

    rewrite_csv(a58, mutator)
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "locator-out-of-range" in result.stderr


def test_locator_bad_shape_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    a58 = clone / "expected_outputs" / "canonical" / "core_controls" / "A58_evidence_excerpts.csv"

    def mutator(rows):
        for r in rows:
            if r.get("ExcerptID") == "E-001":
                r["Locator"] = "not a locator"
        return rows

    rewrite_csv(a58, mutator)
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "locator-shape" in result.stderr


def test_locator_traversal_escape_rejected(tmp_path: Path) -> None:
    """Round-3 codex: locator with '..' that escapes inputs/ must fail."""
    fx_root, clone = clone_fixture(tmp_path)
    a58 = clone / "expected_outputs" / "canonical" / "core_controls" / "A58_evidence_excerpts.csv"

    def mutator(rows):
        for r in rows:
            if r.get("ExcerptID") == "E-001":
                # Points at a real file but outside inputs/
                r["Locator"] = "../fixture_metadata.json:L1"
        return rows

    rewrite_csv(a58, mutator)
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "locator-escapes-inputs" in result.stderr


def test_locator_missing_file_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    a58 = clone / "expected_outputs" / "canonical" / "core_controls" / "A58_evidence_excerpts.csv"

    def mutator(rows):
        for r in rows:
            if r.get("ExcerptID") == "E-001":
                r["Locator"] = "phantom.md:L1"
        return rows

    rewrite_csv(a58, mutator)
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "locator-file-missing" in result.stderr


def test_stage2_baseline_passes(tmp_path: Path) -> None:
    """US-S1-02 AC-2: Stage 2 expected_outputs in baseline fixture pass validation."""
    result = run_runner("--mode=validate")
    assert result.returncode == 0, result.stderr
    # Also confirm stage2 directory exists in the baseline
    stage2 = BASELINE / "expected_outputs" / "canonical" / "stage2"
    assert stage2.is_dir()
    for name in (
        "context_state_frame.md",
        "stakeholder_authority_map.md",
        "system_context_seed.md",
        "constraints_dependencies_route.md",
        "stage2_summary.json",
    ):
        assert (stage2 / name).is_file(), f"Stage 2 artifact missing from baseline: {name}"


def test_stage2_missing_required_header_fails(tmp_path: Path) -> None:
    """US-S1-02 AC-3: removing a required section from context_state_frame fails validate."""
    fx_root, clone = clone_fixture(tmp_path)
    ctx = clone / "expected_outputs" / "canonical" / "stage2" / "context_state_frame.md"
    text = ctx.read_text(encoding="utf-8")
    # Strip the Scope Boundary header line entirely
    mutated = text.replace("## Scope Boundary\n", "")
    ctx.write_text(mutated, encoding="utf-8")
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "stage2-missing-header" in result.stderr
    assert "Scope Boundary" in result.stderr


def test_stage2_missing_required_column_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    sam = clone / "expected_outputs" / "canonical" / "stage2" / "stakeholder_authority_map.md"
    text = sam.read_text(encoding="utf-8")
    mutated = text.replace("authority_level", "level_of_power")
    sam.write_text(mutated, encoding="utf-8")
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "stage2-missing-column" in result.stderr
    assert "authority_level" in result.stderr


def test_stage2_summary_missing_field_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    summary = clone / "expected_outputs" / "canonical" / "stage2" / "stage2_summary.json"
    data = json.loads(summary.read_text(encoding="utf-8"))
    data.pop("stakeholder_count", None)
    summary.write_text(json.dumps(data), encoding="utf-8")
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "stage2-summary-field" in result.stderr
    assert "stakeholder_count" in result.stderr


def test_stage2_summary_wrong_stage_id_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    summary = clone / "expected_outputs" / "canonical" / "stage2" / "stage2_summary.json"
    data = json.loads(summary.read_text(encoding="utf-8"))
    data["stage_id"] = "stage3"
    summary.write_text(json.dumps(data), encoding="utf-8")
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "stage2-summary-stage-id" in result.stderr


def test_stage2_summary_bad_context_mode_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    summary = clone / "expected_outputs" / "canonical" / "stage2" / "stage2_summary.json"
    data = json.loads(summary.read_text(encoding="utf-8"))
    data["context_mode"] = "hybrid"
    summary.write_text(json.dumps(data), encoding="utf-8")
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "stage2-summary-context-mode" in result.stderr


def test_stage2_block_skipped_when_directory_absent(tmp_path: Path) -> None:
    """Presence-gate regression: a fixture without canonical/stage2/ must still pass.

    Protects the Stage 2 validator from becoming accidentally mandatory for
    pre-Sprint-1 style fixtures or downstream-only fixtures. If a future
    refactor makes the block unconditional, this test breaks immediately.
    """
    fx_root, clone = clone_fixture(tmp_path)
    stage2_dir = clone / "expected_outputs" / "canonical" / "stage2"
    shutil.rmtree(stage2_dir)
    # Also remove the Stage 2 marker and the audit_expectations entry so
    # the clone is internally consistent with a no-stage2 fixture.
    stage2_marker = clone / "expected_markers" / "stage2.context_state.pass.json"
    if stage2_marker.is_file():
        stage2_marker.unlink()
    expectations_path = clone / "audit_expectations.json"
    expectations = json.loads(expectations_path.read_text(encoding="utf-8"))
    expectations.get("expected_verdicts", {}).pop("stage2.context_state.pass", None)
    expectations_path.write_text(json.dumps(expectations), encoding="utf-8")
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 0, result.stderr
    assert "stage2-" not in result.stderr


def test_stage2_missing_artifact_fails(tmp_path: Path) -> None:
    fx_root, clone = clone_fixture(tmp_path)
    ctx = clone / "expected_outputs" / "canonical" / "stage2" / "context_state_frame.md"
    ctx.unlink()
    result = run_runner(f"--fixtures-dir={fx_root}", "--mode=validate")
    assert result.returncode == 1
    assert "stage2-missing-file" in result.stderr
    assert "context_state_frame.md" in result.stderr


def test_baseline_has_three_claim_types() -> None:
    """The fixture intentionally exercises every allowed ClaimType (INV-07)."""
    a59 = BASELINE / "expected_outputs" / "canonical" / "core_controls" / "A59_claim_register.csv"
    with a59.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        types = {row["ClaimType"] for row in reader}
    assert types == {"direct", "inference", "analyst_judgment"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
