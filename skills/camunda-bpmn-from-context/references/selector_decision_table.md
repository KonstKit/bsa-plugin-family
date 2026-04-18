# Selector Decision Table

This table documents the deterministic selector behavior implemented by [scripts/backend_selector.py](../scripts/backend_selector.py).

## Precedence

Rules are applied in this strict order:

1. `logic_only=true` -> skip layout/preview (`eligibility_class=logic_only`)
2. `full_relayout=true` + `preserve_existing_di=true` -> emit override reason, continue evaluation
3. `preserve_existing_di=true` + `full_relayout=false` -> force native preserve (`eligibility_class=native_preserve`)
4. inferred `di_quality=usable_di` + `full_relayout=false` -> effective preserve path, force native preserve
5. Any hard exclusion -> force native (`eligibility_class=simple_ineligible`)
6. Otherwise -> simple-eligible (`eligibility_class=simple_eligible`)

## Truth Table

| requested_mode | logic_only | preserve_existing_di | full_relayout | hard_exclusion_present | eligibility_class | forced_native | forced_skip_layout | primary_reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| auto | true | false | false | false | logic_only | false | true | logic_only_requested |
| simple | true | true | false | true | logic_only | false | true | logic_only_requested |
| auto | false | effective=true (inferred by usable DI) | false | false | native_preserve | true | false | preserve_existing_di_forces_native |
| native | false | true | false | false | native_preserve | true | false | preserve_existing_di_forces_native |
| auto | false | true | true | false | simple_eligible | false | false | full_relayout_overrides_preserve_existing_di |
| simple | false | false | false | true | simple_ineligible | true | false | first matched hard exclusion |
| auto | false | false | false | false | simple_eligible | false | false | requested_mode_auto |
| simple | false | false | false | false | simple_eligible | false | false | requested_mode_simple |
| native | false | false | false | false | simple_eligible | true | false | requested_mode_native |

## Hard Exclusions

Simple mode is blocked when any of these conditions is true:

- multi-participant collaboration
- `messageFlow`
- `textAnnotation`
- `association`
- `complexGateway`
- `group`
- `boundaryEvent`
- `eventSubProcess`
- expanded subprocess

See [selector-reason-codes.md](selector-reason-codes.md) for exact reason-code vocabulary.
