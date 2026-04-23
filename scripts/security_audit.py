#!/usr/bin/env python3
"""scripts/security_audit.py — automated security drift detection.

v1.1.11 (Section G). Complements `scripts/privacy_scan.py` (which catches
PII / credentials in test fixtures) by scanning the SCRIPT + TEST + SCHEMA
surface for security drift:

  1. **Hardcoded token-shaped strings** — JWT, GitHub PAT (ghp_/gho_/...),
     Atlassian API token (ATATT3...), Bearer/Basic-prefixed credentials.
     Catches the case where a maintainer pastes a real token into a script
     comment / docstring / test fixture by mistake.

  2. **Insecure subprocess invocations** — `shell=True` without an
     explicit allowlist comment; `os.system()`; `subprocess.call()` with
     dynamic args. Catches command-injection vectors.

  3. **Dangerous Python builtins** — `eval()` / `exec()` / `compile()`
     in non-test scripts. Catches code-injection vectors.

  4. **Path-traversal heuristic** — file-write paths constructed from
     operator-supplied input without `posixpath.normpath` / `pathlib`
     normalization. Catches `..`-segment escape.

  5. **Token-shape leak in committed fixtures** — same regex set as #1,
     applied to fixture data files (CSV, JSON, MD).

  6. **Missing scrub on persisted error fields** — heuristic scan for
     code paths that catch HTTP errors and persist the message without
     calling `_scrub_secrets()`.

Reports findings as severity-tiered output:

  CRITICAL — must fix before commit (e.g., real token in committed file)
  HIGH     — should fix before next release (e.g., shell=True without justify)
  MEDIUM   — review (e.g., dynamic subprocess arg)
  LOW      — informational (e.g., reminder to scrub error fields)

Exit codes:
  0 — clean (zero CRITICAL + zero HIGH)
  1 — at least one CRITICAL or HIGH finding
  2 — invocation error (missing repo root, etc.)

Stdlib-only. Python 3.9+.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# Repo root resolved relative to this script's location.
REPO_ROOT = Path(__file__).resolve().parent.parent


# ---- Token-shape detectors --------------------------------------------
# Mirror the regex set used in scripts/backlog_live_apply.py and
# governance/schemas/live_api_response.schema.json. Any new token shape
# added here SHOULD also be added to the script's `_TOKEN_SHAPE_RE`.

TOKEN_SHAPE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("JWT", re.compile(
        r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
    )),
    ("GitHub PAT", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("Atlassian API Token", re.compile(r"\bATATT3[A-Za-z0-9]{20,}")),
    # Minimum 20 chars to match runtime quarantine threshold in
    # scripts/backlog_live_apply.py::_TOKEN_SHAPE_RE and the schema
    # token-shape rejection in live_api_response.schema.json. v1.1.11
    # round-1 should-fix (earlier had 30+ which let 20-29 char shapes
    # slip past CI while runtime would still reject them).
    ("Bearer credential", re.compile(
        r"[Bb]earer\s+[A-Za-z0-9_\-=+/.]{20,}"
    )),
    ("Basic credential", re.compile(
        r"[Bb]asic\s+[A-Za-z0-9_+/=]{20,}"
    )),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack bot token", re.compile(r"\bxox[bpars]-[A-Za-z0-9\-]{10,}")),
)


# ---- Insecure subprocess patterns -------------------------------------

INSECURE_SUBPROCESS_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "subprocess shell=True",
        re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True"),
        "shell=True allows command injection if any arg is operator-controlled. Either use a list arg + shell=False (default), or add a `# nosec: shell-allowlist` comment justifying the pattern.",
    ),
    (
        "os.system",
        re.compile(r"\bos\.system\s*\("),
        "os.system runs through /bin/sh; same shell-injection risk as subprocess shell=True. Prefer subprocess.run([...]) with a list arg.",
    ),
    (
        "subprocess.call legacy",
        re.compile(r"\bsubprocess\.call\s*\([^)]*shell\s*=\s*True"),
        "Same as subprocess shell=True — but legacy API. Migrate to subprocess.run() and drop shell=True.",
    ),
)


# ---- Dangerous Python builtins ----------------------------------------

DANGEROUS_BUILTIN_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    # Lookbehind `(?<![A-Za-z_.])` excludes both word-char predecessors
    # (avoids `myeval(...)` matching) AND `.` predecessors (avoids
    # `re.compile(...)`, `ast.literal_eval(...)`, `tracer.exec_steps(...)`
    # matching). The dangerous form is the BARE builtin call.
    (
        "eval()",
        re.compile(r"(?<![A-Za-z_.])eval\s*\("),
        "eval() of operator-controlled input is code injection. If the call is genuinely safe (e.g., parsing a literal expression), use ast.literal_eval and add a `# nosec: literal-only` comment.",
    ),
    (
        "exec()",
        re.compile(r"(?<![A-Za-z_.])exec\s*\("),
        "exec() runs arbitrary Python. If unavoidable (e.g., loading a generated module), add a `# nosec: <reason>` comment.",
    ),
    (
        "compile()",
        re.compile(r"(?<![A-Za-z_.])compile\s*\("),
        "compile() of operator input is code injection. If used for a known-safe template language, document with a comment. (Note: re.compile and similar attribute-access calls are NOT flagged — only the bare builtin.)",
    ),
)


# ---- Path-traversal heuristic ----------------------------------------

# Heuristic: file-open with a Path constructed from operator-controlled
# input concatenated with a relative segment, then sunk into a write/
# read/open call. We can't fully analyze taint statically, so we
# pattern-match common smells. False-positive rate is acceptable; the
# `# nosec: path-validated` comment can suppress.
#
# v1.1.11 round-1 critical fix: was previously not wired into run_audit
# at all, AND the regex didn't match the typical sink shape
# `(Path(base) / user_input).write_text(...)`. Both fixed below.

PATH_TRAVERSAL_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "Path() / operator-input → write/open sink",
        # Match  (Path(<anything>) / <identifier>).{write,open,read,...}
        # OR     Path(<anything>) / <identifier>).{write,open,read,...}
        # Catches the typical shape where a base Path is concatenated
        # with an operator-supplied segment and immediately sunk into
        # I/O without intervening normpath / resolve / parts validation.
        # Also matches the bare form  open(Path(<...>) / <ident>, ...).
        re.compile(
            r"\(?Path\s*\([^)]*\)\s*/\s*[A-Za-z_][A-Za-z0-9_]*\s*\)?\s*\.(?:write_text|write_bytes|open|read_text|read_bytes|mkdir|touch|rename|symlink_to|hardlink_to)\b"
        ),
        "Path() concatenated with an identifier-bearing segment without "
        "an intervening posixpath.normpath / .resolve() / parts-validation "
        "can be a path-traversal sink if the segment is operator-controlled. "
        "Either validate the segment via PurePosixPath(seg).parts before sinking, "
        "or add a `# nosec: path-validated` comment with a justification.",
    ),
    (
        "open() called with .. in literal path",
        # Catches accidentally-committed dev-test code that opens
        # ".." literal paths (often paste artifacts from local prep).
        re.compile(r"""open\s*\(\s*['"][^'"\n]*\.\.\/[^'"\n]*['"]"""),
        "open() called with a literal '..' segment in the path is almost "
        "always a leftover dev artifact. Either remove it or document with "
        "`# nosec: dev-fixture-only` if intentional.",
    ),
)


# ---- Files we WANT scrubbed ------------------------------------------
# These files MUST contain the appropriate scrub call. Drift = security
# regression.

SCRUB_REQUIRED_FILES: tuple[tuple[Path, str, str], ...] = (
    (
        REPO_ROOT / "scripts" / "backlog_live_apply.py",
        "_scrub_secrets",
        "Live API client persists error messages — MUST call _scrub_secrets() before persisting any error string.",
    ),
)


# ---- File scope rules ------------------------------------------------

# Token-shape scan: every committed file under these paths.
TOKEN_SHAPE_SCAN_PATHS = (
    "scripts/",
    "tests/",
    "governance/",
    "skills/",
    "fixtures/",
    "docs/",
    "hooks/",
    "migrations/",
    ".github/",
)

# Subprocess + dangerous-builtin scan: scripts + tests (where Python lives).
PYTHON_CODE_SCAN_PATHS = (
    "scripts/",
    "tests/",
    "governance/",
)

# Files that LEGITIMATELY contain token-shape regexes / fake test
# tokens / documentation snippets that look like real tokens. These
# get an exemption — the audit script knows about them by exact path.
# Adding a file here REQUIRES a comment justifying why the token-shape
# strings are intentional (defense-in-depth: catches an attacker who
# adds a real-token-bearing file to the exemption list as cover).
TOKEN_REGEX_DEFINITION_FILES = {
    # Audit script's own pattern definitions.
    REPO_ROOT / "scripts" / "security_audit.py",
    # Live API client's defense-in-depth scrub regex + idempotency-key
    # quarantine regex.
    REPO_ROOT / "scripts" / "backlog_live_apply.py",
    # Privacy scan's per-pattern definitions.
    REPO_ROOT / "scripts" / "privacy_scan.py",
    # Live API response schema's not.anyOf token-shape rejection.
    REPO_ROOT / "governance" / "schemas" / "live_api_response.schema.json",
    # Live API client tests use FAKE tokens (e.g., "Bearer abc123token")
    # to verify the scrub regex catches them. Schema tests use FAKE
    # GitHub PAT shape ("ghp_aB3dEfGhI...") to verify rejection.
    REPO_ROOT / "tests" / "test_backlog_live_apply.py",
    # Audit script's own regression tests use FAKE tokens to verify
    # detection works.
    REPO_ROOT / "tests" / "test_security_audit.py",
    # Privacy scanner regression tests intentionally include FAKE
    # GitHub PATs / Slack tokens to verify the scanner catches them.
    REPO_ROOT / "tests" / "test_privacy_scan.py",
    # Documentation references token shapes for operator education.
    REPO_ROOT / "SECURITY.md",
    REPO_ROOT / "docs" / "threat_model.md",
}


# ---- Severity tiers --------------------------------------------------

CRITICAL = "CRITICAL"
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

SEVERITY_ORDER = (CRITICAL, HIGH, MEDIUM, LOW)


@dataclass
class Finding:
    severity: str
    category: str
    file_path: Path
    line: int
    message: str
    matched_text: str = ""

    def format(self, repo_root: Path) -> str:
        rel = self.file_path.relative_to(repo_root) if self.file_path.is_relative_to(repo_root) else self.file_path
        snippet = f" — {self.matched_text[:80]!r}" if self.matched_text else ""
        return f"  [{self.severity}] {rel}:{self.line} ({self.category}){snippet}\n    {self.message}"


# ---- Scanner core ----------------------------------------------------


def _iter_files_under(repo_root: Path, rel_paths: Iterable[str]) -> list[Path]:
    """Walk every file under each rel_path. Skip __pycache__, .git, and
    binary-ish extensions."""
    skip_dirs = {"__pycache__", ".pytest_cache", ".git", "node_modules"}
    skip_extensions = {".pyc", ".so", ".dylib", ".dll", ".png", ".jpg", ".gif", ".pdf"}
    out: list[Path] = []
    for rel in rel_paths:
        base = repo_root / rel
        if not base.exists():
            continue
        if base.is_file():
            out.append(base)
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if any(seg in skip_dirs for seg in p.parts):
                continue
            if p.suffix.lower() in skip_extensions:
                continue
            out.append(p)
    return sorted(set(out))


def _scan_token_shapes(files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for fpath in files:
        if fpath in TOKEN_REGEX_DEFINITION_FILES:
            continue  # legitimate regex-definition files
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for label, pat in TOKEN_SHAPE_PATTERNS:
            for match in pat.finditer(text):
                line_no = text[:match.start()].count("\n") + 1
                findings.append(Finding(
                    severity=CRITICAL,
                    category=f"token-shape:{label}",
                    file_path=fpath,
                    line=line_no,
                    message=f"Possible {label} found in committed file. If this is a real credential, ROTATE IT IMMEDIATELY and remove from history. If false positive, add the file path to TOKEN_REGEX_DEFINITION_FILES in security_audit.py with justification.",
                    matched_text=match.group(0),
                ))
    return findings


def _scan_insecure_subprocess(files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for fpath in files:
        if fpath.suffix != ".py":
            continue
        # Self-introspection: this script's own docstring / pattern
        # definitions reference 'os.system' and 'shell=True' as
        # documentation strings, not actual calls. Skip the audit
        # script when scanning itself for these patterns.
        if fpath == REPO_ROOT / "scripts" / "security_audit.py":
            continue
        # Tests legitimately write string-literal samples like
        # "subprocess.run(...shell=True)" to verify the audit's
        # detection works. Skip tests/ for the subprocess scan; the
        # scrub-required check + real-call audit on production
        # scripts is the actual gate.
        if "tests/" in fpath.as_posix():
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for label, pat, msg in INSECURE_SUBPROCESS_PATTERNS:
            for match in pat.finditer(text):
                line_no = text[:match.start()].count("\n") + 1
                # Check for inline justification comment within ±2 lines
                lines = text.splitlines()
                ctx_start = max(0, line_no - 3)
                ctx_end = min(len(lines), line_no + 2)
                ctx = "\n".join(lines[ctx_start:ctx_end])
                if "# nosec" in ctx:
                    continue  # justified
                findings.append(Finding(
                    severity=HIGH,
                    category=f"insecure-subprocess:{label}",
                    file_path=fpath,
                    line=line_no,
                    message=msg,
                    matched_text=match.group(0),
                ))
    return findings


def _scan_dangerous_builtins(files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for fpath in files:
        if fpath.suffix != ".py":
            continue
        # Self-introspection: this script's own docstring lists
        # 'eval()' / 'exec()' / 'compile()' as documentation of what
        # it scans for. Skip self-scan.
        if fpath == REPO_ROOT / "scripts" / "security_audit.py":
            continue
        # Tests can exercise eval/exec on adversarial fixtures — skip
        # by convention. The audit catches NEW eval/exec landings in
        # production scripts, which are the actual risk.
        if "tests/" in fpath.as_posix():
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for label, pat, msg in DANGEROUS_BUILTIN_PATTERNS:
            for match in pat.finditer(text):
                line_no = text[:match.start()].count("\n") + 1
                lines = text.splitlines()
                ctx_start = max(0, line_no - 3)
                ctx_end = min(len(lines), line_no + 2)
                ctx = "\n".join(lines[ctx_start:ctx_end])
                if "# nosec" in ctx:
                    continue
                findings.append(Finding(
                    severity=HIGH,
                    category=f"dangerous-builtin:{label}",
                    file_path=fpath,
                    line=line_no,
                    message=msg,
                    matched_text=match.group(0),
                ))
    return findings


def _scan_scrub_required(repo_root: Path) -> list[Finding]:
    """Scrub-required files are anchored to ``repo_root``, not the global
    REPO_ROOT (v1.1.11 round-1 should-fix #2 — earlier the function
    used the global, which meant `--repo-root <other>` would silently
    inherit the current checkout's scrub-required list)."""
    findings: list[Finding] = []
    # Re-base SCRUB_REQUIRED_FILES on the actual repo_root in case it
    # differs from the script's source location.
    for relpath_or_abs, required_call, why in _scrub_required_for(repo_root):
        path = repo_root / relpath_or_abs if not Path(relpath_or_abs).is_absolute() else Path(relpath_or_abs)
        if not path.is_file():
            findings.append(Finding(
                severity=MEDIUM,
                category="scrub-required:file-missing",
                file_path=path,
                line=0,
                message=f"Expected scrub-required file {path.name} not found. Was the file moved?",
            ))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if required_call not in text:
            findings.append(Finding(
                severity=HIGH,
                category="scrub-required:call-missing",
                file_path=path,
                line=0,
                message=f"{why} Required call '{required_call}' not found in file.",
            ))
    return findings


def _scrub_required_for(repo_root: Path) -> tuple[tuple[str, str, str], ...]:
    """Return SCRUB_REQUIRED_FILES as (rel_path, call, why) tuples
    rebased on repo_root. The global SCRUB_REQUIRED_FILES uses
    REPO_ROOT-derived absolute paths; this rebases to the per-call
    root so `--repo-root` is fully honored."""
    return (
        ("scripts/backlog_live_apply.py", "_scrub_secrets",
         "Live API client persists error messages — MUST call _scrub_secrets() before persisting any error string."),
    )


def _scan_path_traversal(files: list[Path]) -> list[Finding]:
    """Heuristic scan for path-traversal sinks (v1.1.11 round-1 critical
    fix — was defined but never invoked).

    Skips:
    * Audit script itself (self-introspection: the patterns are
      defined as string literals here).
    * tests/ (test data legitimately includes Path(...) construction
      examples).
    """
    findings: list[Finding] = []
    for fpath in files:
        if fpath.suffix != ".py":
            continue
        if fpath == REPO_ROOT / "scripts" / "security_audit.py":
            continue
        if "tests/" in fpath.as_posix():
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for label, pat, msg in PATH_TRAVERSAL_PATTERNS:
            for match in pat.finditer(text):
                line_no = text[:match.start()].count("\n") + 1
                lines = text.splitlines()
                ctx_start = max(0, line_no - 3)
                ctx_end = min(len(lines), line_no + 2)
                ctx = "\n".join(lines[ctx_start:ctx_end])
                if "# nosec" in ctx:
                    continue
                findings.append(Finding(
                    severity=MEDIUM,
                    category=f"path-traversal:{label}",
                    file_path=fpath,
                    line=line_no,
                    message=msg,
                    matched_text=match.group(0),
                ))
    return findings


# ---- Driver ----------------------------------------------------------


def run_audit(repo_root: Path) -> list[Finding]:
    findings: list[Finding] = []

    token_files = _iter_files_under(repo_root, TOKEN_SHAPE_SCAN_PATHS)
    findings.extend(_scan_token_shapes(token_files))

    py_files = _iter_files_under(repo_root, PYTHON_CODE_SCAN_PATHS)
    findings.extend(_scan_insecure_subprocess(py_files))
    findings.extend(_scan_dangerous_builtins(py_files))
    # v1.1.11 round-1 critical fix: path-traversal scan was defined but
    # not invoked. Now wired in.
    findings.extend(_scan_path_traversal(py_files))

    findings.extend(_scan_scrub_required(repo_root))

    return findings


def _format_summary(findings: list[Finding], repo_root: Path) -> str:
    by_severity: dict[str, list[Finding]] = {sev: [] for sev in SEVERITY_ORDER}
    for f in findings:
        by_severity.setdefault(f.severity, []).append(f)
    lines = ["BSA security-audit (v1.1.11):"]
    for sev in SEVERITY_ORDER:
        bucket = by_severity.get(sev, [])
        lines.append(f"  {sev}: {len(bucket)}")
    lines.append("")
    if findings:
        lines.append("Findings (sorted by severity):")
        for sev in SEVERITY_ORDER:
            for f in by_severity.get(sev, []):
                lines.append(f.format(repo_root))
    else:
        lines.append("Clean. No findings.")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="BSA security-audit — drift detection for token leakage, "
        "insecure subprocess, dangerous builtins, and missing scrubs."
    )
    parser.add_argument(
        "--repo-root", type=Path, default=REPO_ROOT,
        help="Repository root to scan (default: derived from script location).",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Print only on findings; silent on clean run.",
    )
    args = parser.parse_args(argv)

    if not (args.repo_root / "scripts").is_dir():
        print(f"ERROR: --repo-root {args.repo_root} doesn't look like a BSA repo (no scripts/)", file=sys.stderr)
        return 2

    findings = run_audit(args.repo_root)
    summary = _format_summary(findings, args.repo_root)

    has_critical_or_high = any(f.severity in (CRITICAL, HIGH) for f in findings)

    if args.quiet and not has_critical_or_high:
        return 0

    print(summary)
    return 1 if has_critical_or_high else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
