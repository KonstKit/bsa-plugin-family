---
name: Feature request
about: Propose a new feature or extension for the BSA plugin family
title: "[FEAT] "
labels: enhancement
assignees: ''
---

## Problem

<!-- What's the analytical / operator pain point this feature addresses? -->

## Proposed solution

<!-- What would the feature do? Cite the relevant SKILL.md, schema, or
invariant if the proposal touches existing contracts. -->

## Scope classification

- [ ] **Additive enum extension** — adds a new value to a closed enum (e.g., new A51 IssueType, new A50 ReliabilityTier, new ClaimType). Backward-compatible; patch-line bump.
- [ ] **New SKILL.md** — adds a new worker / auditor / sidecar. Minor bump.
- [ ] **New invariant** — adds an INV-NN governance rule. Major CanonPolicyVersion bump required (per immutable-invariants contract).
- [ ] **New canonical artifact** — adds A`NN` schema (analogous to A62/A70/A71/A72 in Phase 3). Minor bump.
- [ ] **New platform export** — adds `backlog_export_<platform>.{json,csv}` (analogous to v1.1.4 GitHub Projects v2). Minor bump.
- [ ] **Operator-facing tool** — adds a script under `scripts/` (analogous to v1.1.6 `backlog_live_apply.py`). Patch bump (script not in POLICY_GLOBS).
- [ ] **Documentation** — patch-line bump.
- [ ] **Other** (specify):

## Acceptance criteria

<!-- What does "done" look like? Use the format we use in fixture
audit_expectations.json: testable invariants, not vague "it should
work" statements. -->

- [ ] Schema / contract changes documented in `governance/schemas/` and `skills/bsa-orchestrator/references/shared-control-surface-contracts.md` (when in POLICY_GLOBS).
- [ ] Test coverage: positive case + at least one negative regression.
- [ ] CHANGELOG entry under the next patch-line version.
- [ ] If touching POLICY_GLOBS: canon hash recomputed in `.claude-plugin/plugin.json`.
- [ ] Codex review APPROVE.

## Carry-forward / dependencies

<!-- Does this depend on a TODO marker (e.g., [TODO-S9-LIVE-API],
[TODO-S8-02-INCREMENTAL-MATRIX])? Reference it explicitly. -->
