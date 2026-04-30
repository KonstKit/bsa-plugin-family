"""Workspace subcommand for `bsa` CLI (v1.4.10).

Closes lifecycle review rec #6 — workspace snapshot/restore/bundle
operations. Three operator-driven actions:

  bsa workspace snapshot [--output PATH] [--include-raw]
    Dump the WHOLE workspace to a timestamped tar.gz under
    <workspace>/snapshots/ (or --output). Includes runtime markers,
    .bak files, lock files — full state suitable for rollback.
    Excludes raw/ by default (large) unless --include-raw.

  bsa workspace restore --from PATH [--force]
    Unpack a snapshot tar.gz back over a workspace. Refuses if
    target workspace already has analysis/ unless --force (defends
    against accidental clobbering of in-progress work).

  bsa workspace bundle [--output PATH] [--minimal]
    Pack workspace for TRANSFER / SHARING. Excludes ephemeral state:
    .bsa_materials.lock, source_manifest.csv.bak.*, runtime/,
    raw/, .pytest_cache, __pycache__. With --minimal also drops
    proposals/ (canonical-only bundle).

Public surface (re-exported from bsa_cli.py):
  * `cmd_workspace(args)` — argparse subcommand handler.
  * `_snapshot(workspace, output, include_raw)` — pure helper.
  * `_restore(workspace, source_path, force)` — pure helper.
  * `_bundle(workspace, output, minimal)` — pure helper.

Dependencies:
  * Stdlib only — `tarfile` for archive build/extract.
  * No new external dependencies.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Patterns for path filtering during bundle/snapshot.
# Patterns matched against POSIX-style paths relative to the workspace
# root (e.g. "analysis/runtime/foo.json"). Any segment matching the
# excluded set short-circuits inclusion.
_BUNDLE_EXCLUDED_NAMES = frozenset({
    ".bsa_materials.lock",
    "__pycache__",
    ".pytest_cache",
    ".DS_Store",
    "raw",  # heavy; keep snapshot small
})
# .bak.<UTC-timestamp> files — match by suffix pattern.
_BAK_PATTERN = re.compile(r"\.bak(\.[0-9TZ_]+)?$")


def _utc_timestamp() -> str:
    """ISO-8601-ish UTC timestamp safe for filenames (no `:`)."""
    return datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_timestamp_microsecond() -> str:
    """Microsecond-precision UTC timestamp for collision-safe filenames.

    v1.4.10 R1 MINOR #2 fix: snapshot/bundle output filenames now use
    microsecond precision so two runs in the same UTC second don't
    collide on `os.replace` (which silently overwrites)."""
    return datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def _allocate_unique_path(
    candidate: Path, *, max_attempts: int = 64,
) -> Path:
    """v1.4.10 R1 MINOR #2 fix: if `candidate` exists, append `_<n>`
    counter until we find an unused path. Defends against the
    same-microsecond collision case (theoretically possible if
    two operators race) AND the operator-passed `--output` collision."""
    if not candidate.exists():
        return candidate
    stem = candidate.name
    for n in range(1, max_attempts + 1):
        # candidate has shape `name.tar.gz` → bisect on `.tar.gz` to
        # insert counter before the compound suffix.
        if stem.endswith(".tar.gz"):
            base = stem[:-len(".tar.gz")]
            new_name = f"{base}_{n}.tar.gz"
        else:
            new_name = f"{stem}_{n}"
        new_path = candidate.with_name(new_name)
        if not new_path.exists():
            return new_path
    raise FileExistsError(
        f"could not allocate a unique output name near {candidate} "
        f"after {max_attempts} attempts"
    )


def _resolve_workspace(workspace: Path) -> Path:
    """Validate + resolve. Raises FileNotFoundError if no analysis/."""
    ws = workspace.resolve()
    if not ws.is_dir():
        raise FileNotFoundError(
            f"workspace path is not a directory: {ws}"
        )
    if not (ws / "analysis").is_dir():
        raise FileNotFoundError(
            f"{ws} does not look like a BSA workspace "
            f"(no analysis/ subdirectory). Run /bsa-start first."
        )
    return ws


def _should_include_in_snapshot(
    rel_path: Path, *, include_raw: bool,
) -> bool:
    """Snapshot inclusion rule.

    Includes EVERYTHING under analysis/ EXCEPT:
      * raw/ subdirectory (skipped unless include_raw=True; large)
      * __pycache__ / .pytest_cache (always skipped — vendored noise)
      * .DS_Store (macOS)

    Backup files (.bak.<ts>) ARE included — snapshots are full state.
    Lock files ARE included — snapshots are full state.
    Runtime markers ARE included — snapshots are full state.
    """
    parts = rel_path.parts
    for seg in parts:
        if seg in {"__pycache__", ".pytest_cache", ".DS_Store"}:
            return False
        if seg == "raw" and not include_raw:
            return False
    return True


def _should_include_in_bundle(
    rel_path: Path, *, minimal: bool,
) -> bool:
    """Bundle inclusion rule — STRICTER than snapshot.

    Excludes ephemeral state irrelevant to a transfer recipient:
      * .bsa_materials.lock (process-local)
      * source_manifest.csv.bak.* (recovery state, not canonical)
      * Known runtime-marker prefixes: `analysis/runtime/` AND
        `analysis/discovery/runtime/` (markers; recipient regenerates).
        v1.4.10 R1 MINOR #1 fix: was matching ANY `runtime` segment,
        which would silently drop unrelated subdirectories like
        `analysis/proposals/stage1/runtime/foo` if they ever existed.
      * raw/ (heavy; recipient can re-stage)
      * __pycache__ / .pytest_cache / .DS_Store
      * --minimal: also drop proposals/ (canonical-only)
    """
    parts = rel_path.parts
    for seg in parts:
        if seg in _BUNDLE_EXCLUDED_NAMES:
            return False
        if _BAK_PATTERN.search(seg):
            return False
    # v1.4.10 R1 MINOR #1 fix: match only KNOWN runtime-marker
    # path prefixes, not ANY segment named `runtime`.
    posix_path = rel_path.as_posix()
    if (
        posix_path == "analysis/runtime"
        or posix_path.startswith("analysis/runtime/")
        or posix_path == "analysis/discovery/runtime"
        or posix_path.startswith("analysis/discovery/runtime/")
    ):
        return False
    if minimal and "proposals" in parts:
        return False
    return True


def _snapshot(
    workspace: Path,
    output: Optional[Path],
    include_raw: bool,
) -> Path:
    """Build a snapshot tar.gz. Returns the resolved output path.

    Default output: `<workspace>/snapshots/snapshot-<UTC>.tar.gz`.
    Operator can override via --output.

    Atomic: writes to <output>.tmp first, then os.replace to final
    name (so a partial write doesn't leave a corrupt archive at the
    canonical path).
    """
    ws = _resolve_workspace(workspace)
    if output is None:
        snap_dir = ws / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        # v1.4.10 R1 MINOR #2 fix: microsecond-precision timestamp +
        # _allocate_unique_path collision retry. Default name no
        # longer races on os.replace.
        out_path = _allocate_unique_path(
            snap_dir / f"snapshot-{_utc_timestamp_microsecond()}.tar.gz",
        )
    else:
        out_path = output.resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Operator-passed --output: respect their literal name but
        # still apply collision-retry so two parallel runs don't
        # silently clobber each other.
        out_path = _allocate_unique_path(out_path)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    analysis_dir = ws / "analysis"
    # v1.4.10 R1 MINOR #3 fix: if --output lands inside analysis/,
    # the in-progress .tmp would be picked up by os.walk and bundled
    # into its own archive (silent recursion). Skip them explicitly.
    skip_realpaths = {tmp_path.resolve(), out_path.resolve()}
    file_count = 0
    bytes_written = 0
    try:
        with tarfile.open(tmp_path, "w:gz") as tar:
            for root, dirs, files in os.walk(analysis_dir):
                root_path = Path(root)
                rel_root = root_path.relative_to(ws)
                # Filter dirs in-place so os.walk doesn't recurse
                # into excluded subtrees.
                dirs[:] = [
                    d for d in dirs
                    if _should_include_in_snapshot(
                        rel_root / d, include_raw=include_raw,
                    )
                ]
                for fname in files:
                    abs_path = root_path / fname
                    if abs_path.resolve() in skip_realpaths:
                        continue  # don't tar the in-progress archive
                    rel_path = abs_path.relative_to(ws)
                    if not _should_include_in_snapshot(
                        rel_path, include_raw=include_raw,
                    ):
                        continue
                    tar.add(str(abs_path), arcname=str(rel_path))
                    file_count += 1
                    try:
                        bytes_written += abs_path.stat().st_size
                    except OSError:
                        pass
        os.replace(str(tmp_path), str(out_path))
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    print(
        f"[bsa workspace snapshot] {file_count} file(s), "
        f"{bytes_written:,} bytes → {out_path}"
    )
    return out_path


def _validate_archive_path(name: str, kind: str = "member") -> None:
    """v1.4.10 R1 MAJOR #4 fix: centralized archive-path validation
    used for both member NAMES and link TARGETS.

    Rejects:
      * Absolute POSIX paths (`/foo`).
      * Windows drive-letter paths (`C:\\foo`, `c:foo`).
      * Backslash anywhere (Windows-native paths in tar archives
        can sneak past POSIX-only checks).
      * UNC paths (`\\\\server\\share`, `//server/share`).
      * Parent-traversal segments (`..` anywhere in the path).
      * Empty path or pure whitespace.
      * Embedded NUL bytes (filesystem path-injection).
    """
    if not name or not name.strip():
        raise ValueError(f"refusing archive with empty {kind} name")
    if "\x00" in name:
        raise ValueError(
            f"refusing archive with NUL byte in {kind} name: {name!r}"
        )
    if "\\" in name:
        raise ValueError(
            f"refusing archive with backslash in {kind} name "
            f"(Windows-native path): {name!r}"
        )
    if name.startswith("/") or name.startswith("//"):
        raise ValueError(
            f"refusing archive with absolute / UNC {kind} path: {name!r}"
        )
    # Windows drive-letter check: `C:foo` or `C:\foo`.
    if len(name) >= 2 and name[1] == ":" and name[0].isalpha():
        raise ValueError(
            f"refusing archive with Windows drive-letter {kind} path: {name!r}"
        )
    # Parent-traversal: `..` as a path segment.
    if ".." in Path(name).parts:
        raise ValueError(
            f"refusing archive with parent-traversal {kind}: {name!r}"
        )


def _restore(
    workspace: Path,
    source_path: Path,
    force: bool,
) -> Path:
    """Unpack a snapshot tar.gz back over the workspace.

    Safety (v1.4.10 R1 fixes):
      * **MAJOR #1** (atomic --force): extract to a same-filesystem
        staging dir FIRST, then swap analysis/ via backup + rename.
        Rollback on any failure keeps the workspace's existing
        analysis/ intact.
      * **MAJOR #2** (analysis/-only constraint): every archive
        member MUST be exactly `analysis` or under `analysis/`.
        Defends against archives that try to write `.git/hooks/...`,
        `scripts/backdoor.py`, etc. under the workspace root.
      * **MAJOR #3** (allowlist member type): only REGTYPE / AREGTYPE
        (regular files), DIRTYPE (directories), SYMTYPE / LNKTYPE
        (symlinks / hardlinks with validated targets) accepted.
        FIFOs / block devices / char devices / unknown types
        rejected (no use case in BSA workspace, large attack surface).
      * **MAJOR #4** (path validation): centralized via
        `_validate_archive_path` — covers POSIX absolute paths,
        Windows drive letters / backslash / UNC, NUL bytes,
        parent-traversal, empty names. Applied to BOTH member names
        AND link targets.
      * Refuses if target `<workspace>/analysis/` already exists
        unless `force=True` (operator may have in-progress work).
    """
    import shutil
    import tempfile
    ws = workspace.resolve()
    ws.mkdir(parents=True, exist_ok=True)
    src = source_path.resolve()
    if not src.is_file():
        raise FileNotFoundError(
            f"snapshot source not found: {src}"
        )
    analysis_dir = ws / "analysis"
    if analysis_dir.exists() and not force:
        raise FileExistsError(
            f"refuse to overwrite existing workspace at {ws} "
            f"(analysis/ present). Pass --force to proceed."
        )
    # v1.4.10 R1 MAJOR #3 type allowlist.
    _ALLOWED_TYPES = {
        tarfile.REGTYPE, tarfile.AREGTYPE,
        tarfile.DIRTYPE,
        tarfile.SYMTYPE, tarfile.LNKTYPE,
    }
    # Validate every archive member BEFORE staging-extract so we
    # never touch the disk if the archive is malicious.
    with tarfile.open(src, "r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            # Type allowlist (R1 MAJOR #3).
            if member.type not in _ALLOWED_TYPES:
                raise ValueError(
                    f"refusing snapshot with disallowed member type "
                    f"{member.type!r} for {member.name!r} "
                    f"(only regular files, directories, and validated "
                    f"links accepted)"
                )
            # Centralized path validation (R1 MAJOR #4).
            _validate_archive_path(member.name, kind="member")
            # analysis/-only constraint (R1 MAJOR #2).
            parts = Path(member.name).parts
            if not parts or parts[0] != "analysis":
                raise ValueError(
                    f"refusing snapshot member outside analysis/: "
                    f"{member.name!r} (workspace restore is "
                    f"analysis/-scoped only)"
                )
            # v1.4.10 R2 NEW MAJOR fix: the root `analysis` entry
            # MUST be a real directory, not a symlink. A crafted
            # archive could otherwise restore `analysis` as a
            # symlink to `.` (the workspace root) — turning future
            # writes under analysis/ into writes anywhere in the
            # workspace, AND creating an infinite-loop self-ref.
            if member.name == "analysis" and not member.isdir():
                raise ValueError(
                    f"refusing snapshot whose root `analysis` entry "
                    f"is not a directory (got type "
                    f"{member.type!r}); the workspace boundary must "
                    f"be a real dir."
                )
            # Link-target validation.
            if member.issym() or member.islnk():
                target = member.linkname
                _validate_archive_path(target, kind="link target")
                # v1.4.10 R2 NEW MAJOR fix: explicitly reject link
                # targets that are `.`, `./`, or empty (resolve to
                # current dir = workspace boundary escape via
                # self-ref).
                t_parts = Path(target).parts
                if not t_parts or t_parts == (".",) or target.strip() == "":
                    raise ValueError(
                        f"refusing snapshot with self-referential "
                        f"link {member.name!r} → {target!r}"
                    )

        # v1.4.10 R1 MAJOR #1: stage extract to a temp dir on the
        # SAME filesystem, then swap into place. Same-fs is required
        # for the os.replace dance to be atomic.
        staging = Path(
            tempfile.mkdtemp(
                prefix=".bsa_restore_staging.", dir=str(ws),
            )
        )
        backup_dir: Optional[Path] = None
        try:
            tar.extractall(str(staging))
            staged_analysis = staging / "analysis"
            # v1.4.10 R2 NEW MAJOR fix (defense-in-depth): re-verify
            # the staged `analysis/` is a REAL directory, not a
            # symlink. The pre-extract validation already rejects
            # symlink-as-root, but some tarfile implementations
            # (older Python) might silently coerce types — extra
            # check costs nothing.
            if not staged_analysis.is_dir() or staged_analysis.is_symlink():
                raise ValueError(
                    "snapshot extracted but `analysis/` is missing or "
                    "is a symlink (boundary violation) — refusing to "
                    "swap"
                )
            # Atomic swap: rename existing analysis/ to backup, move
            # staged in, delete backup. If anything fails after the
            # rename, restore the backup.
            if analysis_dir.exists():
                backup_dir = ws / f".bsa_analysis_backup.{_utc_timestamp()}"
                os.rename(str(analysis_dir), str(backup_dir))
            try:
                os.rename(str(staged_analysis), str(analysis_dir))
            except OSError:
                # Restore backup if rename failed.
                if backup_dir is not None and backup_dir.exists():
                    os.rename(str(backup_dir), str(analysis_dir))
                    backup_dir = None
                raise
            # Success — purge the backup.
            if backup_dir is not None and backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
                backup_dir = None
        finally:
            # Always clean staging dir (whether success or failure).
            shutil.rmtree(staging, ignore_errors=True)
    print(
        f"[bsa workspace restore] restored from {src} into {ws}"
    )
    return ws


def _bundle(
    workspace: Path,
    output: Optional[Path],
    minimal: bool,
) -> Path:
    """Build a transfer/sharing tar.gz of the workspace.

    Drops ephemeral / regenerable state to keep the bundle small.
    See `_should_include_in_bundle` for the exclusion list.
    """
    ws = _resolve_workspace(workspace)
    if output is None:
        snap_dir = ws / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        suffix = "-minimal" if minimal else ""
        out_path = _allocate_unique_path(
            snap_dir
            / f"bundle-{_utc_timestamp_microsecond()}{suffix}.tar.gz",
        )
    else:
        out_path = output.resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path = _allocate_unique_path(out_path)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    analysis_dir = ws / "analysis"
    skip_realpaths = {tmp_path.resolve(), out_path.resolve()}
    file_count = 0
    bytes_written = 0
    try:
        with tarfile.open(tmp_path, "w:gz") as tar:
            for root, dirs, files in os.walk(analysis_dir):
                root_path = Path(root)
                rel_root = root_path.relative_to(ws)
                dirs[:] = [
                    d for d in dirs
                    if _should_include_in_bundle(
                        rel_root / d, minimal=minimal,
                    )
                ]
                for fname in files:
                    abs_path = root_path / fname
                    if abs_path.resolve() in skip_realpaths:
                        continue
                    rel_path = abs_path.relative_to(ws)
                    if not _should_include_in_bundle(
                        rel_path, minimal=minimal,
                    ):
                        continue
                    tar.add(str(abs_path), arcname=str(rel_path))
                    file_count += 1
                    try:
                        bytes_written += abs_path.stat().st_size
                    except OSError:
                        pass
        os.replace(str(tmp_path), str(out_path))
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    label = "minimal " if minimal else ""
    print(
        f"[bsa workspace bundle] {label}{file_count} file(s), "
        f"{bytes_written:,} bytes → {out_path}"
    )
    return out_path


def cmd_workspace(args: argparse.Namespace) -> int:
    """Dispatcher for `bsa workspace {snapshot|restore|bundle}`.

    Exit codes:
      0 — success.
      1 — operation-level failure (refused due to safety / partial).
      2 — invocation error (bad path / missing required arg).
    """
    action = getattr(args, "ws_action", None)
    workspace = Path(getattr(args, "workspace", ".")).resolve()
    if action == "snapshot":
        try:
            _snapshot(
                workspace,
                output=Path(args.output) if args.output else None,
                include_raw=bool(args.include_raw),
            )
        except FileNotFoundError as exc:
            sys.stderr.write(f"[bsa workspace snapshot] {exc}\n")
            return 2
        return 0
    if action == "restore":
        try:
            _restore(
                workspace,
                source_path=Path(args.from_path),
                force=bool(args.force),
            )
        except FileNotFoundError as exc:
            sys.stderr.write(f"[bsa workspace restore] {exc}\n")
            return 2
        except FileExistsError as exc:
            sys.stderr.write(f"[bsa workspace restore] {exc}\n")
            return 1
        except (ValueError, tarfile.TarError) as exc:
            sys.stderr.write(f"[bsa workspace restore] {exc}\n")
            return 1
        return 0
    if action == "bundle":
        try:
            _bundle(
                workspace,
                output=Path(args.output) if args.output else None,
                minimal=bool(args.minimal),
            )
        except FileNotFoundError as exc:
            sys.stderr.write(f"[bsa workspace bundle] {exc}\n")
            return 2
        return 0
    sys.stderr.write(
        f"[bsa workspace] unknown action {action!r}; "
        f"expected snapshot|restore|bundle\n"
    )
    return 2
