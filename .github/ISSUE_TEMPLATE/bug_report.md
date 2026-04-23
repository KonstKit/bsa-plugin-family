---
name: Bug report
about: Report a defect in the BSA plugin family
title: "[BUG] "
labels: bug
assignees: ''
---

## Plugin version

- `bsa-full` manifest version (from `/plugin list`):
- Canon policy version + hash prefix (from `.claude-plugin/plugin.json` `canonPolicyVersion.semver` + `hash_prefix`):
- Git tag (if known):
- Claude Code version:

## Workspace state

- Operating system:
- Python version (for validators):
- `bsa doctor` exit code (run from your workspace):
- Pipeline mode (`direct` / `discovery_then_bsa` / unsure):
- Last successful stage:

## Reproduction steps

1.
2.
3.

## Expected behavior

<!-- What did you expect to happen? Cite the relevant SKILL.md, schema,
or invariant if applicable. -->

## Actual behavior

<!-- What actually happened? Include the slash command you ran, its
stdout/stderr, and any audit reports. -->

## Affected artifacts

<!-- Which canonical CSVs / markers / handoff packets are involved?
Cite the A-N IDs (A50, A59, A51, etc.) and any specific row IDs. -->

- [ ] A48 (run context)
- [ ] A50 (sources)
- [ ] A51 (issue routes)
- [ ] A58 (excerpts)
- [ ] A59 (claims)
- [ ] A60 (negative evidence)
- [ ] A61 (anchors)
- [ ] A62 (NFRs — Phase 3)
- [ ] A70 (stories — Phase 3)
- [ ] A71 (test scenarios — Phase 3)
- [ ] A72 (traceability matrix — Phase 3)
- [ ] Marker chain
- [ ] H1-H4 handoff pack
- [ ] Backlog export (Jira / Linear / GitHub Projects v2 / generic)

## Privacy + anonymization

- [ ] I have NOT included real client names, PII, credentials, or internal URLs in this report.
- [ ] If sharing fixture / workspace data, it is sanitized (see `fixtures/golden/project_0001/README.md` for a sanitization template).
