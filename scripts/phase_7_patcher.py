#!/usr/bin/env python3
"""Phase 7 L2 auto-patcher (v1.2.19).

Reads a miner proposal bundle from `analysis/telemetry/miner_proposals.json`
(produced by `scripts/phase_7_miner.py` v1.2.18, schema
`governance/schemas/miner_proposal.schema.json`), validates each proposal
against the live `config/tunables.yaml` state, and emits per-proposal
unified-diff patches + human-readable summaries to
`analysis/telemetry/proposals/`.

**The patcher NEVER:**

  * runs `git apply`, `git commit`, `git push`, or any git-mutating
    command;
  * modifies canonical state (`analysis/canonical/`) or POLICY_GLOBS
    files directly;
  * edits the source files referenced by tunables — it only writes
    patch files describing what an analyst could choose to apply.

The "auto" in L2 is **proposal generation**, NOT auto-apply. The
operator still runs `git apply <proposal>.patch` manually after the
review pass documented in `docs/phase_7_runbook.md`.

## Validation pipeline

For each proposal in the bundle, the patcher walks these gates in
order; failure at any gate marks the proposal as `rejected` (no
patch written) with a structured reason:

  1. **immutable_conflict gate** — runtime mirror of phase_7_lint C5.
     Rejects any proposal where `immutable_conflict=true` regardless
     of bundle/operator state. This is unconditional.
  2. **change_class gate** — only `L2_proposal_only` proposals are
     materialized. `L1_auto_tunable` proposals are SKIPPED (the L1
     auto-merge path is operator tooling outside this script's scope).
  3. **tunable_id resolution** — must match an `id` from the live
     `config/tunables.yaml`. Unknown ids are rejected.
  4. **current_value drift gate** — the proposal's `current_value`
     MUST equal the live tunable's `current_value`. If the tunable
     has been edited since the miner ran, the proposal is stale and
     rejected (operator should re-run the miner).
  5. **range gate** — the proposal's `proposed_value` parsed as a
     number MUST fall within the live tunable's `allowed_range`.
  6. **POLICY_GLOBS safety gate** — the live tunable's `source_file`
     MUST NOT match any POLICY_GLOBS pattern from
     `scripts/compute_canon_hash.py` for `L1_auto_tunable` entries
     (defensive — the lint already enforces this statically; if it
     somehow slips through, the patcher refuses). For
     `L2_proposal_only` the source_file MAY live in POLICY_GLOBS
     (analyst sign-off includes the manifest bump per phase_7_lint
     C6); the patcher proceeds.
  7. **no-op gate** — if `proposed_value == current_value`, skip
     (no patch needed).

## Output layout

```
analysis/telemetry/proposals/
  <proposal_id>.patch       # unified diff, single-file change
  <proposal_id>.summary.md  # human-readable rationale + how-to-apply
  _index.json               # bundle-level summary of all attempts
```

The `_index.json` always exists (even when 0 patches written), so
operators have a single deterministic entry point for inspecting the
last patcher run.

## Pattern lineage

Mirrors the v1.2.4 `phase_7_telemetry_collector.py` + v1.2.16
`freshness_audit.py` + v1.2.18 `phase_7_miner.py` operator-runner
pattern: stdlib + pyyaml only, defensive reads, atomic writes via
tempfile + os.replace, `--print-only` / `--quiet` / `--workspace`
CLI surface, exit codes (0 on completion, 2 on invocation error).

NOT canonical state. NOT in POLICY_GLOBS. The v1.2.19 manifest stays
at 1.2.17 (script + schema + tests outside POLICY_GLOBS).

CLI:
  scripts/phase_7_patcher.py --workspace <path>
  scripts/phase_7_patcher.py --workspace <path> --input <bundle.json>
  scripts/phase_7_patcher.py --workspace <path> --output-dir <dir>
  scripts/phase_7_patcher.py --workspace <path> --print-only
  scripts/phase_7_patcher.py --workspace <path> --quiet

Exit codes:
  0 — patcher completed (zero or more patches written; rejections
      are counted, not error-coded).
  2 — invocation error (workspace not initialized, malformed
      bundle JSON, missing tunables.yaml, etc.).
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import shlex
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_BUNDLE_REL = "analysis/telemetry/miner_proposals.json"
DEFAULT_OUTPUT_REL = "analysis/telemetry/proposals"
TUNABLES_REL = "config/tunables.yaml"
CANON_HASH_REL = "scripts/compute_canon_hash.py"

INDEX_FILENAME = "_index.json"

# R1 fix: validate proposal_id against the schema pattern before
# using it as a path component. Mirrors `governance/schemas/
# miner_proposal.schema.json::$defs/proposal/properties/proposal_id`.
# An attacker-controlled bundle could otherwise embed `../escape` and
# slip artifacts outside output_dir.
_PROPOSAL_ID_PATTERN = re.compile(r"^P7-[A-Z0-9]{1,12}-[0-9]{4}$")


# ---- Helpers (standalone — see test_reach_equality_with_phase_7_lint) ----


def _load_yaml(path: Path) -> Any:
    """Lazy-import yaml + parse the file. Returns the parsed structure
    or raises on malformed content. Same shape as
    `phase_7_lint._load_yaml` — the test suite pins reach equality."""
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML required for phase_7_patcher.py. Install via "
            "`pip install pyyaml` or `pip install -r requirements-dev.txt`."
        ) from exc
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_policy_globs(canon_path: Path) -> list[str]:
    """Read POLICY_GLOBS from `scripts/compute_canon_hash.py` via AST so
    embedded comments + tuple/list literal flexibility don't break us
    (same approach as phase_7_lint._read_policy_globs). Reach equality
    with phase_7_lint is pinned by `test_reach_equality_with_phase_7_lint`.
    """
    tree = ast.parse(canon_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value_node = node.value
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target_name = node.targets[0].id
            value_node = node.value
        else:
            continue
        if target_name != "POLICY_GLOBS":
            continue
        if not isinstance(value_node, (ast.Tuple, ast.List)):
            raise RuntimeError(
                f"POLICY_GLOBS in {canon_path} is "
                f"{type(value_node).__name__}, expected Tuple or List."
            )
        out: list[str] = []
        for elt in value_node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(elt.value)
            else:
                raise RuntimeError(
                    f"POLICY_GLOBS in {canon_path} contains non-string "
                    f"element {ast.dump(elt)} — patcher expects literals."
                )
        return out
    raise RuntimeError(
        f"Could not locate POLICY_GLOBS = (...) | [...] in {canon_path}."
    )


def _matches_any_glob(rel_path: str, patterns: list[str]) -> str | None:
    """Returns the first matching POLICY_GLOBS pattern, or None.
    Uses fnmatchcase (POSIX glob) to match phase_7_lint's
    `_matches_any_glob` exactly."""
    for pat in patterns:
        if fnmatch.fnmatchcase(rel_path, pat):
            return pat
    return None


def _parse_numeric(value_str: str) -> float | None:
    """Best-effort numeric parse. Strips operator prefixes (>=, ≥, <=)
    so values like '>= 0.75' and '0.75' both parse. Mirrors
    phase_7_lint._parse_numeric for reach equality."""
    cleaned = value_str.strip()
    for prefix in (">=", "<=", "≥", "≤", ">", "<", "="):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    try:
        return float(cleaned)
    except ValueError:
        return None


# ---- Tunable lookup -------------------------------------------------


def _build_tunable_index(tunables_doc: dict) -> dict[str, dict]:
    """{id → entry dict} from a parsed tunables.yaml document.

    Defensive: returns {} when the document is missing the `tunables`
    key OR `tunables` is not a list. The patcher reports the bundle-
    wide error elsewhere (no proposals can be processed without a
    tunable index)."""
    if not isinstance(tunables_doc, dict):
        return {}
    entries = tunables_doc.get("tunables")
    if not isinstance(entries, list):
        return {}
    out: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        eid = entry.get("id")
        if isinstance(eid, str) and eid:
            out[eid] = entry
    return out


# ---- Validation -----------------------------------------------------


def _validate_proposal(
    proposal: dict,
    tunable_index: dict[str, dict],
    policy_globs: list[str],
) -> tuple[str, str]:
    """Run a proposal through the validation pipeline.

    Returns ``(status, reason)`` where status is one of:
      * "ready" — proposal passed all gates; ready for patch emission.
      * "skipped" — semantic skip (L1 path / no-op); not an error.
      * "rejected" — failed a safety/correctness gate.
    """
    # Gate 0 (R1 fix): proposal_id pattern. Validated FIRST because
    # subsequent stages embed it in output paths — a malformed id like
    # `../escape` would otherwise let a hostile bundle write outside
    # output_dir. The schema pattern is the canonical filter.
    proposal_id = proposal.get("proposal_id", "")
    if not isinstance(proposal_id, str) or not _PROPOSAL_ID_PATTERN.fullmatch(proposal_id):
        return "rejected", (
            f"proposal_id={proposal_id!r} does not match the schema "
            f"pattern `^P7-[A-Z0-9]{{1,12}}-[0-9]{{4}}$`. Refusing to "
            f"materialize artifacts under an unsafe id (path-traversal "
            f"defense)."
        )

    # Gate 1: immutable_conflict (runtime mirror of phase_7_lint C5)
    if proposal.get("immutable_conflict") is True:
        return "rejected", (
            "immutable_conflict=true on the proposal — refusing to "
            "materialize a patch that would violate IMMUTABLE_CONFLICT "
            "(phase_7_lint C5)."
        )

    # Gate 2: change_class
    change_class = proposal.get("change_class")
    if change_class == "L1_auto_tunable":
        return "skipped", (
            "change_class=L1_auto_tunable — patcher is L2-only "
            "(L1 auto-merge path is operator tooling outside this "
            "script's scope)."
        )
    if change_class != "L2_proposal_only":
        return "rejected", (
            f"unknown change_class={change_class!r} — expected "
            f"L1_auto_tunable or L2_proposal_only per phase_7_lint C7."
        )

    # Gate 3: tunable_id resolution
    tunable_id = proposal.get("tunable_id")
    if not isinstance(tunable_id, str) or tunable_id not in tunable_index:
        return "rejected", (
            f"tunable_id={tunable_id!r} not found in config/tunables.yaml. "
            f"Stale proposal — re-run the miner."
        )
    tunable = tunable_index[tunable_id]

    # Gate 4: current_value drift
    proposal_current = proposal.get("current_value", "")
    live_current = str(tunable.get("current_value", ""))
    if proposal_current != live_current:
        return "rejected", (
            f"current_value drift: proposal observed "
            f"{proposal_current!r}, live tunables.yaml has "
            f"{live_current!r}. The tunable changed since the miner "
            f"ran — re-run the miner to refresh observations."
        )

    # Gate 5: range
    proposed_value = proposal.get("proposed_value", "")
    proposed_num = _parse_numeric(str(proposed_value))
    if proposed_num is None:
        return "rejected", (
            f"proposed_value={proposed_value!r} is not numeric. "
            f"v1.2.19 patcher supports numeric tunables only "
            f"(enum tunables out of scope until phase_7_lint extends "
            f"to non-numeric ranges)."
        )
    allowed_range = tunable.get("allowed_range")
    if (
        not isinstance(allowed_range, list)
        or len(allowed_range) != 2
        or not all(isinstance(v, (int, float)) for v in allowed_range)
    ):
        return "rejected", (
            f"tunable {tunable_id} has malformed allowed_range="
            f"{allowed_range!r}. Fix tunables.yaml + re-run "
            f"phase_7_lint.py."
        )
    lo, hi = allowed_range
    if not lo <= proposed_num <= hi:
        return "rejected", (
            f"proposed_value={proposed_num} out of allowed_range "
            f"[{lo}, {hi}] for tunable {tunable_id}."
        )

    # Gate 6: POLICY_GLOBS safety (defensive runtime mirror of C6)
    source_file = tunable.get("source_file", "")
    if not isinstance(source_file, str) or not source_file:
        return "rejected", (
            f"tunable {tunable_id} has empty/non-string source_file."
        )
    matched_glob = _matches_any_glob(source_file, policy_globs)
    if matched_glob is not None and change_class == "L1_auto_tunable":
        # Unreachable in current control flow (we returned at Gate 2),
        # but kept as defense-in-depth for future change_class additions.
        return "rejected", (
            f"L1_auto_tunable proposal targets POLICY_GLOBS file "
            f"{source_file} (matches glob {matched_glob!r}). Auto-merge "
            f"would silently bump canon hash — refused per "
            f"phase_7_lint C6."
        )

    # Gate 7: no-op
    current_num = _parse_numeric(str(live_current))
    if current_num is not None and current_num == proposed_num:
        return "skipped", (
            f"no-op: proposed_value equals current_value "
            f"({proposed_value}). Nothing to patch."
        )

    return "ready", ""


# ---- Patch emission -------------------------------------------------


def _build_patch(
    workspace: Path,
    proposal: dict,
    tunable: dict,
) -> str:
    """Emit a unified-diff patch that replaces the line at
    `tunable.source_line` so it carries `proposed_value` instead of
    `current_value`. The diff is single-hunk + single-line — keeps
    the change minimal + reversible per Safety Contract item 4
    (`docs/phase_7_design.md` §Safety contract).

    Path in the diff headers is repo-relative (operators run
    `git apply` from repo root)."""
    source_rel = tunable["source_file"]
    source_path = workspace / source_rel
    source_text = source_path.read_text(encoding="utf-8")

    # R1 fix: reject source files without a trailing newline. Unified-
    # diff EOF semantics for missing-newline files require the
    # `\ No newline at end of file` marker placed in specific positions
    # (per old/new line state, possibly in trailing context too); a
    # partial impl emits not-quite-`git apply`-able output. Simpler +
    # safer to require the invariant. All canonical / POLICY_GLOBS
    # files in this repo have trailing newlines today; this only
    # surfaces if an operator has a hand-rolled tunable source_file
    # without one, in which case adding the newline (one keystroke)
    # is the right fix.
    if not source_text.endswith("\n"):
        raise RuntimeError(
            f"source file {source_rel} has no trailing newline. "
            f"phase_7_patcher requires source files to end with a "
            f"newline so unified-diff EOF semantics are unambiguous "
            f"(`\\ No newline at end of file` marker handling is "
            f"intentionally out of scope in v1.2.19). Add a trailing "
            f"newline to {source_rel}; tunables.yaml entry stays "
            f"unchanged."
        )

    lines = source_text.splitlines()
    line_idx = tunable["source_line"] - 1
    if not 0 <= line_idx < len(lines):
        raise RuntimeError(
            f"source_line {tunable['source_line']} out of range for "
            f"{source_rel} (file has {len(lines)} lines)."
        )

    current_line = lines[line_idx]
    current_value_str = str(tunable["current_value"])
    proposed_value_str = str(proposal["proposed_value"])

    if current_value_str not in current_line:
        raise RuntimeError(
            f"current_value {current_value_str!r} not found verbatim at "
            f"{source_rel}:{tunable['source_line']}. phase_7_lint C1 "
            f"would have caught this — fix tunables.yaml + re-run lint."
        )

    new_line = current_line.replace(
        current_value_str, proposed_value_str, 1,
    )

    # Unified diff with 3 lines of context (git's default).
    context_before_start = max(0, line_idx - 3)
    context_after_end = min(len(lines), line_idx + 4)
    context_before = lines[context_before_start:line_idx]
    context_after = lines[line_idx + 1:context_after_end]

    hunk_old_start = context_before_start + 1
    hunk_old_count = len(context_before) + 1 + len(context_after)
    hunk_new_start = hunk_old_start
    hunk_new_count = hunk_old_count

    parts: list[str] = []
    parts.append(f"--- a/{source_rel}\n")
    parts.append(f"+++ b/{source_rel}\n")
    parts.append(
        f"@@ -{hunk_old_start},{hunk_old_count} "
        f"+{hunk_new_start},{hunk_new_count} @@\n"
    )
    for ctx in context_before:
        parts.append(f" {ctx}\n")
    parts.append(f"-{current_line}\n")
    parts.append(f"+{new_line}\n")
    for ctx in context_after:
        parts.append(f" {ctx}\n")
    return "".join(parts)


def _build_summary_md(
    proposal: dict,
    tunable: dict,
    patch_filename: str,
    *,
    apply_path: str,
) -> str:
    """Human-readable rationale + how-to-apply for the analyst.

    `apply_path` is the path the analyst will pass to `git apply` —
    repo-relative when the patch lives inside the workspace, absolute
    when it's been written elsewhere via `--output-dir`. R2 fix:
    pre-fix the summary hardcoded `analysis/telemetry/proposals/<id>`
    regardless of where the patch actually landed, leading operators
    using `--output-dir` to a wrong-path apply command."""
    lines = [
        f"# Proposal {proposal['proposal_id']}",
        "",
        f"- tunable_id: `{proposal['tunable_id']}`",
        f"- source_file: `{tunable['source_file']}`",
        f"- source_line: {tunable['source_line']}",
        f"- current_value: `{proposal['current_value']}`",
        f"- proposed_value: `{proposal['proposed_value']}`",
        f"- confidence: {proposal.get('confidence', 'n/a')}",
        f"- change_class: `{proposal['change_class']}`",
        f"- linked_invariants: "
        f"{', '.join(proposal.get('linked_invariants', [])) or '(none)'}",
        f"- evidence_run_ids: "
        f"{', '.join(proposal.get('evidence_run_ids', [])) or '(none)'}",
        "",
        "## Rationale",
        "",
        proposal.get("rationale", "(no rationale provided)"),
        "",
        "## How to apply (analyst workflow)",
        "",
        "1. Review this proposal + the patch file `" + patch_filename + "`.",
        "2. Decide whether the change is justified by the cited evidence.",
        "3. If approved, from the repo root:",
        "",
        "   ```bash",
        # R3 fix: shell-quote both paths. apply_path may legitimately
        # contain spaces / shell metacharacters when --output-dir
        # points at an unusual location; source_file is operator-
        # controlled in tunables.yaml. Without shlex.quote the rendered
        # command would be a copy-paste hazard (broken / misleading /
        # in the worst case unintentionally executed).
        # R4 fix: insert `--` end-of-options separator before the path
        # so git treats leading-hyphen paths (e.g. an `--output-dir
        # ./-out` argument that produces `-out/<id>.patch`) as paths,
        # not as git options. Idiomatic UNIX defense — pairs with
        # shell-quote to make the rendered command unambiguous for any
        # legal path.
        f"   git apply -- {shlex.quote(apply_path)}",
        "   # Inspect the change",
        f"   git diff -- {shlex.quote(tunable['source_file'])}",
        "   ```",
        "",
        "4. Update `config/tunables.yaml` so its `current_value` matches "
        "the new value (the patcher does NOT auto-update tunables.yaml — "
        "operator does both edits in one commit so phase_7_lint C1 stays "
        "green). Then re-run `phase_7_lint.py`.",
        "5. Bump manifest semver if the source_file is in POLICY_GLOBS "
        "(per `scripts/compute_canon_hash.py`); re-run "
        "`compute_canon_hash.py --diff-against <prev>` to confirm.",
        "6. Commit + tag per `docs/RELEASING.md`.",
        "",
        "**The patcher never runs git or modifies canonical state.** "
        "All steps above are operator-driven.",
    ]
    return "\n".join(lines)


# ---- Bundle processing ----------------------------------------------


def process_bundle(
    workspace: Path,
    *,
    bundle_path: Path | None = None,
    output_dir: Path | None = None,
    tunables_path: Path | None = None,
    canon_path: Path | None = None,
) -> dict:
    """Read the bundle, validate every proposal, materialize patches
    for ready ones, return a structured _index.json payload.

    Defensive: missing bundle / malformed bundle / missing tunables
    raise RuntimeError so the CLI layer can return exit 2 with a
    clear message. Per-proposal failures DO NOT raise — they are
    captured in the returned attempts list with status=rejected."""
    if bundle_path is None:
        bundle_path = workspace / DEFAULT_BUNDLE_REL
    if output_dir is None:
        output_dir = workspace / DEFAULT_OUTPUT_REL
    if tunables_path is None:
        tunables_path = workspace / TUNABLES_REL
    if canon_path is None:
        canon_path = workspace / CANON_HASH_REL

    if not bundle_path.is_file():
        raise RuntimeError(
            f"miner proposal bundle not found at {bundle_path}. Run "
            f"scripts/phase_7_miner.py first."
        )
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"miner bundle {bundle_path} is malformed JSON: {exc}"
        ) from exc
    if not isinstance(bundle, dict) or "proposals" not in bundle:
        raise RuntimeError(
            f"miner bundle {bundle_path} doesn't have the expected shape "
            f"(missing 'proposals' key)."
        )

    if not tunables_path.is_file():
        raise RuntimeError(
            f"config/tunables.yaml not found at {tunables_path}."
        )
    tunables_doc = _load_yaml(tunables_path)
    tunable_index = _build_tunable_index(tunables_doc)
    if not tunable_index:
        raise RuntimeError(
            f"config/tunables.yaml at {tunables_path} has no parseable "
            f"`tunables:` entries."
        )

    if not canon_path.is_file():
        raise RuntimeError(
            f"scripts/compute_canon_hash.py not found at {canon_path}."
        )
    policy_globs = _load_policy_globs(canon_path)

    proposals = bundle.get("proposals", [])
    if not isinstance(proposals, list):
        raise RuntimeError(
            f"bundle proposals field is {type(proposals).__name__}, "
            f"expected list."
        )

    attempts: list[dict] = []
    written_count = 0
    for proposal in proposals:
        if not isinstance(proposal, dict):
            attempts.append({
                "proposal_id": None,
                "status": "rejected",
                "reason": (
                    f"proposal entry is {type(proposal).__name__}, "
                    f"expected dict."
                ),
                "patch_path": None,
            })
            continue

        proposal_id = proposal.get("proposal_id", "<unknown>")
        status, reason = _validate_proposal(
            proposal, tunable_index, policy_globs,
        )
        if status != "ready":
            attempts.append({
                "proposal_id": proposal_id,
                "status": status,
                "reason": reason,
                "patch_path": None,
            })
            continue

        # Materialize patch + summary.
        tunable = tunable_index[proposal["tunable_id"]]
        try:
            patch_text = _build_patch(workspace, proposal, tunable)
        except RuntimeError as exc:
            attempts.append({
                "proposal_id": proposal_id,
                "status": "rejected",
                "reason": str(exc),
                "patch_path": None,
            })
            continue

        patch_filename = f"{proposal_id}.patch"
        summary_filename = f"{proposal_id}.summary.md"
        patch_path = output_dir / patch_filename
        summary_path = output_dir / summary_filename

        # R1 fix: defense-in-depth path containment check. Even though
        # Gate 0 already validated proposal_id against the schema
        # pattern (which excludes `..` and `/`), reject if the resolved
        # patch path somehow ends up outside output_dir. Catches future
        # regressions if Gate 0 weakens or if `output_dir` itself is
        # symlinked into something unexpected.
        try:
            resolved_patch = patch_path.resolve()
            resolved_output = output_dir.resolve()
            resolved_patch.relative_to(resolved_output)
        except ValueError:
            attempts.append({
                "proposal_id": proposal_id,
                "status": "rejected",
                "reason": (
                    f"resolved patch path {resolved_patch} escapes "
                    f"output_dir {resolved_output} — refusing to "
                    f"write (path-traversal defense)."
                ),
                "patch_path": None,
            })
            continue

        # R1 fix: relative_to() raises ValueError if patch_path is
        # outside the workspace (legit for --output-dir overrides
        # pointing at /tmp etc.). Fall back to absolute string.
        # Used for BOTH _index.json provenance AND the summary's
        # `git apply` instruction (R2 fix — pre-fix the summary
        # hardcoded the default proposals/ path regardless of where
        # the patch actually landed, leading operators using
        # --output-dir to a wrong-path apply command).
        if _is_relative_to(patch_path, workspace):
            patch_path_str = str(patch_path.relative_to(workspace))
        else:
            patch_path_str = str(patch_path)
        summary_text = _build_summary_md(
            proposal, tunable, patch_filename,
            apply_path=patch_path_str,
        )
        _atomic_write(patch_path, patch_text)
        _atomic_write(summary_path, summary_text)
        written_count += 1
        attempts.append({
            "proposal_id": proposal_id,
            "status": "written",
            "reason": "",
            "patch_path": patch_path_str,
        })

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rejected = sum(1 for a in attempts if a["status"] == "rejected")
    skipped = sum(1 for a in attempts if a["status"] == "skipped")
    return {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "bundle_path": str(bundle_path.relative_to(workspace))
        if _is_relative_to(bundle_path, workspace) else str(bundle_path),
        "summary": {
            "proposals_total": len(proposals),
            "patches_written": written_count,
            "rejected": rejected,
            "skipped": skipped,
        },
        "attempts": attempts,
    }


def _is_relative_to(path: Path, base: Path) -> bool:
    """Backport of Path.is_relative_to (Py3.9 compat)."""
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


# ---- Atomic write ---------------------------------------------------


def _atomic_write(target_path: Path, body: str) -> None:
    """Atomic text write (tempfile + os.replace; mirrors v1.2.16/v1.2.18
    pattern)."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=".phase_7_patcher_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, target_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_json(target_path: Path, doc: dict) -> None:
    _atomic_write(target_path, json.dumps(doc, indent=2))


# ---- CLI ------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 7 L2 auto-patcher (v1.2.19). Reads a miner proposal "
            "bundle, validates each proposal against live tunables.yaml "
            "+ POLICY_GLOBS, and emits per-proposal unified-diff patch "
            "files for analyst review. NEVER runs git/commit/push or "
            "modifies canonical state — operator applies patches "
            "manually per docs/phase_7_runbook.md."
        ),
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="BSA workspace root (defaults to cwd).",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help=(
            f"Override the miner-bundle input path (default "
            f"<workspace>/{DEFAULT_BUNDLE_REL})."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            f"Override the patch output directory (default "
            f"<workspace>/{DEFAULT_OUTPUT_REL}). The patcher writes "
            f"only inside this directory — patches NEVER target other "
            f"locations directly (git apply is operator-driven)."
        ),
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print _index.json to stdout instead of writing patches.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-summary log line.",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    workspace = args.workspace.resolve()
    if not (workspace / "analysis").is_dir():
        print(
            f"phase_7_patcher: workspace {workspace} is not initialized "
            f"(no analysis/ directory). Run /bsa-start first.",
            file=sys.stderr,
        )
        return 2

    bundle_path = (
        args.input.resolve() if args.input is not None
        else workspace / DEFAULT_BUNDLE_REL
    )
    output_dir = (
        args.output_dir.resolve() if args.output_dir is not None
        else workspace / DEFAULT_OUTPUT_REL
    )

    try:
        index = process_bundle(
            workspace,
            bundle_path=bundle_path,
            output_dir=output_dir,
        )
    except RuntimeError as exc:
        print(f"phase_7_patcher: {exc}", file=sys.stderr)
        return 2

    if args.print_only:
        print(json.dumps(index, indent=2))
        return 0

    index_path = output_dir / INDEX_FILENAME
    _atomic_write_json(index_path, index)

    if not args.quiet:
        s = index["summary"]
        print(
            f"phase_7_patcher: wrote {index_path}\n"
            f"  proposals: {s['proposals_total']} total / "
            f"{s['patches_written']} patches written / "
            f"{s['rejected']} rejected / {s['skipped']} skipped\n"
            f"  NOTE: patches are advisory — apply via "
            f"`git apply` per docs/phase_7_runbook.md."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
