# Dashboard Operator Runbook

Status: **opt-in operator workflow** as of v1.3.3. The dashboard is a read-only static-HTML viewer over canonical artifacts + handoff packets + audit reports + sidecar diagrams + Phase 7 telemetry. It NEVER writes to `analysis/canonical/`, NEVER runs git, NEVER invokes any pipeline skill. Generation is operator-driven.

## What it does

Reads the workspace, emits 20+ static HTML pages under `<workspace>/analysis/handoff/dashboard/`, opens them in any browser. No HTTP server. No backend. No deps beyond Python stdlib + jinja2 + markdown-it-py.

## When to use it

- **After a pipeline run** to see the full state at a glance: pipeline-stage progress, A-table counts, audit verdicts, handoff packet links.
- **During analyst review** to navigate between A59 claims and their bound A50 sources / A58 excerpts (claim-layer view) without grep'ing CSVs.
- **Before shipping** to verify traceability matrix (A72) is complete and audit verdicts are pass.
- **For Phase 7 review pass** to scan L2 patcher proposals with diff viewer + clipboard `git apply` command instead of opening each `.patch` file individually.
- **Ad-hoc** any time you want a navigable view of the workspace state.

## Quick start

```bash
# Generate everything (default output: <workspace>/analysis/handoff/dashboard/)
python3 scripts/generate_dashboard.py --workspace .

# Open the result
open analysis/handoff/dashboard/index.html  # macOS
xdg-open analysis/handoff/dashboard/index.html  # Linux
```

That's it. Dashboard regenerates from current canonical state every run; no incremental cache.

## CLI surface

```
python3 scripts/generate_dashboard.py --workspace <path>
python3 scripts/generate_dashboard.py --workspace <path> --output-dir <dir>
python3 scripts/generate_dashboard.py --workspace <path> --filter audits,phase7
python3 scripts/generate_dashboard.py --workspace <path> --watch
python3 scripts/generate_dashboard.py --workspace <path> --print-only
python3 scripts/generate_dashboard.py --workspace <path> --quiet
```

| Flag | Effect |
|---|---|
| `--workspace <path>` | BSA workspace root. Defaults to cwd. Must contain `analysis/` subdirectory or exits 2. |
| `--output-dir <dir>` | Override output. Default `<workspace>/analysis/handoff/dashboard/`. Implicit-missing dir is created on demand; explicit path that doesn't exist is rejected (operator typo defense). Outside-workspace dirs work; their absolute path is recorded in the manifest. |
| `--filter audits,phase7` | Comma-separated subset of pages to render. Valid keys: `index, artifacts, audits, handoff, contracts, sidecars, phase7`. `index` is always included. Unrecognized keys exit 2. Nav links auto-hide for unrendered sections (no 404s). |
| `--watch` | Polls `<workspace>/analysis/` mtimes every 2s and re-renders on any change. Browser auto-refreshes via injected `<meta http-equiv="refresh">` tag. Ctrl-C to stop. Output dir excluded from snapshot to avoid feedback loops. |
| `--print-only` | Print page-render manifest as JSON to stdout. **Zero filesystem writes.** Use for tooling integration / debugging which pages would be rendered. |
| `--quiet` | Suppress per-summary log line. Forced on when `--print-only` (so stdout stays valid JSON). |

## Page map

```
analysis/handoff/dashboard/
├── index.html                          # Overview: counts + verdict badges + pipeline state
├── artifacts/
│   ├── index.html                      # Counter grid for all 10 A-tables
│   ├── a50.html, a51.html, ..., a72.html  # Per-A-table sortable+filterable view
│   ├── claim_layer.html                # A59 cards with bound A50/A58 (joined view)
│   └── traceability.html               # A72 grouped by StoryID (collapsible)
├── audits/
│   ├── index.html                      # Verdict-badge list of all discovered audits
│   └── <audit_id>.html                 # Per-audit MD→HTML rendering
├── handoff/
│   ├── index.html                      # H1-H4 packet list
│   └── h1.html, h2.html, h3.html, h4.html  # Per-packet MD→HTML
├── contracts/
│   ├── index.html                      # OpenAPI / AsyncAPI / proto export list
│   └── openapi.html, asyncapi.html, proto.html  # Spec source + anchor manifest mapping
├── sidecars/
│   ├── index.html                      # C4 / BPMN / DBML diagram list
│   └── c4.html, bpmn.html, dbml.html   # Source code blocks + anchor manifest mapping
├── phase7/
│   ├── index.html                      # L2 proposals list + telemetry runs
│   └── proposal_<id>.html              # Per-proposal: summary + diff + clipboard apply command
└── static/
    ├── style.css                       # Light/dark mode auto via prefers-color-scheme
    ├── filterable_table.js             # Click-to-sort + text-filter for A-tables
    ├── claim_filter.js                 # Generic .filterable-row text filter
    └── clipboard.js                    # Copy-button handler with execCommand fallback
```

Pages auto-skip when their inventory is empty: an A-table page is skipped if its CSV is missing; a sidecar page is skipped if there are no `.puml` / `.bpmn` / `.dbml` files; the Phase 7 section is skipped if there's no `analysis/telemetry/`.

## Operator workflows

### Workflow A: post-pipeline state check

```bash
# After running /bsa-stage 6 or full pipeline:
python3 scripts/generate_dashboard.py --workspace . --quiet
open analysis/handoff/dashboard/index.html
```

Look at: pipeline-stage chips (which stages produced artifacts), A-table counts, verdict-badge colors. Click any artifact ID to jump to its row in the relevant A-table.

### Workflow B: Phase 7 proposal review

```bash
# After phase_7_patcher.py emitted proposals to analysis/telemetry/proposals/
python3 scripts/generate_dashboard.py --workspace . --filter phase7 --quiet
open analysis/handoff/dashboard/phase7/index.html
```

Per proposal page shows:
- Summary MD rendered
- Unified diff with green/red line coloring
- Copy-button for `git apply -- <patch-path>` (path is shlex-quoted automatically — safe to paste even if proposal_id contains shell metacharacters)

After clicking Copy and applying the patch:
```bash
# Operator-side, dashboard does NOT run this:
git apply -- analysis/telemetry/proposals/<id>.patch
git diff       # review the change
git commit ... # ship per docs/RELEASING.md
```

### Workflow C: live development with auto-refresh

```bash
# Terminal 1: keep regenerating on every workspace change
python3 scripts/generate_dashboard.py --workspace . --watch

# Browser: open the index, leave it; meta-refresh tag re-fetches every 2s
open analysis/handoff/dashboard/index.html
```

Edit a CSV / re-run an audit / drop a sidecar diagram — dashboard reflects within ~2s. Useful during `/bsa-stage` iterations.

### Workflow D: filtered renders for fast iteration

When the workspace is huge and you only care about one section:

```bash
# Just audits (skips artifacts/, handoff/, contracts/, sidecars/, phase7/):
python3 scripts/generate_dashboard.py --workspace . --filter audits --quiet

# Audits + Phase 7:
python3 scripts/generate_dashboard.py --workspace . --filter audits,phase7 --quiet
```

Nav links automatically hide for unrendered sections — no 404s.

### Workflow E: dry-run to inspect manifest

```bash
# Pure JSON to stdout, ZERO filesystem writes:
python3 scripts/generate_dashboard.py --workspace . --print-only | jq .
```

Use cases: CI integration, scripted "did the dashboard pick up my new artifact?" check, debugging discovery without polluting `dashboard/` output.

## Interpreting the overview index

The overview page (`index.html`) shows five sections:

1. **Pipeline state** — chips per detected stage (`core controls`, `stage1`, ..., `stage8`) with artifact counts. Stage is "present" iff at least one A-table CSV was found in its subdirectory.

2. **Canonical artifacts** — counter grid (A50 sources, A51 issue routes, ..., A72 trace links). Each tile click → per-A-table page.

3. **Audits** — verdict-badge list with color coding:
   - 🟢 `pass` (green left-border) — verdict explicitly passed
   - 🟡 `warn` (orange) — warnings present
   - 🔴 `fail` (red) — blockers present
   - ⚫ `na` (gray) — n/a (upstream missing)
   - `unknown` (slate) — verdict marker not detected in audit MD

   The detector scans the entire audit MD for verdict patterns; `unknown` typically means the audit doesn't follow the conventional `Verdict: PASS|WARN|FAIL` line.

4. **Handoff packets** — H1-H4 link list (only those present).

5. **Phase 7 telemetry** — collapsed: telemetry run count + open proposal count + link to detail.

## Cross-linking (anchor IDs)

Every primary-key cell in an A-table is rendered with `id="row-<value>"`. Every cross-reference column (e.g., `RelatedClaimID` in A51) links to the target A-table page with `#row-<id>` fragment, so clicking jumps directly to the referenced row.

Cross-link map:
- `A51.RelatedClaimID` → `A59.ClaimID`
- `A58.SourceID` → `A50.SourceID`
- `A59.SourceID` → `A50.SourceID`, `A59.ExcerptID` → `A58.ExcerptID`
- `A60.SourceID` → `A50`, `A60.RelatedClaimID` → `A59`
- `A61.ClaimID` → `A59`, `A61.A51Ref` → `A51`
- `A62.RelatedClaimID` → `A59`, `A62.A51Ref` → `A51`
- `A70.SourceClaimIDs` → `A59` (multi-value `;`/`/`-split), `A70.RelatedNFRIDs` → `A62`, `A70.A51Ref` → `A51`
- `A71.RelatedNFRID` → `A62`, `A71.A51Ref` → `A51`
- `A72.StoryID` → `A70`, `A72.ClaimID` → `A59`, `A72.SourceID` → `A50`, `A72.A51Ref` → `A51`

## Filter + sort on A-table pages

Every A-table page has:
- **Filter input** at top — case-insensitive text search across all visible cells. Empty filter shows all rows. Live count `<visible> / <total>` updates as you type.
- **Click-to-sort headers** — click any column header to sort ascending; click again to flip. Numeric values auto-detected (sorted numerically); strings sorted via `localeCompare`. Active sort indicator (↑ / ↓) shown next to header text.
- **Severity color rows** (A51 only) — each row has a left-border colored by `Severity`: red for `critical`/`high`, orange for `medium`, gray for `low`.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Exit 2 with "no analysis/" | Workspace path doesn't have `analysis/` subdir | Pass `--workspace` to actual BSA workspace root (the dir that contains `analysis/canonical/...`). |
| Exit 2 with "--output-dir does not exist" | Explicit `--output-dir` path missing | Either create the dir first OR drop `--output-dir` to use the implicit default (which IS created on demand). |
| Exit 2 with "unknown filter page(s)" | Typo in `--filter` value | Valid keys: `index, artifacts, audits, handoff, contracts, sidecars, phase7`. |
| RuntimeError "Jinja2 required" | Python env missing dep | `pip install jinja2` (or `pip install -r requirements-dev.txt`). |
| RuntimeError "markdown-it-py required" | Same | `pip install markdown-it-py`. |
| Dashboard pages all empty | Workspace has no canonical / handoff / views / telemetry artifacts yet | Run pipeline first: `/bsa-stage 1` etc. Dashboard reflects current state; it doesn't generate anything itself. |
| Audit verdict shows "unknown" | Audit MD doesn't have a recognized verdict line | Cosmetic; click through to read the MD content directly. The detector looks for `Verdict: PASS\|WARN\|FAIL` patterns + a few synonyms. |
| Watch loop seems stuck | Two terminals running watch on same workspace | Only run one watch instance per workspace; they don't coordinate. |
| Browser shows stale content | Browser cache (rare; static HTML usually refreshes) | Hard-reload (`Cmd-Shift-R` / `Ctrl-Shift-R`). |

## Safety properties (operator-relevant)

- **Read-only**: dashboard never writes to `analysis/canonical/` (verified by `test_dashboard_does_not_modify_canonical_state` regression).
- **No subprocess**: `scripts/generate_dashboard.py` + `scripts/dashboard/{loaders,renderers}.py` do NOT import `subprocess` — no shell-out, no git invocation, no `protoc` call (verified by `test_*_does_not_import_subprocess` regressions).
- **Atomic writes**: every page emit goes through `tempfile + os.replace` — no half-written HTML if the process is killed mid-render.
- **Path-traversal defense**: `proposal_id` from `_index.json` is validated against `^[A-Za-z0-9_-]+$` before any path join (lesson #15 reapplied; v1.3.3 R1 fix).
- **Shell-injection defense**: the operator-pasteable `git apply` command uses `shlex.quote()` for the patch path AND `--` end-of-options separator (lesson #4 + #5 reapplied).
- **HTML-injection defense**: markdown-it-py configured with `html: false` to block raw `<script>` injection from operator MD content; Jinja2 autoescape on for all templates.

## v1.3.5 enhancements

The v1.3.5 release added five operator-facing UX improvements layered on top of the v1.3.3 baseline. All canon-neutral; no breaking changes.

### Keyboard shortcuts

| Key | Effect |
|---|---|
| `/` | Focus the nav search box. |
| `Escape` | Blur the active input + close any open dropdown. |
| `g` then `o` | Navigate to Overview (index.html). |
| `g` then `a` | Navigate to Artifacts. |
| `g` then `u` | Navigate to a**U**dits (`a` is taken by Artifacts; `u` from "audit"). |
| `g` then `h` | Navigate to Handoff. |
| `g` then `c` | Navigate to Contracts. |
| `g` then `d` | Navigate to Diagrams (sidecars). |
| `g` then `p` | Navigate to Phase 7. |

The `g`-prefix has a 1500ms timeout — if you don't press the second key within 1.5s, the prefix clears. Shortcuts are disabled while typing in inputs (input / textarea / select / contentEditable elements), so they don't interfere with the search box or the in-page filter inputs.

### Full-text search

Nav search box (right side of the header on every page) does instant client-side substring matching across all rendered content:

- A-table rows (one entry per row, indexed by primary-key value — clicking lands on the row's `#row-<id>` anchor)
- Audit reports (full Markdown body, snippet-truncated to 400 chars)
- Handoff packets (same)
- Contract specs (OpenAPI/AsyncAPI/proto source)
- Sidecar diagrams (one entry per file)
- Phase 7 proposals (summary MD; only safe-ID entries — unsafe IDs from `_index.json` are filtered out, same as the proposal page list)

Source: `<dashboard_root>/search_index.json`. Browser fetches once, then filters in memory. Up to 30 results shown; refining the query narrows the set. Press `/` from anywhere to focus the box; `Escape` closes the dropdown.

### Mermaid traceability flowchart

`artifacts/traceability.html` now renders the A72 traceability matrix as a Mermaid `flowchart LR` (Story → Claim → Source) above the existing nested HTML table. Three-tier color classes:
- 🟦 Story (blue)
- 🟩 Claim (green)
- 🟨 Source (amber)

Multi-value `;`/`/`-joined IDs in any column fan out into multiple nodes + edges (e.g., one A72 row with `ClaimID=C-1;C-2` and `SourceID=S-1/S-2` produces 4 source-edges). Node IDs are sanitized to Mermaid-safe form (any non-`[A-Za-z0-9_]` char → `_`). The HTML table below remains as a JS-disabled fallback.

For very large graphs (>50 unique nodes), a hint above the chart warns that rendering may take a few seconds.

### bpmn-js inline viewer

`sidecars/bpmn.html` embeds the [bpmn-js NavigatedViewer](https://github.com/bpmn-io/bpmn-js) for each `.bpmn` file in the workspace. The XML source is moved into a collapsible `<details>` block beneath the rendered diagram. Pan/zoom interactions work natively (mouse drag + scroll-wheel).

If the bpmn-js bundle isn't loaded (e.g., `vendor/bpmn-navigated-viewer.js` missing), each viewer container shows a clear error message instead of failing silently.

C4 (PlantUML) and DBML sidecar pages remain code-block + manifest mapping per the v1.3.3 locked design — those formats render via operator-side tools (`plantuml`, `dbdiagram.io`, etc.).

### Chart.js KPI trend charts

`phase7/index.html` now renders one line chart per numeric KPI extracted from `analysis/telemetry/run_*.json` files. Per chart:

- X-axis: chronological by `generated_at` timestamp (sorted at index-build time)
- Y-axis: numeric KPI value, starting at 0
- Hover any point: tooltip with run_id + value
- Dark-mode-aware (axis + grid + line colors auto-switch via `prefers-color-scheme`)

KPIs with `null` or non-numeric values across all runs are silently skipped (telemetry collector emits `null` when upstream artifact missing per v1.2.4 contract). Section only appears when at least one telemetry run is present.

### Vendor JS bundles

v1.3.5 ships 5 bundled assets totaling ~4.4 MB under `scripts/dashboard/static/vendor/`:

| File | Library | Version | Source URL |
|---|---|---|---|
| `mermaid.min.js` | Mermaid | 10.9.1 | `https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js` |
| `chart.umd.js` | Chart.js | 4.4.0 | `https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.js` |
| `bpmn-navigated-viewer.js` | bpmn-js NavigatedViewer | 17.9.1 | `https://unpkg.com/bpmn-js@17.9.1/dist/bpmn-navigated-viewer.production.min.js` |
| `bpmn-diagram.css` | bpmn-js diagram-js styles | 17.9.1 | `https://unpkg.com/bpmn-js@17.9.1/dist/assets/diagram-js.css` |
| `bpmn-embedded.css` | bpmn-js embedded styles | 17.9.1 | `https://unpkg.com/bpmn-js@17.9.1/dist/assets/bpmn-js.css` |

To re-pin or re-bundle:
```bash
cd scripts/dashboard/static/vendor
curl -fsSL -o mermaid.min.js 'https://cdn.jsdelivr.net/npm/mermaid@<NEW>/dist/mermaid.min.js'
# ... repeat for each lib
```

Operators uncomfortable with the +4.4 MB repo-size delta can `.gitignore` the vendor/ directory and run the curl commands above as a one-time setup step. The dashboard gracefully degrades if vendor files are missing (Mermaid blocks render plain `<pre>`; bpmn-containers show a "not loaded" error; KPI canvases show a similar error).

## Cross-references

- `scripts/generate_dashboard.py` — main entry point + CLI surface.
- `scripts/dashboard/loaders.py` — workspace inventory discovery (glob-based filename routing).
- `scripts/dashboard/renderers.py` — per-page context builders + safe-ID validation + diff renderer.
- `scripts/dashboard/templates/*.html` — 15 Jinja2 templates.
- `scripts/dashboard/static/{style.css,filterable_table.js,claim_filter.js,clipboard.js}` — bundled vanilla assets.
- `scripts/test_generate_dashboard.py` — 60-test regression suite.
- `docs/phase_7_runbook.md` — operator workflow for the L2 patcher (the dashboard's Phase 7 page links to per-proposal detail pages that complement this runbook).
- `docs/cookbook/` — recipes for adding new artifacts that the dashboard will pick up automatically.
- `docs/CONTRIBUTING.md` — self-review discipline for changes that touch any of the dashboard's read sources.
