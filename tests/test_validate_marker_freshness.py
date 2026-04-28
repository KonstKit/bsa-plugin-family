"""Tests for scripts/validate_marker_freshness.py (v1.3.8 — closes #3.1).

Coverage:
  * Happy path: every marker matches current canon → exit 0, no findings.
  * Stale single marker: stage1 marker hash ≠ current → STALE_MARKER + exit 1.
  * Cascade: stage1 stale → stage2..stage8 markers (all matching current
    hash on their own) flagged DOWNSTREAM_OF_STALE.
  * Pre-hash workspace: marker without canon_policy_version_hash field is
    PRE_HASH_TOLERATED, NOT blocking → exit 0.
  * Discovery chain: same logic, separate cascade pass.
  * Mixed: main + discovery both stale, each cascade computed separately.
  * Empty workspace: no markers → exit 0.
  * Invocation errors: missing workspace, missing canon_policy.json.
  * Override --canon-hash bypasses on-disk read.

Stdlib + pytest only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "validate_marker_freshness.py"


def _make_marker(
    workspace: Path,
    rel: str,
    marker_id: str,
    *,
    stage: str,
    verdict: str = "PASS",
    canon_hash: str = "abcd1234",
    timestamp: str = "2026-04-26T10:00:00Z",
    canon_version: str = "1.3.3",
) -> Path:
    d = workspace / rel
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{marker_id}.json"
    payload = {
        "marker_id": marker_id,
        "stage": stage,
        "verdict": verdict,
        "timestamp": timestamp,
        "canon_policy_version": canon_version,
        "canon_policy_version_hash": canon_hash,
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def _run(workspace: Path, *, canon_hash: str | None = None) -> subprocess.CompletedProcess:
    args: list[str] = [sys.executable, str(SCRIPT), str(workspace)]
    if canon_hash is not None:
        args.extend(["--canon-hash", canon_hash])
    return subprocess.run(args, capture_output=True, text=True, check=False)


# ---- Happy paths --------------------------------------------------------


def test_clean_workspace_passes(tmp_path: Path) -> None:
    """Single marker with matching hash → exit 0, no STALE/DOWNSTREAM."""
    _make_marker(
        tmp_path, "analysis/runtime/ready", "stage1.excerpts.merged",
        stage="stage1", verdict="MERGED", canon_hash="abcd1234",
    )
    res = _run(tmp_path, canon_hash="abcd1234")
    assert res.returncode == 0, f"clean workspace failed: {res.stderr}"
    assert "STALE_MARKER" not in res.stderr
    assert "DOWNSTREAM_OF_STALE" not in res.stderr


def test_empty_workspace_passes(tmp_path: Path) -> None:
    """No markers at all (pre-/bsa-start workspace) → exit 0."""
    res = _run(tmp_path, canon_hash="abcd1234")
    assert res.returncode == 0


# ---- Stale + cascade ----------------------------------------------------


def test_single_stale_marker_blocked(tmp_path: Path) -> None:
    """A stage1 marker with the OLD hash, current is NEW → STALE + exit 1."""
    _make_marker(
        tmp_path, "analysis/runtime/ready", "stage1.excerpts.merged",
        stage="stage1", verdict="MERGED", canon_hash="oldhash1",
    )
    res = _run(tmp_path, canon_hash="newhash1")
    assert res.returncode == 1, f"expected exit 1, got {res.returncode}: {res.stderr}"
    assert "STALE_MARKER" in res.stderr
    assert "stage1.excerpts.merged" in res.stderr
    assert "oldhash1" in res.stderr
    assert "newhash1" in res.stderr


def test_cascade_flags_downstream_markers(tmp_path: Path) -> None:
    """Pre-v1.3.8 the chain validator only checked INTRA-chain hash
    consistency. The bug: stage1 stale (canon shifted), stage2..stage8
    re-emitted with current hash by accident — chain validator passes
    because all markers agree, but stage2..stage8 preconditions are no
    longer guaranteed (the upstream stage1 was emitted under different
    canon). v1.3.8 cascade catches it: stage1 STALE +
    stage2..stage8 DOWNSTREAM_OF_STALE."""
    # stage1 stale (old hash)
    _make_marker(
        tmp_path, "analysis/runtime/ready", "stage1.excerpts.merged",
        stage="stage1", verdict="MERGED", canon_hash="oldhash1",
    )
    # stage2..stage8 with NEW hash (each "innocent" individually)
    for stage_n, mid, stage in [
        (2, "stage2.context_state.pass", "stage2"),
        (3, "stage3.citation_audit.pass", "stage3"),
        (5, "stage5.anchor_audit.pass", "stage5"),
        (6, "stage6.anchor_audit.pass", "stage6"),
        (7, "stage7.skeptical_review.pass", "stage7"),
        (8, "stage8.no_new_claims.pass", "stage8"),
    ]:
        _make_marker(
            tmp_path, "analysis/runtime/ready", mid,
            stage=stage, canon_hash="newhash1",
            timestamp=f"2026-04-26T10:0{stage_n}:00Z",
        )
    res = _run(tmp_path, canon_hash="newhash1")
    assert res.returncode == 1
    # Exactly one STALE_MARKER (stage1)
    stale_lines = [l for l in res.stderr.splitlines() if "STALE_MARKER" in l]
    assert len(stale_lines) == 1
    assert "stage1.excerpts.merged" in stale_lines[0]
    # Six DOWNSTREAM_OF_STALE (stage2..stage8 — but chain seq has 7 entries
    # excluding stage1; we have all 6 of those past stage1 = stage2/3/5/6/7/8)
    downstream = [l for l in res.stderr.splitlines() if "DOWNSTREAM_OF_STALE" in l]
    assert len(downstream) == 6, (
        f"expected 6 downstream-of-stale findings, got {len(downstream)}: "
        f"{downstream}"
    )
    # Sanity: each downstream finding cites stage1 as the upstream
    # stale point.
    for d in downstream:
        assert "stage1.excerpts.merged" in d, (
            f"downstream finding doesn't cite the stale upstream: {d}"
        )


def test_cascade_truncates_at_earliest_stale(tmp_path: Path) -> None:
    """When BOTH stage1 AND stage3 are stale, the cascade should anchor
    on stage1 (earliest) — stage3 is reported STALE_MARKER, not
    DOWNSTREAM_OF_STALE (don't double-report)."""
    _make_marker(
        tmp_path, "analysis/runtime/ready", "stage1.excerpts.merged",
        stage="stage1", verdict="MERGED", canon_hash="old1",
    )
    _make_marker(
        tmp_path, "analysis/runtime/ready", "stage2.context_state.pass",
        stage="stage2", canon_hash="newh", timestamp="2026-04-26T10:02:00Z",
    )
    _make_marker(
        tmp_path, "analysis/runtime/ready", "stage3.citation_audit.pass",
        stage="stage3", canon_hash="old2", timestamp="2026-04-26T10:03:00Z",
    )
    res = _run(tmp_path, canon_hash="newh")
    assert res.returncode == 1
    # stage1 + stage3 are STALE (both have wrong hash)
    stale = [l for l in res.stderr.splitlines() if "STALE_MARKER" in l]
    assert len(stale) == 2
    # stage2 is DOWNSTREAM (matches current hash but stage1 is upstream stale)
    downstream = [l for l in res.stderr.splitlines() if "DOWNSTREAM_OF_STALE" in l]
    assert len(downstream) == 1
    assert "stage2.context_state.pass" in downstream[0]


# ---- Pre-hash workspace tolerance --------------------------------------


def test_pre_hash_marker_tolerated_not_blocking(tmp_path: Path) -> None:
    """A marker without canon_policy_version_hash (pre-Sprint-3) is
    informational, not a failure. Exit 0."""
    d = tmp_path / "analysis/runtime/ready"
    d.mkdir(parents=True)
    payload = {
        "marker_id": "stage1.excerpts.merged",
        "stage": "stage1",
        "verdict": "MERGED",
        "timestamp": "2026-04-26T10:00:00Z",
        "canon_policy_version": "0.95",
        # no canon_policy_version_hash
    }
    (d / "stage1.excerpts.merged.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    res = _run(tmp_path, canon_hash="abcd1234")
    assert res.returncode == 0
    assert "PRE_HASH_TOLERATED" in res.stderr
    assert "STALE_MARKER" not in res.stderr


def test_pre_hash_marker_does_not_seed_cascade(tmp_path: Path) -> None:
    """A pre-hash stage1 marker should NOT seed the cascade for
    downstream stages. Pre-hash means "we don't know if it's stale" —
    not "it's definitely stale". Cascading on uncertainty would
    over-block legacy workspaces."""
    d = tmp_path / "analysis/runtime/ready"
    d.mkdir(parents=True)
    pre_hash = {
        "marker_id": "stage1.excerpts.merged",
        "stage": "stage1",
        "verdict": "MERGED",
        "timestamp": "2026-04-26T10:00:00Z",
        "canon_policy_version": "0.95",
    }
    (d / "stage1.excerpts.merged.json").write_text(
        json.dumps(pre_hash), encoding="utf-8"
    )
    _make_marker(
        tmp_path, "analysis/runtime/ready", "stage2.context_state.pass",
        stage="stage2", canon_hash="newh", timestamp="2026-04-26T10:02:00Z",
    )
    res = _run(tmp_path, canon_hash="newh")
    assert res.returncode == 0
    assert "DOWNSTREAM_OF_STALE" not in res.stderr


# ---- Discovery chain ---------------------------------------------------


def test_discovery_chain_cascade_independent_of_main(tmp_path: Path) -> None:
    """Main and discovery chains compute cascades independently. A
    stale main-cycle marker MUST NOT cascade into discovery markers
    (different prefix sequence)."""
    # Main stage1 stale
    _make_marker(
        tmp_path, "analysis/runtime/ready", "stage1.excerpts.merged",
        stage="stage1", verdict="MERGED", canon_hash="oldh",
    )
    # Discovery d1 fresh (matches current)
    _make_marker(
        tmp_path, "analysis/discovery/runtime/ready", "discovery.d1.ready",
        stage="d1", verdict="READY", canon_hash="newh",
    )
    res = _run(tmp_path, canon_hash="newh")
    assert res.returncode == 1  # main stage1 still stale
    # discovery.d1.ready not in audit-pass sequence (it's a ready marker
    # not an audit-pass), so it doesn't participate in cascade. Sanity:
    # no DOWNSTREAM finding cites discovery markers.
    for line in res.stderr.splitlines():
        if "DOWNSTREAM_OF_STALE" in line:
            assert "discovery." not in line


def test_discovery_chain_internal_cascade(tmp_path: Path) -> None:
    """Discovery's own cascade: d2.claims.merged stale → d3 / d4 / d5
    audit-pass markers flagged DOWNSTREAM_OF_STALE."""
    _make_marker(
        tmp_path, "analysis/discovery/runtime/ready", "discovery.d2.claims.merged",
        stage="d2", verdict="MERGED", canon_hash="oldh",
    )
    _make_marker(
        tmp_path, "analysis/discovery/runtime/ready", "discovery.d2.research_quality.pass",
        stage="d2", canon_hash="newh", timestamp="2026-04-26T10:02:30Z",
    )
    _make_marker(
        tmp_path, "analysis/discovery/runtime/ready", "discovery.d3.prioritization.pass",
        stage="d3", canon_hash="newh", timestamp="2026-04-26T10:03:00Z",
    )
    res = _run(tmp_path, canon_hash="newh")
    assert res.returncode == 1
    downstream = [l for l in res.stderr.splitlines() if "DOWNSTREAM_OF_STALE" in l]
    # research_quality.pass + d3 (both later in discovery sequence than d2.claims.merged)
    assert len(downstream) == 2


# ---- CLI / invocation --------------------------------------------------


def test_missing_workspace_exits_2(tmp_path: Path) -> None:
    res = _run(tmp_path / "nonexistent", canon_hash="abcd1234")
    assert res.returncode == 2


def test_no_canon_hash_no_canon_policy_file_exits_2(tmp_path: Path) -> None:
    """Without --canon-hash AND without a readable canon_policy.json
    (pointed via --plugin-repo to an empty dir), the script exits 2."""
    empty_repo = tmp_path / "empty-plugin-repo"
    empty_repo.mkdir()
    res = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path), "--plugin-repo", str(empty_repo)],
        capture_output=True, text=True, check=False,
    )
    assert res.returncode == 2
    assert "canon_policy.json" in res.stderr


def test_default_canon_hash_read_from_real_plugin_repo(tmp_path: Path) -> None:
    """Default --plugin-repo points at the real plugin repo; the script
    reads .claude-plugin/canon_policy.json::hash_full and validates
    against it. This is the production code path."""
    # Empty workspace ensures no STALE/DOWNSTREAM, so the only thing we
    # exercise is the canon-hash read.
    res = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert res.returncode == 0


# ---- Malformed input ---------------------------------------------------


def test_present_but_empty_canon_hash_treated_as_stale(tmp_path: Path) -> None:
    """v1.3.8 R1 (Codex MAJOR): pre-fix `canon_policy_version_hash: ""`
    was treated as PRE_HASH_TOLERATED (not blocking). That let a
    corrupted modern marker silently bypass both the freshness gate
    AND the cascade seed. Post-fix: present-but-invalid is STALE."""
    d = tmp_path / "analysis/runtime/ready"
    d.mkdir(parents=True)
    payload = {
        "marker_id": "stage1.excerpts.merged",
        "stage": "stage1",
        "verdict": "MERGED",
        "timestamp": "2026-04-26T10:00:00Z",
        "canon_policy_version": "1.3.3",
        "canon_policy_version_hash": "",  # present but empty
    }
    (d / "stage1.excerpts.merged.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    res = _run(tmp_path, canon_hash="abcd1234")
    assert res.returncode == 1, (
        f"empty hash must block, not tolerate; got {res.returncode}: {res.stderr}"
    )
    assert "STALE_MARKER" in res.stderr
    assert "PRE_HASH_TOLERATED" not in res.stderr
    assert "present but invalid" in res.stderr


def test_present_but_non_string_canon_hash_treated_as_stale(tmp_path: Path) -> None:
    """Companion to the empty-string case: type-violation values (None,
    list, int) are also corrupted-marker, not pre-hash."""
    d = tmp_path / "analysis/runtime/ready"
    d.mkdir(parents=True)
    payload = {
        "marker_id": "stage1.excerpts.merged",
        "stage": "stage1",
        "verdict": "MERGED",
        "timestamp": "2026-04-26T10:00:00Z",
        "canon_policy_version": "1.3.3",
        "canon_policy_version_hash": None,  # present but null
    }
    (d / "stage1.excerpts.merged.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    res = _run(tmp_path, canon_hash="abcd1234")
    assert res.returncode == 1
    assert "STALE_MARKER" in res.stderr
    assert "present but invalid" in res.stderr


def test_invalid_hash_marker_seeds_cascade(tmp_path: Path) -> None:
    """v1.3.8 R1 corollary: a STALE-via-corruption marker must seed the
    downstream cascade just like a STALE-via-mismatch marker. Otherwise
    the corruption fix would block ONE marker but let the chain
    proceed past it."""
    d = tmp_path / "analysis/runtime/ready"
    d.mkdir(parents=True)
    # stage1 corrupted (empty hash)
    bad = {
        "marker_id": "stage1.excerpts.merged",
        "stage": "stage1",
        "verdict": "MERGED",
        "timestamp": "2026-04-26T10:00:00Z",
        "canon_policy_version": "1.3.3",
        "canon_policy_version_hash": "",
    }
    (d / "stage1.excerpts.merged.json").write_text(
        json.dumps(bad), encoding="utf-8"
    )
    # stage2 fresh (current hash)
    _make_marker(
        tmp_path, "analysis/runtime/ready", "stage2.context_state.pass",
        stage="stage2", canon_hash="abcd1234",
        timestamp="2026-04-26T10:02:00Z",
    )
    res = _run(tmp_path, canon_hash="abcd1234")
    assert res.returncode == 1
    assert "STALE_MARKER" in res.stderr
    assert "DOWNSTREAM_OF_STALE" in res.stderr
    # Sanity: the downstream finding cites stage1 as the upstream stale point.
    downstream_lines = [l for l in res.stderr.splitlines() if "DOWNSTREAM_OF_STALE" in l]
    assert any("stage1.excerpts.merged" in l for l in downstream_lines)


def test_malformed_marker_json_exits_2(tmp_path: Path) -> None:
    d = tmp_path / "analysis/runtime/ready"
    d.mkdir(parents=True)
    (d / "stage1.excerpts.merged.json").write_text("{not valid json", encoding="utf-8")
    res = _run(tmp_path, canon_hash="abcd1234")
    assert res.returncode == 2
    assert "malformed marker" in res.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
