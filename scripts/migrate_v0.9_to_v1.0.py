#!/usr/bin/env python3
"""Workspace migration v0.9 → v1.0 for BSA plugin family.

US-S2-02 part 2/3: renames legacy `no_new_facts_*` filenames in
existing `analysis/` runtime state to the canonical `no_new_claims_*`
naming introduced by Sprint 2 US-S2-02.

Authoritative rename specification:
  migrations/v0.9_to_v1.0/no_new_facts_rename.md

Properties:
  - Idempotent: re-running after a clean migration is a no-op.
  - Non-destructive: never overwrites an existing target; halts with
    exit 1 on any target-conflict BEFORE applying any rename.
  - Scoped: touches only 4 filename patterns; no body edits.
  - Logged: emits JSONL record per operation to
    `<workspace>/runtime/migration_log_v0.9_to_v1.0.jsonl`.
  - Dry-run by default (must pass --apply to actually rename).

Exit codes:
  0 — migration succeeded (or dry-run without conflicts)
  1 — at least one target-conflict detected (nothing renamed)
  2 — invocation error (missing/unreadable workspace, bad CLI)

Stdlib-only. Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# Authoritative rename mappings. Order matters only for deterministic
# log output. Each tuple: (mapping_id, rel_parent_glob_fragment,
# legacy_filename, canonical_filename).
#
# rel_parent_glob_fragment is matched as a suffix of the containing
# directory's POSIX path (relative to the workspace root). This way
# we rename files in both canonical and proposal layers, and across
# the optional discovery branch, without hardcoding absolute paths.
RENAME_MAPPINGS: tuple[tuple[int, str, str, str], ...] = (
    # (1) Discovery marker
    (1, "discovery/runtime/ready",
     "discovery.d5.no_new_facts.pass.json",
     "discovery.d5.no_new_claims.pass.json"),
    # (2) Stage 8 report — canonical
    (2, "canonical/stage8",
     "no_new_facts_report.md",
     "no_new_claims_report.md"),
    # (2a) Stage 8 report — proposal layer
    (3, "proposals/stage7_8/stage8",
     "no_new_facts_report.md",
     "no_new_claims_report.md"),
    # (3) Handoff report — proposal layer
    (4, "proposals/stage7_8/handoff",
     "handoff_no_new_facts_report.md",
     "handoff_no_new_claims_report.md"),
    # (4) Discovery D5 report — canonical
    (5, "discovery/canonical/d5",
     "discovery_no_new_facts_report.md",
     "discovery_no_new_claims_report.md"),
    # (4a) Discovery D5 report — proposal layer
    (6, "discovery/proposals/d5",
     "discovery_no_new_facts_report.md",
     "discovery_no_new_claims_report.md"),
)


@dataclass
class PlannedRename:
    mapping_id: int
    from_path: Path
    to_path: Path


@dataclass
class Conflict:
    mapping_id: int
    from_path: Path
    to_path: Path
    reason: str


@dataclass
class LogRecord:
    mapping_id: int
    from_path: str
    to_path: str
    mode: str  # renamed | skipped | error
    reason: str = ""
    dry_run: bool = True
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def to_json_line(self) -> str:
        payload = {
            "timestamp": self.timestamp,
            "migration": "v0.9_to_v1.0",
            "mapping_id": self.mapping_id,
            "from_path": self.from_path,
            "to_path": self.to_path,
            "mode": self.mode,
            "dry_run": self.dry_run,
        }
        if self.reason:
            payload["reason"] = self.reason
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _iter_candidate_parents(workspace: Path, parent_suffix: str) -> list[Path]:
    """Return every directory under `workspace` whose relative POSIX path ends with
    `parent_suffix`. Stable ordering (sorted) for deterministic output.

    May raise OSError / PermissionError if the workspace tree contains
    unreadable entries. Callers are expected to catch that and translate
    it into an invocation-error exit code rather than a traceback.
    """
    suffix = parent_suffix.strip("/")
    results: list[Path] = []
    for p in sorted(workspace.rglob("*")):
        if not p.is_dir():
            continue
        try:
            rel = p.relative_to(workspace).as_posix()
        except ValueError:
            continue
        if rel == suffix or rel.endswith("/" + suffix):
            results.append(p)
    return results


def plan_migration(workspace: Path) -> tuple[list[PlannedRename], list[Conflict], list[LogRecord]]:
    planned: list[PlannedRename] = []
    conflicts: list[Conflict] = []
    skipped_logs: list[LogRecord] = []

    for mapping_id, parent_suffix, legacy_name, canonical_name in RENAME_MAPPINGS:
        parents = _iter_candidate_parents(workspace, parent_suffix)
        if not parents:
            # No matching directory in this workspace — genuinely absent, not an error.
            skipped_logs.append(LogRecord(
                mapping_id=mapping_id,
                from_path=f"<any>/{parent_suffix}/{legacy_name}",
                to_path=f"<any>/{parent_suffix}/{canonical_name}",
                mode="skipped",
                reason="parent-dir-absent",
            ))
            continue
        for parent in parents:
            src = parent / legacy_name
            dst = parent / canonical_name
            if src.exists() and dst.exists():
                conflicts.append(Conflict(
                    mapping_id=mapping_id,
                    from_path=src,
                    to_path=dst,
                    reason="target-conflict",
                ))
                continue
            if src.exists() and not dst.exists():
                planned.append(PlannedRename(
                    mapping_id=mapping_id,
                    from_path=src,
                    to_path=dst,
                ))
                continue
            # src absent → already migrated or never existed
            skipped_logs.append(LogRecord(
                mapping_id=mapping_id,
                from_path=str(src),
                to_path=str(dst),
                mode="skipped",
                reason="source-missing",
            ))

    return planned, conflicts, skipped_logs


def apply_migration(
    workspace: Path,
    dry_run: bool,
) -> int:
    # Catch filesystem errors during planning and log-dir setup and
    # translate them to an invocation-error exit code (2) rather than
    # letting a traceback escape. Rename-time OSError during the apply
    # loop is already handled per-file as mode=error.
    try:
        planned, conflicts, skipped_logs = plan_migration(workspace)
    except (OSError, PermissionError) as exc:
        print(
            f"ERROR: cannot walk workspace {workspace}: {exc}",
            file=sys.stderr,
        )
        return 2

    log_dir = workspace / "runtime"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError) as exc:
        print(
            f"ERROR: cannot create migration log directory {log_dir}: {exc}",
            file=sys.stderr,
        )
        return 2
    log_path = log_dir / "migration_log_v0.9_to_v1.0.jsonl"

    # Conflict path: log every conflict + skipped; do NOT apply any rename.
    if conflicts:
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                for skip in skipped_logs:
                    skip.dry_run = dry_run
                    fh.write(skip.to_json_line() + "\n")
                for c in conflicts:
                    rec = LogRecord(
                        mapping_id=c.mapping_id,
                        from_path=str(c.from_path),
                        to_path=str(c.to_path),
                        mode="error",
                        reason=c.reason,
                        dry_run=dry_run,
                    )
                    fh.write(rec.to_json_line() + "\n")
        except (OSError, PermissionError) as exc:
            print(
                f"ERROR: cannot write migration log {log_path}: {exc}",
                file=sys.stderr,
            )
            return 2
        print(
            f"FAIL: {len(conflicts)} target-conflict(s). No renames applied.",
            file=sys.stderr,
        )
        for c in conflicts:
            print(f"  conflict: {c.from_path} vs {c.to_path}", file=sys.stderr)
        print(f"Log: {log_path}", file=sys.stderr)
        return 1

    # Apply phase.
    applied_count = 0
    errors: list[Conflict] = []
    records: list[LogRecord] = list(skipped_logs)
    for p in planned:
        if dry_run:
            records.append(LogRecord(
                mapping_id=p.mapping_id,
                from_path=str(p.from_path),
                to_path=str(p.to_path),
                mode="renamed",
                dry_run=True,
            ))
            continue
        try:
            p.from_path.rename(p.to_path)
            applied_count += 1
            records.append(LogRecord(
                mapping_id=p.mapping_id,
                from_path=str(p.from_path),
                to_path=str(p.to_path),
                mode="renamed",
                dry_run=False,
            ))
        except OSError as exc:
            errors.append(Conflict(
                mapping_id=p.mapping_id,
                from_path=p.from_path,
                to_path=p.to_path,
                reason=f"rename-error: {exc}",
            ))
            records.append(LogRecord(
                mapping_id=p.mapping_id,
                from_path=str(p.from_path),
                to_path=str(p.to_path),
                mode="error",
                reason=f"rename-error: {exc}",
                dry_run=False,
            ))

    # Write log records.
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            for rec in records:
                fh.write(rec.to_json_line() + "\n")
    except (OSError, PermissionError) as exc:
        print(
            f"ERROR: cannot write migration log {log_path}: {exc}",
            file=sys.stderr,
        )
        return 2

    mode_label = "dry-run" if dry_run else "applied"
    if errors:
        print(
            f"PARTIAL: {applied_count} renamed, {len(errors)} error(s). Log: {log_path}",
            file=sys.stderr,
        )
        for e in errors:
            print(f"  error: {e.from_path} -> {e.to_path}: {e.reason}", file=sys.stderr)
        return 1

    print(
        f"OK ({mode_label}): {len(planned)} rename(s) planned, "
        f"{len(skipped_logs)} skipped, {applied_count} actually renamed. "
        f"Log: {log_path}"
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="BSA workspace migration v0.9 → v1.0 (US-S2-02 filename rename)."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="Path to the workspace root (typically a directory containing `analysis/` subdirs).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually perform the renames. Default: dry-run (plans and logs without modifying).",
    )
    args = parser.parse_args(argv)

    # Preflight the workspace path. stat() failure (e.g. parent directory
    # has no exec permission, so the lookup itself raises PermissionError)
    # must surface as exit 2, not as a Python traceback.
    try:
        exists = args.workspace.exists()
        is_dir = args.workspace.is_dir() if exists else False
    except (OSError, PermissionError) as exc:
        print(
            f"ERROR: cannot access workspace {args.workspace}: {exc}",
            file=sys.stderr,
        )
        return 2
    if not exists:
        print(f"ERROR: workspace does not exist: {args.workspace}", file=sys.stderr)
        return 2
    if not is_dir:
        print(f"ERROR: workspace is not a directory: {args.workspace}", file=sys.stderr)
        return 2

    return apply_migration(args.workspace, dry_run=not args.apply)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
