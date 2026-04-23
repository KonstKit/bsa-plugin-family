#!/usr/bin/env python3
"""Sidecar registry lint (v1.1.18, S2).

Validates `config/sidecar_registry.yaml` per the contract documented
in the file's own header:

  C1. Each entry's `name` MUST match an existing skills/<name>/ dir.
  C2. Each entry's `integration_contract` MUST point at a real file.
  C3. Each entry's `anchor_manifest_schema` MUST exist + conform to
      the base shape (governance/schemas/sidecar_anchor_manifest.base.schema.json):
      (a) all 5 base-required top-level fields present;
      (b) properties.view_files.type == "array";
      (c) properties.view_files.minItems >= 1;
      (d) each view_files[] item requires path + anchor_map.
  C4. Each entry's `f5_path_prefix` MUST NOT match any POLICY_GLOBS
      entry (sidecar paths must stay non-canonical).
  C5. No two entries may share the same `name`.
  C6. Required fields (name, output_format, f5_path_prefix,
      integration_contract, anchor_manifest_schema, status, added_in,
      summary) MUST all be present.
  C7. `status` MUST be one of {stable, beta, experimental}.

CLI:
  scripts/sidecar_registry_lint.py            # lint (exit 0 on PASS)
  scripts/sidecar_registry_lint.py --quiet    # suppress OK lines

Exit codes:
  0 — all checks pass.
  1 — at least one finding.
  2 — invocation error (missing registry, malformed YAML, missing
      base schema, etc.).

Stdlib + pyyaml.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "config" / "sidecar_registry.yaml"
BASE_SCHEMA_PATH = (
    REPO_ROOT / "governance" / "schemas" / "sidecar_anchor_manifest.base.schema.json"
)

ALLOWED_STATUSES = frozenset({"stable", "beta", "experimental"})
REQUIRED_FIELDS = (
    "name", "output_format", "f5_path_prefix",
    "integration_contract", "anchor_manifest_schema",
    "status", "added_in", "summary",
)


@dataclass
class Finding:
    sidecar_name: str  # may be empty for file-level findings
    code: str
    message: str

    def format(self) -> str:
        if self.sidecar_name:
            return f"[{self.code}] {self.sidecar_name}: {self.message}"
        return f"[{self.code}] {self.message}"


# ---- Helpers ---------------------------------------------------------


def _load_yaml(path: Path):
    try:
        import yaml  # type: ignore
    except ImportError:
        raise RuntimeError(
            "PyYAML required; install via `pip install pyyaml`."
        )
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_base_schema() -> dict:
    if not BASE_SCHEMA_PATH.is_file():
        raise RuntimeError(
            f"base schema missing: {BASE_SCHEMA_PATH}. v1.1.18 added this; "
            f"if it's gone the lint can't validate per-sidecar conformance."
        )
    return json.loads(BASE_SCHEMA_PATH.read_text(encoding="utf-8"))


def _read_policy_globs() -> list[str]:
    """Reuse the AST-based reader from phase_7_lint (same contract:
    keep in lockstep with scripts/compute_canon_hash.py POLICY_GLOBS)."""
    import ast
    canon_path = REPO_ROOT / "scripts" / "compute_canon_hash.py"
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
                f"POLICY_GLOBS is {type(value_node).__name__}, expected Tuple/List."
            )
        # v1.1.18 round-1 (Codex MEDIUM): fail loudly on non-string
        # elements — matches phase_7_lint behavior. A future refactor
        # that adds `Path("...")` or computed-string entries to
        # POLICY_GLOBS would silently skip those globs in C4 otherwise,
        # leaving the canon-neutrality guard incomplete.
        out: list[str] = []
        for elt in value_node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(elt.value)
            else:
                raise RuntimeError(
                    f"POLICY_GLOBS contains non-string element "
                    f"{ast.dump(elt)} — sidecar_registry_lint expects string "
                    f"literals (matching phase_7_lint contract)."
                )
        return out
    raise RuntimeError(
        "Could not find POLICY_GLOBS in scripts/compute_canon_hash.py."
    )


# ---- Per-entry checks ------------------------------------------------


def check_required_fields(entry: dict, findings: list[Finding]) -> None:
    name = entry.get("name", "<no-name>")
    for field_name in REQUIRED_FIELDS:
        if field_name not in entry or entry[field_name] in (None, ""):
            findings.append(Finding(
                name, "C6_MISSING_FIELD",
                f"missing required field {field_name!r}",
            ))


def check_skill_dir_exists(entry: dict, findings: list[Finding]) -> None:
    name = entry.get("name", "")
    if not name:
        return
    skill_dir = REPO_ROOT / "skills" / name
    if not skill_dir.is_dir():
        findings.append(Finding(
            name, "C1_SKILL_DIR_MISSING",
            f"no skills/{name}/ directory; either typo or sidecar not yet committed",
        ))


def check_integration_contract_exists(entry: dict, findings: list[Finding]) -> None:
    name = entry.get("name", "")
    contract_path = entry.get("integration_contract", "")
    if not contract_path:
        return
    if not (REPO_ROOT / contract_path).is_file():
        findings.append(Finding(
            name, "C2_INTEGRATION_CONTRACT_MISSING",
            f"integration_contract path does not exist: {contract_path}",
        ))


def check_anchor_schema_conforms_to_base(
    entry: dict, base_schema: dict, findings: list[Finding],
) -> None:
    """C3: per-sidecar schema MUST conform to the base shape.

    v1.1.18 round-1 (Codex HIGH): earlier impl only compared the
    top-level `required` field set. A per-sidecar schema could keep
    the 5 required fields but mutate `view_files` to a non-array OR
    drop minItems/items.required → the new "add a sidecar" pipeline
    would silently accept malformed schemas. Now we also pin:
      * top-level `properties.view_files.type == 'array'`
      * top-level `properties.view_files.minItems >= 1`
      * each view_files item declares `path` + `anchor_map` as required."""
    name = entry.get("name", "")
    schema_rel = entry.get("anchor_manifest_schema", "")
    if not schema_rel:
        return
    schema_path = REPO_ROOT / schema_rel
    if not schema_path.is_file():
        findings.append(Finding(
            name, "C3_ANCHOR_SCHEMA_MISSING",
            f"anchor_manifest_schema path does not exist: {schema_rel}",
        ))
        return
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        findings.append(Finding(
            name, "C3_ANCHOR_SCHEMA_MALFORMED",
            f"could not parse: {exc}",
        ))
        return

    base_required = set(base_schema.get("required", []))
    schema_required = set(schema.get("required", []))
    missing = base_required - schema_required
    if missing:
        findings.append(Finding(
            name, "C3_ANCHOR_SCHEMA_BASE_VIOLATION",
            f"per-sidecar schema {schema_rel} missing required fields "
            f"that the base schema declares: {sorted(missing)}. Add them "
            f"OR explain in a comment why this sidecar deliberately omits.",
        ))

    # Deeper structural conformance: view_files must be an array with
    # minItems >= 1 (non-empty) AND each item must require `path` +
    # `anchor_map`. This catches the round-1 hole where a per-sidecar
    # schema could keep `view_files` in `required` but mutate its type
    # or relax its constraints.
    #
    # v1.1.18 round-2 (Codex HIGH): if `properties.view_files` is
    # MISSING entirely, the structural checks below would silently
    # short-circuit. A per-sidecar schema that lists view_files in
    # `required` but never describes its shape would pass the lint
    # while emitting zero useful contract. Treat absence as its own
    # violation before running the deeper checks.
    view_files_def = (schema.get("properties") or {}).get("view_files")
    if view_files_def is None:
        findings.append(Finding(
            name, "C3_ANCHOR_SCHEMA_VIEW_FILES_NOT_DEFINED",
            f"per-sidecar schema {schema_rel}: properties.view_files is "
            f"absent. The base schema requires view_files structurally "
            f"(type:array, minItems>=1, items.required=[path, anchor_map]); "
            f"declaring it in `required` without `properties` defines no "
            f"contract.",
        ))
    else:
        if view_files_def.get("type") != "array":
            findings.append(Finding(
                name, "C3_ANCHOR_SCHEMA_VIEW_FILES_NOT_ARRAY",
                f"per-sidecar schema {schema_rel}: properties.view_files.type "
                f"is {view_files_def.get('type')!r}, expected 'array'.",
            ))
        min_items = view_files_def.get("minItems", 0)
        if min_items < 1:
            findings.append(Finding(
                name, "C3_ANCHOR_SCHEMA_VIEW_FILES_ALLOWS_EMPTY",
                f"per-sidecar schema {schema_rel}: properties.view_files.minItems "
                f"is {min_items}, expected >= 1 (a manifest with zero view files "
                f"is meaningless — every sidecar emits at least one .puml/.bpmn/etc.).",
            ))
        item_def = view_files_def.get("items") or {}
        item_required = set(item_def.get("required", []))
        for required_item_field in ("path", "anchor_map"):
            if required_item_field not in item_required:
                findings.append(Finding(
                    name, "C3_ANCHOR_SCHEMA_VIEW_FILES_ITEM_MISSING_REQUIRED",
                    f"per-sidecar schema {schema_rel}: each view_files[] item "
                    f"MUST require {required_item_field!r} (base schema contract).",
                ))


def check_f5_path_outside_policy_globs(
    entry: dict, policy_globs: list[str], findings: list[Finding],
) -> None:
    name = entry.get("name", "")
    prefix = entry.get("f5_path_prefix", "")
    if not prefix:
        return
    # f5_path_prefix is a directory prefix; check that no POLICY_GLOBS
    # entry lives inside it (which would mean canonical state under a
    # sidecar path — by design forbidden).
    for glob in policy_globs:
        if glob.startswith(prefix):
            findings.append(Finding(
                name, "C4_F5_PATH_INSIDE_POLICY_GLOBS",
                f"sidecar f5_path_prefix {prefix!r} contains POLICY_GLOBS "
                f"entry {glob!r}; sidecar paths must be non-canonical "
                f"(see docs/sidecar_inventory.md §'F5 boundary').",
            ))


def check_status_value(entry: dict, findings: list[Finding]) -> None:
    name = entry.get("name", "")
    status = entry.get("status")
    if status is None:
        return
    if status not in ALLOWED_STATUSES:
        findings.append(Finding(
            name, "C7_STATUS_UNKNOWN",
            f"status {status!r} not in {sorted(ALLOWED_STATUSES)}",
        ))


# ---- File-level checks -----------------------------------------------


def check_unique_names(entries: list[dict], findings: list[Finding]) -> None:
    seen: dict[str, int] = {}
    for idx, entry in enumerate(entries, start=1):
        name = entry.get("name")
        if not name:
            findings.append(Finding(
                "", "C5_MISSING_NAME",
                f"entry #{idx} has no name field",
            ))
            continue
        if name in seen:
            findings.append(Finding(
                name, "C5_DUPLICATE_NAME",
                f"duplicate name (also at entry #{seen[name]})",
            ))
            continue
        seen[name] = idx


# ---- Driver ----------------------------------------------------------


def run_lint() -> tuple[bool, list[Finding]]:
    findings: list[Finding] = []
    if not REGISTRY_PATH.is_file():
        return False, [Finding(
            "", "C0_FILE_MISSING",
            f"registry file missing: {REGISTRY_PATH}",
        )]
    try:
        doc = _load_yaml(REGISTRY_PATH)
    except Exception as exc:
        return False, [Finding(
            "", "C0_PARSE_ERROR",
            f"could not parse {REGISTRY_PATH}: {type(exc).__name__}: {exc}",
        )]
    if not isinstance(doc, dict):
        return False, [Finding(
            "", "C0_BAD_TOP_LEVEL",
            f"top-level YAML is {type(doc).__name__}, expected dict",
        )]
    entries = doc.get("sidecars")
    if not isinstance(entries, list):
        return False, [Finding(
            "", "C0_NO_SIDECARS_KEY",
            "top-level dict missing `sidecars:` list",
        )]
    base_schema = _load_base_schema()
    policy_globs = _read_policy_globs()

    check_unique_names(entries, findings)
    for entry in entries:
        if not isinstance(entry, dict):
            findings.append(Finding(
                "", "C0_BAD_ENTRY",
                f"entry is {type(entry).__name__}, expected dict",
            ))
            continue
        check_required_fields(entry, findings)
        check_skill_dir_exists(entry, findings)
        check_integration_contract_exists(entry, findings)
        check_anchor_schema_conforms_to_base(entry, base_schema, findings)
        check_f5_path_outside_policy_globs(entry, policy_globs, findings)
        check_status_value(entry, findings)
    return not findings, findings


# ---- CLI -------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sidecar registry lint")
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-entry OK lines",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        passed, findings = run_lint()
    except RuntimeError as exc:
        print(f"sidecar_registry_lint: {exc}", file=sys.stderr)
        return 2
    if findings:
        print(
            f"sidecar_registry_lint: {len(findings)} finding(s) in "
            f"{REGISTRY_PATH.relative_to(REPO_ROOT)}:",
            file=sys.stderr,
        )
        for f in findings:
            print(f"  {f.format()}", file=sys.stderr)
        return 1 if not passed else 0
    if not args.quiet:
        print(
            f"sidecar_registry_lint: PASS — "
            f"{REGISTRY_PATH.relative_to(REPO_ROOT)} clean (0 findings)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
