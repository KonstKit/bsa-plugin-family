# Workflow Contract

## Runtime Layout

```text
analysis/
  runtime/
    ready/
    locks/
    reentry/
    events/
  canonical/
    core_controls/ (A48/A50/A51/A58/A59/A60/A61)
    stage1/
    stage2/
    stage3/
    stage4/
    stage5/
    stage6/
    stage7/
    stage8/
  proposals/
    stage1/      # intake + claim-layer proposals
    stage2/
    stage3/
    stage4/
    stage5/
    stage6/
    stage7_8/
      stage7/
      stage8/
      handoff/
  views/
    evidence/
    bpmn/
    c4/
    adjudication/
    checkpoints/
  handoff/
  discovery/
    runtime/
      ready/
      locks/
      reentry/
      events/
    canonical/
      core_controls/   # discovery-local A58/A59/A60 + refs to shared A48/A50/A51
      d1/
      d2/
      d3/
      d4/
      d5/
    proposals/
      d1/
      d2/
      d3/
      d4/
      d5/
    handoff/
```

## Execution Paths
Without discovery:
1. `stage1` (`bsa-evidence-intake` -> `bsa-claim-binder`)
2. `stage2` (context/state framing by `bsa-context-framer`)
3. `stage3`
4. `stage4`
5. `stage5`
6. `stage6`
7. `stage7`
8. `stage8`
9. `handoff`
10. (optional, Phase 3) `phase3.nfr -> phase3.story -> phase3.test_scenario -> phase3.traceability -> phase3.backlog_exported` via `/bsa-dev-handoff`

With discovery:
1. `d1 -> d2 -> d3 -> d4 -> d5`
2. discovery decision (`go/pivot/more_research/no_go`)
3. if `go`: `bsa.stage1.entry.enabled` then main cycle starts at composite `stage1`
4. discovery `d5` also provides `stage2_seed_bundle.md` consumed by `bsa-context-framer` when applicable
5. After `handoff`: same optional Phase-3 tail as above.

## Phase 3 Dev-Handoff Extension (Sprint 6+)

Phase 3 is an **opt-in** extension that runs AFTER `handoff.ready.json` has been emitted. It does not replace or modify the main-cycle handoff; it consumes it as input. Invocation: `/bsa-dev-handoff` (see `commands/bsa-dev-handoff.md`).

Phase-3 stages and their owning skills:

| Phase-3 stage | Skill | Required markers emitted | Artifact promoted |
|---|---|---|---|
| `phase3.nfr` | `bsa-nfr-collector` | `phase3.nfr.pass.json` | `A62_nfr_register.csv` |
| `phase3.story` | `bsa-story-writer` | `phase3.story.pass.json` | `A70_story_register.csv` |
| `phase3.test_scenario` | `bsa-test-scenario-builder` | `phase3.test_scenario.pass.json` | `A71_test_scenario_register.csv` |
| `phase3.traceability` | `bsa-traceability-matrix` | `phase3.traceability.pass.json` | `A72_traceability_matrix.csv` |
| `phase3.backlog_exported` | `bsa-backlog-bridge` | `phase3.backlog_exported.json` | `analysis/handoff/backlog_export_*` (terminal, no promotion) |

After all five pass, orchestrator emits `pipeline.phase3.complete.json`.

Phase-3 invariants (INV-08 / INV-09 / INV-10) will land in `governance/immutable_invariants.md` at v1.1.0 (Sprint 9 close); enforced by the F5 write-validator and per-skill auditors from their respective sprints.

Phase-3 artifacts (A62 / A70 / A71 / A72) gain write-time schema enforcement automatically as their schemas land in `governance/schemas/` and are added to `write_validator.py`'s `_DISPATCHER` table — same mechanism as Sprint-5 A50/A51/A58/A59/A60 enforcement.

Partial runs (`/bsa-dev-handoff --only=<skill>`) are supported so a single Phase-3 skill can be debugged or retried without re-executing upstream Phase-3 work. Main-cycle prerequisites (`handoff.ready` + promoted A59/A50/A51) are still required for any partial run.

## Promotion Sequence (Two-Key)
1. Validate stage-owned proposal directory.
2. Validate evidence-binding and shared-control-surface references.
3. Run the **discovery → main merge step** when in `discovery_then_bsa` mode and `discovery.go` has fired. Emit `merge_log.jsonl` entries per [discovery_to_main_merge.md](discovery_to_main_merge.md) and [merge_log.schema.json](merge_log.schema.json). Hard-blocking events (`claim_conflict`, `excerpt_text_conflict`) halt promotion here with an `A51` contradiction row.
4. Validate required audit marker(s).
5. Acquire merge lock.
6. Promote artifacts.
7. Promote control surfaces:
   - `A50/A51/A58/A59/A60` after main-cycle `stage1` (carrying forward discovery lineage per the merge step above when applicable)
   - Stage 2 context/state outputs after `stage2`
   - discovery `A58/A59/A60` after `d2`
   - `A61` after `stage6`
8. Emit next ready/control markers and append event log. For runs that executed the merge step, also append merge events to `analysis/canonical/merge_logs/discovery_to_main_merge_log.jsonl`.
9. Invalidate downstream markers on re-entry.

## Blocking Rule
- Canonical promotion stops when new claims, hidden assumptions, or hard-blocking `A51` items remain unresolved.
- Stage 3 cannot start until Stage 2 is promoted and `stage2.context_state.pass` is valid.
- Stage 4-6 workers may remodel, normalize, and stabilize upstream canonical claims, but may not add net-new claims outside explicit `A51Ref`-guarded hypotheses.
- Sidecars cannot bypass the promotion sequence.
