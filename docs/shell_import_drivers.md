# Shell Import Drivers

**Status:** v1.1.17 (Sprint 1 / T5). Closes `TODO-S9-03-IMPORT-DRIVER` from `scripts/backlog_live_apply.py`.

Thin bash wrappers around `jq + curl + gh` that import `bsa-backlog-bridge` exports into the live platforms. Target audience: operators who prefer shell over Python, or whose CI environment doesn't have Python beyond `python3 -c` snippets.

The canonical implementation remains `scripts/backlog_live_apply.py` (Python, full fcntl lock + F5-validated state file + token-shape scrubbing). The shell drivers are a **lighter alternative** — simpler retry policy, no fcntl lock (operator responsibility), no F5-validated state output. Use the Python impl unless you have a specific reason to prefer shell.

## The three drivers

| Driver | Source export | API | Dependencies | Auth | State file |
|---|---|---|---|---|---|
| `scripts/jira_import_from_export.sh` | `analysis/handoff/backlog_export_jira.json` | Jira REST v3 | `bash 3.2+`, `jq`, `curl` | `$BSA_JIRA_EMAIL` + `$BSA_JIRA_TOKEN` | `live_api_response_jira_shell.json` |
| `scripts/linear_import_from_export.sh` | `analysis/handoff/backlog_export_linear.csv` | Linear GraphQL | `bash 3.2+`, `jq`, `curl`, `python3` (CSV) | `$BSA_LINEAR_TOKEN` | `live_api_response_linear_shell.json` |
| `scripts/github_import_from_export.sh` | `analysis/handoff/backlog_export_github.csv` | `gh` CLI (Issues + Projects v2) | `bash 3.2+`, `gh`, `python3` (CSV) | `gh auth login` OR `$GH_TOKEN` | `live_api_response_github_shell.json` |

## State files

**v1.4.9 (rec #5): unified idempotency.** Python and shell drivers now share the same key space AND cross-read each other's state files. Operators can switch drivers mid-engagement without re-creating issues.

| | Python impl | Shell drivers |
|---|---|---|
| **Write** path | `analysis/handoff/live_api_response_<platform>.json` | `analysis/handoff/live_api_response_<platform>_shell.json` |
| **Read** paths | BOTH (Python F5-validated + shell loose) | BOTH (shell + Python canonical) |
| Shape | F5-validated against `governance/schemas/live_api_response.schema.json` (strict, additionalProperties:false) | Simpler `.results[].status` shape; no F5 validation |
| Idempotency key format | `bsa-{StoryID}-{canon_hash_prefix}` | **same as Python** (was `bsa-{StoryID}-sh-{sha256}` pre-v1.4.9) |

**Cross-read semantics**: on startup each driver merges idempotency keys from BOTH state files into a single done-set. A key produced by EITHER driver causes the matching row to skip. Each driver still WRITES only to its own path (Python keeps F5 validation; shell stays simpler — cross-write would require shell to construct F5-valid JSON which is impractical in bash).

**Platform filter (v1.4.9 R1 MAJOR #3)**: cross-read enforces `.platform` field match when present. A misplaced state file (e.g. a Linear shell state renamed to `*_jira_shell.json`) won't poison this run's idempotency decisions. Files without `.platform` are accepted (legacy v1.1.17 shell state didn't always emit it).

**`--canon-hash` (v1.4.9)**: shell drivers REQUIRE `--canon-hash HEX` when `--apply` is set (matches Python's contract). Auto-detected from `<workspace>/.claude-plugin/canon_policy.json` `hash_prefix` field when omitted.

**Migration from pre-v1.4.9 shell state**: legacy `bsa-{StoryID}-sh-{sha256}` keys won't match the new format → ONE-TIME duplicate creation per legacy story. Operators with large legacy state can rewrite keys via the jq one-liner in CHANGELOG v1.4.9 §Migration. Solo workflow: accept the cost.

## Common contract

All three drivers share:

- **Dry-run by default.** `--apply` is required to actually POST. Dry-run prints the per-row plan + row count + target URL.
- **Idempotency via prior state file.** Both `live_api_response_{platform}_shell.json` (shell driver writeback) AND `live_api_response_{platform}.json` (Python's canonical state) are READ on startup. Rows whose idempotency key matches a `status=created` or `status=skipped` entry in EITHER file are skipped on rerun. v1.4.9 unified the key format: `bsa-{StoryID}-{canon_hash_prefix}` — same as Python. Pre-v1.4.9 shell state used `bsa-{StoryID}-sh-{sha256}` and is documented as one-time-duplicate migration cost in CHANGELOG v1.4.9 §Migration.
- **Token via env var only.** Never via CLI arg. The driver scrubs base64-looking tokens from error output as defense-in-depth.
- **Partial-failure tolerant.** Per-row failures are logged; the driver continues to the next row. Exit 1 at the end if any row failed, 0 if clean.
- **macOS compatibility.** All three drivers avoid `declare -A` (bash 3.2 lacks associative arrays); prior state tracking uses a tmpfile + `grep -Fxq` pattern.

## Jira driver

```bash
export BSA_JIRA_EMAIL='user@example.invalid'
export BSA_JIRA_TOKEN='ATATT3...'

# Dry-run (default) — print plan.
bash scripts/jira_import_from_export.sh --workspace /path/to/workspace

# Actual POST — requires --base-url.
bash scripts/jira_import_from_export.sh \
  --workspace /path/to/workspace \
  --base-url https://acme.atlassian.net \
  --apply
```

Retry policy: exponential backoff (2^attempt seconds) on 429 / 5xx, up to 5 attempts per row. Non-retryable 4xx errors surface immediately.

## Linear driver

```bash
export BSA_LINEAR_TOKEN='lin_api_...'

# Dry-run.
bash scripts/linear_import_from_export.sh --workspace /path/to/workspace

# Actual GraphQL mutation — requires --team-id.
bash scripts/linear_import_from_export.sh \
  --workspace /path/to/workspace \
  --team-id <linear-team-uuid> \
  --apply
```

Linear returns HTTP 200 even on GraphQL errors, so the driver also checks `data.issueCreate.success` + `errors[]` before recording a row as succeeded.

## GitHub driver

```bash
# gh auth EITHER via `gh auth login` OR via env var:
export GH_TOKEN='ghp_...'  # or GITHUB_TOKEN

# Dry-run.
bash scripts/github_import_from_export.sh --workspace /path/to/workspace

# Issues only.
bash scripts/github_import_from_export.sh \
  --workspace /path/to/workspace \
  --repo acme/backlog \
  --apply

# Issues + Projects v2 board attach.
bash scripts/github_import_from_export.sh \
  --workspace /path/to/workspace \
  --repo acme/backlog \
  --project-owner acme \
  --project-number 42 \
  --apply
```

Uses `gh` CLI natively — no curl needed. Projects v2 attach is optional: if `--project-owner` / `--project-number` are omitted, the driver creates the issue and reports its URL; the operator attaches it to a Project manually.

## Exit codes

| Exit | Meaning |
|---|---|
| `0` | All rows OK (or dry-run clean) |
| `1` | Partial failure — at least one row failed; driver completed gracefully |
| `2` | Invocation error — missing export, missing auth env var, missing dependency, missing required CLI arg |

## Comparison with `scripts/backlog_live_apply.py`

| Feature | Python (`backlog_live_apply.py`) | Shell drivers |
|---|---|---|
| Stdlib-only | Yes (Python stdlib) | No — requires jq / curl / gh / python3-for-CSV |
| fcntl concurrency lock | Yes | No (operator responsibility) |
| State file path | Canonical `live_api_response_{platform}.json` (F5-validated against `governance/schemas/live_api_response.schema.json`) | Separate `live_api_response_{platform}_shell.json` (no F5 validation; shell + Python tracks are independent) |
| Token-shape scrubbing | Defense-in-depth (multiple layers + schema-level rejection) | Sed regex on error output only |
| Retry policy | Exponential backoff + per-row 30s deadline | Exponential backoff, no per-row deadline |
| Platform coverage | Jira + Linear + GitHub Issues | Jira + Linear + GitHub Issues + Projects v2 |

**Recommendation**: use the Python impl unless you specifically need one of the shell-driver advantages (e.g., `gh` Projects v2 attach in one step, or CI environment where bash+jq+curl is simpler than managing a Python venv).

## Testing

`tests/test_shell_import_drivers.py` pins:

- All 3 scripts exist + executable.
- Shebang is `#!/usr/bin/env bash` (portable).
- `--help` exits 0 + prints Usage.
- Dry-run correctly prints the plan against synthetic fixtures.
- `--apply` refuses without required auth env var + target arg.
- Idempotency skips rows with prior `outcome=created` state.
- No `declare -A` (macOS bash 3.2 compatibility pin).
