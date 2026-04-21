"""Unit tests for scripts/validate_no_new_stories.py (Sprint 7 US-S7-03).

Five test groups mirror the reconciliation auditor:

1. Empty / minimal workspace (no A70 → exit 0 silently).
2. Clean case: all stories have upstream provenance + all refs resolve
   + no leaked tokens → exit 0.
3. STORY_PROVENANCE class: row with both SourceClaimIDs and
   RelatedNFRIDs empty (INV-08 violation).
4. STORY_DANGLING_REF class: ClaimID / NFRID referenced but absent
   from A59 / A62.
5. STORY_LEAKAGE class: story text contains significant tokens not
   present in any upstream source.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "validate_no_new_stories.py"


def _write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    """Minimal CSV writer that uses the loader's column order."""
    lines = [",".join(header)]
    for row in rows:
        # Quote values containing commas; otherwise leave bare.
        cells = []
        for h in header:
            v = row.get(h, "")
            if "," in v or '"' in v:
                v_escaped = v.replace('"', '""')
                cells.append(f'"{v_escaped}"')
            else:
                cells.append(v)
        lines.append(",".join(cells))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_workspace(
    tmp_path: Path,
    a59_rows: list[dict[str, str]] | None = None,
    a58_rows: list[dict[str, str]] | None = None,
    a62_rows: list[dict[str, str]] | None = None,
    a70_rows: list[dict[str, str]] | None = None,
) -> Path:
    canonical = tmp_path / "analysis" / "canonical" / "core_controls"
    canonical.mkdir(parents=True)

    if a59_rows:
        _write_csv(
            canonical / "A59_claim_register.csv",
            [
                "ClaimID", "SourceID", "ExcerptID", "ClaimType", "Statement",
                "JustificationRationale", "A51Ref", "ClaimStrength", "Criticality", "Notes",
            ],
            a59_rows,
        )
    if a58_rows:
        _write_csv(
            canonical / "A58_evidence_excerpts.csv",
            ["ExcerptID", "SourceID", "Locator", "ExcerptText", "Notes"],
            a58_rows,
        )
    if a62_rows:
        _write_csv(
            canonical / "A62_nfr_register.csv",
            [
                "NFRID", "NFRCategory", "Statement", "SourceClaimIDs",
                "MeasurabilityType", "Metric", "Target", "TestabilityNotes",
                "Criticality", "A51Ref", "Notes",
            ],
            a62_rows,
        )
    if a70_rows:
        _write_csv(
            canonical / "A70_story_register.csv",
            [
                "StoryID", "Title", "Persona", "StoryText", "AcceptanceCriteria",
                "SourceClaimIDs", "RelatedNFRIDs", "Priority", "EstimationHint",
                "INVESTStatus", "A51Ref", "Notes",
            ],
            a70_rows,
        )

    return tmp_path


def _run(workspace: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(workspace)],
        capture_output=True,
        text=True,
    )


# ---- 1. Empty / minimal ---------------------------------------------


def test_no_a70_returns_ok(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    result = _run(ws)
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_no_analysis_dir_exits_2(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 2


# ---- 2. Clean ------------------------------------------------------


def test_well_formed_story_passes(tmp_path: Path) -> None:
    """Story text uses only tokens present in upstream claim + excerpt."""
    ws = _make_workspace(
        tmp_path,
        a58_rows=[{
            "ExcerptID": "E-001",
            "SourceID": "S-001",
            "Locator": "p.1",
            "ExcerptText": (
                "The triage Ops Lead receives escalation notifications within seconds "
                "of an order timeout and reassigns the order before SLA breach happens."
            ),
            "Notes": "",
        }],
        a59_rows=[{
            "ClaimID": "C-042",
            "SourceID": "S-001",
            "ExcerptID": "E-001",
            "ClaimType": "direct",
            "Statement": (
                "Triage Ops Lead receives escalation notifications within seconds "
                "of an order timeout and reassigns before SLA breach happens."
            ),
            "JustificationRationale": "",
            "A51Ref": "",
            "ClaimStrength": "0.85",
            "Criticality": "level-1",
            "Notes": "",
        }],
        a70_rows=[{
            "StoryID": "STORY-001",
            "Title": "Triage escalation within seconds",
            "Persona": "Triage Ops Lead",
            "StoryText": (
                "As a Triage Ops Lead, I want escalation notifications within seconds "
                "of order timeout, so that reassigns happens before SLA breach."
            ),
            "AcceptanceCriteria": (
                "Escalation notifications within seconds; reassigns before SLA breach."
            ),
            "SourceClaimIDs": "C-042",
            "RelatedNFRIDs": "",
            "Priority": "level-1",
            "EstimationHint": "m",
            "INVESTStatus": "pass",
            "A51Ref": "",
            "Notes": "",
        }],
    )
    result = _run(ws)
    assert result.returncode == 0, (
        f"Well-formed story failed audit.\nstderr={result.stderr}"
    )


# ---- 3. STORY_PROVENANCE class --------------------------------------


def test_provenance_both_empty_flagged(tmp_path: Path) -> None:
    ws = _make_workspace(
        tmp_path,
        a70_rows=[{
            "StoryID": "STORY-001",
            "Title": "Orphan story",
            "Persona": "Triage Ops Lead",
            "StoryText": (
                "As a Triage Ops Lead, I want something, so that it happens."
            ),
            "AcceptanceCriteria": "It works.",
            "SourceClaimIDs": "",
            "RelatedNFRIDs": "",
            "Priority": "level-2",
            "EstimationHint": "m",
            "INVESTStatus": "pass",
            "A51Ref": "",
            "Notes": "",
        }],
    )
    result = _run(ws)
    assert result.returncode == 1
    assert "STORY_PROVENANCE" in result.stderr
    assert "STORY-001" in result.stderr


# ---- 4. STORY_DANGLING_REF class ------------------------------------


def test_dangling_claim_id_flagged(tmp_path: Path) -> None:
    """SourceClaimIDs references a claim not in promoted A59."""
    ws = _make_workspace(
        tmp_path,
        a59_rows=[],  # empty — C-042 won't resolve
        a70_rows=[{
            "StoryID": "STORY-001",
            "Title": "Dangling",
            "Persona": "Triage Ops Lead",
            "StoryText": "As a Triage Ops Lead, I want something, so that it happens.",
            "AcceptanceCriteria": "It works.",
            "SourceClaimIDs": "C-042",
            "RelatedNFRIDs": "",
            "Priority": "level-2",
            "EstimationHint": "m",
            "INVESTStatus": "pass",
            "A51Ref": "",
            "Notes": "",
        }],
    )
    result = _run(ws)
    assert result.returncode == 1
    assert "STORY_DANGLING_REF" in result.stderr
    assert "C-042" in result.stderr


def test_dangling_nfr_id_flagged(tmp_path: Path) -> None:
    ws = _make_workspace(
        tmp_path,
        a62_rows=[],  # empty — NFR-PERF-001 won't resolve
        a70_rows=[{
            "StoryID": "STORY-001",
            "Title": "Dangling NFR",
            "Persona": "Triage Ops Lead",
            "StoryText": "As a Triage Ops Lead, I want something fast, so that latency is low.",
            "AcceptanceCriteria": "Latency low.",
            "SourceClaimIDs": "",
            "RelatedNFRIDs": "NFR-PERF-001",
            "Priority": "level-2",
            "EstimationHint": "m",
            "INVESTStatus": "pass",
            "A51Ref": "",
            "Notes": "",
        }],
    )
    result = _run(ws)
    assert result.returncode == 1
    assert "STORY_DANGLING_REF" in result.stderr
    assert "NFR-PERF-001" in result.stderr


# ---- 5. STORY_LEAKAGE class -----------------------------------------


def test_story_leakage_new_subject_flagged(tmp_path: Path) -> None:
    """Story text introduces a subject ('mobile app') not in upstream claim."""
    ws = _make_workspace(
        tmp_path,
        a58_rows=[{
            "ExcerptID": "E-001",
            "SourceID": "S-001",
            "Locator": "p.1",
            "ExcerptText": (
                "The triage agent reassigns orders via the desktop console."
            ),
            "Notes": "",
        }],
        a59_rows=[{
            "ClaimID": "C-042",
            "SourceID": "S-001",
            "ExcerptID": "E-001",
            "ClaimType": "direct",
            "Statement": "The triage agent reassigns orders via the desktop console.",
            "JustificationRationale": "",
            "A51Ref": "",
            "ClaimStrength": "0.85",
            "Criticality": "level-1",
            "Notes": "",
        }],
        a70_rows=[{
            "StoryID": "STORY-001",
            "Title": "Mobile reassignment",
            "Persona": "Triage Ops Lead",
            "StoryText": (
                # "mobile" and "application" are brand-new tokens not in upstream.
                "As a Triage Ops Lead, I want to reassign orders via mobile application, "
                "so that field deployments work."
            ),
            "AcceptanceCriteria": "Mobile application shows reassignment button.",
            "SourceClaimIDs": "C-042",
            "RelatedNFRIDs": "",
            "Priority": "level-1",
            "EstimationHint": "m",
            "INVESTStatus": "pass",
            "A51Ref": "",
            "Notes": "",
        }],
    )
    result = _run(ws)
    assert result.returncode == 1
    assert "STORY_LEAKAGE" in result.stderr
    assert "STORY-001" in result.stderr
    # The flagged tokens should include "mobile" and/or "application"
    # (both are length >= 4 and not in the stop-list).
    assert "mobile" in result.stderr or "application" in result.stderr


def test_stop_words_not_flagged(tmp_path: Path) -> None:
    """Common filler tokens (that, have, want, feature, etc.) should NOT
    surface as leakage even when they appear in the story but not in
    the source (they're in the stop-word list or below min-length)."""
    ws = _make_workspace(
        tmp_path,
        a58_rows=[{
            "ExcerptID": "E-001",
            "SourceID": "S-001",
            "Locator": "p.1",
            "ExcerptText": "Triage Ops Lead reassigns orders quickly happens.",
            "Notes": "",
        }],
        a59_rows=[{
            "ClaimID": "C-042",
            "SourceID": "S-001",
            "ExcerptID": "E-001",
            "ClaimType": "direct",
            "Statement": "Triage Ops Lead reassigns orders quickly happens.",
            "JustificationRationale": "",
            "A51Ref": "",
            "ClaimStrength": "0.85",
            "Criticality": "level-1",
            "Notes": "",
        }],
        a70_rows=[{
            "StoryID": "STORY-001",
            "Title": "Reassign quickly",
            "Persona": "Triage Ops Lead",
            "StoryText": (
                # Only stop-words + short common words in addition to the
                # upstream subject tokens.
                "As a Triage Ops Lead, I want to reassigns orders quickly, "
                "so that it happens."
            ),
            "AcceptanceCriteria": "Reassigns happens quickly.",
            "SourceClaimIDs": "C-042",
            "RelatedNFRIDs": "",
            "Priority": "level-1",
            "EstimationHint": "m",
            "INVESTStatus": "pass",
            "A51Ref": "",
            "Notes": "",
        }],
    )
    result = _run(ws)
    assert result.returncode == 0, (
        f"False-positive leakage on stop-words.\nstderr={result.stderr}"
    )


def test_nfr_metric_target_counts_as_corpus(tmp_path: Path) -> None:
    """Story acceptance criteria can embed the NFR's Metric/Target (e.g.,
    '500ms') without tripping leakage — those tokens are in the corpus
    via the linked NFR."""
    ws = _make_workspace(
        tmp_path,
        a59_rows=[{
            "ClaimID": "C-042",
            "SourceID": "S-001",
            "ExcerptID": "E-001",
            "ClaimType": "direct",
            "Statement": "Triage system responds quickly under typical load.",
            "JustificationRationale": "",
            "A51Ref": "",
            "ClaimStrength": "0.85",
            "Criticality": "level-1",
            "Notes": "",
        }],
        a62_rows=[{
            "NFRID": "NFR-PERF-001",
            "NFRCategory": "performance",
            "Statement": (
                "Triage system SHALL respond within 500ms latency "
                "under concurrent load."
            ),
            "SourceClaimIDs": "C-042",
            "MeasurabilityType": "quantitative",
            "Metric": "latency",
            "Target": "< 500ms",
            "TestabilityNotes": "load test concurrent.",
            "Criticality": "level-1",
            "A51Ref": "",
            "Notes": "",
        }],
        a70_rows=[{
            "StoryID": "STORY-001",
            "Title": "Fast Triage responds",
            "Persona": "Triage Ops Lead",
            "StoryText": (
                # Tokens present in upstream: Triage / responds (claim),
                # 500ms / latency (NFR Target + Metric), load (claim + NFR),
                # concurrent (NFR).
                "As a Triage Ops Lead, I want Triage responds within 500ms latency, "
                "so that system under load."
            ),
            "AcceptanceCriteria": (
                # latency + 500ms + concurrent all come from NFR corpus.
                "latency below 500ms under concurrent load."
            ),
            "SourceClaimIDs": "C-042",
            "RelatedNFRIDs": "NFR-PERF-001",
            "Priority": "level-1",
            "EstimationHint": "m",
            "INVESTStatus": "pass",
            "A51Ref": "",
            "Notes": "",
        }],
    )
    result = _run(ws)
    assert result.returncode == 0, (
        f"NFR-sourced tokens falsely flagged as leakage.\nstderr={result.stderr}"
    )


def test_multiple_findings_aggregated(tmp_path: Path) -> None:
    ws = _make_workspace(
        tmp_path,
        a70_rows=[
            {
                "StoryID": "STORY-001",
                "Title": "Orphan",
                "Persona": "X",
                "StoryText": "As an X, I want Y, so that Z.",
                "AcceptanceCriteria": "Y happens.",
                "SourceClaimIDs": "",
                "RelatedNFRIDs": "",
                "Priority": "level-2",
                "EstimationHint": "m",
                "INVESTStatus": "pass",
                "A51Ref": "",
                "Notes": "",
            },
            {
                "StoryID": "STORY-002",
                "Title": "Dangling",
                "Persona": "Y",
                "StoryText": "As a Y, I want Z, so that W.",
                "AcceptanceCriteria": "Z happens.",
                "SourceClaimIDs": "C-999",  # dangling
                "RelatedNFRIDs": "",
                "Priority": "level-2",
                "EstimationHint": "m",
                "INVESTStatus": "pass",
                "A51Ref": "",
                "Notes": "",
            },
        ],
    )
    result = _run(ws)
    assert result.returncode == 1
    assert "STORY-001" in result.stderr
    assert "STORY-002" in result.stderr
