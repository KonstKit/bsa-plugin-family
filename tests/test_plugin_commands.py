"""Tests for commands/*.md (US-S4-02).

Locks the six slash commands that make up `/bsa-*`: each file has
frontmatter with matching name, a description, a Usage section, and
documents the flags (--verbose is universal; --dry-run on promote;
--mode on start).

Stdlib-only.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMANDS_DIR = REPO_ROOT / "commands"

EXPECTED_COMMANDS = (
    "bsa-start",
    "bsa-status",
    "bsa-stage",
    "bsa-promote",
    "bsa-audit",
    "bsa-handoff",
)

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
NAME_RE = re.compile(r"^name:\s*(\S+)", re.MULTILINE)
DESCRIPTION_RE = re.compile(r"^description:\s*(.+?)$", re.MULTILINE)


def _parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise AssertionError(f"{path.name}: no YAML frontmatter block at top of file")
    fm = m.group(1)
    out: dict[str, str] = {}
    name_m = NAME_RE.search(fm)
    if name_m:
        out["name"] = name_m.group(1)
    desc_m = DESCRIPTION_RE.search(fm)
    if desc_m:
        out["description"] = desc_m.group(1).strip()
    return out


def _body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    return text[m.end():] if m else text


@pytest.mark.parametrize("command_name", EXPECTED_COMMANDS)
def test_command_file_exists(command_name: str) -> None:
    path = COMMANDS_DIR / f"{command_name}.md"
    assert path.is_file(), f"missing expected command file {path}"


@pytest.mark.parametrize("command_name", EXPECTED_COMMANDS)
def test_command_frontmatter_has_name_matching_filename(command_name: str) -> None:
    path = COMMANDS_DIR / f"{command_name}.md"
    fm = _parse_frontmatter(path)
    assert fm.get("name") == command_name, (
        f"{command_name}.md: frontmatter name={fm.get('name')!r} "
        f"does not match filename"
    )


@pytest.mark.parametrize("command_name", EXPECTED_COMMANDS)
def test_command_has_non_empty_description(command_name: str) -> None:
    path = COMMANDS_DIR / f"{command_name}.md"
    fm = _parse_frontmatter(path)
    desc = fm.get("description", "")
    assert len(desc) >= 20, (
        f"{command_name}.md: description should be at least 20 chars; got {desc!r}"
    )


@pytest.mark.parametrize("command_name", EXPECTED_COMMANDS)
def test_command_body_has_usage_section(command_name: str) -> None:
    path = COMMANDS_DIR / f"{command_name}.md"
    body = _body(path)
    assert re.search(r"^##\s+Usage", body, re.MULTILINE), (
        f"{command_name}.md: body must have a '## Usage' section"
    )


@pytest.mark.parametrize("command_name", EXPECTED_COMMANDS)
def test_command_body_documents_verbose_flag(command_name: str) -> None:
    """The plan says --verbose is universal; every command documents it."""
    path = COMMANDS_DIR / f"{command_name}.md"
    body = _body(path)
    assert "--verbose" in body, (
        f"{command_name}.md: must document the --verbose flag"
    )


def test_promote_command_documents_dry_run() -> None:
    """Per plan US-S4-02 AC-9, /bsa promote must support --dry-run."""
    body = _body(COMMANDS_DIR / "bsa-promote.md")
    assert "--dry-run" in body
    # Dry-run output example should be present so users see what it looks like.
    assert "DRY RUN" in body or "dry-run" in body.lower()


def test_start_command_documents_both_modes() -> None:
    """Per plan US-S4-02 AC-1/AC-2, /bsa start supports --mode=direct and
    --mode=discovery_then_bsa."""
    body = _body(COMMANDS_DIR / "bsa-start.md")
    assert "--mode=direct" in body
    assert "--mode=discovery_then_bsa" in body


def test_audit_command_documents_five_audit_kinds() -> None:
    """Per plan US-S4-02 AC-6, /bsa audit accepts
    citation | consistency | skeptical | no-new-claims | anchor."""
    body = _body(COMMANDS_DIR / "bsa-audit.md")
    for kind in ("citation", "consistency", "skeptical", "no-new-claims", "anchor"):
        assert kind in body, f"bsa-audit.md must document the {kind!r} kind"


def test_stage_command_references_main_and_discovery_stages() -> None:
    """Per plan US-S4-02 AC-4, /bsa stage accepts 1..8 main stages and
    d1..d5 discovery stages."""
    body = _body(COMMANDS_DIR / "bsa-stage.md")
    # At least one main-cycle stage reference:
    assert any(f"stage{n}" in body for n in (1, 2, 3, 4, 5, 6, 7, 8))
    # At least one discovery stage reference:
    assert re.search(r"\bd[1-5]\b", body)


def test_handoff_command_references_h1_h4_manifest_and_nnc() -> None:
    """Per plan US-S4-02 AC-7 + US-S2-01, /bsa handoff assembles H1-H4 + manifest
    + runs final no-new-claims gate."""
    body = _body(COMMANDS_DIR / "bsa-handoff.md")
    for marker in ("H1", "H2", "H3", "H4", "handoff_manifest", "no-new-claims"):
        assert marker in body or marker.replace("-", "_") in body, (
            f"bsa-handoff.md must reference {marker!r}"
        )


def test_every_command_documents_graceful_degradation_or_failure_modes() -> None:
    """Per plan US-S4-02 AC-10, each command must document graceful handling
    when optional tools are missing OR the command is otherwise blocked.
    We verify the presence of a 'Failure modes' or 'graceful' section."""
    for command_name in EXPECTED_COMMANDS:
        body = _body(COMMANDS_DIR / f"{command_name}.md")
        assert (
            re.search(r"^##\s+Failure modes", body, re.MULTILINE)
            or "graceful" in body.lower()
        ), f"{command_name}.md: must document failure modes or graceful degradation"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
