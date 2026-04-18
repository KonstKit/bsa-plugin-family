# Acceptance Fixtures

Primary fixture inventory is defined in [scripts/fixtures/fixture_inventory.json](../scripts/fixtures/fixture_inventory.json).

Original fixtures are runtime-tested in PR/release-candidate acceptance gates (not inventory-only).

## Critical Path Fixtures

| Fixture | Category | DI Quality | Expected Routing Class |
| --- | --- | --- | --- |
| `01_original` | original | `usable_di` | `native_preserve` |
| `01_stripped` | stripped | `no_di` | `simple_eligible` |
| `02_original` | original | `usable_di` | `native_preserve` |
| `02_stripped` | stripped | `no_di` | `simple_eligible` |
| `03_original` | original | `usable_di` | `native_preserve` |
| `03_stripped` | stripped | `partial_di` | `simple_ineligible` |
| `04a_original` | original | `partial_di` | `simple_direct` |
| `04a_stripped` | stripped | `no_di` | `simple_eligible` |
| `04b_original` | original | `partial_di` | `simple_direct` |
| `04b_stripped` | stripped | `no_di` | `simple_eligible` |
| `04c_original` | original | `partial_di` | `simple_direct` |
| `04c_stripped` | stripped | `no_di` | `simple_eligible` |
| `04d_original` | original | `partial_di` | `simple_direct` |
| `04d_stripped` | stripped | `no_di` | `simple_eligible` |

PR/RC gate expectation:

- usable original fixtures execute runtime in `native_preserve`; if preserve escalates to `native_greenfield`, the run must expose `fallback_happened=true` with reason `native_preserve_degraded_to_greenfield`
- partial-DI originals route through simple/direct or fallback paths per selector output
- stripped fixtures must execute runtime in simple/native paths according to fixture metadata
- quality checks use inventory quality fields when present:
  - `expected_layout_final_mode`
  - `expected_layout_profile_family`
  - `max_warning_issue_count`
  - `max_error_issue_count`
  - `advisory_only_allowed`

## Negative Exclusion Fixtures

| Fixture | Exclusion Driver |
| --- | --- |
| `neg_collaboration_message_flow` | `message_flow_present` |
| `neg_text_annotation` | `text_annotation_present` |
| `neg_association` | `association_present` |
| `neg_boundary_event` | `boundary_event_present` |
| `neg_expanded_subprocess` | `expanded_subprocess_present` |
| `neg_event_subprocess` | `event_subprocess_present` |
| `neg_complex_gateway` | `complex_gateway_present` |
| `neg_group` | `group_present` |
| `neg_multi_participant_collaboration` | `multi_participant_collaboration` |

Negative fixture status expectation is metadata-driven: certain fixtures intentionally expect `semantic_status=FAIL` or `layout_status=FAIL` while still enforcing selector exclusion to native path.

## Runtime Extension Fixtures

| Fixture | Purpose |
| --- | --- |
| `c7_simple_extension_stripped` | C7 namespace/extension preservation in bridge contract checks |
| `c8_simple_extension_stripped` | C8 namespace/extension preservation in bridge contract checks |
