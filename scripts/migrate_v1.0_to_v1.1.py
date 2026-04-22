#!/usr/bin/env python3
"""Workspace migration v1.0 → v1.1 for BSA plugin family (Sysco pilot drift).

Closes the Sysco-pilot drift bundle catalogued in
`migrations/v1.0_to_v1.1/README.md`. Splits into two surface kinds:

  * MECHANICAL — drift the script can fix automatically (applied with
    ``--apply``; dry-run otherwise).

  * REPORT-ONLY — drift that needs operator judgment (printed via
    ``--report <kind>``; never auto-modified).

Mechanical fixes (each opt-in via its own flag, or all via
``--all-mechanical``):

  --markers-only             Marker payload field-name renames.
                               legacy ``marker`` → canonical ``marker_id``
                               legacy ``emittedAt`` → canonical ``timestamp``
                               legacy ``canonPolicyVersion`` → canonical
                                  ``canon_policy_version``
                             Operator MUST inspect each marker's filename
                             to assign ``verdict`` (script suggests a
                             default based on filename pattern but does
                             NOT auto-assign — the field is added with
                             value ``"<MIGRATION_TODO_VERDICT>"`` so the
                             operator sees it on next ``bsa doctor``).
  --a50-priority             Strip ``P\\d_`` prefix from
                               A50_source_register.csv ``Priority`` column.
  --a50-reliability-tier     Strip ``_<descriptor>`` suffix from
                               A50_source_register.csv ``ReliabilityTier``;
                               append descriptor to ``Notes`` (semicolon-
                               separated).
  --a50-source-id-prefix     Prepend ``S-`` to A50 ``SourceID`` values
                               matching ``^[A-Z]{2,5}-\\d{3,4}$`` (i.e.,
                               missing the canonical ``S-`` prefix). Also
                               rewrites every cross-reference in
                               A58/A59/A60 to keep foreign keys consistent.

Report-only (each opt-in via ``--report <kind>``; ``all-reports`` aliases
all four):

  --report verdict-caveats         Lists every marker with verdict
                                     ``PASS (with caveats)`` (or any
                                     suffix-bearing verdict). Operator
                                     decides per row.
  --report a50-access-status-partial
                                   Lists every A50 row with
                                     ``AccessStatus=readable_partial``.
  --report a60-header-mismatch     Prints A60 header alongside the
                                     canonical header.
  --report a51-reconciliation      Delegates to the upstream auditor at
                                     ``scripts/validate_a51_reconciliation.
                                     audit_workspace`` so the report stays
                                     in lockstep with ``bsa doctor`` (full
                                     resolution-intent vocabulary, H1-H4
                                     handoff packet scanning, shorthand
                                     ``A51-MISS-010/011/012`` ref expansion,
                                     200-char proximity window).

Properties:

  - **Idempotent**: re-running after a clean migration is a no-op.
  - **Non-destructive**: every fix preserves a backup at
    ``<file>.pre-v1.1.bak`` before writing the migrated content.
  - **Scoped**: only touches files under ``analysis/`` (and the optional
    ``analysis/discovery/``); never edits files outside the workspace.
  - **Logged**: emits JSONL records to
    ``<workspace>/runtime/migration_log_v1.0_to_v1.1.jsonl`` with one
    record per fix attempt or report finding.
  - **Dry-run by default**: must pass ``--apply`` to actually write
    changes (mechanical fixes only — reports never modify anything).

Exit codes:
  0 — migration succeeded (or dry-run clean / report only)
  1 — at least one fix-error (mechanical) or unresolved finding
        (report mode emits the finding catalogue but always returns 0
        unless invocation error; exit 1 means the mechanical apply
        partially failed)
  2 — invocation error (missing/unreadable workspace, bad CLI)

Stdlib-only. Python 3.9+.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

# Reuse upstream validators / schemas so this script's reports stay in
# lockstep with `bsa doctor`. Path arithmetic mirrors the existing pattern.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Soft imports — the script must still run even when invoked from a
# packaging mode where governance/ isn't on the path. Reports degrade
# gracefully (the kind is skipped with a clear log message) rather than
# crashing.
try:  # pragma: no cover - import-time fallback
    from scripts import validate_a51_reconciliation as _a51_auditor  # type: ignore
except ImportError:  # pragma: no cover
    _a51_auditor = None  # type: ignore

try:  # pragma: no cover - import-time fallback
    from governance.schemas import loader as _schema_loader  # type: ignore
except ImportError:  # pragma: no cover
    _schema_loader = None  # type: ignore


MIGRATION_NAME = "v1.0_to_v1.1"
LOG_FILENAME = f"migration_log_{MIGRATION_NAME}.jsonl"
BACKUP_SUFFIX = ".pre-v1.1.bak"

# Canonical A60 column set. Single source of truth: load from the live
# schema at module import time so this script can never publish a stale
# header set vs `governance/schemas/a60.schema.json`. Falls back to the
# v1.1.x literal when the schema isn't importable (packaging-mode runs).
_A60_CANONICAL_FALLBACK: tuple[str, ...] = (
    "NegEvID", "SourceID", "ExcerptRef", "RelatedClaimID",
    "NegativeFinding", "A51Ref", "Notes",
)


def _load_a60_canonical_columns() -> tuple[str, ...]:
    if _schema_loader is None:
        return _A60_CANONICAL_FALLBACK
    try:
        a60_schema_path = _REPO_ROOT / "governance" / "schemas" / "a60.schema.json"
        schema = json.loads(a60_schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _A60_CANONICAL_FALLBACK
    order_block = schema.get("x-bsa-csv-columns-order", {})
    cols = order_block.get("order") or schema.get("required") or []
    return tuple(cols) if cols else _A60_CANONICAL_FALLBACK


A60_CANONICAL_COLUMNS: tuple[str, ...] = _load_a60_canonical_columns()

# Marker payload field renames (camelCase legacy → snake_case canonical).
MARKER_FIELD_RENAMES: tuple[tuple[str, str], ...] = (
    ("marker", "marker_id"),
    ("emittedAt", "timestamp"),
    ("canonPolicyVersion", "canon_policy_version"),
)

# Marker filename pattern → suggested verdict default. The migration
# inserts ``"<MIGRATION_TODO_VERDICT>"`` when verdict is genuinely missing
# so the operator sees it on next ``bsa doctor``; this table is for the
# console hint only (not auto-applied).
VERDICT_DEFAULT_HINTS: tuple[tuple[str, str], ...] = (
    (".ready.json", "READY"),
    (".pass.json", "PASS"),
    (".merged.json", "MERGED"),
    ("discovery.go.json", "GO"),
    ("discovery.exit.pass.json", "PASS"),
)

# A50 Priority Jira-style → canonical mapping.
A50_PRIORITY_MAP: dict[str, str] = {
    "P0_critical": "<MIGRATION_TODO_PRIORITY_CRITICAL>",  # see README.md §C
    "P1_high": "high",
    "P2_medium": "medium",
    "P3_low": "low",
}

# A50 ReliabilityTier prefix-only canonical regex (capture the Tn prefix).
A50_RELIABILITY_TIER_RE = re.compile(r"^(T[1-5])_(.+)$")

# A50 SourceID Sysco-style (missing S- prefix) regex.
A50_SOURCE_ID_LEGACY_RE = re.compile(r"^([A-Z]{2,5})-(\d{3,4})$")
A50_SOURCE_ID_CANONICAL_RE = re.compile(r"^S-(?:[A-Z]{2,5}-)?\d{3,4}$")


@dataclass
class FixRecord:
    """One mechanical fix attempt or report finding."""
    fix_kind: str  # markers | a50-priority | a50-reliability-tier | a50-source-id-prefix | report-*
    target_path: str
    detail: str  # short human-readable description of the change/finding
    mode: str  # planned | applied | error | finding | skipped
    reason: str = ""  # for skipped/error
    dry_run: bool = True
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def to_json_line(self) -> str:
        payload = {
            "timestamp": self.timestamp,
            "migration": MIGRATION_NAME,
            "fix_kind": self.fix_kind,
            "target_path": self.target_path,
            "detail": self.detail,
            "mode": self.mode,
            "dry_run": self.dry_run,
        }
        if self.reason:
            payload["reason"] = self.reason
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# ---- File discovery helpers ------------------------------------------


def _iter_marker_files(workspace: Path) -> list[Path]:
    """Every JSON file under ``analysis/runtime/ready/`` and
    ``analysis/discovery/runtime/ready/``. Sorted for deterministic
    output."""
    patterns = (
        "analysis/runtime/ready/*.json",
        "analysis/discovery/runtime/ready/*.json",
        "runtime/ready/*.json",  # workspace root may already be analysis/
        "discovery/runtime/ready/*.json",
    )
    seen: set[Path] = set()
    out: list[Path] = []
    for pat in patterns:
        for p in workspace.glob(pat):
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append(p)
    return sorted(out)


def _iter_a50_files(workspace: Path) -> list[Path]:
    """Every A50_source_register.csv under canonical/discovery."""
    patterns = (
        "analysis/canonical/core_controls/A50_source_register.csv",
        "analysis/discovery/canonical/core_controls/A50_source_register.csv",
        "canonical/core_controls/A50_source_register.csv",
        "discovery/canonical/core_controls/A50_source_register.csv",
    )
    seen: set[Path] = set()
    out: list[Path] = []
    for pat in patterns:
        for p in workspace.glob(pat):
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append(p)
    return sorted(out)


def _iter_a51_files(workspace: Path) -> list[Path]:
    patterns = (
        "analysis/canonical/core_controls/A51_issue_route_register.csv",
        "analysis/discovery/canonical/core_controls/A51_issue_route_register.csv",
        "canonical/core_controls/A51_issue_route_register.csv",
        "discovery/canonical/core_controls/A51_issue_route_register.csv",
    )
    seen: set[Path] = set()
    out: list[Path] = []
    for pat in patterns:
        for p in workspace.glob(pat):
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append(p)
    return sorted(out)


def _iter_a58_a59_a60_files(workspace: Path) -> list[Path]:
    """Every A58/A59/A60 CSV — needed when rewriting SourceID cross-refs."""
    patterns = (
        "analysis/canonical/core_controls/A58_evidence_excerpts.csv",
        "analysis/canonical/core_controls/A59_claim_register.csv",
        "analysis/canonical/core_controls/A60_negative_evidence_register.csv",
        "analysis/discovery/canonical/core_controls/A58_evidence_excerpts.csv",
        "analysis/discovery/canonical/core_controls/A59_claim_register.csv",
        "analysis/discovery/canonical/core_controls/A60_negative_evidence_register.csv",
        "canonical/core_controls/A58_evidence_excerpts.csv",
        "canonical/core_controls/A59_claim_register.csv",
        "canonical/core_controls/A60_negative_evidence_register.csv",
        "discovery/canonical/core_controls/A58_evidence_excerpts.csv",
        "discovery/canonical/core_controls/A59_claim_register.csv",
        "discovery/canonical/core_controls/A60_negative_evidence_register.csv",
    )
    seen: set[Path] = set()
    out: list[Path] = []
    for pat in patterns:
        for p in workspace.glob(pat):
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append(p)
    return sorted(out)


def _backup(path: Path) -> None:
    bak = path.with_suffix(path.suffix + BACKUP_SUFFIX)
    if bak.exists():
        return  # already backed up — preserves first-run state
    shutil.copy2(path, bak)


# ---- Mechanical fix: marker camelCase ---------------------------------


def _suggest_verdict_for_marker(filename: str) -> Optional[str]:
    for suffix, verdict in VERDICT_DEFAULT_HINTS:
        if filename.endswith(suffix) or filename == suffix.lstrip("."):
            return verdict
    return None


def fix_markers(workspace: Path, dry_run: bool) -> list[FixRecord]:
    records: list[FixRecord] = []
    for path in _iter_marker_files(workspace):
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            records.append(FixRecord(
                fix_kind="markers", target_path=str(path),
                detail="read-error", mode="error",
                reason=str(exc), dry_run=dry_run,
            ))
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            records.append(FixRecord(
                fix_kind="markers", target_path=str(path),
                detail="json-decode-error", mode="error",
                reason=str(exc), dry_run=dry_run,
            ))
            continue
        if not isinstance(payload, dict):
            records.append(FixRecord(
                fix_kind="markers", target_path=str(path),
                detail="payload-not-object", mode="skipped",
                reason="marker JSON is not a top-level object", dry_run=dry_run,
            ))
            continue

        changes: list[str] = []
        new_payload = dict(payload)
        for legacy, canonical in MARKER_FIELD_RENAMES:
            if legacy in new_payload and canonical not in new_payload:
                new_payload[canonical] = new_payload.pop(legacy)
                changes.append(f"{legacy}→{canonical}")
            elif legacy in new_payload and canonical in new_payload:
                # Both present — non-destructively keep the canonical, drop legacy
                if new_payload[legacy] == new_payload[canonical]:
                    new_payload.pop(legacy)
                    changes.append(f"drop-duplicate-{legacy}")
                # else: values differ — operator must reconcile; skip this field
        # If verdict is still missing, insert a TODO marker so the operator sees it.
        if "verdict" not in new_payload:
            hint = _suggest_verdict_for_marker(path.name)
            todo_value = (
                f"<MIGRATION_TODO_VERDICT verdict_hint={hint}>"
                if hint else "<MIGRATION_TODO_VERDICT verdict_hint=UNKNOWN>"
            )
            new_payload["verdict"] = todo_value
            changes.append("inject-verdict-todo")

        if not changes:
            records.append(FixRecord(
                fix_kind="markers", target_path=str(path),
                detail="already-canonical", mode="skipped",
                reason="no marker field renames needed", dry_run=dry_run,
            ))
            continue

        if dry_run:
            records.append(FixRecord(
                fix_kind="markers", target_path=str(path),
                detail=", ".join(changes), mode="planned", dry_run=True,
            ))
            continue
        try:
            _backup(path)
            path.write_text(
                json.dumps(new_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            records.append(FixRecord(
                fix_kind="markers", target_path=str(path),
                detail=", ".join(changes), mode="applied", dry_run=False,
            ))
        except OSError as exc:
            records.append(FixRecord(
                fix_kind="markers", target_path=str(path),
                detail="write-error", mode="error",
                reason=str(exc), dry_run=False,
            ))
    return records


# ---- Mechanical fix: A50 Priority ------------------------------------


def _csv_read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


class HeaderValidationError(ValueError):
    """Raised when a CSV's header doesn't contain at least one expected
    column — prevents the headerless-input case from being silently
    downgraded to ``no-column`` skips.

    Carries the actual header (so the operator sees what's wrong) plus
    the set of expected columns the script was looking for.
    """

    def __init__(self, path: Path, actual_header: list[str], expected_any_of: tuple[str, ...]):
        self.path = path
        self.actual_header = actual_header
        self.expected_any_of = expected_any_of
        msg = (
            f"{path.name}: header validation failed — expected at least "
            f"one of {list(expected_any_of)} but got {actual_header}. "
            "(Likely a headerless CSV: csv.DictReader is treating the "
            "first data row as the header. Fix the file or skip this "
            "fix.)"
        )
        super().__init__(msg)


def _csv_read_validated(
    path: Path, expected_any_of: tuple[str, ...],
) -> tuple[list[str], list[dict[str, str]]]:
    """Read a CSV and assert its header contains at least one expected
    column. Raises ``HeaderValidationError`` on failure so callers can
    surface the issue instead of silently skipping.
    """
    fieldnames, rows = _csv_read(path)
    if not any(col in fieldnames for col in expected_any_of):
        raise HeaderValidationError(path, fieldnames, expected_any_of)
    return fieldnames, rows


def _csv_write(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def fix_a50_priority(workspace: Path, dry_run: bool) -> list[FixRecord]:
    records: list[FixRecord] = []
    # An A50 file with NONE of these columns is almost certainly
    # headerless — surface that as an error rather than a benign skip.
    a50_marker_columns = ("SourceID", "Priority", "ReliabilityTier", "Title")
    for path in _iter_a50_files(workspace):
        try:
            fieldnames, rows = _csv_read_validated(path, a50_marker_columns)
        except HeaderValidationError as exc:
            records.append(FixRecord(
                fix_kind="a50-priority", target_path=str(path),
                detail="header-validation-failed",
                mode="error",
                reason=str(exc), dry_run=dry_run,
            ))
            continue
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            records.append(FixRecord(
                fix_kind="a50-priority", target_path=str(path),
                detail="csv-read-error", mode="error",
                reason=str(exc), dry_run=dry_run,
            ))
            continue
        if "Priority" not in fieldnames:
            records.append(FixRecord(
                fix_kind="a50-priority", target_path=str(path),
                detail="no-Priority-column", mode="skipped",
                reason="A50 file has no Priority column", dry_run=dry_run,
            ))
            continue
        changed_rows: list[str] = []
        for idx, row in enumerate(rows, start=2):  # header is line 1
            value = (row.get("Priority") or "").strip()
            if value in A50_PRIORITY_MAP:
                new_value = A50_PRIORITY_MAP[value]
                row["Priority"] = new_value
                changed_rows.append(f"line {idx}: {value}→{new_value}")
        if not changed_rows:
            records.append(FixRecord(
                fix_kind="a50-priority", target_path=str(path),
                detail="already-canonical", mode="skipped",
                reason="no Priority cells need rewriting", dry_run=dry_run,
            ))
            continue
        if dry_run:
            records.append(FixRecord(
                fix_kind="a50-priority", target_path=str(path),
                detail=f"{len(changed_rows)} rewrite(s): {'; '.join(changed_rows[:5])}{'...' if len(changed_rows) > 5 else ''}",
                mode="planned", dry_run=True,
            ))
            continue
        try:
            _backup(path)
            _csv_write(path, fieldnames, rows)
            records.append(FixRecord(
                fix_kind="a50-priority", target_path=str(path),
                detail=f"{len(changed_rows)} cell(s) rewritten",
                mode="applied", dry_run=False,
            ))
        except (OSError, csv.Error) as exc:
            records.append(FixRecord(
                fix_kind="a50-priority", target_path=str(path),
                detail="csv-write-error", mode="error",
                reason=str(exc), dry_run=False,
            ))
    return records


# ---- Mechanical fix: A50 ReliabilityTier ------------------------------


def fix_a50_reliability_tier(workspace: Path, dry_run: bool) -> list[FixRecord]:
    records: list[FixRecord] = []
    a50_marker_columns = ("SourceID", "Priority", "ReliabilityTier", "Title")
    for path in _iter_a50_files(workspace):
        try:
            fieldnames, rows = _csv_read_validated(path, a50_marker_columns)
        except HeaderValidationError as exc:
            records.append(FixRecord(
                fix_kind="a50-reliability-tier", target_path=str(path),
                detail="header-validation-failed",
                mode="error",
                reason=str(exc), dry_run=dry_run,
            ))
            continue
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            records.append(FixRecord(
                fix_kind="a50-reliability-tier", target_path=str(path),
                detail="csv-read-error", mode="error",
                reason=str(exc), dry_run=dry_run,
            ))
            continue
        if "ReliabilityTier" not in fieldnames:
            records.append(FixRecord(
                fix_kind="a50-reliability-tier", target_path=str(path),
                detail="no-ReliabilityTier-column", mode="skipped",
                reason="A50 file has no ReliabilityTier column", dry_run=dry_run,
            ))
            continue
        # Ensure Notes column exists (we may need to append).
        if "Notes" not in fieldnames:
            fieldnames = list(fieldnames) + ["Notes"]
            for row in rows:
                row.setdefault("Notes", "")
        changed_rows: list[str] = []
        for idx, row in enumerate(rows, start=2):
            value = (row.get("ReliabilityTier") or "").strip()
            m = A50_RELIABILITY_TIER_RE.match(value)
            if not m:
                continue
            tier_only, descriptor = m.group(1), m.group(2)
            row["ReliabilityTier"] = tier_only
            existing_notes = (row.get("Notes") or "").strip()
            human_descriptor = descriptor.replace("_", " ")
            if existing_notes:
                row["Notes"] = f"{existing_notes}; reliability-tier descriptor: {human_descriptor}"
            else:
                row["Notes"] = f"reliability-tier descriptor: {human_descriptor}"
            changed_rows.append(f"line {idx}: {value}→{tier_only} (Notes appended)")
        if not changed_rows:
            records.append(FixRecord(
                fix_kind="a50-reliability-tier", target_path=str(path),
                detail="already-canonical", mode="skipped",
                reason="no ReliabilityTier cells need rewriting", dry_run=dry_run,
            ))
            continue
        if dry_run:
            records.append(FixRecord(
                fix_kind="a50-reliability-tier", target_path=str(path),
                detail=f"{len(changed_rows)} rewrite(s): {'; '.join(changed_rows[:3])}{'...' if len(changed_rows) > 3 else ''}",
                mode="planned", dry_run=True,
            ))
            continue
        try:
            _backup(path)
            _csv_write(path, fieldnames, rows)
            records.append(FixRecord(
                fix_kind="a50-reliability-tier", target_path=str(path),
                detail=f"{len(changed_rows)} cell(s) rewritten",
                mode="applied", dry_run=False,
            ))
        except (OSError, csv.Error) as exc:
            records.append(FixRecord(
                fix_kind="a50-reliability-tier", target_path=str(path),
                detail="csv-write-error", mode="error",
                reason=str(exc), dry_run=False,
            ))
    return records


# ---- Mechanical fix: A50 SourceID prefix + cross-ref rewrite ----------


def fix_a50_source_id_prefix(workspace: Path, dry_run: bool) -> list[FixRecord]:
    """Prepend ``S-`` to A50 SourceIDs missing the prefix; rewrite every
    A58/A59/A60 cross-reference."""
    records: list[FixRecord] = []

    # Phase 1 — collect SourceID rewrites from every A50 file.
    rewrite_map: dict[str, str] = {}  # legacy → canonical
    a50_paths_to_write: list[tuple[Path, list[str], list[dict[str, str]]]] = []
    a50_marker_columns = ("SourceID", "Priority", "ReliabilityTier", "Title")
    for path in _iter_a50_files(workspace):
        try:
            fieldnames, rows = _csv_read_validated(path, a50_marker_columns)
        except HeaderValidationError as exc:
            records.append(FixRecord(
                fix_kind="a50-source-id-prefix", target_path=str(path),
                detail="header-validation-failed",
                mode="error",
                reason=str(exc), dry_run=dry_run,
            ))
            continue
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            records.append(FixRecord(
                fix_kind="a50-source-id-prefix", target_path=str(path),
                detail="csv-read-error", mode="error",
                reason=str(exc), dry_run=dry_run,
            ))
            continue
        if "SourceID" not in fieldnames:
            records.append(FixRecord(
                fix_kind="a50-source-id-prefix", target_path=str(path),
                detail="no-SourceID-column", mode="skipped",
                reason="A50 file has no SourceID column", dry_run=dry_run,
            ))
            continue
        per_file_rewrites: list[str] = []
        for idx, row in enumerate(rows, start=2):
            sid = (row.get("SourceID") or "").strip()
            if A50_SOURCE_ID_CANONICAL_RE.match(sid):
                continue  # already canonical
            m = A50_SOURCE_ID_LEGACY_RE.match(sid)
            if not m:
                continue  # neither legacy nor canonical — operator-only fix
            new_sid = f"S-{sid}"
            if sid in rewrite_map and rewrite_map[sid] != new_sid:
                # Conflict — same legacy mapped to two canonicals (shouldn't happen)
                records.append(FixRecord(
                    fix_kind="a50-source-id-prefix", target_path=str(path),
                    detail=f"line {idx}: rewrite-conflict {sid} would map to two canonicals",
                    mode="error",
                    reason="conflicting-rewrite", dry_run=dry_run,
                ))
                continue
            rewrite_map[sid] = new_sid
            row["SourceID"] = new_sid
            per_file_rewrites.append(f"line {idx}: {sid}→{new_sid}")
        if per_file_rewrites:
            a50_paths_to_write.append((path, fieldnames, rows))
            # Always log "planned" here — the actual write happens in
            # Phase 3 below; logging "applied" before the write would
            # produce a misleading trail if the write later fails.
            records.append(FixRecord(
                fix_kind="a50-source-id-prefix", target_path=str(path),
                detail=f"{len(per_file_rewrites)} A50 SourceID rewrite(s): {'; '.join(per_file_rewrites[:3])}{'...' if len(per_file_rewrites) > 3 else ''}",
                mode="planned",
                dry_run=dry_run,
            ))

    if not rewrite_map:
        # Nothing to rewrite anywhere.
        if not records:
            records.append(FixRecord(
                fix_kind="a50-source-id-prefix", target_path=str(workspace),
                detail="no A50 files needed SourceID prefix rewriting",
                mode="skipped", dry_run=dry_run,
            ))
        return records

    # Phase 2 — apply cross-reference rewrites in A58/A59/A60.
    crossref_columns: dict[str, tuple[str, ...]] = {
        # filename pattern → columns to rewrite
        "A58_evidence_excerpts.csv": ("SourceID",),
        "A59_claim_register.csv": ("SourceID",),
        "A60_negative_evidence_register.csv": ("SourceID",),
    }
    crossref_paths_to_write: list[tuple[Path, list[str], list[dict[str, str]]]] = []
    for path in _iter_a58_a59_a60_files(workspace):
        try:
            fieldnames, rows = _csv_read(path)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            records.append(FixRecord(
                fix_kind="a50-source-id-prefix-crossref", target_path=str(path),
                detail="csv-read-error", mode="error",
                reason=str(exc), dry_run=dry_run,
            ))
            continue
        # Look up which columns to rewrite for this filename.
        cols_to_rewrite = ()
        for suffix, cols in crossref_columns.items():
            if path.name == suffix:
                cols_to_rewrite = cols
                break
        if not cols_to_rewrite:
            continue
        present_cols = tuple(c for c in cols_to_rewrite if c in fieldnames)
        if not present_cols:
            continue
        per_file_rewrites: list[str] = []
        for idx, row in enumerate(rows, start=2):
            for col in present_cols:
                value = (row.get(col) or "").strip()
                # Cell may contain multiple SIDs joined by ; / , or space.
                # Split on common delimiters, rewrite each, rejoin with original delimiter
                # if recognizable, else just join with ;.
                tokens = re.split(r"[;,/\s]+", value) if value else []
                changed_in_cell = False
                new_tokens = []
                for tok in tokens:
                    if tok in rewrite_map:
                        new_tokens.append(rewrite_map[tok])
                        changed_in_cell = True
                    else:
                        new_tokens.append(tok)
                if changed_in_cell:
                    # Preserve original delimiter if it's a single one; else use ;
                    delim_match = re.search(r"[;,/\s]+", value)
                    delim = delim_match.group(0) if delim_match and len([t for t in tokens if t]) > 1 else ";"
                    row[col] = delim.join(t for t in new_tokens if t)
                    per_file_rewrites.append(f"line {idx} [{col}]: {value} → {row[col]}")
        if per_file_rewrites:
            crossref_paths_to_write.append((path, fieldnames, rows))
            records.append(FixRecord(
                fix_kind="a50-source-id-prefix-crossref", target_path=str(path),
                detail=f"{len(per_file_rewrites)} crossref rewrite(s): {'; '.join(per_file_rewrites[:3])}{'...' if len(per_file_rewrites) > 3 else ''}",
                mode="planned",
                dry_run=dry_run,
            ))

    # Phase 3 — actually write everything (apply mode only). Append a
    # per-file `applied` record on success and `error` on failure so the
    # JSONL log faithfully reflects what hit disk.
    if not dry_run:
        write_targets: list[tuple[str, Path, list[str], list[dict[str, str]]]] = []
        for path, fieldnames, rows in a50_paths_to_write:
            write_targets.append(("a50-source-id-prefix-write", path, fieldnames, rows))
        for path, fieldnames, rows in crossref_paths_to_write:
            write_targets.append(("a50-source-id-prefix-crossref-write", path, fieldnames, rows))
        for fix_kind, path, fieldnames, rows in write_targets:
            try:
                _backup(path)
                _csv_write(path, fieldnames, rows)
                records.append(FixRecord(
                    fix_kind=fix_kind, target_path=str(path),
                    detail="phase-3 write succeeded",
                    mode="applied", dry_run=False,
                ))
            except (OSError, csv.Error) as exc:
                records.append(FixRecord(
                    fix_kind=fix_kind, target_path=str(path),
                    detail="csv-write-error", mode="error",
                    reason=str(exc), dry_run=False,
                ))
    return records


# ---- Report-only checks -----------------------------------------------


def report_verdict_caveats(workspace: Path) -> list[FixRecord]:
    """Find every marker with a verdict that is NOT in the closed enum
    (e.g., ``PASS (with caveats)``)."""
    canonical_verdicts = {"PASS", "FAIL", "READY", "MERGED", "GO", "PIVOT", "MORE_RESEARCH", "NO_GO"}
    records: list[FixRecord] = []
    for path in _iter_marker_files(workspace):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        verdict = payload.get("verdict")
        if not isinstance(verdict, str):
            continue
        if verdict in canonical_verdicts:
            continue
        if verdict.startswith("<MIGRATION_TODO_VERDICT"):
            continue  # already flagged by --markers-only
        records.append(FixRecord(
            fix_kind="report-verdict-caveats", target_path=str(path),
            detail=f"non-canonical verdict: {verdict!r}",
            mode="finding",
            reason="Operator must split into canonical verdict + A51 informational route",
        ))
    return records


def report_a50_access_status_partial(workspace: Path) -> list[FixRecord]:
    """Find every A50 row with AccessStatus=readable_partial (or any value
    not in the canonical enum)."""
    canonical_access = {"readable", "unreadable", "denied", "expired", "missing"}
    records: list[FixRecord] = []
    for path in _iter_a50_files(workspace):
        try:
            fieldnames, rows = _csv_read(path)
        except (OSError, csv.Error):
            continue
        if "AccessStatus" not in fieldnames:
            continue
        for idx, row in enumerate(rows, start=2):
            access = (row.get("AccessStatus") or "").strip()
            if not access or access in canonical_access:
                continue
            records.append(FixRecord(
                fix_kind="report-a50-access-status-partial", target_path=str(path),
                detail=f"line {idx}: SourceID={row.get('SourceID', '?')!r} AccessStatus={access!r}",
                mode="finding",
                reason="Operator must classify as readable/unreadable + raise A51 for the missing portion",
            ))
    return records


def report_a60_header_mismatch(workspace: Path) -> list[FixRecord]:
    """Compare each A60 file's header against the canonical column set
    (loaded from the live ``governance/schemas/a60.schema.json``).

    The check is **exact-set** (every required column must be present
    AND no extra columns), matching the schema validator's semantics —
    the loader rejects A60 rows on either kind of drift. Stale 5-column
    pilot headers OR canonical-with-extras pilot headers both produce
    a finding.
    """
    canonical = list(A60_CANONICAL_COLUMNS)
    canonical_set = set(canonical)
    records: list[FixRecord] = []
    for path in _iter_a58_a59_a60_files(workspace):
        if path.name != "A60_negative_evidence_register.csv":
            continue
        try:
            fieldnames, _ = _csv_read(path)
        except (OSError, csv.Error):
            continue
        pilot_set = set(fieldnames)
        missing = [c for c in canonical if c not in pilot_set]
        extra = [c for c in fieldnames if c not in canonical_set]
        if not missing and not extra:
            continue  # exact match — no finding
        details = [f"pilot header: {fieldnames}", f"canonical: {canonical}"]
        if missing:
            details.append(f"missing: {missing}")
        if extra:
            details.append(f"extra: {extra}")
        records.append(FixRecord(
            fix_kind="report-a60-header-mismatch", target_path=str(path),
            detail="; ".join(details),
            mode="finding",
            reason="Operator must rewrite A60 with the canonical column set; no mechanical mapping possible",
        ))
    return records


def report_a51_reconciliation(workspace: Path) -> list[FixRecord]:
    """Delegate to ``scripts/validate_a51_reconciliation.audit_workspace``
    so this report stays in lockstep with ``bsa doctor``'s reconciliation
    check.

    The upstream auditor handles: H1-H4 handoff packet scanning (not just
    markers), shorthand ``A51-MISS-010/011/012`` ref expansion, the
    full 9-word resolution-intent vocabulary (``resolved | remediated |
    closed | fixed | completed | done | obsolete | superseded |
    resolved_by_remediation``), and the 200-char proximity window. Also
    produces the ``A51_RECONCILE_GHOST`` finding when an A51Ref appears
    declared-resolved upstream but isn't in the canonical register at
    all.

    Falls back to a clear "skipped" record if the auditor module is
    unavailable (packaging-mode runs).
    """
    if _a51_auditor is None:
        return [FixRecord(
            fix_kind="report-a51-reconciliation", target_path=str(workspace),
            detail="upstream auditor not importable",
            mode="skipped",
            reason="scripts/validate_a51_reconciliation.py not on sys.path",
        )]
    # The auditor expects the workspace root (parent of analysis/).
    audit_root = workspace if (workspace / "analysis").is_dir() else workspace.parent
    try:
        report = _a51_auditor.audit_workspace(audit_root)
    except (OSError, ValueError, KeyError) as exc:
        return [FixRecord(
            fix_kind="report-a51-reconciliation", target_path=str(workspace),
            detail=f"auditor invocation failed: {exc}",
            mode="error",
            reason="upstream auditor raised an exception; investigate workspace state",
        )]
    a51_paths = _iter_a51_files(workspace)
    a51_path_for_finding = a51_paths[0] if a51_paths else workspace
    records: list[FixRecord] = []
    for finding in report.findings:
        records.append(FixRecord(
            fix_kind="report-a51-reconciliation", target_path=str(a51_path_for_finding),
            detail=finding.format(),
            mode="finding",
            reason=(
                "Either set canonical A51 ResolutionStatus to "
                "resolved/resolved_by_remediation/superseded/wontfix, "
                "or strip the resolved language from the marker / handoff payload"
            ),
        ))
    return records


# ---- Driver -----------------------------------------------------------


@dataclass
class RunPlan:
    apply_markers: bool = False
    apply_a50_priority: bool = False
    apply_a50_reliability_tier: bool = False
    apply_a50_source_id_prefix: bool = False
    report_kinds: tuple[str, ...] = ()
    apply_mode: bool = False  # --apply (mechanical fixes write)


REPORT_KINDS = (
    "verdict-caveats",
    "a50-access-status-partial",
    "a60-header-mismatch",
    "a51-reconciliation",
)


def run(workspace: Path, plan: RunPlan) -> tuple[list[FixRecord], int]:
    records: list[FixRecord] = []
    dry_run = not plan.apply_mode

    # Mechanical fixes
    if plan.apply_markers:
        records.extend(fix_markers(workspace, dry_run=dry_run))
    if plan.apply_a50_priority:
        records.extend(fix_a50_priority(workspace, dry_run=dry_run))
    if plan.apply_a50_reliability_tier:
        records.extend(fix_a50_reliability_tier(workspace, dry_run=dry_run))
    if plan.apply_a50_source_id_prefix:
        records.extend(fix_a50_source_id_prefix(workspace, dry_run=dry_run))

    # Reports
    for kind in plan.report_kinds:
        if kind == "verdict-caveats":
            records.extend(report_verdict_caveats(workspace))
        elif kind == "a50-access-status-partial":
            records.extend(report_a50_access_status_partial(workspace))
        elif kind == "a60-header-mismatch":
            records.extend(report_a60_header_mismatch(workspace))
        elif kind == "a51-reconciliation":
            records.extend(report_a51_reconciliation(workspace))

    has_error = any(r.mode == "error" for r in records)
    return records, (1 if has_error else 0)


def write_log(workspace: Path, records: Iterable[FixRecord]) -> Optional[Path]:
    log_dir = workspace / "runtime"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Try sub-path: workspace may be `analysis/` already
        log_dir = workspace.parent / "analysis" / "runtime"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
    log_path = log_dir / LOG_FILENAME
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            for rec in records:
                fh.write(rec.to_json_line() + "\n")
    except OSError:
        return None
    return log_path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="BSA workspace migration v1.0 → v1.1 (Sysco pilot drift bundle)."
    )
    parser.add_argument("--workspace", type=Path, required=True,
                        help="Path to workspace root (typically a directory containing analysis/).")
    parser.add_argument("--apply", action="store_true",
                        help="Actually apply mechanical fixes. Default: dry-run.")

    parser.add_argument("--markers-only", action="store_true",
                        help="Apply marker payload field renames.")
    parser.add_argument("--a50-priority", action="store_true",
                        help="Apply A50 Priority enum cleanup.")
    parser.add_argument("--a50-reliability-tier", action="store_true",
                        help="Apply A50 ReliabilityTier enum cleanup.")
    parser.add_argument("--a50-source-id-prefix", action="store_true",
                        help="Apply A50 SourceID S- prefix + crossref rewrite.")
    parser.add_argument("--all-mechanical", action="store_true",
                        help="Apply all mechanical fixes (equivalent to --markers-only --a50-priority --a50-reliability-tier --a50-source-id-prefix).")

    parser.add_argument("--report", action="append", default=[],
                        choices=list(REPORT_KINDS) + ["all-reports"],
                        help="Print a manual-review finding catalogue (repeatable).")

    args = parser.parse_args(argv)

    # Preflight workspace
    try:
        exists = args.workspace.exists()
        is_dir = args.workspace.is_dir() if exists else False
    except (OSError, PermissionError) as exc:
        print(f"ERROR: cannot access workspace {args.workspace}: {exc}", file=sys.stderr)
        return 2
    if not exists:
        print(f"ERROR: workspace does not exist: {args.workspace}", file=sys.stderr)
        return 2
    if not is_dir:
        print(f"ERROR: workspace is not a directory: {args.workspace}", file=sys.stderr)
        return 2

    plan = RunPlan(
        apply_markers=args.markers_only or args.all_mechanical,
        apply_a50_priority=args.a50_priority or args.all_mechanical,
        apply_a50_reliability_tier=args.a50_reliability_tier or args.all_mechanical,
        apply_a50_source_id_prefix=args.a50_source_id_prefix or args.all_mechanical,
        report_kinds=tuple(REPORT_KINDS) if "all-reports" in args.report else tuple(args.report),
        apply_mode=args.apply,
    )

    if not (
        plan.apply_markers or plan.apply_a50_priority or plan.apply_a50_reliability_tier
        or plan.apply_a50_source_id_prefix or plan.report_kinds
    ):
        print("ERROR: nothing to do. Pass --markers-only / --a50-* / --all-mechanical and/or --report <kind>.", file=sys.stderr)
        return 2

    records, exit_code = run(args.workspace, plan)
    log_path = write_log(args.workspace, records)

    # Console summary.
    by_kind: dict[str, dict[str, int]] = {}
    for r in records:
        by_kind.setdefault(r.fix_kind, {}).setdefault(r.mode, 0)
        by_kind[r.fix_kind][r.mode] += 1
    mode_label = "applied" if plan.apply_mode else "dry-run"
    summary_lines = [
        f"BSA migration v1.0 → v1.1 ({mode_label}): {len(records)} record(s)",
    ]
    for kind in sorted(by_kind):
        modes_summary = ", ".join(f"{m}={n}" for m, n in sorted(by_kind[kind].items()))
        summary_lines.append(f"  {kind}: {modes_summary}")
    if log_path:
        summary_lines.append(f"Log: {log_path}")
    print("\n".join(summary_lines))

    # Echo findings (report mode) inline so operator doesn't have to open the log.
    findings = [r for r in records if r.mode == "finding"]
    if findings:
        print("\nFindings (operator action required):")
        for r in findings:
            print(f"  [{r.fix_kind}] {r.target_path}")
            print(f"    detail: {r.detail}")
            if r.reason:
                print(f"    next:   {r.reason}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
