#!/usr/bin/env python3
"""Marker chain validator (US-S3-05).

Verifies the integrity of a runtime marker set — the JSON files under
``analysis/runtime/ready/`` (plus the discovery variant) that record
per-stage pass/ready events. The validator enforces:

1. Every marker JSON has the required payload fields (marker_id,
   stage, verdict, canon_policy_version). `timestamp` is recommended
   but not strictly required for pre-Sprint-3 compatibility — its
   absence only blocks monotonicity checks, not the whole validation.
2. The emitted markers form a valid **prefix** of the mandatory
   main-cycle sequence (stage1 → stage2 → stage3 → stage5 → stage6
   → stage7 → stage8) OR the discovery sequence (d1 → d2 → d3 → d4
   → d5 → discovery.exit → discovery.go).
3. No stage appears twice in the chain.
4. Timestamps on the chain are monotonic non-decreasing.
5. All markers in a chain carry the same ``canon_policy_version`` and
   (when Sprint-3+ hash field is present) the same
   ``canon_policy_version_hash``. Pre-Sprint-3 markers without the
   hash are tolerated — missing hash is treated as "pre-hash
   workspace", not a failure.

Exit codes:
  0 — all chains valid.
  1 — at least one chain finding (prefix gap, duplicate stage, bad
      timestamp, hash mismatch, missing required field).
  2 — invocation error (missing directory, malformed JSON).

Stdlib-only.

CLI:
  scripts/validate_marker_chain.py <markers_dir>
  scripts/validate_marker_chain.py fixtures/golden/project_0001/expected_markers/

Main-cycle mandatory sequence (in order):
  stage1.excerpts.merged
  stage2.context_state.pass
  stage3.citation_audit.pass
  stage5.anchor_audit.pass
  stage6.anchor_audit.pass
  stage7.skeptical_review.pass
  stage8.no_new_claims.pass

Discovery sequence (in order):
  discovery.d1.ready
  discovery.d2.claims.merged
  discovery.d2.research_quality.pass
  discovery.d3.prioritization.pass
  discovery.d4.constraint_audit.pass
  discovery.d5.citation_audit.pass
  discovery.d5.no_solution_leakage.pass
  discovery.exit.pass
  discovery.go

The validator identifies the chain by marker-id prefix: ``discovery.*``
markers go into the discovery chain, everything else into the main
chain. An empty chain is valid (pre-start workspace).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# F1 (Sprint 5): single source of truth for marker alphabet + audit-pass
# sequences is governance/schemas/marker.schema.json, accessed via the
# loader below. The script's previous private MAIN_CYCLE_SEQUENCE /
# DISCOVERY_SEQUENCE tuples drifted from the documented schema (they
# only knew the seven audit-pass markers and rejected stage*.ready,
# handoff.ready, pipeline.complete, and bsa.stage1.entry.enabled even
# though all of those are valid markers per runtime-marker-schema.md).
# Adding a new marker now requires editing the schema only — never this
# file.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from governance.schemas import loader as _schema_loader  # noqa: E402

MAIN_CYCLE_SEQUENCE: tuple[str, ...] = _schema_loader.audit_pass_sequence("main")
DISCOVERY_SEQUENCE: tuple[str, ...] = _schema_loader.audit_pass_sequence("discovery")
_MARKER_ALPHABET: frozenset[str] = frozenset(_schema_loader.marker_id_alphabet())
_BRIDGE_MARKERS: frozenset[str] = frozenset(_schema_loader.bridge_markers())
_END_STATE_MARKERS: frozenset[str] = frozenset(_schema_loader.end_state_markers())
_READY_MARKERS: frozenset[str] = frozenset(_schema_loader.ready_markers())
_DECISION_MARKERS: frozenset[str] = frozenset(_schema_loader.decision_markers())

REQUIRED_FIELDS: tuple[str, ...] = (
    "marker_id",
    "stage",
    "verdict",
    "canon_policy_version",
)


@dataclass
class Finding:
    code: str
    message: str

    def format(self) -> str:
        return f"[{self.code}] {self.message}"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def add(self, code: str, message: str) -> None:
        self.findings.append(Finding(code, message))


def _load_markers(markers_dir: Path, report: Report) -> list[dict]:
    if not markers_dir.is_dir():
        report.add("missing-markers-dir", f"markers directory not found: {markers_dir}")
        return []
    docs: list[dict] = []
    for path in sorted(markers_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.add("marker-parse", f"{path.name}: invalid JSON: {exc}")
            continue
        except UnicodeDecodeError as exc:
            report.add("marker-parse", f"{path.name}: unicode decode error: {exc}")
            continue
        if not isinstance(data, dict):
            report.add("marker-shape", f"{path.name}: top-level must be object")
            continue
        # Tag with on-disk filename so downstream messages can cite it.
        data.setdefault("_source_file", path.name)
        docs.append(data)
    return docs


def _validate_required_fields(markers: list[dict], report: Report) -> None:
    for m in markers:
        fname = m.get("_source_file", "?")
        for field_name in REQUIRED_FIELDS:
            if field_name not in m:
                report.add(
                    "marker-schema",
                    f"{fname}: missing required field '{field_name}'",
                )


def _split_chains(markers: list[dict]) -> tuple[list[dict], list[dict]]:
    """Partition markers into (main_chain, discovery_chain).

    Routing rules:
      - discovery.* (including discovery.go/pivot/more_research/no_go) → discovery
      - bsa.stage1.entry.enabled (bridge) → discovery (it is the discovery-exit
        side-effect that unlocks main cycle entry).
      - everything else (stage1..stage8 + handoff.* + pipeline.*) → main
    """
    main: list[dict] = []
    discovery: list[dict] = []
    for m in markers:
        mid = m.get("marker_id", "")
        if mid.startswith("discovery.") or mid in _BRIDGE_MARKERS:
            discovery.append(m)
        else:
            main.append(m)
    return main, discovery


def _validate_chain(
    markers: list[dict],
    sequence: tuple[str, ...],
    chain_label: str,
    report: Report,
) -> None:
    """Validate a single chain against its mandatory sequence.

    markers order doesn't matter coming in — we reorder by
    sequence-position and check for gaps / duplicates / timestamp
    monotonicity.
    """
    if not markers:
        return  # empty chain is valid (pre-start workspace)

    # Index markers by marker_id.
    by_id: dict[str, list[dict]] = {}
    for m in markers:
        mid = m.get("marker_id", "")
        by_id.setdefault(mid, []).append(m)

    # Check duplicates.
    for mid, rows in by_id.items():
        if len(rows) > 1:
            fnames = ", ".join(r.get("_source_file", "?") for r in rows)
            report.add(
                "chain-duplicate",
                f"{chain_label}: marker_id '{mid}' appears {len(rows)} times ({fnames})",
            )

    # Two-tier check (F1 fix, Sprint 5):
    #   1. Marker must be in the overall marker_id alphabet (schema-defined).
    #      Anything outside the alphabet is a hard failure — that is the
    #      class of drift the schema exists to catch (e.g. legacy
    #      camelCase markers, no_new_facts naming, ad-hoc synthetic IDs).
    #   2. Whether the marker is in the GATING sequence is a separate
    #      question. Stage-ready markers (stage1.ready, ...), end-state
    #      markers (handoff.ready, pipeline.complete), bridge marker
    #      (bsa.stage1.entry.enabled), and the non-go decision markers
    #      (discovery.pivot/more_research/no_go) are all valid markers
    #      that should NOT be flagged as chain errors merely because
    #      they are not part of the audit-pass gating chain.
    seq_positions: dict[str, int] = {mid: i for i, mid in enumerate(sequence)}
    present_positions: list[int] = []
    for m in markers:
        mid = m.get("marker_id", "")
        if mid not in _MARKER_ALPHABET:
            # Not in any documented alphabet — hard reject.
            report.add(
                "chain-unknown-marker",
                f"{chain_label}: marker_id '{mid}' is not in the documented alphabet "
                f"(governance/schemas/marker.schema.json). Ad-hoc, drifted, or legacy IDs are rejected.",
            )
            continue
        if mid not in seq_positions:
            # In alphabet but not part of the gating sequence (ready /
            # end-state / bridge / non-go decision). Accept silently —
            # these markers are informational for chain-completeness
            # purposes and do not occupy a position in the prefix check.
            continue
        present_positions.append(seq_positions[mid])
    if not present_positions:
        return
    present_positions_set = set(present_positions)

    # Must form a prefix: highest position H implies all positions 0..H are present.
    max_pos = max(present_positions_set)
    missing_prefix = [sequence[i] for i in range(max_pos + 1) if i not in present_positions_set]
    if missing_prefix:
        # Report the first gap (most actionable).
        first_missing = missing_prefix[0]
        first_missing_pos = sequence.index(first_missing)
        # Find the earliest marker after the gap that IS present.
        later_present = [
            sequence[i] for i in range(first_missing_pos + 1, max_pos + 1)
            if i in present_positions_set
        ]
        later_label = later_present[0] if later_present else sequence[max_pos]
        report.add(
            "chain-gap",
            f"{chain_label}: {first_missing} missing before {later_label}",
        )

    # Timestamp monotonicity (only across present markers, in sequence order).
    ordered = sorted(
        (m for m in markers if m.get("marker_id") in seq_positions),
        key=lambda m: seq_positions[m["marker_id"]],
    )
    prev_ts: str | None = None
    prev_label: str | None = None
    for m in ordered:
        ts = m.get("timestamp")
        if not isinstance(ts, str):
            # Missing timestamp is soft — just can't check monotonicity here.
            continue
        if prev_ts is not None and ts < prev_ts:
            report.add(
                "chain-timestamp",
                f"{chain_label}: {m['marker_id']} timestamp {ts} is earlier than "
                f"preceding {prev_label} {prev_ts} (non-monotonic)",
            )
        prev_ts = ts
        prev_label = m["marker_id"]

    # canon_policy_version consistency.
    versions = {m.get("canon_policy_version") for m in ordered}
    versions.discard(None)
    if len(versions) > 1:
        report.add(
            "chain-version-inconsistent",
            f"{chain_label}: canon_policy_version differs across chain: {sorted(versions)}",
        )

    # canon_policy_version_hash consistency (Sprint-3+, tolerant).
    hashes = {m.get("canon_policy_version_hash") for m in ordered if m.get("canon_policy_version_hash")}
    # Only flag if present markers disagree; missing field is pre-hash workspace.
    if len(hashes) > 1:
        report.add(
            "chain-hash-inconsistent",
            f"{chain_label}: canon_policy_version_hash differs across chain: {sorted(hashes)}",
        )


def validate_markers_dir(markers_dir: Path) -> Report:
    report = Report()
    markers = _load_markers(markers_dir, report)
    # Bail on outright I/O failure but keep going on per-file parse errors.
    if any(f.code == "missing-markers-dir" for f in report.findings):
        return report
    _validate_required_fields(markers, report)
    main_chain, discovery_chain = _split_chains(markers)
    _validate_chain(main_chain, MAIN_CYCLE_SEQUENCE, "main", report)
    _validate_chain(discovery_chain, DISCOVERY_SEQUENCE, "discovery", report)
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Validate BSA runtime marker chain integrity (US-S3-05)."
    )
    parser.add_argument(
        "markers_dir",
        type=Path,
        help=(
            "Directory containing marker JSON files (e.g. "
            "analysis/runtime/ready/ or a fixture's expected_markers/)."
        ),
    )
    args = parser.parse_args(argv)

    report = validate_markers_dir(args.markers_dir)

    # Surface findings on stderr so clean-output piping is unaffected.
    for f in report.findings:
        print(f.format(), file=sys.stderr)

    if any(f.code == "missing-markers-dir" for f in report.findings):
        return 2
    if report.findings:
        return 1
    print(f"OK: marker chain valid ({args.markers_dir})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
