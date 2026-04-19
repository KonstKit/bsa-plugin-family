# Discovery -> BSA Handoff Contract

## Entry Gate
Stage 1 is enabled only when:
- `discovery.go.json` exists,
- `bsa.stage1.entry.enabled.json` exists.

## Blocking Decisions
If `discovery.pivot`, `discovery.more_research`, or `discovery.no_go` is active, Stage 1 entry is blocked.

## Seed Rule
Discovery handoff is used as Stage 1 seed input only; it cannot directly promote canonical main-cycle claims.
Every seed statement must carry `ClaimID` or explicit `A51Ref`.
