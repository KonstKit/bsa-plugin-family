# BSA Plugin Family

**Local-only, solo-maintainer tool.** Evidence-first BA/SA analytical pipeline packaged as a Claude Code plugin. Anti-hallucination gates, claim-binding traceability, two-key promotion, and artifact-first governance. Not published to any public marketplace; installed from a local checkout.

## Install

```
/plugin marketplace add /Users/kkitanin/projects/bsa-plugin-family
/plugin install bsa-full@bsa-marketplace
/plugin list       # expect bsa-full@1.0.0
```

Full install / uninstall / upgrade (including session-only `claude --plugin-dir` path): [INSTALL.md](INSTALL.md).

## 30-second tour

```
cd /tmp/my-engagement
/bsa-start --mode=direct
# drop your sources under analysis/proposals/stage1/inputs/
/bsa-stage 1          # runs bsa-evidence-intake + bsa-claim-binder
/bsa-promote
/bsa-stage 2          # runs bsa-context-framer
/bsa-promote
# ... Stages 3-8 (each with its own worker chain + in-stage audits) ...
/bsa-handoff
```

Each `/bsa-stage N` invocation runs the stage's full worker chain (worker + any in-stage auditor) per the routing manifest. The standalone `/bsa-audit <kind>` command is only needed to re-run a specific audit against current proposals. Full walkthrough + discovery mode: [docs/getting_started.md](docs/getting_started.md).

## Status

**v1.0.0** — first public release (Phase 0-2 MVP close, Sprint 4.5 US-S45-03).

23 skills • 6 slash-commands • 3 safety hooks • 3 golden fixtures + 1 adversarial • 302 unit tests • evidence-bound claim layer (INV-01) • closed `ClaimType` enum (INV-07) • tier-aware weighted coverage (KPI-001) • two-key promotion • no-new-claims gate.

Phase 2.5 external shakedown (2-4 weeks of real-project usage) is the gate before Phase 3 dev-handoff extension begins. See [docs/faq.md](docs/faq.md) "Is this ready for production use?" for the boundaries.

## Architecture

Two-phase pipeline:

- **Discovery (D1-D5, optional):** problem framing → context research → hypothesis prioritization → feasibility → synthesis.
- **Main cycle (Stage 1-8 + Handoff):** evidence intake → claim binding → context/state → semantic catalogs → backbone → contracts → skeptical review → no-new-claims gate → H1-H4 handoff pack.

Governance invariants: evidence-binding, single-writer canonical, no-new-claims, two-key promotion, composition-via-orchestrator, `ClaimType` schema closed. Registry: [governance/immutable_invariants.md](governance/immutable_invariants.md). Full architecture: [docs/architecture_overview.md](docs/architecture_overview.md).

## Repository layout

```
.claude-plugin/         Plugin manifest (plugin.json with canonPolicyVersion)
commands/               6 slash commands (/bsa-start, /bsa-status, /bsa-stage, /bsa-promote, /bsa-audit, /bsa-handoff)
hooks/                  3 safety hooks (SessionStart, PreToolUse:Write, PreToolUse:Bash)
skills/                 23 worker/auditor/sidecar skills (bsa-*, d0-*, sidecars, inot-prompt-builder)
scripts/                Validators, fixture runners, canon-hash computer, migration tools
tests/                  302 unit tests
fixtures/golden/        3 regression fixtures + 1 adversarial prompt-injection fixture
config/                 Orchestrator routing manifest (request_skill_routes.json)
governance/             Immutable invariants registry
migrations/             v0.9 → v1.0 migration pack
docs/                   User + maintainer documentation
```

## Documentation

- [docs/getting_started.md](docs/getting_started.md) — install + first run.
- [docs/workflow.md](docs/workflow.md) — stage-by-stage walkthrough (+ discovery mode).
- [docs/commands_reference.md](docs/commands_reference.md) — every slash command with flags.
- [docs/troubleshooting.md](docs/troubleshooting.md) — common failure modes.
- [docs/architecture_overview.md](docs/architecture_overview.md) — skill families + invariants + governance.
- [docs/faq.md](docs/faq.md) — FAQ.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Solo maintainer, AI-assisted workflow. All commits run `pytest` + `scripts/fixture_runner.py --all` + `scripts/privacy_scan.py` + `scripts/compute_canon_hash.py` locally, and land through a `codex exec` review round before merge.

Sprint history: [docs/retros/](docs/retros/).

## License

See [LICENSE](LICENSE).
