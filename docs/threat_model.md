# Threat Model

v1.1.11 (Section G) — explicit attack-surface inventory + per-vector mitigations + open risks.

This document is the operator-facing security reference. For high-level posture, see [`SECURITY.md`](../SECURITY.md). For the Codex-review history that produced each mitigation, see the relevant CHANGELOG entry.

## Scope

The BSA plugin family is a Claude Code plugin with three operator-facing surfaces:

1. **Pipeline orchestration** (slash commands `/bsa-*`). LLM-driven; runs in Claude Code's sandbox.
2. **F5 hooks** (`hooks/pre_write_canonical.sh`). Block/allow Write+Edit operations against canonical paths.
3. **Operator scripts** (`scripts/*.py`). Python 3.9+ stdlib-only (mostly); cover migration, validation, live API, doctor.

The plugin operates against operator-local workspaces (`analysis/`); it does not run a server, does not bind a port, does not expose an HTTP API. The one network surface is the **outbound** live API client (v1.1.6 — POST to Jira / Linear / GitHub) controlled by the operator.

## Threat actors

- **Malicious source content**: a stakeholder document (PDF / MD / TXT) authored to inject prompts, escalate via tier-spoofing, or drift the schema. Already exercised by `fixtures/golden/adversarial_prompt_injection_001/`.
- **Compromised operator credentials**: a stolen Jira / Linear / GitHub token used to POST forged backlog issues. Mitigation: env-var indirection + token-shape rejection in persisted state (v1.1.6).
- **Malicious operator-local file**: an attacker who can write to the operator's workspace (`analysis/`) trying to escape via path traversal, env injection, or hook bypass. Mitigation stack in §4 below.
- **Supply-chain drift**: an upstream dep (pytest / jsonschema / PyYAML) compromised. Mitigation: test-only deps, runtime stays stdlib-only.

## Attack-surface inventory

### 1. Token handling (live API client, v1.1.6)

| Vector | Mitigation | Pinned by |
|---|---|---|
| Token in CLI args (`ps` / shell history) | Env-var indirection only (`--*-token-env=BSA_*_TOKEN`); the env-var NAME is in CLI args, not the token value | `_read_token_env()` |
| Token in JSONL log (`live_api_log.jsonl`) | Log records carry only request URL + status code + attempt #; NEVER body, NEVER headers | `LogRecord.to_json_line()` |
| Token in F5-validated state (`live_api_response_*.json`) | Schema rejects token-shaped strings (JWT / GitHub PAT / Atlassian PAT / Bearer/Basic) in `platform_id` / `platform_url` / `last_error` via `not.anyOf` JSON-Schema clauses | `live_api_response.schema.json` |
| Token in error messages | `_scrub_secrets()` regex replaces Authorization-header values with `<REDACTED>` before persistence; ECMA-262-compliant pattern (Codex v1.1.6 round-2 fix) | `_scrub_secrets()` |
| Stale prior-state poisoned with token | `_load_prior_state_validated()` runs F5 schema check on the prior file + applies `_looks_token_shaped()` quarantine; rejects the file silently rather than echoing through | `_load_prior_state_validated()` |
| Concurrent runs creating duplicate POSTs | `fcntl.flock` per `(workspace, platform)` lock; second run sees `_LockBusy` and exits 2 | `_acquire_platform_lock()` |
| Cross-platform state collision (Jira run skipping Linear) | Per-platform response filenames (`live_api_response_{jira,linear,github}.json`); F5 dispatcher regex narrowed to per-platform; loader filters by `platform` field | Codex v1.1.6 round-1 critical fix |
| Linear GraphQL "soft failure" treated as success | `_is_linear_success()` strict check (no errors[] AND data.issueCreate.success=true AND non-empty identifier) | Codex v1.1.6 round-1 critical fix |

**Open risks**:
- Token leakage via Python tracebacks if `urlopen` raises an unexpected exception not wrapped by our scrub. Mitigation: outer `try/except` in `_process_row` catches all and routes through `_scrub_secrets()`. Spot-checked but not exhaustively unit-tested.
- Tokens stored in operator-side files (e.g., `.envrc`, `.netrc`) are out of scope for this plugin's mitigations — operator uses their own secret store.

### 2. Single-writer canonical (INV-02)

| Vector | Mitigation | Pinned by |
|---|---|---|
| Worker skill writes directly to `analysis/canonical/` | `hooks/pre_write_canonical.sh` blocks any Write/Edit by non-orchestrator caller | INV-02 + identity check |
| Hook bypass via env-var override of plugin location | Hook does NOT honor operator-supplied `BSA_PLUGIN_REPO`; plugin location resolved from `pwd -P $(dirname "$0")/..` (Codex C2 lockdown) | `hooks/pre_write_canonical.sh:78-95` |
| Path traversal via `..`-segments in `file_path` | Validator runs `posixpath.normpath()` before dispatcher regex match (Codex C3 hardening, v1.0.2) | `_normalize_path()` |
| Schema drift bypass (camelCase markers, legacy ClaimType) | F5 hook validates content-shape, not just identity | `pre_write_canonical.sh` + `write_validator.py` |

**Open risks**:
- The hook trusts `BSA_WRITER` env var for identity check (v1.0.2 design choice; documented). An attacker with shell access to the operator's session can spoof it. Defense-in-depth: the F5 content validator catches malformed payloads regardless of identity, so identity spoofing alone doesn't enable schema drift.

### 3. Cross-artifact validator (v1.1.3)

| Vector | Mitigation | Pinned by |
|---|---|---|
| Sibling-cache loading attacker-controlled CSV from outside workspace | `_resolve_sibling_dir` requires `analysis/canonical/core_controls/` suffix + on-disk `is_dir()` check; sibling reads anchored to `BSA_WORKSPACE_CWD` (set by hook) or process CWD | `_resolve_sibling_dir()` |
| Path-traversal in sibling filename | Sibling filenames hard-coded (`A50_source_register.csv`, etc.) per schema's `x-bsa-foreign-key-rules.<field>_resolves_in`; not operator-controlled | `_apply_foreign_key_rules()` |
| Memory exhaustion from huge sibling CSV | Sibling cache is per-validation-run; bounded by N rows of A50/A59/A70. No mitigation for explicit DoS but A50 etc. have row-count practical bounds | (open) |

### 4. Migration script (v1.1.2)

| Vector | Mitigation | Pinned by |
|---|---|---|
| Mass overwrite of canonical files without backup | `_backup()` writes `.pre-v1.1.bak` before every write; first-run wins (idempotent) | `migrate_v1.0_to_v1.1.py::_backup` |
| Headerless CSV silently downgrading to no-column skip | `_csv_read_validated()` raises `HeaderValidationError` when none of the expected marker columns are present (Codex v1.1.2 round-1 should-fix) | `_csv_read_validated()` |
| Phase-3 write log records `applied` before write actually succeeded | Phase 1+2 emit `planned` only; phase 3 emits `applied` (or `error`) per file after each successful write | Codex v1.1.2 round-1 should-fix |

### 5. Hook scripts (`pre_write_canonical.sh`, `pre_promote.sh` if present)

| Vector | Mitigation | Pinned by |
|---|---|---|
| Hook running operator-controlled Python via env-var injection | Plugin repo location locked to `pwd -P $(dirname "$0")/..` + `CLAUDE_PLUGIN_ROOT` fallback only; `BSA_PLUGIN_REPO` operator override explicitly forbidden | v1.0.2 C3 (Codex security review) |
| Hook bypass via JSON-decode failure | Hook exits 0 on stdin parse failure (preserves backward compat with non-JSON stdin) — but the F5 content validator runs only on valid JSON, so a malformed JSON write is silently waved through. Open risk; documented. | (open — Phase-5 hardening candidate) |
| Hook timing-side-channel | Not in scope (hook is local; no network; no timing-sensitive crypto comparisons) | n/a |

### 6. Schema drift / governance bypass

| Vector | Mitigation | Pinned by |
|---|---|---|
| Operator manually edits canonical CSV to inject drifted enum value | F5 hook + jsonschema validator reject non-enum values | `_make_csv_validator()` |
| Operator extends a closed enum (e.g., A51 IssueType, ClaimType) without invariant bump | INV-07 declares ClaimType enum closed; major CanonPolicyVersion bump required for any extension; pytest invariants pin the closure | `tests/test_schemas_a59.py` + INV-07 |
| Adversarial fixture state slipping past schema validator | `tests/test_adversarial_b3_fixtures.py::test_fixture_csv_passes_live_write_validator` exercises every adversarial fixture's CSVs against the live F5 validator | v1.1.5 round-1 hardening |

### 7. Privacy / PII leakage

| Vector | Mitigation | Pinned by |
|---|---|---|
| Real client name in committed canonical CSVs | Pre-commit `privacy_scan.py` enforces 0 blockers; v1.1.7 anonymization scrubbed all active-surface client-name leaks | `privacy_scan.py` + v1.1.7 patch |
| PII (email, SSN, credit card) in committed test fixtures | `privacy_scan.py` Luhn check + email + token regex set | `privacy_scan.py` |
| Real-engagement workspace path leaking via committed test logs | Test fixtures use `<operator-local-path>/<pilot-1>/...` placeholders since v1.1.7; tests use `tmp_path` exclusively | v1.1.7 anonymization |

## Defense-in-depth pattern

The plugin uses multiple overlapping defenses for high-value vectors:

- **Token leakage**: env-var indirection + scrub regex + F5 schema-level token-shape rejection + prior-state quarantine. ANY one of these failing still leaves the others as backstop.
- **Schema drift**: closed-enum schema + per-row validator + cross-field rules + cross-artifact validator + adversarial fixture regression. Drift would have to evade ALL five.
- **Privacy**: pre-commit privacy scan + CI privacy scan + anonymization audit + retro/active-surface separation.

## Out-of-scope threats

- **Network attacker** beyond the live API client (no inbound surface; outbound is operator-controlled).
- **Operator-side malware** that has already compromised the workspace (this plugin's mitigations assume the operator's machine is trusted; if it's not, the plugin can't recover that).
- **Side-channel attacks** on the LLM (prompt injection in source documents IS in scope and exercised by the prompt-injection adversarial fixture; LLM-internal attacks like jailbreaks are Anthropic's concern).
- **Cryptographic attacks** (no custom crypto; relies on Python stdlib + OpenSSL).
- **Regulated-domain compliance** (FIPS / SOX / HIPAA / GDPR right-to-erasure) — Phase 5 / Phase 8 scope.

## Mitigation drift detection

`scripts/security_audit.py` runs as part of CI (`.github/workflows/ci.yml::security-audit` job). It catches drift in:

- Hardcoded credentials in `scripts/`, `tests/`, `governance/`.
- `shell=True` subprocess calls without sanitized args.
- `eval()` / `exec()` / `compile()` usage in non-test scripts.
- File-write paths that escape the workspace (`..`-segment heuristic).
- Unscrubbed token references in committed test fixtures.

Operator can run locally: `python3 scripts/security_audit.py`.
