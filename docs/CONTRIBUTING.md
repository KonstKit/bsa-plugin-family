# Contributing — BSA Plugin Family

Operator-facing contributor guide. Codifies the discipline accumulated across v1.0 → v1.3.3 — 15 self-review lessons, Codex review workflow, two-semver convention, canon-bump discipline.

## Read this first

Five hard rules:

1. **Canonical writes go through `governance/schemas/write_validator.py`'s F5 hook.** No new code path may write under `analysis/canonical/` outside this hook. The hook enforces every schema, every cross-row rule, every immutable invariant. Bypassing it = INV-02 violation.
2. **Skill = canon-bumping. Script = canon-neutral.** New `skills/<name>/SKILL.md` (or new `references/integration-contract.md` / `anchor_manifest.schema.json`) edits POLICY_GLOBS; the canon hash bumps; the manifest must move in lockstep. Pure `scripts/<name>.py` additions (operator-tooling) leave canon unchanged. Choose the right shape for the change.
3. **Operator-runner pattern for new scripts.** Stdlib + minimal deps. Defensive reads. Atomic writes via `tempfile + os.replace`. CLI surface: `--workspace`, `--input` (override + bypass workspace guard), `--output-dir` (implicit-permissive / explicit-rejected), `--print-only`, `--quiet`. Exit codes: 0 / 2. Mirror `scripts/freshness_audit.py` (v1.2.16) or `skills/proto-from-context/scripts/generate_proto.py` (v1.3.2).
4. **NEVER run git/commit/push from any pipeline script.** Operator drives all commits per `docs/RELEASING.md`. Mirrors v1.2.19 patcher's never-list. Verified by `test_script_does_not_import_subprocess` regressions.
5. **Codex review before commit.** Run a self-review pass first (15-lesson checklist below), then `codex exec --skip-git-repo-check -s read-only -m gpt-5.4` per the workflow in this doc. Canon-bumping releases typically need 2-5 rounds; canon-neutral 1-2.

## Two-semver convention

The repo uses two independent semver dimensions. Keep them consistent.

- **`.claude-plugin/plugin.json::version`** — plugin manifest version. Bumps ONLY when canon-policy state changes (any file in `scripts/compute_canon_hash.py::POLICY_GLOBS` was edited). Enforced by `tests/test_plugin_manifest.py::test_manifest_version_and_canon_semver_agree`.
- **Git tag `vX.Y.Z`** — operator-facing release marker. May advance independently when the patch is operator-tooling-only (new scripts, new tests, new fixtures, docs).

See `docs/RELEASING.md` for the full table of historical examples + the release procedure (commit direct-to-main + local tag, no push).

## The 15 self-review lessons

Run this checklist BEFORE invoking Codex. Skipping it cost 5+ Codex round cascades in v1.2.16/v1.2.17 — most findings were catchable with basic checks.

### Process-side (1-7)

1. **Impact analysis on consumers.** When editing a schema property or shared constant: `grep -rn "<field-name>" --include="*.py" --include="*.md"`. Every consumer must tolerate the new shape OR be updated in the same commit.
2. **Read cross-referenced schemas.** When emitting a "draft row" or "suggested entry" for another artifact, read THAT artifact's schema and check `required[]` + key constraints.
3. **Edge-case sweep.** For string fields: empty / whitespace-only / whitespace-padded / Unicode digits / case variants / leading-zero / boundary / future-dated / multi-value (`;`/`/`-joined per multi-FK contract). For numeric: 0 / negative / max / NaN / overflow.
4. **Layer-overlap check.** When adding a new validator/handler, list every OTHER validator that touches the same input. Where do they overlap? Will a bad input fire BOTH? That's a double-violation bug — gate the new handler so its reach is ≤ existing layer's reach.
5. **Reach equality.** When a handler's regex/check is meant to mirror a schema's regex/enum, verify them character-by-character. Python `\d` ≠ JSON Schema `[0-9]`. `.strip()` in handler ≠ anchored schema regex.
6. **Documentation alignment after every fix.** When a fix changes accepted values (e.g., empty string now allowed), every place that documents the contract must be updated in the SAME commit. Don't wait for the next Codex round to flag stale docs.
7. **Use cheaper subagents first.** `inject-prevention`, `staff-critical-code-review` skill are local. Run one before paying Codex. Especially for security-relevant code.

### Domain-side (8-14, accumulated v1.2.19 — v1.3.2)

8. **Untrusted input as path component.** ANY value from a JSON / YAML / user file / API response that becomes a filename or directory MUST be validated against an explicit pattern BEFORE construction. Schema regex is the canonical filter. Defense-in-depth: also check `.resolve().relative_to(output_dir.resolve())` to catch symlink/`..` slip past the regex. Test with `../escape`, `/`, null bytes, control chars, leading hyphen.
9. **Exception after side-effect.** When emitting multiple artifacts in a loop, `Path.relative_to(base)` raises `ValueError` if the path is outside `base`. If `relative_to` comes AFTER the file is written, you get partial-state + crash. Compute the path string BEFORE the write, OR guard with `_is_relative_to()` + explicit fallback.
10. **Consumer-of-the-signal-I-just-changed.** A refactor that changes a value (e.g., "patch path was repo-relative; now may be absolute") leaves stale consumers that copied the OLD form. Search for downstream USES of the changed signal — not just upstream PRODUCERS — and update in lockstep.
11. **Shell-quote operator-pasteable commands.** Any rendered shell snippet (Markdown summary, log line, generated runbook step) that interpolates a path or argument MUST go through `shlex.quote()`. A path with spaces / metacharacters / control chars produces a broken or misleading command otherwise.
12. **Leading-hyphen-safe command construction.** `shlex.quote()` is necessary but NOT sufficient. A path like `-out/file` is shell-safe but `git apply '-out/file'` still parses `-out/file` as a git option. Use the `--` end-of-options separator: `git apply -- <quoted-path>`.
13. **Encoded-traversal defense: regex-level character-class rejection beats recursive decode-until-stable.** v1.3.0 R2: my fix used two-pass `urllib.parse.unquote` to catch `%2e%2e` and `%252e%252e`, but triple-encoded `%25252e%25252e` survived. Removing `%` from the regex character class entirely closed the entire encoding-depth attack class atomically. **Atomic gate beats iterative defense.**
14. **ASCII shape regex must be paired with domain-specific syntax validation when the regex admits malformed structure.** v1.3.0 R1: shape regex permitted `{` and `}` without enforcing balanced / non-empty / well-ordered template syntax. Always check: "what malformed inputs does my permissive regex admit?" + add an explicit structural scan.

### Spec-side (12-13 from v1.3.1, 14 from v1.3.2)

(Numbered to match `feedback_self_review_before_codex.md` original order; some overlap with above. Treat the canonical list as the merged 15.)

- **Spec-bridging exporters: read the target spec's reference page for the exact element being emitted, including required sub-fields per element kind.** v1.3.1 R1: AsyncAPI Channel Object spec REQUIRES `parameters: {<name>: {...}}` for every Channel Address Expression `{order_id}`. v1.3.2 R1: proto3 field name grammar is `^[A-Za-z_][A-Za-z0-9_]*$`, NOT v1.3.1's permissive `^[A-Za-z0-9_-]+$`.
- **Reach equality applies INSIDE the gate, not just at the gate boundary.** v1.3.1 R2: brace-balance scan accepted any chars in `{...}` while extractor was narrower. Both must agree on the EXACT character class.
- **When porting a charset/regex constant across exporters in a sibling family, do NOT reuse it verbatim — re-derive from the new exporter's downstream consumer grammar.** v1.3.2 R1: I copied AsyncAPI's parameter charset into proto exporter, but proto3 field names don't allow hyphens.

### Untrusted-input-from-files (15, from v1.3.3)

15. **Untrusted-input-as-path-component applies to file-content extraction, not just CLI args.** v1.3.3 R1: `proposal_id` from `_index.json` was used raw in path joins. The file is operator-authored in normal use, but a downstream tool emitting the JSON could craft a `proposal_id` like `../../etc/passwd` that escapes both read AND write boundaries. The validate-before-path-join discipline (lesson #8) covers ANY value that flows into a path — CLI arg, JSON value, CSV cell, YAML field. Pin with regression test for `../escape`, `/separators`, empty/non-string values.

## Codex review workflow

Codex is a safety net, not a primary reviewer. Self-review first.

### CLI invocation (the only working form)

`mcp__codex__codex` is broken (returns only `threadId`). Use `codex exec` via Bash:

```bash
CODEX_ID=$(date +%s)
cat > /tmp/codex_prompt_${CODEX_ID}.txt <<'PROMPT'
[your 7-section prompt here]
PROMPT

codex exec --skip-git-repo-check -s read-only -m gpt-5.4 \
    -o /tmp/codex_out_${CODEX_ID}.txt \
    "$(cat /tmp/codex_prompt_${CODEX_ID}.txt)" \
    </dev/null
cat /tmp/codex_out_${CODEX_ID}.txt
```

Two gotchas:
- **`</dev/null` is mandatory for codex exec 0.125+.** Without it the CLI waits for EOF on stdin forever — appears as a hang.
- **Use unique CODEX_ID per call.** Reusing `/tmp/codex_out.txt` causes you to read the previous run's output and miss the actual review.

### 7-section prompt format

Every Codex delegation prompt MUST include:

```
TASK: [One sentence — atomic, specific goal]

EXPECTED OUTCOME: [What success looks like; verdict format]

CONTEXT:
- Workspace: [absolute path]
- Files to read: [list with brief descriptions]
- Recent diff/change: [what's new]
- Key design decisions: [locked choices the reviewer should not relitigate]

CONSTRAINTS:
- Workspace: [path]
- Read-only review.
- Canon-bumping or canon-neutral?
- Author wants N rounds (typical: 2-3 for canon-bumping, 1-2 for canon-neutral).

MUST DO:
- [Specific verifications to perform]
- [Specific files to read in full vs spot-check]

MUST NOT DO:
- Re-litigate prior round findings.
- Demand framework adoption (X chosen deliberately).
- Suggest stylistic changes that aren't release-blocking.

OUTPUT FORMAT:
1. Verdict: APPROVE or REQUEST CHANGES
2. Severity-bucketed findings: MAJOR (release-blocking) / MINOR (doc-drift) / NIT (style).
3. Per finding: file:line + 1-3 sentence description + concrete fix suggestion.

DEVELOPER INSTRUCTIONS:
[Role + tone + specifics about what NOT to nitpick]
```

### Round expectations by release shape

| Release type | Typical rounds | Why |
|---|---|---|
| Pure docs | 1 | Trivial; usually APPROVE first round. |
| Canon-neutral script (operator-tooling) | 1-2 | Read-only or operator-side; lower security surface. |
| Schema extension (canon-neutral) | 2-3 | Cross-artifact regression risk. |
| New skill (canon-bumping) | 3-5 | Full surface; new POLICY_GLOBS file means many places to keep in lockstep. |
| Stage 6 contract exporter | 2-4 | Domain-specific spec gotchas surface in R1; doc drift in R2-R3. |
| Hotfix | 1-2 | Narrow scope. |

### Background-mode Codex run

For long Codex calls (canon-bumping releases ≈ 3-7 minutes per round):

```bash
# Use Bash tool with run_in_background: true
# Do NOT pgrep + sleep loop — the wait-loop's argv matches "codex exec"
# and the loop never exits even after the real process dies.
# Use the background-task notification system (Bash tool surfaces it).
```

## Canon-bump discipline

When you edit ANY file in `scripts/compute_canon_hash.py::POLICY_GLOBS`:

1. **Make all edits first.** Don't recompute the hash mid-batch.
2. **Run `python3 scripts/compute_canon_hash.py`.** Capture the new full hex digest.
3. **Update `.claude-plugin/plugin.json` `version`** AND **`.claude-plugin/canon_policy.json`** (v1.3.6 split — bump `semver` AND `hash_prefix` (8-char) AND `hash_full` (full 64-char) AND `computed_at`). Both files MUST move in lockstep — `tests/test_plugin_manifest.py::test_manifest_version_and_canon_semver_agree` enforces it.
4. **Update 5 `fixtures/golden/project_0004_sidecar_e2e/` metadata files** in lockstep:
   - `fixture_metadata.json` (`canon_policy_version` + `plugin_version`)
   - `expected_outputs/views/{bpmn,c4,dbml}/anchor_manifest.json` (`canon_policy_version`)
   - `expected_markers/stage1.excerpts.merged.json` (`canon_policy_version` + `canon_policy_version_hash`)
5. **Run `python3 -m pytest tests/test_plugin_manifest.py`** — confirms manifest+hash agreement.
6. **Update `CHANGELOG.md` + `docs/RELEASING.md`** — both narrative + table row carry the new hash.
7. **Run final validators**: full pytest, `scripts/privacy_scan.py`, `scripts/phase_7_lint.py`, `scripts/fixture_runner.py`.
8. **Commit + tag**: direct-to-main commit, local annotated tag, no push (per release workflow).

## Surprise patterns from history

- **POLICY_GLOBS surprise**: a sidecar's `references/integration-contract.md` IS in POLICY_GLOBS (caught v1.2.15 — turned an expected canon-neutral release into a canon-bump and forced lockstep manifest + 5 fixture metadata updates).
- **Single-pass parser refactor**: when a validator/auditor needs multiple passes over the same artifact, prefer one parser call returning a tuple over re-scanning. Closed an entire class of false-positives in v1.2.15.
- **Atomic gate beats iterative defense**: see lesson #13. Removing `%` from the regex character class atomically closes the recursive-decode attack surface — better than recursive `urllib.parse.unquote`.
- **Five-surface grep after any code change touching emission shape OR validation gate**: SKILL.md + integration-contract.md + anchor_manifest.schema.json (description fields, not just structural pattern) + CHANGELOG.md + docs/RELEASING.md. If the change touches a constant referenced in a docstring, add `generate_<format>.py` as 6th surface.

## File layout reference

```
.claude-plugin/plugin.json           # Plugin manifest (Claude Code-schema-valid: name/version/description/license/...)
.claude-plugin/canon_policy.json     # Canon policy version block (v1.3.6 split from plugin.json)
.claude-plugin/marketplace.json      # Local-only marketplace registration
governance/
├── immutable_invariants.md          # INV-01..INV-10 (POLICY_GLOBS)
└── schemas/
    ├── *.schema.json                # Draft 2020-12 schemas
    ├── loader.py                    # iter_a*_rows + iter_csv_rows
    └── write_validator.py           # F5 hook (every canonical write)
skills/
├── bsa-*/                           # Pipeline skills (Stage 0-8)
├── d0-*/                            # Discovery skills (d0/d1/...)
├── *-from-context/                  # Sidecars + Stage 6 exporters
└── inot-prompt-builder/             # Auxiliary
scripts/
├── compute_canon_hash.py            # POLICY_GLOBS authoritative list
├── freshness_audit.py               # v1.2.16 — operator-runner template
├── triangulation_audit.py           # v1.2.17
├── phase_7_*.py                     # Phase 7 L0/L1a/L1b/L2
├── generate_dashboard.py            # v1.3.3 — dashboard
└── dashboard/                       # Dashboard renderers/templates/static
docs/
├── RELEASING.md                     # Release procedure + history
├── CONTRIBUTING.md                  # This file
├── architecture_overview.md         # System overview
├── dashboard_runbook.md             # v1.3.3 dashboard operator how-to
├── phase_7_runbook.md               # Phase 7 review workflow
├── cookbook/                        # Recipes for adding new artifacts
└── retros/                          # Per-release retrospectives
fixtures/golden/
├── project_0001 .. project_0003/    # End-to-end pipeline fixtures
├── project_0004_sidecar_e2e/        # Sidecar + canon hash regression
└── adversarial_*/                   # Edge-case probes
config/
└── tunables.yaml                    # Phase 7 L0 inventory (POLICY_GLOBS-adjacent)
```

## Cross-references

- `docs/RELEASING.md` — release procedure + two-semver convention table.
- `docs/dashboard_runbook.md` — operator how-to for the v1.3.3 dashboard.
- `docs/cookbook/` — recipes (add a new exporter / audit / sidecar / Phase 7 tunable).
- `docs/phase_7_runbook.md` — operator workflow for the L2 patcher.
- `docs/architecture_overview.md` — system overview (Stage 0-8 pipeline + dev-handoff + Stage 6 contract exporter family + dashboard).
- `governance/immutable_invariants.md` — INV-01..INV-10 (the un-tunable rules).
