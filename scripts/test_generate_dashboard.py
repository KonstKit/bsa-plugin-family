"""Tests for `scripts/generate_dashboard.py` + `scripts/dashboard/`
(v1.3.3 dashboard generator).

Covers:
  * loaders.discover() on empty / partial / full workspaces
  * loaders.count_rows + detect_audit_verdict
  * renderers.build_artifact_context (anchor cross-refs, A51 severity
    rows, primary-key detection)
  * renderers.md_to_html
  * renderers.detect_audit_verdict_robust (full-file scan)
  * renderers.render_unified_diff_html (add/del/hunk/context classes)
  * renderers.build_claim_layer_context (A59+A50+A58 join)
  * renderers.build_traceability_context (StoryID grouping)
  * renderers.build_proposal_context (summary + diff + apply_command)
  * renderers.build_contract_context (anchor mapping + unmapped)
  * renderers.build_sidecar_context (code blocks + anchor map)
  * CLI: --workspace, --output-dir, --filter, --print-only, --quiet,
    --watch (interrupt-safe smoke)
  * Safety boundary: NO subprocess import; canonical state unchanged;
    no .tmp leftovers; idempotent rendering
  * Full-fixture render: project_0003 + project_0004 produce expected
    page count + manifest shape
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_dashboard.py"
DASHBOARD_PKG = REPO_ROOT / "scripts" / "dashboard"
FIXTURE_P0003 = REPO_ROOT / "fixtures" / "golden" / "project_0003" / "expected_outputs"
FIXTURE_P0004 = REPO_ROOT / "fixtures" / "golden" / "project_0004_sidecar_e2e" / "expected_outputs"


# ---- Module loaders --------------------------------------------------


@pytest.fixture(scope="module")
def main_module():
    """Load scripts/generate_dashboard.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "generate_dashboard", SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def loaders(main_module):
    return main_module.loaders


@pytest.fixture(scope="module")
def renderers(main_module):
    return main_module.renderers


# ---- Workspace builders ---------------------------------------------


def _make_p0003_workspace(tmp_path: Path) -> Path:
    """Synthesize a workspace from project_0003 fixture (canonical +
    handoff)."""
    ws = tmp_path / "ws_p0003"
    (ws / "analysis").mkdir(parents=True)
    shutil.copytree(FIXTURE_P0003 / "canonical", ws / "analysis" / "canonical")
    if (FIXTURE_P0003 / "handoff").is_dir():
        shutil.copytree(FIXTURE_P0003 / "handoff", ws / "analysis" / "handoff")
    return ws


def _make_p0004_workspace(tmp_path: Path) -> Path:
    """project_0004 — has canonical + sidecar views."""
    ws = tmp_path / "ws_p0004"
    (ws / "analysis").mkdir(parents=True)
    shutil.copytree(FIXTURE_P0004 / "canonical", ws / "analysis" / "canonical")
    if (FIXTURE_P0004 / "views").is_dir():
        shutil.copytree(FIXTURE_P0004 / "views", ws / "analysis" / "views")
    return ws


def _make_empty_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws_empty"
    (ws / "analysis").mkdir(parents=True)
    return ws


def _make_uninit_workspace(tmp_path: Path) -> Path:
    """No analysis/ subdir."""
    ws = tmp_path / "ws_uninit"
    ws.mkdir()
    return ws


# ---- loaders.discover() ---------------------------------------------


def test_discover_empty_workspace(loaders, tmp_path):
    ws = _make_empty_workspace(tmp_path)
    inv = loaders.discover(ws)
    assert all(p is None for p in inv.a_tables.values())
    assert all(p is None for p in inv.audits.values())
    assert all(p is None for p in inv.handoff.values())
    assert all(
        files.get("spec") is None and files.get("manifest") is None
        for files in inv.contracts.values()
    )
    assert all(not files for files in inv.sidecars.values())
    assert inv.telemetry_runs == []
    assert inv.proposals == []


def test_discover_p0003_workspace(loaders, tmp_path):
    ws = _make_p0003_workspace(tmp_path)
    inv = loaders.discover(ws)
    a_tables_present = sum(1 for p in inv.a_tables.values() if p is not None)
    assert a_tables_present >= 5
    # core_controls fixtures have at least A50/A51/A58/A59/A60.
    assert inv.a_tables["a50"] is not None
    assert inv.a_tables["a51"] is not None
    assert inv.a_tables["a59"] is not None
    # Handoff packets present.
    handoff_present = sum(1 for p in inv.handoff.values() if p is not None)
    assert handoff_present >= 1


def test_discover_p0004_with_sidecars(loaders, tmp_path):
    ws = _make_p0004_workspace(tmp_path)
    inv = loaders.discover(ws)
    sidecar_total = sum(len(files) for files in inv.sidecars.values())
    assert sidecar_total >= 1
    # At least one of c4/bpmn/dbml present.
    assert any(files for files in inv.sidecars.values())


def test_discover_handles_missing_subdirs(loaders, tmp_path):
    """Missing analysis/canonical|handoff|views|telemetry must not
    crash; result should be empty inventory."""
    ws = _make_uninit_workspace(tmp_path)
    inv = loaders.discover(ws)
    assert inv.workspace == ws
    assert all(p is None for p in inv.a_tables.values())


def test_a_table_pattern_matches_candidate_filenames(loaders):
    """A61 also matches the `_candidate.csv` form."""
    rx = loaders.A_TABLE_PATTERNS["a61"]
    assert rx.fullmatch("A61_anchor_map.csv")
    assert rx.fullmatch("A61_anchor_map_candidate.csv")
    assert not rx.fullmatch("A61_anchor_map_other.csv")


def test_count_rows_missing_file(loaders, tmp_path):
    assert loaders.count_rows(tmp_path / "nope.csv") == 0


def test_count_rows_well_formed(loaders, tmp_path):
    csv_path = tmp_path / "x.csv"
    csv_path.write_text("a,b\n1,2\n3,4\n5,6\n", encoding="utf-8")
    assert loaders.count_rows(csv_path) == 3


def test_detect_audit_verdict_missing(loaders, tmp_path):
    assert loaders.detect_audit_verdict(tmp_path / "nope.md") == "na"
    assert loaders.detect_audit_verdict(None) == "na"


# ---- renderers.detect_audit_verdict_robust -------------------------


def test_verdict_robust_pass(renderers, tmp_path):
    p = tmp_path / "audit.md"
    p.write_text("# Audit\n\nVerdict: PASS\n0 findings\n", encoding="utf-8")
    assert renderers.detect_audit_verdict_robust(p) == "pass"


def test_verdict_robust_warn(renderers, tmp_path):
    p = tmp_path / "audit.md"
    p.write_text("# Audit\n\nVerdict: warn\nWarnings: 3\n", encoding="utf-8")
    assert renderers.detect_audit_verdict_robust(p) == "warn"


def test_verdict_robust_fail(renderers, tmp_path):
    p = tmp_path / "audit.md"
    p.write_text("# Audit\n\nVerdict: FAIL\nBlockers: 2\n", encoding="utf-8")
    assert renderers.detect_audit_verdict_robust(p) == "fail"


def test_verdict_robust_na(renderers, tmp_path):
    p = tmp_path / "audit.md"
    p.write_text("Status: n/a — upstream artifact missing\n", encoding="utf-8")
    assert renderers.detect_audit_verdict_robust(p) == "na"


def test_verdict_robust_unknown(renderers, tmp_path):
    p = tmp_path / "audit.md"
    p.write_text("# Audit\n\nNo recognizable verdict marker.\n", encoding="utf-8")
    assert renderers.detect_audit_verdict_robust(p) == "unknown"


# ---- renderers.render_unified_diff_html ----------------------------


def test_diff_renders_add_del_hunk_classes(renderers):
    diff = (
        "--- a/file.txt\n"
        "+++ b/file.txt\n"
        "@@ -1,3 +1,3 @@\n"
        " context line\n"
        "-removed line\n"
        "+added line\n"
    )
    html = renderers.render_unified_diff_html(diff)
    assert 'class="diff-meta"' in html
    assert 'class="diff-hunk"' in html
    assert 'class="diff-add"' in html
    assert 'class="diff-del"' in html
    assert 'class="diff-context"' in html


def test_diff_escapes_html(renderers):
    diff = "+<script>alert(1)</script>\n"
    html = renderers.render_unified_diff_html(diff)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_diff_empty_input(renderers):
    assert renderers.render_unified_diff_html("") == ""


# ---- renderers.md_to_html ------------------------------------------


def test_md_to_html_headings_and_lists(renderers):
    html = renderers.md_to_html("# Title\n\n- one\n- two\n")
    assert "<h1>" in html
    assert "<ul>" in html
    assert "<li>one</li>" in html


def test_md_to_html_table(renderers):
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    html = renderers.md_to_html(md)
    assert "<table>" in html
    assert "<th>a</th>" in html or "<th>a</th>" in html.lower()


def test_md_to_html_empty(renderers):
    assert renderers.md_to_html("") == ""


def test_md_to_html_no_raw_html(renderers):
    """html: false in config — raw HTML in MD must be escaped."""
    md = "Hello <script>alert(1)</script>"
    html = renderers.md_to_html(md)
    assert "<script>" not in html
    assert "alert(1)" in html  # text content preserved


# ---- renderers.build_artifact_context ------------------------------


def test_build_artifact_a51_severity_classes(renderers, tmp_path):
    csv_path = tmp_path / "a51.csv"
    csv_path.write_text(
        "A51Ref,IssueType,Severity,BlockingStatus\n"
        "R-001,decision_needed,critical,blocking\n"
        "R-002,evidence_gap,low,informational\n",
        encoding="utf-8",
    )
    ctx = renderers.build_artifact_context("a51", csv_path, "issue routes")
    assert ctx["row_count"] == 2
    assert ctx["row_classes"][0] == "row-critical"
    assert ctx["row_classes"][1] == "row-low"
    assert ctx["pk_col"] == "A51Ref"


def test_build_artifact_anchor_cross_links(renderers, tmp_path):
    csv_path = tmp_path / "a72.csv"
    csv_path.write_text(
        "TraceID,StoryID,ClaimID,SourceID,LinkType,LinkStrength\n"
        "T-001,STR-1,C-1,S-1,direct,high\n",
        encoding="utf-8",
    )
    ctx = renderers.build_artifact_context("a72", csv_path, "trace links")
    # Find the cell links for StoryID, ClaimID, SourceID columns.
    headers = ctx["headers"]
    links_by_col = {
        col: ctx["cell_links"][0][i]
        for i, col in enumerate(headers)
    }
    assert any(
        link.get("href", "").endswith("a70.html#row-STR-1")
        for link in links_by_col["StoryID"]
    )
    assert any(
        link.get("href", "").endswith("a59.html#row-C-1")
        for link in links_by_col["ClaimID"]
    )
    assert any(
        link.get("href", "").endswith("a50.html#row-S-1")
        for link in links_by_col["SourceID"]
    )


def test_build_artifact_multivalue_split(renderers, tmp_path):
    csv_path = tmp_path / "a70.csv"
    csv_path.write_text(
        "StoryID,SourceClaimIDs\n"
        "STR-1,C-1;C-2/C-3\n",
        encoding="utf-8",
    )
    ctx = renderers.build_artifact_context("a70", csv_path, "stories")
    headers = ctx["headers"]
    src_col_idx = headers.index("SourceClaimIDs")
    links = ctx["cell_links"][0][src_col_idx]
    # Split on `;` and `/` → 3 entries.
    assert len(links) == 3
    values = sorted(link["value"] for link in links)
    assert values == ["C-1", "C-2", "C-3"]


def test_build_artifact_missing_csv_returns_empty(renderers, tmp_path):
    ctx = renderers.build_artifact_context("a50", tmp_path / "nope.csv", "sources")
    assert ctx["row_count"] == 0
    assert ctx["headers"] == []
    assert ctx["rows"] == []


# ---- renderers.build_claim_layer_context ---------------------------


def test_claim_layer_joins_sources_and_excerpts(renderers, tmp_path):
    a59 = tmp_path / "a59.csv"
    a59.write_text(
        "ClaimID,ClaimText,SourceID,ExcerptID,Confidence\n"
        "C-001,Test claim,S-001;S-002,E-001,high\n",
        encoding="utf-8",
    )
    a50 = tmp_path / "a50.csv"
    a50.write_text(
        "SourceID,Title,ReliabilityTier\n"
        "S-001,First source,T1\n"
        "S-002,Second source,T2\n",
        encoding="utf-8",
    )
    a58 = tmp_path / "a58.csv"
    a58.write_text(
        "ExcerptID,ExcerptText,SourceID\n"
        "E-001,Quoted text here,S-001\n",
        encoding="utf-8",
    )
    ctx = renderers.build_claim_layer_context(a59, a50, a58)
    assert ctx["claim_count"] == 1
    card = ctx["claim_cards"][0]
    assert len(card["bound_sources"]) == 2
    assert card["bound_sources"][0]["Title"] == "First source"
    assert len(card["bound_excerpts"]) == 1
    assert "Quoted text" in card["bound_excerpts"][0]["ExcerptText"]


# ---- renderers.build_traceability_context ---------------------------


def test_traceability_groups_by_story(renderers, tmp_path):
    a72 = tmp_path / "a72.csv"
    a72.write_text(
        "TraceID,StoryID,ClaimID,SourceID,LinkType\n"
        "T-001,STR-1,C-1,S-1,direct\n"
        "T-002,STR-1,C-2,S-2,indirect\n"
        "T-003,STR-2,C-3,S-3,direct\n",
        encoding="utf-8",
    )
    ctx = renderers.build_traceability_context(a72)
    assert ctx["trace_count"] == 3
    assert ctx["story_count"] == 2
    by_story = {g["story_id"]: g["row_count"] for g in ctx["grouped"]}
    assert by_story == {"STR-1": 2, "STR-2": 1}


# ---- renderers.build_proposal_context ------------------------------


def test_proposal_context_renders_summary_and_diff(renderers, tmp_path):
    proposal_id = "prop-001"
    summary = tmp_path / f"{proposal_id}.summary.md"
    summary.write_text("# Proposal prop-001\n\nBumps tunable X.\n", encoding="utf-8")
    patch = tmp_path / f"{proposal_id}.patch"
    patch.write_text(
        "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n", encoding="utf-8",
    )
    meta = {"proposal_id": proposal_id, "tunable_id": "tier_weight_T2"}
    ctx = renderers.build_proposal_context(meta, tmp_path)
    assert ctx["proposal_id"] == proposal_id
    assert "<h1>" in ctx["summary_html"]
    assert "diff-add" in ctx["diff_html"]
    assert "git apply" in ctx["apply_command"]
    assert proposal_id in ctx["apply_command"]


def test_proposal_context_handles_missing_files(renderers, tmp_path):
    meta = {"proposal_id": "missing-001"}
    ctx = renderers.build_proposal_context(meta, tmp_path)
    assert not ctx["summary_present"]
    assert not ctx["patch_present"]
    assert ctx["apply_command"] is None


# ---- renderers.build_contract_context ------------------------------


def test_contract_context_with_manifest(renderers, tmp_path):
    spec = tmp_path / "api.yaml"
    spec.write_text("openapi: 3.1.0\ninfo: {title: T}\n", encoding="utf-8")
    manifest = tmp_path / "anchor_manifest.json"
    manifest.write_text(json.dumps({
        "view_files": [{
            "anchor_map": [{
                "view_element_id": "/orders",
                "view_element_kind": "PathItem",
                "a61_anchor_id": "ANC-001",
                "notes": "trace: C-001",
            }],
            "unmapped_anchors": [{
                "a61_anchor_id": "ANC-002",
                "reason": "element_id_not_path_shaped",
                "element_id": "bad/path",
            }],
        }],
    }), encoding="utf-8")
    ctx = renderers.build_contract_context("openapi", spec, manifest, "OpenAPI")
    assert ctx["language"] == "yaml"
    assert "openapi: 3.1.0" in ctx["spec_text"]
    assert ctx["manifest_present"] is True
    assert len(ctx["anchor_rows"]) == 1
    assert ctx["anchor_rows"][0]["a61_anchor_id"] == "ANC-001"
    assert len(ctx["unmapped_rows"]) == 1
    assert ctx["unmapped_rows"][0]["reason"] == "element_id_not_path_shaped"


def test_contract_context_proto_language(renderers, tmp_path):
    spec = tmp_path / "services.proto"
    spec.write_text('syntax = "proto3";\n', encoding="utf-8")
    ctx = renderers.build_contract_context("proto", spec, None, "proto3")
    assert ctx["language"] == "protobuf"
    assert ctx["manifest_present"] is False


# ---- renderers.build_sidecar_context -------------------------------


def test_sidecar_context_loads_diagram_content(renderers, tmp_path):
    spec1 = tmp_path / "diagram.puml"
    spec1.write_text("@startuml\nactor User\n@enduml\n", encoding="utf-8")
    ctx = renderers.build_sidecar_context("c4", [spec1], None, "C4 — PlantUML")
    assert len(ctx["diagrams"]) == 1
    assert "actor User" in ctx["diagrams"][0]["content"]
    assert "plantuml" in ctx["render_hint"].lower()


# ---- CLI integration -----------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_uninit_workspace_returns_2(tmp_path):
    ws = _make_uninit_workspace(tmp_path)
    result = _run_cli("--workspace", str(ws), "--print-only")
    assert result.returncode == 2
    assert "no analysis/" in result.stderr


def test_cli_empty_workspace_renders_index(tmp_path):
    ws = _make_empty_workspace(tmp_path)
    result = _run_cli("--workspace", str(ws), "--quiet")
    assert result.returncode == 0
    out_dir = ws / "analysis" / "handoff" / "dashboard"
    assert (out_dir / "index.html").is_file()


def test_cli_print_only_emits_manifest(tmp_path):
    ws = _make_p0003_workspace(tmp_path)
    result = _run_cli("--workspace", str(ws), "--print-only")
    assert result.returncode == 0
    # stdout has both the summary line + JSON manifest. Find JSON.
    out = result.stdout
    json_start = out.find("{")
    manifest = json.loads(out[json_start:])
    assert manifest["manifest_version"] == "1.0"
    assert "pages" in manifest
    assert manifest["inventory_summary"]["a_tables_present"] >= 5


def test_cli_full_render_p0003(tmp_path):
    ws = _make_p0003_workspace(tmp_path)
    result = _run_cli("--workspace", str(ws), "--quiet")
    assert result.returncode == 0
    out_dir = ws / "analysis" / "handoff" / "dashboard"
    assert (out_dir / "index.html").is_file()
    assert (out_dir / "artifacts" / "index.html").is_file()
    assert (out_dir / "artifacts" / "a50.html").is_file()
    assert (out_dir / "artifacts" / "a59.html").is_file()
    assert (out_dir / "artifacts" / "claim_layer.html").is_file()
    assert (out_dir / "static" / "style.css").is_file()
    assert (out_dir / "static" / "filterable_table.js").is_file()


def test_cli_full_render_p0004_sidecars(tmp_path):
    ws = _make_p0004_workspace(tmp_path)
    result = _run_cli("--workspace", str(ws), "--quiet")
    assert result.returncode == 0
    out_dir = ws / "analysis" / "handoff" / "dashboard"
    sidecar_pages = list((out_dir / "sidecars").glob("*.html"))
    # At least index + at least one of c4/bpmn/dbml.
    assert len(sidecar_pages) >= 2


def test_cli_filter_audits_only(tmp_path):
    ws = _make_p0003_workspace(tmp_path)
    result = _run_cli("--workspace", str(ws), "--filter", "audits", "--quiet")
    assert result.returncode == 0
    out_dir = ws / "analysis" / "handoff" / "dashboard"
    # index always written; audits/ written; artifacts/ NOT written.
    assert (out_dir / "index.html").is_file()
    assert (out_dir / "audits").is_dir()
    assert not (out_dir / "artifacts").is_dir()


def test_cli_filter_unknown_page_rejected(tmp_path):
    ws = _make_p0003_workspace(tmp_path)
    result = _run_cli(
        "--workspace", str(ws), "--filter", "nonexistent", "--print-only",
    )
    assert result.returncode != 0
    assert "unknown filter" in result.stderr


def test_cli_output_dir_explicit_missing_returns_2(tmp_path):
    ws = _make_p0003_workspace(tmp_path)
    bogus = tmp_path / "does_not_exist"
    result = _run_cli(
        "--workspace", str(ws),
        "--output-dir", str(bogus),
        "--print-only",
    )
    assert result.returncode == 2
    assert "does not exist" in result.stderr


def test_cli_output_dir_implicit_permissive(tmp_path):
    """Default output dir doesn't exist yet → created on demand."""
    ws = _make_p0003_workspace(tmp_path)
    out_dir = ws / "analysis" / "handoff" / "dashboard"
    assert not out_dir.exists()
    result = _run_cli("--workspace", str(ws), "--quiet")
    assert result.returncode == 0
    assert (out_dir / "index.html").is_file()


def test_cli_quiet_suppresses_summary(tmp_path):
    ws = _make_p0003_workspace(tmp_path)
    result = _run_cli("--workspace", str(ws), "--quiet")
    assert result.returncode == 0
    assert result.stdout == ""


# ---- Safety boundary -----------------------------------------------


def test_script_does_not_import_subprocess():
    """Structural pin: dashboard generator is operator-driven, no
    shelling out (mirrors v1.3.x exporter discipline)."""
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    # Allow `subprocess` only inside test scaffolding; the generator
    # itself must not import or use it.
    # (Simple substring check is fine — the test file is separate.)
    assert "import subprocess" not in src
    assert "from subprocess" not in src


def test_renderers_does_not_import_subprocess():
    src = (DASHBOARD_PKG / "renderers.py").read_text(encoding="utf-8")
    assert "subprocess" not in src


def test_loaders_does_not_import_subprocess():
    src = (DASHBOARD_PKG / "loaders.py").read_text(encoding="utf-8")
    assert "subprocess" not in src


def test_dashboard_does_not_modify_canonical_state(tmp_path):
    ws = _make_p0003_workspace(tmp_path)
    canonical_before = {
        p.relative_to(ws): p.read_bytes()
        for p in (ws / "analysis" / "canonical").rglob("*")
        if p.is_file()
    }
    result = _run_cli("--workspace", str(ws), "--quiet")
    assert result.returncode == 0
    canonical_after = {
        p.relative_to(ws): p.read_bytes()
        for p in (ws / "analysis" / "canonical").rglob("*")
        if p.is_file()
    }
    assert canonical_before == canonical_after, (
        "dashboard modified analysis/canonical/ — INV-02 violation"
    )


def test_no_tmp_files_left_after_render(tmp_path):
    ws = _make_p0003_workspace(tmp_path)
    result = _run_cli("--workspace", str(ws), "--quiet")
    assert result.returncode == 0
    out_dir = ws / "analysis" / "handoff" / "dashboard"
    leftovers = [
        p.name for p in out_dir.rglob(".dashboard_*.tmp")
    ]
    assert leftovers == [], f"tempfile leftovers: {leftovers}"


# ---- v1.3.3 R1 fix regressions -------------------------------------


def test_proposal_id_unsafe_traversal_skipped(renderers, tmp_path):
    """v1.3.3 R1 fix #1: proposal_id with `../` or path separators
    must be skipped before any path join. Pre-R1 the dashboard would
    read outside proposals_root and write outside output_dir/phase7/."""
    proposals_root = tmp_path
    # Plant a "../escape" file outside proposals_root that the
    # malicious _index.json would point at if validation didn't run.
    (tmp_path.parent / "escape.summary.md").write_text(
        "should not be read", encoding="utf-8",
    )
    bad_meta = {"proposal_id": "../escape"}
    ctx = renderers.build_proposal_context(bad_meta, proposals_root)
    assert ctx is None


def test_proposal_id_with_separators_skipped(renderers, tmp_path):
    bad_meta = {"proposal_id": "a/b/c"}
    assert renderers.build_proposal_context(bad_meta, tmp_path) is None


def test_proposal_id_empty_skipped(renderers, tmp_path):
    assert renderers.build_proposal_context({"proposal_id": ""}, tmp_path) is None
    assert renderers.build_proposal_context({}, tmp_path) is None


def test_proposal_id_safe_passes(renderers, tmp_path):
    (tmp_path / "p-001.summary.md").write_text("# ok", encoding="utf-8")
    ctx = renderers.build_proposal_context(
        {"proposal_id": "p-001"}, tmp_path,
    )
    assert ctx is not None
    assert ctx["proposal_id"] == "p-001"


def test_proposal_meta_non_dict_skipped(renderers, tmp_path):
    """Defensive: list / string / None / int should all skip."""
    for bad in [None, [], "string", 42, True]:
        assert renderers.build_proposal_context(bad, tmp_path) is None


def test_proposal_id_pattern_constants(renderers):
    """Pin the safe-ID regex so future edits notice."""
    assert renderers.is_safe_proposal_id("foo")
    assert renderers.is_safe_proposal_id("p-001")
    assert renderers.is_safe_proposal_id("ABC_123")
    assert not renderers.is_safe_proposal_id("../escape")
    assert not renderers.is_safe_proposal_id("a/b")
    assert not renderers.is_safe_proposal_id("a.b")
    assert not renderers.is_safe_proposal_id("a b")
    assert not renderers.is_safe_proposal_id("")


def test_print_only_writes_no_files(tmp_path):
    """v1.3.3 R1 fix #2: --print-only must not touch the filesystem."""
    ws = _make_p0003_workspace(tmp_path)
    out_dir = ws / "analysis" / "handoff" / "dashboard"
    assert not out_dir.exists()
    result = _run_cli("--workspace", str(ws), "--print-only")
    assert result.returncode == 0
    assert not out_dir.exists(), (
        "--print-only created the dashboard output dir; expected dry-run"
    )


def test_print_only_stdout_pure_json(tmp_path):
    """v1.3.3 R1 fix #2: stdout must be valid JSON (no human summary
    line mixed in). Pre-R1 the summary printed before the JSON
    manifest unless --quiet was also set."""
    ws = _make_p0003_workspace(tmp_path)
    result = _run_cli("--workspace", str(ws), "--print-only")
    assert result.returncode == 0
    # Should parse cleanly without splitting.
    manifest = json.loads(result.stdout)
    assert manifest["manifest_version"] == "1.0"


def test_filter_hides_nav_links_for_unrendered_sections(tmp_path):
    """v1.3.3 R1 fix #3: --filter audits must produce an index.html
    where the nav contains the audits link but NOT the artifacts /
    handoff / contracts / sidecars / phase7 links (they would 404).
    Pre-R1 nav links pointed to ungenerated pages."""
    ws = _make_p0003_workspace(tmp_path)
    result = _run_cli("--workspace", str(ws), "--filter", "audits", "--quiet")
    assert result.returncode == 0
    index_html = (ws / "analysis" / "handoff" / "dashboard" / "index.html").read_text(
        encoding="utf-8",
    )
    # Audits link present.
    assert 'href="audits/index.html"' in index_html
    # Other sections absent (would be 404s).
    assert 'href="artifacts/index.html"' not in index_html
    assert 'href="handoff/index.html"' not in index_html


def test_filter_index_only_shows_only_overview_link(tmp_path):
    """--filter index alone (always-included) renders no other nav
    links because no section was requested."""
    ws = _make_p0003_workspace(tmp_path)
    result = _run_cli("--workspace", str(ws), "--filter", "index", "--quiet")
    assert result.returncode == 0
    index_html = (ws / "analysis" / "handoff" / "dashboard" / "index.html").read_text(
        encoding="utf-8",
    )
    # Only Overview nav link visible.
    nav_links = [
        line for line in index_html.splitlines()
        if 'class="site-nav"' in line or 'href=' in line
    ]
    # Look for the nav block specifically.
    assert 'href="audits/index.html"' not in index_html
    assert 'href="artifacts/index.html"' not in index_html


def test_watch_snapshot_excludes_custom_output_dir(main_module, tmp_path):
    """v1.3.3 R1 fix #4: watch-mode snapshot must exclude files under
    the actual --output-dir (not a hardcoded `dashboard` segment).
    Pre-R1 a custom output dir inside analysis/ would feed back into
    its own snapshot and re-render forever."""
    ws = tmp_path / "ws"
    (ws / "analysis").mkdir(parents=True)
    (ws / "analysis" / "canonical").mkdir()
    (ws / "analysis" / "canonical" / "test.csv").write_text("a\n1\n", encoding="utf-8")
    # Custom output dir inside analysis/, NOT named "dashboard".
    custom_out = ws / "analysis" / "custom_dashboard_output"
    custom_out.mkdir()
    (custom_out / "fake.html").write_text("<p>generated</p>", encoding="utf-8")

    snapshot = main_module._snapshot_mtimes(ws, custom_out)
    # Generated file inside custom_out must NOT appear in the
    # snapshot (would cause feedback loop).
    assert all("custom_dashboard_output" not in p for p in snapshot.keys())
    # The canonical CSV does appear.
    assert any("test.csv" in p for p in snapshot.keys())


def test_phase7_index_filters_unsafe_proposals(tmp_path):
    """v1.3.3 R2 fix (Codex R2 MINOR): phase7/index.html must NOT
    render dead links to proposal_<id>.html pages that the detail-
    page loop will skip due to unsafe IDs. Pre-R2 the index template
    received the raw _index.json proposals list; R2 filters upstream."""
    ws = tmp_path / "ws"
    (ws / "analysis" / "telemetry" / "proposals").mkdir(parents=True)
    (ws / "analysis" / "telemetry" / "proposals" / "_index.json").write_text(
        json.dumps({
            "proposals": [
                {"proposal_id": "good-001", "title": "Safe one"},
                {"proposal_id": "../bad", "title": "Traversal attempt"},
                {"proposal_id": "a/b", "title": "Separator attempt"},
                {"id": "good-002", "title": "Also safe (id key)"},
                "not-a-dict",
            ],
        }),
        encoding="utf-8",
    )
    # Plant the safe summary so the detail page actually renders.
    (ws / "analysis" / "telemetry" / "proposals" / "good-001.summary.md").write_text(
        "# good-001 summary", encoding="utf-8",
    )
    (ws / "analysis" / "telemetry" / "proposals" / "good-002.summary.md").write_text(
        "# good-002 summary", encoding="utf-8",
    )
    result = _run_cli("--workspace", str(ws), "--quiet")
    assert result.returncode == 0
    out_dir = ws / "analysis" / "handoff" / "dashboard"
    index_html = (out_dir / "phase7" / "index.html").read_text(encoding="utf-8")
    # Safe proposals: link present.
    assert "proposal_good-001.html" in index_html
    assert "proposal_good-002.html" in index_html
    # Unsafe entries: NOT linked.
    assert "../bad" not in index_html
    assert "proposal_a/b.html" not in index_html
    # Detail pages: only safe ones written.
    assert (out_dir / "phase7" / "proposal_good-001.html").is_file()
    assert (out_dir / "phase7" / "proposal_good-002.html").is_file()
    assert not (out_dir / "phase7" / "proposal_../bad.html").exists()


def test_watch_snapshot_excludes_default_output_dir(main_module, tmp_path):
    """Same defense for the default output_dir path."""
    ws = tmp_path / "ws"
    (ws / "analysis" / "canonical").mkdir(parents=True)
    (ws / "analysis" / "canonical" / "x.csv").write_text("a\n1\n", encoding="utf-8")
    default_out = ws / "analysis" / "handoff" / "dashboard"
    default_out.mkdir(parents=True)
    (default_out / "index.html").write_text("<p>generated</p>", encoding="utf-8")

    snapshot = main_module._snapshot_mtimes(ws, default_out)
    assert all("dashboard" not in Path(p).parts for p in snapshot.keys())


def test_idempotent_render(tmp_path):
    """Same input → byte-identical HTML (modulo generated_at timestamp,
    which we exclude by hashing only artifact pages)."""
    ws = _make_p0003_workspace(tmp_path)
    _run_cli("--workspace", str(ws), "--quiet")
    a51_first = (
        ws / "analysis" / "handoff" / "dashboard" / "artifacts" / "a51.html"
    ).read_text(encoding="utf-8")
    _run_cli("--workspace", str(ws), "--quiet")
    a51_second = (
        ws / "analysis" / "handoff" / "dashboard" / "artifacts" / "a51.html"
    ).read_text(encoding="utf-8")
    # Strip the generated_at line from both before comparing.
    def _strip_ts(html: str) -> str:
        return "\n".join(
            line for line in html.splitlines()
            if "generated-at" not in line
        )
    assert _strip_ts(a51_first) == _strip_ts(a51_second)
