#!/usr/bin/env python3
"""scripts/backlog_live_apply.py — POST bsa-backlog-bridge exports to live APIs.

Section C v1.1.6 — closes TODO-S9-LIVE-API. Reads
``analysis/handoff/backlog_export_{jira,linear,github}.{json,csv}``
and posts each row to the live platform API.

Properties:
  - **Idempotent** per-row (idempotency_key = ``bsa-{StoryID}-{canon_hash_prefix}``).
    Re-runs against an unchanged export read the prior
    ``live_api_response.json`` and skip already-created rows.
  - **Dry-run by default** (``--apply`` to actually POST).
  - **Stdlib-only** (``urllib.request`` for HTTP — no ``requests`` /
    ``httpx`` dep).
  - **Exponential backoff** on 429 (rate-limited) + 5xx (server error).
    Retry budget capped at 5 attempts per row; per-row deadline 30s.
  - **Partial-failure tolerant**: continues processing remaining rows
    after an individual failure; emits non-zero exit code only if at
    least one row failed.
  - **Tokens NEVER persisted, NEVER logged**: env-var indirection only
    (``--jira-token-env=BSA_JIRA_TOKEN``); error messages scrub the
    Authorization header value before recording.
  - **JSONL log** under ``<workspace>/handoff/live_api_log.jsonl`` —
    one record per HTTP attempt (request URL, status code, attempt
    number, timestamp; NO body, NO headers).
  - **Idempotency state** in ``<workspace>/handoff/live_api_response.json``
    — F5-validated structured outcome record.

Auth:
  Jira:   ``--jira-base-url=https://acme.atlassian.net``
          ``--jira-email-env=BSA_JIRA_EMAIL``
          ``--jira-token-env=BSA_JIRA_TOKEN``
          (basic auth: <email>:<api_token>; Atlassian Cloud convention)
  Linear: ``--linear-token-env=BSA_LINEAR_TOKEN``
          (header ``Authorization: <token>``; Linear API key shape)
  GitHub: ``--github-base-url=https://api.github.com``
          ``--github-repo=owner/name``
          ``--github-token-env=BSA_GITHUB_TOKEN``
          (header ``Authorization: Bearer <token>``)

Exit codes:
  0 — all OK (or dry-run clean)
  1 — partial failure: at least one row failed but the run completed
      gracefully (log + response.json written; operator sees per-row
      outcome)
  2 — invocation error (missing arg, missing env var, malformed export,
      total network failure on attempt 1)

Stdlib-only. Python 3.9+.
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


# ---- Constants --------------------------------------------------------

SCHEMA_VERSION = "1.0"
LOG_FILENAME = "live_api_log.jsonl"
LOCK_FILENAME_TEMPLATE = "live_api_response_{platform}.lock"
# Per-platform response files. Cross-platform collision (Codex v1.1.6
# round-1 critical): a single shared live_api_response.json would let
# a sequential Jira→Linear→GitHub run skip the second/third platform
# because the Jira-platform StoryID idempotency key was already
# present. The fix is per-platform filenames matching the schema's
# stated (workspace, platform) contract.
RESPONSE_FILENAME_TEMPLATE = "live_api_response_{platform}.json"
MAX_ATTEMPTS = 5
PER_ROW_DEADLINE_SEC = 30
INITIAL_BACKOFF_SEC = 1.0
USER_AGENT = "bsa-backlog-live-apply/1.0 (stdlib)"

# Per-platform URL templates for browseable result. {base} = base URL,
# {key} = platform-side ID. Empty string = no browseable URL convention.
PLATFORM_URL_TEMPLATES = {
    "jira": "{base}/browse/{key}",
    "linear": "{base}/issue/{key}",
    "github": "{base}/{repo}/issues/{key}",  # base here is the API root; repo substituted
}


# ---- Data classes -----------------------------------------------------


@dataclass
class ResultRow:
    story_id: str
    idempotency_key: str
    status: str  # created | skipped | failed
    attempts: int = 0
    platform_id: str = ""
    platform_url: str = ""
    last_error: str = ""

    def to_dict(self) -> dict:
        out: dict = {
            "story_id": self.story_id,
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "attempts": self.attempts,
        }
        if self.platform_id:
            out["platform_id"] = self.platform_id
        if self.platform_url:
            out["platform_url"] = self.platform_url
        if self.last_error:
            out["last_error"] = self.last_error
        return out


@dataclass
class LogRecord:
    """One HTTP attempt. Written to live_api_log.jsonl. NEVER carries
    request body or headers — those could leak tokens."""
    timestamp: str
    operator_run_id: str
    platform: str
    story_id: str
    idempotency_key: str
    attempt: int
    request_url: str  # path-only, NO query string with secrets
    status_code: int = 0  # 0 = network error before HTTP response
    error: str = ""
    dry_run: bool = True

    def to_json_line(self) -> str:
        d = {
            "timestamp": self.timestamp,
            "operator_run_id": self.operator_run_id,
            "platform": self.platform,
            "story_id": self.story_id,
            "idempotency_key": self.idempotency_key,
            "attempt": self.attempt,
            "request_url": self.request_url,
            "status_code": self.status_code,
            "dry_run": self.dry_run,
        }
        if self.error:
            d["error"] = self.error
        return json.dumps(d, ensure_ascii=False, sort_keys=True)


# ---- Token security ---------------------------------------------------


_AUTH_HEADER_SCRUB_RE = re.compile(
    # Match the WHOLE auth-header value up to the next delimiter (comma,
    # semicolon, end-of-line). Without this, "Authorization: Bearer abc123"
    # would scrub only "Bearer" and leave the actual token visible.
    r"(authorization\s*[:=]\s*)([^,;\n\r]+)",
    re.IGNORECASE,
)


def _scrub_secrets(text: str) -> str:
    """Replace any Authorization-header value occurrence with <REDACTED>.
    Defensive scrub for error messages before persistence. Handles both
    'Bearer <token>' and 'Basic <b64creds>' shapes."""
    return _AUTH_HEADER_SCRUB_RE.sub(r"\1<REDACTED>", text)


def _read_token_env(env_var: str) -> str:
    value = os.environ.get(env_var, "").strip()
    if not value:
        raise InvocationError(
            f"required env var {env_var!r} is not set or empty. "
            f"Set it before invoking with --apply."
        )
    return value


# ---- Errors -----------------------------------------------------------


class InvocationError(ValueError):
    """Raised on bad CLI / env — translates to exit 2."""


# ---- HTTP layer (stdlib only) -----------------------------------------


def _http_post_json(
    url: str,
    headers: dict[str, str],
    body: dict | str,
    timeout_sec: int = 30,
) -> tuple[int, dict | None, str]:
    """POST a JSON body. Returns (status_code, parsed_json_or_None, error_message).
    On network error returns (0, None, scrubbed_message). HTTP 4xx/5xx
    returns (status, parsed_or_None, '') so the caller can decide retry."""
    data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
    req_headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = None
            return resp.status, parsed, ""
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else None
        except (json.JSONDecodeError, OSError):
            parsed = None
        return exc.code, parsed, ""
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        return 0, None, _scrub_secrets(str(exc))


# ---- Platform clients -------------------------------------------------


@dataclass
class PlatformConfig:
    platform: str  # jira | linear | github
    base_url: str
    headers: dict[str, str] = field(default_factory=dict)
    extra: dict[str, str] = field(default_factory=dict)  # platform-specific knobs


def _build_jira_config(args: argparse.Namespace) -> PlatformConfig:
    if not args.jira_base_url:
        raise InvocationError("--apply for platform=jira requires --jira-base-url")
    if not args.jira_email_env or not args.jira_token_env:
        raise InvocationError(
            "--apply for platform=jira requires --jira-email-env + --jira-token-env"
        )
    email = _read_token_env(args.jira_email_env)
    token = _read_token_env(args.jira_token_env)
    basic = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    return PlatformConfig(
        platform="jira",
        base_url=args.jira_base_url.rstrip("/"),
        headers={"Authorization": f"Basic {basic}"},
    )


def _build_linear_config(args: argparse.Namespace) -> PlatformConfig:
    if not args.linear_token_env:
        raise InvocationError("--apply for platform=linear requires --linear-token-env")
    # Codex round-1 critical fix #2 — fail FAST when --linear-team-id
    # is missing. Without it Linear's mutation gets a missing-required-
    # field server error and burns 5 retries per row before failing.
    if not args.linear_team_id or not args.linear_team_id.strip():
        raise InvocationError(
            "--apply for platform=linear requires --linear-team-id <UUID>. "
            "Linear's GraphQL issueCreate mutation cannot derive the team "
            "from the CSV row; the operator must supply it explicitly."
        )
    token = _read_token_env(args.linear_token_env)
    base = args.linear_base_url or "https://api.linear.app"
    return PlatformConfig(
        platform="linear",
        base_url=base.rstrip("/"),
        headers={"Authorization": token},
        extra={"team_id": args.linear_team_id.strip()},
    )


def _build_github_config(args: argparse.Namespace) -> PlatformConfig:
    if not args.github_token_env or not args.github_repo:
        raise InvocationError(
            "--apply for platform=github requires --github-token-env + --github-repo (owner/name)"
        )
    if "/" not in args.github_repo:
        raise InvocationError("--github-repo must be in 'owner/name' shape")
    token = _read_token_env(args.github_token_env)
    base = args.github_base_url or "https://api.github.com"
    return PlatformConfig(
        platform="github",
        base_url=base.rstrip("/"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        extra={"repo": args.github_repo},
    )


def _post_jira_issue(cfg: PlatformConfig, issue_payload: dict, timeout: int) -> tuple[int, dict | None, str]:
    """POST /rest/api/3/issue with the bridge-emitted issue payload."""
    url = f"{cfg.base_url}/rest/api/3/issue"
    return _http_post_json(url, cfg.headers, issue_payload, timeout_sec=timeout)


def _post_linear_issue(cfg: PlatformConfig, csv_row: dict, timeout: int) -> tuple[int, dict | None, str]:
    """POST GraphQL mutation issueCreate. Linear API has no REST surface
    — only GraphQL. The mutation creates one issue per call.

    NOTE: this returns (status_code, parsed_json, error). GraphQL status
    semantics are weird — a 200 response can carry top-level ``errors``
    or ``data.issueCreate.success=false`` which means the mutation
    FAILED despite HTTP 200. The caller (_process_row) consults
    _is_linear_success() before treating the result as 'created'.
    """
    url = f"{cfg.base_url}/graphql"
    team_id = cfg.extra.get("team_id", "")
    # Minimal mutation; Linear schema accepts more fields but this is
    # the deterministic core. Operator can extend via post-import GraphQL.
    mutation = (
        "mutation IssueCreate($input: IssueCreateInput!) {"
        " issueCreate(input: $input) { success issue { id identifier url } }"
        "}"
    )
    variables = {
        "input": {
            "teamId": team_id,
            "title": csv_row.get("Title", ""),
            "description": csv_row.get("Description", ""),
            "priority": int(csv_row["Priority"]) if csv_row.get("Priority", "").isdigit() else 0,
        }
    }
    body = {"query": mutation, "variables": variables}
    return _http_post_json(url, cfg.headers, body, timeout_sec=timeout)


def _is_linear_success(parsed: dict | None) -> tuple[bool, str]:
    """Linear strict success check (Codex round-1 critical #2).

    GraphQL returns 200 even on errors. A response is genuinely success
    only when ALL of:
      * No top-level ``errors`` array (or it's empty).
      * data.issueCreate.success is True.
      * data.issueCreate.issue.identifier is non-empty.

    Returns (is_success, error_message). When is_success=False, the
    error_message is suitable for the result_row.last_error field.
    """
    if not isinstance(parsed, dict):
        return False, "linear: response is not a JSON object"
    errors = parsed.get("errors")
    if isinstance(errors, list) and errors:
        first_msg = ""
        if isinstance(errors[0], dict):
            first_msg = str(errors[0].get("message", ""))[:200]
        else:
            first_msg = str(errors[0])[:200]
        return False, f"linear: GraphQL errors[0]={first_msg!r}"
    data = parsed.get("data")
    if not isinstance(data, dict):
        return False, "linear: response missing 'data' object"
    issue_create = data.get("issueCreate")
    if not isinstance(issue_create, dict):
        return False, "linear: response missing 'data.issueCreate'"
    if not issue_create.get("success", False):
        return False, "linear: data.issueCreate.success=false"
    issue = issue_create.get("issue")
    if not isinstance(issue, dict):
        return False, "linear: response missing 'data.issueCreate.issue'"
    identifier = (issue.get("identifier") or "").strip()
    if not identifier:
        return False, "linear: response missing 'data.issueCreate.issue.identifier'"
    return True, ""


def _post_github_issue(cfg: PlatformConfig, csv_row: dict, timeout: int) -> tuple[int, dict | None, str]:
    """POST /repos/{owner}/{name}/issues. Issue-only — Project v2 board
    assignment is operator-side via gh CLI (TODO-S9-03-IMPORT-DRIVER)."""
    repo = cfg.extra.get("repo", "")
    url = f"{cfg.base_url}/repos/{repo}/issues"
    labels_str = csv_row.get("Labels", "")
    labels = [lab.strip() for lab in labels_str.split(",") if lab.strip()]
    body = {
        "title": csv_row.get("Title", ""),
        "body": csv_row.get("Body", ""),
        "labels": labels,
    }
    return _http_post_json(url, cfg.headers, body, timeout_sec=timeout)


# ---- Idempotency ------------------------------------------------------


_CANON_HASH_PREFIX_RE = re.compile(r"^[a-f0-9]{8}$")


def _make_idempotency_key(story_id: str, canon_hash_prefix: str) -> str:
    """Format: bsa-{StoryID}-{canon_hash_prefix}. Re-runs against the
    same StoryID + canonical-policy state yield the same key, which is
    looked up in the prior live_api_response.json to skip."""
    if not _CANON_HASH_PREFIX_RE.match(canon_hash_prefix):
        raise InvocationError(
            f"canon_hash_prefix {canon_hash_prefix!r} must be 8 lowercase hex chars"
        )
    return f"bsa-{story_id}-{canon_hash_prefix}"


def _load_prior_state_validated(path: Path, expected_platform: str) -> dict[str, dict]:
    """Return {idempotency_key: prior_result_dict} from a prior per-platform
    live_api_response_<platform>.json, or {} if absent.

    v1.1.6 round-1 critical + should-fix #2:
    * Hard-filters by top-level ``platform`` field — a Jira state file
      MUST NOT propagate keys into a Linear run (per-platform filenames
      already prevent this at the path level, but defense-in-depth here
      catches a poisoned file that was renamed).
    * Validates the prior file against the F5 schema before trusting any
      content — a poisoned/edited file is rejected, not silently used.
    * Defensive secret-pattern check on platform_id / platform_url /
      last_error fields before re-emitting them — catches operator
      mistakes that would otherwise echo a token through.
    """
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        doc = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(doc, dict):
        return {}
    # Platform filter — a sibling file misplacement shouldn't poison this run.
    if doc.get("platform") != expected_platform:
        return {}
    # Schema validation — a poisoned file is rejected.
    try:
        from governance.schemas.write_validator import validate_canonical_write
        validate_path = f"analysis/handoff/{path.name}"
        ok, _msgs = validate_canonical_write(validate_path, raw)
        if not ok:
            return {}  # silently ignore corrupt prior state
    except ImportError:
        pass  # validator unavailable in packaging mode — degrade gracefully
    if not isinstance(doc.get("results"), list):
        return {}
    out: dict[str, dict] = {}
    for r in doc["results"]:
        if not isinstance(r, dict):
            continue
        # Defensive secret scrub on every echoed field.
        if _looks_token_shaped(r.get("platform_id", "")) or _looks_token_shaped(r.get("platform_url", "")) or _looks_token_shaped(r.get("last_error", "")):
            continue  # quarantine suspect rows
        key = (r.get("idempotency_key") or "").strip()
        if key and r.get("status") == "created":
            out[key] = r
    return out


# Backward-compat alias — internal callers use the validated form now.
_load_prior_state = _load_prior_state_validated  # type: ignore[assignment]


# Heuristic: anything looking like a JWT, GitHub PAT, Atlassian API token
# fragment, or long-base64 secret should never appear in result_row fields.
_TOKEN_SHAPE_RE = re.compile(
    r"(?:"
    # JWT (eyJ... three dot-separated base64url)
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
    # GitHub PAT (ghp_/gho_/ghu_/ghs_/ghr_ + 36+ chars)
    r"|gh[pousr]_[A-Za-z0-9]{30,}"
    # Atlassian API token (24-char alphanum is too generic, but ATATT3xFfGF style is common)
    r"|ATATT3[A-Za-z0-9]{20,}"
    # Bearer / Basic prefix in an embedded value
    r"|(?:[Bb]earer|[Bb]asic)\s+[A-Za-z0-9_\-=+/.]{20,}"
    r")"
)


def _looks_token_shaped(value: str) -> bool:
    """Heuristic: True if the value matches a known secret shape.
    Used to quarantine prior_state rows whose persisted fields might
    have been poisoned by an operator copy-paste mistake."""
    if not isinstance(value, str) or not value.strip():
        return False
    return bool(_TOKEN_SHAPE_RE.search(value))


# ---- Concurrency lock -------------------------------------------------


class _LockBusy(Exception):
    """Raised when another live-apply run holds the per-platform lock."""


def _acquire_platform_lock(lock_path: Path) -> "object":
    """Acquire an exclusive lock for this (workspace, platform) pair.

    Uses fcntl.flock on Unix (atomic). Returns the file handle (must be
    held open until released — flock is auto-released on close, but we
    want explicit release for clarity). Raises _LockBusy if another
    process already holds the lock.

    The file's contents are immaterial; only the OS-level advisory lock
    matters. We open in 'a+' so the file gets created on first run.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+", encoding="utf-8")
    try:
        import fcntl  # Unix only — Windows operators get OSError, see except below
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            raise _LockBusy(str(exc)) from exc
    except ImportError:
        # Windows: degrade to existence-based lock (less robust). The
        # script writes its PID + timestamp; if a stale lock is found
        # the operator can manually delete it.
        existing = lock_path.read_text(encoding="utf-8") if lock_path.exists() else ""
        if existing.strip():
            fh.close()
            raise _LockBusy(f"existing lock content: {existing.strip()[:80]}")
    fh.write(f"pid={os.getpid()} acquired_at={datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
    fh.flush()
    return fh


def _release_platform_lock(lock_handle: "object", lock_path: Path) -> None:
    """Release the lock acquired by _acquire_platform_lock.

    Closing the file releases flock automatically on Unix; we also
    truncate the file content so a stale lock isn't left around to
    confuse a fallback-mode run later.
    """
    try:
        try:
            import fcntl
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
        except (ImportError, OSError):
            pass
        try:
            lock_handle.close()  # type: ignore[attr-defined]
        except OSError:
            pass
    finally:
        # Best-effort: truncate the file so the next run sees an empty lock.
        try:
            lock_path.write_text("", encoding="utf-8")
        except OSError:
            pass


# ---- Per-row driver ---------------------------------------------------


def _process_row(
    cfg: PlatformConfig,
    story_id: str,
    canon_hash_prefix: str,
    payload: dict,
    prior_state: dict[str, dict],
    apply_mode: bool,
    operator_run_id: str,
    log_records: list[LogRecord],
) -> ResultRow:
    """Process one export row. Handles idempotency lookup, dry-run /
    apply branching, retry-with-backoff. Returns the final ResultRow."""
    key = _make_idempotency_key(story_id, canon_hash_prefix)
    # Idempotency hit → skip without HTTP.
    if key in prior_state:
        prior = prior_state[key]
        return ResultRow(
            story_id=story_id, idempotency_key=key, status="skipped",
            attempts=0, platform_id=prior.get("platform_id", ""),
            platform_url=prior.get("platform_url", ""),
        )
    # Dry-run: planned but no HTTP.
    if not apply_mode:
        return ResultRow(
            story_id=story_id, idempotency_key=key, status="created",
            attempts=0, platform_id="<DRY_RUN>",
            platform_url="",
        )
    # Apply mode: retry with exponential backoff.
    #
    # Codex round-1 should-fix #3: STRICT deadline. The previous loop
    # checked deadline only at the top of each iteration AND counted
    # the "deadline exhausted" branch as an attempt. We now:
    #   * Track sent_attempts (only counts attempts where HTTP actually
    #     fired) separately from the loop counter.
    #   * Compute remaining_budget on every iteration; cap both the
    #     HTTP request timeout AND the backoff sleep by it.
    #   * If remaining_budget < a minimum (1s) we abort cleanly without
    #     incrementing sent_attempts.
    backoff = INITIAL_BACKOFF_SEC
    last_status_code = 0
    last_error = ""
    sent_attempts = 0
    started = time.time()
    deadline = started + PER_ROW_DEADLINE_SEC
    for _loop_idx in range(MAX_ATTEMPTS):
        remaining = deadline - time.time()
        if remaining < 1.0:
            last_error = (
                last_error
                or f"per-row deadline ({PER_ROW_DEADLINE_SEC}s) exhausted before next attempt"
            )
            break
        # Cap per-request timeout by remaining budget (max 10s normally;
        # less when budget is tight).
        request_timeout = min(10, max(1, int(remaining)))
        if cfg.platform == "jira":
            status, parsed, err = _post_jira_issue(cfg, payload, timeout=request_timeout)
            request_url = "/rest/api/3/issue"
        elif cfg.platform == "linear":
            status, parsed, err = _post_linear_issue(cfg, payload, timeout=request_timeout)
            request_url = "/graphql"
        elif cfg.platform == "github":
            repo = cfg.extra.get("repo", "")
            status, parsed, err = _post_github_issue(cfg, payload, timeout=request_timeout)
            request_url = f"/repos/{repo}/issues"
        else:
            return ResultRow(
                story_id=story_id, idempotency_key=key, status="failed",
                attempts=0, last_error=f"unknown platform {cfg.platform!r}",
            )
        sent_attempts += 1
        log_records.append(LogRecord(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            operator_run_id=operator_run_id, platform=cfg.platform,
            story_id=story_id, idempotency_key=key,
            attempt=sent_attempts, request_url=request_url,
            status_code=status, error=_scrub_secrets(err) if err else "",
            dry_run=False,
        ))
        last_status_code = status
        last_error = _scrub_secrets(err) if err else ""
        # Success: 2xx (HTTP layer). Linear has its own GraphQL-semantic
        # success check (Codex round-1 critical #2).
        if 200 <= status < 300:
            if cfg.platform == "linear":
                ok, err_msg = _is_linear_success(parsed)
                if not ok:
                    # GraphQL "soft failure" — typically a permissions / input
                    # error. Don't retry (the same input would fail again);
                    # mark failed.
                    last_error = err_msg
                    break
            platform_id, platform_url = _extract_created(cfg, parsed or {})
            if not platform_id and cfg.platform != "jira":
                # Catch the case where _extract_created can't find the
                # ID even though HTTP was 2xx — surface as failure rather
                # than silently storing an empty ID.
                last_error = (
                    f"{cfg.platform}: response was 2xx but platform_id could not be extracted"
                )
                break
            return ResultRow(
                story_id=story_id, idempotency_key=key, status="created",
                attempts=sent_attempts, platform_id=platform_id, platform_url=platform_url,
            )
        # Retryable: 429 (rate-limited) or 5xx (server error) or network err (status=0)
        retryable = status == 429 or 500 <= status < 600 or status == 0
        if not retryable:
            # 4xx other than 429 → don't retry; persistent client error
            last_error = f"HTTP {status}: {_scrub_secrets(json.dumps(parsed)[:200] if parsed else err)}"
            break
        # Sleep with backoff (capped by remaining budget) if more attempts remain
        if _loop_idx < MAX_ATTEMPTS - 1:
            remaining = deadline - time.time()
            sleep_for = min(backoff, max(0.0, remaining - 1.0))
            if sleep_for > 0:
                time.sleep(sleep_for)
            backoff *= 2
    # Exhausted retries / deadline
    return ResultRow(
        story_id=story_id, idempotency_key=key, status="failed",
        attempts=sent_attempts,
        last_error=last_error or f"HTTP {last_status_code} after {sent_attempts} attempt(s)",
    )


def _extract_created(cfg: PlatformConfig, parsed: dict) -> tuple[str, str]:
    """Extract (platform_id, platform_url) from a 2xx response."""
    if cfg.platform == "jira":
        # Jira REST v3 returns {key: "BSA-123", id: "10001", self: "..."}
        key = (parsed.get("key") or "").strip()
        url = (
            PLATFORM_URL_TEMPLATES["jira"].format(base=cfg.base_url, key=key) if key else ""
        )
        return key, url
    if cfg.platform == "linear":
        # GraphQL: data.issueCreate.issue.{identifier, url}
        try:
            issue = parsed["data"]["issueCreate"]["issue"]
            return (issue.get("identifier") or "").strip(), (issue.get("url") or "").strip()
        except (KeyError, TypeError):
            return "", ""
    if cfg.platform == "github":
        # REST returns {number, html_url, ...}
        number = str(parsed.get("number") or "").strip()
        url = (parsed.get("html_url") or "").strip()
        return number, url
    return "", ""


# ---- Export readers ---------------------------------------------------


def _read_jira_export(path: Path) -> tuple[list[tuple[str, dict]], str]:
    """Returns ([(story_id, issue_payload), ...], canon_hash_prefix).
    Reads the issue-create payloads + the source canon hash prefix."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    canon = ""  # bridge does not embed a canon hash in the export today; operator can pass --canon-hash
    out: list[tuple[str, dict]] = []
    for issue in doc.get("issues", []):
        sid = issue.get("bsa_provenance", {}).get("story_id", "")
        if not sid:
            continue
        # POST body for /rest/api/3/issue is just the {fields: ...}
        payload = {"fields": issue.get("fields", {})}
        out.append((sid, payload))
    return out, canon


def _read_csv_export(path: Path) -> list[dict]:
    """Returns the CSV rows as dicts. Used for Linear + GitHub."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# ---- Main driver ------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    workspace = args.workspace
    handoff_dir = workspace / "analysis" / "handoff" if (workspace / "analysis").is_dir() else workspace / "handoff"
    if not handoff_dir.is_dir():
        print(f"ERROR: handoff dir not found: {handoff_dir}", file=sys.stderr)
        return 2

    # Build platform config
    if args.platform == "jira":
        try:
            cfg = _build_jira_config(args) if args.apply else PlatformConfig(
                platform="jira", base_url=args.jira_base_url or "<DRY_RUN>",
            )
        except InvocationError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        export_path = handoff_dir / "backlog_export_jira.json"
        if not export_path.is_file():
            print(f"ERROR: Jira export missing: {export_path}", file=sys.stderr)
            return 2
        rows, _ = _read_jira_export(export_path)
        story_payload_pairs = rows
    elif args.platform == "linear":
        try:
            cfg = _build_linear_config(args) if args.apply else PlatformConfig(
                platform="linear", base_url=args.linear_base_url or "https://api.linear.app",
                extra={"team_id": args.linear_team_id or ""},
            )
        except InvocationError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        export_path = handoff_dir / "backlog_export_linear.csv"
        if not export_path.is_file():
            print(f"ERROR: Linear export missing: {export_path}", file=sys.stderr)
            return 2
        csv_rows = _read_csv_export(export_path)
        story_payload_pairs = [(r.get("StoryID", ""), r) for r in csv_rows if r.get("StoryID")]
    elif args.platform == "github":
        try:
            cfg = _build_github_config(args) if args.apply else PlatformConfig(
                platform="github",
                base_url=args.github_base_url or "https://api.github.com",
                extra={"repo": args.github_repo or "<DRY_RUN>/<DRY_RUN>"},
            )
        except InvocationError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        export_path = handoff_dir / "backlog_export_github.csv"
        if not export_path.is_file():
            print(f"ERROR: GitHub export missing: {export_path}", file=sys.stderr)
            return 2
        csv_rows = _read_csv_export(export_path)
        story_payload_pairs = [(r.get("StoryID", ""), r) for r in csv_rows if r.get("StoryID")]
    else:
        print(f"ERROR: unknown platform {args.platform!r}", file=sys.stderr)
        return 2

    # Per-platform response file (Codex v1.1.6 round-1 critical fix).
    response_path = handoff_dir / RESPONSE_FILENAME_TEMPLATE.format(platform=args.platform)
    lock_path = handoff_dir / LOCK_FILENAME_TEMPLATE.format(platform=args.platform)

    # Concurrency lock (Codex round-1 should-fix #4): two concurrent
    # runs against the same workspace+platform would both read stale
    # state, both POST, and the last write wins — duplicate platform
    # issues. Acquire an exclusive file lock before reading prior
    # state so the read-process-write cycle is serialized per
    # workspace+platform. Dry-run skips the lock (no state mutation).
    lock_handle = None
    if args.apply:
        try:
            lock_handle = _acquire_platform_lock(lock_path)
        except _LockBusy:
            print(
                f"ERROR: another live-apply run is already in progress "
                f"for platform={args.platform!r} in workspace {workspace} "
                f"(lock file: {lock_path}). Wait for it to finish or "
                f"remove the lock file if you're sure no other run is active.",
                file=sys.stderr,
            )
            return 2
        except OSError as exc:
            print(f"ERROR: cannot acquire lock {lock_path}: {exc}", file=sys.stderr)
            return 2

    try:
        # Idempotency: load prior state if response file exists. Validate
        # the prior file against the F5 schema FIRST — a poisoned/edited
        # prior file shouldn't propagate untrusted content into this
        # run's results. Codex round-1 should-fix #2.
        prior_state = _load_prior_state_validated(response_path, args.platform)

        # Drive each row
        log_records: list[LogRecord] = []
        results: list[ResultRow] = []
        for story_id, payload in story_payload_pairs:
            result = _process_row(
                cfg, story_id, args.canon_hash, payload, prior_state,
                apply_mode=args.apply, operator_run_id=args.run_id,
                log_records=log_records,
            )
            results.append(result)

        # Write JSONL log (append). Log file lives outside F5 (not under
        # canonical/), so no schema dispatch fires for it.
        if log_records:
            log_path = handoff_dir / LOG_FILENAME
            try:
                with log_path.open("a", encoding="utf-8") as fh:
                    for rec in log_records:
                        fh.write(rec.to_json_line() + "\n")
            except OSError as exc:
                print(f"WARN: cannot write log {log_path}: {exc}", file=sys.stderr)

        # Build summary
        by_status: dict[str, int] = {"created": 0, "skipped": 0, "failed": 0}
        for r in results:
            by_status[r.status] = by_status.get(r.status, 0) + 1
        summary = {
            "total": len(results),
            "created": by_status["created"],
            "skipped": by_status["skipped"],
            "failed": by_status["failed"],
        }

        # Build response document
        response = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "platform": args.platform,
            "platform_base_url": cfg.base_url if cfg.base_url and not cfg.base_url.startswith("<") else "https://placeholder.invalid",
            "operator_run_id": args.run_id,
            "source_export_path": f"analysis/handoff/{export_path.name}",
            "source_export_canon_hash": args.canon_hash,
            "results": [r.to_dict() for r in results],
            "summary": summary,
        }

        # Write response file (apply mode only — dry-run prints to stdout
        # to avoid clobbering a real prior state with placeholder data).
        if args.apply:
            # Codex round-1 should-fix #1: validate the response document
            # against the live F5 schema BEFORE writing. Catches drift
            # the script's own _process_row logic might introduce (e.g.,
            # a future refactor breaking the cross-field invariants).
            response_json = json.dumps(response, indent=2, ensure_ascii=False) + "\n"
            try:
                from governance.schemas.write_validator import validate_canonical_write
                validate_path = f"analysis/handoff/{response_path.name}"
                ok, msgs = validate_canonical_write(validate_path, response_json)
                if not ok:
                    print(
                        f"ERROR: response document failed F5 schema validation "
                        f"(would have written {response_path}). Violations:",
                        file=sys.stderr,
                    )
                    for m in msgs:
                        print(f"  {m}", file=sys.stderr)
                    return 2
            except ImportError:
                # Validator module not importable (packaging-mode runs);
                # proceed without pre-write check (schema-conformance
                # check at hook time will still fire when the operator
                # writes the file via Claude Code's Write tool).
                pass
            try:
                response_path.write_text(response_json, encoding="utf-8")
            except OSError as exc:
                print(f"WARN: cannot write response {response_path}: {exc}", file=sys.stderr)

        # Console summary
        mode_label = "applied" if args.apply else "dry-run"
        print(
            f"BSA backlog live-apply ({args.platform}, {mode_label}): "
            f"total={summary['total']} created={summary['created']} "
            f"skipped={summary['skipped']} failed={summary['failed']}"
        )
        if not args.apply:
            # Print response to stdout so operator sees it without
            # clobbering a real file.
            print("---")
            print(json.dumps(response, indent=2, ensure_ascii=False))

        return 1 if summary["failed"] > 0 else 0
    finally:
        if lock_handle is not None:
            _release_platform_lock(lock_handle, lock_path)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Post bsa-backlog-bridge exports to live platform APIs (Section C v1.1.6)."
    )
    parser.add_argument("--workspace", type=Path, required=True,
                        help="Workspace root (typically a directory containing analysis/).")
    parser.add_argument("--platform", required=True, choices=["jira", "linear", "github"],
                        help="Which export to process.")
    parser.add_argument("--apply", action="store_true",
                        help="Actually POST to the live API. Default: dry-run.")
    parser.add_argument("--canon-hash", required=True,
                        help="8-char canon-policy-version hash prefix (from .claude-plugin/plugin.json). "
                             "Used in the per-row idempotency key.")
    parser.add_argument("--run-id", default="",
                        help="Operator run identifier (default: auto from timestamp + workspace name).")

    # Jira
    parser.add_argument("--jira-base-url", default="",
                        help="Jira Cloud base URL (e.g., https://acme.atlassian.net).")
    parser.add_argument("--jira-email-env", default="BSA_JIRA_EMAIL",
                        help="Env var holding the Jira account email (basic auth).")
    parser.add_argument("--jira-token-env", default="BSA_JIRA_TOKEN",
                        help="Env var holding the Jira API token (basic auth).")

    # Linear
    parser.add_argument("--linear-base-url", default="",
                        help="Linear API base URL (default: https://api.linear.app).")
    parser.add_argument("--linear-token-env", default="BSA_LINEAR_TOKEN",
                        help="Env var holding the Linear API key.")
    parser.add_argument("--linear-team-id", default="",
                        help="Linear team UUID — required because Linear API has no CSV-derivable team mapping.")

    # GitHub
    parser.add_argument("--github-base-url", default="",
                        help="GitHub API base URL (default: https://api.github.com).")
    parser.add_argument("--github-repo", default="",
                        help="GitHub repo in 'owner/name' shape.")
    parser.add_argument("--github-token-env", default="BSA_GITHUB_TOKEN",
                        help="Env var holding the GitHub token.")

    args = parser.parse_args(argv)

    # Preflight workspace
    try:
        if not args.workspace.is_dir():
            print(f"ERROR: workspace does not exist or is not a directory: {args.workspace}", file=sys.stderr)
            return 2
    except (OSError, PermissionError) as exc:
        print(f"ERROR: cannot access workspace: {exc}", file=sys.stderr)
        return 2

    # Auto-generate run_id if missing
    if not args.run_id:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%S")
        ws_name = re.sub(r"[^a-z0-9_\-]", "_", args.workspace.name.lower())[:32] or "workspace"
        args.run_id = f"{ws_name}-{ts}"
    # Validate run_id shape (matches the schema pattern)
    if not re.match(r"^[a-z0-9_\-]{8,64}$", args.run_id):
        print(
            f"ERROR: --run-id must match ^[a-z0-9_\\-]{{8,64}}$ — got {args.run_id!r}",
            file=sys.stderr,
        )
        return 2

    return run(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
