"""Unit tests for scripts/validate_request_skill_routing.py (US-S05-02).

Covers the 4 acceptance criteria:
  AC-1: config/request_skill_routes.json contains >= 2 request types with
        full worker sets matching bsa-orchestrator/SKILL.md:37-66
  AC-2: jsonschema validation — schema file is parseable JSON and routing
        JSON conforms (shape + ident patterns)
  AC-3: validator checks: (a) schema conformance, (b) every referenced skill
        exists under skills/<name>/SKILL.md, (c) every route includes
        orchestrator + >= 1 worker
  AC-4: CI integration failure behaviour — invalid routing causes exit 1
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "validate_request_skill_routing.py"
DEFAULT_ROUTING = REPO_ROOT / "config" / "request_skill_routes.json"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "request_skill_routes.schema.json"


def run_validator(routing: Path, skills_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), f"--routing={routing}", f"--skills-dir={skills_dir}"],
        capture_output=True,
        text=True,
        check=False,
    )


def write_routing(path: Path, content: dict) -> None:
    path.write_text(json.dumps(content, indent=2), encoding="utf-8")


def make_skills_dir(tmp_path: Path, names: list[str]) -> Path:
    skills = tmp_path / "skills"
    skills.mkdir()
    for n in names:
        d = skills / n
        d.mkdir()
        (d / "SKILL.md").write_text(f"---\nname: {n}\ndescription: test fixture.\n---\n", encoding="utf-8")
    return skills


MIN_VALID_ROUTING = {
    "schema_version": 1,
    "canon_policy_version": "0.9",
    "routes": [
        {
            "request_type": "unit_test_route",
            "description": "Minimal valid route for tests (>10 chars).",
            "worker_set": ["bsa-orchestrator", "bsa-evidence-intake"],
        }
    ],
}


def test_ac1_repo_manifest_has_two_request_types() -> None:
    """AC-1: real manifest has >= 2 request types with full worker sets."""
    data = json.loads(DEFAULT_ROUTING.read_text(encoding="utf-8"))
    request_types = [r["request_type"] for r in data["routes"]]
    assert "bsa_pack_direct_mixed_sources" in request_types
    assert "discovery_pack_mixed_sources" in request_types
    assert len(request_types) >= 2


def test_ac1_direct_pack_worker_set_matches_spec() -> None:
    """AC-1: bsa_pack_direct_mixed_sources worker_set matches bsa-orchestrator/SKILL.md.

    Sprint 1 US-S1-01 added `bsa-context-framer` as Stage 2 owner between
    claim-binder and semantic-extractor. Expected set is the Phase-0
    14 skills PLUS bsa-context-framer.
    """
    data = json.loads(DEFAULT_ROUTING.read_text(encoding="utf-8"))
    direct = next(r for r in data["routes"] if r["request_type"] == "bsa_pack_direct_mixed_sources")
    expected = {
        "bsa-orchestrator", "bsa-evidence-intake", "bsa-claim-binder",
        "bsa-context-framer",
        "bsa-semantic-extractor", "bsa-domain-modeler", "bsa-backbone-builder",
        "bsa-anchor-auditor", "bsa-contract-builder", "bsa-citation-auditor",
        "bsa-consistency-auditor", "bsa-skeptical-reviewer", "bsa-no-new-facts-auditor",
        "bsa-validation-readiness", "bsa-handoff-packager",
    }
    assert set(direct["worker_set"]) == expected


def test_ac1_discovery_pack_worker_set_matches_spec() -> None:
    data = json.loads(DEFAULT_ROUTING.read_text(encoding="utf-8"))
    disc = next(r for r in data["routes"] if r["request_type"] == "discovery_pack_mixed_sources")
    expected = {
        "bsa-orchestrator", "d0-problem-framer", "d0-context-researcher",
        "d0-hypothesis-prioritizer", "d0-feasibility-assessor",
        "d0-synthesis-gatekeeper", "bsa-citation-auditor",
        "bsa-skeptical-reviewer", "bsa-no-new-facts-auditor",
    }
    assert set(disc["worker_set"]) == expected


def test_ac2_schema_is_valid_json() -> None:
    """AC-2: schema file is itself parseable and declares a Draft 2020-12 schema."""
    schema = json.loads(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert "routes" in schema["properties"]


def test_ac2_and_ac3_baseline_repo_routing_passes() -> None:
    """AC-2/AC-3 baseline: committed manifest validates cleanly against real skills/."""
    result = run_validator(DEFAULT_ROUTING, REPO_ROOT / "skills")
    assert result.returncode == 0, f"baseline routing failed:\n{result.stderr}"
    assert "Routing OK" in result.stdout


def test_ac3_missing_skill_detected(tmp_path: Path) -> None:
    """AC-3: referencing a skill that does not exist under skills/ fails with exit 1."""
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator", "bsa-evidence-intake"])
    routing = tmp_path / "routing.json"
    write_routing(routing, {
        "schema_version": 1,
        "canon_policy_version": "0.9",
        "routes": [{
            "request_type": "phantom_route",
            "description": "References a missing skill to trigger the detector.",
            "worker_set": ["bsa-orchestrator", "bsa-doesnt-exist"],
        }],
    })
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "missing-skill" in result.stderr
    assert "bsa-doesnt-exist" in result.stderr


def test_ac3_missing_orchestrator_detected(tmp_path: Path) -> None:
    """AC-3: worker_set without bsa-orchestrator must fail."""
    skills = make_skills_dir(tmp_path, ["bsa-evidence-intake"])
    routing = tmp_path / "routing.json"
    write_routing(routing, {
        "schema_version": 1,
        "canon_policy_version": "0.9",
        "routes": [{
            "request_type": "no_orchestrator_route",
            "description": "Route missing the mandatory orchestrator skill.",
            "worker_set": ["bsa-evidence-intake"],
        }],
    })
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "missing-orchestrator" in result.stderr


def test_duplicate_request_type_detected(tmp_path: Path) -> None:
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator", "bsa-evidence-intake"])
    routing = tmp_path / "routing.json"
    write_routing(routing, {
        "schema_version": 1,
        "canon_policy_version": "0.9",
        "routes": [
            {"request_type": "dup_route", "description": "First copy of the duplicate.", "worker_set": ["bsa-orchestrator", "bsa-evidence-intake"]},
            {"request_type": "dup_route", "description": "Second copy of the duplicate.", "worker_set": ["bsa-orchestrator", "bsa-evidence-intake"]},
        ],
    })
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "duplicate-request-type" in result.stderr


def test_duplicate_worker_in_set_detected(tmp_path: Path) -> None:
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator", "bsa-evidence-intake"])
    routing = tmp_path / "routing.json"
    write_routing(routing, {
        "schema_version": 1,
        "canon_policy_version": "0.9",
        "routes": [{
            "request_type": "dup_worker_route",
            "description": "Worker_set with a duplicate entry.",
            "worker_set": ["bsa-orchestrator", "bsa-orchestrator", "bsa-evidence-intake"],
        }],
    })
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "route-worker-duplicate" in result.stderr


def test_invalid_request_type_pattern_detected(tmp_path: Path) -> None:
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator"])
    routing = tmp_path / "routing.json"
    write_routing(routing, {
        "schema_version": 1,
        "canon_policy_version": "0.9",
        "routes": [{
            "request_type": "BadCase-request",
            "description": "Capitals and dashes are not allowed.",
            "worker_set": ["bsa-orchestrator"],
        }],
    })
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "route-request-type" in result.stderr


def test_invalid_json_returns_exit_2(tmp_path: Path) -> None:
    """AC-4 edge case: invalid JSON is an invocation error (exit 2), not a finding."""
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator"])
    routing = tmp_path / "routing.json"
    routing.write_text("{not valid json", encoding="utf-8")
    result = run_validator(routing, skills)
    assert result.returncode == 2
    assert "invalid JSON" in result.stderr


def test_missing_routing_file_returns_exit_2(tmp_path: Path) -> None:
    result = run_validator(tmp_path / "nope.json", tmp_path / "skills")
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_min_valid_routing_accepted(tmp_path: Path) -> None:
    """Smoke: minimal well-formed routing passes when skills exist."""
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator", "bsa-evidence-intake"])
    routing = tmp_path / "routing.json"
    write_routing(routing, MIN_VALID_ROUTING)
    result = run_validator(routing, skills)
    assert result.returncode == 0
    assert "Routing OK" in result.stdout


def test_non_string_worker_does_not_crash(tmp_path: Path) -> None:
    """Round-2 codex: dict/list items in worker_set must surface as findings, not TypeError."""
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator", "bsa-evidence-intake"])
    routing = tmp_path / "routing.json"
    routing.write_text(
        json.dumps({
            "schema_version": 1,
            "canon_policy_version": "0.9",
            "routes": [{
                "request_type": "bad_worker_type_route",
                "description": "worker_set contains a non-string entry (should not crash validator).",
                "worker_set": ["bsa-orchestrator", {"nested": "dict"}, ["list-entry"]],
            }],
        }),
        encoding="utf-8",
    )
    result = run_validator(routing, skills)
    assert result.returncode == 1, result.stderr
    assert "route-worker-name" in result.stderr
    assert "Traceback" not in result.stderr


def test_boolean_schema_version_rejected(tmp_path: Path) -> None:
    """Round-2 codex: True/False must not satisfy the integer check for schema_version."""
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator"])
    routing = tmp_path / "routing.json"
    routing.write_text(
        json.dumps({
            "schema_version": True,
            "canon_policy_version": "0.9",
            "routes": [{
                "request_type": "bool_sv_route",
                "description": "schema_version=true must be rejected as non-integer.",
                "worker_set": ["bsa-orchestrator"],
            }],
        }),
        encoding="utf-8",
    )
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "schema_version" in result.stderr


def test_canon_policy_version_pattern_enforced(tmp_path: Path) -> None:
    """Round-2 codex: canon_policy_version shape must match schema regex, not just type."""
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator"])
    routing = tmp_path / "routing.json"
    routing.write_text(
        json.dumps({
            "schema_version": 1,
            "canon_policy_version": "not-a-version",
            "routes": [{
                "request_type": "bad_version_route",
                "description": "canon_policy_version fails the shape regex.",
                "worker_set": ["bsa-orchestrator"],
            }],
        }),
        encoding="utf-8",
    )
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "canon_policy_version" in result.stderr


def test_unknown_top_level_key_detected(tmp_path: Path) -> None:
    """Round-2 minor: align with schema's additionalProperties=false."""
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator"])
    routing = tmp_path / "routing.json"
    routing.write_text(
        json.dumps({
            "schema_version": 1,
            "canon_policy_version": "0.9",
            "routes": [{
                "request_type": "ok_route",
                "description": "Well-formed route for unknown-key test.",
                "worker_set": ["bsa-orchestrator"],
            }],
            "surprise_key": "extra",
        }),
        encoding="utf-8",
    )
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "surprise_key" in result.stderr


def test_unknown_route_key_detected(tmp_path: Path) -> None:
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator"])
    routing = tmp_path / "routing.json"
    routing.write_text(
        json.dumps({
            "schema_version": 1,
            "canon_policy_version": "0.9",
            "routes": [{
                "request_type": "extra_field_route",
                "description": "Route with an unexpected extra field.",
                "worker_set": ["bsa-orchestrator"],
                "extra_route_prop": "foo",
            }],
        }),
        encoding="utf-8",
    )
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "extra_route_prop" in result.stderr


def test_unknown_conditional_worker_key_detected(tmp_path: Path) -> None:
    """Round-3 codex: conditional_workers[] must enforce additionalProperties=false."""
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator", "bsa-evidence-intake"])
    routing = tmp_path / "routing.json"
    write_routing(routing, {
        "schema_version": 1,
        "canon_policy_version": "0.9",
        "routes": [{
            "request_type": "cond_extra_route",
            "description": "Route with extra key in conditional_workers entry.",
            "worker_set": ["bsa-orchestrator"],
            "conditional_workers": [{
                "worker": "bsa-evidence-intake",
                "trigger": "mixed-source inventory required",
                "extra_cond_prop": "foo",
            }],
        }],
    })
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "route-cond-unknown-key" in result.stderr
    assert "extra_cond_prop" in result.stderr


def test_unknown_sidecar_key_detected(tmp_path: Path) -> None:
    """Round-3 codex: sidecars[] must enforce additionalProperties=false."""
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator", "c4-plantuml-from-context"])
    routing = tmp_path / "routing.json"
    write_routing(routing, {
        "schema_version": 1,
        "canon_policy_version": "0.9",
        "routes": [{
            "request_type": "side_extra_route",
            "description": "Route paired with sidecar carrying an unknown key.",
            "worker_set": ["bsa-orchestrator"],
        }],
        "sidecars": [{
            "skill": "c4-plantuml-from-context",
            "policy": "derived-only; test policy text",
            "extra_sidecar_prop": "bar",
        }],
    })
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "sidecar-unknown-key" in result.stderr
    assert "extra_sidecar_prop" in result.stderr


def test_non_string_dollar_schema_rejected(tmp_path: Path) -> None:
    """Round-4 codex: $schema must be string per schema parity."""
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator"])
    routing = tmp_path / "routing.json"
    write_routing(routing, {
        "$schema": 123,
        "schema_version": 1,
        "canon_policy_version": "0.9",
        "routes": [{
            "request_type": "bad_schema_field_route",
            "description": "Well-formed route for the schema-field check.",
            "worker_set": ["bsa-orchestrator"],
        }],
    })
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "$schema" in result.stderr


def test_non_string_description_field_rejected(tmp_path: Path) -> None:
    """Round-4 codex: _description metadata field must be string."""
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator"])
    routing = tmp_path / "routing.json"
    write_routing(routing, {
        "_description": {"bad": "should be string"},
        "schema_version": 1,
        "canon_policy_version": "0.9",
        "routes": [{
            "request_type": "bad_desc_field_route",
            "description": "Well-formed route for the _description parity test.",
            "worker_set": ["bsa-orchestrator"],
        }],
    })
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "_description" in result.stderr


def test_non_list_runtime_notes_rejected(tmp_path: Path) -> None:
    """Round-4 codex: runtime_notes must be array of strings."""
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator"])
    routing = tmp_path / "routing.json"
    write_routing(routing, {
        "schema_version": 1,
        "canon_policy_version": "0.9",
        "routes": [{
            "request_type": "bad_runtime_notes_route",
            "description": "Route with runtime_notes of the wrong shape.",
            "worker_set": ["bsa-orchestrator"],
            "runtime_notes": "not-a-list",
        }],
    })
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "route-runtime-notes" in result.stderr


def test_non_string_runtime_note_item_rejected(tmp_path: Path) -> None:
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator"])
    routing = tmp_path / "routing.json"
    write_routing(routing, {
        "schema_version": 1,
        "canon_policy_version": "0.9",
        "routes": [{
            "request_type": "bad_runtime_item_route",
            "description": "runtime_notes contains a non-string entry.",
            "worker_set": ["bsa-orchestrator"],
            "runtime_notes": ["ok line", 42],
        }],
    })
    result = run_validator(routing, skills)
    assert result.returncode == 1
    assert "route-runtime-notes" in result.stderr
    assert "runtime_notes[1]" in result.stderr


def test_canon_policy_version_hash_accepted(tmp_path: Path) -> None:
    """Sprint 3 US-S3-04 will append +hash:<sha>; schema pattern accepts it now."""
    skills = make_skills_dir(tmp_path, ["bsa-orchestrator", "bsa-evidence-intake"])
    routing = tmp_path / "routing.json"
    write_routing(routing, {
        "schema_version": 1,
        "canon_policy_version": "1.0.0+hash:abc123def",
        "routes": [{
            "request_type": "hash_versioned_route",
            "description": "CanonPolicyVersion with policy-state hash suffix.",
            "worker_set": ["bsa-orchestrator", "bsa-evidence-intake"],
        }],
    })
    result = run_validator(routing, skills)
    assert result.returncode == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
