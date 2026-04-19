# BSA Plugin Family

![CI](https://github.com/OWNER/bsa-plugin-family/actions/workflows/ci.yml/badge.svg)

Evidence-first BA/SA analytical pipeline packaged as a Claude Code plugin family. Anti-hallucination gates, claim-binding traceability, two-key promotion, and artifact-first governance.

> **Note:** the CI badge above points at `OWNER/bsa-plugin-family` as a placeholder. Replace `OWNER` with the actual GitHub owner once the repo is pushed to a remote.

## Status

**v0.9.0-foundation** — Phase 0 (Foundation). Not yet installable. Development tracked in maintainer's private sprint plan.

Target MVP: `bsa-full@1.0.0` over a 12-week roadmap across Phase 0 (Foundation), Phase 1 (P0 Stabilization), and Phase 2 (Plugin MVP).

## Architecture

Two-phase pipeline:

- **Discovery (D1-D5, optional):** problem framing → context research → hypothesis prioritization → feasibility → synthesis
- **Main cycle (Stage 1-8 + Handoff):** evidence intake → claim binding → context/state → semantic → catalogs → backbone → contracts → validation → readiness → H1-H4 handoff

Governance invariants: evidence-binding, single-writer canonical, no-new-claims, two-key promotion, composition-via-orchestrator, `ClaimType` schema closed. Registry: [governance/immutable_invariants.md](governance/immutable_invariants.md).

## Repository layout

```
skills/                 22 worker/auditor/sidecar skills (bsa-*, d0-*, sidecars)
scripts/                Bootstrap + (Sprint 0.5+) validators, fixture runners, migration tools
tests/                  Unit tests for scripts
fixtures/golden/        (Sprint 0.5+) Regression fixtures (end-to-end pipeline runs)
config/                 (Sprint 0.5+) Routing manifest + runtime profiles
governance/             Immutable invariants + (Sprint 3+) contract versioning
migrations/             (Sprint 2+) Version-to-version migration packs
docs/                   (Sprint 0+) Inventory audits, privacy reports, architecture
.github/workflows/      (Sprint 0+) CI pipelines
.claude-plugin/         (Sprint 4+) Plugin manifest
```

Note: v1.0.0 will include 23 skills once `bsa-context-framer` is added in Sprint 1 (Stage 2 worker). Current Phase 0 baseline has 22.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Single maintainer, solo + AI-assist workflow.

## License

See [LICENSE](LICENSE).
