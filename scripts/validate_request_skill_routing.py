#!/usr/bin/env python3
"""Validator for config/request_skill_routes.json (US-S05-02).

Checks:
  1. JSON is parseable and conforms to request_skill_routes.schema.json
     (minimal jsonschema-like validation; no external deps).
  2. Every skill referenced from any worker_set, conditional_workers,
     or sidecars block exists under skills/<name>/SKILL.md.
  3. Every route has at least one worker AND orchestrator skill in the
     worker_set.
  4. No duplicate request_type values across routes.
  5. No duplicate sidecar skill entries.

Usage:
  scripts/validate_request_skill_routing.py [--routing=<path>] [--skills-dir=<path>]

Exit codes:
  0 — manifest valid
  1 — at least one semantic finding (missing skill, missing orchestrator, duplicate route, etc.)
  2 — invocation error (file missing, invalid JSON, schema violation, bad CLI args)

Stdlib-only. Schema validation is minimal but enforces the properties
that matter most (required fields, unique worker sets, identifier
patterns). For richer schema coverage, run `jsonschema` externally.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


IDENT_RE = re.compile(r"^[a-z][a-z0-9-]*$")
REQUEST_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# Mirrors config/request_skill_routes.schema.json "canon_policy_version" pattern.
CANON_POLICY_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:\+hash:[A-Za-z0-9]+)?$")
ORCHESTRATOR_SKILL = "bsa-orchestrator"

KNOWN_TOP_LEVEL_KEYS = frozenset({
    "$schema", "_description",
    "schema_version", "canon_policy_version", "routes", "sidecars",
})
KNOWN_ROUTE_KEYS = frozenset({
    "request_type", "description", "worker_set",
    "conditional_workers", "runtime_notes",
})
KNOWN_COND_KEYS = frozenset({"worker", "trigger"})
KNOWN_SIDECAR_KEYS = frozenset({"skill", "policy"})


@dataclass
class Finding:
    code: str
    message: str


def _check_minimal_schema(data: object, path: Path) -> list[Finding]:
    """Minimal shape validation — the parts enforced in CI without jsonschema dep."""
    findings: list[Finding] = []

    if not isinstance(data, dict):
        findings.append(Finding("schema", f"{path}: top-level JSON must be an object"))
        return findings

    for required in ("schema_version", "canon_policy_version", "routes"):
        if required not in data:
            findings.append(Finding("schema", f"{path}: missing required key '{required}'"))

    sv = data.get("schema_version")
    # Reject booleans explicitly — bool is a subclass of int in Python,
    # so a plain isinstance(sv, int) check would accept True/False.
    if sv is not None and (isinstance(sv, bool) or not isinstance(sv, int) or sv < 1):
        findings.append(Finding("schema", f"{path}: 'schema_version' must be positive int, got {sv!r}"))

    cpv = data.get("canon_policy_version")
    if cpv is not None:
        if not isinstance(cpv, str):
            findings.append(Finding(
                "schema",
                f"{path}: 'canon_policy_version' must be string, got {type(cpv).__name__}",
            ))
        elif not CANON_POLICY_VERSION_RE.match(cpv):
            findings.append(Finding(
                "schema",
                f"{path}: 'canon_policy_version' must match {CANON_POLICY_VERSION_RE.pattern}, got {cpv!r}",
            ))

    routes = data.get("routes")
    if routes is not None and not isinstance(routes, list):
        findings.append(Finding("schema", f"{path}: 'routes' must be an array"))
    elif isinstance(routes, list) and not routes:
        findings.append(Finding("schema", f"{path}: 'routes' must contain at least one entry"))

    sidecars = data.get("sidecars")
    if sidecars is not None and not isinstance(sidecars, list):
        findings.append(Finding("schema", f"{path}: 'sidecars' must be an array"))

    # Schema declares $schema and _description as strings; enforce here.
    for str_field in ("$schema", "_description"):
        if str_field in data and not isinstance(data[str_field], str):
            findings.append(Finding(
                "schema",
                f"{path}: '{str_field}' must be a string, got {type(data[str_field]).__name__}",
            ))

    unknown_keys = sorted(set(data.keys()) - KNOWN_TOP_LEVEL_KEYS)
    for key in unknown_keys:
        findings.append(Finding("schema", f"{path}: unknown top-level key '{key}'"))

    return findings


def _check_route(route: object, index: int) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(route, dict):
        findings.append(Finding("route-shape", f"routes[{index}]: must be an object"))
        return findings

    rt = route.get("request_type")
    if not isinstance(rt, str) or not REQUEST_TYPE_RE.match(rt):
        findings.append(Finding(
            "route-request-type",
            f"routes[{index}]: 'request_type' must match {REQUEST_TYPE_RE.pattern}, got {rt!r}",
        ))

    desc = route.get("description")
    if not isinstance(desc, str) or len(desc) < 10:
        findings.append(Finding(
            "route-description",
            f"routes[{index}]: 'description' must be a non-trivial string (>=10 chars)",
        ))

    workers = route.get("worker_set")
    if not isinstance(workers, list) or not workers:
        findings.append(Finding(
            "route-worker-set",
            f"routes[{index}]: 'worker_set' must be a non-empty array",
        ))
    else:
        # First verify every item is a well-formed skill-name string; only
        # then run duplicate detection. Doing set(workers) before this
        # check would raise TypeError on dict/list items, breaking the
        # validator's 0/1/2 exit-code contract.
        all_strings = True
        for j, w in enumerate(workers):
            if not isinstance(w, str) or not IDENT_RE.match(w):
                findings.append(Finding(
                    "route-worker-name",
                    f"routes[{index}].worker_set[{j}]: must match {IDENT_RE.pattern}, got {w!r}",
                ))
                all_strings = False
        if all_strings and len(set(workers)) != len(workers):
            findings.append(Finding(
                "route-worker-duplicate",
                f"routes[{index}]: 'worker_set' contains duplicates",
            ))

    unknown_route_keys = sorted(set(route.keys()) - KNOWN_ROUTE_KEYS)
    for key in unknown_route_keys:
        findings.append(Finding(
            "route-unknown-key",
            f"routes[{index}]: unknown key '{key}'",
        ))

    runtime_notes = route.get("runtime_notes")
    if runtime_notes is not None:
        if not isinstance(runtime_notes, list):
            findings.append(Finding(
                "route-runtime-notes",
                f"routes[{index}]: 'runtime_notes' must be an array of strings",
            ))
        else:
            for n, note in enumerate(runtime_notes):
                if not isinstance(note, str):
                    findings.append(Finding(
                        "route-runtime-notes",
                        f"routes[{index}].runtime_notes[{n}]: must be a string, "
                        f"got {type(note).__name__}",
                    ))

    cond = route.get("conditional_workers")
    if cond is not None:
        if not isinstance(cond, list):
            findings.append(Finding(
                "route-cond-shape",
                f"routes[{index}]: 'conditional_workers' must be an array",
            ))
        else:
            for k, entry in enumerate(cond):
                if not isinstance(entry, dict):
                    findings.append(Finding(
                        "route-cond-entry",
                        f"routes[{index}].conditional_workers[{k}]: must be an object",
                    ))
                    continue
                wname = entry.get("worker")
                trigger = entry.get("trigger")
                if not isinstance(wname, str) or not IDENT_RE.match(wname):
                    findings.append(Finding(
                        "route-cond-worker",
                        f"routes[{index}].conditional_workers[{k}].worker: must match {IDENT_RE.pattern}",
                    ))
                if not isinstance(trigger, str) or len(trigger) < 10:
                    findings.append(Finding(
                        "route-cond-trigger",
                        f"routes[{index}].conditional_workers[{k}].trigger: must be non-trivial string",
                    ))
                unknown_cond_keys = sorted(set(entry.keys()) - KNOWN_COND_KEYS)
                for key in unknown_cond_keys:
                    findings.append(Finding(
                        "route-cond-unknown-key",
                        f"routes[{index}].conditional_workers[{k}]: unknown key '{key}'",
                    ))

    return findings


def _collect_referenced_skills(data: dict) -> set[str]:
    refs: set[str] = set()
    for route in data.get("routes", []) or []:
        if not isinstance(route, dict):
            continue
        workers = route.get("worker_set") or []
        if isinstance(workers, list):
            refs.update(w for w in workers if isinstance(w, str))
        cond = route.get("conditional_workers") or []
        if isinstance(cond, list):
            for entry in cond:
                if isinstance(entry, dict) and isinstance(entry.get("worker"), str):
                    refs.add(entry["worker"])
    for side in data.get("sidecars", []) or []:
        if isinstance(side, dict) and isinstance(side.get("skill"), str):
            refs.add(side["skill"])
    return refs


def validate(routing_path: Path, skills_dir: Path) -> list[Finding]:
    findings: list[Finding] = []

    if not routing_path.is_file():
        return [Finding("invocation", f"routing file not found: {routing_path}")]
    if not skills_dir.is_dir():
        return [Finding("invocation", f"skills directory not found: {skills_dir}")]

    try:
        data = json.loads(routing_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [Finding("invocation", f"{routing_path}: invalid JSON: {exc}")]

    findings.extend(_check_minimal_schema(data, routing_path))
    if any(f.code == "schema" for f in findings):
        # If the shape is broken, stop before per-route checks.
        return findings

    routes = data.get("routes", []) or []
    seen_types: dict[str, int] = {}
    for i, route in enumerate(routes):
        findings.extend(_check_route(route, i))
        if isinstance(route, dict):
            rt = route.get("request_type")
            if isinstance(rt, str):
                if rt in seen_types:
                    findings.append(Finding(
                        "duplicate-request-type",
                        f"routes[{i}]: duplicate request_type '{rt}' (already at routes[{seen_types[rt]}])",
                    ))
                else:
                    seen_types[rt] = i

    # Orchestrator-presence check. Only consult worker_set when it is a
    # list of strings — malformed shapes are already reported above and
    # `ORCHESTRATOR_SKILL not in workers` must not crash on non-str entries.
    for i, route in enumerate(routes):
        if not isinstance(route, dict):
            continue
        workers = route.get("worker_set")
        if not isinstance(workers, list):
            continue
        str_workers = [w for w in workers if isinstance(w, str)]
        if ORCHESTRATOR_SKILL not in str_workers:
            findings.append(Finding(
                "missing-orchestrator",
                f"routes[{i}] ('{route.get('request_type', '?')}'): worker_set must include '{ORCHESTRATOR_SKILL}'",
            ))

    # Sidecar uniqueness
    sidecars = data.get("sidecars") or []
    seen_sidecars: set[str] = set()
    if isinstance(sidecars, list):
        for i, side in enumerate(sidecars):
            if not isinstance(side, dict):
                findings.append(Finding(
                    "sidecar-shape",
                    f"sidecars[{i}]: must be an object",
                ))
                continue
            skill = side.get("skill")
            policy = side.get("policy")
            if not isinstance(skill, str) or not IDENT_RE.match(skill):
                findings.append(Finding(
                    "sidecar-skill",
                    f"sidecars[{i}].skill: must match {IDENT_RE.pattern}, got {skill!r}",
                ))
            elif skill in seen_sidecars:
                findings.append(Finding(
                    "sidecar-duplicate",
                    f"sidecars[{i}]: duplicate sidecar skill '{skill}'",
                ))
            else:
                seen_sidecars.add(skill)
            if not isinstance(policy, str) or len(policy) < 10:
                findings.append(Finding(
                    "sidecar-policy",
                    f"sidecars[{i}].policy: must be non-trivial string",
                ))
            unknown_sidecar_keys = sorted(set(side.keys()) - KNOWN_SIDECAR_KEYS)
            for key in unknown_sidecar_keys:
                findings.append(Finding(
                    "sidecar-unknown-key",
                    f"sidecars[{i}]: unknown key '{key}'",
                ))

    # Existence of referenced skills
    referenced = _collect_referenced_skills(data)
    existing = {p.name for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()}
    for skill in sorted(referenced):
        if skill not in existing:
            findings.append(Finding(
                "missing-skill",
                f"referenced skill '{skill}' has no skills/{skill}/SKILL.md",
            ))

    return findings


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Validate request-skill routing manifest (US-S05-02).")
    parser.add_argument(
        "--routing",
        type=Path,
        default=repo_root / "config" / "request_skill_routes.json",
        help="Path to routing manifest JSON.",
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=repo_root / "skills",
        help="Root skills directory.",
    )
    args = parser.parse_args(argv)

    findings = validate(args.routing, args.skills_dir)

    invocation_issues = [f for f in findings if f.code == "invocation"]
    if invocation_issues:
        for f in invocation_issues:
            print(f"ERROR: {f.message}", file=sys.stderr)
        return 2

    if not findings:
        print(f"Routing OK: {args.routing}")
        return 0

    print(f"Routing findings ({len(findings)}) in {args.routing}:", file=sys.stderr)
    for f in findings:
        print(f"  [{f.code}] {f.message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
