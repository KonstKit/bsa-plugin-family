#!/usr/bin/env python3
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent / "engine_smoke_matrix.py"
DEFAULT_ACCEPTANCE_TIMEOUT_SECONDS = 120
DEFAULT_TOOL_TIMEOUT_SECONDS = 30


FAKE_PIPELINE_SCRIPT = r'''#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def linked(report_kind, path, status="PASS", schema_version="2"):
    return {
        "report_kind": report_kind,
        "presence": "present",
        "status": status,
        "schema_version": schema_version,
        "path": Path(path).name,
        "hash": sha256(path),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--requested-mode", default="auto")
    parser.add_argument("--logic-only", action="store_true")
    parser.add_argument("--preserve-existing-di", action="store_true")
    parser.add_argument("--full-relayout", action="store_true")
    parser.add_argument("--facts-json")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--helper-command")
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    facts = {}
    if args.facts_json:
        facts = json.loads(Path(args.facts_json).read_text(encoding="utf-8"))

    fixture_id = facts.get("fixture_id") or Path(args.input).stem
    scenario_id = facts.get("scenario_id")

    if args.logic_only:
        eligibility = "logic_only"
        initial_backend = "none"
        final_backend = "none"
    elif args.preserve_existing_di and not args.full_relayout:
        eligibility = "native_preserve"
        initial_backend = "native"
        final_backend = "native"
    elif fixture_id.startswith("neg_"):
        eligibility = "simple_ineligible"
        initial_backend = "native"
        final_backend = "native"
    elif fixture_id == "flaky_fixture" and work_dir.name.endswith("__02"):
        eligibility = "simple_eligible"
        initial_backend = "simple"
        final_backend = "native"
    elif args.requested_mode == "native":
        eligibility = "simple_eligible"
        initial_backend = "native"
        final_backend = "native"
    else:
        eligibility = "simple_eligible"
        initial_backend = "simple"
        final_backend = "simple"

    backend_selection_path = work_dir / "backend_selection.json"
    semantic_report_path = work_dir / "semantic_report.json"
    layout_report_path = work_dir / "layout_report.md"
    human_summary_path = work_dir / "human_summary.md"

    write_json(
        backend_selection_path,
        {
            "initial_backend": initial_backend,
            "final_backend": final_backend,
            "fallback_happened": initial_backend != final_backend,
            "fallback_reason_code": "simple_helper_failed" if initial_backend != final_backend else None,
            "semantic_status": "PASS",
            "layout_status": "PASS",
            "preview_status": "SKIPPED",
            "simple_validation_result": {
                "output_bpmn_path": str(Path(args.input).resolve()),
                "output_bpmn_hash": sha256(args.input),
            },
            "native_result": {
                "output_bpmn_path": str(Path(args.input).resolve()),
                "output_bpmn_hash": sha256(args.input),
            },
        },
    )
    write_json(semantic_report_path, {"backend": final_backend, "status": "PASS", "errors": [], "warnings": []})
    layout_report_path.write_text("# Layout Report\n\nFinal status: PASS\n", encoding="utf-8")
    human_summary_path.write_text("# Human Summary\n\n", encoding="utf-8")

    fallback_happened = initial_backend != final_backend
    manifest = {
        "manifest_schema_version": "2",
        "linked_report_schema_version": "2",
        "build_version": str(facts.get("build_version") or "acceptance-matrix"),
        "skill_version": str(facts.get("skill_version") or "camunda-bpmn-from-context"),
        "runtime_target": str(facts.get("runtime_target") or "acceptance-matrix"),
        "requested_mode": args.requested_mode,
        "logic_only": bool(args.logic_only),
        "preserve_existing_di": bool(args.preserve_existing_di),
        "full_relayout": bool(args.full_relayout),
        "layout_bypass": False,
        "eligibility_class": eligibility,
        "eligibility_reasons": ["fixture_test"],
        "scenario_id": scenario_id,
        "fixture_id": fixture_id,
        "traceability_count": int(facts.get("traceability_count", 0)),
        "assumptions_count": int(facts.get("assumptions_count", 0)),
        "initial_backend": initial_backend,
        "final_backend": final_backend,
        "fallback_happened": fallback_happened,
        "semantic_status": "PASS",
        "layout_status": "PASS",
        "preview_status": "SKIPPED",
        "artifacts": {},
    }
    if fallback_happened:
        manifest["fallback_reason_code"] = "simple_helper_failed"

    manifest["artifacts"] = {
        "backend_selection": linked("backend_selection", backend_selection_path, status="PASS"),
        "semantic_report": linked("semantic_report", semantic_report_path, status="PASS"),
        "layout_report": linked("layout_report", layout_report_path, status="PASS"),
        "preview_report": {
            "report_kind": "preview_report",
            "presence": "skipped",
            "status": "SKIPPED",
            "schema_version": "2",
        },
        "human_summary": linked("human_summary", human_summary_path, status="PASS"),
        "typed_issue_targets": {
            "report_kind": "typed_issue_targets",
            "presence": "not_applicable",
            "status": "SKIPPED",
            "schema_version": "2",
        },
    }

    manifest_path = work_dir / "run_manifest.json"
    write_json(manifest_path, manifest)
    print(json.dumps({"ok": True, "manifest_path": str(manifest_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


FAKE_VALIDATOR_SCRIPT = r'''#!/usr/bin/env python3
import argparse
import sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--fail", action="store_true")
    args = parser.parse_args()
    if args.fail:
        print("forced validation failure", file=sys.stderr)
        return 1
    print("run_manifest validation passed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


FAKE_PREVIEW_BUILDER_SCRIPT = r'''#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text("<html><body>preview</body></html>", encoding="utf-8")
    print(json.dumps({"ok": True, "index_path": str(output_dir / "index.html")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def governance_validator_script(fail=False):
    ok_literal = "True" if not fail else "False"
    return f'''#!/usr/bin/env python3
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-root", required=True)
    parser.add_argument("--gate-profile", default="pr")
    args = parser.parse_args()
    payload = {{
        "ok": {ok_literal},
        "gate_profile": args.gate_profile,
        "docs_root": args.docs_root,
        "checks": {{"release_phases": {ok_literal}}},
        "errors": [] if {ok_literal} else ["forced governance failure"],
    }}
    print(json.dumps(payload, indent=2, sort_keys=True))
    if {repr(fail)}:
        print("forced governance failure", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AcceptanceMatrixTests(unittest.TestCase):
    def _write_file(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _prepare_case(self, include_flaky=False, lineage_mismatch=False, only_originals=False):
        temp_dir = tempfile.TemporaryDirectory()
        root = Path(temp_dir.name)

        fixtures_root = root / "fixtures"
        original_path = fixtures_root / "original" / "01_original.bpmn"
        stripped_path = fixtures_root / "stripped" / "01_stripped.bpmn"
        negative_path = fixtures_root / "negative" / "neg_boundary_event.bpmn"

        self._write_file(original_path, "<definitions id='o1' />\n")
        self._write_file(stripped_path, "<definitions id='s1' />\n")
        self._write_file(negative_path, "<definitions id='n1' />\n")

        fixtures = [
            {
                "fixture_id": "01_original",
                "scenario_id": "ACC-01-ORIGINAL",
                "category": "original",
                "path": "original/01_original.bpmn",
                "strip_to": "stripped/01_stripped.bpmn",
                "requested_mode": "auto",
                "preserve_existing_di": True,
                "expected_eligibility_class": "native_preserve",
                "expected_final_backend": "native",
                "expected_routing_class": "native_preserve",
                "required_profiles": ["pr", "release_candidate"],
            }
        ]
        if not only_originals:
            fixtures.extend(
                [
                    {
                        "fixture_id": "01_stripped",
                        "scenario_id": "ACC-01-STRIPPED",
                        "category": "stripped",
                        "path": "stripped/01_stripped.bpmn",
                        "requested_mode": "auto",
                        "expected_eligibility_class": "simple_eligible",
                        "expected_final_backend": "simple",
                        "required_profiles": ["pr", "release_candidate"],
                    },
                    {
                        "fixture_id": "neg_boundary_event",
                        "scenario_id": "ACC-NEG-BOUNDARY",
                        "category": "negative",
                        "path": "negative/neg_boundary_event.bpmn",
                        "requested_mode": "auto",
                        "facts": {"has_boundary_event": True},
                        "expected_eligibility_class": "simple_ineligible",
                        "expected_final_backend": "native",
                        "required_profiles": ["pr", "release_candidate"],
                    },
                ]
            )

        if include_flaky:
            flaky_path = fixtures_root / "stripped" / "flaky_fixture.bpmn"
            self._write_file(flaky_path, "<definitions id='flaky' />\n")
            fixtures.append(
                {
                    "fixture_id": "flaky_fixture",
                    "scenario_id": "ACC-FLAKY",
                    "category": "stripped",
                    "path": "stripped/flaky_fixture.bpmn",
                    "requested_mode": "auto",
                    "expected_eligibility_class": "simple_eligible",
                    "expected_final_backend": "simple",
                    "required_profiles": ["pr"],
                }
            )

        inventory_path = root / "fixture_inventory.json"
        inventory_path.write_text(json.dumps({"schema_version": "1", "fixtures": fixtures}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        lineage_payload = {
            "schema_version": "1",
            "generator": "scripts/make_stripped_fixture.py",
            "entries": [
                {
                    "fixture_id": "01_original",
                    "generator_version": "1",
                    "invariants_ok": True,
                    "removed_bpmndi_elements": 1,
                    "source_path": "original/01_original.bpmn",
                    "source_sha256": "0" * 64 if lineage_mismatch else sha256(original_path),
                    "stripped_path": "stripped/01_stripped.bpmn",
                    "stripped_sha256": sha256(stripped_path),
                }
            ],
        }
        lineage_path = root / "fixture_lineage.json"
        lineage_path.write_text(json.dumps(lineage_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        pipeline_script = root / "fake_pipeline.py"
        validator_script = root / "fake_validator.py"
        preview_builder_script = root / "fake_preview_builder.py"
        governance_validator_pass_script = root / "fake_governance_pass.py"
        governance_validator_fail_script = root / "fake_governance_fail.py"
        self._write_file(pipeline_script, FAKE_PIPELINE_SCRIPT)
        self._write_file(validator_script, FAKE_VALIDATOR_SCRIPT)
        self._write_file(preview_builder_script, FAKE_PREVIEW_BUILDER_SCRIPT)
        self._write_file(governance_validator_pass_script, governance_validator_script(fail=False))
        self._write_file(governance_validator_fail_script, governance_validator_script(fail=True))

        governance_docs_root = root / "references"
        governance_docs_root.mkdir(parents=True, exist_ok=True)

        return temp_dir, {
            "root": root,
            "fixtures_root": fixtures_root,
            "inventory": inventory_path,
            "lineage": lineage_path,
            "pipeline_script": pipeline_script,
            "validator_script": validator_script,
            "preview_builder_script": preview_builder_script,
            "governance_docs_root": governance_docs_root,
            "governance_validator_pass_script": governance_validator_pass_script,
            "governance_validator_fail_script": governance_validator_fail_script,
        }

    def _run_acceptance(self, cfg, extra_args, timeout_seconds=DEFAULT_ACCEPTANCE_TIMEOUT_SECONDS):
        report_dir = cfg["root"] / "reports"
        command = [
            sys.executable,
            str(SCRIPT_PATH),
            "--mode",
            "acceptance",
            "--gate-profile",
            "pr",
            "--report-dir",
            str(report_dir),
            "--inventory",
            str(cfg["inventory"]),
            "--fixtures-root",
            str(cfg["fixtures_root"]),
            "--lineage",
            str(cfg["lineage"]),
            "--pipeline-script",
            str(cfg["pipeline_script"]),
            "--manifest-validator",
            str(cfg["validator_script"]),
            "--preview-builder-script",
            str(cfg["preview_builder_script"]),
            *extra_args,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(1, int(timeout_seconds)),
            )
        except subprocess.TimeoutExpired as exc:
            completed = subprocess.CompletedProcess(
                args=command,
                returncode=124,
                stdout=(exc.stdout or ""),
                stderr=(str(exc.stderr or "") + "\nacceptance matrix command timed out").strip(),
            )
        summary_path = report_dir / "matrix_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None
        return completed, summary

    def test_acceptance_pr_profile_passes_with_preview_smoke(self):
        temp_dir, cfg = self._prepare_case()
        self.addCleanup(temp_dir.cleanup)

        completed, summary = self._run_acceptance(
            cfg,
            ["--preview-smoke-cmd", "python3 -c \"print('smoke-ok')\""],
        )

        self.assertEqual(completed.returncode, 0)
        self.assertIsNotNone(summary)
        self.assertTrue(summary["all_ok"])
        self.assertTrue(summary["gate_checks"]["required_fixtures_pass"])
        self.assertTrue(summary["gate_checks"]["selector_repeatability_pass"])
        self.assertTrue(summary["gate_checks"]["negative_exclusions_pass"])
        self.assertTrue(summary["gate_checks"]["manifest_schema_pass"])
        self.assertTrue(summary["gate_checks"]["preview_smoke_pass"])
        fixture_ids = [item["fixture_id"] for item in summary["results"]]
        self.assertEqual(fixture_ids, sorted(fixture_ids))
        self.assertIn("01_original", fixture_ids)
        original = next(item for item in summary["results"] if item["fixture_id"] == "01_original")
        self.assertEqual(original["initial_backend"], "native")
        self.assertEqual(original["final_backend"], "native")
        self.assertEqual(original["actual_routing_class"], "native_preserve")
        for item in summary["results"]:
            self.assertIsInstance(item["manifest_id"], str)
            self.assertEqual(len(item["manifest_id"]), 64)
            self.assertIn("initial_backend", item)
            self.assertIn("final_backend", item)
            self.assertIn("fallback_happened", item)

    def test_acceptance_fails_when_layout_report_verdict_mismatches_manifest(self):
        temp_dir, cfg = self._prepare_case()
        self.addCleanup(temp_dir.cleanup)

        mismatched_pipeline = FAKE_PIPELINE_SCRIPT.replace(
            "Final status: PASS",
            "- **Final status:** `FAIL`",
        )
        cfg["pipeline_script"].write_text(mismatched_pipeline, encoding="utf-8")

        completed, summary = self._run_acceptance(
            cfg,
            ["--preview-smoke-cmd", "python3 -c \"print('smoke-ok')\""],
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIsNotNone(summary)
        self.assertFalse(summary["all_ok"])
        self.assertFalse(summary["gate_checks"]["required_fixtures_pass"])
        self.assertTrue(
            any(
                any("layout_report final status mismatch" in error for error in item.get("errors", []))
                for item in summary["results"]
            )
        )

    def test_acceptance_command_timeout_is_reported(self):
        temp_dir, cfg = self._prepare_case()
        self.addCleanup(temp_dir.cleanup)

        cfg["pipeline_script"].write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import time",
                    "time.sleep(5)",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        completed, summary = self._run_acceptance(
            cfg,
            ["--preview-smoke-cmd", "python3 -c \"print('smoke-ok')\""],
            timeout_seconds=1,
        )

        self.assertEqual(completed.returncode, 124)
        self.assertIn("timed out", (completed.stderr or "").lower())
        self.assertIsNone(summary)

    def test_acceptance_pr_profile_real_pipeline_components_pass(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        report_dir = root / "reports"

        skill_root = Path(__file__).resolve().parent.parent
        fixtures_root = skill_root / "scripts" / "fixtures"
        pipeline_script = skill_root / "scripts" / "run_bpmn_pipeline.py"
        validator_script = skill_root / "scripts" / "validate_run_manifest.py"
        preview_builder_script = skill_root / "scripts" / "build_preview_artifacts.py"
        helper_script = skill_root / "node_tooling" / "simple_layout_helper.js"

        original_path = fixtures_root / "original" / "03_original.bpmn"
        stripped_path = fixtures_root / "stripped" / "03_stripped.bpmn"
        negative_path = fixtures_root / "negative" / "neg_boundary_event.bpmn"

        inventory_path = root / "fixture_inventory.json"
        inventory_payload = {
            "schema_version": "1",
            "fixtures": [
                {
                    "fixture_id": "03_original",
                    "scenario_id": "ACC-03-ORIGINAL",
                    "category": "original",
                    "path": "original/03_original.bpmn",
                    "strip_to": "stripped/03_stripped.bpmn",
                    "requested_mode": "auto",
                    "preserve_existing_di": True,
                    "expected_eligibility_class": "native_preserve",
                    "expected_final_backend": "native",
                    "expected_routing_class": "native_preserve",
                    "required_profiles": ["pr", "release_candidate"],
                },
                {
                    "fixture_id": "01_stripped",
                    "scenario_id": "ACC-01-STRIPPED",
                    "category": "stripped",
                    "path": "stripped/01_stripped.bpmn",
                    "requested_mode": "auto",
                    "expected_eligibility_class": "simple_eligible",
                    "expected_final_backend": "simple",
                    "expected_routing_class": "simple_direct",
                    "required_profiles": ["pr", "release_candidate"],
                },
                {
                    "fixture_id": "neg_boundary_event",
                    "scenario_id": "ACC-NEG-BOUNDARY",
                    "category": "negative",
                    "path": "negative/neg_boundary_event.bpmn",
                    "requested_mode": "auto",
                    "expected_eligibility_class": "simple_ineligible",
                    "expected_final_backend": "native",
                    "required_profiles": ["pr", "release_candidate"],
                },
            ],
        }
        inventory_path.write_text(json.dumps(inventory_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        lineage_path = root / "fixture_lineage.json"
        lineage_payload = {
            "schema_version": "1",
            "generator": "scripts/make_stripped_fixture.py",
            "entries": [
                {
                    "fixture_id": "03_original",
                    "generator_version": "1",
                    "invariants_ok": True,
                    "removed_bpmndi_elements": 1,
                    "source_path": "original/03_original.bpmn",
                    "source_sha256": sha256(original_path),
                    "stripped_path": "stripped/03_stripped.bpmn",
                    "stripped_sha256": sha256(stripped_path),
                }
            ],
        }
        lineage_path.write_text(json.dumps(lineage_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        command = [
            sys.executable,
            str(SCRIPT_PATH),
            "--mode",
            "acceptance",
            "--gate-profile",
            "pr",
            "--report-dir",
            str(report_dir),
            "--inventory",
            str(inventory_path),
            "--fixtures-root",
            str(fixtures_root),
            "--lineage",
            str(lineage_path),
            "--pipeline-script",
            str(pipeline_script),
            "--manifest-validator",
            str(validator_script),
            "--preview-builder-script",
            str(preview_builder_script),
            "--helper-command",
            f"node {helper_script}",
            "--preview-smoke-cmd",
            "python3 -c \"print('smoke-ok')\"",
            "--timeout-seconds",
            "20",
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=DEFAULT_ACCEPTANCE_TIMEOUT_SECONDS,
        )
        summary = json.loads((report_dir / "matrix_summary.json").read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertTrue(summary["all_ok"])
        self.assertTrue(summary["gate_checks"]["required_fixtures_pass"])
        self.assertTrue(summary["gate_checks"]["negative_exclusions_pass"])
        self.assertTrue(summary["preview_smoke"]["required"])
        self.assertTrue(summary["gate_checks"]["preview_smoke_pass"])
        result_ids = [item["fixture_id"] for item in summary["results"]]
        self.assertEqual(result_ids, ["01_stripped", "03_original", "neg_boundary_event"])
        self.assertTrue(any(item["actual_routing_class"] == "native_preserve" for item in summary["results"]))

    def test_governance_validator_passes_for_required_docs(self):
        temp_dir, cfg = self._prepare_case()
        self.addCleanup(temp_dir.cleanup)

        docs_root = cfg["governance_docs_root"]
        (docs_root / "release-phases.md").write_text(
            "\n".join(
                [
                    "# Release Phases",
                    "",
                    "## Phase 0-4 Critical Path",
                    "- plan_14",
                    "- plan_15",
                    "",
                    "## Phase 5 Deferred Optional Enhancements",
                    "- plan_09 deferred optional",
                    "",
                    "## Unified Release Gate",
                    "- acceptance matrix",
                    "- manifest schema",
                    "- preview smoke",
                    "- governance docs validation",
                    "- preview_report",
                    "- typed_issue_targets",
                    "- usable original fixtures are runtime-tested in native-preserve path",
                    "- partial-DI originals route through simple/direct or fallback paths per selector output",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (docs_root / "fr-coverage-map.md").write_text(
            "\n".join(
                [
                    "# FR Coverage Map",
                    "",
                    "## Coverage Table",
                    "",
                    "| FR | Capability | Plan | Primary artifact(s) | Acceptance test(s) |",
                    "|---|---|---|---|---|",
                    "| FR-01 | c1 | plan_02 | a1 | t1 |",
                    "| FR-02 | c2 | plan_04 | a2 | t2 |",
                    "| FR-03 | c3 | plan_07 | a3 | t3 |",
                    "| FR-04 | c4 | plan_08 | a4 | t4 |",
                    "| FR-05 | c5 | plan_13 | a5 | t5 |",
                    "| FR-06 | c6 | plan_11 | a6 | t6 |",
                    "| FR-07 | c7 | plan_12 | a7 | t7 |",
                    "| FR-08 | c8 | plan_16 | a8 | t8 |",
                    "| FR-09 | c9 | plan_15 | a9 | t9 |",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (docs_root / "support-matrix.md").write_text(
            "\n".join(
                [
                    "# BPMN Support Matrix",
                    "",
                    "## Orchestration Inputs And Hard Exclusions",
                    "- requested_mode",
                    "- logic_only",
                    "- preserve_existing_di",
                    "- full_relayout",
                    "- hard exclusions",
                    "- preserve-only",
                    "- usable DI",
                    "- partial DI",
                    "- native-preserve by default for usable existing DI inputs when full_relayout=false",
                    "- partial DI does not imply preserve defaults",
                    "- simple success requires post-process edge-DI completeness checks before final PASS",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (docs_root / "engine-smoke-hooks.md").write_text(
            "\n".join(
                [
                    "# Engine Smoke Fixtures and CI Hook Templates (C7 / C8)",
                    "",
                    "## Unified Release Gate",
                    "python3 scripts/engine_smoke_matrix.py --mode acceptance --gate-profile release_candidate",
                    "governance preview smoke matrix_summary.json",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (docs_root.parent / "SKILL.md").write_text(
            "# Skill\n\nreferences/release-phases.md references/fr-coverage-map.md references/support-matrix.md\n",
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "validate_governance_docs.py"),
                "--docs-root",
                str(docs_root),
                "--gate-profile",
                "release_candidate",
            ],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TOOL_TIMEOUT_SECONDS,
        )

        self.assertEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertIn("release_phases", payload["checks"])

    def test_governance_validator_rejects_marker_only_docs(self):
        temp_dir, cfg = self._prepare_case()
        self.addCleanup(temp_dir.cleanup)

        docs_root = cfg["governance_docs_root"]
        (docs_root / "release-phases.md").write_text(
            "# Release Phases\n\nusable original fixtures are runtime-tested partial-DI originals plan_09 deferred optional plan_14 plan_15 acceptance matrix manifest schema preview smoke governance docs validation\n",
            encoding="utf-8",
        )
        (docs_root / "fr-coverage-map.md").write_text(
            "# FR Coverage Map\n\nfr-01 fr-02 fr-03 fr-04 fr-05 fr-06 fr-07 fr-08 fr-09 plan artifact acceptance test\n",
            encoding="utf-8",
        )
        (docs_root / "support-matrix.md").write_text(
            "# BPMN Support Matrix\n\nrequested_mode logic_only preserve_existing_di full_relayout usable DI partial DI hard exclusions preserve-only native-preserve by default for usable existing DI partial DI does not imply preserve defaults simple success requires post-process\n",
            encoding="utf-8",
        )
        (docs_root / "engine-smoke-hooks.md").write_text(
            "# Engine Smoke Fixtures and CI Hook Templates (C7 / C8)\n\ngovernance release_candidate preview smoke matrix summary\n",
            encoding="utf-8",
        )
        (docs_root.parent / "SKILL.md").write_text(
            "# Skill\n\nreferences/release-phases.md references/fr-coverage-map.md references/support-matrix.md\n",
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "validate_governance_docs.py"),
                "--docs-root",
                str(docs_root),
                "--gate-profile",
                "release_candidate",
            ],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TOOL_TIMEOUT_SECONDS,
        )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("missing required markers", "\n".join(payload.get("errors", [])))

    def test_acceptance_release_candidate_requires_governance_pass(self):
        temp_dir, cfg = self._prepare_case()
        self.addCleanup(temp_dir.cleanup)

        completed, summary = self._run_acceptance(
            cfg,
            [
                "--gate-profile",
                "release_candidate",
                "--preview-smoke-cmd",
                "python3 -c \"print('smoke-ok')\"",
                "--governance-validator-script",
                str(cfg["governance_validator_pass_script"]),
                "--governance-docs-root",
                str(cfg["governance_docs_root"]),
            ],
        )

        self.assertEqual(completed.returncode, 0)
        self.assertIsNotNone(summary)
        self.assertTrue(summary["governance"]["required"])
        self.assertTrue(summary["gate_checks"]["governance_pass"])
        self.assertTrue(summary["release_gate_pass"])
        self.assertTrue(summary["all_ok"])

    def test_acceptance_release_candidate_fails_on_governance_failure(self):
        temp_dir, cfg = self._prepare_case()
        self.addCleanup(temp_dir.cleanup)

        completed, summary = self._run_acceptance(
            cfg,
            [
                "--gate-profile",
                "release_candidate",
                "--preview-smoke-cmd",
                "python3 -c \"print('smoke-ok')\"",
                "--governance-validator-script",
                str(cfg["governance_validator_fail_script"]),
                "--governance-docs-root",
                str(cfg["governance_docs_root"]),
            ],
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIsNotNone(summary)
        self.assertTrue(summary["governance"]["required"])
        self.assertFalse(summary["gate_checks"]["governance_pass"])
        self.assertFalse(summary["release_gate_pass"])
        self.assertFalse(summary["all_ok"])

    def test_acceptance_pr_records_governance_failure_without_blocking(self):
        temp_dir, cfg = self._prepare_case()
        self.addCleanup(temp_dir.cleanup)

        completed, summary = self._run_acceptance(
            cfg,
            [
                "--preview-smoke-cmd",
                "python3 -c \"print('smoke-ok')\"",
                "--governance-validator-script",
                str(cfg["governance_validator_fail_script"]),
                "--governance-docs-root",
                str(cfg["governance_docs_root"]),
            ],
        )

        self.assertEqual(completed.returncode, 0)
        self.assertIsNotNone(summary)
        self.assertFalse(summary["governance"]["required"])
        self.assertFalse(summary["gate_checks"]["governance_pass"])
        self.assertTrue(summary["all_ok"])

    def test_acceptance_blocks_when_lineage_mismatch_detected(self):
        temp_dir, cfg = self._prepare_case(lineage_mismatch=True)
        self.addCleanup(temp_dir.cleanup)

        completed, summary = self._run_acceptance(
            cfg,
            ["--preview-smoke-cmd", "python3 -c \"print('smoke-ok')\""],
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIsNotNone(summary)
        self.assertFalse(summary["lineage"]["ok"])
        self.assertEqual(summary["results"], [])
        self.assertFalse(summary["all_ok"])

    def test_acceptance_pr_requires_preview_smoke_command(self):
        temp_dir, cfg = self._prepare_case()
        self.addCleanup(temp_dir.cleanup)

        completed, summary = self._run_acceptance(cfg, [])

        self.assertEqual(completed.returncode, 1)
        self.assertIsNotNone(summary)
        self.assertTrue(summary["preview_smoke"]["required"])
        self.assertFalse(summary["preview_smoke"]["ok"])
        self.assertFalse(summary["gate_checks"]["preview_smoke_pass"])

    def test_acceptance_release_candidate_requires_preview_smoke_command(self):
        temp_dir, cfg = self._prepare_case()
        self.addCleanup(temp_dir.cleanup)

        completed, summary = self._run_acceptance(
            cfg,
            ["--gate-profile", "release_candidate"],
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIsNotNone(summary)
        self.assertTrue(summary["preview_smoke"]["required"])
        self.assertFalse(summary["preview_smoke"]["ok"])
        self.assertFalse(summary["gate_checks"]["preview_smoke_pass"])

    def test_acceptance_reports_selector_repeatability_failure(self):
        temp_dir, cfg = self._prepare_case(include_flaky=True)
        self.addCleanup(temp_dir.cleanup)

        completed, summary = self._run_acceptance(
            cfg,
            ["--preview-smoke-cmd", "python3 -c \"print('smoke-ok')\""],
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIsNotNone(summary)
        self.assertFalse(summary["gate_checks"]["selector_repeatability_pass"])
        flaky = next(item for item in summary["results"] if item["fixture_id"] == "flaky_fixture")
        self.assertFalse(flaky["repeatability_ok"])
        self.assertFalse(flaky["ok"])

    def test_acceptance_forced_selector_repeatability_hook_fails_gate(self):
        temp_dir, cfg = self._prepare_case()
        self.addCleanup(temp_dir.cleanup)

        completed, summary = self._run_acceptance(
            cfg,
            [
                "--preview-smoke-cmd",
                "python3 -c \"print('smoke-ok')\"",
                "--selector-repeatability",
                "FAIL",
            ],
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIsNotNone(summary)
        self.assertFalse(summary["gate_checks"]["selector_repeatability_pass"])
        self.assertIn("selector repeatability forced", "\n".join(summary.get("errors", [])))

    def test_acceptance_fails_when_no_negative_fixtures_selected(self):
        temp_dir, cfg = self._prepare_case()
        self.addCleanup(temp_dir.cleanup)
        inventory = json.loads(cfg["inventory"].read_text(encoding="utf-8"))
        inventory["fixtures"] = [
            item
            for item in inventory["fixtures"]
            if item.get("category") != "negative"
        ]
        cfg["inventory"].write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        completed, summary = self._run_acceptance(
            cfg,
            ["--preview-smoke-cmd", "python3 -c \"print('smoke-ok')\""],
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIsNotNone(summary)
        self.assertFalse(summary["gate_checks"]["negative_exclusions_pass"])

    def test_acceptance_fails_when_no_fixtures_selected_for_profile(self):
        temp_dir, cfg = self._prepare_case(only_originals=True)
        self.addCleanup(temp_dir.cleanup)

        completed, summary = self._run_acceptance(
            cfg,
            ["--gate-profile", "nightly"],
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["results"], [])
        self.assertFalse(summary["gate_checks"]["required_fixtures_pass"])
        self.assertIn("no acceptance fixtures selected", "\n".join(summary.get("errors", [])))

    def test_acceptance_writes_summary_on_invalid_inventory_json(self):
        temp_dir, cfg = self._prepare_case()
        self.addCleanup(temp_dir.cleanup)
        cfg["inventory"].write_text("{ invalid json", encoding="utf-8")

        completed, summary = self._run_acceptance(
            cfg,
            ["--gate-profile", "pr"],
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIsNotNone(summary)
        self.assertFalse(summary["all_ok"])
        self.assertIn("invalid JSON", "\n".join(summary.get("errors", [])))
        self.assertIn("governance", summary)
        self.assertIn("gate_requirements", summary)
        self.assertIn("governance_pass", summary["gate_checks"])
        self.assertFalse(summary["gate_checks"]["governance_pass"])


if __name__ == "__main__":
    unittest.main()
