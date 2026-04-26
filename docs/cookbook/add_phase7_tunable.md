# Cookbook: Add a New Phase 7 Tunable

Step-by-step recipe for adding a knob to `config/tunables.yaml` so the Phase 7 self-improvement loop (L1b miner + L2 patcher) can observe + propose changes to it.

**Estimated effort:** 30 min - 2 hours (depends on whether the tunable already has a consumer or you're adding the consumer too).

**Prerequisites:** read `docs/phase_7_design.md` and `docs/phase_7_runbook.md`.

## Phase 7 architecture recap

```
config/tunables.yaml       (L0 inventory — vN.1.14 foundation)
       │
       ▼
analysis/telemetry/run_*.json    (L1a — telemetry collector, vN.2.4)
       │
       ▼
analysis/telemetry/miner_proposals.json   (L1b — miner skeleton, vN.2.18; real algo deferred)
       │
       ▼
analysis/telemetry/proposals/<id>.{patch,summary.md}   (L2 — patcher, vN.2.19)
       │
       ▼
git apply + manifest bump  (operator-driven, NEVER auto)
```

Adding a tunable means:
1. Declare it in `config/tunables.yaml` (L0 inventory)
2. Wire a consumer that reads it (existing audit/skill/script)
3. Optionally: instrument telemetry to capture per-run knob value (L1a)

## Decision matrix (lock before writing)

| Decision | Default | Notes |
|---|---|---|
| `change_class` | **`L2_proposal_only`** (almost always) | The other valid value is `L1_auto_tunable` — reserved for knobs whose `linked_invariants` is empty AND whose `source_file` is NOT in POLICY_GLOBS. phase_7_lint's IMMUTABLE_CONFLICT detector blocks any L1_auto_tunable that touches an invariant or canonical text. |
| `linked_invariants` | **`[INV-01]`** for any knob influencing evidence quality, audit thresholds, or scoring weights | If your knob touches anything related to claim/evidence integrity, link to INV-01 (canonical claim layer). The `linked_invariants` list is enforced by phase_7_lint — see lint contract C5 in `config/tunables.yaml` header. |
| Type | **numeric** with explicit `allowed_range: [<min>, <max>]` | v1.1.14 phase_7_lint only supports numeric knobs. String/enum knobs are out of L1 inventory scope; document them in the consumer's CLI help text instead. |
| `current_value` | The literal string as it appears in `source_file` (verbatim substring match) | Lint contract C1: `current_value` must appear as a substring at `source_file:source_line`. This catches drift if the value is edited without updating tunables.yaml. |
| `source_file` + `source_line` | Repo-relative path + 1-indexed line where the knob's actual value lives | Tunables.yaml is INVENTORY/PATCH METADATA, not the runtime source of the value. Consumers read the value from `source_file`; phase_7_lint cross-checks. |

## Non-negotiable: never set `linked_invariants: []` to pass lint

If your knob influences evidence-binding quality or audit verdicts, it MUST link to the relevant invariant (`[INV-01]` for evidence-binding) with `change_class: L2_proposal_only`. Setting `linked_invariants: []` (empty list) AND `change_class: L1_auto_tunable` to bypass the IMMUTABLE_CONFLICT detector (lint contract C5) is a forbidden workaround — it would let Phase 7 auto-tune a quality-affecting knob without analyst sign-off. Locked design decision (v1.2.16 retro):

> "Threshold lives in `config/tunables.yaml` and is part of the Phase 7 L1 inventory surface — but `change_class` MUST be **`L2_proposal_only`** with `linked_invariants: [INV-01]`. Reasoning: threshold influences evidence-binding quality; auto-patching it without analyst sign-off would silently weaken the audit. 'L1 surface' in earlier notes meant 'tracked by Phase 7 L1 inventory', NOT 'auto-tunable'. Setting `linked_invariants: []` to pass lint C5 is a forbidden workaround."

Lint contract C6 also forbids L1_auto_tunable entries whose `source_file` matches any POLICY_GLOBS pattern — auto-merge inside canonical state would silently bump the canon hash without operator review.

## Step-by-step

### 1. Pre-flight (~5 min)

```bash
# Read existing tunables for shape:
cat config/tunables.yaml

# Read the lint rules that constrain your entry:
cat scripts/phase_7_lint.py | head -100

# Confirm your consumer (the script that will read the tunable) exists.
# If not, write the consumer first per the relevant cookbook recipe
# (add_audit.md or add_contract_exporter.md), then come back here.
```

### 2. Add the entry to `config/tunables.yaml` (~5 min)

Mirror an existing entry (e.g., `tier_weight_T1` or `freshness_threshold_days`). The schema is documented in the file's own header — read `config/tunables.yaml` lines 1-50 for the canonical contract. Required fields:

```yaml
- id: <my_tunable_id>                    # snake_case, globally unique
  current_value: "<verbatim>"            # MUST appear as substring at source_file:source_line
  allowed_range: [<min>, <max>]          # numeric only in v1.1.14; lint enforces
  owner_skill: <skill-name>              # OR `governance` OR `sidecar:<name>`
  source_file: <repo-relative-path>      # where current_value actually lives
  source_line: <1-indexed-int>           # phase_7_lint substring-checks at this line
  linked_invariants: [INV-01]            # set non-empty for quality-affecting knobs
  change_class: L2_proposal_only         # OR L1_auto_tunable (rare; see lint C5+C6)
  rationale: <one-line-why-and-when-to-tune>
```

ID conventions (from existing entries in `config/tunables.yaml`):
- Audits: `<name>_threshold_<unit>` (e.g., `freshness_threshold_days`, `triangulation_min_distinct_sourcetypes`)
- KPI targets: `kpi_<NNN>_target`
- Tier weights: `tier_weight_<TIER>` (T1..T5)
- Sidecar limits: `<sidecar>_max_<unit>` (e.g., `bpmn_max_shape_shift`)

**Important: `tunables.yaml` is INVENTORY + PATCH METADATA, not the runtime config source.** The value lives at `source_file:source_line` (e.g., a tier weight literal in `reliability_tier_spec.md`); your consumer reads from THERE, not from this yaml. Phase 7's L1b miner / L2 patcher uses tunables.yaml to find what's tunable; the consumer never imports yaml at runtime just to read its own constant.

### 3. Wire the consumer (~30 min - 2 hours)

The consumer is the script that reads this tunable's value. The value lives at `source_file:source_line` — your consumer reads from THERE, not from `config/tunables.yaml`.

**Pattern A: literal in a markdown spec (e.g., tier weight).**

Consumer reads the spec markdown, parses the literal:
```python
SPEC_PATH = Path(__file__).resolve().parent.parent / "skills/<owner>/references/<spec>.md"
def _read_tier_weight(tier: str) -> float:
    text = SPEC_PATH.read_text(encoding="utf-8")
    # Parse table row for `<tier>` weight literal
    ...
```

**Pattern B: literal in a Python module constant (e.g., audit threshold).**

Consumer's own module defines the constant, AND `tunables.yaml`'s `source_file` + `source_line` point at it:
```python
# scripts/freshness_audit.py
DEFAULT_THRESHOLD_DAYS = 180  # Phase 7 L1 tunable: freshness_threshold_days
```
Then `tunables.yaml`:
```yaml
- id: freshness_threshold_days
  current_value: "180"
  source_file: scripts/freshness_audit.py
  source_line: <line of DEFAULT_THRESHOLD_DAYS>
  ...
```

**CLI override (always offer this).**

Whether your consumer uses pattern A or B, ALWAYS expose a CLI flag for ad-hoc operator override (so they can A/B test without editing the yaml or the source_file):
```python
parser.add_argument(
    "--threshold-<knob>",
    type=int,
    default=None,
    help=(
        f"Override the threshold (default <N>). Canonical value lives "
        f"in config/tunables.yaml::<my_tunable_id>."
    ),
)
```

When the flag is None, use the default from `source_file`. Validate against `allowed_range` whether the value came from CLI or from source.

### 4. Add regression tests (~30 min)

In your consumer's test file:
- **Pin the default value** — `test_<my_tunable>_default_matches_yaml` reads `config/tunables.yaml` and asserts the consumer's default matches.
- **Boundary tests** — exactly-at min, exactly-at max, just-past min (rejected), just-past max (rejected).
- **Override semantics** (Case A only) — `--<my-tunable-flag>` overrides the yaml default; passing an out-of-range value rejects (exit 2).

### 5. Run `phase_7_lint.py` (~1 min)

```bash
python3 scripts/phase_7_lint.py
```

Expected output: `phase_7_lint: PASS — config/tunables.yaml clean (0 findings).`

If it fails:
- "IMMUTABLE_CONFLICT" → an L1_auto_tunable entry has non-empty `linked_invariants`. Either change to L2_proposal_only OR clear `linked_invariants: []` (the latter ONLY if the knob genuinely doesn't touch any invariant; see Non-negotiable section above).
- "current_value not at source_file:source_line" → the literal at `source_file:source_line` doesn't contain `current_value` as a substring. Fix the line number, the literal, or the yaml — whichever is wrong.
- "owner_skill not a real skill directory" → fix the owner_skill to point at an existing `skills/<name>/` (or use `governance` / `sidecar:<name>` for non-skill owners).
- "L1_auto_tunable source_file in POLICY_GLOBS" → contract C6 violation. Either change to L2_proposal_only or move the literal out of POLICY_GLOBS.
- "C8_CURRENT_OUT_OF_RANGE: current_value outside allowed_range" → fix the value at source_file or update allowed_range.

### 6. Optional: instrument L1a telemetry (~30 min)

If you want Phase 7 L1b miner to see this knob's value across runs, edit `scripts/phase_7_telemetry_collector.py` to capture it in the per-run snapshot:

```python
def _collect_tunables_snapshot() -> dict[str, Any]:
    # ... existing capture
    snapshot["my_tunable_id"] = _read_tunable("my_tunable_id", default=<value>)
    return snapshot
```

This lets the L1b miner detect drift over time. (L1b is currently a stub — the real mining algorithm is deferred until enough pilot telemetry exists, per `docs/phase_7_design.md`.)

### 7. CHANGELOG + commit (~10 min)

`config/tunables.yaml` is NOT in POLICY_GLOBS (it's L0 inventory, not policy text), so this is canon-neutral. Bump the patch version:

```bash
git add -A
git commit -F /tmp/release_msg.txt
git tag -a vX.Y.Z -F /tmp/tag_msg.txt
```

CHANGELOG entry: brief — "Added tunable `<id>` (range [...], change_class L2_proposal_only, consumer `scripts/<...>.py`). Canon-neutral."

## Non-numeric tunables

v1.1.14 phase_7_lint only supports numeric knobs (with `allowed_range`). For string/enum tunables (e.g., a default policy mode), the current pattern is:

- DO NOT add a tunables.yaml entry — phase_7_lint will reject it
- Document the option in the consumer's CLI help text (`parser.add_argument` `help` field)
- Cross-reference from `docs/CONTRIBUTING.md` if it's a recurring operator-facing knob

v1.2.17 example: Severity / Priority thresholds were left as CLI-only flags (`--severity-threshold`, `--priority-threshold`) because they have non-numeric enum semantics not captured by `allowed_range`. They're documented in the consumer's `--help` and the audit-contract.md, but NOT in tunables.yaml.

## Common pitfalls

- **`linked_invariants: []` to pass lint** when the knob actually touches an invariant — forbidden workaround. v1.2.15 / v1.2.16 retro lock.
- **`change_class: L1_auto_tunable` for quality-affecting knob** — phase_7_lint contract C5 catches it as IMMUTABLE_CONFLICT. L1_auto_tunable is reserved for cosmetic knobs whose source_file is not in POLICY_GLOBS and whose linked_invariants is empty.
- **`current_value` substring drift from `source_file:source_line`** — lint contract C1 catches it. If you change the value in the source, update tunables.yaml in the SAME commit.
- **Treating `tunables.yaml` as the runtime source of defaults** — it's not. Consumer reads from `source_file`. tunables.yaml is inventory + patch metadata for Phase 7 L1b/L2.
- **Tunable consumer doesn't validate value** — operator can pass `--<flag>` value outside `allowed_range` and your script silently uses garbage. Validate at CLI boundary AND when reading from `source_file`.
- **Forgetting to instrument L1a telemetry** — L1b miner can't see knob's value if not captured in `run_*.json`. Optional but recommended.

## Cross-references

- `config/tunables.yaml` — Phase 7 L0 inventory (canonical knob list)
- `scripts/phase_7_lint.py` — lint rules
- `scripts/phase_7_telemetry_collector.py` — L1a (per-run snapshot)
- `scripts/phase_7_miner.py` — L1b (mining; currently stub)
- `scripts/phase_7_patcher.py` — L2 (proposal generation)
- `docs/phase_7_design.md` — change_class semantics + L1/L2 lifecycle + invariant gate
- `docs/phase_7_runbook.md` — operator review workflow
- `docs/CONTRIBUTING.md` — self-review discipline
