---
name: bsa-orchestrator
description: Orchestrate optional D0 discovery and the main BSA pipeline as an artifact-first, evidence-bound analytical conveyor with single-writer merges, mandatory audit gates, and no-hallucination promotion rules.
---

# BSA Orchestrator

Use this skill as the control plane for discovery and main-cycle execution.

## Responsibilities
- Create and maintain `analysis/` + `analysis/discovery/` runtime structures.
- Treat completion as `artifact-first`: required files + markers are the contract; chat prose is never a substitute.
- Route Stage 1 as a composite stage: `bsa-evidence-intake` -> `bsa-claim-binder`.
- Execute Stage 2 via the dedicated worker `bsa-context-framer` between Stage 1 promotion and Stage 3 entry; promotion gated by `stage2.context_state.pass`.
- Enforce single-writer canonical ownership for shared controls `A48/A50/A51` and promoted claim/anchor controls `A58/A59/A60/A61`.
- Enforce two-key promotion gates:
  - evidence-binding (`ClaimID` with `SourceID+ExcerptID`, or explicit `A51Ref` for unresolved items),
  - required audit-pass marker set.
- Halt promotion on hard-blocking `A51` items, failed audits, parallel ledgers, broken anchor maps, or detected new-claim leakage.
- Emit marker-driven transitions including `D0 -> BSA` entry controls.
- Keep sidecars derived-only.

## Bootstrap
1. Create runtime layout under `analysis/` and `analysis/discovery/` (`runtime`, `proposals`, `canonical`, `handoff`, `views`).
2. Initialize shared controls `A48/A50/A51` and set `A48.Mode` (`direct` or `discovery_then_bsa`).
3. Register initial event/guard artifacts and lock zones.
4. Emit initial readiness markers for selected mode (`discovery.d1.ready` for discovery mode, Stage 1 start readiness for direct mode).

## Stage Model
- Main cycle ordering is explicit: `stage1 -> stage2 -> stage3 -> stage4 -> stage5 -> stage6 -> stage7 -> stage8 -> handoff`.
- `stage2` is worker-owned by `bsa-context-framer` (added Sprint 1 US-S1-01). The orchestrator routes Stage 1 promoted claim-layer into the framer, receives 5 proposal artifacts (context_state_frame / stakeholder_authority_map / system_context_seed / constraints_dependencies_route / stage2_summary.json), runs the Stage 2 audit flow, and promotes on `stage2.context_state.pass`.
- Discovery branch (`d1..d5`) remains optional and precedes main-cycle entry.
- `d0-*` skill names are a namespace label for the discovery branch family, not a stage number.

## Routing Boundary
- This skill is `control-plane only`. It does not replace D1-D5 discovery workers or Stage 1-8 workers.
- A request to build a main-cycle analytical pack from mixed sources such as `docx`, `xlsx`, transcripts, call notes, tickets, mixed corpora, or repository documents must not be routed to `bsa-orchestrator` alone.
- The required worker set for `bsa_pack_direct_mixed_sources` is:
  - `bsa-orchestrator`
  - `bsa-evidence-intake`
  - `bsa-claim-binder`
  - `bsa-context-framer`
  - `bsa-semantic-extractor`
  - `bsa-domain-modeler`
  - `bsa-backbone-builder`
  - `bsa-anchor-auditor`
  - `bsa-contract-builder`
  - `bsa-citation-auditor`
  - `bsa-consistency-auditor`
  - `bsa-skeptical-reviewer`
  - `bsa-no-new-claims-auditor`
  - `bsa-validation-readiness`
  - `bsa-handoff-packager`
- `bsa-context-framer` runs between Stage 1 composite (`bsa-evidence-intake` -> `bsa-claim-binder`) and `bsa-semantic-extractor`. It owns Stage 2 framing; the orchestrator gates Stage 3 start on `stage2.context_state.pass`.
- The required worker set for `discovery_pack_mixed_sources` is:
  - `bsa-orchestrator`
  - `d0-problem-framer`
  - `d0-context-researcher`
  - `d0-hypothesis-prioritizer`
  - `d0-feasibility-assessor`
  - `d0-synthesis-gatekeeper`
  - `bsa-citation-auditor`
  - `bsa-skeptical-reviewer`
  - `bsa-no-new-claims-auditor`
- Add `bsa-evidence-intake` when mixed-source inventory, contradiction scan, or Stage 1 bridge materialization is required.
- Add sidecars only when trigger contracts exist and their outputs remain derived-only.
- Repo-visible routing contract: `config/request_skill_routes.json`, validated by `scripts/validate_request_skill_routing.py`.

## Required Marker Families
Main cycle (runtime contract):
- `stage1.excerpts.merged.json`
- `stage2.context_state.pass.json`
- `stage3.citation_audit.pass.json`
- `stage5.anchor_audit.pass.json`
- `stage6.anchor_audit.pass.json`
- `stage7.skeptical_review.pass.json`
- `stage8.no_new_claims.pass.json`

Discovery (runtime contract):
- `discovery.d1.ready.json`
- `discovery.d2.claims.merged.json`
- `discovery.d2.research_quality.pass.json`
- `discovery.d3.prioritization.pass.json`
- `discovery.d4.constraint_audit.pass.json`
- `discovery.d5.citation_audit.pass.json`
- `discovery.d5.no_solution_leakage.pass.json`
- `discovery.exit.pass.json`
- `discovery.go.json`
- `discovery.pivot.json`
- `discovery.more_research.json`
- `discovery.no_go.json`
- `bsa.stage1.entry.enabled.json`

## On Audit Failure
1. Do not promote proposal artifacts.
2. Emit/findings in stage-owned proposal directory.
3. Emit re-entry marker for the failed stage family.
4. Route blocking uncertainty/contradiction to shared `A51`.
5. Re-run only affected stage sequence and invalidate downstream markers.

## Quick Start / Typical Flow
1. Bootstrap runtime layout and shared controls.
2. Select mode: `direct` or `discovery_then_bsa`.
3. If discovery mode: run `d1 -> d2 -> d3 -> d4 -> d5`.
4. Validate discovery decision markers and emit `bsa.stage1.entry.enabled` only on `discovery.go`.
5. Run Stage 1 composite (`intake -> claim-binder`) and promote.
6. Run Stage 2 via `bsa-context-framer` to produce the five context/state proposal artifacts; run the Stage 2 audit flow and promote on `stage2.context_state.pass`.
7. Run Stage 3 through Stage 6 with required audit markers.
8. Run Stage 7 validation gates and Stage 8 no-new-claims gate.
9. Run handoff packaging; enforce final no-new-claims gate.
10. Emit completion markers and validation artifacts.

## Contract Versioning
- Keep `A48.CanonPolicyVersion` authoritative for active contract version.
- Treat minor version bumps as backward-compatible contract clarifications.
- Treat major version bumps as breaking changes requiring migration notes.
- Migration must include marker compatibility, artifact-surface compatibility, and re-entry behavior.

## Validation Binding
- `SCN-ORCH-001-A..E`
- `SCN-DISC-001`
- `CHK-GOV-001-08`

## References
- [references/workflow-contract.md](references/workflow-contract.md)
- [references/runtime-marker-schema.md](references/runtime-marker-schema.md)
- [references/run-profile-gates.md](references/run-profile-gates.md)
- [references/ownership-and-lifecycle.md](references/ownership-and-lifecycle.md)
- [references/merge-and-reentry-policy.md](references/merge-and-reentry-policy.md)
- [references/agent-write-scope.md](references/agent-write-scope.md)
- [references/sidecar-integration.md](references/sidecar-integration.md)
- [references/pilot-runbook.md](references/pilot-runbook.md)
- [references/shared-control-surface-contracts.md](references/shared-control-surface-contracts.md)
- [references/canonical-artifact-map.md](references/canonical-artifact-map.md)
- [references/stage2-runtime-contract.md](references/stage2-runtime-contract.md)
- [references/kpi-definitions.md](references/kpi-definitions.md)
- [references/validation-scenario-manifest.csv](references/validation-scenario-manifest.csv)
- [references/contract-versioning.md](references/contract-versioning.md)
