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

**v1.0.3** — security-hotfix line continuing from v1.0.0. v1.0.0 shipped Phase 0-2 MVP (Sprint 4.5 close). v1.0.1 closed 3 reviewer-P-level findings (marker validator alphabet, promote-hook A48 parse, privacy-scan letter-only secrets). v1.0.2 closed 3 CRITICAL + 1 HIGH security findings from retroactive F5 review (hook matcher coverage, A59 cross-field executable rules, env-injection lockdown, marker filename↔payload binding). v1.0.3 applies the same C2 enforcement pattern to A62 + A70 extension rules (NFR measurability, story provenance, INVEST-A51 coupling).

28 skills (23 Phase-0-2 + 5 Phase-3 scaffolds — only 2 Phase-3 skills implemented end-to-end; 3 are SKILL.md scaffolds awaiting Sprint 8 / Sprint 9) • 6 slash-commands + 1 Phase-3 composite (/bsa-dev-handoff) • 3 safety hooks • 3 golden fixtures + 1 adversarial • 991 unit tests as of v1.0.3 (the exact count grows with each release; the invariant is "all pass", not a number) • evidence-bound claim layer (INV-01) • closed `ClaimType` enum (INV-07) • tier-aware weighted coverage (KPI-001) • two-key promotion • no-new-claims gate.

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
skills/                 28 worker/auditor/sidecar/scaffold skills (bsa-*, d0-*, sidecars, inot-prompt-builder)
scripts/                Validators, fixture runners, canon-hash computer, migration tools
tests/                  ~990 unit tests (grows with each release; exact count in the latest sprint retro)
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
