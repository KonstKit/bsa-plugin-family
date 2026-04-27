#!/usr/bin/env python3
"""AsyncAPI 3.0 exporter from BSA Stage 6 contract layer (v1.3.1).

Reads `analysis/canonical/stage6/A61_anchor_map.csv`, materializes every
`AnchorClass=contract` row whose `ElementID` is path-shaped into a
placeholder AsyncAPI 3.0 channel + `send` operation, and emits the
result as YAML at `<output_dir>/asyncapi.yaml` (default
`analysis/handoff/contracts/asyncapi/`) plus an anchor manifest at
`<output_dir>/anchor_manifest.json`.

**v1.3.1 ships the SKELETON ONLY.** The script does not parse free-
form prose in `interface_contract_model.md` and does not synthesize
message payload schemas. Operators enrich the YAML in place after the
export. Skeleton boundary mirrors v1.3.0 OpenAPI exporter — bundle
shape pinned now so v1.3.1.x / v1.3.2 (proto) can iterate against a
stable contract.

Schemas:
  * Anchor manifest: `skills/asyncapi-from-context/references/anchor_manifest.schema.json` (v1.0).
  * AsyncAPI YAML: written as AsyncAPI 3.0 minimal-valid shape
    (operator runs `@asyncapi/parser` themselves for full conformance).

Pattern lineage: v1.2.4 telemetry collector → v1.2.16 freshness → v1.2.17
triangulation → v1.2.18 miner → v1.2.19 patcher → v1.3.0 OpenAPI
exporter → v1.3.1 (this script). Stdlib + pyyaml. Defensive CSV reads.
Atomic writes via tempfile + os.replace. Operator-invoked. NEVER runs
git/commit/push, NEVER edits canonical state, NEVER modifies source
files referenced by the inputs.

Lessons baked in pre-Codex from v1.3.0 retro (R1-R5):
- `--input` bypasses workspace `analysis/` guard (R1-FIX-1).
- Path-shape regex `^/[A-Za-z0-9_/{}.~-]*$` — atomic regex-level
  rejection of `%` closes recursive-decode attack surface (R2 fix).
- Brace-balance scan after shape regex catches malformed `{...}`
  templates (R1-FIX-2 part b).
- Reach equality: literal `..` → `_TRAVERSAL_HINT` →
  `element_id_path_traversal`; encoded variants → `_PATH_SHAPE` →
  `element_id_not_channel_shaped` (R5 docstring lesson).
- AnchorID validated against `^ANC-[A-Z0-9_-]+$` BEFORE filename
  construction (untrusted-input-as-path-component, v1.2.19 R1-FIX-1).
- `_is_relative_to` fallback before any write (v1.2.19 R1-FIX-2).

CLI:
  python3 skills/asyncapi-from-context/scripts/generate_asyncapi.py --workspace <path>
  python3 skills/asyncapi-from-context/scripts/generate_asyncapi.py --workspace <path> --input <a61_csv>
  python3 skills/asyncapi-from-context/scripts/generate_asyncapi.py --workspace <path> --output-dir <dir>
  python3 skills/asyncapi-from-context/scripts/generate_asyncapi.py --workspace <path> --title "My Events" --version "2.0.0"
  python3 skills/asyncapi-from-context/scripts/generate_asyncapi.py --workspace <path> --print-only

Exit codes:
  0 — bundle generated (zero or more channels materialized).
  2 — invocation error.
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

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parent.parent

DEFAULT_INPUT_REL = "analysis/canonical/stage6/A61_anchor_map.csv"
DEFAULT_OUTPUT_REL = "analysis/handoff/contracts/asyncapi"
DEFAULT_API_FILENAME = "asyncapi.yaml"
DEFAULT_MANIFEST_FILENAME = "anchor_manifest.json"

ASYNCAPI_VERSION = "3.0.0"
MANIFEST_VERSION = "1.0"
SIDECAR_LITERAL = "asyncapi-from-context"
SIDECAR_VERSION = "1.0.0"
FORMAT_LITERAL = "asyncapi-3.0"

# A61 columns we consume.
A61_REQUIRED_COLS = {
    "AnchorID",
    "AnchorClass",
    "ElementType",
    "ElementID",
    "ClaimID",
    "A51Ref",
}

# Channel-shape regex. ASCII-exact, NO `%` (mirrors v1.3.0 OpenAPI
# exporter post-R2 design — atomic regex-level rejection of percent-
# encoding closes the recursive-decode attack surface; encoded
# traversal at any depth surfaces as `element_id_not_channel_shaped`,
# matches the gate that fired). v1.3.1 supports only path-style
# channel addresses (`/user/signedup`); dot-style addresses
# (`user.signed_up`) are intentionally deferred (see SKILL.md "Out of
# scope").
_CHANNEL_SHAPE = re.compile(r"^/[A-Za-z0-9_/{}.~-]*$")
# Literal `..` traversal blocker (encoded variants caught by the shape
# regex's `%` reject). Reported as `element_id_path_traversal`.
_TRAVERSAL_HINT = re.compile(r"\.\.")
_ANCHOR_ID_PATTERN = re.compile(r"^ANC-[A-Z0-9_-]+$")
# R1 fix: AsyncAPI 3.0 spec requires `channels[*].parameters` to declare
# every Channel Address Expression `{name}` used in the channel address.
# Pattern extracts those names from a path-shaped address that has
# already passed `_CHANNEL_SHAPE` + brace-balance scan (so we know
# the templates are well-formed).
#
# R2 fix (charset alignment): AsyncAPI 3.0 Parameter Object keys must
# match `^[A-Za-z0-9_-]+$` per the spec. Hyphens are LEGAL parameter
# names (`{order-id}`); dots / other punctuation are NOT. Pre-R2 the
# extractor used `[A-Za-z0-9_]+` (no hyphen) which silently missed
# hyphenated names; the brace-balance scan also accepted any chars
# (including dots) inside `{...}` which let illegal names slip through
# the shape gate. Reach-equality lesson: brace-balance scan and
# extractor must share the SAME charset, and both must equal the
# AsyncAPI Parameter Object name charset.
_PARAM_NAME_CHARSET = re.compile(r"^[A-Za-z0-9_-]+$")
_CHANNEL_PARAM_NAME = re.compile(r"\{([A-Za-z0-9_-]+)\}")


# ---- CSV helpers ---------------------------------------------------


def _read_a61_rows(path: Path) -> tuple[list[dict], str | None]:
    """Defensive CSV read. Returns (rows, error_message). On success
    error is None; on failure rows is empty."""
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


def _sanitize_anchor_id_for_key(anchor_id: str) -> str:
    """AsyncAPI 3.0 channel/operation keys must match `[A-Za-z0-9._-]+`.
    A61 AnchorIDs are constrained to `^ANC-[A-Z0-9_-]+$` so already
    safe; lower-case for AsyncAPI snake-style convention + replace
    hyphens with underscores."""
    return anchor_id.lower().replace("-", "_")


def _classify_anchor(row: dict) -> tuple[str, str]:
    """Run an A61 row through the inclusion gates.

    Returns ``(status, reason)``:
      * ("ready", "")             — eligible for AsyncAPI materialization.
      * ("skipped_non_contract", "") — AnchorClass != contract.
      * ("skipped_shape", "")     — ElementID not channel-shaped: fails
        the `_CHANNEL_SHAPE` regex (rejects `%`, shell metacharacters,
        Unicode digits, dot-style addresses missing leading `/`, etc.
        — so percent-encoded `..` like `%2e%2e`, `%252e%252e`,
        `%25252e%25252e` ALL surface here, not under
        `skipped_traversal`) OR has malformed OpenAPI-style template
        syntax (unbalanced / empty / nested / misordered `{...}`).
      * ("skipped_traversal", "") — ElementID contains a LITERAL `..`
        in its raw form. Encoded variants are caught one gate earlier
        (`skipped_shape`) because the channel-shape regex rejects `%`
        outright (closes recursive-decode attack surface, mirrors
        v1.3.0 OpenAPI exporter post-R2 design).
      * ("skipped_bad_anchor_id", "") — AnchorID malformed.
    """
    anchor_id = (row.get("AnchorID") or "").strip()
    anchor_class = (row.get("AnchorClass") or "").strip()
    element_id = (row.get("ElementID") or "").strip()

    if not _ANCHOR_ID_PATTERN.fullmatch(anchor_id):
        return "skipped_bad_anchor_id", ""
    if anchor_class != "contract":
        return "skipped_non_contract", ""
    if _TRAVERSAL_HINT.search(element_id):
        return "skipped_traversal", ""
    if not _CHANNEL_SHAPE.fullmatch(element_id):
        return "skipped_shape", ""
    # Brace-balance + parameter-name-charset scan. Mirrors v1.3.0
    # OpenAPI exporter R1-FIX-2 part b PLUS the v1.3.1 R2 alignment:
    # contents inside `{...}` MUST match the AsyncAPI 3.0 Parameter
    # Object name charset `^[A-Za-z0-9_-]+$`. Pre-R2 the scan accepted
    # any chars inside templates (e.g., `{tenant.id}`) which let
    # illegal parameter names slip through the shape gate even though
    # the AsyncAPI spec rejects them.
    in_template = False
    template_buf = ""
    depth = 0
    for ch in element_id:
        if ch == "{":
            if in_template:
                return "skipped_shape", ""  # nested
            in_template = True
            template_buf = ""
            depth += 1
        elif ch == "}":
            if not in_template:
                return "skipped_shape", ""  # `}` before `{`
            if not template_buf:
                return "skipped_shape", ""  # `{}` empty
            if not _PARAM_NAME_CHARSET.fullmatch(template_buf):
                # Template contents not a legal AsyncAPI parameter name
                # (e.g., `{tenant.id}`, `{user id}`, `{order/sub}`).
                return "skipped_shape", ""
            in_template = False
            depth -= 1
        elif in_template:
            template_buf += ch
    if depth != 0:
        return "skipped_shape", ""  # unbalanced
    return "ready", ""


# ---- AsyncAPI / manifest builders ----------------------------------


def _read_plugin_canon_version() -> str:
    """Read active canon_policy_version from .claude-plugin/canon_policy.json
    (extracted from plugin.json in v1.3.6 hotfix). Falls back to the
    legacy plugin.json::canonPolicyVersion block if canon_policy.json
    is missing — one-version backward compat for downstream tooling
    pinned to pre-v1.3.6 manifests."""
    canon_path = REPO_ROOT / ".claude-plugin" / "canon_policy.json"
    plugin_path = REPO_ROOT / ".claude-plugin" / "plugin.json"
    canon: dict = {}
    if canon_path.is_file():
        try:
            canon = json.loads(canon_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            canon = {}
    elif plugin_path.is_file():
        try:
            doc = json.loads(plugin_path.read_text(encoding="utf-8"))
            legacy = doc.get("canonPolicyVersion", {})
            if isinstance(legacy, dict):
                canon = legacy
        except (OSError, json.JSONDecodeError):
            canon = {}
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
    """Build the AsyncAPI YAML doc + the anchor manifest. `api_path_str`
    is the value to record in `view_files[].path` — repo-relative when
    the file lives inside the workspace, absolute otherwise (v1.2.19
    R1-FIX-2 + v1.3.0 patterns).

    Returns (asyncapi_doc, manifest_doc)."""
    channels: dict[str, dict] = {}
    operations: dict[str, dict] = {}
    anchor_map: list[dict] = []
    unmapped: list[dict] = []
    seen_addresses: set[str] = set()

    for row in rows:
        status, _reason = _classify_anchor(row)
        anchor_id = (row.get("AnchorID") or "").strip()
        element_id = (row.get("ElementID") or "").strip()

        if status == "skipped_bad_anchor_id":
            # Silently dropped — AnchorID itself unusable as manifest
            # reference (would fail manifest schema's ANC-... pattern).
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
                "reason": "element_id_not_channel_shaped",
                "element_id": element_id,
            })
            continue

        # status == "ready"
        if element_id in seen_addresses:
            unmapped.append({
                "a61_anchor_id": anchor_id,
                "reason": "duplicate_channel_collision",
                "element_id": element_id,
            })
            continue
        seen_addresses.add(element_id)

        claim_id = (row.get("ClaimID") or "").strip()
        a51_ref = (row.get("A51Ref") or "").strip()
        tag_provenance = claim_id or a51_ref or anchor_id

        channel_key = f"channel_{_sanitize_anchor_id_for_key(anchor_id)}"
        operation_key = channel_key  # symmetry: one operation per channel in skeleton
        channel_obj: dict = {
            "address": element_id,
            "messages": {},
        }
        # R1 fix: AsyncAPI 3.0 spec requires `parameters` for every
        # Channel Address Expression `{name}` in the address. Without
        # this the document is non-conformant against the spec even
        # though our regex accepts the address. Extract names from the
        # already-validated address (brace-balance scan ran earlier)
        # and emit a placeholder parameter object per name. Operator
        # enriches each parameter with `description`/`schema` after
        # export.
        param_names = _CHANNEL_PARAM_NAME.findall(element_id)
        if param_names:
            channel_obj["parameters"] = {
                name: {
                    "description": (
                        f"Placeholder parameter — operator must enrich "
                        f"with type/schema before shipping (extracted "
                        f"from `{{{name}}}` in address `{element_id}`)."
                    ),
                }
                for name in param_names
            }
        channels[channel_key] = channel_obj
        operations[operation_key] = {
            "action": "send",
            "channel": {"$ref": f"#/channels/{channel_key}"},
            "tags": [{"name": f"bsa-anchor:{tag_provenance}"}],
        }

        anchor_map.append({
            "view_element_id": channel_key,
            "view_element_kind": "Channel",
            "a61_anchor_id": anchor_id,
            # v1.3.7: every v1.3.0+ skeleton entry is by definition a
            # candidate (operator must enrich payload schemas before the
            # contract is real). Tagged explicitly so CI / release-
            # readiness gates can grep for un-promoted skeletons.
            "anchor_status": "candidate",
            "notes": f"placeholder; trace: {tag_provenance}",
        })
        anchor_map.append({
            "view_element_id": f"send {channel_key}",
            "view_element_kind": "Operation",
            "a61_anchor_id": anchor_id,
            "anchor_status": "candidate",
            "notes": (
                f"placeholder send op (operator may switch to receive); "
                f"trace: {tag_provenance}"
            ),
        })

    asyncapi_doc = {
        "asyncapi": ASYNCAPI_VERSION,
        "info": {
            "title": title,
            "version": version,
        },
        "channels": channels,
        "operations": operations,
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
    return asyncapi_doc, manifest_doc


# ---- YAML rendering ------------------------------------------------


def _render_yaml(doc: dict) -> str:
    """Render the AsyncAPI dict as deterministic YAML (`safe_dump`,
    `sort_keys=False`). PyYAML is a test-only dep in repo but a
    runtime requirement here; lazy import with clear error."""
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML required for skills/asyncapi-from-context. Install via "
            "`pip install pyyaml` or `pip install -r requirements-dev.txt`."
        ) from exc
    return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)


# ---- Atomic writes -------------------------------------------------


def _atomic_write(target_path: Path, body: str) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=".asyncapi_exporter_",
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


# ---- _is_relative_to backport --------------------------------------


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


# ---- CLI -----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "AsyncAPI 3.0 exporter from BSA Stage 6 contract layer "
            "(v1.3.1). Reads A61 anchor map, emits skeleton "
            "asyncapi.yaml + anchor manifest. Skeleton-only: operator "
            "enriches channels with real message payloads after "
            "export. NEVER runs git/commit/push or modifies canonical "
            "state."
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
            f"{DEFAULT_INPUT_REL}). Bypasses the workspace `analysis/` "
            f"guard so fixture-based runs work without an initialized "
            f"BSA workspace (v1.3.0 OpenAPI exporter R1-FIX-1 lesson)."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            f"Override the output directory (default <workspace>/"
            f"{DEFAULT_OUTPUT_REL}). Implicit-missing path is "
            f"permissive (created on demand); explicit-missing path "
            f"is rejected (operator typo defense, mirrors v1.2.19 "
            f"patcher R1-FIX-1 + v1.3.0 OpenAPI exporter)."
        ),
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help=(
            "AsyncAPI info.title value (default: workspace directory "
            "name)."
        ),
    )
    parser.add_argument(
        "--version",
        type=str,
        default="1.0.0",
        help="AsyncAPI info.version value (default: `1.0.0`).",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help=(
            "Print the manifest JSON to stdout instead of writing "
            "files."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-summary log line.",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    workspace = args.workspace.resolve()
    # v1.3.0 R1-FIX-1: workspace guard only when --input not provided.
    if args.input is None:
        if not (workspace / "analysis").is_dir():
            print(
                f"asyncapi-from-context: workspace {workspace} is not "
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
        # v1.2.19 R1-FIX-1 mirror: explicit override requires existence.
        if not output_dir.is_dir():
            print(
                f"asyncapi-from-context: --output-dir {output_dir} "
                f"does not exist or is not a directory. (An implicit "
                f"workspace-derived output dir that doesn't exist yet "
                f"is permissive; an explicit path that doesn't exist "
                f"is a typo and rejected.)",
                file=sys.stderr,
            )
            return 2

    rows, err = _read_a61_rows(input_path)
    if err is not None:
        print(f"asyncapi-from-context: {err}", file=sys.stderr)
        return 2

    title = args.title if args.title is not None else workspace.name
    api_path = output_dir / DEFAULT_API_FILENAME
    manifest_path = output_dir / DEFAULT_MANIFEST_FILENAME

    # v1.2.19 R1-FIX-2 mirror: relative when in workspace, absolute
    # otherwise.
    if _is_relative_to(api_path, workspace):
        api_path_str = str(api_path.relative_to(workspace))
    else:
        api_path_str = str(api_path)

    asyncapi_doc, manifest_doc = build_bundle(
        rows,
        title=title,
        version=args.version,
        api_path_str=api_path_str,
    )

    try:
        yaml_text = _render_yaml(asyncapi_doc)
    except RuntimeError as exc:
        print(f"asyncapi-from-context: {exc}", file=sys.stderr)
        return 2

    if args.print_only:
        print(json.dumps(manifest_doc, indent=2))
        return 0

    _atomic_write(api_path, yaml_text)
    _atomic_write_json(manifest_path, manifest_doc)

    if not args.quiet:
        view_file = manifest_doc["view_files"][0]
        anchors_in = len(view_file["anchor_map"])
        unmapped = len(view_file["unmapped_anchors"])
        # 2 anchor_map entries per materialized anchor (Channel + Operation).
        channels_count = anchors_in // 2
        print(
            f"asyncapi-from-context: wrote {api_path} + {manifest_path}\n"
            f"  channels materialized: {channels_count}\n"
            f"  anchor_map entries: {anchors_in}\n"
            f"  unmapped_anchors: {unmapped}\n"
            f"  NOTE: v1.3.1 ships a SKELETON — placeholder channels "
            f"+ default `send` action only. Operator must enrich "
            f"asyncapi.yaml with real message payload schemas + "
            f"action direction before shipping."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
