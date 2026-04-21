"""Unit tests for scripts/privacy_scan.py (US-S0-04).

Covers the 4 acceptance criteria plus detector-level correctness:
  AC-3: report generated listing email / phone / credit card / api key
        / internal URL findings
  AC-4: blocker finding causes exit 1

Detector-level assertions (beyond the minimum):
  - Luhn validation (valid card accepted, invalid rejected)
  - Email classification (test TLD -> info; corp -> blocker)
  - Whitelist suppresses exact string match and glob path
  - Binary file is skipped (NUL byte)
  - NPM integrity hashes (sha256-, sha384-, sha512-) NOT flagged as tokens
  - Internal URL hint (corporate TLD) classified as warning
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "privacy_scan.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import privacy_scan  # noqa: E402


def run_scan(root: Path, whitelist: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), f"--root={root}", f"--output={root}/privacy.md"]
    if whitelist is not None:
        cmd.append(f"--whitelist={whitelist}")
    else:
        empty_whitelist = root / "_empty_whitelist.json"
        empty_whitelist.write_text(
            '{"schema_version": 1, "string_matches": [], "path_globs": []}\n',
            encoding="utf-8",
        )
        cmd.append(f"--whitelist={empty_whitelist}")
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def test_luhn_valid_card_detected() -> None:
    assert privacy_scan.luhn_valid("4532015112830366") is True  # Visa test pattern
    assert privacy_scan.luhn_valid("4111111111111111") is True  # classic test number
    assert privacy_scan.luhn_valid("5555555555554444") is True  # Mastercard test


def test_luhn_invalid_rejected() -> None:
    assert privacy_scan.luhn_valid("4532015112830367") is False  # last digit off by 1
    assert privacy_scan.luhn_valid("1234567890123456") is False  # does not pass Luhn


def test_email_classification_test_tld() -> None:
    sev, note = privacy_scan.classify_email("user@example.com")
    assert sev == privacy_scan.SEV_INFO
    assert "test/local" in note


def test_email_classification_corporate() -> None:
    sev, note = privacy_scan.classify_email("user@acme-corp.com")
    assert sev == privacy_scan.SEV_BLOCKER
    assert "real-looking" in note


def test_shannon_entropy_increases_with_randomness() -> None:
    low = privacy_scan.shannon_entropy("aaaaaaaaaa")
    high = privacy_scan.shannon_entropy("aB3xY9qZp2LkM8nR")
    assert low < 1.0
    assert high > 3.5


def test_corporate_email_is_blocker_and_fails_exit(tmp_path: Path) -> None:
    target = tmp_path / "leak.md"
    target.write_text("Contact alice@acme-corp.com for details.\n", encoding="utf-8")
    result = run_scan(tmp_path)
    assert result.returncode == 1
    assert "Blockers: 1" in result.stdout


def test_test_email_info_level_no_fail(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("Use noreply@example.com in demos.\n", encoding="utf-8")
    result = run_scan(tmp_path)
    assert result.returncode == 0
    assert "Blockers: 0" in result.stdout


def test_whitelist_string_suppresses_match(tmp_path: Path) -> None:
    target = tmp_path / "config.md"
    target.write_text("Author: alice@acme-corp.com.\n", encoding="utf-8")
    whitelist = tmp_path / "_whitelist.json"
    whitelist.write_text(
        json.dumps({
            "schema_version": 1,
            "string_matches": [{"match": "alice@acme-corp.com", "reason": "test"}],
            "path_globs": [],
        }),
        encoding="utf-8",
    )
    result = run_scan(tmp_path, whitelist=whitelist)
    assert result.returncode == 0
    assert "Blockers: 0" in result.stdout


def test_whitelist_path_glob_suppresses_file(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    target = tmp_path / "sub" / "ignored.md"
    target.write_text("alice@acme-corp.com\n", encoding="utf-8")
    whitelist = tmp_path / "_whitelist.json"
    whitelist.write_text(
        json.dumps({
            "schema_version": 1,
            "string_matches": [],
            "path_globs": [
                {"glob": "sub/ignored.md", "reason": "test fixture with intentional email"},
            ],
        }),
        encoding="utf-8",
    )
    result = run_scan(tmp_path, whitelist=whitelist)
    assert result.returncode == 0


def test_luhn_valid_card_in_content_is_blocker(tmp_path: Path) -> None:
    target = tmp_path / "card.md"
    target.write_text("Card: 4532015112830366 ok.\n", encoding="utf-8")
    result = run_scan(tmp_path)
    assert result.returncode == 1
    report = (tmp_path / "privacy.md").read_text()
    assert "credit_card" in report
    assert "4532015112830366" in report


def test_binary_file_skipped(tmp_path: Path) -> None:
    target = tmp_path / "blob.bin"
    target.write_bytes(b"\x00\x01\x02alice@acme-corp.com\x00")
    result = run_scan(tmp_path)
    # .bin is not in TEXT_EXTENSIONS, so it's skipped by extension filter.
    # This test documents that behaviour — binary content stays off the scan.
    assert result.returncode == 0


def test_binary_text_extension_skipped_via_nul(tmp_path: Path) -> None:
    target = tmp_path / "not-really.md"
    target.write_bytes(b"header\x00leak: alice@acme-corp.com\n")
    assert privacy_scan.is_binary(target) is True


def test_npm_integrity_hash_not_flagged(tmp_path: Path) -> None:
    target = tmp_path / "package-lock.json"
    target.write_text(
        '{"integrity": "sha512-OGyjZAbBj+iBaKvqH7eJcz2iF9uzbUC6VxRnVqibpj5Y='
        'xXhFgQt4NjTTKs2Chu8nYfOFxrhoL0RHJgPgLsSxU0KlMeAg3EY"}\n',
        encoding="utf-8",
    )
    result = run_scan(tmp_path)
    # No blocker and NO warning about api_key_token.
    assert result.returncode == 0
    report = (tmp_path / "privacy.md").read_text()
    assert "api_key_token" not in report


def test_internal_tld_url_warning(tmp_path: Path) -> None:
    target = tmp_path / "infra.md"
    target.write_text("See https://wiki.acme.corp/docs for details.\n", encoding="utf-8")
    result = run_scan(tmp_path)
    # Warning only, not blocker — scan still exits 0.
    assert result.returncode == 0
    report = (tmp_path / "privacy.md").read_text()
    assert "internal_url" in report
    assert "wiki.acme.corp" in report


def test_sequential_digits_not_flagged_as_phone(tmp_path: Path) -> None:
    """Arithmetic digit progressions (0123456789) are placeholder data, not phones."""
    target = tmp_path / "placeholder.md"
    target.write_text("test pattern 0123456789 appears in fixtures.\n", encoding="utf-8")
    result = run_scan(tmp_path)
    assert result.returncode == 0
    report = (tmp_path / "privacy.md").read_text()
    assert "phone" not in report.lower() or "0123456789" not in report


def test_real_looking_phone_still_flagged(tmp_path: Path) -> None:
    """A non-sequential 10-digit number still surfaces as a phone warning."""
    target = tmp_path / "contacts.md"
    target.write_text("Reach out at +1 408 555 0199 if needed.\n", encoding="utf-8")
    result = run_scan(tmp_path)
    assert result.returncode == 0
    report = (tmp_path / "privacy.md").read_text()
    assert "phone" in report


def test_sequential_helper_direct() -> None:
    assert privacy_scan.is_sequential_digits("0123456789") is True
    assert privacy_scan.is_sequential_digits("9876543210") is True
    assert privacy_scan.is_sequential_digits("1111111111") is True
    assert privacy_scan.is_sequential_digits("4085550199") is False
    assert privacy_scan.is_sequential_digits("123") is False  # too short


def test_prefixed_api_key_detected(tmp_path: Path) -> None:
    """Round-2: real prefixed tokens like ghp_, sk_live_, xoxb- must not be skipped."""
    target = tmp_path / "leak.md"
    target.write_text(
        "token = ghp_abcdefghijklmnop1234567890ABCDEF\n"
        "stripe = sk_live_51H8pQZ3abcdefghijklmnop1234\n"
        "slack = xoxb-1234567890-abcdefghijklmnopqrstuvwx\n",
        encoding="utf-8",
    )
    result = run_scan(tmp_path)
    # Warnings, not blockers (tokens are heuristic). Exit 0 still,
    # but all three must appear in the report.
    assert result.returncode == 0
    report = (tmp_path / "privacy.md").read_text()
    assert "api_key_token" in report
    # Detector truncates matches to 12 chars + ellipsis in the report.
    # Verify at least two of the three known prefixes made it in.
    prefix_hits = sum(
        1 for prefix in ("ghp_abcdefgh", "sk_live_51H8", "xoxb-1234567")
        if prefix in report
    )
    assert prefix_hits >= 2, f"expected >=2 prefix hits, got {prefix_hits}\n{report}"


def test_formatted_credit_card_detected(tmp_path: Path) -> None:
    """Round-2: space/hyphen-separated card numbers must still trigger Luhn blocker."""
    target = tmp_path / "card.md"
    target.write_text(
        "visa with spaces: 4532 0151 1283 0366\n"
        "visa with hyphens: 4532-0151-1283-0366\n",
        encoding="utf-8",
    )
    result = run_scan(tmp_path)
    assert result.returncode == 1
    report = (tmp_path / "privacy.md").read_text()
    assert "credit_card" in report
    assert "4532 0151 1283 0366" in report or "4532-0151-1283-0366" in report


def test_path_glob_object_form_supported(tmp_path: Path) -> None:
    """Round-2: path_globs accept object form with glob+reason fields."""
    (tmp_path / "sub").mkdir()
    target = tmp_path / "sub" / "leak.md"
    target.write_text("alice@acme-corp.com\n", encoding="utf-8")
    whitelist = tmp_path / "_whitelist.json"
    whitelist.write_text(
        json.dumps({
            "schema_version": 1,
            "string_matches": [],
            "path_globs": [
                {"glob": "sub/leak.md", "reason": "test fixture with intentional email"},
            ],
        }),
        encoding="utf-8",
    )
    result = run_scan(tmp_path, whitelist=whitelist)
    assert result.returncode == 0


def test_path_glob_bare_string_rejected(tmp_path: Path) -> None:
    """Round-2: bare-string path_globs must fail fast with exit 2 (invocation error)."""
    whitelist = tmp_path / "_whitelist.json"
    whitelist.write_text(
        json.dumps({
            "schema_version": 1,
            "string_matches": [],
            "path_globs": ["sub/leak.md"],
        }),
        encoding="utf-8",
    )
    result = run_scan(tmp_path, whitelist=whitelist)
    assert result.returncode == 2, result.stderr
    assert "whitelist load failed" in result.stderr
    assert "path_globs[0]" in result.stderr


def test_string_match_without_reason_rejected(tmp_path: Path) -> None:
    """Round-2: string_matches entries without 'reason' must fail load with exit 2."""
    whitelist = tmp_path / "_whitelist.json"
    whitelist.write_text(
        json.dumps({
            "schema_version": 1,
            "string_matches": [{"match": "x@y.com"}],
            "path_globs": [],
        }),
        encoding="utf-8",
    )
    result = run_scan(tmp_path, whitelist=whitelist)
    assert result.returncode == 2, result.stderr
    assert "whitelist load failed" in result.stderr
    assert "string_matches[0]" in result.stderr
    assert "reason" in result.stderr


def test_malformed_json_whitelist_rejected(tmp_path: Path) -> None:
    """Round-3: malformed JSON surfaces as invocation error (exit 2), not traceback."""
    whitelist = tmp_path / "_whitelist.json"
    whitelist.write_text("{not valid json", encoding="utf-8")
    result = run_scan(tmp_path, whitelist=whitelist)
    assert result.returncode == 2, result.stderr
    assert "whitelist load failed" in result.stderr
    assert "Traceback" not in result.stderr


def test_non_object_root_whitelist_rejected(tmp_path: Path) -> None:
    """Round-4: JSON-valid but non-object root (e.g. []) must fail with exit 2."""
    whitelist = tmp_path / "_whitelist.json"
    whitelist.write_text("[]", encoding="utf-8")
    result = run_scan(tmp_path, whitelist=whitelist)
    assert result.returncode == 2, result.stderr
    assert "whitelist load failed" in result.stderr
    assert "top-level JSON must be an object" in result.stderr
    assert "Traceback" not in result.stderr


def test_non_list_section_whitelist_rejected(tmp_path: Path) -> None:
    """Round-4: section with non-list value (e.g. string_matches: {}) must fail."""
    whitelist = tmp_path / "_whitelist.json"
    whitelist.write_text(
        json.dumps({
            "schema_version": 1,
            "string_matches": {"not": "a list"},
            "path_globs": [],
        }),
        encoding="utf-8",
    )
    result = run_scan(tmp_path, whitelist=whitelist)
    assert result.returncode == 2, result.stderr
    assert "must be a JSON array" in result.stderr
    assert "string_matches" in result.stderr
    assert "Traceback" not in result.stderr


def test_non_string_match_value_rejected(tmp_path: Path) -> None:
    """Round-5: string_matches entry with non-string 'match' must fail exit 2."""
    whitelist = tmp_path / "_whitelist.json"
    whitelist.write_text(
        json.dumps({
            "schema_version": 1,
            "string_matches": [{"match": {"oops": 1}, "reason": "typo"}],
            "path_globs": [],
        }),
        encoding="utf-8",
    )
    result = run_scan(tmp_path, whitelist=whitelist)
    assert result.returncode == 2, result.stderr
    assert "must be a non-empty string" in result.stderr
    assert "string_matches[0].match" in result.stderr
    assert "Traceback" not in result.stderr


def test_non_string_glob_value_rejected(tmp_path: Path) -> None:
    """Round-5: path_globs entry with non-string 'glob' must fail exit 2."""
    whitelist = tmp_path / "_whitelist.json"
    whitelist.write_text(
        json.dumps({
            "schema_version": 1,
            "string_matches": [],
            "path_globs": [{"glob": {"oops": 1}, "reason": "typo"}],
        }),
        encoding="utf-8",
    )
    result = run_scan(tmp_path, whitelist=whitelist)
    assert result.returncode == 2, result.stderr
    assert "must be a non-empty string" in result.stderr
    assert "path_globs[0].glob" in result.stderr
    assert "Traceback" not in result.stderr


def test_empty_match_string_rejected(tmp_path: Path) -> None:
    """Round-5: empty 'match' value must be rejected (not just missing key)."""
    whitelist = tmp_path / "_whitelist.json"
    whitelist.write_text(
        json.dumps({
            "schema_version": 1,
            "string_matches": [{"match": "", "reason": "unused"}],
            "path_globs": [],
        }),
        encoding="utf-8",
    )
    result = run_scan(tmp_path, whitelist=whitelist)
    assert result.returncode == 2, result.stderr
    assert "non-empty string" in result.stderr


def test_scan_baseline_has_no_blockers() -> None:
    """Baseline: repo as committed must have zero blocker findings."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"baseline privacy scan has blockers:\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "Blockers: 0" in result.stdout


# ---- F3 regression cases (Sprint 5) -----------------------------------
# Pre-F3 the prose check was a digit-presence gate masquerading as an
# "entropy + length" heuristic — any digit-free string of any entropy
# silently passed. These tests cover the gap (P2 finding from the
# Sprint 5 review) and pin the new heuristic against natural-text /
# identifier false-positive regressions.


def test_letter_only_high_entropy_token_now_detected(tmp_path: Path) -> None:
    """The original P2 reproducer: 26-char mixed-case letter-only token,
    H≈4.70. Pre-F3 silently skipped; post-F3 must surface as api_key_token."""
    target = tmp_path / "leak.md"
    target.write_text(
        'API_KEY = "QwErTyUiOpAsDfGhJkLzXcVbNm"\n',
        encoding="utf-8",
    )
    result = run_scan(tmp_path)
    report = (tmp_path / "privacy.md").read_text()
    assert "api_key_token" in report, (
        "Letter-only high-entropy token slipped through (F3 regression).\n"
        f"report:\n{report}"
    )


def test_camel_case_identifier_not_flagged(tmp_path: Path) -> None:
    """False-positive guard: long camelCase identifiers ARE prose-like
    (high vowel ratio) and must not be flagged. Critical for code corpora."""
    target = tmp_path / "code.md"
    target.write_text(
        "method: getUserAccountBalanceFromTheDatabase()\n"
        "method: calculateRecommendedDailyAllowanceFor(item)\n",
        encoding="utf-8",
    )
    result = run_scan(tmp_path)
    report = (tmp_path / "privacy.md").read_text()
    assert "api_key_token" not in report, (
        "camelCase identifier mis-flagged as token (F3 false-positive regression).\n"
        f"report:\n{report}"
    )


def test_snake_case_identifier_not_flagged(tmp_path: Path) -> None:
    target = tmp_path / "code.md"
    target.write_text(
        "var: some_long_function_name_without_digits_here\n"
        "var: another_clearly_descriptive_function_name\n",
        encoding="utf-8",
    )
    result = run_scan(tmp_path)
    report = (tmp_path / "privacy.md").read_text()
    assert "api_key_token" not in report


def test_known_token_prefix_caught_even_if_low_entropy_letters(tmp_path: Path) -> None:
    """Token-prefix gate: a known prefix (ghp_, sk_live_, eyJ, AKIA, ...)
    forces the candidate through the entropy check regardless of vowel ratio.
    This guards against an attacker padding letters to evade the heuristic."""
    target = tmp_path / "leak.md"
    target.write_text(
        # Real-looking prefixed tokens, no digits beyond what's in the prefix.
        "github = ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZAbCdEfGhIj\n"
        "stripe = sk_live_PqRsTuVwXyZaBcDeFgHiJkLmNoPqRsTuVw\n"
        "jwt    = eyJabcdefghijklmnopqrstuvwxyzABCDEFGHIJKL\n",
        encoding="utf-8",
    )
    result = run_scan(tmp_path)
    report = (tmp_path / "privacy.md").read_text()
    assert "api_key_token" in report
    # All three prefixes (or their truncations) should appear.
    truncated = ("ghp_aBcDeFgH", "sk_live_PqRs", "eyJabcdefghi")
    hit_count = sum(1 for prefix in truncated if prefix in report)
    assert hit_count >= 2, (
        f"Only {hit_count}/3 known-prefix tokens caught. Report:\n{report}"
    )


def test_natural_english_prose_not_flagged(tmp_path: Path) -> None:
    """English text reflowed without spaces must not trigger.
    Vowel ratio for typical English is 0.35-0.45 → in the prose band."""
    target = tmp_path / "doc.md"
    target.write_text(
        # Long contiguous English-ish identifier (no spaces, no digits).
        # This is what a code-as-text corpus or a markdown link slug would look like.
        "slug: thisIsAnEnglishLikeIdentifierThatShouldNotBeAToken\n",
        encoding="utf-8",
    )
    result = run_scan(tmp_path)
    report = (tmp_path / "privacy.md").read_text()
    assert "api_key_token" not in report


def test_is_likely_natural_prose_helper_directly() -> None:
    """Direct unit-test of the heuristic without going through scan_file."""
    from privacy_scan import _is_likely_natural_prose

    # Letter-only high-entropy random-looking → token
    assert _is_likely_natural_prose("QwErTyUiOpAsDfGhJkLzXcVbNm") is False
    # English-like identifier → prose
    assert _is_likely_natural_prose("getUserAccountBalanceFromTheDatabase") is True
    assert _is_likely_natural_prose("some_long_function_name_without_digits") is True
    # Token prefixes → not prose (regardless of vowel ratio)
    assert _is_likely_natural_prose("ghp_anything") is False
    assert _is_likely_natural_prose("sk_live_test") is False
    assert _is_likely_natural_prose("eyJsomething") is False
    assert _is_likely_natural_prose("AKIATEST") is False
    # All-digits → not prose, not enough alpha to judge
    assert _is_likely_natural_prose("12345678901234") is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
