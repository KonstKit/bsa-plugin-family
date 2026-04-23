# Security Policy

## Reporting a vulnerability

The repo is solo-maintained today (no public remote). When the repo lands on a public remote, the recommended channel will be:

1. **Preferred:** [GitHub Security Advisories](https://github.com/<owner>/bsa-plugin-family/security/advisories/new) — private disclosure, structured CVE assignment when applicable.
2. **Fallback:** open a regular issue using the bug-report template **only** if the issue is non-exploitable (e.g., hardening recommendation that doesn't expose live attack vectors).

For high-severity issues that require coordinated disclosure (e.g., token-handling vulnerability that could expose operator credentials), please use the GitHub Security Advisory flow rather than a public issue.

## Supported versions

Security fixes target the latest released minor version. The v1.1.x line is current; older v1.0.x is no longer maintained.

| Version line | Status |
|---|---|
| v1.1.x | supported (latest) |
| v1.0.x | superseded by v1.1.x — operators should run `scripts/migrate_v1.0_to_v1.1.py` to bring workspaces forward |
| v0.9.x and earlier | unsupported |

## Threat model

See [`docs/threat_model.md`](docs/threat_model.md) for the explicit attack-surface inventory + mitigations. Highlights:

- **Token handling** (Live API client, v1.1.6): env-var indirection only; tokens never in CLI args / log records / response files; Authorization headers scrubbed in error messages; schema-level token-shape rejection in `live_api_response_*.json`; per-platform `fcntl.flock` concurrency lock.
- **Single-writer canonical** (INV-02): only `bsa-orchestrator` writes under `analysis/canonical/`; enforced by `hooks/pre_write_canonical.sh`.
- **Path traversal**: write-validator normalizes `..`-segments via `posixpath.normpath` before dispatching (v1.0.2 C3 hardening).
- **Env-var injection**: hook script does NOT honor operator-supplied `BSA_PLUGIN_REPO` overrides (v1.0.2 C2 lockdown). The `BSA_WORKSPACE_CWD` env (v1.1.3) is treated as an anchor hint, not a privileged escalation.
- **Schema drift bypass**: F5 hook validates content-shape, not just identity, so a malformed write fails at the hook (v1.0.2 C1 fix).
- **Secrets in commits**: `scripts/privacy_scan.py` enforces 0 blockers as part of the pre-commit checklist + CI gating.
- **Token leakage in error messages**: `_scrub_secrets()` regex (v1.1.6) replaces Authorization-header values with `<REDACTED>` in any persisted error string.

## Automated security audit

`scripts/security_audit.py` runs as part of CI on every push (see `.github/workflows/ci.yml::security-audit` job). It catches:

- Hardcoded credentials in `scripts/`, `tests/`, `governance/` (token-shape regex set; complements `privacy_scan.py`).
- `shell=True` subprocess calls without sanitized args.
- `eval()` / `exec()` / `compile()` usage in non-test scripts.
- File-write paths that escape the workspace (`..`-segment heuristic).
- Unscrubbed token references in committed test fixtures.

Operators can run it locally: `python3 scripts/security_audit.py`.

## Pre-merge security gates

Every PR (when the repo is on a public remote) MUST pass:

1. `scripts/privacy_scan.py` — 0 blockers.
2. `scripts/security_audit.py` — 0 critical, ≤ N warnings (where N is documented in the audit script).
3. `tests/test_backlog_live_apply.py` — token-handling regressions (12 security-focused tests in v1.1.6).
4. `tests/test_security_audit.py` — security-audit script's own regression suite.

## Anonymization policy

Active surface (schemas / scripts / docs / tests / hooks) MUST NOT reference real client names. Use the universal alias `Pilot-1` / `Pilot-N` for external pilot engagements. Historical sprint retrospectives (`docs/retros/sprint_*.md`) and git commit messages are exempt — they're development-history records.

This is part of the security/privacy posture: the public plugin surface should not leak engagement attribution. See [v1.1.7 anonymization](CHANGELOG.md#v117--2026-04-23) for the contract.

## Cryptographic implementation

The plugin does not implement cryptography itself. It relies on:

- Python `hashlib.sha256()` (stdlib) for canon-policy hashing.
- HTTPS via `urllib.request` (stdlib) for live API calls — TLS implementation is the operator's Python build (typically OpenSSL).
- No key management; no signing; no encryption-at-rest. Tokens flow through env vars and live in operator-controlled secret stores (e.g., 1Password, Bitwarden, OS keychain).

If your engagement requires FIPS-validated crypto / regulated cryptographic primitives, this plugin is **not** the right tool today (Phase 5 pack layer would be the place for that).

## Supply-chain notes

- Test-only dependencies: `pytest`, `jsonschema`, `PyYAML` (pinned in `requirements-dev.txt`).
- Runtime dependencies: stdlib only (no third-party Python deps in production scripts).
- GitHub Actions: pinned to current major versions (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4`); Dependabot weekly updates batched per ecosystem.
- The plugin install path is local-only today; tarballs from `.github/workflows/release.yml` are reproducible (`tar` with explicit excludes; no embedded build artifacts).
