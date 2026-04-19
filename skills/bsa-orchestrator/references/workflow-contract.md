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

With discovery:
1. `d1 -> d2 -> d3 -> d4 -> d5`
2. discovery decision (`go/pivot/more_research/no_go`)
3. if `go`: `bsa.stage1.entry.enabled` then main cycle starts at composite `stage1`
4. discovery `d5` also provides `stage2_seed_bundle.md` consumed by `bsa-context-framer` when applicable

## Promotion Sequence (Two-Key)
1. Validate stage-owned proposal directory.
2. Validate evidence-binding and shared-control-surface references.
3. Validate required audit marker(s).
4. Acquire merge lock.
5. Promote artifacts.
6. Promote control surfaces:
   - `A50/A51/A58/A59/A60` after main-cycle `stage1`
   - Stage 2 context/state outputs after `stage2`
   - discovery `A58/A59/A60` after `d2`
   - `A61` after `stage6`
7. Emit next ready/control markers and append event log.
8. Invalidate downstream markers on re-entry.

## Blocking Rule
- Canonical promotion stops when new facts, hidden assumptions, or hard-blocking `A51` items remain unresolved.
- Stage 3 cannot start until Stage 2 is promoted and `stage2.context_state.pass` is valid.
- Stage 4-6 workers may remodel, normalize, and stabilize upstream canonical claims, but may not add net-new facts outside explicit `A51Ref`-guarded hypotheses.
- Sidecars cannot bypass the promotion sequence.
