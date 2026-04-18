---
name: bsa-skeptical-reviewer
description: Perform adversarial skeptical review of Stage 7 validation artifacts and discovery D5 synthesis outputs to stress assumptions, boundary claims, and hidden contradictions before gating.
---

# BSA Skeptical Reviewer

Run this skill as a mandatory pre-readiness gate in Stage 7 and reuse it for D5 when discovery is enabled.

## Scope
- Challenge high-impact assumptions and inferred claims.
- Test boundary conditions and contradiction handling.
- Produce blocking/non-blocking skeptical findings.
- Reuse skeptical checks for discovery D5 synthesis outputs without granting discovery artifacts canonical authority.

## Invocation Modes
- Main cycle:
  - Read Stage 7 review pack and audit outputs.
  - Write `skeptical_review_report.md` in `analysis/proposals/stage7_8/stage7/`.
  - Supports marker `stage7.skeptical_review.pass.json`.
- Discovery (D5):
  - Read `analysis/discovery/proposals/d5/` synthesis outputs.
  - Write `discovery_skeptical_review_report.md` in the same folder.
  - Supports optional marker `discovery.d5.skeptical_review.pass.json` when enabled by run profile.
- Mode is determined by orchestrator routing.

## Inputs
- Active mode proposal package.
- Shared `A51` and prior audit reports relevant to active mode.

## Outputs
- `analysis/proposals/stage7_8/stage7/skeptical_review_report.md`
- `analysis/discovery/proposals/d5/discovery_skeptical_review_report.md`

## Workflow
1. Read Stage 7 proposal package, `A51`, citation audit report, and consistency audit report.
2. Evaluate claims against strongest counterinterpretations.
3. Record skeptical findings with severity and route.
4. Emit `skeptical_review_report.md` in `analysis/proposals/stage7_8/stage7/`.
5. For discovery reuse, emit `discovery_skeptical_review_report.md` in `analysis/discovery/proposals/d5/`.

## Gate Rule
- Promotion of Stage 7 requires skeptical review status `pass`.
- `discovery.go` requires skeptical review status `pass` for D5 reuse.

## On Audit Failure
1. Emit blocking skeptical findings with explicit claim locators.
2. Do not emit pass marker.
3. Route unresolved disputes via `A51Ref`.
4. Re-run skeptical review after producer-side revision.

## Reference
- [references/skeptical-review.md](references/skeptical-review.md)
