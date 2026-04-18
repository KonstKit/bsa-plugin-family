# Selector and Routing Reason Codes

Canonical reason-code dictionary for selector eligibility and runtime fallback metadata.

## Selector Reason Codes

| Code | Layer | Meaning |
| --- | --- | --- |
| `logic_only_requested` | selector | `logic_only=true`; layout and preview are skipped intentionally. |
| `full_relayout_overrides_preserve_existing_di` | selector | Both flags were set; preserve-existing hint is ignored for backend routing. |
| `preserve_existing_di_forces_native` | selector | Preserve-existing mode forces native backend unless full-relayout override is active. |
| `requested_mode_auto` | selector | No hard exclusions; automatic mode left simple-eligible. |
| `requested_mode_simple` | selector | No hard exclusions; explicit simple request remains simple-eligible. |
| `requested_mode_native` | selector | No hard exclusions; native request is preserved as forced-native routing. |
| `multi_participant_collaboration` | selector | Collaboration has multiple participants; simple mode is excluded. |
| `message_flow_present` | selector | `messageFlow` detected; simple mode is excluded. |
| `text_annotation_present` | selector | `textAnnotation` detected; simple mode is excluded. |
| `association_present` | selector | `association` detected; simple mode is excluded. |
| `complex_gateway_present` | selector | `complexGateway` detected; simple mode is excluded. |
| `group_present` | selector | `group` detected; simple mode is excluded. |
| `boundary_event_present` | selector | `boundaryEvent` detected; simple mode is excluded. |
| `event_subprocess_present` | selector | `eventSubProcess` detected; simple mode is excluded. |
| `expanded_subprocess_present` | selector | Expanded subprocess detected; simple mode is excluded. |

## Runtime / Fallback Reason Codes

| Code | Layer | Meaning |
| --- | --- | --- |
| `simple_helper_unavailable_forced_native` | orchestrator | Requested `auto/simple` but helper command was unavailable; route switched to native. |
| `simple_helper_failed` | orchestrator | Helper launch/runtime failed before simple validation completed. |
| `simple_postprocess_failed` | orchestrator | Native layout post-processing over helper output failed. |
| `simple_hard_check_failed` | orchestrator | Simple path failed semantic hard checks. |
| `native_fallback_failed` | orchestrator | Native fallback also failed after a simple-path failure. |

## Failure Detail Codes

| Code | Source |
| --- | --- |
| `projection_generation_failed` | simple bridge |
| `helper_launch_failed` | simple bridge |
| `helper_runtime_failed` | simple bridge |
| `helper_invalid_output` | simple bridge |
| `projection_rehydration_failed` | simple bridge |
| `namespace_loss_detected` | simple bridge invariants |
| `extension_loss_detected` | simple bridge invariants |
| `id_mismatch_detected` | simple bridge invariants |
| `postprocess_layout_failed` | orchestrator post-process step |
| `simple_validation_failed` | orchestrator simple validation step |
| `native_layout_failed` | native layout execution |
| `native_hard_check_failed` | native semantic validation |
