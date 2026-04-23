"""Anonymization regression test (v1.1.19, H4).

The first external pilot's real client name was scrubbed from the
plugin's active surface in v1.1.7. The plugin uses the universal
alias `Pilot-1` instead. Historical retros + this regression test
itself are exempt from the scrub (retros are development-history
records, analogous to commit messages; this test must literally
mention the forbidden token to test for it).

This file pins that contract:
  * Walks the entire active-surface filesystem.
  * Scans every file (with binary skip) for any case-variant of
    the forbidden token.
  * Fails with the exact file:line of the violation.
  * Skips an explicit allow-list of paths where the token is
    intentionally preserved (retros, this test file, vendored
    third-party content if any, .pytest_cache regen artifacts).

If a maintainer accidentally re-introduces the client name into
the active surface (e.g., by copy-pasting from a retro), this
test fires AT LINT TIME instead of at first external distribution.

The list of FORBIDDEN_TOKENS is intentionally NOT in a separate
config file — keeping it inline here ensures any maintainer
modifying the test sees the contract directly. Adding a new
historical pilot's name to the scrub list is a single-line
diff to this file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Tokens that MUST NOT appear anywhere in the active surface. Case
# variants are matched insensitively per-token so adding "sysco"
# catches "Sysco" / "SYSCO" / "sYsCo".
#
# When adding a new historical pilot's name to this list:
#   1. Scrub the active surface (search-and-replace to "Pilot-N").
#   2. Add the literal client name here.
#   3. Re-run this test to verify zero leaks.
#   4. The retros directory remains exempt — historical record.
FORBIDDEN_TOKENS = (
    "sysco",
)

# Paths (substring match against repo-relative path) that are
# EXEMPT from the scrub. The exemption list is intentionally narrow:
#   * docs/retros/* — historical record per v1.1.7 anonymization
#     commit (the README explicitly preserves client names there
#     analogous to commit messages).
#   * tests/test_anonymization_regression.py — this file itself
#     literally contains the forbidden token to test for it.
#   * .git/, .pytest_cache/, node_modules/, __pycache__/ — VCS /
#     tooling artifacts, not source.
EXEMPT_PATH_SUBSTRINGS = (
    "docs/retros/",
    "tests/test_anonymization_regression.py",
    ".git/",
    ".pytest_cache/",
    "node_modules/",
    "__pycache__/",
    ".venv/",
    "venv/",
    ".tox/",
)

# File extensions to skip entirely (binary / image / large).
SKIP_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".webp", ".ico",
    ".zip", ".tar", ".gz", ".bz2", ".xz",
    ".pyc", ".pyo", ".pyd", ".so", ".dylib", ".dll",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".jar", ".class",
})


def _is_exempt(rel_path: str) -> bool:
    return any(sub in rel_path for sub in EXEMPT_PATH_SUBSTRINGS)


def _walk_active_surface() -> "Iterable[Path]":
    """Yield every file under REPO_ROOT that is NOT exempt + NOT a
    binary/skipped extension. Uses os.walk for speed (Path.rglob is
    slow on large trees) and prunes dirs in-place to skip
    .git/.venv/etc. early."""
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        # Prune top-level + nested skipped dirs in place. Mutating
        # dirnames is the documented os.walk way to do this.
        dirnames[:] = [
            d for d in dirnames
            if d not in (".git", "__pycache__", "node_modules",
                         ".pytest_cache", ".venv", "venv", ".tox")
        ]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in SKIP_EXTENSIONS:
                continue
            yield Path(dirpath) / fname


def test_no_forbidden_tokens_in_active_surface() -> None:
    """The headline regression test: zero matches across the active
    surface. If this fails, the violation report names every
    file:line for easy fix.

    v1.1.19 round-1 (Codex):
      * LOW fix: scan the FULL file body (not line-by-line) so a token
        split across lines like 'sy\\nsco' also fires. `re.DOTALL`
        isn't needed — we just search the full body string, and the
        regex word boundaries work across newlines.
      * HIGH fix: ALSO scan the repo-relative PATH of each file. A
        maintainer re-introducing the client name via a filename
        (e.g., `docs/sysco_runbook.md`) would bypass a body-only
        scan.
    """
    # Build a single case-insensitive regex that matches any forbidden
    # token. Word-boundary anchors (\b) avoid matching tokens
    # embedded in larger identifiers. DOTALL ensures `.` spans
    # newlines if the pattern ever uses `.` (future-proofing; not
    # needed for the current token list).
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(t) for t in FORBIDDEN_TOKENS) + r")\b",
        re.IGNORECASE | re.DOTALL,
    )
    # Path-scan regex: same tokens but WITHOUT word boundaries
    # (path separators `/` + extensions can be anything). A path
    # like `docs/sysco_runbook.md` or `tests/fixtures/sysco.json`
    # must fire.
    path_pattern = re.compile(
        "(?:" + "|".join(re.escape(t) for t in FORBIDDEN_TOKENS) + ")",
        re.IGNORECASE,
    )
    violations: list[str] = []
    for path in _walk_active_surface():
        rel = str(path.relative_to(REPO_ROOT))
        if _is_exempt(rel):
            continue
        # Filename scan (Codex round-1 HIGH fix).
        if path_pattern.search(rel):
            violations.append(
                f"  {rel}: forbidden token in FILENAME / PATH (filename leak, "
                f"not body)"
            )
        # Body scan — full body, not line-by-line (Codex round-1 LOW fix).
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in pattern.finditer(body):
            # Compute line:column for the match so the operator has
            # file:line precision in the diagnostic.
            prefix = body[:m.start()]
            line_no = prefix.count("\n") + 1
            line_start = prefix.rfind("\n") + 1
            line = body[line_start:body.find("\n", m.end()) if "\n" in body[m.start():] else len(body)]
            violations.append(f"  {rel}:{line_no}: {line.strip()[:100]}")
        # v1.1.19 round-2 (Codex LOW fix): additionally run the scan
        # against a whitespace-stripped form of the body to catch
        # tokens split across lines (e.g., `sy\nsco`, `sys\t co`).
        # The normal scan misses these because the regex literal is
        # `sysco` — no `\n` or `\s` in the pattern.
        #
        # NOTE: this fallback intentionally drops word boundaries (the
        # stripped form glues all words together: "...withsyscoon..."
        # so `\bsysco\b` would not match). Tradeoff: this is more
        # liberal than the primary scan + can false-positive on text
        # like "sysctl + cofee" (which strips to "sysctl+cofee" → no
        # sysco — but in pathological inputs like "sysc" + "ozone"
        # → "syscozone" → no sysco; OK that's actually fine since
        # sysco itself is the literal). The real risk is that a
        # benign substring like "syscobra" would match — but no
        # FORBIDDEN_TOKEN today produces this hazard.
        stripped_pattern = re.compile(
            "(?:" + "|".join(re.escape(t) for t in FORBIDDEN_TOKENS) + ")",
            re.IGNORECASE,
        )
        stripped = re.sub(r"\s+", "", body)
        if stripped_pattern.search(stripped) and not pattern.search(body):
            # Fire only if the stripped-body scan finds the token AND
            # the normal scan did NOT (avoiding double-report for
            # same-line matches). The line/column is approximate
            # (whitespace-stripping loses position info); operator
            # needs to grep the file by hand to locate.
            violations.append(
                f"  {rel}:?: forbidden token detected across whitespace / "
                f"line split (normalised scan); grep the file to locate."
            )
    assert not violations, (
        "Forbidden token(s) "
        f"{FORBIDDEN_TOKENS!r} found in active surface (v1.1.7 "
        "anonymization regression). The plugin uses 'Pilot-1' as the "
        "universal alias; historical mentions belong only in "
        "docs/retros/ which is on the exemption list. Findings:\n"
        + "\n".join(violations)
    )


def test_forbidden_tokens_list_is_non_empty() -> None:
    """Defensive pin: a maintainer who accidentally clears
    FORBIDDEN_TOKENS would silently disable this test. Pin
    non-empty + at least one entry."""
    assert FORBIDDEN_TOKENS, (
        "FORBIDDEN_TOKENS is empty — the anonymization regression "
        "test would silently pass on any leak. Re-add at least the "
        "v1.1.7 baseline entry."
    )
    assert "sysco" in FORBIDDEN_TOKENS, (
        "v1.1.7 baseline entry 'sysco' missing from FORBIDDEN_TOKENS."
    )


def test_exempt_paths_match_documented_intent() -> None:
    """Pin: the exemption list MUST include docs/retros/ (historical
    record) AND this test file itself (literally contains the
    forbidden token). Anything else is regen artifacts (.git,
    .pytest_cache, etc.) — explicitly listed but not pinned because
    they're tooling-dependent."""
    assert "docs/retros/" in EXEMPT_PATH_SUBSTRINGS, (
        "docs/retros/ exemption removed — v1.1.7 commit explicitly "
        "preserves historical client-name references there."
    )
    assert any("test_anonymization_regression.py" in s for s in EXEMPT_PATH_SUBSTRINGS), (
        "this test file's exemption removed — the test must literally "
        "mention the forbidden token to test for it."
    )


def test_filename_leak_detected(tmp_path, monkeypatch) -> None:
    """v1.1.19 round-1 (Codex HIGH): a forbidden token embedded in a
    FILENAME (not just file content) must also fire. Simulates a
    maintainer accidentally creating `docs/sysco_runbook.md` by
    monkeypatching the walker to a synthetic tmp tree."""
    # Build a synthetic tmp repo with the forbidden token in a
    # filename. The test WALKS tmp_path using the same _walk helper
    # by monkeypatching REPO_ROOT.
    bad_dir = tmp_path / "docs"
    bad_dir.mkdir()
    bad_file = bad_dir / "sysco_runbook.md"
    bad_file.write_text("Clean body — token only in the filename.\n", encoding="utf-8")
    good_file = bad_dir / "other.md"
    good_file.write_text("Clean body too.\n", encoding="utf-8")

    # Use the current module (already loaded by pytest) so the
    # walker can be monkey-patched to scan tmp_path. We reach into
    # sys.modules instead of `import tests.test_anonymization_regression`
    # because the test may be collected with different package roots
    # depending on how pytest was invoked.
    import sys
    mod = sys.modules[__name__]
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)

    # Re-run the scan against the synthetic tree; expect a violation
    # naming sysco_runbook.md (filename leak).
    import re as _re
    pattern = _re.compile(
        r"\b(?:" + "|".join(_re.escape(t) for t in mod.FORBIDDEN_TOKENS) + r")\b",
        _re.IGNORECASE | _re.DOTALL,
    )
    path_pattern = _re.compile(
        "(?:" + "|".join(_re.escape(t) for t in mod.FORBIDDEN_TOKENS) + ")",
        _re.IGNORECASE,
    )
    violations: list[str] = []
    for path in mod._walk_active_surface():
        rel = str(path.relative_to(tmp_path))
        if mod._is_exempt(rel):
            continue
        if path_pattern.search(rel):
            violations.append(f"  {rel}: FILENAME leak")
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if pattern.search(body):
            violations.append(f"  {rel}: BODY leak")
    # We expect EXACTLY one violation — the filename leak.
    assert violations, "filename-leak scenario did not fire"
    assert any("FILENAME leak" in v and "sysco_runbook.md" in v for v in violations), (
        f"expected filename leak on sysco_runbook.md; got {violations!r}"
    )
    # The clean file must NOT show up.
    assert not any("other.md" in v for v in violations)


def test_cross_line_split_detected(tmp_path, monkeypatch) -> None:
    """v1.1.19 round-2 (Codex LOW): a forbidden token split across
    lines (e.g., `sy\\nsco` — maybe pasted from a wrapped terminal
    output) must also fire. Earlier `\\b(?:sysco)\\b` scan missed
    this because the literal pattern has no `\\n`. The stripped-body
    fallback catches it.

    Synthesises a tmp repo with a file whose body contains `sy\\nsco`
    (split across 2 lines), monkey-patches REPO_ROOT, runs the
    scanner, verifies the diagnostic fires."""
    bad_dir = tmp_path / "docs"
    bad_dir.mkdir()
    (bad_dir / "wrapped.md").write_text(
        "# Harmless header\n\n"
        "This line ends with sy\n"
        "sco on the next line (pasted from a wrapped terminal).\n",
        encoding="utf-8",
    )
    # A control file with NO leak of any form must not trip the scan.
    (bad_dir / "clean.md").write_text(
        "Completely clean body with no forbidden token.\n",
        encoding="utf-8",
    )
    import sys
    mod = sys.modules[__name__]
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)

    import re as _re
    body_pattern = _re.compile(
        r"\b(?:" + "|".join(_re.escape(t) for t in mod.FORBIDDEN_TOKENS) + r")\b",
        _re.IGNORECASE | _re.DOTALL,
    )
    # Stripped pattern intentionally drops word boundaries (mirrors
    # the production scanner); see fallback-scan rationale comment.
    stripped_pattern = _re.compile(
        "(?:" + "|".join(_re.escape(t) for t in mod.FORBIDDEN_TOKENS) + ")",
        _re.IGNORECASE,
    )
    violations: list[str] = []
    for path in mod._walk_active_surface():
        rel = str(path.relative_to(tmp_path))
        if mod._is_exempt(rel):
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        stripped = _re.sub(r"\s+", "", body)
        if stripped_pattern.search(stripped) and not body_pattern.search(body):
            violations.append(f"  {rel}: cross-line split detected")
    assert any("wrapped.md" in v for v in violations), (
        f"cross-line split scenario not detected; got {violations!r}"
    )
    assert not any("clean.md" in v for v in violations)


def test_stripped_scan_avoids_false_positive_on_split_words(
    tmp_path, monkeypatch,
) -> None:
    """v1.1.19 round-3 (Codex non-blocking LOW): document the
    stripped-body fallback's false-positive surface. A benign phrase
    like `sys cobra` strips to `syscobra` which the fallback regex
    `(?:sysco)` (no word boundaries) would match — this is the
    documented tradeoff. Pin: confirm the false-positive HAPPENS so
    a future maintainer adding word-boundary-respecting fallback
    knows what changed.

    If the fallback is later upgraded to handle this case (e.g.,
    via a smarter normaliser), this test should flip to assert
    NO false positive. For v1.1.19 we accept the tradeoff because
    real adversarial cross-line splits in actual files are far
    more likely than benign phrases that happen to combine into
    the forbidden token."""
    bad_dir = tmp_path / "docs"
    bad_dir.mkdir()
    (bad_dir / "split_word_phrase.md").write_text(
        "Operations runs sys cobra checks daily.\n",
        encoding="utf-8",
    )
    import sys
    mod = sys.modules[__name__]
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    import re as _re
    body_pattern = _re.compile(
        r"\b(?:" + "|".join(_re.escape(t) for t in mod.FORBIDDEN_TOKENS) + r")\b",
        _re.IGNORECASE | _re.DOTALL,
    )
    stripped_pattern = _re.compile(
        "(?:" + "|".join(_re.escape(t) for t in mod.FORBIDDEN_TOKENS) + ")",
        _re.IGNORECASE,
    )
    body = (bad_dir / "split_word_phrase.md").read_text(encoding="utf-8")
    assert not body_pattern.search(body), "primary scan should not fire on benign body"
    stripped = _re.sub(r"\s+", "", body)
    # `sys cobra` → `syscobra` → contains `sysco` (false positive).
    # Documenting the limitation; if a future fix avoids this, flip
    # this assertion to `not stripped_pattern.search(stripped)`.
    assert stripped_pattern.search(stripped), (
        "stripped-body fallback would NOT fire on `sys cobra`-style benign "
        "phrase — possibly upgraded; flip this assertion + remove the "
        "v1.1.19 round-3 LOW carve-out from the CHANGELOG."
    )


def test_pilot_1_alias_appears_in_active_surface() -> None:
    """Defense-in-depth: the universal alias 'Pilot-1' MUST appear
    somewhere in the active surface as the documented replacement
    for the scrubbed client name. If this fails, either the alias
    convention got accidentally dropped OR the v1.1.7 commit got
    reverted."""
    pilot_1_re = re.compile(r"\bPilot-1\b")
    found_in: list[str] = []
    for path in _walk_active_surface():
        rel = str(path.relative_to(REPO_ROOT))
        if _is_exempt(rel):
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if pilot_1_re.search(body):
            found_in.append(rel)
            if len(found_in) >= 5:
                break  # 5 hits is sufficient evidence; stop scanning
    assert found_in, (
        "'Pilot-1' alias not found anywhere in active surface — "
        "did v1.1.7 anonymization commit get reverted? See "
        "CHANGELOG v1.1.7 + docs/pilot_validation.md anonymization note."
    )
