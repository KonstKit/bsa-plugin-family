"""Tests for .claude-plugin/plugin.json (US-S4-01).

Locks the manifest shape and enforces the invariant that the declared
canonPolicyVersion.hash_full matches what ``scripts/compute_canon_hash.py``
produces against the current repo. Any policy-file edit that changes
the hash MUST also update the manifest (the release workflow also
enforces this at tag-push time, but tests catch it pre-push).

Stdlib-only.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
HASH_SCRIPT = REPO_ROOT / "scripts" / "compute_canon_hash.py"


def _load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_parses_as_json() -> None:
    _load_manifest()


def test_manifest_has_required_name_field() -> None:
    data = _load_manifest()
    assert data.get("name") == "bsa-full"


def test_manifest_version_is_semver() -> None:
    """plugin.json version MUST be a semver string (with optional pre-release suffix)."""
    data = _load_manifest()
    version = data.get("version", "")
    # Accept 1.0.0 and 1.0.0-rc1 forms; reject anything weirder.
    assert re.match(
        r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$", version
    ), f"plugin.json version {version!r} is not a well-formed semver"


def test_manifest_has_mit_license() -> None:
    """License SHOULD match the committed LICENSE file; MIT is what Sprint 0 committed."""
    data = _load_manifest()
    assert data.get("license") == "MIT"


def test_manifest_has_keywords_array() -> None:
    data = _load_manifest()
    keywords = data.get("keywords")
    assert isinstance(keywords, list) and len(keywords) >= 3


def test_manifest_canon_policy_version_shape() -> None:
    """The custom canonPolicyVersion block has the fields the release
    workflow (and human reviewers) expect."""
    data = _load_manifest()
    cpv = data.get("canonPolicyVersion")
    assert isinstance(cpv, dict), "canonPolicyVersion must be an object"
    for key in ("semver", "hash_prefix", "hash_full", "computed_by", "computed_at"):
        assert key in cpv, f"canonPolicyVersion missing required key: {key}"
    assert re.match(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$", cpv["semver"])
    assert re.match(r"^[a-f0-9]{6,64}$", cpv["hash_prefix"])
    assert re.match(r"^[a-f0-9]{64}$", cpv["hash_full"])
    # hash_prefix must be a leading substring of hash_full — the "prefix"
    # is redundant if it doesn't match.
    assert cpv["hash_full"].startswith(cpv["hash_prefix"])


def test_manifest_canon_hash_matches_current_script_output() -> None:
    """The release workflow recomputes and hard-fails on mismatch; this
    test catches the drift pre-push. If this test fails, update
    plugin.json canonPolicyVersion.hash_full + hash_prefix to the
    current value (see scripts/compute_canon_hash.py)."""
    result = subprocess.run(
        [sys.executable, str(HASH_SCRIPT)],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    current_hash = result.stdout.strip().split("\n")[0]
    declared_hash = _load_manifest()["canonPolicyVersion"]["hash_full"]
    assert current_hash == declared_hash, (
        f"canon hash drift: plugin.json declares {declared_hash} but "
        f"compute_canon_hash.py returns {current_hash}. Update the manifest."
    )


def test_manifest_version_and_canon_semver_agree() -> None:
    """Top-level version and canonPolicyVersion.semver must be identical."""
    data = _load_manifest()
    assert data["version"] == data["canonPolicyVersion"]["semver"]


def test_manifest_author_has_name() -> None:
    data = _load_manifest()
    author = data.get("author", {})
    assert isinstance(author, dict)
    assert author.get("name"), "author.name must be set"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
