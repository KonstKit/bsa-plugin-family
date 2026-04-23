#!/usr/bin/env python3
"""Phase 7 tunable inventory lint (v1.1.14, Section D foundation).

Validates `config/tunables.yaml` per the contract documented in
`docs/phase_7_design.md`:

  1. Every entry's `source_file:source_line` MUST contain the declared
     `current_value` (verbatim substring match). Catches drift if a
     maintainer edits the value but forgets to update tunables.yaml.

  2. Every entry's `linked_invariants` MUST reference real INV-XX IDs
     from `governance/immutable_invariants.md`.

  3. Every entry's `owner_skill` MUST reference a real skill directory
     (or 'governance' / 'sidecar:<name>' for non-skill owners).

  4. No two entries may share the same `id`.

  5. Every L1_auto_tunable with non-empty `linked_invariants` is an
     IMMUTABLE_CONFLICT — auto-patch is forbidden when the tunable
     touches an invariant. Hard-fail.

  6. **L1_auto_tunable** entries' `source_file` MUST NOT match any
     POLICY_GLOBS pattern (canon-hash-neutrality for auto-merge).
     L2_proposal_only entries MAY live in POLICY_GLOBS — the
     analyst-sign-off step naturally includes a manifest version
     bump + canon-hash refresh, so the two-semver discipline stays
     intact.

  7. `change_class` MUST be one of {L1_auto_tunable, L2_proposal_only}.

  8. `allowed_range` MUST satisfy: len()==2, min < max, both numeric,
     AND `current_value` (parsed as float when possible) MUST fall
     within the range (otherwise the bench is operating off-baseline).

CLI:
  scripts/phase_7_lint.py                  # lint (exit 0 on PASS)
  scripts/phase_7_lint.py --quiet          # suppress per-entry OK lines

Exit codes:
  0 — all entries pass all 8 checks
  1 — at least one entry has a finding
  2 — invocation error (missing tunables.yaml, malformed YAML, etc.)

Stdlib-only EXCEPT for `yaml` parsing (pulled in via requirements-dev.txt
the same way tests/test_ci_workflows.py uses it).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TUNABLES_PATH = REPO_ROOT / "config" / "tunables.yaml"
INVARIANTS_PATH = REPO_ROOT / "governance" / "immutable_invariants.md"

ALLOWED_CHANGE_CLASSES = frozenset({"L1_auto_tunable", "L2_proposal_only"})
INV_ID_RE = re.compile(r"^INV-(?:0[1-9]|10)$")  # INV-01..INV-10


@dataclass
class Finding:
    """One lint finding. `tunable_id` may be empty for file-level findings."""

    tunable_id: str
    code: str
    message: str

    def format(self) -> str:
        prefix = f"[{self.code}]"
        if self.tunable_id:
            return f"{prefix} {self.tunable_id}: {self.message}"
        return f"{prefix} {self.message}"


# ---- Helpers -----------------------------------------------------------


def _load_yaml(path: Path):
    """Lazy-import yaml + parse the file. Returns the parsed structure
    or raises on malformed content."""
    try:
        import yaml  # type: ignore
    except ImportError:
        raise RuntimeError(
            "PyYAML required for phase_7_lint.py. Install via "
            "`pip install pyyaml` or `pip install -r requirements-dev.txt`."
        )
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _read_invariant_ids() -> set[str]:
    """Parse `governance/immutable_invariants.md` and extract all
    `INV-XX` IDs **declared** as section headers (i.e., authoritative
    declarations, not historical / prose mentions).

    A declaration looks like `### INV-01: <name>` (h3 header with the
    invariant ID + colon). Prose references like "see INV-09 above"
    or "historical note: INV-09 was removed" do NOT count as
    declarations and would otherwise let `check_invariants_exist`
    silently accept stale links.

    v1.1.14 round-1 (Codex): the earlier impl regexed every INV-XX
    mention in the file, which let prose references satisfy C2 even
    if the actual invariant declaration was gone. Now we parse only
    h2/h3 headers."""
    body = INVARIANTS_PATH.read_text(encoding="utf-8")
    return set(re.findall(r"^#{2,3}\s+(INV-\d{2})\b", body, flags=re.MULTILINE))


def _read_policy_globs() -> list[str]:
    """Read POLICY_GLOBS from `scripts/compute_canon_hash.py` so the
    lint stays in lockstep with the canon-hash contract. Returns a
    list of glob patterns (str). If the script has been refactored,
    fail loudly rather than silently letting tunables sneak into
    canonical state.

    Uses Python's `ast` module so we correctly handle:
      * tuple OR list literals (the script currently uses tuple)
      * embedded comments containing `(` or `)` (which would fool a
        regex-based reader into stopping at the first close-paren in
        a comment — round-1 bug fixed in v1.1.14)
      * arbitrary whitespace + type annotations
    """
    import ast
    canon_path = REPO_ROOT / "scripts" / "compute_canon_hash.py"
    tree = ast.parse(canon_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        # Type-annotated form: POLICY_GLOBS: tuple[str, ...] = (...)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value_node = node.value
        # Plain assignment: POLICY_GLOBS = (...)
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
                f"POLICY_GLOBS in scripts/compute_canon_hash.py is a "
                f"{type(value_node).__name__}, expected ast.Tuple or ast.List."
            )
        out: list[str] = []
        for elt in value_node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(elt.value)
            else:
                raise RuntimeError(
                    f"POLICY_GLOBS contains non-string element "
                    f"{ast.dump(elt)} — phase_7_lint expects string literals."
                )
        return out
    raise RuntimeError(
        "Could not locate POLICY_GLOBS = (...) | [...] in "
        "scripts/compute_canon_hash.py. Did the script get "
        "refactored? Update scripts/phase_7_lint.py to match."
    )


def _matches_any_glob(path: str, patterns: list[str]) -> str | None:
    """Return the first matching pattern, or None if no match.
    Uses `fnmatch.fnmatchcase` (POSIX glob, the same primitive the
    canon-hash script uses to expand its globs)."""
    import fnmatch
    for pat in patterns:
        if fnmatch.fnmatchcase(path, pat):
            return pat
    return None


def _parse_numeric(value_str: str) -> float | None:
    """Best-effort numeric parse. Strips operator prefixes (>=, ≥, <=)
    so values like '>= 0.75' and '0.75' both parse to 0.75. Returns
    None if the string is non-numeric (e.g., enum value)."""
    cleaned = value_str.strip()
    for prefix in (">=", "<=", "≥", "≤", ">", "<", "="):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    try:
        return float(cleaned)
    except ValueError:
        return None


# ---- Per-entry checks -------------------------------------------------


def check_source_line_matches(
    entry: dict, findings: list[Finding]
) -> None:
    """C1: The declared current_value MUST appear at source_file:source_line."""
    src = REPO_ROOT / entry["source_file"]
    if not src.is_file():
        findings.append(Finding(
            entry["id"], "C1_NO_SOURCE_FILE",
            f"source_file does not exist: {entry['source_file']}",
        ))
        return
    lines = src.read_text(encoding="utf-8").splitlines()
    line_idx = entry["source_line"] - 1
    if not 0 <= line_idx < len(lines):
        findings.append(Finding(
            entry["id"], "C1_LINE_OUT_OF_RANGE",
            f"source_line {entry['source_line']} > file length {len(lines)} "
            f"in {entry['source_file']}",
        ))
        return
    line = lines[line_idx]
    needle = str(entry["current_value"])
    if needle not in line:
        findings.append(Finding(
            entry["id"], "C1_VALUE_DRIFT",
            f"current_value {needle!r} not found at "
            f"{entry['source_file']}:{entry['source_line']}. "
            f"Line content: {line!r}",
        ))


def check_invariants_exist(
    entry: dict, valid_inv_ids: set[str], findings: list[Finding]
) -> None:
    """C2: Every linked_invariants entry MUST be a real INV-XX from
    immutable_invariants.md."""
    for inv_id in entry.get("linked_invariants", []):
        if not INV_ID_RE.match(inv_id):
            findings.append(Finding(
                entry["id"], "C2_INVARIANT_BAD_FORMAT",
                f"linked_invariants entry {inv_id!r} doesn't match INV-XX "
                f"shape (expected INV-01..INV-10)",
            ))
            continue
        if inv_id not in valid_inv_ids:
            findings.append(Finding(
                entry["id"], "C2_INVARIANT_NOT_DECLARED",
                f"linked_invariants references {inv_id!r} but no INV by "
                f"that ID is declared in governance/immutable_invariants.md. "
                f"Either fix the typo or add the INV.",
            ))


def check_owner_skill_exists(entry: dict, findings: list[Finding]) -> None:
    """C3: owner_skill MUST be 'governance', 'sidecar:<name>', or a real
    skill directory under skills/."""
    owner = entry["owner_skill"]
    if owner == "governance":
        return
    if owner.startswith("sidecar:"):
        sidecar_name = owner.split(":", 1)[1]
        sidecar_path = REPO_ROOT / "skills" / sidecar_name
        if not sidecar_path.is_dir():
            findings.append(Finding(
                entry["id"], "C3_SIDECAR_MISSING",
                f"owner_skill {owner!r} but skills/{sidecar_name}/ "
                f"does not exist",
            ))
        return
    skill_path = REPO_ROOT / "skills" / owner
    if not skill_path.is_dir():
        findings.append(Finding(
            entry["id"], "C3_SKILL_MISSING",
            f"owner_skill {owner!r} but skills/{owner}/ does not exist. "
            f"Use 'governance' or 'sidecar:<name>' for non-skill owners.",
        ))


def check_change_class(entry: dict, findings: list[Finding]) -> None:
    """C7: change_class MUST be in the allowed set."""
    cc = entry.get("change_class")
    if cc not in ALLOWED_CHANGE_CLASSES:
        findings.append(Finding(
            entry["id"], "C7_CHANGE_CLASS_UNKNOWN",
            f"change_class {cc!r} not in {sorted(ALLOWED_CHANGE_CLASSES)}",
        ))


def check_immutable_conflict(entry: dict, findings: list[Finding]) -> None:
    """C5: L1_auto_tunable + non-empty linked_invariants = IMMUTABLE_CONFLICT.

    This is the headline Phase 7 safety rule (per
    docs/phase_7_design.md): auto-patching is forbidden when the
    tunable touches an immutable invariant. The maintainer must
    re-classify as L2_proposal_only or remove the linked_invariants
    entry (i.e., assert the tunable is invariant-independent)."""
    cc = entry.get("change_class")
    inv_links = entry.get("linked_invariants", [])
    if cc == "L1_auto_tunable" and inv_links:
        findings.append(Finding(
            entry["id"], "C5_IMMUTABLE_CONFLICT",
            f"L1_auto_tunable with linked_invariants={inv_links} is an "
            f"IMMUTABLE_CONFLICT — auto-patch is forbidden when the "
            f"tunable touches an invariant. Re-classify as "
            f"L2_proposal_only OR remove the invariant link if the "
            f"tunable is genuinely invariant-independent.",
        ))


def check_policy_globs_neutrality(
    entry: dict, policy_globs: list[str], findings: list[Finding]
) -> None:
    """C6: L1_auto_tunable entries' source_file MUST NOT match any
    POLICY_GLOBS pattern (canon-hash-neutrality for auto-merge).

    L2_proposal_only entries MAY live in POLICY_GLOBS — the analyst-
    sign-off step naturally includes a manifest version bump + canon-
    hash refresh, so the two-semver discipline stays intact.

    Hard-failing for L1 prevents the design pathology where Phase 7
    silently auto-bumps canon state without a release marker."""
    matched = _matches_any_glob(entry["source_file"], policy_globs)
    if matched is None:
        return
    if entry.get("change_class") == "L1_auto_tunable":
        findings.append(Finding(
            entry["id"], "C6_POLICY_GLOB_VIOLATION",
            f"L1_auto_tunable source_file {entry['source_file']!r} "
            f"matches POLICY_GLOBS pattern {matched!r}. Auto-merging "
            f"a value inside canonical state would silently bump the "
            f"canon hash without a release marker — breaks the "
            f"two-semver discipline. Either re-classify as "
            f"L2_proposal_only (analyst sign-off includes manifest "
            f"bump) OR move the value out of POLICY_GLOBS.",
        ))


def check_allowed_range(entry: dict, findings: list[Finding]) -> None:
    """C8: allowed_range = [min, max] with min < max, AND current_value
    falls within (when current_value is numeric)."""
    rng = entry.get("allowed_range")
    if not isinstance(rng, list) or len(rng) != 2:
        findings.append(Finding(
            entry["id"], "C8_RANGE_MALFORMED",
            f"allowed_range {rng!r} must be [min, max]",
        ))
        return
    lo, hi = rng
    if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
        findings.append(Finding(
            entry["id"], "C8_RANGE_NON_NUMERIC",
            f"allowed_range {rng!r} contains non-numeric bound",
        ))
        return
    if lo >= hi:
        findings.append(Finding(
            entry["id"], "C8_RANGE_INVERTED",
            f"allowed_range [{lo}, {hi}] has min >= max",
        ))
        return
    cur_numeric = _parse_numeric(str(entry["current_value"]))
    if cur_numeric is not None and not (lo <= cur_numeric <= hi):
        findings.append(Finding(
            entry["id"], "C8_CURRENT_OUT_OF_RANGE",
            f"current_value {cur_numeric} not in allowed_range "
            f"[{lo}, {hi}]",
        ))


# ---- File-level checks ------------------------------------------------


def check_unique_ids(entries: list[dict], findings: list[Finding]) -> None:
    """C4: No two entries may share the same `id`."""
    seen: dict[str, int] = {}
    for idx, entry in enumerate(entries, start=1):
        eid = entry.get("id")
        if not eid:
            findings.append(Finding(
                "", "C4_MISSING_ID",
                f"entry #{idx} has no `id` field",
            ))
            continue
        if eid in seen:
            findings.append(Finding(
                eid, "C4_DUPLICATE_ID",
                f"duplicate id (also at entry #{seen[eid]})",
            ))
            continue
        seen[eid] = idx


# ---- Required-fields shape check --------------------------------------


REQUIRED_FIELDS = (
    "id", "current_value", "allowed_range", "owner_skill",
    "source_file", "source_line", "linked_invariants",
    "change_class", "rationale",
)


def check_required_fields(entry: dict, findings: list[Finding]) -> None:
    """Pre-check: every entry has the required keys. Per-field checks
    that depend on these fields short-circuit safely if a key is
    missing."""
    eid = entry.get("id", "<no-id>")
    for field_name in REQUIRED_FIELDS:
        if field_name not in entry:
            findings.append(Finding(
                eid, "C0_MISSING_FIELD",
                f"entry missing required field {field_name!r}",
            ))


# ---- Driver -----------------------------------------------------------


def run_lint() -> tuple[bool, list[Finding]]:
    """Returns (passed, findings)."""
    findings: list[Finding] = []
    if not TUNABLES_PATH.is_file():
        return False, [Finding(
            "", "C0_FILE_MISSING",
            f"tunables file missing: {TUNABLES_PATH}",
        )]
    try:
        doc = _load_yaml(TUNABLES_PATH)
    except Exception as exc:  # malformed YAML, missing yaml lib, etc.
        return False, [Finding(
            "", "C0_PARSE_ERROR",
            f"could not parse {TUNABLES_PATH}: "
            f"{type(exc).__name__}: {exc}",
        )]
    if not isinstance(doc, dict):
        return False, [Finding(
            "", "C0_BAD_TOP_LEVEL",
            f"top-level YAML is {type(doc).__name__}, expected dict",
        )]
    entries = doc.get("tunables")
    if not isinstance(entries, list):
        return False, [Finding(
            "", "C0_NO_TUNABLES_KEY",
            "top-level dict missing `tunables:` list",
        )]
    valid_inv_ids = _read_invariant_ids()
    policy_globs = _read_policy_globs()

    check_unique_ids(entries, findings)
    for entry in entries:
        if not isinstance(entry, dict):
            findings.append(Finding(
                "", "C0_BAD_ENTRY",
                f"entry is {type(entry).__name__}, expected dict",
            ))
            continue
        check_required_fields(entry, findings)
        # Per-entry checks. They self-skip if a required field is missing.
        if {"source_file", "source_line", "current_value", "id"} <= entry.keys():
            check_source_line_matches(entry, findings)
        if {"linked_invariants", "id"} <= entry.keys():
            check_invariants_exist(entry, valid_inv_ids, findings)
        if {"owner_skill", "id"} <= entry.keys():
            check_owner_skill_exists(entry, findings)
        if {"change_class", "id"} <= entry.keys():
            check_change_class(entry, findings)
        if {"change_class", "linked_invariants", "id"} <= entry.keys():
            check_immutable_conflict(entry, findings)
        if {"source_file", "id"} <= entry.keys():
            check_policy_globs_neutrality(entry, policy_globs, findings)
        if {"allowed_range", "current_value", "id"} <= entry.keys():
            check_allowed_range(entry, findings)

    return not findings, findings


# ---- CLI --------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 7 tunable inventory lint",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-entry OK lines (still prints findings + summary)",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        passed, findings = run_lint()
    except RuntimeError as exc:
        print(f"phase_7_lint: {exc}", file=sys.stderr)
        return 2
    if findings:
        print(
            f"phase_7_lint: {len(findings)} finding(s) in "
            f"{TUNABLES_PATH.relative_to(REPO_ROOT)}:",
            file=sys.stderr,
        )
        for f in findings:
            print(f"  {f.format()}", file=sys.stderr)
        return 1 if not passed else 0
    if not args.quiet:
        print(
            f"phase_7_lint: PASS — {TUNABLES_PATH.relative_to(REPO_ROOT)} "
            f"clean (0 findings).",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
