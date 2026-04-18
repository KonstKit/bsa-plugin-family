# Anchor Audit Contract

## Required Sections
- anchors audited
- anchors with `ClaimID`
- anchors with `A51Ref`
- orphan anchors count
- duplicate anchors count
- class mismatch count
- verdict (`PASS`/`FAIL`)

## Rules
- A positive anchor cannot be justified by `A51Ref` alone when upstream evidence is expected to exist.
- `A51Ref` is allowed only for explicitly unresolved candidate anchors that remain unpromoted.
