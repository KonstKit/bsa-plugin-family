"""Smoke tests for .github/workflows/*.yml + .github/dependabot.yml.

v1.1.9 (Section H): CI workflows live alongside the code; if we edit them
without checking syntax, GitHub Actions silently fails the next push. These
tests assert the YAML parses + the expected jobs exist + the expected
triggers fire on the expected events. Cheap regression guard.

Stdlib-only check would be possible but pyyaml is already pulled in via
the actions/setup-python pip install pipeline; here we use the test
runner's existing pytest infra and lazy-import yaml.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
DEPENDABOT_FILE = REPO_ROOT / ".github" / "dependabot.yml"


@pytest.fixture(scope="module")
def yaml_module():
    """Lazy-import yaml. CI runs pip-installed pyyaml via test deps;
    locally pytest also picks it up if installed. If unavailable, skip."""
    return pytest.importorskip("yaml")


def _load(path: Path, yaml_mod) -> dict:
    return yaml_mod.safe_load(path.read_text(encoding="utf-8"))


# ---- ci.yml -----------------------------------------------------------


def test_ci_yml_parses(yaml_module) -> None:
    doc = _load(WORKFLOWS_DIR / "ci.yml", yaml_module)
    assert isinstance(doc, dict)
    assert doc.get("name") == "CI"


def test_ci_yml_has_required_jobs(yaml_module) -> None:
    """The CI workflow MUST run all 7 gates the operator's pre-commit
    checklist enforces locally (5 from v1.1.9 + security-audit added
    in v1.1.11 + perf-bench added in v1.1.13)."""
    doc = _load(WORKFLOWS_DIR / "ci.yml", yaml_module)
    jobs = doc.get("jobs", {})
    expected = {
        "pytest", "fixture-runner", "privacy-scan", "canon-hash",
        "marker-chain", "security-audit", "perf-bench",
    }
    actual = set(jobs.keys())
    assert expected.issubset(actual), (
        f"CI workflow missing required jobs. Expected {expected}, got {actual}."
    )


def test_ci_yml_runs_on_push_and_pr(yaml_module) -> None:
    doc = _load(WORKFLOWS_DIR / "ci.yml", yaml_module)
    # YAML "on:" key sometimes parses as boolean True; safe_load handles
    # quoted "on" correctly. Look up via the actual key name in the doc.
    on_block = doc.get("on") or doc.get(True)
    assert on_block, "ci.yml has no 'on' block"
    assert "push" in on_block
    assert "pull_request" in on_block


def test_ci_yml_pytest_matrix_covers_supported_python_versions(yaml_module) -> None:
    """The pytest matrix MUST include the floor declared in scripts/*
    shebangs (Python 3.9+)."""
    doc = _load(WORKFLOWS_DIR / "ci.yml", yaml_module)
    pytest_job = doc["jobs"]["pytest"]
    matrix = pytest_job["strategy"]["matrix"]
    versions = set(str(v) for v in matrix["python-version"])
    assert "3.9" in versions, "Python 3.9 floor MUST be in the matrix"


def test_ci_yml_concurrency_cancels_in_progress(yaml_module) -> None:
    """Saves runner minutes during rapid-fire patch lines."""
    doc = _load(WORKFLOWS_DIR / "ci.yml", yaml_module)
    concurrency = doc.get("concurrency", {})
    assert concurrency.get("cancel-in-progress") is True


# ---- release.yml -----------------------------------------------------


def test_release_yml_parses(yaml_module) -> None:
    doc = _load(WORKFLOWS_DIR / "release.yml", yaml_module)
    assert isinstance(doc, dict)
    assert doc.get("name") == "Release"


def test_release_yml_only_triggers_on_version_tags(yaml_module) -> None:
    """Codex v1.1.9 round-1 critical fix: GitHub Actions tag filters use
    GLOB syntax, not regex. Earlier draft used '[0-9]+' which silently
    never matched. We now verify with fnmatch (the same engine GitHub
    Actions uses internally) that real version tags would actually
    fire the workflow."""
    import fnmatch
    doc = _load(WORKFLOWS_DIR / "release.yml", yaml_module)
    on_block = doc.get("on") or doc.get(True)
    assert "tags" in on_block.get("push", {})
    tag_patterns = on_block["push"]["tags"]

    # Real released tags MUST match (otherwise the workflow is dead).
    must_match = ["v1.0.0", "v1.0.4", "v1.1.0", "v1.1.6", "v1.1.8", "v1.1.9", "v2.0.0", "v10.20.30"]
    for tag in must_match:
        assert any(fnmatch.fnmatch(tag, p) for p in tag_patterns), (
            f"release.yml tag-glob would NOT match real tag {tag!r}; patterns: {tag_patterns}"
        )

    # Pre-release tags MUST also match.
    must_match_prerelease = ["v1.1.0-rc1", "v2.0.0-beta3"]
    for tag in must_match_prerelease:
        assert any(fnmatch.fnmatch(tag, p) for p in tag_patterns), (
            f"release.yml tag-glob would NOT match prerelease tag {tag!r}; patterns: {tag_patterns}"
        )

    # Non-version tags MUST NOT match (avoids accidental release runs
    # for branch-marker / phase-marker tags).
    must_not_match = ["phase-3-baseline", "snapshot", "main", "stage-final"]
    for tag in must_not_match:
        assert not any(fnmatch.fnmatch(tag, p) for p in tag_patterns), (
            f"release.yml tag-glob falsely matches non-version tag {tag!r}; patterns: {tag_patterns}"
        )


def test_release_yml_action_versions_current(yaml_module) -> None:
    """Codex v1.1.9 round-1 should-fix: spot-check that workflow steps
    don't use deprecated action majors. Today the deprecated set is
    actions/checkout@v1..@v3 and actions/upload-artifact@v1..@v3."""
    deprecated_actions = {
        "actions/checkout@v1", "actions/checkout@v2", "actions/checkout@v3",
        "actions/setup-python@v1", "actions/setup-python@v2", "actions/setup-python@v3", "actions/setup-python@v4",
        "actions/upload-artifact@v1", "actions/upload-artifact@v2", "actions/upload-artifact@v3",
    }
    for wf_name in ("ci.yml", "release.yml"):
        doc = _load(WORKFLOWS_DIR / wf_name, yaml_module)
        for job_name, job in doc.get("jobs", {}).items():
            for step in job.get("steps", []):
                uses = step.get("uses", "")
                assert uses not in deprecated_actions, (
                    f"{wf_name}::{job_name} uses deprecated action {uses!r}"
                )


def test_release_yml_validates_changelog_entry(yaml_module) -> None:
    """The release workflow MUST verify the tag has a CHANGELOG entry —
    catches the case where a maintainer tags a release but forgets to
    update CHANGELOG.md."""
    doc = _load(WORKFLOWS_DIR / "release.yml", yaml_module)
    job = doc["jobs"]["validate-tag"]
    steps = job["steps"]
    step_names = [s.get("name", "") for s in steps]
    assert any("CHANGELOG" in n for n in step_names), (
        f"release.yml has no CHANGELOG-verification step. Steps: {step_names}"
    )


def test_release_yml_validates_canon_hash_and_manifest(yaml_module) -> None:
    """The release workflow MUST gate on canon-hash drift + manifest
    invariants (test_manifest_canon_hash_matches_current_script_output +
    test_manifest_version_and_canon_semver_agree are the equivalent
    pytest invariants)."""
    doc = _load(WORKFLOWS_DIR / "release.yml", yaml_module)
    job = doc["jobs"]["validate-tag"]
    steps = job["steps"]
    step_names = [s.get("name", "") for s in steps]
    assert any("canon hash" in n.lower() or "manifest" in n.lower() for n in step_names), (
        f"release.yml has no canon-hash/manifest verification step. Steps: {step_names}"
    )


def test_release_yml_uploads_release_artifact(yaml_module) -> None:
    """The release workflow MUST produce a downloadable artifact so the
    operator can attach it to a GitHub Release page."""
    doc = _load(WORKFLOWS_DIR / "release.yml", yaml_module)
    job = doc["jobs"]["validate-tag"]
    steps = job["steps"]
    uses = [s.get("uses", "") for s in steps]
    assert any("upload-artifact" in u for u in uses), (
        f"release.yml has no upload-artifact step. Steps: {uses}"
    )


# ---- dependabot.yml --------------------------------------------------


def test_dependabot_yml_parses(yaml_module) -> None:
    doc = _load(DEPENDABOT_FILE, yaml_module)
    assert isinstance(doc, dict)
    assert doc.get("version") == 2


def test_dependabot_covers_pip_and_actions(yaml_module) -> None:
    """Dependabot MUST track both pip (requirements-dev.txt) AND
    github-actions (workflow uses: action@vN) so neither drifts onto
    a deprecated version unnoticed."""
    doc = _load(DEPENDABOT_FILE, yaml_module)
    updates = doc.get("updates", [])
    ecosystems = {u["package-ecosystem"] for u in updates}
    assert "pip" in ecosystems
    assert "github-actions" in ecosystems
