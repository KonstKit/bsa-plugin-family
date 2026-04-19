"""Unit tests for scripts/validate_skill_structure.py (US-S0-02).

Covers the 4 acceptance criteria:
  AC-1: valid SKILL.md -> exit 0
  AC-2: missing `description` frontmatter field -> exit 1 with specific message
  AC-3: broken reference link -> exit 1 with specific message
  AC-4: all 22 source skills -> exit 0 (baseline health)

Additional edge cases covered beyond the minimum 4 fixtures required by DoD:
  - Missing `name` frontmatter field
  - Name/directory mismatch
  - Missing frontmatter block entirely
  - Link escaping skill root (../ traversal)
  - External URL skipped (not checked)
  - Anchor-only link skipped

Uses pytest tmp_path fixtures — no network, no external tools.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "validate_skill_structure.py"


def run_validator(*skill_files: Path, quiet: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT)]
    if quiet:
        cmd.append("--quiet")
    cmd.extend(str(f) for f in skill_files)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )


def make_skill(
    root: Path,
    name: str,
    *,
    frontmatter: str | None = None,
    body: str = "",
    extra_files: dict[str, str] | None = None,
) -> Path:
    """Create a fake skill directory with given content. Returns SKILL.md path."""
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    default_fm = f"---\nname: {name}\ndescription: Test fixture skill.\n---\n"
    text = (frontmatter if frontmatter is not None else default_fm) + body
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(text, encoding="utf-8")
    if extra_files:
        for rel_path, content in extra_files.items():
            target = skill_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    return skill_md


def test_ac1_valid_skill_passes(tmp_path: Path) -> None:
    """AC-1: SKILL.md with valid frontmatter -> exit 0."""
    skill = make_skill(tmp_path, "sample-skill")
    result = run_validator(skill)
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout


def test_ac2_missing_description_fails(tmp_path: Path) -> None:
    """AC-2: missing `description` -> exit 1 with specific message."""
    skill = make_skill(
        tmp_path,
        "no-desc-skill",
        frontmatter="---\nname: no-desc-skill\n---\n",
    )
    result = run_validator(skill)
    assert result.returncode == 1
    assert "missing required frontmatter field: description" in result.stderr


def test_ac3_broken_reference_fails(tmp_path: Path) -> None:
    """AC-3: broken reference link -> exit 1 with specific message."""
    skill = make_skill(
        tmp_path,
        "broken-ref-skill",
        body="See [foo](references/nonexistent.md) for details.\n",
    )
    result = run_validator(skill)
    assert result.returncode == 1
    assert "broken reference: skills/broken-ref-skill/references/nonexistent.md" in result.stderr


def test_ac4_all_source_skills_pass() -> None:
    """AC-4: all 22 source skills in the repo baseline pass."""
    skill_files = sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))
    assert len(skill_files) == 22, f"expected 22 skills, got {len(skill_files)}"
    result = run_validator(*skill_files, quiet=True)
    assert result.returncode == 0, (
        f"baseline health check failed:\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_missing_name_field_fails(tmp_path: Path) -> None:
    skill = make_skill(
        tmp_path,
        "no-name-skill",
        frontmatter="---\ndescription: Has desc but no name.\n---\n",
    )
    result = run_validator(skill)
    assert result.returncode == 1
    assert "missing required frontmatter field: name" in result.stderr


def test_name_directory_mismatch_fails(tmp_path: Path) -> None:
    skill = make_skill(
        tmp_path,
        "actual-dir-name",
        frontmatter="---\nname: different-declared-name\ndescription: mismatch.\n---\n",
    )
    result = run_validator(skill)
    assert result.returncode == 1
    assert "does not match directory" in result.stderr


def test_missing_frontmatter_fails(tmp_path: Path) -> None:
    skill = make_skill(
        tmp_path,
        "no-fm-skill",
        frontmatter="# Just a heading, no frontmatter\n",
    )
    result = run_validator(skill)
    assert result.returncode == 1
    assert "missing or malformed frontmatter" in result.stderr


def test_link_escaping_skill_root_fails(tmp_path: Path) -> None:
    skill = make_skill(
        tmp_path,
        "escape-link-skill",
        body="Bad [link](references/../../outside.md).\n",
    )
    result = run_validator(skill)
    assert result.returncode == 1
    assert "link target escapes skill root" in result.stderr


def test_external_url_not_checked(tmp_path: Path) -> None:
    skill = make_skill(
        tmp_path,
        "external-link-skill",
        body="See [docs](https://example.com/foo.md) online.\n",
    )
    result = run_validator(skill)
    assert result.returncode == 0


def test_anchor_only_link_not_checked(tmp_path: Path) -> None:
    skill = make_skill(
        tmp_path,
        "anchor-only-skill",
        body="Jump to [Top](#top).\n",
    )
    result = run_validator(skill)
    assert result.returncode == 0


def test_valid_reference_with_file_present_passes(tmp_path: Path) -> None:
    skill = make_skill(
        tmp_path,
        "good-ref-skill",
        body="See [doc](references/policy.md).\n",
        extra_files={"references/policy.md": "# Policy\n"},
    )
    result = run_validator(skill)
    assert result.returncode == 0


def test_aggregated_exit_code_over_multiple_files(tmp_path: Path) -> None:
    """Mixed set: one pass, one fail -> exit 1 (aggregated failure)."""
    good = make_skill(tmp_path, "good-skill")
    bad = make_skill(
        tmp_path,
        "bad-skill",
        frontmatter="---\nname: bad-skill\n---\n",
    )
    result = run_validator(good, bad)
    assert result.returncode == 1
    assert "missing required frontmatter field: description" in result.stderr


def test_nonexistent_file_errors_with_code_2(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist" / "SKILL.md"
    result = run_validator(missing)
    assert result.returncode == 2
    assert "does not exist" in result.stderr


def test_crlf_frontmatter_accepted(tmp_path: Path) -> None:
    """Round-2: CRLF line endings must not reject valid frontmatter."""
    name = "crlf-skill"
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    crlf_content = "---\r\nname: crlf-skill\r\ndescription: Uses CRLF endings.\r\n---\r\nBody line.\r\n"
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_bytes(crlf_content.encode("utf-8"))
    result = run_validator(skill_md)
    assert result.returncode == 0, result.stderr


def test_single_quoted_frontmatter_value_unwrapped(tmp_path: Path) -> None:
    """Round-2: single-quoted scalar must be unwrapped so name check passes."""
    skill = make_skill(
        tmp_path,
        "sq-skill",
        frontmatter="---\nname: 'sq-skill'\ndescription: 'Single-quoted desc.'\n---\n",
    )
    result = run_validator(skill)
    assert result.returncode == 0, result.stderr


def test_link_with_single_quoted_title_handled(tmp_path: Path) -> None:
    """Round-2: markdown link with single-quoted title must still detect broken ref."""
    skill = make_skill(
        tmp_path,
        "sq-title-skill",
        body="See [doc](references/missing.md 'hover title') for more.\n",
    )
    result = run_validator(skill)
    assert result.returncode == 1
    assert "broken reference: skills/sq-title-skill/references/missing.md" in result.stderr


def test_link_with_double_quoted_title_handled(tmp_path: Path) -> None:
    """Round-2: markdown link with double-quoted title must still detect broken ref."""
    skill = make_skill(
        tmp_path,
        "dq-title-skill",
        body='See [doc](references/missing.md "hover title") for more.\n',
    )
    result = run_validator(skill)
    assert result.returncode == 1
    assert "broken reference: skills/dq-title-skill/references/missing.md" in result.stderr


def test_link_with_parenthesized_title_handled(tmp_path: Path) -> None:
    """Round-2: markdown link with (title) must still detect broken ref."""
    skill = make_skill(
        tmp_path,
        "paren-title-skill",
        body="See [doc](references/missing.md (hover title)) for more.\n",
    )
    result = run_validator(skill)
    assert result.returncode == 1
    assert "broken reference: skills/paren-title-skill/references/missing.md" in result.stderr


def test_link_with_balanced_parens_in_path_resolved(tmp_path: Path) -> None:
    """Round-2: path with balanced parens should resolve to the actual file."""
    skill = make_skill(
        tmp_path,
        "paren-path-skill",
        body="See [doc](references/file(alt).md) for more.\n",
        extra_files={"references/file(alt).md": "# File with parens\n"},
    )
    result = run_validator(skill)
    assert result.returncode == 0, result.stderr


def test_link_with_balanced_parens_in_path_detects_broken(tmp_path: Path) -> None:
    """Round-2: path with balanced parens pointing at missing file must fail."""
    skill = make_skill(
        tmp_path,
        "paren-path-missing-skill",
        body="See [doc](references/file(alt).md) for more.\n",
    )
    result = run_validator(skill)
    assert result.returncode == 1
    assert "broken reference: skills/paren-path-missing-skill/references/file(alt).md" in result.stderr


def test_symlink_loop_in_reference_reports_finding(tmp_path: Path) -> None:
    """Round-2: resolve() on a symlink loop must surface as finding, not traceback."""
    skill = make_skill(
        tmp_path,
        "loop-skill",
        body="See [doc](references/loop.md) for more.\n",
    )
    ref_dir = skill.parent / "references"
    ref_dir.mkdir(exist_ok=True)
    # Create a self-referencing symlink loop.
    (ref_dir / "loop.md").symlink_to("loop.md")
    result = run_validator(skill)
    # Either broken-reference (macOS resolves loop to non-existent) or
    # resolve-error — both acceptable outcomes; crucial thing is exit 1,
    # not uncaught traceback.
    assert result.returncode == 1
    assert "Traceback" not in result.stderr, result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
