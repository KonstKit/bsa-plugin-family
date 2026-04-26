"""Tests for .claude-plugin/plugin.json (US-S4-01) + .claude-plugin/canon_policy.json (v1.3.6).

Locks the manifest shape and enforces the invariant that the declared
canon_policy.json hash_full matches what ``scripts/compute_canon_hash.py``
produces against the current repo. Any policy-file edit that changes
the hash MUST also update the canon_policy.json (the release workflow
also enforces this at tag-push time, but tests catch it pre-push).

v1.3.6 split: the `canonPolicyVersion` block was extracted from
`plugin.json` into a sibling file `.claude-plugin/canon_policy.json`
because Claude Code v2.1.19's plugin install schema rejects unknown
top-level keys in plugin.json (`bugs`, `canonPolicyVersion`, and
object-form `repository` were all rejected). plugin.json now contains
ONLY Claude-Code-schema-valid fields.

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
CANON_POLICY = REPO_ROOT / ".claude-plugin" / "canon_policy.json"
HASH_SCRIPT = REPO_ROOT / "scripts" / "compute_canon_hash.py"


def _load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _load_canon_policy() -> dict:
    """v1.3.6: canon-policy block lives in a separate file."""
    return json.loads(CANON_POLICY.read_text(encoding="utf-8"))


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


def test_canon_policy_file_present() -> None:
    """v1.3.6: canon-policy block was moved out of plugin.json into a
    separate file because Claude Code v2.1.19 plugin install schema
    rejects unknown top-level keys in plugin.json."""
    assert CANON_POLICY.is_file(), (
        f"canon-policy file missing at {CANON_POLICY} — v1.3.6 split "
        f"requires this sibling file"
    )


def test_canon_policy_version_shape() -> None:
    """The canon-policy block has the fields the release workflow + 3
    contract exporters + dashboard expect. v1.3.6: read from
    canon_policy.json (was plugin.json::canonPolicyVersion)."""
    cpv = _load_canon_policy()
    assert isinstance(cpv, dict), "canon_policy.json must be an object"
    for key in ("semver", "hash_prefix", "hash_full", "computed_by", "computed_at"):
        assert key in cpv, f"canon_policy.json missing required key: {key}"
    assert re.match(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$", cpv["semver"])
    assert re.match(r"^[a-f0-9]{6,64}$", cpv["hash_prefix"])
    assert re.match(r"^[a-f0-9]{64}$", cpv["hash_full"])
    assert cpv["hash_full"].startswith(cpv["hash_prefix"])


def test_manifest_canon_hash_matches_current_script_output() -> None:
    """The release workflow recomputes and hard-fails on mismatch; this
    test catches the drift pre-push. If this test fails, update
    canon_policy.json hash_full + hash_prefix to the current value
    (see scripts/compute_canon_hash.py). v1.3.6: declared hash now
    lives in canon_policy.json (was plugin.json::canonPolicyVersion)."""
    result = subprocess.run(
        [sys.executable, str(HASH_SCRIPT)],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    current_hash = result.stdout.strip().split("\n")[0]
    declared_hash = _load_canon_policy()["hash_full"]
    assert current_hash == declared_hash, (
        f"canon hash drift: canon_policy.json declares {declared_hash} but "
        f"compute_canon_hash.py returns {current_hash}. Update the file."
    )


def test_manifest_version_and_canon_semver_agree() -> None:
    """Top-level plugin.json `version` and canon_policy.json `semver`
    must be identical (the lockstep invariant)."""
    data = _load_manifest()
    cpv = _load_canon_policy()
    assert data["version"] == cpv["semver"], (
        f"manifest version {data['version']!r} != canon_policy.json semver "
        f"{cpv['semver']!r} — the two MUST move in lockstep"
    )


def test_plugin_json_no_legacy_canonPolicyVersion() -> None:
    """v1.3.6 hotfix: plugin.json must NOT contain the canonPolicyVersion
    key — Claude Code v2.1.19 install schema rejects it. Keep this
    test as a regression to make sure no future edit re-adds it."""
    data = _load_manifest()
    assert "canonPolicyVersion" not in data, (
        "plugin.json contains 'canonPolicyVersion' — Claude Code v2.1.19 "
        "rejects this key; move it to .claude-plugin/canon_policy.json"
    )


def test_plugin_json_no_legacy_bugs_key() -> None:
    """v1.3.6 hotfix: plugin.json must NOT contain the `bugs` key —
    Claude Code v2.1.19 install schema rejects it."""
    data = _load_manifest()
    assert "bugs" not in data, (
        "plugin.json contains 'bugs' — Claude Code v2.1.19 rejects this key"
    )


def test_plugin_json_repository_is_string() -> None:
    """v1.3.6 hotfix: plugin.json `repository` MUST be a string (URL),
    NOT the legacy {type, url} object form. Claude Code v2.1.19
    rejects the object form."""
    data = _load_manifest()
    repo = data.get("repository")
    assert isinstance(repo, str), (
        f"plugin.json repository must be a string (was {type(repo).__name__})"
    )
    assert repo.endswith(".git"), (
        f"plugin.json repository should be a git URL ending in .git; got {repo!r}"
    )


def test_manifest_author_has_name() -> None:
    data = _load_manifest()
    author = data.get("author", {})
    assert isinstance(author, dict)
    assert author.get("name"), "author.name must be set"


def test_manifest_license_matches_license_file() -> None:
    """v1.1.10 (Section J): the manifest 'license' field MUST match the
    actual LICENSE file contents. Pre-v1.1.10 the manifest declared
    'MIT' while the LICENSE file said 'All rights reserved' / 'TBD' —
    that mismatch is exactly the kind of distribution-readiness bug a
    public-remote operator would call out."""
    from pathlib import Path
    data = _load_manifest()
    declared = (data.get("license") or "").strip()
    assert declared, "manifest 'license' field must be set"
    license_path = Path(__file__).resolve().parent.parent / "LICENSE"
    body = license_path.read_text(encoding="utf-8")
    if declared == "MIT":
        # Sanity-check the LICENSE actually carries an MIT clause.
        assert "MIT License" in body or "MIT" in body.split("\n")[0], (
            f"manifest declares license=MIT but LICENSE file does not start with "
            f"'MIT License' — drift between declared license and actual file"
        )
        # MIT permission grant clause must be present (canonical phrasing).
        assert "Permission is hereby granted, free of charge" in body, (
            "manifest declares license=MIT but LICENSE file is missing the "
            "canonical MIT permission grant clause — likely still a placeholder"
        )
    # Reject the legacy 'TBD' / 'All rights reserved' content explicitly.
    assert "All rights reserved" not in body or "MIT License" in body, (
        "LICENSE file appears to be the pre-v1.1.10 'All rights reserved' "
        "placeholder — pick an actual license"
    )


def test_manifest_distribution_metadata_present() -> None:
    """v1.1.10 (Section J): packaging-readiness contract — the manifest
    MUST carry homepage / repository slots so when the repo lands on a
    public remote, dependant tooling can find the canonical URLs without
    a follow-up patch. v1.3.6: `bugs` slot dropped (Claude Code v2.1.19
    install schema rejects the key); operators link to issues via the
    homepage URL instead. `repository` is now string-form (was object)."""
    data = _load_manifest()
    assert "homepage" in data, "manifest 'homepage' slot missing"
    assert "repository" in data, "manifest 'repository' slot missing"
    repo = data["repository"]
    assert isinstance(repo, str), (
        f"manifest repository must be a string URL (v1.3.6); got {type(repo).__name__}"
    )
    assert repo.endswith(".git"), (
        "manifest repository must be a git URL ending in .git"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
