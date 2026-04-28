#!/usr/bin/env python3
"""Marker freshness + cascade validator (v1.3.8 — closes output review #3.1).

Detects the class of governance drift first observed when a v1.3.7 user
ran `/bsa-promote stage5` after a canon-policy edit had landed between
stage3 and stage5: the stage5 promote succeeded against the new canon,
but the stage3 marker on disk still carried the OLD canon hash. Nothing
in the existing chain validator (`scripts/validate_marker_chain.py`)
caught it because that validator only checks INTRA-chain hash
consistency — it doesn't compare any marker to the CURRENT canon hash.

This auditor closes the gap with two checks:

  1. **Per-marker freshness** — every marker's `canon_policy_version_hash`
     MUST match the current `.claude-plugin/canon_policy.json` `hash_full`
     prefix. A mismatch is `STALE_MARKER`. Markers without the hash
     field (pre-Sprint-3 / pre-hash workspace) are tolerated as
     `PRE_HASH_TOLERATED`, not failures.

  2. **Cascade** — within each chain (main / discovery), if any marker
     is STALE, every LATER-stage marker is flagged as
     `DOWNSTREAM_OF_STALE` even when its own hash matches the current
     canon. Reasoning: that downstream marker was emitted under a
     stage-precondition assumption (the upstream marker was valid at
     the time); once the upstream marker is invalidated by a canon
     shift, the downstream marker's preconditions are no longer
     guaranteed and the entire chain prefix needs re-promotion. A
     downstream marker that happens to carry the new hash got there by
     coincidence, not by design.

Inputs:
    `<workspace>/analysis/runtime/ready/*.json` (main-cycle markers)
    `<workspace>/analysis/discovery/runtime/ready/*.json` (discovery)
    `<plugin_repo>/.claude-plugin/canon_policy.json` (current hash)

Output:
    Findings on stderr, one per stale or downstream marker. Exit 0 on
    clean (or only PRE_HASH_TOLERATED), 1 on any STALE_MARKER /
    DOWNSTREAM_OF_STALE, 2 on invocation error (workspace missing,
    canon_policy.json unreadable, malformed marker JSON).

CLI:
    scripts/validate_marker_freshness.py <workspace_root>
    scripts/validate_marker_freshness.py <workspace_root> --canon-hash <prefix>
        # Override the on-disk canon hash — useful for tests or for
        # checking against a future hash before running the canon-bump.

Stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from governance.schemas import loader as _schema_loader  # noqa: E402

MAIN_CYCLE_SEQUENCE: tuple[str, ...] = _schema_loader.audit_pass_sequence("main")
DISCOVERY_SEQUENCE: tuple[str, ...] = _schema_loader.audit_pass_sequence("discovery")


@dataclass
class Finding:
    code: str  # STALE_MARKER | DOWNSTREAM_OF_STALE | PRE_HASH_TOLERATED | invocation
    marker_path: Path | None
    marker_id: str | None
    detail: str

    def format(self) -> str:
        loc = f" {self.marker_path}" if self.marker_path else ""
        mid = f" {self.marker_id}" if self.marker_id else ""
        return f"[{self.code}]{loc}{mid}: {self.detail}"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    @property
    def has_blocking(self) -> bool:
        """STALE / DOWNSTREAM are blocking; PRE_HASH_TOLERATED is not."""
        return any(
            f.code in ("STALE_MARKER", "DOWNSTREAM_OF_STALE") for f in self.findings
        )

    def add(
        self,
        code: str,
        marker_path: Path | None,
        marker_id: str | None,
        detail: str,
    ) -> None:
        self.findings.append(Finding(code, marker_path, marker_id, detail))


def _read_current_canon_hash(plugin_repo: Path) -> str:
    """Return the current canon-policy hash_full prefix.

    Reads `.claude-plugin/canon_policy.json::hash_full` and strips to
    the first 8 hex chars (matches the marker-side `canon_policy_version_hash`
    convention — see governance/schemas/marker.schema.json).

    Raises RuntimeError on missing/unreadable file or missing field.
    """
    canon_path = plugin_repo / ".claude-plugin" / "canon_policy.json"
    if not canon_path.is_file():
        raise RuntimeError(
            f"canon_policy.json not found at {canon_path} — cannot determine "
            f"current canon hash. Pass --canon-hash explicitly to bypass."
        )
    try:
        doc = json.loads(canon_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read {canon_path}: {exc}") from exc
    full = doc.get("hash_full")
    if not isinstance(full, str) or not full:
        raise RuntimeError(
            f"{canon_path} missing 'hash_full' field — cannot determine "
            f"current canon hash."
        )
    return full[:8]  # 8-char prefix matches marker convention


def _load_marker_files(workspace: Path) -> list[tuple[Path, dict, bool]]:
    """Walk both runtime/ready directories and load every marker JSON.

    Returns a list of (path, payload, is_discovery) tuples. Skips
    non-JSON files silently; raises ValueError on a malformed JSON file
    so the validator can report it as an invocation error rather than
    silently mis-classifying.
    """
    out: list[tuple[Path, dict, bool]] = []
    for rel, is_disc in (
        ("analysis/runtime/ready", False),
        ("analysis/discovery/runtime/ready", True),
    ):
        d = workspace / rel
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"malformed marker {path}: {exc}") from exc
            if not isinstance(doc, dict):
                # Not a marker shape (could be a manifest). Skip.
                continue
            out.append((path, doc, is_disc))
    return out


def _chain_index(marker_id: str, sequence: tuple[str, ...]) -> int | None:
    """Return the sequence index of `marker_id` in the given audit-pass
    sequence, or None when the marker is not part of the gating chain
    (ready markers, end-state markers, bridge markers — these don't
    participate in the cascade because they don't have downstream
    dependents in the same way)."""
    try:
        return sequence.index(marker_id)
    except ValueError:
        return None


def validate_marker_freshness(
    workspace: Path, current_hash: str
) -> Report:
    """Top-level entry. Caller picks `current_hash` (typically from
    `_read_current_canon_hash`)."""
    report = Report()
    try:
        markers = _load_marker_files(workspace)
    except ValueError as exc:
        report.add("invocation", None, None, str(exc))
        return report

    # Pass 1 — per-marker freshness check. Build per-chain (path, mid,
    # idx, hash, is_stale) records in chain order for the cascade pass.
    main_chain: list[tuple[Path, str, int, str, bool]] = []
    disc_chain: list[tuple[Path, str, int, str, bool]] = []

    for path, doc, is_disc in markers:
        mid = doc.get("marker_id")
        if not isinstance(mid, str):
            # Schema-required field missing. Defer to the chain
            # validator for the structured error; freshness can't speak
            # to a marker without an ID.
            continue

        # v1.3.8 R1 fix (Codex MAJOR): distinguish "field truly absent"
        # from "field present but invalid". Pre-fix any falsy value
        # (empty string, None, 0, [], etc.) was treated as PRE_HASH_-
        # TOLERATED — meaning a corrupted modern marker (`"canon_policy_-
        # version_hash": ""`) silently bypassed BOTH the blocking check
        # AND the cascade seed. Now only the truly-absent case is
        # tolerated; present-but-invalid is treated as STALE_MARKER
        # (and seeds the cascade like any other stale marker).
        if "canon_policy_version_hash" not in doc:
            report.add(
                "PRE_HASH_TOLERATED",
                path,
                mid,
                "marker has no canon_policy_version_hash field "
                "(pre-Sprint-3 workspace shape; not blocking)",
            )
            continue
        marker_hash = doc.get("canon_policy_version_hash")
        if not isinstance(marker_hash, str) or not marker_hash:
            # Field present but invalid type / empty — corrupted
            # modern marker. Treat as STALE so it both blocks promote
            # AND seeds the cascade (operator must repair or re-emit).
            report.add(
                "STALE_MARKER",
                path,
                mid,
                f"canon_policy_version_hash is present but invalid "
                f"(type={type(marker_hash).__name__}, value={marker_hash!r}); "
                f"corrupted marker — cannot verify against current "
                f"canon hash {current_hash!r}. Re-emit the marker or "
                f"restore the file from a known-good backup.",
            )
            # Build chain record with is_stale=True so the cascade pass
            # sees this marker. We don't have a real hash to compare,
            # but conceptually this IS a stale marker — its absence
            # from canon-hash verification is the failure.
            sequence = DISCOVERY_SEQUENCE if is_disc else MAIN_CYCLE_SEQUENCE
            idx = _chain_index(mid, sequence)
            if idx is not None:
                target = disc_chain if is_disc else main_chain
                target.append((path, mid, idx, "<invalid>", True))
            continue

        # Compare 8-char prefixes (marker schema pattern is 6-64; we
        # normalize to 8 to match the canon_policy.json convention).
        marker_hash_8 = marker_hash[:8]
        is_stale = marker_hash_8 != current_hash
        if is_stale:
            report.add(
                "STALE_MARKER",
                path,
                mid,
                f"marker canon_policy_version_hash={marker_hash_8!r} != "
                f"current canon hash {current_hash!r}. The canon policy "
                f"was edited after this marker was emitted; re-run the "
                f"stage to refresh the marker (or revert the canon edit "
                f"if it was unintended).",
            )

        # Build chain record for cascade. Only audit-pass sequence
        # markers participate; ready / end-state / bridge markers don't
        # have downstream gates in the same chain sense.
        sequence = DISCOVERY_SEQUENCE if is_disc else MAIN_CYCLE_SEQUENCE
        idx = _chain_index(mid, sequence)
        if idx is None:
            continue
        target = disc_chain if is_disc else main_chain
        target.append((path, mid, idx, marker_hash_8, is_stale))

    # Pass 2 — cascade. For each chain, find the earliest STALE marker
    # by chain index; flag every later-index marker as DOWNSTREAM_OF_STALE
    # unless it's already STALE itself (avoid double-reporting).
    for chain_label, chain in (("main", main_chain), ("discovery", disc_chain)):
        stale_indices = [r[2] for r in chain if r[4]]
        if not stale_indices:
            continue
        earliest_stale = min(stale_indices)
        # Find the marker_id at that earliest stale index for the message.
        earliest_stale_mid = next(
            r[1] for r in chain if r[2] == earliest_stale and r[4]
        )
        for path, mid, idx, marker_hash, is_stale in chain:
            if is_stale:
                continue  # Already reported as STALE_MARKER.
            if idx <= earliest_stale:
                continue  # Earlier or same as the stale point — not downstream.
            report.add(
                "DOWNSTREAM_OF_STALE",
                path,
                mid,
                f"{chain_label} chain has a stale marker upstream "
                f"({earliest_stale_mid}, chain idx {earliest_stale}); "
                f"this marker (chain idx {idx}) was emitted under "
                f"preconditions that are no longer guaranteed. Even "
                f"though its own hash matches current canon, the chain "
                f"must be re-promoted from {earliest_stale_mid} forward.",
            )

    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate runtime marker freshness against the current "
            "canon-policy hash + cascade-flag downstream-of-stale "
            "markers (v1.3.8 — closes output review #3.1)."
        )
    )
    parser.add_argument(
        "workspace",
        type=Path,
        help=(
            "Workspace root (typically a directory containing analysis/)."
        ),
    )
    parser.add_argument(
        "--canon-hash",
        default=None,
        help=(
            "Override the on-disk canon-policy hash (default: read from "
            "<plugin_repo>/.claude-plugin/canon_policy.json::hash_full). "
            "Pass an 8-char prefix; longer values are truncated."
        ),
    )
    parser.add_argument(
        "--plugin-repo",
        type=Path,
        default=_REPO_ROOT,
        help=(
            "Plugin repo root (used to locate canon_policy.json when "
            "--canon-hash is not supplied). Default: the repo this "
            "script lives in."
        ),
    )
    args = parser.parse_args(argv)

    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        print(
            f"validate_marker_freshness: workspace {workspace} is not "
            f"a directory.",
            file=sys.stderr,
        )
        return 2

    if args.canon_hash:
        current_hash = args.canon_hash[:8]
    else:
        try:
            current_hash = _read_current_canon_hash(args.plugin_repo)
        except RuntimeError as exc:
            print(f"validate_marker_freshness: {exc}", file=sys.stderr)
            return 2

    report = validate_marker_freshness(workspace, current_hash)

    for f in report.findings:
        print(f.format(), file=sys.stderr)

    # Invocation errors get exit 2; blocking findings exit 1; PRE_HASH-
    # only is exit 0 (informational).
    if any(f.code == "invocation" for f in report.findings):
        return 2
    if report.has_blocking:
        return 1
    print(
        f"OK: marker freshness clean for {workspace} "
        f"(current canon hash: {current_hash})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
