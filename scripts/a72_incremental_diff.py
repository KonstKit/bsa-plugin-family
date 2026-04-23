#!/usr/bin/env python3
"""A72 traceability matrix incremental-diff helper (v1.2.2, T1).

Closes TODO-S8-02-INCREMENTAL-MATRIX from
skills/bsa-traceability-matrix/SKILL.md. For engagements with
thousands of triples, a full matrix re-build on every
`bsa-dev-handoff` invocation is wasteful — the Phase-3 SKILL.md
has documented this since v1.1.0 but provided no mechanical hook
for the LLM to scope its rebuild.

This script:
  1. Computes a per-row hash of the current A70/A59/A50/A62 inputs.
  2. Compares to a stored cache at
     `analysis/canonical/.a72_incremental_state.json` (operator-side
     cache; NOT canonical state, NOT F5-validated, NOT in POLICY_GLOBS).
  3. Outputs a diff classifying each upstream row as:
       added       — new ID since last build
       modified    — existing ID, hash changed
       removed     — existing ID gone
       unchanged   — same hash
  4. The LLM can then scope its A72 re-emission: for `unchanged` rows
     that already have A72 entries, copy them forward; for added /
     modified / removed, recompute the affected A72 triples.

The cache file shape is a nested dict:
  ``{"cache_version": "1.0", "row_hashes": {<artifact>: {<row_id>: <sha256>}}}``
where ``<artifact>`` is one of TRACKED_ARTIFACTS keys (A50/A59/A70/A62)
and ``<row_id>`` is the artifact's natural ID column value. The cache
is operator-side state — NOT F5-validated, NOT in POLICY_GLOBS — but
``_load_cache()`` does enforce structural sanity (v1.2.2 round-1
hardening): any malformed shape (top-level not dict, wrong
``cache_version``, ``row_hashes`` not dict, artifact sub-tree not dict,
mixed-type key/value inside sub-tree) → reject the WHOLE cache → empty
prior → next run is a full rebuild + cache repopulation. Missing
artifact sub-trees ARE tolerated (forward-compat for caches written
before a tracked artifact was added).

Stdlib-only. CLI:

  scripts/a72_incremental_diff.py --workspace <path>
  scripts/a72_incremental_diff.py --workspace <path> --force-rebuild
  scripts/a72_incremental_diff.py --workspace <path> --update-cache
  scripts/a72_incremental_diff.py --workspace <path> --json

Exit codes:
  0 — diff computed successfully (use --json to consume programmatically;
      includes the cache-missing / cache-corrupt / cache-version-mismatch
      cases — those silently fall back to an empty-prior diff which
      classifies every current row as `added`).
  1 — explicit full-rebuild signal: ONLY emitted when `--force-rebuild`
      is passed (the operator opts in). The downstream LLM treats this
      as a hard-rebuild instruction.
  2 — invocation error (no workspace, malformed canonical CSV, etc.)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Per-artifact upstream sources the matrix depends on. Adding a 4th
# tracked artifact here just adds it to the diff output; the
# downstream LLM scoping logic decides what to do with each.
TRACKED_ARTIFACTS = {
    "A70": ("analysis/canonical/core_controls/A70_story_register.csv", "StoryID"),
    "A59": ("analysis/canonical/core_controls/A59_claim_register.csv", "ClaimID"),
    "A50": ("analysis/canonical/core_controls/A50_source_register.csv", "SourceID"),
    "A62": ("analysis/canonical/core_controls/A62_nfr_register.csv", "NFRID"),
}

CACHE_REL = "analysis/canonical/.a72_incremental_state.json"
CACHE_VERSION = "1.0"


@dataclass(frozen=True)
class RowDiff:
    """One row's classification."""
    artifact: str
    row_id: str
    status: str  # added | modified | removed | unchanged
    old_hash: str = ""
    new_hash: str = ""


@dataclass
class DiffSummary:
    """Roll-up of per-row classifications."""
    added: int = 0
    modified: int = 0
    removed: int = 0
    unchanged: int = 0
    rows: list[RowDiff] = field(default_factory=list)

    def add(self, diff: RowDiff) -> None:
        self.rows.append(diff)
        setattr(self, diff.status, getattr(self, diff.status) + 1)

    @property
    def needs_full_rebuild(self) -> bool:
        """A re-build is needed if ANY row changed (added, modified,
        or removed). Pure unchanged → no rebuild needed."""
        return self.added > 0 or self.modified > 0 or self.removed > 0


def _hash_row(row: dict) -> str:
    """Stable SHA-256 over the row's sorted (key, value) pairs.
    Encoding via JSON canonicalises types (str / int / null) while
    sorting keys keeps the output order-independent. Per-row hashes
    are intentionally simple — we don't need cryptographic
    collision resistance, just structural fingerprinting."""
    encoded = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_artifact(path: Path, id_column: str) -> dict[str, str]:
    """Read one canonical CSV; return {row_id: row_hash} mapping.
    Skips rows with empty IDs (defensive — F5 should already reject
    those, but malformed inputs shouldn't crash the diff)."""
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            row_id = (row.get(id_column) or "").strip()
            if not row_id:
                continue
            out[row_id] = _hash_row(row)
    return out


def _load_cache(cache_path: Path) -> dict[str, dict[str, str]]:
    """Return {artifact: {row_id: hash}} dict from the cache file.
    Returns {} (forces full rebuild) on ANY structural violation:
      * file missing
      * malformed JSON
      * top-level not a dict
      * wrong / missing cache_version
      * row_hashes not a dict
      * any tracked artifact's sub-tree not a dict
      * any sub-tree contains non-string key OR non-string value
    v1.2.2 round-1 (Codex MEDIUM): earlier impl silently coerced
    bad sub-trees to {} and filtered non-string entries — that left
    the cache partially loaded and `compute_diff` could still emit
    `unchanged` rows from a malformed cache, defeating the
    documented fail-CLOSED model. Now any inconsistency forces a
    full rebuild."""
    if not cache_path.is_file():
        return {}
    try:
        with cache_path.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(doc, dict):
        return {}
    if doc.get("cache_version") != CACHE_VERSION:
        return {}
    row_hashes = doc.get("row_hashes")
    if not isinstance(row_hashes, dict):
        return {}
    # Strict: every tracked artifact MUST have a dict sub-tree (even
    # if empty). Missing keys are tolerated (forward-compat with a
    # cache written before a tracked artifact was added). Anything
    # PRESENT but not-dict → reject the whole cache.
    out: dict[str, dict[str, str]] = {}
    for artifact in TRACKED_ARTIFACTS:
        sub = row_hashes.get(artifact)
        if sub is None:
            out[artifact] = {}
            continue
        if not isinstance(sub, dict):
            return {}
        # Strict per-row: every key + value must be string. Mixed
        # types in the sub-tree → reject the whole cache.
        for k, v in sub.items():
            if not isinstance(k, str) or not isinstance(v, str):
                return {}
        out[artifact] = dict(sub)
    return out


def _write_cache(cache_path: Path, current: dict[str, dict[str, str]]) -> None:
    """Atomic write: tmpfile in same dir → mv (same-FS atomicity guarantee)."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile, os
    fd, tmp = tempfile.mkstemp(
        dir=cache_path.parent, prefix=".a72_incremental_state_", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({
                "cache_version": CACHE_VERSION,
                "_comment": (
                    "Operator-side incremental-diff cache for A72 matrix "
                    "rebuilds. NOT canonical state — safe to delete (forces "
                    "full rebuild on next bsa-dev-handoff). NOT F5-validated. "
                    "NOT in POLICY_GLOBS."
                ),
                "row_hashes": current,
            }, fh, indent=2)
        os.replace(tmp, cache_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def compute_diff(
    workspace: Path, prior: dict[str, dict[str, str]],
) -> DiffSummary:
    """Walk every TRACKED_ARTIFACTS upstream, compute per-row hash,
    classify against `prior`."""
    summary = DiffSummary()
    for artifact, (rel_path, id_column) in TRACKED_ARTIFACTS.items():
        current = _read_artifact(workspace / rel_path, id_column)
        old = prior.get(artifact, {})
        # Added / modified / unchanged.
        for row_id, new_hash in current.items():
            old_hash = old.get(row_id, "")
            if not old_hash:
                summary.add(RowDiff(artifact, row_id, "added", new_hash=new_hash))
            elif old_hash != new_hash:
                summary.add(RowDiff(
                    artifact, row_id, "modified",
                    old_hash=old_hash, new_hash=new_hash,
                ))
            else:
                summary.add(RowDiff(
                    artifact, row_id, "unchanged",
                    old_hash=old_hash, new_hash=new_hash,
                ))
        # Removed.
        for row_id, old_hash in old.items():
            if row_id not in current:
                summary.add(RowDiff(artifact, row_id, "removed", old_hash=old_hash))
    return summary


def collect_current_hashes(workspace: Path) -> dict[str, dict[str, str]]:
    """Snapshot the current state for cache-update purposes."""
    return {
        artifact: _read_artifact(workspace / rel_path, id_column)
        for artifact, (rel_path, id_column) in TRACKED_ARTIFACTS.items()
    }


def format_text_summary(summary: DiffSummary) -> str:
    """Operator-readable diff report."""
    total = summary.added + summary.modified + summary.removed + summary.unchanged
    lines = [
        f"# A72 Incremental Diff",
        "",
        f"Total upstream rows: {total}",
        f"  added:     {summary.added:5}",
        f"  modified:  {summary.modified:5}",
        f"  removed:   {summary.removed:5}",
        f"  unchanged: {summary.unchanged:5}",
        "",
    ]
    if summary.needs_full_rebuild:
        lines.append(f"Rebuild scope: {summary.added + summary.modified + summary.removed} affected upstream row(s); incremental rebuild possible.")
    else:
        lines.append("Rebuild scope: ZERO changes — A72 may be re-emitted from cache without recomputation.")
    if summary.added or summary.modified or summary.removed:
        lines.append("")
        lines.append("## Affected rows")
        for d in summary.rows:
            if d.status == "unchanged":
                continue
            lines.append(f"  [{d.status:8}] {d.artifact}:{d.row_id}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="A72 incremental-diff helper (T1)",
    )
    parser.add_argument(
        "--workspace", type=Path, default=Path.cwd(),
        help="BSA workspace root (defaults to cwd)",
    )
    parser.add_argument(
        "--force-rebuild", action="store_true",
        help="Treat the cache as missing — exit 1 with full-rebuild signal",
    )
    parser.add_argument(
        "--update-cache", action="store_true",
        help="After diff, refresh the cache to the current snapshot",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of text report",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    workspace = args.workspace.resolve()
    if not (workspace / "analysis").is_dir():
        print(
            f"a72_incremental_diff: workspace {workspace} is not initialized "
            f"(no analysis/ directory). Run /bsa-start first.",
            file=sys.stderr,
        )
        return 2

    cache_path = workspace / CACHE_REL
    if args.force_rebuild:
        prior: dict[str, dict[str, str]] = {}
    else:
        prior = _load_cache(cache_path)

    summary = compute_diff(workspace, prior)

    if args.json:
        print(json.dumps({
            "added": summary.added,
            "modified": summary.modified,
            "removed": summary.removed,
            "unchanged": summary.unchanged,
            "needs_full_rebuild": summary.needs_full_rebuild,
            "rows": [
                {
                    "artifact": r.artifact, "row_id": r.row_id,
                    "status": r.status, "old_hash": r.old_hash,
                    "new_hash": r.new_hash,
                }
                for r in summary.rows
            ],
        }, indent=2))
    else:
        print(format_text_summary(summary))

    if args.update_cache:
        current = collect_current_hashes(workspace)
        _write_cache(cache_path, current)
        if not args.json:
            print(f"\nCache updated: {cache_path}", file=sys.stderr)

    # Exit 1 if a force-rebuild was requested (signals downstream
    # tooling to do a full rebuild). Exit 0 otherwise.
    return 1 if args.force_rebuild else 0


if __name__ == "__main__":
    raise SystemExit(main())
