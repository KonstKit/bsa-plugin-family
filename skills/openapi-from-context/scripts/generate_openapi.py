#!/usr/bin/env python3
"""OpenAPI 3.1 exporter from BSA Stage 6 contract layer (v1.3.0).

Reads `analysis/canonical/stage6/A61_anchor_map.csv`, materializes every
`AnchorClass=contract` row whose `ElementID` is path-shaped into a
placeholder OpenAPI 3.1 path with one `get` operation, and emits the
result as YAML at `analysis/handoff/contracts/openapi/api.yaml` plus an
anchor manifest at `analysis/handoff/contracts/openapi/anchor_manifest.json`.

**v1.3.0 ships the SKELETON ONLY** — the script does not parse free-form
prose in `interface_contract_model.md` and does not synthesize request /
response schemas. Operators enrich the YAML in place after the export.
The skeleton's value:

  1. Establishes the bundle shape (YAML + manifest schema) so v1.3.0.x
     follow-ups can iterate against a stable contract.
  2. Provides the anchor → path traceability scaffold every downstream
     OpenAPI consumer needs.
  3. Lets v1.3.1 (AsyncAPI) and v1.3.2 (proto) reuse the same
     `analysis/handoff/contracts/<format>/` layout + base manifest shape.

Schemas:
  * Anchor manifest: `skills/openapi-from-context/references/anchor_manifest.schema.json` (v1.0).
  * OpenAPI YAML: written as OpenAPI 3.1 minimal-valid shape (operator
    runs `openapi-spec-validator` themselves for full conformance).

Pattern lineage (mirrors the operator-runner family):
- v1.2.4 `phase_7_telemetry_collector.py`
- v1.2.16 `freshness_audit.py`
- v1.2.17 `triangulation_audit.py`
- v1.2.18 `phase_7_miner.py`
- v1.2.19 `phase_7_patcher.py`

Stdlib + pyyaml. Defensive CSV reads. Atomic writes via tempfile +
os.replace. Operator-invoked. NEVER runs git/commit/push, NEVER edits
canonical state, NEVER modifies source files referenced by the inputs.

CLI:
  python3 skills/openapi-from-context/scripts/generate_openapi.py --workspace <path>
  python3 skills/openapi-from-context/scripts/generate_openapi.py --workspace <path> --input <a61_csv>
  python3 skills/openapi-from-context/scripts/generate_openapi.py --workspace <path> --output-dir <dir>
  python3 skills/openapi-from-context/scripts/generate_openapi.py --workspace <path> --title "My API" --version "2.1.0"
  python3 skills/openapi-from-context/scripts/generate_openapi.py --workspace <path> --print-only

Exit codes:
  0 — bundle generated (zero or more paths materialized).
  2 — invocation error (workspace not initialized, missing A61, malformed
      CSV, explicit --output-dir not a directory, etc.).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Module-relative root: this script lives at
# skills/openapi-from-context/scripts/generate_openapi.py, so the repo
# root is three levels up.
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parent.parent

DEFAULT_INPUT_REL = "analysis/canonical/stage6/A61_anchor_map.csv"
DEFAULT_OUTPUT_REL = "analysis/handoff/contracts/openapi"
DEFAULT_API_FILENAME = "api.yaml"
DEFAULT_MANIFEST_FILENAME = "anchor_manifest.json"

OPENAPI_VERSION = "3.1.0"
MANIFEST_VERSION = "1.0"
SIDECAR_LITERAL = "openapi-from-context"
SIDECAR_VERSION = "1.0.0"  # First release; bumps with breaking shape changes.
FORMAT_LITERAL = "openapi-3.1"

# A61 columns we consume (per skills/bsa-contract-builder/references/
# contract-layer-selection.md "A61 Candidate Columns"):
A61_REQUIRED_COLS = {
    "AnchorID",
    "AnchorClass",
    "ElementType",
    "ElementID",
    "ClaimID",
    "A51Ref",
}

# Path-shape regex. ASCII-exact character class: alphanumerics, slash,
# underscore, hyphen, dot, tilde, plus OpenAPI template braces. NO `%`
# — percent-encoding is intentionally rejected here because:
#   1. legitimate OpenAPI path templates rarely need %-encoding (operator
#      can put encoded values in parameters, not path literals);
#   2. % opens a recursive-decoding attack surface (R2 fix: even with
#      two-pass unquote, triple-encoded `%25252e%25252e` survived; an
#      iterative decode-until-stable + `%HH` validation pass would work
#      but adds complexity for marginal benefit);
#   3. malformed escapes (`/users/%`, `/users/%GG`) would slip through
#      a permissive `%`-allowing regex and yield invalid URI templates.
# Reach-equality lesson from v1.2.16 R5 + v1.2.19 R5: the gate's reach
# must match the validator's reach exactly. Reject `%` at the regex
# layer keeps the gate atomic; the structured reason is
# `element_id_not_path_shaped` (operator removes the `%` and re-runs).
_PATH_SHAPE = re.compile(r"^/[A-Za-z0-9_/{}.~-]*$")
# Explicit traversal blocker: catches the `..` literal that the shape
# regex accepts as legal characters (`.` is in the class). Reported with
# the structured `element_id_path_traversal` reason for operator triage.
_TRAVERSAL_HINT = re.compile(r"\.\.")
_ANCHOR_ID_PATTERN = re.compile(r"^ANC-[A-Z0-9_-]+$")


# ---- CSV helpers ---------------------------------------------------


def _read_a61_rows(path: Path) -> tuple[list[dict], str | None]:
    """Defensive CSV read. Returns (rows, error_message). On success,
    error_message is None and rows is a list of dicts. On failure,
    rows is empty and error_message is a single-line operator hint."""
    if not path.is_file():
        return [], (
            f"A61 anchor map not found at {path}. Did Stage 6 finish "
            f"promotion? Re-run /bsa-stage 6 first, or pass --input "
            f"explicitly to point at a fixture-based A61 CSV."
        )
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            actual_cols = set(reader.fieldnames or [])
            missing = A61_REQUIRED_COLS - actual_cols
            if missing:
                return [], (
                    f"A61 anchor map at {path} is missing required "
                    f"columns: {sorted(missing)}. Expected at least "
                    f"{sorted(A61_REQUIRED_COLS)}."
                )
            rows = list(reader)
    except (OSError, csv.Error) as exc:
        return [], f"failed to read A61 CSV at {path}: {exc}"
    return rows, None


# ---- Anchor classification -----------------------------------------


def _sanitize_anchor_id_for_operationid(anchor_id: str) -> str:
    """OpenAPI operationId must match `^[a-zA-Z0-9_-]+$`. A61 AnchorIDs
    are already constrained to that alphabet by `_ANCHOR_ID_PATTERN`,
    but lower-case + hyphen→underscore for OpenAPI convention."""
    return anchor_id.lower().replace("-", "_")


def _classify_anchor(row: dict) -> tuple[str, str]:
    """Run an A61 row through the inclusion gates.

    Returns ``(status, reason)``:
      * ("ready", "")             — eligible for OpenAPI materialization.
      * ("skipped_non_contract", "") — AnchorClass != contract.
      * ("skipped_shape", "")     — ElementID not path-shaped: fails
        the `_PATH_SHAPE` regex (rejects `%`, shell metacharacters,
        Unicode digits, etc. — so percent-encoded `..` like `%2e%2e`,
        `%252e%252e`, `%25252e%25252e` ALL surface here, not under
        `skipped_traversal`) OR has malformed OpenAPI template syntax
        (unbalanced / empty / nested / misordered `{...}`).
      * ("skipped_traversal", "") — ElementID contains a LITERAL `..`
        in its raw form. Encoded variants are caught one gate earlier
        (`skipped_shape`) because R2 removed `%` from the path-shape
        character class to close the recursive-decode attack surface.
      * ("skipped_bad_anchor_id", "") — AnchorID malformed.
    """
    anchor_id = (row.get("AnchorID") or "").strip()
    anchor_class = (row.get("AnchorClass") or "").strip()
    element_id = (row.get("ElementID") or "").strip()

    if not _ANCHOR_ID_PATTERN.fullmatch(anchor_id):
        return "skipped_bad_anchor_id", ""
    if anchor_class != "contract":
        return "skipped_non_contract", ""
    # Traversal check FIRST so a literal `..` in ElementID gets the
    # structured `element_id_path_traversal` reason (more actionable
    # than the generic `element_id_not_path_shaped`). Percent-encoded
    # traversal (`%2e%2e`, `%2E%2E`, double/triple encoded) does NOT
    # need a separate decode pass: the path-shape regex (next gate)
    # rejects `%` outright (R2 fix — see _PATH_SHAPE comment for why).
    # That keeps the gate's reach equal to the schema's reach without a
    # recursive decode loop.
    if _TRAVERSAL_HINT.search(element_id):
        return "skipped_traversal", ""
    if not _PATH_SHAPE.fullmatch(element_id):
        return "skipped_shape", ""
    # R1 fix: validate `{param}` template syntax. The shape regex
    # accepts `{` and `}` as characters but doesn't enforce balanced /
    # non-empty / well-ordered templates — `/users/{id` (unbalanced),
    # `/users/{}` (empty), `/users/}{` (misordered) all fail OpenAPI
    # 3.1's path-template grammar even though the shape regex passes.
    # Reject all three with `skipped_shape`.
    depth = 0
    in_template = False
    saw_param_char_in_template = False
    for ch in element_id:
        if ch == "{":
            if in_template:
                # Nested `{` inside `{...}` is invalid template syntax.
                return "skipped_shape", ""
            in_template = True
            saw_param_char_in_template = False
            depth += 1
        elif ch == "}":
            if not in_template:
                # `}` before any `{` is misordered.
                return "skipped_shape", ""
            if not saw_param_char_in_template:
                # `{}` empty template.
                return "skipped_shape", ""
            in_template = False
            depth -= 1
        elif in_template:
            saw_param_char_in_template = True
    if depth != 0:
        # Unbalanced — open brace without matching close.
        return "skipped_shape", ""
    return "ready", ""


# ---- OpenAPI / manifest builders -----------------------------------


def _read_plugin_canon_version() -> str:
    """Read the active canon_policy_version from .claude-plugin/plugin.json
    so the manifest correlates exporter output to a specific policy
    state. Returns "0.0.0" if the manifest is unreadable (defensive —
    the manifest is required for normal runs but the exporter shouldn't
    crash if invoked in a partially-set-up workspace)."""
    plugin_path = REPO_ROOT / ".claude-plugin" / "plugin.json"
    if not plugin_path.is_file():
        return "0.0.0"
    try:
        doc = json.loads(plugin_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "0.0.0"
    canon = doc.get("canonPolicyVersion", {})
    if not isinstance(canon, dict):
        return "0.0.0"
    semver = str(canon.get("semver", "0.0.0"))
    prefix = canon.get("hash_prefix")
    if isinstance(prefix, str) and prefix:
        return f"{semver}+hash:{prefix}"
    return semver


def build_bundle(
    rows: list[dict],
    *,
    title: str,
    version: str,
    api_path_str: str,
) -> tuple[dict, dict]:
    """Build the OpenAPI YAML doc + the anchor manifest. `api_path_str`
    is the value to record in `view_files[].path` (caller decides
    repo-relative vs absolute — mirrors v1.2.19 patcher's
    apply_path semantic so downstream consumers see a path that
    matches where the file actually landed).

    Returns (openapi_doc, manifest_doc)."""
    paths: dict[str, dict] = {}
    anchor_map: list[dict] = []
    unmapped: list[dict] = []
    seen_paths: set[str] = set()

    for row in rows:
        status, _reason = _classify_anchor(row)
        anchor_id = (row.get("AnchorID") or "").strip()
        element_id = (row.get("ElementID") or "").strip()

        if status == "skipped_bad_anchor_id":
            # Don't surface in unmapped_anchors — the AnchorID itself
            # is unusable as a manifest reference (would fail schema
            # `ANC-...` pattern). Surface in stderr log instead via
            # the caller's warnings stream (out of scope for v1.3.0
            # skeleton; future hardening).
            continue
        if status == "skipped_non_contract":
            unmapped.append({
                "a61_anchor_id": anchor_id,
                "reason": "non_contract_anchor_class",
                "element_id": element_id,
            })
            continue
        if status == "skipped_traversal":
            unmapped.append({
                "a61_anchor_id": anchor_id,
                "reason": "element_id_path_traversal",
                "element_id": element_id,
            })
            continue
        if status == "skipped_shape":
            unmapped.append({
                "a61_anchor_id": anchor_id,
                "reason": "element_id_not_path_shaped",
                "element_id": element_id,
            })
            continue

        # status == "ready"
        if element_id in seen_paths:
            unmapped.append({
                "a61_anchor_id": anchor_id,
                "reason": "duplicate_path_collision",
                "element_id": element_id,
            })
            continue
        seen_paths.add(element_id)

        claim_id = (row.get("ClaimID") or "").strip()
        a51_ref = (row.get("A51Ref") or "").strip()
        # Tag is operator-readable provenance: prefer ClaimID, fall back
        # to A51Ref if the anchor is A51-routed. Never empty by INV-01
        # (every anchor has at least one of the two).
        tag_provenance = claim_id or a51_ref or anchor_id

        operation_id = f"anc_{_sanitize_anchor_id_for_operationid(anchor_id)}_get"
        path_item: dict = {
            "get": {
                "operationId": operation_id,
                "summary": (
                    f"Placeholder operation for A61 anchor {anchor_id}"
                ),
                "tags": [f"bsa-anchor:{tag_provenance}"],
                "responses": {
                    "200": {
                        "description": (
                            "Placeholder response — operator must "
                            "enrich with real schema before shipping."
                        ),
                    },
                },
            },
        }
        paths[element_id] = path_item

        anchor_map.append({
            "view_element_id": element_id,
            "view_element_kind": "PathItem",
            "a61_anchor_id": anchor_id,
            "notes": (
                f"placeholder; trace: {tag_provenance}"
                if tag_provenance else "placeholder"
            ),
        })
        anchor_map.append({
            "view_element_id": f"GET {element_id}",
            "view_element_kind": "Operation",
            "a61_anchor_id": anchor_id,
            "notes": (
                f"placeholder GET op; trace: {tag_provenance}"
                if tag_provenance else "placeholder"
            ),
        })

    openapi_doc = {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": title,
            "version": version,
        },
        "paths": paths,
    }

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest_doc = {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": generated_at,
        "sidecar": SIDECAR_LITERAL,
        "sidecar_version": SIDECAR_VERSION,
        "canon_policy_version": _read_plugin_canon_version(),
        "view_files": [
            {
                "path": api_path_str,
                "format": FORMAT_LITERAL,
                "anchor_map": anchor_map,
                "unmapped_anchors": unmapped,
            },
        ],
    }
    return openapi_doc, manifest_doc


# ---- YAML rendering (stdlib via PyYAML) -----------------------------


def _render_yaml(doc: dict) -> str:
    """Render the OpenAPI dict as deterministic YAML. PyYAML's
    `safe_dump(sort_keys=False)` preserves insertion order (Python
    3.7+ dicts are ordered) so callers can rely on a stable byte-level
    output for diffing + idempotency tests.

    PyYAML is a test-only dependency in this repo (`requirements-dev.txt`)
    but at runtime the exporter genuinely needs it. We import lazily
    with a clear error message so an operator without pyyaml gets a
    graceful exit, not an ImportError stack trace."""
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML required for skills/openapi-from-context. Install via "
            "`pip install pyyaml` or `pip install -r requirements-dev.txt`."
        ) from exc
    return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)


# ---- Atomic writes -------------------------------------------------


def _atomic_write(target_path: Path, body: str) -> None:
    """Atomic text write: tempfile in same dir + os.replace. Mirrors
    v1.2.16/v1.2.18/v1.2.19 hygiene."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=".openapi_exporter_",
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


# ---- _is_relative_to backport ---------------------------------------


def _is_relative_to(path: Path, base: Path) -> bool:
    """Backport of Path.is_relative_to (Py3.9 compat). Used to decide
    whether to record repo-relative vs absolute paths in the manifest
    — same semantic as v1.2.19 patcher's R1-FIX-2."""
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


# ---- CLI -----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "OpenAPI 3.1 exporter from BSA Stage 6 contract layer "
            "(v1.3.0). Reads A61 anchor map, emits skeleton api.yaml + "
            "anchor manifest. Skeleton-only: operator enriches paths "
            "with real request/response schemas after export. NEVER "
            "runs git/commit/push or modifies canonical state."
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
            f"Override the A61 anchor-map CSV path (default <workspace>/"
            f"{DEFAULT_INPUT_REL}). Useful for fixture-based runs without "
            f"an initialized BSA workspace."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            f"Override the output directory (default <workspace>/"
            f"{DEFAULT_OUTPUT_REL}). Mirrors v1.2.19 patcher: implicit-"
            f"missing path is permissive (created on demand); explicit-"
            f"missing path is rejected (operator typo defense)."
        ),
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help=(
            "OpenAPI info.title value (default: workspace directory name)."
        ),
    )
    parser.add_argument(
        "--version",
        type=str,
        default="1.0.0",
        help="OpenAPI info.version value (default: `1.0.0`).",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help=(
            "Print the manifest JSON to stdout instead of writing files. "
            "Useful for previewing the bundle without touching the "
            "output directory."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-summary log line.",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    workspace = args.workspace.resolve()
    # R1 fix: workspace `analysis/` check applies only when --input
    # is NOT explicitly overridden — fixture-based runs (operator
    # passes --input pointing at a CSV outside any BSA workspace)
    # don't need an initialized BSA workspace. Mirrors v1.2.18 miner's
    # `--telemetry-dir` semantic.
    if args.input is None:
        if not (workspace / "analysis").is_dir():
            print(
                f"openapi-from-context: workspace {workspace} is not "
                f"initialized (no analysis/ directory). Run /bsa-start "
                f"first OR pass --input explicitly.",
                file=sys.stderr,
            )
            return 2
        input_path = workspace / DEFAULT_INPUT_REL
    else:
        input_path = args.input.resolve()

    if args.output_dir is None:
        output_dir = workspace / DEFAULT_OUTPUT_REL
    else:
        output_dir = args.output_dir.resolve()
        # R1-FIX-1 mirror from v1.2.19: explicit override + non-existent
        # path = operator typo, fail fast. Implicit (default) path may
        # not exist yet — created on demand by _atomic_write.
        if not output_dir.is_dir():
            print(
                f"openapi-from-context: --output-dir {output_dir} does "
                f"not exist or is not a directory. (An implicit "
                f"workspace-derived output dir that doesn't exist yet "
                f"is permissive; an explicit path that doesn't exist "
                f"is a typo and rejected.)",
                file=sys.stderr,
            )
            return 2

    rows, err = _read_a61_rows(input_path)
    if err is not None:
        print(f"openapi-from-context: {err}", file=sys.stderr)
        return 2

    title = args.title if args.title is not None else workspace.name
    api_path = output_dir / DEFAULT_API_FILENAME
    manifest_path = output_dir / DEFAULT_MANIFEST_FILENAME

    # Decide the path string recorded in the manifest. Mirrors v1.2.19
    # R1-FIX-2: repo-relative when inside the workspace, absolute when
    # outside (downstream consumers need a path that matches where the
    # file landed, not a relative path that breaks if the consumer
    # cd's elsewhere).
    if _is_relative_to(api_path, workspace):
        api_path_str = str(api_path.relative_to(workspace))
    else:
        api_path_str = str(api_path)

    openapi_doc, manifest_doc = build_bundle(
        rows,
        title=title,
        version=args.version,
        api_path_str=api_path_str,
    )

    try:
        yaml_text = _render_yaml(openapi_doc)
    except RuntimeError as exc:
        print(f"openapi-from-context: {exc}", file=sys.stderr)
        return 2

    if args.print_only:
        # Print manifest JSON (canonical structured representation);
        # the YAML text goes to a separate fence for clarity.
        print(json.dumps(manifest_doc, indent=2))
        return 0

    _atomic_write(api_path, yaml_text)
    _atomic_write_json(manifest_path, manifest_doc)

    if not args.quiet:
        view_file = manifest_doc["view_files"][0]
        anchors_in = len(view_file["anchor_map"])
        unmapped = len(view_file["unmapped_anchors"])
        # Two anchor_map entries per materialized anchor (PathItem +
        # Operation), so paths_count == anchors_in / 2 by construction.
        paths_count = anchors_in // 2
        print(
            f"openapi-from-context: wrote {api_path} + {manifest_path}\n"
            f"  paths materialized: {paths_count}\n"
            f"  anchor_map entries: {anchors_in}\n"
            f"  unmapped_anchors: {unmapped}\n"
            f"  NOTE: v1.3.0 ships a SKELETON — placeholder responses "
            f"only. Operator must enrich api.yaml with real "
            f"request/response schemas before shipping."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
