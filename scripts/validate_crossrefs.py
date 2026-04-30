#!/usr/bin/env python3
"""Cross-reference validator for bsa-plugin-family markdown.

v1.4.8 (closes lifecycle review rec #4: catch stale skill→file refs
on every commit).

Common breakages this catches:
  * SKILL.md references `scripts/foo.py` after the script was renamed.
  * Skill references `governance/schemas/aXX.schema.json` that doesn't
    exist (typo or schema removal).
  * Within-skill ref to `references/bar.md` (subfile in skill dir)
    that became dangling.
  * CHANGELOG / docs reference repo-root paths that no longer exist.

Scope:
  * Markdown links `[text](path)` + image refs `![alt](path)`.
  * Reference-style links `[text][ref]` + `[ref]: path` definitions.
  * Anchored at SKILL.md files inside `skills/` + top-level `*.md`.

Skipped:
  * External links (http/https/mailto/ftp/tel).
  * Anchor-only links (`#section`).
  * Links inside ```` ``` ```` / ``~~~`` fenced code blocks (often
    example commands referencing files that may not exist in this
    checkout — too noisy to validate).
  * Links inside `` `inline code` `` spans (CHANGELOG / docs
    frequently use `` `[text](url)` `` as syntax illustration).
  * Links resolving OUTSIDE the repo root (out of scope; defends
    against the validator being used as a file-existence oracle
    for arbitrary system paths via `../../../../etc/passwd`).

Known scope limitations (deferred — log via Codex if they bite):
  * Fragment anchors inside markdown headings are NOT validated:
    `[link](file.md#stale-section)` passes if file.md exists, even
    when the section anchor is stale. Would require parsing
    headings + slug-generation; staged for v2 if false negatives
    surface in real CHANGELOG / SKILL audits.
  * Link URLs containing balanced parens (`[t](path(with)parens.md)`)
    are clipped at the first `)`. Real-world incidence is low.
  * Multi-line link text (per CommonMark legal but rare) is missed.

CLI:
  python3 scripts/validate_crossrefs.py
      [--root REPO_ROOT]
      [--strict]
      [--paths PATH PATH ...]

  --strict    Exit 1 on any broken ref. Default: also exit 1, since
              this script is wired into CI; pass --no-strict for
              local diagnostic runs that should always exit 0.
  --paths     Limit scan to specific files (CI integration:
              `validate_crossrefs.py --paths $(git diff --name-only)`).
              Default: scan skills/**/SKILL.md + skills/**/*.md +
              top-level *.md + governance/*.md + docs/*.md.

Exit codes:
  0  No violations OR violations found but --no-strict.
  1  Violations found AND --strict (default).
  2  Invocation error (bad path / unreadable file).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional


# Match `[text](url)` AND `![alt](url)` markdown link/image syntax.
# Captures the url group; supports trailing optional title `(url "title")`.
# `[^)\s]+` for url stops at first whitespace OR closing paren so we
# don't greedily consume a title that follows.
# v1.4.8 R1 MAJOR #4 fix: `(?<!\\)` lookbehind so `\[escaped\](url)`
# isn't matched as a link (markdown escapes the bracket — not a link).
# Image refs `![alt](url)` still work because `!?` is INSIDE the
# lookbehind anchor; the lookbehind checks the char before the
# optional `!` (or before `[` if no `!`).
_LINK_RE = re.compile(
    r'(?<!\\)!?\[(?P<text>[^\]]*?)\]\((?P<url>[^)\s]+)(?:\s+"[^"]*")?\)',
)

# Reference-style link DEFINITION: `[ref-id]: url "optional title"`
_REF_DEF_RE = re.compile(
    r'^\s*\[(?P<refid>[^\]]+)\]:\s+(?P<url>\S+)',
    re.MULTILINE,
)

# Reference-style link USAGE: `[text][ref-id]`. Note: `[text][]` (empty
# ref-id, falls back to using `text` as the ref) is also valid markdown
# but rare in this codebase; not handled.
_REF_USE_RE = re.compile(
    r'(?<!\!)\[(?P<text>[^\]]+)\]\[(?P<refid>[^\]]+)\]',
)

# Code fence pattern — opens / closes a ```...``` or ~~~...~~~ block.
# Match the opening ``` / ~~~ at line start (markdown convention).
_CODE_FENCE_RE = re.compile(r'^[ \t]{0,3}(```|~~~)')

# Inline code span scanner — see `_strip_inline_code_spans` below.
# v1.4.8 R1 MAJOR #1 fix: regex-only single-backtick approach missed
# multi-backtick spans (`` `[text](url)` `` is a 2-backtick span
# containing a single backtick; my own CHANGELOG entry hit this).
# Replaced with a per-line state-machine scanner that handles N-
# backtick spans correctly per CommonMark.

# Top-level repo directory names treated as repo-root anchors.
# A url starting with one of these is resolved against REPO_ROOT
# rather than the source file's parent.
_REPO_TOP_DIRS: set[str] = {
    "skills", "scripts", "governance", "docs", "fixtures",
    "config", "hooks", "commands", "tests", ".github",
    "migrations",
}


def _strip_inline_code_spans(line: str) -> str:
    """Blank inline code spans on a single line, preserving column
    count. Handles multi-backtick spans per CommonMark: a span
    opens with N consecutive backticks and closes with the next
    run of EXACTLY N backticks (allowing internal runs of different
    lengths — e.g. ``` ``has ` inside`` ``` is a 2-backtick span).

    v1.4.8 R1 MAJOR #1 fix: single-backtick regex missed the multi-
    backtick case; my own CHANGELOG entry tripped on `` `[t](u)` ``
    wrapped in double backticks. State-machine scanner is more
    code than the regex but handles all CommonMark legal spans.

    Unmatched openers (e.g. trailing single backtick at end of
    line with no closer) are passed through as literal text
    (matches markdown rendering — a lone ` is just a backtick)."""
    if "`" not in line:
        return line
    out: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        if line[i] != "`":
            out.append(line[i])
            i += 1
            continue
        # Count opening backtick run length.
        j = i
        while j < n and line[j] == "`":
            j += 1
        opener_len = j - i
        # Look for matching closer: a run of EXACTLY opener_len
        # backticks somewhere after position j.
        closer_start = -1
        k = j
        while k < n:
            if line[k] != "`":
                k += 1
                continue
            m = k
            while m < n and line[m] == "`":
                m += 1
            if m - k == opener_len:
                closer_start = k
                closer_end = m
                break
            k = m  # skip past this non-matching run
        if closer_start < 0:
            # No matching closer — treat opener as literal text.
            out.append(line[i:j])
            i = j
        else:
            # Replace [i, closer_end) with spaces (preserve cols).
            span_len = closer_end - i
            out.append(" " * span_len)
            i = closer_end
    return "".join(out)


def _strip_code_blocks(text: str) -> str:
    """Replace lines inside fenced code blocks with blank lines AND
    blank out inline code spans on remaining lines.

    Preserves line numbers (so violation messages still point at the
    right line in the original file) while ensuring `_LINK_RE` doesn't
    match links inside code examples (those often reference files
    that don't exist in this checkout — too many false positives) OR
    inline code spans (CHANGELOG / docs frequently include
    `[text](url)` inside backticks as illustration of markdown
    syntax)."""
    out_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        is_fence = _CODE_FENCE_RE.match(line) is not None
        if is_fence:
            in_fence = not in_fence
            out_lines.append("")  # drop the fence line itself too
        elif in_fence:
            out_lines.append("")  # blank inside-fence line
        else:
            out_lines.append(_strip_inline_code_spans(line))
    return "\n".join(out_lines)


def _resolve_targets(
    url: str, source_file: Path, repo_root: Path,
) -> list[Path]:
    """Resolve a markdown link URL to one or more filesystem paths.

    Returns:
      * `[]` (empty list) for external/anchor-only/scheme links AND
        for in-line refs that resolve OUTSIDE the repo root (out of
        scope — operator may legitimately link to `/etc/...` or
        absolute system paths; v1.4.8 R1 MAJOR #2 fix prevents the
        validator from being used as an oracle for arbitrary file
        existence on the build machine).
      * `[primary_target]` for explicit-relative links (./foo, ../foo,
        anything starting with `/`) that resolve inside the repo.
      * `[source_relative, repo_root_relative]` when the URL starts
        with a top-level repo dir — both interpretations are valid
        markdown convention; caller passes if EITHER exists.

    The two-target list disambiguates intra-skill references like
    `[scripts/foo.py](scripts/foo.py)` inside
    `skills/c4-plantuml-from-context/SKILL.md`: source-relative
    resolves to `skills/c4-plantuml-from-context/scripts/foo.py`
    (the script lives under the skill); repo-root would resolve
    to `<repo>/scripts/foo.py`. Either reading is grammatically
    valid; we accept both."""
    # Drop fragment (#section) + query (?key=val) before the path check.
    url = url.split("#", 1)[0].split("?", 1)[0]
    if not url:
        return []
    # External / non-file schemes.
    if url.startswith(
        ("http://", "https://", "mailto:", "ftp://", "tel:", "git@")
    ):
        return []
    # v1.4.8 R1 MINOR #1 fix: URL-decode percent-escaped chars (e.g.
    # `path%20with%20spaces.md` → `path with spaces.md`) before the
    # filesystem resolution. Without this, the literal `%20` path is
    # checked.
    from urllib.parse import unquote as _unquote
    url = _unquote(url)
    # Explicit-relative URLs (./foo, ../foo) or absolute (/foo) get
    # ONE target — source-relative.
    if url.startswith(("./", "../", "/")):
        candidates = [(source_file.parent / url).resolve()]
    else:
        # Otherwise: try source-relative AND (if first segment matches
        # a top-level repo dir) repo-root. Caller passes if either
        # exists.
        candidates = [(source_file.parent / url).resolve()]
        first_segment = url.split("/", 1)[0]
        if first_segment in _REPO_TOP_DIRS:
            candidates.append((repo_root / url).resolve())
    # v1.4.8 R1 MAJOR #2 fix: filter out targets that escape repo_root.
    # Out-of-tree refs are out of scope (operator may legitimately link
    # to system paths) AND prevent the validator from being used as
    # an oracle for arbitrary file existence on the build machine
    # (e.g. `[link](../../../../etc/passwd)`).
    repo_resolved = repo_root.resolve()
    in_tree: list[Path] = []
    for c in candidates:
        try:
            c.relative_to(repo_resolved)
        except ValueError:
            continue
        in_tree.append(c)
    return in_tree


def _default_scan_paths(repo_root: Path) -> list[Path]:
    """Default file set to scan when --paths isn't passed.

    Excludes vendored content paths (`node_modules/`, `.git/`,
    `__pycache__/`, `.pytest_cache/`) — those carry their own
    READMEs with internal relative links that don't apply to OUR
    repo layout (false-positive noise)."""
    excluded_segments: set[str] = {
        "node_modules", ".git", "__pycache__", ".pytest_cache",
        ".venv", "venv", "site-packages",
    }

    def _accept(p: Path) -> bool:
        return not any(seg in excluded_segments for seg in p.parts)

    paths: list[Path] = []
    # skills/**/*.md (SKILL.md + references/* + any other .md in the tree)
    for p in sorted((repo_root / "skills").rglob("*.md")):
        if _accept(p):
            paths.append(p)
    # Top-level *.md (README, CHANGELOG, INSTALL, CONTRIBUTING, SECURITY).
    for p in sorted(repo_root.glob("*.md")):
        paths.append(p)
    # governance/*.md + docs/*.md (one level deep — recurse skipped to
    # avoid drowning in autogenerated content like privacy_audit.md
    # citing tons of file paths inside reports).
    for sub in ("governance", "docs"):
        sub_dir = repo_root / sub
        if sub_dir.is_dir():
            for p in sorted(sub_dir.glob("*.md")):
                paths.append(p)
    return paths


def validate(
    files: list[Path], repo_root: Path,
) -> list[str]:
    """Return a list of violation messages (one per broken ref).

    Each message is `<rel-source>:<line>: broken <kind> → <url> (...)`.
    Empty list = no violations."""
    violations: list[str] = []
    for src in files:
        try:
            text = src.read_text(encoding="utf-8")
        except OSError as exc:
            violations.append(f"{src}: cannot read: {exc}")
            continue
        scrubbed = _strip_code_blocks(text)
        # Build the ref-id → url map ONCE for reference-style usages.
        ref_defs: dict[str, str] = {}
        for m in _REF_DEF_RE.finditer(scrubbed):
            ref_defs[m.group("refid").lower()] = m.group("url")
        # Resolve source-relative path lazily.
        try:
            rel_src = src.relative_to(repo_root)
        except ValueError:
            rel_src = src
        for lineno, line in enumerate(scrubbed.splitlines(), start=1):
            # Inline links + image refs.
            for m in _LINK_RE.finditer(line):
                url = m.group("url")
                candidates = _resolve_targets(url, src, repo_root)
                if not candidates:
                    continue  # external or non-file scheme
                if not any(c.exists() for c in candidates):
                    tried = ", ".join(str(c) for c in candidates)
                    violations.append(
                        f"{rel_src}:{lineno}: broken link "
                        f"→ {url!r} (tried: {tried})"
                    )
            # Reference-style usages.
            for m in _REF_USE_RE.finditer(line):
                refid = m.group("refid").lower()
                if refid not in ref_defs:
                    continue  # may be a stylistic [text][shortcut]
                url = ref_defs[refid]
                candidates = _resolve_targets(url, src, repo_root)
                if not candidates:
                    continue
                if not any(c.exists() for c in candidates):
                    tried = ", ".join(str(c) for c in candidates)
                    violations.append(
                        f"{rel_src}:{lineno}: broken ref-style "
                        f"link [{refid}] → {url!r} "
                        f"(tried: {tried})"
                    )
    return violations


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Cross-reference validator for bsa-plugin-family markdown. "
            "Catches stale skill→file refs (typos, deleted scripts, "
            "renamed schemas) on every CI run."
        ),
    )
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parent.parent),
        help=(
            "Repo root path. Default: parent of scripts/ "
            "(`Path(__file__).parent.parent`)."
        ),
    )
    parser.add_argument(
        "--strict",
        dest="strict",
        action="store_true",
        default=True,
        help=(
            "Exit 1 on any broken ref (default — CI integration). "
            "Pass --no-strict for diagnostic runs that always exit 0."
        ),
    )
    parser.add_argument(
        "--no-strict",
        dest="strict",
        action="store_false",
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help=(
            "Specific files to scan. Default: skills/**/*.md + "
            "top-level *.md + governance/*.md + docs/*.md."
        ),
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.root).resolve()
    if not repo_root.is_dir():
        sys.stderr.write(f"[validate_crossrefs] {repo_root} is not a directory\n")
        return 2

    if args.paths:
        # v1.4.8 R1 MAJOR #3 fix: relative --paths arguments are
        # resolved against `repo_root` (not process cwd) so the
        # validator behaves identically whether run from the repo
        # root or from elsewhere (CI runs from $GITHUB_WORKSPACE
        # which IS the repo root, but local invocations from
        # `cd scripts/ && python validate_crossrefs.py --paths
        # ../tests/test.md` would otherwise resolve against
        # `scripts/` not the project root).
        files = []
        for raw in args.paths:
            p = Path(raw)
            if not p.is_absolute():
                p = repo_root / p
            files.append(p.resolve())
        # Filter out non-existent paths up front (CI may pass deleted
        # files; treat as no-op rather than failure).
        files = [f for f in files if f.is_file() and f.suffix == ".md"]
    else:
        files = _default_scan_paths(repo_root)

    if not files:
        print("validate_crossrefs: no files to scan.")
        return 0

    violations = validate(files, repo_root)
    print(
        f"validate_crossrefs: scanned {len(files)} file(s); "
        f"{len(violations)} violation(s)."
    )
    if violations:
        for v in violations:
            print(f"  {v}")
        if args.strict:
            sys.stderr.write(
                f"FAIL: {len(violations)} broken cross-reference(s) "
                f"found. Fix the listed paths or pass --no-strict for "
                f"a diagnostic run.\n"
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
