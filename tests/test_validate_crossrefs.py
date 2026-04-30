"""Tests for v1.4.8 scripts/validate_crossrefs.py
(closes lifecycle review rec #4: cross-reference validator + CI gate).

Coverage:
  - happy path: all links valid → 0 violations.
  - broken inline link → flagged with line number + tried paths.
  - broken image ref → flagged.
  - external links (http/https/mailto) → skipped.
  - anchor-only links (#section) → skipped.
  - link inside fenced code block → skipped.
  - link inside inline code span → skipped (CHANGELOG / docs commonly
    use `[text](url)` as syntax illustration).
  - intra-skill ref `scripts/foo.py` resolves source-relative FIRST
    (skill-local script) before falling back to repo-root.
  - reference-style link `[text][ref]` + `[ref]: path` validated.
  - relative `./foo` and `../foo` resolved against source dir only.
  - `--paths` argument limits scan; missing files are skipped silently.
  - `--strict` (default) exits 1 on violations; `--no-strict` exits 0.
  - node_modules + .git + __pycache__ paths excluded from default scan.
  - whole-repo scan currently passes (regression guard against future
    accidental skill→file rename without updating SKILL.md).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "validate_crossrefs.py"


def _run(*args: str, cwd: Path = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False,
        cwd=str(cwd) if cwd else None,
    )


def _make_fake_repo(tmp_path: Path) -> Path:
    """Build a minimal repo skeleton with skills/ + scripts/ + a
    SKILL.md to use as a controlled test surface."""
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    (repo / "skills").mkdir()
    (repo / "scripts").mkdir()
    (repo / "docs").mkdir()
    (repo / "governance").mkdir()
    return repo


# ---- happy paths ----------------------------------------------------


def test_happy_path_all_links_valid(tmp_path: Path) -> None:
    """No broken refs → exit 0, 0 violations reported."""
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "# Demo\n\n"
        "See [docs/foo.md](../../docs/foo.md) and [helper](helper.md).\n",
        encoding="utf-8",
    )
    (skill_dir / "helper.md").write_text("helper", encoding="utf-8")
    (repo / "docs" / "foo.md").write_text("foo", encoding="utf-8")
    res = _run(f"--root={repo}")
    assert res.returncode == 0
    assert "0 violation(s)" in res.stdout


def test_external_links_skipped(tmp_path: Path) -> None:
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "[ext](https://example.com/page)\n"
        "[mail](mailto:a@example.com)\n"
        "[anchor](#section)\n",
        encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 0
    assert "0 violation(s)" in res.stdout


def test_intra_skill_ref_resolves_source_relative_first(
    tmp_path: Path,
) -> None:
    """`[text](scripts/foo.py)` in a SKILL.md should resolve against
    the skill's own dir BEFORE falling back to repo-root scripts/.
    Catches the false-positive case where a skill bundles its own
    scripts/ subdirectory."""
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "foo.py").write_text("# foo", encoding="utf-8")
    # No `repo/scripts/foo.py` — only the skill-local one.
    (skill_dir / "SKILL.md").write_text(
        "Run [scripts/foo.py](scripts/foo.py) for details.\n",
        encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 0


def test_repo_root_fallback_when_no_skill_local(tmp_path: Path) -> None:
    """When source-relative resolution fails AND first segment matches
    a known top-level dir, validator falls back to repo-root."""
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (repo / "scripts" / "shared.py").write_text("x", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        "Uses [scripts/shared.py](scripts/shared.py).\n",
        encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 0


# ---- broken refs ----------------------------------------------------


def test_broken_inline_link_flagged(tmp_path: Path) -> None:
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "Line 1.\n"
        "Line 2 with [bad](missing.md) link.\n",
        encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 1
    assert "1 violation(s)" in res.stdout
    assert "skills/demo/SKILL.md:2" in res.stdout
    assert "missing.md" in res.stdout


def test_broken_image_ref_flagged(tmp_path: Path) -> None:
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "![alt](missing.png)\n",
        encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 1
    assert "missing.png" in res.stdout


def test_no_strict_returns_zero_even_with_violations(
    tmp_path: Path,
) -> None:
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "[bad](missing.md)\n", encoding="utf-8",
    )
    res = _run(f"--root={repo}", "--no-strict")
    assert res.returncode == 0
    assert "1 violation(s)" in res.stdout


# ---- code-block / inline-code stripping -----------------------------


def test_link_inside_fenced_code_block_skipped(tmp_path: Path) -> None:
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "Real link: [present](present.md)\n"
        "\n"
        "```\n"
        "[fake](does-not-exist.md)\n"
        "```\n",
        encoding="utf-8",
    )
    (skill_dir / "present.md").write_text("p", encoding="utf-8")
    res = _run(f"--root={repo}")
    assert res.returncode == 0


def test_link_inside_inline_code_span_skipped(tmp_path: Path) -> None:
    """Catches the v1.4.8 R0 false positive — CHANGELOG entries
    often embed `[text](url)` inside backticks as syntax illustration."""
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "Markdown links look like `[text](url)` — the URL part is "
        "`[anything-here](nowhere.md)`.\n",
        encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 0


# ---- reference-style links ------------------------------------------


def test_reference_style_link_validated(tmp_path: Path) -> None:
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "See [the doc][ref1] and [missing][ref2].\n"
        "\n"
        "[ref1]: present.md\n"
        "[ref2]: missing.md\n",
        encoding="utf-8",
    )
    (skill_dir / "present.md").write_text("p", encoding="utf-8")
    res = _run(f"--root={repo}")
    assert res.returncode == 1
    # Only [ref2] → missing.md is broken.
    assert "1 violation(s)" in res.stdout
    assert "missing.md" in res.stdout
    assert "ref2" in res.stdout


# ---- explicit-relative links ----------------------------------------


def test_dot_relative_link_resolved_against_source_dir(
    tmp_path: Path,
) -> None:
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "sibling.md").write_text("s", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        "Sibling: [./sibling.md](./sibling.md)\n",
        encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 0


def test_dotdot_relative_link_resolved_against_source_dir(
    tmp_path: Path,
) -> None:
    repo = _make_fake_repo(tmp_path)
    (repo / "skills" / "demo").mkdir()
    sibling = repo / "skills" / "demo-sibling"
    sibling.mkdir()
    (sibling / "SIBLING.md").write_text("s", encoding="utf-8")
    (repo / "skills" / "demo" / "SKILL.md").write_text(
        "Sibling skill: [../demo-sibling/SIBLING.md]"
        "(../demo-sibling/SIBLING.md)\n",
        encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 0


# ---- --paths argument -----------------------------------------------


def test_paths_argument_limits_scan(tmp_path: Path) -> None:
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "[broken](missing.md)\n", encoding="utf-8",
    )
    other = repo / "skills" / "other"
    other.mkdir()
    (other / "OTHER.md").write_text(
        "[also-broken](nope.md)\n", encoding="utf-8",
    )
    # Scan ONLY the skill-2 file.
    res = _run(f"--root={repo}", "--paths", str(other / "OTHER.md"))
    assert res.returncode == 1
    # Should report the OTHER.md violation, not the demo one.
    assert "nope.md" in res.stdout
    assert "missing.md" not in res.stdout


def test_paths_silently_skips_nonexistent_files(tmp_path: Path) -> None:
    """CI may pass deleted files via `git diff --name-only`; the
    script must treat missing paths as no-op rather than crash."""
    repo = _make_fake_repo(tmp_path)
    res = _run(
        f"--root={repo}",
        "--paths", str(repo / "deleted.md"),
    )
    assert res.returncode == 0
    assert "no files to scan" in res.stdout


# ---- exclusions -----------------------------------------------------


def test_node_modules_excluded_from_default_scan(tmp_path: Path) -> None:
    """node_modules/ READMEs (vendored packages) often have internal
    relative links that don't apply to OUR repo layout — must be
    skipped by default."""
    repo = _make_fake_repo(tmp_path)
    nm = repo / "skills" / "demo" / "node_modules" / "some-pkg"
    nm.mkdir(parents=True)
    (nm / "README.md").write_text(
        "[bad](does-not-exist-in-our-repo)\n", encoding="utf-8",
    )
    # The node_modules file would fail validation if scanned, but
    # should be excluded.
    res = _run(f"--root={repo}")
    assert res.returncode == 0


# ---- regression guard -----------------------------------------------


def test_real_repo_passes_validator() -> None:
    """Whole-repo scan must pass — regression guard against future
    accidental skill→file rename without updating SKILL.md (caught
    on every CI run)."""
    res = _run()  # default --root = repo root
    assert res.returncode == 0, (
        f"real-repo scan must pass; output:\n{res.stdout}\n{res.stderr}"
    )


# ---- v1.4.8 R1 fixes — Codex review round 1 -------------------------


def test_multi_backtick_inline_code_span_skipped(tmp_path: Path) -> None:
    """R1 MAJOR #1: a 2-backtick span containing a single backtick
    (e.g. `` ``[text](url)`` `` from CHANGELOG syntax illustration)
    must be skipped. Single-backtick regex missed this case; my own
    v1.4.8 CHANGELOG entry tripped on it."""
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "Markdown shorthand: ``[some-text](nowhere.md)`` — ignore this.\n",
        encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 0, (
        f"double-backtick code span must skip embedded link; "
        f"output: {res.stdout!r}"
    )


def test_escaped_brackets_not_treated_as_link(tmp_path: Path) -> None:
    """R1 MAJOR #4: `\\[text\\](url)` is escaped markdown — the
    backslash before `[` says 'literal bracket', NOT a link. The
    validator must skip these."""
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        r"Escaped: \[text\](nowhere.md) — not a link." + "\n",
        encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 0


def test_link_escaping_repo_root_skipped(tmp_path: Path) -> None:
    """R1 MAJOR #2: `[link](../../../../etc/passwd)` resolves outside
    repo_root → must be skipped (out of scope; defends against the
    validator being used as a file-existence oracle)."""
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "[oracle](../../../../etc/passwd)\n"
        "[also-out](/etc/passwd)\n",
        encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    # Both refs resolve outside repo_root → silently skipped, exit 0.
    assert res.returncode == 0
    assert "0 violation(s)" in res.stdout


def test_paths_relative_resolved_against_repo_root(
    tmp_path: Path, monkeypatch,
) -> None:
    """R1 MAJOR #3: `--paths skills/demo/SKILL.md` with relative path
    must resolve against `--root` (not process cwd) so the validator
    works identically regardless of where it's invoked."""
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "[broken](missing.md)\n", encoding="utf-8",
    )
    # Run from a DIFFERENT cwd so process-cwd-relative resolution
    # would fail to find the file.
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    res = _run(
        f"--root={repo}",
        "--paths", "skills/demo/SKILL.md",
        cwd=other_cwd,
    )
    # Should have actually scanned the SKILL.md (relative path
    # resolved against --root, not cwd) and flagged the broken link.
    assert res.returncode == 1, (
        f"relative --paths must resolve against --root, not cwd; "
        f"output: {res.stdout!r}"
    )
    assert "missing.md" in res.stdout


def test_url_encoded_path_decoded(tmp_path: Path) -> None:
    """R1 MINOR #1: `[link](path%20with%20spaces.md)` must decode
    `%20` to space before filesystem resolution."""
    repo = _make_fake_repo(tmp_path)
    skill_dir = repo / "skills" / "demo"
    skill_dir.mkdir()
    target = skill_dir / "path with spaces.md"
    target.write_text("p", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        "[link](path%20with%20spaces.md)\n",
        encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 0


# ---- v1.4.11 hotfix — default-scan coverage gap ---------------------


def test_default_scan_includes_commands_md(tmp_path: Path) -> None:
    """v1.4.11 hotfix: pre-fix `_default_scan_paths()` only recursed
    `skills/**/*.md` + top-level + ONE level of governance/docs.
    `commands/*.md` was completely missed → CI gate false-clean for
    7 command files in this repo. Pin: a broken link in
    `commands/<foo>.md` MUST be flagged."""
    repo = _make_fake_repo(tmp_path)
    (repo / "commands").mkdir()
    (repo / "commands" / "bsa-stage.md").write_text(
        "[broken-link](missing.md)\n", encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 1, (
        f"v1.4.11 must scan commands/*.md; got: {res.stdout!r}"
    )
    assert "commands/bsa-stage.md" in res.stdout
    assert "missing.md" in res.stdout


def test_default_scan_includes_nested_docs(tmp_path: Path) -> None:
    """v1.4.11 hotfix: pre-fix only scanned `docs/*.md` (one level).
    `docs/retros/sprint.md`, `docs/cookbook/*.md` (19 files in this
    repo) were missed. Pin: a broken link in `docs/<sub>/foo.md`
    MUST be flagged."""
    repo = _make_fake_repo(tmp_path)
    (repo / "docs" / "retros").mkdir()
    (repo / "docs" / "retros" / "sprint.md").write_text(
        "[broken](missing.md)\n", encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 1, (
        f"v1.4.11 must scan docs/<sub>/*.md; got: {res.stdout!r}"
    )
    assert "docs/retros/sprint.md" in res.stdout


def test_default_scan_includes_nested_governance(tmp_path: Path) -> None:
    """v1.4.11 hotfix: same gap for `governance/<sub>/*.md`.
    No nested governance docs exist in the repo today, but the
    coverage symmetry matters for future additions."""
    repo = _make_fake_repo(tmp_path)
    (repo / "governance" / "retros").mkdir()
    (repo / "governance" / "retros" / "review.md").write_text(
        "[broken](missing.md)\n", encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 1
    assert "governance/retros/review.md" in res.stdout


def test_default_scan_still_excludes_node_modules_in_new_dirs(
    tmp_path: Path,
) -> None:
    """v1.4.11 hotfix: extending recursion to commands/docs/governance
    must NOT also pick up vendored content (node_modules/) inside
    those dirs."""
    repo = _make_fake_repo(tmp_path)
    nm = repo / "docs" / "node_modules" / "vendored"
    nm.mkdir(parents=True)
    (nm / "README.md").write_text(
        "[broken-internal](does-not-exist)\n", encoding="utf-8",
    )
    res = _run(f"--root={repo}")
    assert res.returncode == 0, (
        f"node_modules in newly-recursed dirs must still be excluded; "
        f"got: {res.stdout!r}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
