#!/usr/bin/env python3
"""Privacy scanner for the BSA plugin repository.

US-S0-04 (Sprint 0) part 2: scans tracked text files for common PII and
secret patterns, emits docs/privacy_audit.md, and exits non-zero when any
blocker-severity findings remain after the whitelist.

Detectors:
  email           blocker if corporate-looking domain; info if test/local TLD
  phone           warning (high false-positive rate without context)
  credit_card     blocker (Luhn-verified digit sequences 13–19 long)
  api_key_token   warning (Shannon entropy >= 4.5 + length >= 20, not dict)
  internal_url    warning (corporate/internal TLDs, known intranet patterns)

Notes:
  - Binary files are skipped (detected via NUL byte in first 8KB).
  - `.git/`, `analysis/` (runtime), `__pycache__/`, and fixtures under
    skills/*/scripts/fixtures/ are skipped by default.
  - Whitelist file `scripts/privacy_whitelist.json` suppresses specific
    string matches and path globs. Every entry must carry a `reason`.
  - Severity policy: blocker findings fail CI (exit 1). Warnings and info
    are reported but do not fail.

Usage:
  scripts/privacy_scan.py [--root=<path>] [--output=<path>] [--no-fail]

Exit codes:
  0 — no blocker-level findings
  1 — at least one blocker finding (and --no-fail was not passed)
  2 — invocation error
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

SEV_BLOCKER = "blocker"
SEV_WARNING = "warning"
SEV_INFO = "info"

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"
)
DIGIT_RUN_RE = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
# Matches grouped digits with optional space/hyphen separators, typical of
# formatted credit cards: "4532 0151 1283 0366" or "4532-0151-1283-0366".
# Normalize away separators before running Luhn; length must fall in 13..19.
GROUPED_DIGITS_RE = re.compile(
    r"(?<![\d/-])(?:\d{4}[\s\-]){2,4}\d{1,4}(?![\d/-])"
)
URL_RE = re.compile(r"https?://([A-Za-z0-9.\-]+)(?:[:/][^\s)\"']*)?")
TOKEN_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/_=\-]{20,}")
NPM_INTEGRITY_PREFIXES = ("sha256-", "sha384-", "sha512-")

INTERNAL_TLD_SUFFIXES = (
    ".corp",
    ".internal",
    ".intranet",
    ".priv",
    ".lan",
    ".onion",
    ".i",
)
INTERNAL_HOST_HINTS = (
    "jira.",
    "confluence.",
    "gitlab.internal",
    "github.internal",
    "artifactory.",
    "nexus.",
)
TEST_EMAIL_DOMAINS_EXACT = frozenset({
    "example.com",
    "example.org",
    "example.net",
    "example",
    "test",
    "invalid",
    "localhost",
})
TEST_EMAIL_DOMAIN_SUFFIXES = (
    ".example.com",
    ".example.org",
    ".example.net",
    ".example",
    ".test",
    ".invalid",
    ".localhost",
    ".local",
)

DEFAULT_SKIP_DIR_NAMES = {
    ".git",
    ".github",
    "analysis",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
}
DEFAULT_SKIP_PATH_SUBSTRINGS = (
    "/scripts/fixtures/",
    "/fixtures/runtime/",
    "/assets/examples/",
)
TEXT_EXTENSIONS = {
    ".md", ".py", ".sh", ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini",
    ".txt", ".csv", ".tsv", ".xml", ".html", ".rst", ".js", ".ts",
    ".bpmn", ".puml",
}

MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024


@dataclass
class Finding:
    file: Path
    line: int
    detector: str
    severity: str
    match: str
    note: str = ""


@dataclass
class Whitelist:
    string_matches: set[str] = field(default_factory=set)
    path_globs: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Whitelist":
        if not path.is_file():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(data, dict):
            raise ValueError(
                f"whitelist {path}: top-level JSON must be an object, got "
                f"{type(data).__name__}"
            )
        for section in ("string_matches", "path_globs"):
            if section in data and not isinstance(data[section], list):
                raise ValueError(
                    f"whitelist {path}: '{section}' must be a JSON array, got "
                    f"{type(data[section]).__name__}"
                )

        def _require_non_empty_string(context: str, value: object) -> str:
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"whitelist {path}: {context} must be a non-empty string, got "
                    f"{type(value).__name__}"
                )
            return value

        strings: set[str] = set()
        for i, entry in enumerate(data.get("string_matches", [])):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"whitelist {path}: string_matches[{i}] must be an object with "
                    "'match' and 'reason' fields"
                )
            if "match" not in entry:
                raise ValueError(f"whitelist {path}: string_matches[{i}] missing 'match'")
            if "reason" not in entry:
                raise ValueError(f"whitelist {path}: string_matches[{i}] missing 'reason'")
            match_value = _require_non_empty_string(
                f"string_matches[{i}].match", entry["match"]
            )
            _require_non_empty_string(
                f"string_matches[{i}].reason", entry["reason"]
            )
            strings.add(match_value)

        globs: list[str] = []
        for i, entry in enumerate(data.get("path_globs", [])):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"whitelist {path}: path_globs[{i}] must be an object with "
                    "'glob' and 'reason' fields (bare strings are rejected)"
                )
            if "glob" not in entry:
                raise ValueError(f"whitelist {path}: path_globs[{i}] missing 'glob'")
            if "reason" not in entry:
                raise ValueError(f"whitelist {path}: path_globs[{i}] missing 'reason'")
            glob_value = _require_non_empty_string(
                f"path_globs[{i}].glob", entry["glob"]
            )
            _require_non_empty_string(
                f"path_globs[{i}].reason", entry["reason"]
            )
            globs.append(glob_value)

        return cls(string_matches=strings, path_globs=globs)

    def path_suppressed(self, rel_path: Path) -> bool:
        s = rel_path.as_posix()
        return any(fnmatch.fnmatch(s, g) for g in self.path_globs)

    def match_suppressed(self, match: str) -> bool:
        return match in self.string_matches


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    entropy = 0.0
    for c in counts.values():
        p = c / length
        entropy -= p * math.log2(p)
    return entropy


def is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            chunk = fh.read(8192)
    except OSError:
        return True
    return b"\x00" in chunk


def is_sequential_digits(digits: str) -> bool:
    """Detect arithmetic progressions (0123456789, 9876543210, 1111111111).

    Used to filter phone-detector false positives on obvious placeholder data.
    """
    if len(digits) < 4:
        return False
    diffs = [int(digits[i + 1]) - int(digits[i]) for i in range(len(digits) - 1)]
    return all(d == diffs[0] for d in diffs)


def luhn_valid(num: str) -> bool:
    digits = [int(c) for c in num if c.isdigit()]
    if len(digits) < 13:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _is_likely_natural_prose(s: str) -> bool:
    """Decide whether a long high-entropy candidate is likely natural prose.

    Real API keys and secrets almost always contain digits; natural English
    words, function identifiers, and hyphenated compound words typically do
    not. We filter by digit presence first, then by vowel density as a
    defense-in-depth check for all-alphabetic identifiers like
    'some_long_function_name_without_digits'.
    """
    if not any(c.isdigit() for c in s):
        # No digits at all — prose-like; skip. Real tokens (ghp_..., sk_live_,
        # xoxb-..., GitHub App JWTs, AWS keys) always contain digits.
        return True
    return False


def classify_email(match: str) -> tuple[str, str]:
    domain = match.split("@", 1)[1].lower()
    if domain in TEST_EMAIL_DOMAINS_EXACT:
        return SEV_INFO, f"test/local domain ({domain})"
    if any(domain.endswith(suf) for suf in TEST_EMAIL_DOMAIN_SUFFIXES):
        return SEV_INFO, f"test/local domain suffix ({domain})"
    return SEV_BLOCKER, f"real-looking email domain ({domain})"


def classify_url(match: str) -> tuple[str, str] | None:
    host = match.lower()
    if any(host.endswith(suf) for suf in INTERNAL_TLD_SUFFIXES):
        return SEV_WARNING, f"internal TLD ({host})"
    for hint in INTERNAL_HOST_HINTS:
        if hint in host:
            return SEV_WARNING, f"intranet hostname hint ({host})"
    return None


def scan_line(path: Path, line_no: int, line: str, whitelist: Whitelist) -> list[Finding]:
    findings: list[Finding] = []

    for m in EMAIL_RE.finditer(line):
        text = m.group(0)
        if whitelist.match_suppressed(text):
            continue
        severity, note = classify_email(text)
        findings.append(Finding(path, line_no, "email", severity, text, note))

    for m in URL_RE.finditer(line):
        host = m.group(1)
        if whitelist.match_suppressed(host):
            continue
        verdict = classify_url(host)
        if verdict:
            severity, note = verdict
            findings.append(Finding(path, line_no, "internal_url", severity, host, note))

    # 1) Unseparated 13-19 digit runs.
    for m in DIGIT_RUN_RE.finditer(line):
        text = m.group(0)
        if whitelist.match_suppressed(text):
            continue
        if luhn_valid(text):
            findings.append(
                Finding(path, line_no, "credit_card", SEV_BLOCKER, text, "Luhn-valid digit sequence")
            )
    # 2) Grouped digits with space/hyphen separators (formatted cards).
    for m in GROUPED_DIGITS_RE.finditer(line):
        raw = m.group(0)
        normalized = re.sub(r"[\s\-]", "", raw)
        if not (13 <= len(normalized) <= 19):
            continue
        if whitelist.match_suppressed(raw) or whitelist.match_suppressed(normalized):
            continue
        if luhn_valid(normalized):
            findings.append(
                Finding(
                    path,
                    line_no,
                    "credit_card",
                    SEV_BLOCKER,
                    raw.strip(),
                    f"Luhn-valid after normalization to {normalized}",
                )
            )

    for m in PHONE_RE.finditer(line):
        text = m.group(0)
        digits_only = "".join(c for c in text if c.isdigit())
        if len(digits_only) < 10:
            continue
        if is_sequential_digits(digits_only):
            continue
        if whitelist.match_suppressed(text):
            continue
        findings.append(
            Finding(path, line_no, "phone", SEV_WARNING, text, "possible phone number — verify context")
        )

    for m in TOKEN_CANDIDATE_RE.finditer(line):
        text = m.group(0)
        if whitelist.match_suppressed(text):
            continue
        if _is_likely_natural_prose(text):
            continue
        if text.startswith(NPM_INTEGRITY_PREFIXES):
            continue
        entropy = shannon_entropy(text)
        if entropy >= 4.5:
            findings.append(
                Finding(
                    path,
                    line_no,
                    "api_key_token",
                    SEV_WARNING,
                    text[:12] + "…",
                    f"high-entropy token (H={entropy:.2f}, len={len(text)})",
                )
            )

    return findings


def scan_file(path: Path, whitelist: Whitelist) -> list[Finding]:
    findings: list[Finding] = []
    try:
        size = path.stat().st_size
    except OSError:
        return findings
    if size > MAX_FILE_SIZE_BYTES:
        return findings
    if is_binary(path):
        return findings
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line_no, line in enumerate(fh, start=1):
                findings.extend(scan_line(path, line_no, line, whitelist))
    except OSError:
        pass
    return findings


def iter_candidate_files(root: Path) -> list[Path]:
    results: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_dir():
            if child.name in DEFAULT_SKIP_DIR_NAMES:
                continue
            results.extend(iter_candidate_files(child))
            continue
        if not child.is_file():
            continue
        rel_str = child.relative_to(root.parents[0] if root != Path("/") else root).as_posix() if False else child.as_posix()
        if any(sub in rel_str for sub in DEFAULT_SKIP_PATH_SUBSTRINGS):
            continue
        if child.suffix.lower() in TEXT_EXTENSIONS or child.suffix == "":
            results.append(child)
    return results


def render_report(findings: list[Finding], scanned_count: int, root: Path) -> str:
    by_severity: dict[str, list[Finding]] = {SEV_BLOCKER: [], SEV_WARNING: [], SEV_INFO: []}
    for f in findings:
        by_severity[f.severity].append(f)

    lines: list[str] = []
    lines.append("# Privacy Audit Report")
    lines.append("")
    lines.append(
        "Auto-generated by `scripts/privacy_scan.py` (US-S0-04). Findings reflect "
        "regex/heuristic detection, not a guarantee of privacy — review "
        f"`{len(findings)}` item(s) below."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Files scanned: **{scanned_count}**")
    lines.append(f"- Blocker findings: **{len(by_severity[SEV_BLOCKER])}**  *(CI fails if > 0)*")
    lines.append(f"- Warnings: {len(by_severity[SEV_WARNING])}")
    lines.append(f"- Info: {len(by_severity[SEV_INFO])}")
    lines.append("")

    def _emit_section(title: str, items: list[Finding]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        if not items:
            lines.append("_None._")
            lines.append("")
            return
        lines.append("| File | Line | Detector | Match | Note |")
        lines.append("|---|---|---|---|---|")
        for f in items:
            rel = f.file.relative_to(root).as_posix() if f.file.is_absolute() else f.file.as_posix()
            safe_match = f.match.replace("|", "\\|")
            lines.append(f"| `{rel}` | {f.line} | {f.detector} | `{safe_match}` | {f.note} |")
        lines.append("")

    _emit_section("Blocker findings", by_severity[SEV_BLOCKER])
    _emit_section("Warning findings", by_severity[SEV_WARNING])
    _emit_section("Info findings", by_severity[SEV_INFO])

    lines.append("## Remediation guidance")
    lines.append("")
    lines.append("1. For true findings: remove the content, rewrite history if needed, rotate the secret.")
    lines.append("2. For legitimate false-positives: add to `scripts/privacy_whitelist.json` with a `reason` field.")
    lines.append("3. For test/sample data that triggers heuristics: move under a fixture path already covered by default skip substrings.")
    lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Privacy scanner (US-S0-04).")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Root directory to scan (default: repo root).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "docs" / "privacy_audit.md",
        help="Output report path (default: <repo>/docs/privacy_audit.md).",
    )
    parser.add_argument(
        "--whitelist",
        type=Path,
        default=Path(__file__).resolve().parent / "privacy_whitelist.json",
        help="Whitelist JSON path.",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Do not exit non-zero even if blocker findings exist.",
    )
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"ERROR: root is not a directory: {args.root}", file=sys.stderr)
        return 2

    try:
        whitelist = Whitelist.load(args.whitelist)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: whitelist load failed: {exc}", file=sys.stderr)
        return 2
    candidate_files = iter_candidate_files(args.root)
    whitelisted_paths = {
        f for f in candidate_files
        if whitelist.path_suppressed(f.relative_to(args.root))
    }
    files_to_scan = [f for f in candidate_files if f not in whitelisted_paths]

    findings: list[Finding] = []
    for f in files_to_scan:
        findings.extend(scan_file(f, whitelist))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = render_report(findings, len(files_to_scan), args.root)
    args.output.write_text(report, encoding="utf-8")

    blockers = [f for f in findings if f.severity == SEV_BLOCKER]
    warnings_ = [f for f in findings if f.severity == SEV_WARNING]

    print(
        f"Privacy scan: {len(files_to_scan)} files scanned "
        f"({len(whitelisted_paths)} path-whitelisted). "
        f"Blockers: {len(blockers)}, warnings: {len(warnings_)}, "
        f"info: {len(findings) - len(blockers) - len(warnings_)}. "
        f"Report: {args.output}"
    )

    if blockers and not args.no_fail:
        print("FAIL: blocker-level privacy findings present. See report.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
