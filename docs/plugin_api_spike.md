# Plugin API Spike — US-S4-01 AC-0

**Status:** complete. Blocking prerequisite for US-S4-01 AC-1..AC-4.
**Date:** 2026-04-20.
**Source:** `claude-code-guide` agent research against `code.claude.com/docs/en/plugins-reference` + open-source plugins under `anthropics/` org.

## Questions and answers

### 1. `plugin.json` schema

Authoritative source: `code.claude.com/docs/en/plugins-reference`. Required field is only `name`; everything else is optional.

| Field | Required | Type | Notes |
|---|---|---|---|
| `name` | **yes** | string | Kebab-case, unique across installed plugins. We use `bsa-full`. |
| `version` | no | string | Semver. When present, plugin.json value wins over marketplace metadata. We use `1.0.0` at release (`1.0.0-rc1` during Sprint 4). |
| `description` | no | string | Short plain-English. |
| `author` | no | object | `{name, email, url}` shape. |
| `license` | no | string | SPDX-style identifier. |
| `homepage`, `repository`, `keywords` | no | string/array | Marketplace-surface metadata. |
| `skills` | no | string/array | Path(s) to skill directories. Relative, leading `./`. Omit to use default `./skills/`. |
| `commands` | no | string/array | Path(s) to command directory OR individual command `.md` files. Default `./commands/`. |
| `agents` | no | string/array | Path(s) to agent markdown. Default `./agents/`. |
| `hooks` | no | string/array/object | Either an inline object or a path to a JSON file (default `./hooks/hooks.json`). |
| `mcpServers` | no | string/array/object | MCP config paths or inline. |
| `dependencies` | no | array | Dependencies on other plugins: `["name"]` or `[{"name": "...", "version": "~2.1.0"}]`. |

**BSA decision.** We use the default layout (`./skills/`, `./commands/`, `./hooks/hooks.json`). Leaving the corresponding plugin.json fields OUT is idiomatic — Claude Code auto-discovers the default paths.

### 2. Custom fields

**Claude Code is permissive — unknown top-level fields in plugin.json are silently preserved.** This means we can put `canonPolicyVersion` directly in the manifest without a separate `bsa-config.json`.

**BSA decision.** Store the canon version + hash at the top level of `plugin.json`:

```json
"canonPolicyVersion": {
  "semver": "1.0.0-rc1",
  "hash_prefix": "ac039430",
  "hash_full": "ac039430bdffdaf66c75107c1792aa71f8bd077c8f1da4f76844cc6b50a4a6f1",
  "computed_by": "scripts/compute_canon_hash.py",
  "computed_at": "2026-04-20T00:00:00Z"
}
```

A release workflow step recomputes the hash at tag-push time and refuses to publish if it disagrees with the plugin.json value.

### 3. Skills directory structure

Each skill is a **directory** under `./skills/` containing at minimum a `SKILL.md` file. Frontmatter `name` field sets the invocation name; directory name is fallback.

```
skills/
├── bsa-orchestrator/SKILL.md
├── bsa-evidence-intake/SKILL.md
├── ...
└── d0-synthesis-gatekeeper/SKILL.md
```

We already have all 23 skills in this shape — no restructuring needed.

### 4. Slash commands

- Each command is a **separate markdown file** under `./commands/`.
- Filename stem is the command name; frontmatter `name` field must match.
- Sub-commands (`bsa start`, `bsa status`, `bsa promote`) are **separate files**, not a single router. Convention is `bsa-start.md`, `bsa-status.md`, `bsa-promote.md`, etc.
- **Claude Code does not parse flags** — documenting `--mode=direct` or `--verbose` in the command body is how users discover them, but the command logic is responsible for handling the argument string itself.

**BSA decision.** We ship six command files matching AC-2 of US-S4-02:
- `bsa-start.md`
- `bsa-status.md`
- `bsa-stage.md`
- `bsa-promote.md`
- `bsa-audit.md`
- `bsa-handoff.md`

Each file's body prompts Claude to delegate to the appropriate skill(s), honor the `--verbose` and `--dry-run` flags documented in the prompt, and surface graceful-degradation messages when optional tools (plantuml, xmllint) are absent.

### 5. Hooks

Hooks live in `./hooks/hooks.json` (default path; plugin.json can override). Supported events include `SessionStart`, `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`, `SessionEnd`, etc.

Hook matcher syntax:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "prompt", "prompt": "..." }] }
    ],
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "matchers": [{ "type": "path", "pattern": "analysis/canonical/*" }],
        "hooks": [{ "type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/block-non-orchestrator.sh" }]
      }
    ]
  }
}
```

- `matcher` is the tool-name regex (e.g., `Write|Edit`, `Bash`).
- `matchers[]` narrows further: `type=path` with glob `pattern`, or `type=command` with regex `pattern`.
- Hook scripts: executable bash under `./hooks/`, use `${CLAUDE_PLUGIN_ROOT}` for portable paths. Exit 0 allows, non-zero blocks.

**BSA decision.** Three hooks per US-S4-03:

- `SessionStart` — prompt-type hook that suggests `/bsa status` when the session starts in a BSA-initialized directory (detected by presence of `analysis/canonical/`).
- `PreToolUse:Write` on canonical paths — blocks non-orchestrator writes.
- `PreToolUse:Bash` on `bsa promote` invocations — blocks if required markers absent.

All three hook scripts stay stdlib-only Python (invoked via `python3` shebang) so they inherit the repo's no-runtime-deps discipline.

### 6. Install flow

Claude Code auto-discovers plugins by looking for `.claude-plugin/plugin.json` at the repo root of anything added via `claude plugin marketplace add <url>`.

Required at repo root:
1. `.claude-plugin/plugin.json` (the manifest).
2. Git tags matching `plugin.json` version for update detection.
3. Optional: `CHANGELOG.md`, `README.md` for discovery.

No special GitHub release-asset requirements. Users run:
```
claude plugin marketplace add https://github.com/<user>/bsa-plugin-family
claude plugin install bsa-full
```

### 7. Reference open-source plugins

Studied for pattern confirmation:

1. **anthropics/claude-plugins-official → plugin-dev** — 7 skills + master command + validation agents. Confirmed the multi-skill + commands layout.
2. **anthropics/claude-code → feature-dev** — sub-agent orchestration pattern. Confirmed our plan of having commands delegate to skills rather than implementing logic inline.
3. **anthropics/claude-code → security-guidance** — `PreToolUse` hook with 9 pattern matchers. Confirmed the matcher-with-nested-matchers syntax.

## Decisions captured

| Decision | Value | Rationale |
|---|---|---|
| Plugin name | `bsa-full` | Per plan. Kebab-case. Unique. |
| Version | `1.0.0-rc1` (then `1.0.0` at Sprint 4.5 cut) | Matches canon policy semver. |
| Canon version placement | Custom field in plugin.json | Codec is permissive; no separate config file needed. |
| Skills directory | `./skills/` (default) | Matches existing layout. |
| Commands directory | `./commands/` (default) | One `.md` per sub-command. |
| Hook config | `./hooks/hooks.json` (default) | Three hooks: SessionStart + two PreToolUse. |
| Hook scripts | `./hooks/*.sh` invoking `python3` | Stdlib-only, matches repo discipline. |
| License | `MIT` | Matches `LICENSE` file committed in Sprint 0. |

## Out of scope for Sprint 4

- Actual install-on-fresh-VM validation — that's US-S4-04 AC-4 (mechanical exercise).
- Custom marketplace (non-GitHub) distribution — Phase 3+.
- Plugin dependencies on other plugins (`dependencies` field) — not needed for Sprint 4 MVP.

## Follow-ups captured for Sprint 4

1. Build `.claude-plugin/plugin.json` with the standard fields + `canonPolicyVersion` block.
2. Write six command files under `./commands/`: bsa-start, bsa-status, bsa-stage, bsa-promote, bsa-audit, bsa-handoff.
3. Write `./hooks/hooks.json` + three executable hook scripts.
4. Author `INSTALL.md` documenting the marketplace + install flow.
5. Add a GitHub Actions release workflow at `.github/workflows/release.yml` that publishes a release when a `v*` tag is pushed and recomputes canon hash.
