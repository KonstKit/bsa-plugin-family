# Runtime Marker Schema

## Marker Zones
- Main: `analysis/runtime/ready/*.json`
- Discovery: `analysis/discovery/runtime/ready/*.json`
- Bridge: `analysis/runtime/ready/bsa.stage1.entry.enabled.json`

## Main Control + Audit Markers
- `stage1.ready.json`
- `stage1.excerpts.merged.json`
- `stage2.ready.json`
- `stage2.context_state.pass.json`
- `stage3.ready.json`
- `stage3.citation_audit.pass.json`
- `stage4.ready.json`
- `stage5.ready.json`
- `stage5.anchor_audit.pass.json`
- `stage6.ready.json`
- `stage6.anchor_audit.pass.json`
- `stage7.ready.json`
- `stage7.skeptical_review.pass.json`
- `stage8.ready.json`
- `stage8.no_new_claims.pass.json`
- `handoff.ready.json`
- `pipeline.complete.json`

## Discovery Markers
- `discovery.d1.ready.json`
- `discovery.d2.ready.json`
- `discovery.d2.claims.merged.json`
- `discovery.d2.research_quality.pass.json`
- `discovery.d3.ready.json`
- `discovery.d3.prioritization.pass.json`
- `discovery.d4.ready.json`
- `discovery.d4.constraint_audit.pass.json`
- `discovery.d5.ready.json`
- `discovery.d5.citation_audit.pass.json`
- `discovery.d5.no_solution_leakage.pass.json`
- optional (strict profile):
  - `discovery.d5.skeptical_review.pass.json`
  - `discovery.d5.no_new_claims.pass.json` (legacy: `discovery.d5.no_new_facts.pass.json` accepted read-only in pre-v1.0 workspaces)
- `discovery.exit.pass.json`
- `discovery.go.json`
- `discovery.pivot.json`
- `discovery.more_research.json`
- `discovery.no_go.json`

## Phase 3 Markers (Sprint 6+; opt-in via `/bsa-dev-handoff`)
- `phase3.nfr.pass.json` (emitted after bsa-nfr-collector promotes A62; Sprint 6)
- `phase3.story.pass.json` (emitted after bsa-story-writer promotes A70; Sprint 7)
- `phase3.test_scenario.pass.json` (emitted after bsa-test-scenario-builder promotes A71; Sprint 8 US-S8-01)
- `phase3.traceability.pass.json` (emitted after bsa-traceability-matrix promotes A72; Sprint 8 US-S8-02)
- `phase3.backlog_exported.json` (emitted after bsa-backlog-bridge writes the requested platform exports under analysis/handoff/; Sprint 9 US-S9-01..03)
- `pipeline.phase3.complete.json` (emitted at the end of a full /bsa-dev-handoff chain — NOT under --only=backlog-bridge; Sprint 9)

Phase 3 marker alphabet is now closed at v1.1.0.

## Bridge Rule
`stage1` may start from discovery only when both markers exist:
- `discovery.go.json`
- `bsa.stage1.entry.enabled.json`

## Marker Payload Fields (Sprint 3 US-S3-04)

Every marker JSON file MUST be an object with at minimum these fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `marker_id` | string | yes | Filename stem (e.g., `stage3.citation_audit.pass`). |
| `stage` | string | yes | Stage identifier (`stage1`..`stage8`, `d1`..`d5`, `handoff`, `pipeline`). |
| `verdict` | string | yes | `PASS`, `FAIL`, `READY`, `MERGED` (for `stage1.excerpts.merged` and `discovery.d2.claims.merged` composite-promotion markers), or for decision markers `GO`/`PIVOT`/`MORE_RESEARCH`/`NO_GO`. |
| `timestamp` | string (ISO-8601 UTC) | yes | Emission time. |
| `canon_policy_version` | string | yes | Accepts both bare semver (`0.95`) and Sprint-3 semver+hash form (`1.0.0+hash:abc123`). |
| `canon_policy_version_hash` | string | Sprint-3+ | 6-64 hex chars. Matches the SHA-256 digest from `scripts/compute_canon_hash.py`. Optional in pre-v1.0 workspaces; mandatory at v1.0.0-rc1 and later. |

Additional fields are marker-specific (e.g., KPI numbers on audit-pass markers). Producers MAY include them; consumers MUST ignore unknown fields rather than reject.

Pre-Sprint-3 markers that lack `canon_policy_version_hash` remain valid. Future marker-chain validators (US-S3-05) treat missing hash as "pre-hash workspace" and skip hash consistency checks; they do not raise a finding for the missing field.
