"""Tests for scripts/security_audit.py (v1.1.11, Section G).

Covers:
  * Detection: each finding category fires on a planted positive sample.
  * False-positive suppression: re.compile / ast.literal_eval / `# nosec`
    comments / TOKEN_REGEX_DEFINITION_FILES exemptions all work.
  * CLI: clean run = exit 0; finding presence = exit 1; --quiet works.
  * Self-introspection: the audit script doesn't fire on its own
    docstring listing the dangerous builtins.
  * Live state: against the actual repo HEAD, the audit MUST be clean
    (zero CRITICAL + zero HIGH). This is the regression baseline — if
    any future commit lands a real finding, the test fails.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "security_audit.py"


def _import_audit_module():
    """Load security_audit.py as a module so tests can call its helpers."""
    if "security_audit" in sys.modules:
        return sys.modules["security_audit"]
    spec = importlib.util.spec_from_file_location("security_audit", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["security_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- Live-repo regression baseline ------------------------------------


def test_live_repo_is_clean() -> None:
    """The actual repo HEAD MUST pass the audit with zero CRITICAL +
    zero HIGH findings. Any future commit that lands a real token, an
    insecure subprocess pattern, or a dangerous builtin will fail this
    test. This IS the regression baseline."""
    mod = _import_audit_module()
    findings = mod.run_audit(REPO_ROOT)
    critical_or_high = [f for f in findings if f.severity in (mod.CRITICAL, mod.HIGH)]
    assert not critical_or_high, (
        f"Live repo has {len(critical_or_high)} CRITICAL/HIGH security findings:\n"
        + "\n".join(f.format(REPO_ROOT) for f in critical_or_high)
    )


def test_subprocess_clean_exit_on_clean_repo() -> None:
    """The CLI returns 0 on a clean run."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"Live repo audit returned {result.returncode}:\n{result.stdout}\n{result.stderr}"
    )


def test_subprocess_quiet_mode_silent_on_clean(tmp_path: Path) -> None:
    """--quiet produces no stdout when the repo is clean."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--quiet"],
        capture_output=True, text=True, check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert result.stdout == "", f"--quiet produced unexpected stdout: {result.stdout!r}"


# ---- Detection: positive samples -------------------------------------
# Each test plants a single finding pattern in a temp file and verifies
# the audit catches it.


def _make_temp_repo(tmp_path: Path) -> Path:
    """Create a minimal repo skeleton (just scripts/) so the audit
    accepts it as a valid --repo-root."""
    repo = tmp_path / "fake_repo"
    repo.mkdir()
    (repo / "scripts").mkdir()
    (repo / "tests").mkdir()
    return repo


def test_detects_github_pat(tmp_path: Path) -> None:
    """A real-shape GitHub PAT (ghp_ + 36 chars) MUST be caught."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    bad_file = repo / "scripts" / "leaky.py"
    bad_file.write_text(
        "# Hardcoded credential — NOT good\n"
        'TOKEN = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    pat_findings = [f for f in findings if "GitHub PAT" in f.category]
    assert pat_findings, "GitHub PAT not detected"
    assert pat_findings[0].severity == mod.CRITICAL


def test_detects_jwt(tmp_path: Path) -> None:
    """A JWT shape (eyJ.<base64>.<base64>.<base64>) MUST be caught."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    bad_file = repo / "scripts" / "leaky.py"
    bad_file.write_text(
        'JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.signaturepartlongenough"\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    jwt_findings = [f for f in findings if "JWT" in f.category]
    assert jwt_findings, "JWT not detected"


def test_detects_bearer_credential(tmp_path: Path) -> None:
    """A 'Bearer <30+ chars>' string MUST be caught."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    bad_file = repo / "scripts" / "leaky.py"
    bad_file.write_text(
        '# Auth header sample (BAD)\n'
        'header = "Authorization: Bearer abcdefghij1234567890ABCDEFGHIJ"\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    bearer_findings = [f for f in findings if "Bearer credential" in f.category]
    assert bearer_findings, "Bearer credential not detected"


def test_detects_aws_access_key(tmp_path: Path) -> None:
    """AKIA-prefixed AWS access key MUST be caught."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    bad_file = repo / "scripts" / "leaky.py"
    bad_file.write_text(
        'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    aws_findings = [f for f in findings if "AWS access key" in f.category]
    assert aws_findings, "AWS access key not detected"


def test_detects_subprocess_shell_true(tmp_path: Path) -> None:
    """subprocess.run(..., shell=True) without # nosec MUST be flagged."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    bad_file = repo / "scripts" / "shellcall.py"
    bad_file.write_text(
        "import subprocess\n"
        'subprocess.run(["rm", "-rf", path], shell=True)\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    shell_findings = [f for f in findings if "shell=True" in f.category]
    assert shell_findings, "subprocess shell=True not detected"
    assert shell_findings[0].severity == mod.HIGH


def test_detects_os_system(tmp_path: Path) -> None:
    """os.system() MUST be flagged."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    bad_file = repo / "scripts" / "syscall.py"
    bad_file.write_text(
        "import os\n"
        'os.system("rm -rf " + path)\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    sys_findings = [f for f in findings if "os.system" in f.category]
    assert sys_findings, "os.system not detected"


def test_detects_eval_builtin(tmp_path: Path) -> None:
    """Bare eval() MUST be flagged."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    bad_file = repo / "scripts" / "evaluser.py"
    bad_file.write_text(
        "result = eval(operator_input)\n",
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    eval_findings = [f for f in findings if "eval()" in f.category]
    assert eval_findings, "Bare eval() not detected"


def test_detects_exec_builtin(tmp_path: Path) -> None:
    """Bare exec() MUST be flagged."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    bad_file = repo / "scripts" / "execer.py"
    bad_file.write_text(
        'exec("print(1)")\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    exec_findings = [f for f in findings if "exec()" in f.category]
    assert exec_findings, "Bare exec() not detected"


def test_detects_compile_builtin(tmp_path: Path) -> None:
    """Bare compile() MUST be flagged."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    bad_file = repo / "scripts" / "compiler.py"
    bad_file.write_text(
        'code = compile(src, "<string>", "exec")\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    compile_findings = [f for f in findings if "compile()" in f.category]
    assert compile_findings, "Bare compile() not detected"


def test_detects_path_concat_into_write_sink(tmp_path: Path) -> None:
    """v1.1.11 round-1 critical regression: typical path-traversal sink
    `(Path(base) / user_input).write_text(...)` MUST fire. The earlier
    regex didn't match this shape AND wasn't even wired in."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    bad_file = repo / "scripts" / "writer.py"
    bad_file.write_text(
        "from pathlib import Path\n"
        "def save(base, user_input, payload):\n"
        '    (Path(base) / user_input).write_text(payload)\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    pt_findings = [f for f in findings if "path-traversal" in f.category]
    assert pt_findings, "Path() concat → write_text sink not detected"


def test_detects_open_with_dotdot_literal(tmp_path: Path) -> None:
    """A literal '..' in an open() path string MUST fire."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    bad_file = repo / "scripts" / "leftover.py"
    bad_file.write_text(
        'with open("../parent_secret.txt") as fh:\n'
        '    data = fh.read()\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    pt_findings = [f for f in findings if "path-traversal" in f.category]
    assert pt_findings, "open() with literal '..' not detected"


def test_path_traversal_nosec_suppresses(tmp_path: Path) -> None:
    """`# nosec: path-validated` within ±2 lines suppresses the finding."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    suppressed = repo / "scripts" / "validated.py"
    suppressed.write_text(
        "from pathlib import Path\n"
        "def save(base, user_input, payload):\n"
        "    # nosec: path-validated — user_input is enum-checked upstream\n"
        '    (Path(base) / user_input).write_text(payload)\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    pt_findings = [f for f in findings if "path-traversal" in f.category]
    assert not pt_findings, f"# nosec did not suppress: {pt_findings}"


def test_repo_root_arg_isolates_scrub_required_check(tmp_path: Path) -> None:
    """v1.1.11 round-1 should-fix #2 + round-2 nice-to-have tightening:
    --repo-root must be fully honored — scrub-required paths anchored
    to the arg, not the script's source REPO_ROOT global. An empty
    temp repo MUST produce a `scrub-required:file-missing` finding
    (because backlog_live_apply.py doesn't exist in that repo) AND
    the finding's path MUST anchor under the temp repo, not the live
    checkout. Without the round-1 fix, the audit would silently
    inherit the live repo's scrub-required file and pass vacuously."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    # Empty temp repo: scripts/backlog_live_apply.py does NOT exist.
    findings = mod.run_audit(repo)
    scrub_findings = [f for f in findings if "scrub-required" in f.category]
    # Hard assertion: the scrub check MUST fire on a temp repo without
    # the live API client. Vacuous-pass would mean the audit is
    # silently anchored to the live REPO_ROOT (the round-1 bug).
    file_missing = [f for f in scrub_findings if f.category == "scrub-required:file-missing"]
    assert file_missing, (
        "scrub-required:file-missing did not fire on empty temp repo — "
        "this would happen if _scan_scrub_required is silently using "
        "the global REPO_ROOT (live checkout) instead of the passed "
        "repo_root arg (the round-1 should-fix #2 bug)."
    )
    # And every scrub-required finding's path MUST anchor under the
    # temp repo, NOT the live checkout.
    for f in file_missing:
        assert str(repo) in str(f.file_path), (
            f"scrub-required file path anchored to wrong root: "
            f"{f.file_path} (expected under {repo})"
        )


# ---- False-positive suppression -------------------------------------


def test_re_compile_does_not_fire(tmp_path: Path) -> None:
    """re.compile(...) is NOT the dangerous compile() — must NOT fire."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    good_file = repo / "scripts" / "regexer.py"
    good_file.write_text(
        "import re\n"
        'pattern = re.compile(r"foo\\d+")\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    compile_findings = [f for f in findings if "compile()" in f.category]
    assert not compile_findings, f"re.compile false-positive: {compile_findings}"


def test_attribute_eval_does_not_fire(tmp_path: Path) -> None:
    """ast.literal_eval / instance.eval are NOT the bare eval()."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    good_file = repo / "scripts" / "ast_user.py"
    good_file.write_text(
        "import ast\n"
        'value = ast.literal_eval("[1, 2, 3]")\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    eval_findings = [f for f in findings if "eval()" in f.category]
    assert not eval_findings, f"ast.literal_eval false-positive: {eval_findings}"


def test_nosec_comment_suppresses(tmp_path: Path) -> None:
    """A `# nosec: <reason>` comment within ±2 lines suppresses the
    finding."""
    mod = _import_audit_module()
    repo = _make_temp_repo(tmp_path)
    suppressed = repo / "scripts" / "justified.py"
    suppressed.write_text(
        "import subprocess\n"
        "# nosec: shell-allowlist — we control the args here\n"
        'subprocess.run("ls -la", shell=True)\n',
        encoding="utf-8",
    )
    findings = mod.run_audit(repo)
    shell_findings = [f for f in findings if "shell=True" in f.category]
    assert not shell_findings, f"# nosec did not suppress: {shell_findings}"


def test_token_regex_definition_files_exempt(tmp_path: Path) -> None:
    """Files in TOKEN_REGEX_DEFINITION_FILES MUST be skipped from the
    token-shape scan (otherwise the audit's own pattern definitions
    would self-report)."""
    mod = _import_audit_module()
    # The exemption set includes scripts/security_audit.py itself —
    # which contains the token-shape regex strings (e.g., "ghp_").
    # The live-repo audit (test_live_repo_is_clean above) already
    # exercises this; the additional pin here is that the exemption
    # set is non-empty AND includes the audit script.
    assert SCRIPT in mod.TOKEN_REGEX_DEFINITION_FILES


# ---- Self-introspection ---------------------------------------------


def test_audit_skips_itself_for_dangerous_builtins() -> None:
    """The audit's own docstring lists `eval()` / `exec()` / `compile()`
    as documentation. Self-scan would self-report. The script skips
    itself by exact path."""
    mod = _import_audit_module()
    findings = mod.run_audit(REPO_ROOT)
    self_findings = [
        f for f in findings
        if "scripts/security_audit.py" in str(f.file_path)
        and f.category.startswith("dangerous-builtin:")
    ]
    assert not self_findings, (
        f"audit script self-reports for dangerous builtins: {self_findings}"
    )


def test_audit_skips_itself_for_subprocess_patterns() -> None:
    """Same as above but for subprocess patterns (`os.system`)."""
    mod = _import_audit_module()
    findings = mod.run_audit(REPO_ROOT)
    self_findings = [
        f for f in findings
        if "scripts/security_audit.py" in str(f.file_path)
        and f.category.startswith("insecure-subprocess:")
    ]
    assert not self_findings, (
        f"audit script self-reports for subprocess patterns: {self_findings}"
    )


# ---- CLI ------------------------------------------------------------


def test_cli_repo_root_validation(tmp_path: Path) -> None:
    """--repo-root pointing at a non-BSA-shaped dir exits 2."""
    not_a_repo = tmp_path / "empty"
    not_a_repo.mkdir()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), f"--repo-root={not_a_repo}"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert "doesn't look like a BSA repo" in result.stderr


def test_cli_exits_1_on_finding(tmp_path: Path) -> None:
    """A repo with a planted finding produces exit code 1."""
    repo = _make_temp_repo(tmp_path)
    (repo / "scripts" / "leak.py").write_text(
        'TOKEN = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), f"--repo-root={repo}"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "CRITICAL" in result.stdout
    assert "GitHub PAT" in result.stdout


# ---- Scrub-required check -------------------------------------------


def test_scrub_required_files_exist() -> None:
    """The SCRUB_REQUIRED_FILES set MUST point at real existing files
    (otherwise the audit silently degrades)."""
    mod = _import_audit_module()
    for path, _, _ in mod.SCRUB_REQUIRED_FILES:
        assert path.is_file(), f"scrub-required file missing: {path}"


def test_backlog_live_apply_carries_scrub_call() -> None:
    """The live API client MUST call _scrub_secrets — defense-in-depth
    against token leakage in error messages."""
    mod = _import_audit_module()
    findings = mod.run_audit(REPO_ROOT)
    scrub_findings = [f for f in findings if "scrub-required:call-missing" in f.category]
    assert not scrub_findings, (
        f"_scrub_secrets call missing in scrub-required files: {scrub_findings}"
    )
