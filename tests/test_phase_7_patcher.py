"""Tests for `scripts/phase_7_patcher.py` (v1.2.19, L2 auto-patcher).

Covers:
  * Reach equality with phase_7_lint helpers (POLICY_GLOBS load,
    glob match, numeric parse). Pinned so the two scripts stay in
    lockstep on shared semantics.
  * Per-proposal validation pipeline (7 gates):
      Gate 1 immutable_conflict (runtime mirror of C5)
      Gate 2 change_class (L1 skipped, unknown rejected)
      Gate 3 tunable_id resolution
      Gate 4 current_value drift
      Gate 5 range
      Gate 6 POLICY_GLOBS safety
      Gate 7 no-op
  * Patch emission: unified-diff format, repo-relative paths,
    line-replace correctness, file-with-no-trailing-newline edge.
  * Atomic write hygiene + idempotency (same bundle → identical output).
  * Safety boundaries: NEVER runs git, NEVER writes outside output_dir.
  * Bundle-level errors raise RuntimeError → CLI returns exit 2.
  * CLI: --workspace / --input / --output-dir / --print-only /
    --quiet / error paths (uninit workspace, missing bundle, etc.).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "phase_7_patcher.py"
LINT_PATH = REPO_ROOT / "scripts" / "phase_7_lint.py"
CANON_PATH = REPO_ROOT / "scripts" / "compute_canon_hash.py"


# ---- Module loaders -------------------------------------------------


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location("phase_7_patcher", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def lint_helper():
    spec = importlib.util.spec_from_file_location("phase_7_lint", LINT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- Workspace + fixture builders -----------------------------------


def _make_workspace(tmp_path: Path) -> Path:
    """Build a synthetic workspace with analysis/ dir + a fake repo
    layout (config/tunables.yaml + scripts/compute_canon_hash.py +
    a tunable source_file the patcher will rewrite)."""
    (tmp_path / "analysis").mkdir(exist_ok=True)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "skills" / "bsa-orchestrator" / "references").mkdir(
        parents=True, exist_ok=True,
    )
    return tmp_path


def _write_canon_globs(workspace: Path, globs: list[str]) -> None:
    """Write a minimal compute_canon_hash.py with a POLICY_GLOBS literal
    the patcher's AST loader can parse."""
    body = (
        "POLICY_GLOBS: tuple[str, ...] = (\n"
        + "".join(f"    {g!r},\n" for g in globs)
        + ")\n"
    )
    (workspace / "scripts" / "compute_canon_hash.py").write_text(
        body, encoding="utf-8"
    )


def _write_tunables(workspace: Path, tunables: list[dict]) -> None:
    """Write config/tunables.yaml with the given entries."""
    doc = {"schema_version": "1.0", "tunables": tunables}
    (workspace / "config" / "tunables.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False), encoding="utf-8",
    )


def _write_source_file(
    workspace: Path,
    rel_path: str,
    *,
    line_with_value: str,
    pad_lines: int = 5,
) -> int:
    """Write a fake source file containing `line_with_value` somewhere
    in the middle. Returns the 1-indexed line number."""
    source = workspace / rel_path
    source.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"context line {i}" for i in range(pad_lines)]
    line_idx = pad_lines  # 0-indexed insertion point
    lines.append(line_with_value)
    lines.extend(f"trailing line {i}" for i in range(pad_lines))
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return line_idx + 1  # 1-indexed


def _write_bundle(workspace: Path, proposals: list[dict]) -> None:
    """Write analysis/telemetry/miner_proposals.json with the given
    proposals (top-level shape mirrors miner_proposal.schema.json)."""
    bundle = {
        "schema_version": "1.0",
        "generated_at": "2026-04-26T10:00:00Z",
        "window": {"window_days": 30, "today_utc": "2026-04-26"},
        "summary": {
            "runs_total": 3, "runs_in_window": 3,
            "runs_excluded_outside_window": 0,
            "runs_excluded_malformed": 0,
            "proposals_count": len(proposals),
            "proposals_immutable_conflict_count": sum(
                1 for p in proposals
                if p.get("immutable_conflict") is True
            ),
        },
        "proposals": proposals,
    }
    target = workspace / "analysis" / "telemetry" / "miner_proposals.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bundle, indent=2), encoding="utf-8")


def _proposal(
    proposal_id: str,
    tunable_id: str,
    *,
    current_value: str = "100",
    proposed_value: str = "150",
    confidence: float = 0.85,
    change_class: str = "L2_proposal_only",
    immutable_conflict: bool = False,
    linked_invariants: list[str] | None = None,
    evidence_run_ids: list[str] | None = None,
    rationale: str = "test rationale",
) -> dict:
    return {
        "proposal_id": proposal_id,
        "tunable_id": tunable_id,
        "current_value": current_value,
        "proposed_value": proposed_value,
        "confidence": confidence,
        "evidence_run_ids": evidence_run_ids or ["run-001a-b2c3"],
        "linked_invariants": linked_invariants or [],
        "change_class": change_class,
        "immutable_conflict": immutable_conflict,
        "rationale": rationale,
    }


def _setup_minimal_tunable_workspace(tmp_path: Path) -> Path:
    """Set up a workspace with one happy-path tunable (no POLICY_GLOBS
    overlap, allowed_range=[50, 200], current_value=100)."""
    workspace = _make_workspace(tmp_path)
    _write_canon_globs(workspace, [
        "governance/immutable_invariants.md",
        "skills/bsa-orchestrator/references/*.md",
    ])
    line_no = _write_source_file(
        workspace,
        "skills/bsa-orchestrator/references/test-contract.md",
        line_with_value="threshold: 100 (default)",
    )
    _write_tunables(workspace, [{
        "id": "test_tunable",
        "current_value": "100",
        "allowed_range": [50, 200],
        "owner_skill": "governance",
        "source_file": "skills/bsa-orchestrator/references/test-contract.md",
        "source_line": line_no,
        "linked_invariants": [],
        "change_class": "L2_proposal_only",
        "rationale": "test",
    }])
    return workspace


# ---- Reach equality with phase_7_lint -------------------------------


def test_reach_equality_with_phase_7_lint_policy_globs(helper, lint_helper) -> None:
    """Pin: phase_7_patcher._load_policy_globs and
    phase_7_lint._read_policy_globs MUST return the same list against
    the live scripts/compute_canon_hash.py. If one drifts, this test
    fires and the maintainer must re-sync — they share semantics by
    design."""
    patcher_globs = helper._load_policy_globs(CANON_PATH)
    lint_globs = lint_helper._read_policy_globs()
    assert patcher_globs == lint_globs


def test_reach_equality_glob_match(helper, lint_helper) -> None:
    """Pin: same fnmatch semantics for representative paths."""
    patterns = ["skills/bsa-*/SKILL.md", "docs/*.md"]
    samples = [
        "skills/bsa-foo/SKILL.md",
        "skills/other/SKILL.md",
        "docs/RELEASING.md",
        "config/tunables.yaml",
    ]
    for s in samples:
        assert (
            (helper._matches_any_glob(s, patterns) is not None)
            == (lint_helper._matches_any_glob(s, patterns) is not None)
        )


def test_reach_equality_numeric_parse(helper, lint_helper) -> None:
    samples = ["0.75", ">= 0.75", "  100  ", "garbage", "≥ 0.9", ""]
    for s in samples:
        assert helper._parse_numeric(s) == lint_helper._parse_numeric(s)


# ---- Tunable index --------------------------------------------------


def test_build_tunable_index_well_formed(helper) -> None:
    doc = {"tunables": [
        {"id": "a", "current_value": "1"},
        {"id": "b", "current_value": "2"},
    ]}
    idx = helper._build_tunable_index(doc)
    assert set(idx.keys()) == {"a", "b"}
    assert idx["a"]["current_value"] == "1"


def test_build_tunable_index_missing_tunables_key(helper) -> None:
    assert helper._build_tunable_index({}) == {}


def test_build_tunable_index_non_list_tunables(helper) -> None:
    assert helper._build_tunable_index({"tunables": "not a list"}) == {}


def test_build_tunable_index_skips_entries_without_id(helper) -> None:
    doc = {"tunables": [
        {"id": "good", "current_value": "1"},
        {"current_value": "no id here"},
        {"id": "", "current_value": "empty id"},
        "not a dict",
    ]}
    idx = helper._build_tunable_index(doc)
    assert set(idx.keys()) == {"good"}


# ---- Validation gates -----------------------------------------------


def test_gate0_proposal_id_path_traversal_rejected(helper) -> None:
    """R1 fix: proposal_id is used as a path component when writing
    `<proposal_id>.patch`. A malformed id like `../escape` would let
    a hostile bundle write outside output_dir. Gate 0 validates the
    id against the schema pattern BEFORE any path is constructed."""
    proposal = _proposal("../escape", "x")
    status, reason = helper._validate_proposal(proposal, {"x": {}}, [])
    assert status == "rejected"
    assert "path-traversal" in reason or "schema pattern" in reason


def test_gate0_proposal_id_with_slash_rejected(helper) -> None:
    proposal = _proposal("P7-OK-0001/../escape", "x")
    status, _ = helper._validate_proposal(proposal, {"x": {}}, [])
    assert status == "rejected"


def test_gate0_proposal_id_with_null_byte_rejected(helper) -> None:
    proposal = _proposal("P7-OK-0001\x00escape", "x")
    status, _ = helper._validate_proposal(proposal, {"x": {}}, [])
    assert status == "rejected"


def test_gate0_proposal_id_lowercase_rejected(helper) -> None:
    """Schema pattern `^P7-[A-Z0-9]{4,12}-[0-9]{4}$` is case-sensitive."""
    proposal = _proposal("p7-test-0001", "x")
    status, _ = helper._validate_proposal(proposal, {"x": {}}, [])
    assert status == "rejected"


def test_gate0_well_formed_proposal_id_passes(helper) -> None:
    """Valid id passes Gate 0 (then proceeds to subsequent gates)."""
    tunable = {
        "id": "x", "current_value": "100", "allowed_range": [50, 200],
        "source_file": "some/file.md", "source_line": 1,
    }
    proposal = _proposal(
        "P7-VALID-0001", "x",
        current_value="100", proposed_value="150",
    )
    status, _ = helper._validate_proposal(proposal, {"x": tunable}, [])
    assert status == "ready"


def test_gate1_immutable_conflict_rejected(helper) -> None:
    proposal = _proposal("P7-T-0001", "x", immutable_conflict=True)
    status, reason = helper._validate_proposal(proposal, {}, [])
    assert status == "rejected"
    assert "immutable_conflict" in reason.lower()


def test_gate2_l1_change_class_skipped(helper) -> None:
    proposal = _proposal(
        "P7-T-0002", "x", change_class="L1_auto_tunable",
    )
    status, reason = helper._validate_proposal(proposal, {"x": {}}, [])
    assert status == "skipped"
    assert "L1_auto_tunable" in reason


def test_gate2_unknown_change_class_rejected(helper) -> None:
    proposal = _proposal(
        "P7-T-0003", "x", change_class="something_else",
    )
    status, _ = helper._validate_proposal(proposal, {"x": {}}, [])
    assert status == "rejected"


def test_gate3_unknown_tunable_id_rejected(helper) -> None:
    proposal = _proposal("P7-T-0004", "missing_tunable")
    status, reason = helper._validate_proposal(proposal, {}, [])
    assert status == "rejected"
    assert "tunable_id" in reason


def test_gate4_current_value_drift_rejected(helper) -> None:
    """Proposal claims current=100 but live tunable has current=120 →
    miner observation is stale, reject."""
    tunable = {
        "id": "x", "current_value": "120", "allowed_range": [50, 200],
        "source_file": "some/file.md", "source_line": 1,
    }
    proposal = _proposal(
        "P7-T-0005", "x", current_value="100", proposed_value="150",
    )
    status, reason = helper._validate_proposal(
        proposal, {"x": tunable}, [],
    )
    assert status == "rejected"
    assert "drift" in reason.lower()


def test_gate5_proposed_value_out_of_range_rejected(helper) -> None:
    tunable = {
        "id": "x", "current_value": "100", "allowed_range": [50, 200],
        "source_file": "some/file.md", "source_line": 1,
    }
    proposal = _proposal(
        "P7-T-0006", "x", current_value="100", proposed_value="500",
    )
    status, reason = helper._validate_proposal(
        proposal, {"x": tunable}, [],
    )
    assert status == "rejected"
    assert "out of allowed_range" in reason


def test_gate5_proposed_value_at_lower_bound_passes(helper) -> None:
    """Inclusive range — proposed_value == lo passes."""
    tunable = {
        "id": "x", "current_value": "100", "allowed_range": [50, 200],
        "source_file": "some/file.md", "source_line": 1,
    }
    proposal = _proposal(
        "P7-T-0007", "x", current_value="100", proposed_value="50",
    )
    status, _ = helper._validate_proposal(proposal, {"x": tunable}, [])
    assert status == "ready"


def test_gate5_proposed_value_at_upper_bound_passes(helper) -> None:
    tunable = {
        "id": "x", "current_value": "100", "allowed_range": [50, 200],
        "source_file": "some/file.md", "source_line": 1,
    }
    proposal = _proposal(
        "P7-T-0008", "x", current_value="100", proposed_value="200",
    )
    status, _ = helper._validate_proposal(proposal, {"x": tunable}, [])
    assert status == "ready"


def test_gate5_non_numeric_proposed_value_rejected(helper) -> None:
    tunable = {
        "id": "x", "current_value": "100", "allowed_range": [50, 200],
        "source_file": "some/file.md", "source_line": 1,
    }
    proposal = _proposal(
        "P7-T-0009", "x", current_value="100", proposed_value="banana",
    )
    status, reason = helper._validate_proposal(
        proposal, {"x": tunable}, [],
    )
    assert status == "rejected"
    assert "not numeric" in reason


def test_gate5_malformed_allowed_range_rejected(helper) -> None:
    tunable = {
        "id": "x", "current_value": "100", "allowed_range": "not a list",
        "source_file": "some/file.md", "source_line": 1,
    }
    proposal = _proposal(
        "P7-T-0010", "x", current_value="100", proposed_value="150",
    )
    status, reason = helper._validate_proposal(
        proposal, {"x": tunable}, [],
    )
    assert status == "rejected"
    assert "malformed allowed_range" in reason


def test_gate6_l2_in_policy_globs_proceeds(helper) -> None:
    """L2_proposal_only entries MAY live in POLICY_GLOBS — analyst
    sign-off includes manifest bump (mirrors phase_7_lint C6)."""
    tunable = {
        "id": "x", "current_value": "100", "allowed_range": [50, 200],
        "source_file": "skills/bsa-orchestrator/references/x.md",
        "source_line": 1,
    }
    proposal = _proposal(
        "P7-T-0011", "x", current_value="100", proposed_value="150",
    )
    status, _ = helper._validate_proposal(
        proposal, {"x": tunable},
        ["skills/bsa-orchestrator/references/*.md"],
    )
    assert status == "ready"


def test_gate6_empty_source_file_rejected(helper) -> None:
    tunable = {
        "id": "x", "current_value": "100", "allowed_range": [50, 200],
        "source_file": "", "source_line": 1,
    }
    proposal = _proposal(
        "P7-T-0012", "x", current_value="100", proposed_value="150",
    )
    status, reason = helper._validate_proposal(
        proposal, {"x": tunable}, [],
    )
    assert status == "rejected"
    assert "source_file" in reason


def test_gate7_no_op_skipped(helper) -> None:
    tunable = {
        "id": "x", "current_value": "100", "allowed_range": [50, 200],
        "source_file": "some/file.md", "source_line": 1,
    }
    proposal = _proposal(
        "P7-T-0013", "x", current_value="100", proposed_value="100",
    )
    status, reason = helper._validate_proposal(
        proposal, {"x": tunable}, [],
    )
    assert status == "skipped"
    assert "no-op" in reason


def test_gate_chain_happy_path(helper) -> None:
    tunable = {
        "id": "x", "current_value": "100", "allowed_range": [50, 200],
        "source_file": "some/file.md", "source_line": 1,
    }
    proposal = _proposal(
        "P7-T-0014", "x", current_value="100", proposed_value="150",
    )
    status, _ = helper._validate_proposal(proposal, {"x": tunable}, [])
    assert status == "ready"


# ---- Patch emission -------------------------------------------------


def test_build_patch_unified_diff_format(helper, tmp_path) -> None:
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    proposal = _proposal(
        "P7-T-0015", "test_tunable",
        current_value="100", proposed_value="150",
    )
    tunables_doc = yaml.safe_load(
        (workspace / "config/tunables.yaml").read_text(encoding="utf-8")
    )
    tunable = helper._build_tunable_index(tunables_doc)["test_tunable"]
    patch = helper._build_patch(workspace, proposal, tunable)
    # Unified diff headers.
    assert patch.startswith("--- a/skills/bsa-orchestrator/references/test-contract.md\n")
    assert "+++ b/skills/bsa-orchestrator/references/test-contract.md\n" in patch
    # Hunk header.
    assert "@@ -" in patch and "+" in patch.split("@@", 2)[1]
    # The actual change.
    assert "-threshold: 100 (default)\n" in patch
    assert "+threshold: 150 (default)\n" in patch


def test_build_patch_replaces_only_first_occurrence_in_line(helper, tmp_path) -> None:
    """`str.replace(..., 1)` semantics — if current_value appears
    twice in the same line, only the first instance is replaced.
    Matters for tunable values that are common substrings."""
    workspace = _make_workspace(tmp_path)
    _write_canon_globs(workspace, [])
    rel = "skills/bsa-orchestrator/references/dup.md"
    line_no = _write_source_file(
        workspace, rel,
        line_with_value="value 100 then 100 again",
    )
    _write_tunables(workspace, [{
        "id": "dup_tunable",
        "current_value": "100",
        "allowed_range": [50, 200],
        "owner_skill": "governance",
        "source_file": rel,
        "source_line": line_no,
        "linked_invariants": [],
        "change_class": "L2_proposal_only",
        "rationale": "test",
    }])
    proposal = _proposal(
        "P7-T-0016", "dup_tunable",
        current_value="100", proposed_value="150",
    )
    tunable = helper._build_tunable_index(
        yaml.safe_load((workspace / "config/tunables.yaml").read_text())
    )["dup_tunable"]
    patch = helper._build_patch(workspace, proposal, tunable)
    assert "+value 150 then 100 again\n" in patch
    assert "+value 150 then 150 again\n" not in patch


def test_build_patch_raises_when_current_value_missing(helper, tmp_path) -> None:
    """If tunables.yaml says current=100 but the source file has 999 at
    that line (drift not caught by phase_7_lint somehow), patch
    generation refuses rather than emitting a no-op or wrong patch."""
    workspace = _make_workspace(tmp_path)
    _write_canon_globs(workspace, [])
    rel = "skills/bsa-orchestrator/references/drift.md"
    line_no = _write_source_file(
        workspace, rel, line_with_value="actual: 999",
    )
    proposal = _proposal(
        "P7-T-0017", "drift_tunable",
        current_value="100", proposed_value="150",
    )
    tunable = {
        "id": "drift_tunable", "current_value": "100",
        "source_file": rel, "source_line": line_no,
    }
    with pytest.raises(RuntimeError, match="not found verbatim"):
        helper._build_patch(workspace, proposal, tunable)


def test_build_patch_rejects_source_without_trailing_newline(helper, tmp_path) -> None:
    """R1 fix: source files without a trailing newline are rejected.
    Unified-diff EOF semantics for missing-newline files require
    `\\ No newline at end of file` markers placed in specific positions
    per old/new line state — getting that wrong yields not-quite-`git
    apply`-able output. Simpler to require the invariant."""
    workspace = _make_workspace(tmp_path)
    rel = "config/no-newline.txt"
    target = workspace / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("ctx\nvalue 100", encoding="utf-8")  # no trailing \n
    proposal = _proposal(
        "P7-T-0018", "nn_tunable",
        current_value="100", proposed_value="150",
    )
    tunable = {
        "id": "nn_tunable", "current_value": "100",
        "source_file": rel, "source_line": 2,
    }
    with pytest.raises(RuntimeError, match="no trailing newline"):
        helper._build_patch(workspace, proposal, tunable)


# ---- Bundle processing ----------------------------------------------


def test_process_bundle_empty_proposals_returns_zero_attempts(
    helper, tmp_path,
) -> None:
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    _write_bundle(workspace, [])
    index = helper.process_bundle(workspace)
    assert index["summary"] == {
        "proposals_total": 0, "patches_written": 0,
        "rejected": 0, "skipped": 0,
    }
    assert index["attempts"] == []


def test_process_bundle_happy_path_writes_patch_and_summary(
    helper, tmp_path,
) -> None:
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    _write_bundle(workspace, [
        _proposal(
            "P7-TEST-0001", "test_tunable",
            current_value="100", proposed_value="150",
        ),
    ])
    index = helper.process_bundle(workspace)
    assert index["summary"]["patches_written"] == 1
    assert index["summary"]["rejected"] == 0
    out_dir = workspace / "analysis/telemetry/proposals"
    assert (out_dir / "P7-TEST-0001.patch").is_file()
    assert (out_dir / "P7-TEST-0001.summary.md").is_file()
    # Summary should reference the patch file + the analyst workflow.
    summary = (out_dir / "P7-TEST-0001.summary.md").read_text(encoding="utf-8")
    assert "P7-TEST-0001.patch" in summary
    assert "git apply" in summary
    # Default location → repo-relative apply path. R4 fix: `--`
    # end-of-options separator before the path so git treats leading-
    # hyphen paths as paths, not options.
    assert "git apply -- analysis/telemetry/proposals/P7-TEST-0001.patch" in summary


def test_process_bundle_mixed_outcomes_count_correctly(
    helper, tmp_path,
) -> None:
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    _write_bundle(workspace, [
        # 1 happy-path → written
        _proposal(
            "P7-OK-0001", "test_tunable",
            current_value="100", proposed_value="150",
        ),
        # 1 immutable_conflict → rejected
        _proposal(
            "P7-IC-0001", "test_tunable",
            current_value="100", proposed_value="150",
            immutable_conflict=True,
        ),
        # 1 L1_auto_tunable → skipped
        _proposal(
            "P7-L1-0001", "test_tunable",
            current_value="100", proposed_value="150",
            change_class="L1_auto_tunable",
        ),
        # 1 unknown tunable → rejected
        _proposal(
            "P7-NK-0001", "no_such_tunable",
            current_value="100", proposed_value="150",
        ),
        # 1 no-op → skipped
        _proposal(
            "P7-NO-0001", "test_tunable",
            current_value="100", proposed_value="100",
        ),
    ])
    index = helper.process_bundle(workspace)
    s = index["summary"]
    assert s["proposals_total"] == 5
    assert s["patches_written"] == 1
    assert s["rejected"] == 2
    assert s["skipped"] == 2
    # Status spread per attempt.
    statuses = {a["proposal_id"]: a["status"] for a in index["attempts"]}
    assert statuses["P7-OK-0001"] == "written"
    assert statuses["P7-IC-0001"] == "rejected"
    assert statuses["P7-L1-0001"] == "skipped"
    assert statuses["P7-NK-0001"] == "rejected"
    assert statuses["P7-NO-0001"] == "skipped"


def test_process_bundle_idempotent(helper, tmp_path) -> None:
    """Running twice on the same bundle produces byte-identical
    patch + summary files (atomic-write hygiene)."""
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    _write_bundle(workspace, [
        _proposal(
            "P7-IDEM-0001", "test_tunable",
            current_value="100", proposed_value="150",
        ),
    ])
    helper.process_bundle(workspace)
    patch_path = workspace / "analysis/telemetry/proposals/P7-IDEM-0001.patch"
    first = patch_path.read_text(encoding="utf-8")
    helper.process_bundle(workspace)
    second = patch_path.read_text(encoding="utf-8")
    assert first == second


def test_process_bundle_missing_bundle_raises(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_canon_globs(workspace, [])
    _write_tunables(workspace, [{
        "id": "x", "current_value": "1", "allowed_range": [0, 2],
        "owner_skill": "governance", "source_file": "x.md",
        "source_line": 1, "linked_invariants": [],
        "change_class": "L2_proposal_only", "rationale": "x",
    }])
    with pytest.raises(RuntimeError, match="not found"):
        helper.process_bundle(workspace)


def test_process_bundle_malformed_json_raises(helper, tmp_path) -> None:
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    target = workspace / "analysis/telemetry/miner_proposals.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not { json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="malformed"):
        helper.process_bundle(workspace)


def test_process_bundle_missing_proposals_key_raises(helper, tmp_path) -> None:
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    target = workspace / "analysis/telemetry/miner_proposals.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"hello": "world"}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="proposals"):
        helper.process_bundle(workspace)


def test_process_bundle_missing_tunables_yaml_raises(helper, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    _write_canon_globs(workspace, [])
    _write_bundle(workspace, [])
    # tunables.yaml deliberately not written.
    with pytest.raises(RuntimeError, match="tunables.yaml"):
        helper.process_bundle(workspace)


def test_process_bundle_non_dict_proposal_recorded_as_rejected(
    helper, tmp_path,
) -> None:
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    target = workspace / "analysis/telemetry/miner_proposals.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "schema_version": "1.0",
        "generated_at": "2026-04-26T10:00:00Z",
        "window": {"window_days": 30, "today_utc": "2026-04-26"},
        "summary": {
            "runs_total": 0, "runs_in_window": 0,
            "runs_excluded_outside_window": 0,
            "runs_excluded_malformed": 0,
            "proposals_count": 1,
            "proposals_immutable_conflict_count": 0,
        },
        "proposals": ["not a dict"],
    }
    target.write_text(json.dumps(bundle), encoding="utf-8")
    index = helper.process_bundle(workspace)
    assert index["summary"]["rejected"] == 1
    assert index["attempts"][0]["status"] == "rejected"


# ---- Safety boundary -----------------------------------------------


def test_patcher_does_not_invoke_git(helper, tmp_path) -> None:
    """The patcher must NOT shell out to git. Search the script's
    source for any subprocess.run('git', ...) call. This is a
    structural pin — the scripted runner is operator-driven, not
    git-mutating."""
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    # Any subprocess invocation at all is suspicious for this script.
    assert "subprocess" not in src, (
        "phase_7_patcher.py imported subprocess — verify that no "
        "git/commit/push call slipped in. Patcher is operator-driven."
    )


def test_patcher_writes_only_inside_output_dir(helper, tmp_path) -> None:
    """All writes go to the output_dir tree. We pin this by checking
    that after a happy-path run, the only new files in the workspace
    are inside analysis/telemetry/proposals/."""
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    _write_bundle(workspace, [
        _proposal(
            "P7-SAFE-0001", "test_tunable",
            current_value="100", proposed_value="150",
        ),
    ])
    # Snapshot file set before.
    before = {p for p in workspace.rglob("*") if p.is_file()}
    helper.process_bundle(workspace)
    # _atomic_write_json for index is CLI-layer; check helper alone
    # only writes patch + summary.
    new_files = {p for p in workspace.rglob("*") if p.is_file()} - before
    out_dir = workspace / "analysis/telemetry/proposals"
    for new_path in new_files:
        assert out_dir in new_path.parents, (
            f"patcher wrote outside output_dir: {new_path}"
        )


def test_patcher_no_tmp_files_left(helper, tmp_path) -> None:
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    _write_bundle(workspace, [
        _proposal(
            "P7-TMP-0001", "test_tunable",
            current_value="100", proposed_value="150",
        ),
    ])
    helper.process_bundle(workspace)
    out_dir = workspace / "analysis/telemetry/proposals"
    leftovers = [
        p.name for p in out_dir.iterdir()
        if p.name.startswith(".phase_7_patcher_")
    ]
    assert leftovers == [], f"tempfile leftovers: {leftovers}"


# ---- CLI ------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_print_only_does_not_write(tmp_path) -> None:
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    _write_bundle(workspace, [
        _proposal(
            "P7-CLI-0001", "test_tunable",
            current_value="100", proposed_value="150",
        ),
    ])
    result = _run_cli("--workspace", str(workspace), "--print-only")
    assert result.returncode == 0
    index = json.loads(result.stdout)
    assert index["summary"]["patches_written"] == 1
    # Patch + summary still written (process_bundle is the call site
    # in --print-only too); the only thing print-only suppresses is
    # the _index.json write. Verify patch was created.
    assert (workspace / "analysis/telemetry/proposals/P7-CLI-0001.patch").is_file()
    # _index.json NOT written under --print-only.
    assert not (workspace / "analysis/telemetry/proposals/_index.json").is_file()


def test_cli_writes_index(tmp_path) -> None:
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    _write_bundle(workspace, [])
    result = _run_cli("--workspace", str(workspace), "--quiet")
    assert result.returncode == 0
    idx = workspace / "analysis/telemetry/proposals/_index.json"
    assert idx.is_file()
    doc = json.loads(idx.read_text(encoding="utf-8"))
    assert doc["summary"]["proposals_total"] == 0


def test_cli_workspace_not_initialized_returns_2(tmp_path) -> None:
    result = _run_cli("--workspace", str(tmp_path), "--print-only")
    assert result.returncode == 2
    assert "not initialized" in result.stderr


def test_cli_missing_bundle_returns_2(tmp_path) -> None:
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    # No bundle written.
    result = _run_cli("--workspace", str(workspace), "--print-only")
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_cli_input_override(tmp_path) -> None:
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    custom_bundle = workspace / "custom_bundle.json"
    custom_bundle.write_text(json.dumps({
        "schema_version": "1.0",
        "generated_at": "2026-04-26T10:00:00Z",
        "window": {"window_days": 30, "today_utc": "2026-04-26"},
        "summary": {
            "runs_total": 0, "runs_in_window": 0,
            "runs_excluded_outside_window": 0,
            "runs_excluded_malformed": 0,
            "proposals_count": 0,
            "proposals_immutable_conflict_count": 0,
        },
        "proposals": [],
    }), encoding="utf-8")
    result = _run_cli(
        "--workspace", str(workspace),
        "--input", str(custom_bundle),
        "--print-only",
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["summary"]["proposals_total"] == 0


def test_cli_output_dir_override(tmp_path) -> None:
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    custom_out = workspace / "custom_out"
    _write_bundle(workspace, [
        _proposal(
            "P7-OD-0001", "test_tunable",
            current_value="100", proposed_value="150",
        ),
    ])
    result = _run_cli(
        "--workspace", str(workspace),
        "--output-dir", str(custom_out),
        "--quiet",
    )
    assert result.returncode == 0
    assert (custom_out / "P7-OD-0001.patch").is_file()
    assert (custom_out / "_index.json").is_file()
    # Default location should NOT have been used.
    assert not (workspace / "analysis/telemetry/proposals/P7-OD-0001.patch").is_file()
    # R2 fix: summary's `git apply` instruction must reference the
    # ACTUAL output dir, not the hardcoded default. Pre-R2 the
    # summary always said `git apply analysis/telemetry/proposals/...`
    # regardless of --output-dir, leading operators to a wrong-path
    # apply command.
    summary = (custom_out / "P7-OD-0001.summary.md").read_text(encoding="utf-8")
    assert "git apply -- custom_out/P7-OD-0001.patch" in summary
    assert "analysis/telemetry/proposals" not in summary.split("git apply")[1].splitlines()[0]


def test_cli_output_dir_leading_hyphen_uses_end_of_options_separator(
    tmp_path,
) -> None:
    """R4 fix: a path that starts with `-` (legal — operator might
    `--output-dir ./-out` for any reason) would be parsed by git as
    an option, not a path, even when shell-quoted. The `--` end-of-
    options separator before the path makes the rendered command
    unambiguous. This regression pins the separator's presence."""
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    # Leading-hyphen output dir.
    custom_out = workspace / "-out"
    _write_bundle(workspace, [
        _proposal(
            "P7-DASH-0001", "test_tunable",
            current_value="100", proposed_value="150",
        ),
    ])
    result = _run_cli(
        "--workspace", str(workspace),
        "--output-dir", str(custom_out),
        "--quiet",
    )
    assert result.returncode == 0
    summary = (custom_out / "P7-DASH-0001.summary.md").read_text(encoding="utf-8")
    apply_line = next(
        line for line in summary.splitlines()
        if line.strip().startswith("git apply")
    )
    # MUST contain `git apply -- ` (end-of-options separator).
    assert "git apply -- " in apply_line, (
        f"expected `git apply -- <path>` form for leading-hyphen path; "
        f"got:\n{apply_line!r}"
    )


def test_cli_output_dir_with_space_shell_quoted_in_summary(tmp_path) -> None:
    """R3 fix: paths in `git apply` / `git diff` snippets MUST be
    shell-quoted so a `--output-dir` containing spaces or shell
    metacharacters produces a copy-pasteable command, not a broken
    one. Without shlex.quote() a path like `/tmp/my proposals/`
    would render as `git apply /tmp/my proposals/P7-FOO-0001.patch`
    which the operator's shell would split into 2 args."""
    workspace = _setup_minimal_tunable_workspace(tmp_path)
    custom_out = workspace / "out with space"  # space → must quote
    _write_bundle(workspace, [
        _proposal(
            "P7-SQ-0001", "test_tunable",
            current_value="100", proposed_value="150",
        ),
    ])
    result = _run_cli(
        "--workspace", str(workspace),
        "--output-dir", str(custom_out),
        "--quiet",
    )
    assert result.returncode == 0
    summary = (custom_out / "P7-SQ-0001.summary.md").read_text(encoding="utf-8")
    # shell-quoted: either single-quoted ('...') or backslash-escaped.
    # Both are valid shlex.quote outputs.
    apply_line = next(
        line for line in summary.splitlines()
        if line.strip().startswith("git apply")
    )
    # The bare unquoted path with space MUST NOT appear; the quoted
    # form (with single quotes around the whole path) MUST.
    bare = "git apply -- out with space/P7-SQ-0001.patch"
    assert bare not in apply_line, (
        f"path with space rendered unquoted; line:\n{apply_line!r}"
    )
    assert "git apply -- 'out with space/P7-SQ-0001.patch'" in apply_line, (
        f"expected `--` separator + single-quoted path; got:\n{apply_line!r}"
    )


def test_cli_output_dir_outside_workspace_does_not_crash(tmp_path) -> None:
    """R1 fix: --output-dir pointing OUTSIDE the workspace tree must
    not crash the CLI after partial writes. Pre-R1,
    `relative_to(workspace)` raised ValueError on the outside path →
    patches written but CLI exited non-zero with a stack trace. Now
    falls back to absolute string in `attempts[].patch_path`."""
    # Build workspace as a sub-directory so we have a sibling location
    # for external_out (truly outside the workspace tree).
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    workspace = _setup_minimal_tunable_workspace(ws_root)
    external_out = tmp_path / "external_proposals"
    _write_bundle(workspace, [
        _proposal(
            "P7-EXT-0001", "test_tunable",
            current_value="100", proposed_value="150",
        ),
    ])
    result = _run_cli(
        "--workspace", str(workspace),
        "--output-dir", str(external_out),
        "--quiet",
    )
    assert result.returncode == 0, (
        f"--output-dir outside workspace must not crash; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert (external_out / "P7-EXT-0001.patch").is_file()
    idx = json.loads((external_out / "_index.json").read_text(encoding="utf-8"))
    # patch_path should be an absolute string (not relative to workspace
    # — which would either crash or be misleading for an external path).
    written = next(a for a in idx["attempts"] if a["status"] == "written")
    assert Path(written["patch_path"]).is_absolute()
    # R2 fix: summary's `git apply` instruction uses the SAME
    # absolute path. Operator pasting it from the external dir gets
    # an apply command that actually works.
    summary = (external_out / "P7-EXT-0001.summary.md").read_text(encoding="utf-8")
    assert f"git apply -- {external_out}/P7-EXT-0001.patch" in summary
