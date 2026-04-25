#!/usr/bin/env python3
"""Compute the CanonPolicyVersion hash (US-S3-04).

CanonPolicyVersion travels in two forms:

1. **Bare semver** — e.g. `0.95` or `1.0.0`. Used pre-US-S3-04.
2. **Semver + hash** — e.g. `1.0.0+hash:abc123def456`. The hash is a
   SHA-256 digest over a canonical serialization of the POLICY files
   — the subset of the repo whose contents define the active policy.
   Anything else (fixture data, script implementation, docs not touched
   by policy rules) is excluded.

Policy files (authoritative list lives in ``POLICY_GLOBS`` below — any
change to that tuple is itself a CanonPolicyVersion change):

- ``governance/immutable_invariants.md``
- Every ``skills/*/SKILL.md`` (BSA workers, BSA auditors, BSA
  orchestrator, discovery d0-* workers, and sidecars). Full file,
  not just frontmatter — the body describes policy in places.
- Every ``skills/bsa-orchestrator/references/*.md`` (orchestrator is
  the policy owner).
- Per-skill policy references with semantic invariants:
  ``bsa-anchor-auditor/references/anchor-audit-contract.md``,
  ``bsa-citation-auditor/references/citation-and-overclaim.md``,
  ``bsa-claim-binder/references/claim-layer.md``,
  ``bsa-context-framer/references/*`` (all three),
  ``bsa-evidence-intake/references/reliability_tier_spec.md`` +
  ``source-intake.md``,
  ``bsa-handoff-packager/references/`` (h1..h4 specs,
  ``handoff-contract.md``, ``handoff_manifest.schema.json``),
  ``bsa-no-new-claims-auditor/references/no-new-claims-contract.md``.
- Both sidecar ``references/integration-contract.md`` +
  ``anchor_manifest.schema.json`` files (c4-plantuml, camunda-bpmn).
- ``docs/sem_audit_rename.md``.

Everything else (fixture data, scripts, tests, README, CI, retros) is
excluded so that non-policy changes do NOT bump the hash.

The digest is:
  h = sha256()
  for path in sorted(policy_files):
      h.update(path.encode('utf-8'))
      h.update(b'\\x00')
      h.update(open(path,'rb').read())
      h.update(b'\\x00')
  digest = h.hexdigest()

CLI usage:
  scripts/compute_canon_hash.py                  # prints the hash
  scripts/compute_canon_hash.py --full           # prints hash + breakdown
  scripts/compute_canon_hash.py --diff-against <prev_hash>
                                                 # prints hash; also prints
                                                 # 'CHANGED' or 'UNCHANGED'
                                                 # vs the prior hash string

Stdlib-only.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Authoritative list of policy-file globs, relative to repo root.
# Any change to the glob set is itself a CanonPolicyVersion change.
# Policy-file list. Every committed skill directory AND every policy-
# bearing reference is covered. Changing this tuple is itself a policy
# change (the docstring and contract-versioning.md prose must be kept
# in lockstep with this list).
POLICY_GLOBS: tuple[str, ...] = (
    # Governance (foundation layer).
    "governance/immutable_invariants.md",
    # Every SKILL.md across the skills/ directory — BSA main workers,
    # BSA auditors, BSA orchestrator, discovery workers (d0-*), and
    # sidecars. Omitting any one of these creates a drift blind-spot.
    "skills/bsa-anchor-auditor/SKILL.md",
    "skills/bsa-backbone-builder/SKILL.md",
    "skills/bsa-backlog-bridge/SKILL.md",
    "skills/bsa-citation-auditor/SKILL.md",
    "skills/bsa-claim-binder/SKILL.md",
    "skills/bsa-consistency-auditor/SKILL.md",
    "skills/bsa-context-framer/SKILL.md",
    "skills/bsa-contract-builder/SKILL.md",
    "skills/bsa-domain-modeler/SKILL.md",
    "skills/bsa-evidence-intake/SKILL.md",
    "skills/bsa-handoff-packager/SKILL.md",
    "skills/bsa-nfr-collector/SKILL.md",
    "skills/bsa-no-new-claims-auditor/SKILL.md",
    "skills/bsa-orchestrator/SKILL.md",
    "skills/bsa-semantic-extractor/SKILL.md",
    "skills/bsa-skeptical-reviewer/SKILL.md",
    "skills/bsa-story-writer/SKILL.md",
    "skills/bsa-test-scenario-builder/SKILL.md",
    "skills/bsa-traceability-matrix/SKILL.md",
    "skills/bsa-validation-readiness/SKILL.md",
    "skills/c4-plantuml-from-context/SKILL.md",
    "skills/camunda-bpmn-from-context/SKILL.md",
    "skills/dbml-from-context/SKILL.md",
    "skills/d0-context-researcher/SKILL.md",
    "skills/d0-feasibility-assessor/SKILL.md",
    "skills/d0-hypothesis-prioritizer/SKILL.md",
    "skills/d0-problem-framer/SKILL.md",
    "skills/d0-synthesis-gatekeeper/SKILL.md",
    "skills/asyncapi-from-context/SKILL.md",
    "skills/inot-prompt-builder/SKILL.md",
    "skills/openapi-from-context/SKILL.md",
    # Orchestrator references — the policy heart of the system.
    "skills/bsa-orchestrator/references/agent-write-scope.md",
    "skills/bsa-orchestrator/references/canonical-artifact-map.md",
    "skills/bsa-orchestrator/references/contract-versioning.md",
    "skills/bsa-orchestrator/references/discovery_to_main_merge.md",
    "skills/bsa-orchestrator/references/freshness-audit-contract.md",
    "skills/bsa-orchestrator/references/kpi-definitions.md",
    "skills/bsa-orchestrator/references/merge-and-reentry-policy.md",
    "skills/bsa-orchestrator/references/merge_log.schema.json",
    "skills/bsa-orchestrator/references/ownership-and-lifecycle.md",
    "skills/bsa-orchestrator/references/run-profile-gates.md",
    "skills/bsa-orchestrator/references/runtime-marker-schema.md",
    "skills/bsa-orchestrator/references/shared-control-surface-contracts.md",
    "skills/bsa-orchestrator/references/sidecar-integration.md",
    "skills/bsa-orchestrator/references/stage2-runtime-contract.md",
    "skills/bsa-orchestrator/references/triangulation-audit-contract.md",
    "skills/bsa-orchestrator/references/validation-scenario-manifest.csv",
    "skills/bsa-orchestrator/references/workflow-contract.md",
    # Per-skill policy references with semantic invariants.
    "skills/bsa-anchor-auditor/references/anchor-audit-contract.md",
    "skills/bsa-citation-auditor/references/citation-and-overclaim.md",
    "skills/bsa-claim-binder/references/claim-layer.md",
    "skills/bsa-context-framer/references/context-state-contract.md",
    "skills/bsa-context-framer/references/stakeholder-authority-rules.md",
    "skills/bsa-context-framer/references/system-context-seed-template.md",
    "skills/bsa-evidence-intake/references/reliability_tier_spec.md",
    "skills/bsa-evidence-intake/references/source-intake.md",
    "skills/bsa-handoff-packager/references/h1_spec.md",
    "skills/bsa-handoff-packager/references/h2_spec.md",
    "skills/bsa-handoff-packager/references/h3_spec.md",
    "skills/bsa-handoff-packager/references/h4_spec.md",
    "skills/bsa-handoff-packager/references/handoff-contract.md",
    "skills/bsa-handoff-packager/references/handoff_manifest.schema.json",
    "skills/bsa-no-new-claims-auditor/references/no-new-claims-contract.md",
    # Sidecar integration contracts + anchor manifest schemas.
    "skills/c4-plantuml-from-context/references/integration-contract.md",
    "skills/c4-plantuml-from-context/references/anchor_manifest.schema.json",
    "skills/camunda-bpmn-from-context/references/integration-contract.md",
    "skills/camunda-bpmn-from-context/references/anchor_manifest.schema.json",
    "skills/asyncapi-from-context/references/integration-contract.md",
    "skills/asyncapi-from-context/references/anchor_manifest.schema.json",
    "skills/dbml-from-context/references/integration-contract.md",
    "skills/dbml-from-context/references/anchor_manifest.schema.json",
    "skills/openapi-from-context/references/integration-contract.md",
    "skills/openapi-from-context/references/anchor_manifest.schema.json",
    # Repo-level policy docs.
    "docs/sem_audit_rename.md",
)


# Category buckets for --diff-breakdown (AC-7). Matching is by prefix.
POLICY_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("governance", "governance/"),
    ("skills_skill_md", "skills/"),  # sub-filter: path ends with /SKILL.md
    ("orchestrator_references", "skills/bsa-orchestrator/references/"),
    ("per_skill_references", "skills/"),  # sub-filter: anything else
    ("docs", "docs/"),
)


def _categorize(rel: str) -> str:
    if rel.startswith("governance/"):
        return "governance"
    if rel.startswith("docs/"):
        return "docs"
    if rel.startswith("skills/bsa-orchestrator/references/"):
        return "orchestrator_references"
    if rel.endswith("/SKILL.md"):
        return "skills_skill_md"
    return "per_skill_references"

HASH_PATTERN = re.compile(r"^[a-f0-9]{6,64}$")


def _resolve_policy_files(root: Path = REPO_ROOT) -> list[Path]:
    """Return sorted absolute paths of committed policy files."""
    paths: list[Path] = []
    for rel in POLICY_GLOBS:
        p = root / rel
        if not p.is_file():
            raise FileNotFoundError(f"policy file missing: {rel}")
        paths.append(p)
    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def compute_hash(root: Path = REPO_ROOT) -> str:
    """SHA-256 over canonical serialization of policy files."""
    paths = _resolve_policy_files(root)
    h = hashlib.sha256()
    for p in paths:
        rel = p.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(p.read_bytes())
        h.update(b"\x00")
    return h.hexdigest()


def compute_breakdown(root: Path = REPO_ROOT) -> list[tuple[str, str]]:
    """Return list of (relative path, per-file sha256) for every policy file."""
    paths = _resolve_policy_files(root)
    out: list[tuple[str, str]] = []
    for p in paths:
        rel = p.relative_to(root).as_posix()
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        out.append((rel, digest))
    return out


def compute_category_breakdown(root: Path = REPO_ROOT) -> dict[str, dict[str, object]]:
    """Return per-category {'count': N, 'hash': <sha256>, 'files': [...]}.

    This is the category-level diff breakdown required by AC-7. The
    per-category hash is computed the same way as the aggregate hash
    but scoped to files in that category — so the top-level hash
    changes iff at least one category hash changes.
    """
    paths = _resolve_policy_files(root)
    by_cat: dict[str, list[Path]] = {}
    for p in paths:
        rel = p.relative_to(root).as_posix()
        cat = _categorize(rel)
        by_cat.setdefault(cat, []).append(p)
    result: dict[str, dict[str, object]] = {}
    for cat, cat_paths in by_cat.items():
        h = hashlib.sha256()
        files: list[str] = []
        for p in sorted(cat_paths, key=lambda x: x.relative_to(root).as_posix()):
            rel = p.relative_to(root).as_posix()
            h.update(rel.encode("utf-8"))
            h.update(b"\x00")
            h.update(p.read_bytes())
            h.update(b"\x00")
            files.append(rel)
        result[cat] = {
            "count": len(cat_paths),
            "hash": h.hexdigest(),
            "files": files,
        }
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Compute CanonPolicyVersion hash over repo policy files (US-S3-04)."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repo root (defaults to script's parent directory).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Also print per-file breakdown after the digest.",
    )
    parser.add_argument(
        "--diff-breakdown",
        action="store_true",
        help=(
            "Print a category-level breakdown (governance / skills_skill_md "
            "/ orchestrator_references / per_skill_references / docs) "
            "alongside the aggregate hash. Each category row shows file "
            "count + per-category hash so reviewers can narrow where a "
            "policy bump originated."
        ),
    )
    parser.add_argument(
        "--diff-against",
        type=str,
        default=None,
        help="Compare against a prior hash (hex). Prints CHANGED or UNCHANGED.",
    )
    args = parser.parse_args(argv)

    try:
        digest = compute_hash(args.repo_root)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(digest)

    if args.full:
        print("--- per-file breakdown ---")
        for rel, file_digest in compute_breakdown(args.repo_root):
            print(f"{file_digest}  {rel}")

    if args.diff_breakdown:
        print("--- category breakdown ---")
        cat_info = compute_category_breakdown(args.repo_root)
        # Stable ordering for reviewer readability.
        order = (
            "governance",
            "skills_skill_md",
            "orchestrator_references",
            "per_skill_references",
            "docs",
        )
        for cat in order:
            info = cat_info.get(cat, {"count": 0, "hash": "-" * 64})
            print(f"{info['hash']}  {cat}  (n={info['count']})")

    if args.diff_against is not None:
        prev = args.diff_against.strip().lower()
        if not HASH_PATTERN.match(prev):
            print(
                f"ERROR: --diff-against expects a hex hash (6..64 chars); got {prev!r}",
                file=sys.stderr,
            )
            return 2
        # Compare by prefix — we accept either the full 64-char sha256 or a
        # 6+ char prefix (useful for short-hash display in markers).
        prev_len = len(prev)
        if digest[:prev_len] == prev:
            print("UNCHANGED")
        else:
            print("CHANGED")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
