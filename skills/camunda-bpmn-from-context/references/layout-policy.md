# BPMN Layout Policy (Hard Rule)

This policy is mandatory for all BPMN diagrams delivered for Camunda. A diagram is rejected if any single hard check fails.

## 1. Geometry Contract

- Grid snap: 10 px for shape, label, lane, and participant bounds.
- Edge routing remains orthogonal, but edge endpoints must use exact visual side anchors derived from actual shape bounds.
- Exact gateway/event anchors are allowed to fall off the 10 px grid when required by figure geometry (for example 50x50 gateways and 36x36 events).
- Internal routing channels prefer the 10 px grid, but first/last orthogonal stubs may inherit exact anchor X/Y coordinates.
- Default sizes:
  - service task: minimum 180x80
  - exclusive gateway: 50x50
  - start/end event: 36x36
  - expanded subprocess: minimum 220x100, then expanded from the internal layout envelope
- Horizontal spacing: at least 60 px between neighboring figure bounding boxes in the same visual row.
- Vertical lane spacing: at least 120 px between lane envelopes.
- Routing clearance around every bbox (shape and label): 20 px.
- Labels are first-class geometry objects and participate in collision checks.
- Minimum internal edge segment length: 20 px.
- Maximum preferred bends per edge: 3. More is allowed only if there is no collision-free alternative within the local routing budget.

## 2. Placement Rule

- Preserve existing BPMN DI coordinates if they are valid or can be repaired locally.
- Do not rebuild the entire canvas if a local fix is sufficient.
- Full relayout is allowed only when:
  - the diagram has no BPMN DI geometry, or
  - a hard-rule violation cannot be fixed within local movement budgets.
- Placement runs as a phased pipeline:
  1. graph analysis
  2. constraint placement
  3. label placement
  4. edge routing
  5. compaction and final reroute
- Column placement:
  - use longest-path process depth for columns
  - column X is computed from cumulative maximum width of previous columns plus `gapX`
  - sibling ordering inside a column must be deterministic
- Lane placement priority:
  1. explicit external lane map
  2. BPMN `laneSet` / `lane` membership
  3. preserved existing Y-band layout from BPMN DI
  4. deterministic heuristic fallback
- Compute coordinates, do not place manually:
  - `column_left[d] = marginX + sum(max_width[col] + gapX for col < d)`
  - `x = column_left[depth] + alignWithinColumn(nodeWidth)`
  - `lane_top[l] = marginY + sum(laneEnvelopeHeight[k] + gapY for k < l)`
  - `y = lane_top[lane] + localSlot * subrowGap`
- Keep all figures inside canvas with external margin >= 40 px.

## 3. Stability Rule

- Existing shapes must not move more than 120 px from their baseline BPMN DI position during automatic repair.
- Existing external labels must not move more than 80 px from baseline during automatic repair.
- If a valid result requires larger movement, automatic repair must fail and report `requires_full_relayout`.
- Edge routing must prefer the baseline path when it already satisfies all hard checks.
- Local search is bounded. If the bounded candidate set is exhausted, the script must report failure instead of silently inventing a global reroute.
- Among valid alternatives, choose the route with:
  1. zero hard violations
  2. minimum displacement from baseline
  3. fewer bends
  4. shorter Manhattan length

### Profile Rationale

- Canonical alias names are accepted by the loader and map to the native profile names below:
  - `greenfield_canonical` -> `native_greenfield`
  - `preserve_existing` -> `native_preserve_existing`
  - `repair_escalated` -> `native_repair_escalated`
- `native_preserve_existing`:
  - first pass when valid BPMN DI already exists
  - preserves the current house style while preferring local repair over rebuild
- `native_repair_escalated`:
  - second pass when preserve-existing still violates hard rules
  - keeps the same native style vocabulary, but makes the repair phase explicit in policy so thresholds can diverge later without changing code
- `native_greenfield`:
  - canonical fallback when local repair is insufficient or no usable DI exists
  - builds a fresh layout using the same native style defaults unless policy overrides them
- `simple_postprocess_refine`:
  - first pass for `--simple-postprocess` runs after helper output projection
  - keeps simple backend semantics and never reports itself as `native_*`
- `simple_postprocess_repair`:
  - second-pass simple repair mode when refine still violates hard checks
- `simple_postprocess_greenfield`:
  - simple-family fallback pass; allowed for simple success when hard checks pass

## 4. Edge Rule

- Edge endpoints must use side anchors only: midpoint of left, right, top, or bottom side computed from the true figure geometry.
- For gateway and event figures, endpoint coordinates must use the exact visual side anchor, not a grid-snapped surrogate.
- Grid snapping is forbidden for endpoint-anchor calculation.
- Orthogonality is validated against the actual endpoint coordinates; off-grid endpoint coordinates are valid when they coincide with the true visual anchor.
- Routing style: orthogonal (Manhattan) only.
- No edge is allowed to cross:
  - any shape bbox except the source/target attachment side
  - any label bbox
- Edge-edge intersections are forbidden except a single shared endpoint that is also an endpoint of both intersecting segments.
- Collinear overlap of different edges is forbidden.
- Shared source/target stubs are allowed only before divergence or after convergence:
  - common prefix segments for edges with the same source are not treated as crossings
  - common suffix segments for edges with the same target are not treated as crossings
- Micro-jogs are forbidden:
  - no internal segment shorter than 20 px
  - no 2 px or 10 px corrective kink near the endpoint when a direct anchored route exists
- Backtracking is forbidden when a monotonic left-to-right route exists within the same local routing budget.
- Gateway routing preference:
  - for same-lane through-flow, prefer left/right gateway anchors over top/bottom;
  - for vertical branch fanout or vertical convergence, prefer top/bottom anchors;
  - top/bottom on a same-lane through-flow may be used only if left/right creates a hard collision or route-quality failure within the local routing budget.

## 5. Label Rule

- Task labels are centered inside task bounds.
- Gateway labels default above the gateway and may move below only if the default placement collides.
- Event labels default below the event and may move above only if the default placement collides.
- External labels must use wrapped multi-line bounds when needed; the label bbox is validated like any other geometry object.
- If task text does not fit:
  - first expand task width in 20 px steps
  - then increase task height in 20 px steps
  - never allow visible text overflow

## 6. Validation Rule

A valid diagram must satisfy all checks:

- shape-shape overlap count = 0
- label-shape overlap count = 0
- label-label overlap count = 0
- edge-bbox collisions = 0
- invalid edge-edge intersections = 0
- endpoint-anchor mismatch against exact visual anchors = 0
- route-quality violations = 0
- shape movement budget violations = 0
- label movement budget violations = 0
- participant/lane movement budget violations = 0
- diagram readability violations = 0 (`diagram_width`, `diagram_height`, `aspect_ratio`, `depth_columns`, `edge_span_columns`, `gateway_chain`)
- XML validation passes (`xmllint --noout`)

`endpoint-anchor mismatch` is evaluated against true shape-derived anchor coordinates, not against grid-snapped proxy points.

`simple-postprocess` exception:
- shape/label/participant-lane budget violations are still measured and reported, but they are advisory and do not flip final status to `FAIL`.
- all geometry and routing hard checks remain mandatory in `simple-postprocess`.
- `simple-postprocess` reports must use `simple_*` fields (`simple_refine_error`, `simple_repair_error`, `simple_postprocess_final_mode`) instead of native preserve-chain field names.

Readability gating:
- layout computes machine-readable readability metrics: `diagram_width_px`, `diagram_height_px`, `aspect_ratio_x100`, `max_depth_columns`, `max_edge_span_columns`, `consecutive_gateway_chain_length`.
- if any readability budget is exceeded, `layout_requires_decomposition=true` and final status is `FAIL`.
- these metrics are propagated to `layout_report.summary.json`, `run_manifest.layout_summary`, and preview metadata.

## 7. Layout Pipeline (Mandatory)

For every layout run execute the following phases:

1. Read existing BPMN DI geometry, if present, as baseline.
2. Resolve lane membership using the lane priority order.
3. Constraint placement:
   - compute canonical column/lane positions
   - prefer existing DI when valid
   - resolve all shape overlaps with push-apart separation before proceeding
   - for expanded subprocesses, compute internal layout recursively first and size the subprocess to contain that internal envelope
4. Label placement:
   - place all external gateway/event labels
   - expand label search budget when necessary
5. Edge routing:
   - route sequence flows in priority order
   - treat already-routed edges as routing context
   - run crossing minimization and source fan-out for sibling flows
   - execute policy-driven conflict sequence explicitly:
     - local branch-label move
     - edge waypoint adjustment
     - local node-space reclaim
     - fallback escalation if hard conflicts remain
6. Compaction:
   - remove excessive column and lane whitespace
   - reroute after compaction using the compacted geometry as baseline
7. Final verification:
   - if preserve-existing mode still violates hard rules, retry with full canonical relayout
   - if hard-rule violations remain after canonical relayout, fail the run with `LayoutError`
8. Expanded subprocess handling:
   - run the same pipeline recursively for embedded flow nodes inside each expanded subprocess
   - write BPMNDI shapes and edges for embedded nodes on the same plane with coordinates offset by the subprocess bounds

## 8. Policy Config Keys

The runtime policy is loaded from `config/layout_thresholds.yaml` relative to the script location unless `--layout-config` is provided.

### `policy`

- `default_profile`: explicit first-pass mode. Default house style uses `native_preserve_existing`.
- `escalated_profile`: explicit second-pass repair mode. Default house style uses `native_repair_escalated`.
- `fallback_profile`: explicit full-relayout mode. Default house style uses `native_greenfield`.
- `simple_default_profile`: explicit first-pass mode for `--simple-postprocess`. Default is `simple_postprocess_refine`.
- `simple_escalated_profile`: explicit second-pass repair mode for `--simple-postprocess`. Default is `simple_postprocess_repair`.
- `simple_fallback_profile`: explicit fallback mode for `--simple-postprocess`. Default is `simple_postprocess_greenfield`.
- The loader accepts either the native profile names above or their canonical aliases and normalizes them internally to the native names.

### `profiles.<profile>.main`

- `margin_x`: left/right outer canvas margin for top-level placement
- `margin_y`: top/bottom outer canvas margin for top-level placement
- `gap_x`: preferred inter-column gap for top-level placement and verification
- `gap_y`: preferred inter-lane gap for top-level placement and verification
- `subrow_gap`: vertical spacing between siblings in the same lane/column bucket
- `max_shape_shift`: allowed movement budget for existing shapes in preserve/repair modes
- `max_label_shift`: allowed movement budget for existing labels in preserve/repair modes
- `participant_band_margin`: outer band margin applied when framing participant/process envelopes around generated node and label geometry
- `lane_band_margin`: extra top/bottom clearance applied from lane members to the lane band
- `lane_inset_x`: left/right inset between the participant/process frame and each lane band
- `lane_inset_y`: top/bottom inset between the participant/process frame and the contiguous lane stack
- `lane_min_height`: preferred minimum lane height before proportional compression
- `lane_min_height_floor`: last-resort minimum lane height when the available band is smaller than the preferred total lane stack
- `container_padding_x`: right-side padding used when sizing expanded subprocess outer envelopes from canonical inner geometry
- `container_padding_y`: bottom padding used when sizing expanded subprocess outer envelopes from canonical inner geometry
- `compaction_margin`: minimum post-compaction canvas framing margin for top-level node geometry
- `participant_label_offset_x`: X offset for participant labels inside the participant band
- `participant_label_offset_y`: Y offset for participant labels inside the participant band
- `lane_label_offset_x`: X offset for lane labels inside the lane band
- `lane_label_offset_y`: Y offset for lane labels inside the lane band
- `max_participant_lane_shift`: allowed preserve/repair drift budget for regenerated participant and lane bounds
- `label_zone_gap`: default gap from a node to its primary external label zone
- `label_zone_alternate_gap`: default gap from a node to its alternate external label zone
- `label_conflict_padding`: collision padding used when evaluating label conflicts against shapes, labels, and rerouted edge corridors
- `label_conflict_budget_step`: budget increment used during local branch-label move retries
- `label_conflict_max_budget`: max label-search budget used before conflict resolution escalates
- `label_conflict_shift_step`: step size for candidate label-zone shifts during local branch-label move
- `label_conflict_shift_levels`: number of shift levels generated on either side of the primary/alternate zone
- `edge_label_overlap_step`: vertical step used when de-overlapping generated branch/edge labels
- `edge_label_overlap_levels`: number of branch-label overlap retry levels
- `edge_corridor_thickness`: synthetic corridor thickness used when treating routed edges as geometry during conflict checks
- `edge_reroute_collision_padding`: collision padding used while scoring reroute candidates against shapes and labels
- `edge_reroute_channel_minor_offset`: near-channel offset used when generating local reroute candidates
- `edge_reroute_channel_major_offset`: outer-channel offset used when generating reroute candidates and outer channels
- `edge_reroute_outer_offset`: initial distance from the occupied bbox envelope to the first outer reroute channel
- `edge_reroute_channel_margin`: pruning margin around the source/target pair used when selecting reroute channels
- `edge_reroute_outer_count`: number of outer reroute channels retained on each side during pruning
- `edge_reroute_channel_limit`: maximum number of reroute channels retained after pruning
- `edge_reroute_max_passes`: maximum crossing-minimization passes during edge waypoint adjustment
- `edge_branch_fanout_step`: stub fanout step used when separating sibling edges near a shared source or target
- `edge_branch_fanout_top_multiplier`: multiplier applied to top-anchored fanout offsets
- `conflict_local_reclaim_clearance`: clearance target used during local node-space reclaim
- `conflict_local_reclaim_max_passes`: maximum local node-space reclaim passes before escalation
- `conflict_report_issue_limit`: max number of typed issue detail lines emitted into the report
- `column_gap_violation_tolerance`: allowed post-compaction slack before a column gap is reported as a violation
- `lane_gap_violation_tolerance`: allowed post-compaction slack before a lane gap is reported as a violation
- `boundary_event_fanout_offset`: offset step used when distributing regenerated boundary events along the host side
- `edge_route_same_lane_knee_offset`: knee offset used for same-lane horizontal routing candidates
- `edge_route_vertical_mid_offset`: vertical midpoint offset used when routing across different lanes
- `edge_route_horizontal_mid_offset`: horizontal midpoint offset used when routing fallback horizontal channels
- `edge_route_backtrack_tolerance`: route-quality backtrack tolerance used when scoring orthogonal edge paths
- all threshold values must resolve to integers; boolean values and fractional numerics are invalid policy input

### `profiles.<profile>.nested`

- same keys as `main`
- applies to recursively laid out expanded subprocess contents, including the outer expanded-subprocess frame sizing keys (`container_padding_x`, `container_padding_y`, `compaction_margin`)
- defaults intentionally preserve the prior nested layout behavior (`gap_x=60`, `gap_y=90`, `subrow_gap=80`, `margin_x=30`, `margin_y=50`)

The spacing and movement keys are required. Framing keys above are also policy-backed and should be published in `layout_thresholds.yaml`; older configs are backfilled with the documented defaults so preserve-mode upgrades stay stable.
Final verification is executed against the serialized geometry set after nested subprocess expansion, not only the top-level process geometry.

## 9. Delivery Rule

Every run must produce a report with:

- phase summary
- issue counts by category
- moved objects and reason
- maximum and total movement from baseline
- drift channels:
  - untouched shapes
  - touched/repaired shapes
  - participant/lane bounds
  - labels
- each drift channel must report deterministic preserve accounting:
  - `budget`: per-item allowed drift for that channel
  - `violations`: count of items that exceeded the channel budget
  - `total_over_budget`: summed overflow beyond the channel budget
  - `max_over_budget`: worst single overflow beyond the channel budget
- drift channels are emitted in stable order:
  - `untouched_shapes`
  - `touched_repaired_shapes`
  - `participant_lane_bounds`
  - `labels`
- preserve semantics:
  - `untouched_shapes` uses a zero budget and must remain exactly anchored to baseline DI
  - `touched_repaired_shapes` uses the shape repair budget and records only nodes that actually moved
  - `participant_lane_bounds` uses the participant/lane regeneration budget because pool/lane boxes are rebuilt from final geometry
  - `labels` uses the label movement budget
- whether baseline geometry was preserved or a full relayout was required
- participant/lane budget overruns are hard failures in the same PASS / FAIL gate as shape and label movement overruns
- typed issue contract:
  - every run exposes machine-consumable typed issue items with fields `target_type`, `element_id`, `secondary_element_id`, `bbox`, `severity`, `code`
  - supported target classes are `shape`, `edge`, `label`, `pair`, and `global`
  - report output includes typed issue summary counts and bounded detail lines
  - issue-count summaries are sorted deterministically by issue code
- final status: PASS / FAIL

## 10. Optional Layout Hint Ingestion (Deferred Optimization Path)

- Layout hints are opt-in and gated by an explicit CLI flag:
  - `--enable-layout-hints`
- Hint payload is optional and accepted via:
  - `--layout-hints-json <inline-json-or-file-path>`
- Default behavior remains no-hint:
  - if no hint flag and no hint payload are provided, no hint override is applied
  - if a payload is provided without the flag, hints are ignored
- Hint payload contract (advisory-only):
  - top-level object with optional `profiles` mapping
  - profile keys may use native names (`native_preserve_existing`, `native_repair_escalated`, `native_greenfield`) or canonical aliases
  - each profile may define `main` and/or `nested` objects with integer threshold overrides
  - unknown keys are ignored
- Hard validation invariants are unchanged:
  - hints can only adjust threshold inputs
  - hints never bypass hard checks or PASS/FAIL gate criteria
- Report contract includes hint status fields for downstream orchestration:
  - `layout_hint_source`
  - `hint_applied`

### Optional A/B Regression Usage

- Baseline run (no hints):
  - run `scripts/apply_bpmn_layout_policy.py` without hint flags and keep the generated report.
- Hint run (A/B variant):
  - rerun with `--enable-layout-hints --layout-hints-json ...` on the same fixture set.
- Compare:
  - final status (must remain `PASS`)
  - hard metrics (`shape_shape`, `label_shape`, `label_label`, `edge_bbox_collisions_detected`, route-quality and budget violation counters)
  - drift and typed issue summaries
- Rollback trigger:
  - if hard-check regressions appear in the hint run, disable the hint flag and keep the no-hint baseline path.
