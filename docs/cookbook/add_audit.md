# Cookbook: Add a New Audit

Step-by-step recipe for shipping a new reality-probe audit (mirrors v1.2.16 freshness / v1.2.17 triangulation). Use this when adding a new check that scans canonical artifacts and emits a report without modifying canonical state.

**Estimated effort:** 1-2 days + 2-4 Codex review rounds.

**Prerequisites:** read `docs/CONTRIBUTING.md` (esp. lessons #2, #3, #5).

## Decision matrix (lock before writing code)

| Decision | Default | Notes |
|---|---|---|
| Skill or script? | **Script** (`scripts/<name>_audit.py`), unless the audit needs its own SKILL.md for orchestrator dispatch | v1.2.16/17 are scripts; the audit-contract docs they reference live in `skills/bsa-orchestrator/references/` (which IS in POLICY_GLOBS — canon bump). |
| Audit-contract location | `skills/bsa-orchestrator/references/<name>-audit-contract.md` (canon-bumping) | Operator-facing contract description. Co-located with other orchestrator references. |
| Trigger | Per-row condition (e.g., severity threshold, age threshold) | Document in audit-contract.md. |
| Verdict shape | **`pass / warn / n/a` only — NO `fail`** (mirror v1.2.16) | Audits are non-blocking by design; the verdict policy never escalates to a build-failing `fail`. `n/a` when upstream artifact missing — never crash. |
| Blocking? | **Non-blocking by default and forever** | Audits emit reports; operator decides. The verdict enum has no `fail` precisely because the audit must never fail the build. |
| Tunable threshold? | If yes → `config/tunables.yaml` entry with `change_class: L2_proposal_only`, `linked_invariants: [INV-01]` | Phase 7 L1 inventory. Numeric thresholds only — phase_7_lint requires ranges. |

## File scaffold

```
scripts/
├── <name>_audit.py                     # Main audit runner
└── test_<name>_audit.py                # 30-50 tests
skills/bsa-orchestrator/references/
└── <name>-audit-contract.md            # Operator-facing contract (POLICY_GLOBS)
config/
└── tunables.yaml                       # +1 entry if tunable threshold added
```

## Step-by-step

### 1. Pre-flight (~20 min)

```bash
# Read existing reality-probe audits end-to-end:
cat scripts/freshness_audit.py
cat scripts/triangulation_audit.py
cat skills/bsa-orchestrator/references/freshness-audit-contract.md
cat skills/bsa-orchestrator/references/triangulation-audit-contract.md
```

Identify:
- Which canonical artifact(s) the audit reads (A50? A51? A59? join across multiple?)
- What the failure condition is in business terms
- What "n/a" means (which upstream artifact's absence makes the audit moot)

### 2. Write `skills/bsa-orchestrator/references/<name>-audit-contract.md` (~30 min)

Mirror `freshness-audit-contract.md` shape. Sections:
- Frontmatter: `# <Name> Audit — Contract`
- One-paragraph what-it-checks intro
- "Trigger" — exact condition expression
- "Inputs" — required + optional canonical artifacts
- "Output" — verdict shape + per-row finding shape
- "Verdict semantics" — what `pass`/`warn`/`n/a` each mean (no `fail` — non-blocking by design)
- "Tunable" — if applicable, the `config/tunables.yaml` knob name + range + default
- "Non-blocking" — explicit statement, mirror v1.2.16 wording

This file is in POLICY_GLOBS — canon hash will bump.

### 3. Write `scripts/<name>_audit.py` (~2-4 hours)

Module-level constants + helpers (mirror v1.2.16):
```python
import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path

# v1.2.16 convention: audits write BOTH a machine-readable JSON marker
# and a human-readable Markdown report under a stage-local subdirectory
# of analysis/canonical/, NOT under analysis/handoff/. Stage choice is
# usually wherever the primary input artifact lives (e.g., A50 lives in
# core_controls but freshness_audit lands under stage1/).
DEFAULT_JSON_REL = "analysis/canonical/<stage>/<name>_audit.json"
DEFAULT_MD_REL = "analysis/canonical/<stage>/<name>_audit.md"

# Per-audit constants (e.g., default thresholds)
DEFAULT_<KNOB>_<UNIT> = <value>
```

Function structure:
- `_read_<inputs>(workspace)` — defensive CSV reads, return rows or empty list
- `_evaluate_row(row, threshold)` — pure function: row + config → finding dict (or None for pass)
- `_render_markdown(findings, summary)` — emit `*_audit.md` body
- `_render_json(findings, summary)` — emit `*_audit.json` machine-readable counterpart (always paired with the MD per v1.2.16 convention)
- `_atomic_write(path, body)` — tempfile + os.replace
- `main(argv)` — CLI

CLI surface (mandatory; mirror freshness_audit.py exactly):
```python
parser.add_argument("--workspace", type=Path, default=Path.cwd())
parser.add_argument("--threshold-<knob>", type=int, default=None,
                    help="Override the threshold (default <N>). Canonical value lives in config/tunables.yaml::<id>.")
parser.add_argument("--today", type=_parse_today_arg, default=None,
                    help="Override today's UTC date. Test-only knob.")
parser.add_argument("--output-path", type=Path, default=None,
                    help="Override JSON marker path (default <workspace>/analysis/canonical/<stage>/<name>_audit.json).")
parser.add_argument("--report-path", type=Path, default=None,
                    help="Override Markdown report path (default <workspace>/analysis/canonical/<stage>/<name>_audit.md).")
parser.add_argument("--print-only", action="store_true")
parser.add_argument("--quiet", action="store_true")
```

Verdict policy (mirror v1.2.16 EXACTLY — `fail` is intentionally absent):
- 0 findings → `pass`
- 1+ findings (any severity) → `warn`
- Upstream artifact missing → `n/a`
- Print verdict line in summary block: `verdict: <pass|warn|n/a>`
- Exit code: ALWAYS 0 (audit completed successfully, regardless of verdict; non-blocking by design). Exit 2 reserved for invocation errors only.

Apply self-review lessons:
- **Lesson #2** — read the cross-referenced schema (e.g., A50.schema.json for EffectiveDate field shape) before assuming column exists
- **Lesson #3** — edge cases: empty cell, whitespace-padded, future-dated, multi-value `;`/`/`-joined per multi-FK contract
- **Lesson #5** — reach equality between schema regex and audit's parsing (don't use `\d` if schema uses `[0-9]`)

### 4. Write `scripts/test_<name>_audit.py` (~2-3 hours)

Test buckets (target 30-50 tests):
- **Parser** (5-8 tests): missing file / missing required columns / well-formed / empty cells / whitespace handling
- **Verdict policy** (3 tests): 0 findings → pass / 1+ findings → warn / upstream missing → n/a
- **Threshold boundary** (3-5 tests): exactly-at / just-past / well-past
- **Multi-value join** (if applicable, e.g., A59→A50 via SourceID) (2-3 tests)
- **Tier-blindness or other invariants** (2-3 tests)
- **Backward-compat** (1-2 tests): pre-v1.x.y CSVs without the new column still parse
- **CLI** (4-6 tests): uninit workspace / missing artifact / --threshold override / --print-only / --quiet
- **Markdown rendering** (3-5 tests): verdict line present + finding rows + summary counts
- **Safety boundary** (3 tests): no subprocess imports / canonical state unchanged / no .tmp leftovers

### 5. Update `config/tunables.yaml` (if tunable threshold) (~10 min)

Use the real schema documented in `config/tunables.yaml` header lines 1-50 (NOT the invented one shown in pre-R1 versions of this recipe). Read [docs/cookbook/add_phase7_tunable.md](add_phase7_tunable.md) for the full procedure; minimal example for an audit threshold:

```yaml
- id: <name>_<unit>_threshold              # snake_case, globally unique
  current_value: "<verbatim>"              # MUST appear at source_file:source_line
  allowed_range: [<min>, <max>]            # numeric only (v1.1.14)
  owner_skill: <audit-owning-skill>        # OR `governance` if no skill owns the audit
  source_file: scripts/<name>_audit.py
  source_line: <line of DEFAULT_<UNIT>_<NAME> constant>
  linked_invariants: [INV-01]              # set non-empty for quality-affecting knobs
  change_class: L2_proposal_only           # NEVER L1_auto_tunable for audit thresholds
  rationale: <one-line-why-and-when-to-tune>
```

**Important**: tunables.yaml is INVENTORY/PATCH METADATA. Your audit reads the value from `source_file:source_line` (its own module constant), NOT by importing yaml at runtime.

Run `python3 scripts/phase_7_lint.py` to confirm new entry passes.

### 6. Update `scripts/compute_canon_hash.py` POLICY_GLOBS (~5 min)

Add the new audit-contract reference alphabetically:
```python
"skills/bsa-orchestrator/references/<name>-audit-contract.md",
```

### 7. Recompute canon hash + bump manifest (~10 min)

Same as `add_contract_exporter.md` step 8. New hash → plugin.json + 5 fixture metadata files in lockstep.

### 8. Update CHANGELOG + RELEASING (~20 min)

Mirror v1.2.16 entry shape. Emphasize:
- "opt-in operator audit" framing (non-blocking)
- Verdict policy
- Tunable knob (if added) + Phase 7 L1 inventory entry
- Lesson application

### 9. Pre-Codex self-review + Codex loop (~1-3 rounds)

Same as `add_contract_exporter.md` steps 10-11. Audits typically need fewer rounds (2-3) than exporters because they're read-only.

### 10. Final commit + tag (~5 min)

```bash
git add -A
git commit -F /tmp/release_msg.txt
git tag -a vX.Y.Z -F /tmp/tag_msg.txt
```

## Common pitfalls

- **Reading the wrong schema for the column you're about to require.** v1.2.16 added `EffectiveDate` to A50; you must read `governance/schemas/a50.schema.json` for the column shape, not assume.
- **Forgetting backward-compatibility for new optional columns.** Pre-v1.x.y CSVs without the new column must still parse. Use `optional_columns=` in `iter_csv_rows()`.
- **Reach equality drift between audit threshold parsing and schema's value range.** Lesson #5. v1.2.17 R-X caught: capitalized `Severity` in audit didn't match lowercase enum in schema.
- **Tunable with `change_class: L1_auto_apply`** for a knob that influences evidence-binding quality. Use `L2_proposal_only` with `linked_invariants: [INV-01]` — never auto-tune evidence quality without human review (locked v1.2.15 design decision).
- **Audit emitting blockers but not labeling its own verdict line.** Dashboard's `detect_audit_verdict` heuristic looks for `Verdict: PASS|WARN|FAIL` patterns + a few synonyms. Without one of those patterns, the dashboard shows "unknown" — cosmetic but ugly.

## Cross-references

- `scripts/freshness_audit.py` — v1.2.16 (template; clean reality-probe pattern)
- `scripts/triangulation_audit.py` — v1.2.17 (multi-artifact join pattern)
- `skills/bsa-orchestrator/references/freshness-audit-contract.md` — v1.2.16 contract template
- `skills/bsa-orchestrator/references/triangulation-audit-contract.md` — v1.2.17 contract template
- `config/tunables.yaml` — Phase 7 L0 inventory
- `docs/phase_7_design.md` — change_class semantics + L1/L2 lifecycle
- `docs/CONTRIBUTING.md` — 15 self-review lessons
