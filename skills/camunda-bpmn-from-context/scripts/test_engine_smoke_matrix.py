#!/usr/bin/env python3
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent / "engine_smoke_matrix.py"
SPEC = importlib.util.spec_from_file_location("engine_smoke_matrix", SCRIPT_PATH)
MATRIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATRIX)


def python_ok_command(message):
    return f"{sys.executable} -c \"print('{message}')\""


def python_fail_command(message):
    return f"{sys.executable} -c \"import sys; print('{message}'); sys.exit(1)\""


class EngineSmokeMatrixTests(unittest.TestCase):
    def run_matrix(self, extra_args):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_dir = Path(temp_dir) / "reports"
            command = [
                sys.executable,
                str(SCRIPT_PATH),
                "--report-dir",
                str(report_dir),
                *extra_args,
            ]
            completed = subprocess.run(command, capture_output=True, text=True)
            summary_path = report_dir / "matrix_summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None
            return completed, summary

    def test_happy_suite_passes_with_successful_commands(self):
        completed, summary = self.run_matrix(
            [
                "--profiles",
                "8",
                "--suite",
                "happy",
                "--import-cmd",
                python_ok_command("import-ok"),
                "--deploy-cmd",
                python_ok_command("deploy-ok"),
                "--process-test-cmd",
                python_ok_command("process-ok"),
            ]
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIsNotNone(summary)
        self.assertTrue(summary["all_ok"])
        self.assertEqual(summary["results"][0]["actual_status"], "PASS")

    def test_negative_suite_passes_when_not_verified_is_expected(self):
        completed, summary = self.run_matrix(
            [
                "--profiles",
                "7",
                "--suite",
                "negative",
                "--import-cmd",
                python_ok_command("import-ok"),
                "--process-test-cmd",
                python_ok_command("process-ok"),
            ]
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIsNotNone(summary)
        self.assertTrue(summary["all_ok"])
        self.assertEqual(summary["results"][0]["actual_status"], "NOT_VERIFIED")

    def test_matrix_fails_on_status_mismatch(self):
        completed, summary = self.run_matrix(
            [
                "--profiles",
                "8",
                "--suite",
                "happy",
                "--import-cmd",
                python_ok_command("import-ok"),
                "--deploy-cmd",
                python_fail_command("deploy-fail"),
                "--process-test-cmd",
                python_ok_command("process-ok"),
            ]
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIsNotNone(summary)
        self.assertFalse(summary["all_ok"])

    def test_pr_profile_includes_original_native_preserve_fixtures(self):
        inventory = {
            "fixtures": [
                {
                    "fixture_id": "01_original",
                    "category": "original",
                    "required_profiles": ["pr", "release_candidate"],
                    "path": "original/01_original.bpmn",
                },
                {
                    "fixture_id": "01_stripped",
                    "category": "stripped",
                    "required_profiles": ["pr", "release_candidate"],
                    "path": "stripped/01_stripped.bpmn",
                },
            ]
        }
        selected = MATRIX._selected_acceptance_fixtures(inventory, MATRIX.ACCEPTANCE_PROFILE_PR)
        self.assertEqual([item["fixture_id"] for item in selected], ["01_original", "01_stripped"])

    def test_original_fixture_runtime_class_is_native_preserve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fixture_path = root / "original_01.bpmn"
            fixture_path.write_text("<definitions id='f1' />\n", encoding="utf-8")

            pipeline_script = root / "pipeline.py"
            pipeline_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import argparse, hashlib, json",
                        "from pathlib import Path",
                        "def sha256(path):",
                        "  h=hashlib.sha256(); h.update(Path(path).read_bytes()); return h.hexdigest()",
                        "def w(path,payload):",
                        "  Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True)+'\\n', encoding='utf-8')",
                        "parser=argparse.ArgumentParser()",
                        "parser.add_argument('input')",
                        "parser.add_argument('--work-dir', required=True)",
                        "parser.add_argument('--requested-mode', default='auto')",
                        "parser.add_argument('--preserve-existing-di', action='store_true')",
                        "parser.add_argument('--facts-json')",
                        "parser.add_argument('--timeout-seconds', type=int, default=30)",
                        "args=parser.parse_args()",
                        "work=Path(args.work_dir); work.mkdir(parents=True, exist_ok=True)",
                        "backend=work/'backend_selection.json'",
                        "semantic=work/'semantic_report.json'",
                        "layout=work/'layout_report.md'",
                        "human=work/'human_summary.md'",
                        "w(backend, {'initial_backend':'native','final_backend':'native','fallback_happened':False,'semantic_status':'PASS','layout_status':'PASS','preview_status':'SKIPPED'})",
                        "w(semantic, {'status':'PASS','errors':[],'warnings':[]})",
                        "layout.write_text('# Layout Report\\n\\nFinal status: PASS\\n', encoding='utf-8')",
                        "human.write_text('# Summary\\n', encoding='utf-8')",
                        "manifest={",
                        "  'manifest_schema_version':'2','linked_report_schema_version':'2','build_version':'t','skill_version':'s','runtime_target':'r',",
                        "  'requested_mode':args.requested_mode,'logic_only':False,'preserve_existing_di':bool(args.preserve_existing_di),'full_relayout':False,",
                        "  'layout_bypass':False,'eligibility_class':'native_preserve','eligibility_reasons':['preserve_existing_di_forces_native'],",
                        "  'scenario_id':'ACC-01-ORIGINAL','fixture_id':'01_original','traceability_count':0,'assumptions_count':0,",
                        "  'initial_backend':'native','final_backend':'native','fallback_happened':False,'semantic_status':'PASS','layout_status':'PASS','preview_status':'SKIPPED',",
                        "  'artifacts':{",
                        "    'backend_selection':{'report_kind':'backend_selection','presence':'present','status':'PASS','schema_version':'2','path':'backend_selection.json','hash':sha256(backend)},",
                        "    'semantic_report':{'report_kind':'semantic_report','presence':'present','status':'PASS','schema_version':'2','path':'semantic_report.json','hash':sha256(semantic)},",
                        "    'layout_report':{'report_kind':'layout_report','presence':'present','status':'PASS','schema_version':'2','path':'layout_report.md','hash':sha256(layout)},",
                        "    'preview_report':{'report_kind':'preview_report','presence':'skipped','status':'SKIPPED','schema_version':'2'},",
                        "    'human_summary':{'report_kind':'human_summary','presence':'present','status':'PASS','schema_version':'2','path':'human_summary.md','hash':sha256(human)},",
                        "    'typed_issue_targets':{'report_kind':'typed_issue_targets','presence':'not_applicable','status':'SKIPPED','schema_version':'2'}",
                        "  }",
                        "}",
                        "w(work/'run_manifest.json', manifest)",
                        "print('{\"ok\": true}')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            validator_script = root / "validator.py"
            validator_script.write_text(
                "#!/usr/bin/env python3\nimport sys\nprint('ok')\nsys.exit(0)\n",
                encoding="utf-8",
            )
            report_dir = root / "reports"
            fixture = {
                "fixture_id": "01_original",
                "scenario_id": "ACC-01-ORIGINAL",
                "category": "original",
                "path": fixture_path.name,
                "requested_mode": "auto",
                "preserve_existing_di": True,
                "expected_eligibility_class": "native_preserve",
                "expected_final_backend": "native",
                "expected_routing_class": "native_preserve",
            }
            args = type(
                "Args",
                (),
                {
                    "pipeline_script": str(pipeline_script),
                    "manifest_validator": str(validator_script),
                    "timeout_seconds": 5,
                    "helper_command": None,
                    "repeatability_runs": 2,
                    "build_version": "test",
                    "skill_version": "test",
                    "runtime_target": "test",
                },
            )()
            result = MATRIX._run_pipeline_fixture(args, fixture, fixture_path, report_dir)

        self.assertTrue(result["ok"])
        self.assertEqual(result["actual_routing_class"], "native_preserve")

    def test_partial_original_fixture_routes_as_simple_direct(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fixture_path = root / "original_04a.bpmn"
            fixture_path.write_text("<definitions id='f4a' />\n", encoding="utf-8")

            pipeline_script = root / "pipeline.py"
            pipeline_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import argparse, hashlib, json",
                        "from pathlib import Path",
                        "def sha256(path):",
                        "  h=hashlib.sha256(); h.update(Path(path).read_bytes()); return h.hexdigest()",
                        "def w(path,payload):",
                        "  Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True)+'\\n', encoding='utf-8')",
                        "parser=argparse.ArgumentParser()",
                        "parser.add_argument('input')",
                        "parser.add_argument('--work-dir', required=True)",
                        "parser.add_argument('--requested-mode', default='auto')",
                        "parser.add_argument('--preserve-existing-di', action='store_true')",
                        "parser.add_argument('--facts-json')",
                        "parser.add_argument('--timeout-seconds', type=int, default=30)",
                        "args=parser.parse_args()",
                        "work=Path(args.work_dir); work.mkdir(parents=True, exist_ok=True)",
                        "backend=work/'backend_selection.json'",
                        "semantic=work/'semantic_report.json'",
                        "layout=work/'layout_report.md'",
                        "human=work/'human_summary.md'",
                        "w(backend, {'initial_backend':'simple','final_backend':'simple','fallback_happened':False,'semantic_status':'PASS','layout_status':'PASS','preview_status':'SKIPPED'})",
                        "w(semantic, {'backend':'simple','status':'PASS','errors':[],'warnings':[]})",
                        "layout.write_text('# Layout Report\\n\\nFinal status: PASS\\n', encoding='utf-8')",
                        "human.write_text('# Summary\\n', encoding='utf-8')",
                        "manifest={",
                        "  'manifest_schema_version':'2','linked_report_schema_version':'2','build_version':'t','skill_version':'s','runtime_target':'r',",
                        "  'requested_mode':args.requested_mode,'logic_only':False,'preserve_existing_di':bool(args.preserve_existing_di),'full_relayout':False,",
                        "  'layout_bypass':False,'eligibility_class':'simple_eligible','eligibility_reasons':['partial_di_does_not_force_preserve'],",
                        "  'scenario_id':'ACC-04A-ORIGINAL','fixture_id':'04a_original','traceability_count':0,'assumptions_count':0,",
                        "  'initial_backend':'simple','final_backend':'simple','fallback_happened':False,'semantic_status':'PASS','layout_status':'PASS','preview_status':'SKIPPED',",
                        "  'artifacts':{",
                        "    'backend_selection':{'report_kind':'backend_selection','presence':'present','status':'PASS','schema_version':'2','path':'backend_selection.json','hash':sha256(backend)},",
                        "    'semantic_report':{'report_kind':'semantic_report','presence':'present','status':'PASS','schema_version':'2','path':'semantic_report.json','hash':sha256(semantic)},",
                        "    'layout_report':{'report_kind':'layout_report','presence':'present','status':'PASS','schema_version':'2','path':'layout_report.md','hash':sha256(layout)},",
                        "    'preview_report':{'report_kind':'preview_report','presence':'skipped','status':'SKIPPED','schema_version':'2'},",
                        "    'human_summary':{'report_kind':'human_summary','presence':'present','status':'PASS','schema_version':'2','path':'human_summary.md','hash':sha256(human)},",
                        "    'typed_issue_targets':{'report_kind':'typed_issue_targets','presence':'not_applicable','status':'SKIPPED','schema_version':'2'}",
                        "  }",
                        "}",
                        "w(work/'run_manifest.json', manifest)",
                        "print('{\"ok\": true}')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            validator_script = root / "validator.py"
            validator_script.write_text(
                "#!/usr/bin/env python3\nimport sys\nprint('ok')\nsys.exit(0)\n",
                encoding="utf-8",
            )
            report_dir = root / "reports"
            fixture = {
                "fixture_id": "04a_original",
                "scenario_id": "ACC-04A-ORIGINAL",
                "category": "original",
                "path": fixture_path.name,
                "requested_mode": "auto",
                "preserve_existing_di": False,
                "expected_eligibility_class": "simple_eligible",
                "expected_final_backend": "simple",
                "expected_routing_class": "simple_direct",
            }
            args = type(
                "Args",
                (),
                {
                    "pipeline_script": str(pipeline_script),
                    "manifest_validator": str(validator_script),
                    "timeout_seconds": 5,
                    "helper_command": None,
                    "repeatability_runs": 2,
                    "build_version": "test",
                    "skill_version": "test",
                    "runtime_target": "test",
                },
            )()
            result = MATRIX._run_pipeline_fixture(args, fixture, fixture_path, report_dir)

        self.assertTrue(result["ok"])
        self.assertEqual(result["actual_routing_class"], "simple_direct")

    def test_fixture_fails_when_layout_report_final_status_disagrees_with_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fixture_path = root / "fixture.bpmn"
            fixture_path.write_text("<definitions id='f1' />\n", encoding="utf-8")

            pipeline_script = root / "pipeline.py"
            pipeline_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import argparse, hashlib, json",
                        "from pathlib import Path",
                        "def sha256(path):",
                        "  h=hashlib.sha256(); h.update(Path(path).read_bytes()); return h.hexdigest()",
                        "def w(path,payload):",
                        "  Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True)+'\\n', encoding='utf-8')",
                        "parser=argparse.ArgumentParser()",
                        "parser.add_argument('input')",
                        "parser.add_argument('--work-dir', required=True)",
                        "parser.add_argument('--requested-mode', default='auto')",
                        "parser.add_argument('--preserve-existing-di', action='store_true')",
                        "parser.add_argument('--facts-json')",
                        "parser.add_argument('--timeout-seconds', type=int, default=30)",
                        "args=parser.parse_args()",
                        "work=Path(args.work_dir); work.mkdir(parents=True, exist_ok=True)",
                        "backend=work/'backend_selection.json'",
                        "semantic=work/'semantic_report.json'",
                        "layout=work/'layout_report.md'",
                        "human=work/'human_summary.md'",
                        "w(backend, {'initial_backend':'simple','final_backend':'simple','fallback_happened':False,'semantic_status':'PASS','layout_status':'PASS','preview_status':'SKIPPED'})",
                        "w(semantic, {'backend':'simple','status':'PASS','errors':[],'warnings':[]})",
                        "layout.write_text('# Layout Report\\n\\n- **Final status:** `FAIL`\\n', encoding='utf-8')",
                        "human.write_text('# Summary\\n', encoding='utf-8')",
                        "manifest={",
                        "  'manifest_schema_version':'2','linked_report_schema_version':'2','build_version':'t','skill_version':'s','runtime_target':'r',",
                        "  'requested_mode':args.requested_mode,'logic_only':False,'preserve_existing_di':bool(args.preserve_existing_di),'full_relayout':False,",
                        "  'layout_bypass':False,'eligibility_class':'simple_eligible','eligibility_reasons':['test'],",
                        "  'scenario_id':'ACC-MISMATCH','fixture_id':'fixture_mismatch','traceability_count':0,'assumptions_count':0,",
                        "  'initial_backend':'simple','final_backend':'simple','fallback_happened':False,'semantic_status':'PASS','layout_status':'PASS','preview_status':'SKIPPED',",
                        "  'artifacts':{",
                        "    'backend_selection':{'report_kind':'backend_selection','presence':'present','status':'PASS','schema_version':'2','path':'backend_selection.json','hash':sha256(backend)},",
                        "    'semantic_report':{'report_kind':'semantic_report','presence':'present','status':'PASS','schema_version':'2','path':'semantic_report.json','hash':sha256(semantic)},",
                        "    'layout_report':{'report_kind':'layout_report','presence':'present','status':'PASS','schema_version':'2','path':'layout_report.md','hash':sha256(layout)},",
                        "    'preview_report':{'report_kind':'preview_report','presence':'skipped','status':'SKIPPED','schema_version':'2'},",
                        "    'human_summary':{'report_kind':'human_summary','presence':'present','status':'PASS','schema_version':'2','path':'human_summary.md','hash':sha256(human)},",
                        "    'typed_issue_targets':{'report_kind':'typed_issue_targets','presence':'not_applicable','status':'SKIPPED','schema_version':'2'}",
                        "  }",
                        "}",
                        "w(work/'run_manifest.json', manifest)",
                        "print('{\"ok\": true}')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            validator_script = root / "validator.py"
            validator_script.write_text(
                "#!/usr/bin/env python3\nimport sys\nprint('ok')\nsys.exit(0)\n",
                encoding="utf-8",
            )
            report_dir = root / "reports"
            fixture = {
                "fixture_id": "fixture_mismatch",
                "scenario_id": "ACC-MISMATCH",
                "category": "stripped",
                "path": fixture_path.name,
                "requested_mode": "auto",
                "preserve_existing_di": False,
                "expected_eligibility_class": "simple_eligible",
                "expected_final_backend": "simple",
                "expected_routing_class": "simple_direct",
            }
            args = type(
                "Args",
                (),
                {
                    "pipeline_script": str(pipeline_script),
                    "manifest_validator": str(validator_script),
                    "timeout_seconds": 5,
                    "helper_command": None,
                    "repeatability_runs": 2,
                    "build_version": "test",
                    "skill_version": "test",
                    "runtime_target": "test",
                },
            )()
            result = MATRIX._run_pipeline_fixture(args, fixture, fixture_path, report_dir)

        self.assertFalse(result["ok"])
        self.assertEqual(result["layout_status"], "PASS")
        self.assertEqual(result["layout_report_final_status"], "FAIL")
        self.assertIn(
            "layout_report final status mismatch expected=PASS actual=FAIL",
            result["errors"],
        )

    def test_fixture_passes_when_inventory_expects_fail_statuses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fixture_path = root / "fixture_fail_expected.bpmn"
            fixture_path.write_text("<definitions id='f1' />\n", encoding="utf-8")

            pipeline_script = root / "pipeline.py"
            pipeline_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import argparse, hashlib, json",
                        "from pathlib import Path",
                        "def sha256(path):",
                        "  h=hashlib.sha256(); h.update(Path(path).read_bytes()); return h.hexdigest()",
                        "def w(path,payload):",
                        "  Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True)+'\\n', encoding='utf-8')",
                        "parser=argparse.ArgumentParser()",
                        "parser.add_argument('input')",
                        "parser.add_argument('--work-dir', required=True)",
                        "parser.add_argument('--requested-mode', default='auto')",
                        "parser.add_argument('--preserve-existing-di', action='store_true')",
                        "parser.add_argument('--facts-json')",
                        "parser.add_argument('--timeout-seconds', type=int, default=30)",
                        "args=parser.parse_args()",
                        "work=Path(args.work_dir); work.mkdir(parents=True, exist_ok=True)",
                        "backend=work/'backend_selection.json'",
                        "semantic=work/'semantic_report.json'",
                        "layout=work/'layout_report.md'",
                        "human=work/'human_summary.md'",
                        "w(backend, {'initial_backend':'native','final_backend':'native','fallback_happened':False,'semantic_status':'FAIL','layout_status':'FAIL','preview_status':'SKIPPED'})",
                        "w(semantic, {'backend':'native','status':'FAIL','errors':['x'],'warnings':[]})",
                        "layout.write_text('# Layout Report\\n\\nFinal status: FAIL\\n', encoding='utf-8')",
                        "human.write_text('# Summary\\n', encoding='utf-8')",
                        "manifest={",
                        "  'manifest_schema_version':'2','linked_report_schema_version':'2','build_version':'t','skill_version':'s','runtime_target':'r',",
                        "  'requested_mode':args.requested_mode,'logic_only':False,'preserve_existing_di':bool(args.preserve_existing_di),'full_relayout':False,",
                        "  'layout_bypass':False,'eligibility_class':'native_preserve','eligibility_reasons':['test'],",
                        "  'scenario_id':'ACC-EXPECTED-FAIL','fixture_id':'fixture_fail_expected','traceability_count':0,'assumptions_count':0,",
                        "  'initial_backend':'native','final_backend':'native','fallback_happened':False,'semantic_status':'FAIL','layout_status':'FAIL','preview_status':'SKIPPED',",
                        "  'artifacts':{",
                        "    'backend_selection':{'report_kind':'backend_selection','presence':'present','status':'PASS','schema_version':'2','path':'backend_selection.json','hash':sha256(backend)},",
                        "    'semantic_report':{'report_kind':'semantic_report','presence':'present','status':'FAIL','schema_version':'2','path':'semantic_report.json','hash':sha256(semantic)},",
                        "    'layout_report':{'report_kind':'layout_report','presence':'present','status':'FAIL','schema_version':'2','path':'layout_report.md','hash':sha256(layout)},",
                        "    'preview_report':{'report_kind':'preview_report','presence':'skipped','status':'SKIPPED','schema_version':'2'},",
                        "    'human_summary':{'report_kind':'human_summary','presence':'present','status':'PASS','schema_version':'2','path':'human_summary.md','hash':sha256(human)},",
                        "    'typed_issue_targets':{'report_kind':'typed_issue_targets','presence':'not_applicable','status':'SKIPPED','schema_version':'2'}",
                        "  }",
                        "}",
                        "w(work/'run_manifest.json', manifest)",
                        "print('{\"ok\": true}')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            validator_script = root / "validator.py"
            validator_script.write_text(
                "#!/usr/bin/env python3\nimport sys\nprint('ok')\nsys.exit(0)\n",
                encoding="utf-8",
            )
            report_dir = root / "reports"
            fixture = {
                "fixture_id": "fixture_fail_expected",
                "scenario_id": "ACC-EXPECTED-FAIL",
                "category": "original",
                "path": fixture_path.name,
                "requested_mode": "auto",
                "preserve_existing_di": True,
                "expected_eligibility_class": "native_preserve",
                "expected_final_backend": "native",
                "expected_routing_class": "native_preserve",
                "expected_layout_status": "FAIL",
                "expected_semantic_status": "FAIL",
            }
            args = type(
                "Args",
                (),
                {
                    "pipeline_script": str(pipeline_script),
                    "manifest_validator": str(validator_script),
                    "timeout_seconds": 5,
                    "helper_command": None,
                    "repeatability_runs": 2,
                    "build_version": "test",
                    "skill_version": "test",
                    "runtime_target": "test",
                },
            )()
            result = MATRIX._run_pipeline_fixture(args, fixture, fixture_path, report_dir)

        self.assertTrue(result["ok"])
        self.assertEqual(result["layout_status"], "FAIL")
        self.assertEqual(result["semantic_status"], "FAIL")
        self.assertEqual(result["layout_report_final_status"], "FAIL")

    def test_inventory_can_assert_expected_layout_final_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fixture_path = root / "fixture_mode.bpmn"
            fixture_path.write_text("<definitions id='f1' />\n", encoding="utf-8")

            pipeline_script = root / "pipeline.py"
            pipeline_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import argparse, hashlib, json",
                        "from pathlib import Path",
                        "def sha256(path):",
                        "  h=hashlib.sha256(); h.update(Path(path).read_bytes()); return h.hexdigest()",
                        "def w(path,payload):",
                        "  Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True)+'\\n', encoding='utf-8')",
                        "parser=argparse.ArgumentParser()",
                        "parser.add_argument('input')",
                        "parser.add_argument('--work-dir', required=True)",
                        "parser.add_argument('--requested-mode', default='auto')",
                        "parser.add_argument('--preserve-existing-di', action='store_true')",
                        "parser.add_argument('--facts-json')",
                        "parser.add_argument('--timeout-seconds', type=int, default=30)",
                        "args=parser.parse_args()",
                        "work=Path(args.work_dir); work.mkdir(parents=True, exist_ok=True)",
                        "backend=work/'backend_selection.json'",
                        "semantic=work/'semantic_report.json'",
                        "layout=work/'layout_report.md'",
                        "human=work/'human_summary.md'",
                        "w(backend, {'initial_backend':'simple','final_backend':'simple','fallback_happened':False,'semantic_status':'PASS','layout_status':'PASS','preview_status':'SKIPPED'})",
                        "w(semantic, {'backend':'simple','status':'PASS','errors':[],'warnings':[]})",
                        "layout.write_text('# Layout Report\\n\\nFinal status: PASS\\n', encoding='utf-8')",
                        "human.write_text('# Summary\\n', encoding='utf-8')",
                        "manifest={",
                        "  'manifest_schema_version':'2','linked_report_schema_version':'2','build_version':'t','skill_version':'s','runtime_target':'r',",
                        "  'requested_mode':args.requested_mode,'logic_only':False,'preserve_existing_di':bool(args.preserve_existing_di),'full_relayout':False,",
                        "  'layout_bypass':False,'eligibility_class':'simple_eligible','eligibility_reasons':['test'],",
                        "  'scenario_id':'ACC-MODE','fixture_id':'fixture_mode','traceability_count':0,'assumptions_count':0,",
                        "  'initial_backend':'simple','final_backend':'simple','fallback_happened':False,'semantic_status':'PASS','layout_status':'PASS','preview_status':'SKIPPED',",
                        "  'layout_summary':{'final_status':'PASS','final_mode':'native_greenfield','layout_profile_family':'native','layout_policy_status':'PASS','typed_issue_count':0,'warning_issue_count':0,'error_issue_count':0,'shape_budget_violations':0,'label_budget_violations':0,'participant_lane_budget_violations':0,'advisory_only':False},",
                        "  'artifacts':{",
                        "    'backend_selection':{'report_kind':'backend_selection','presence':'present','status':'PASS','schema_version':'2','path':'backend_selection.json','hash':sha256(backend)},",
                        "    'semantic_report':{'report_kind':'semantic_report','presence':'present','status':'PASS','schema_version':'2','path':'semantic_report.json','hash':sha256(semantic)},",
                        "    'layout_report':{'report_kind':'layout_report','presence':'present','status':'PASS','schema_version':'2','path':'layout_report.md','hash':sha256(layout)},",
                        "    'preview_report':{'report_kind':'preview_report','presence':'skipped','status':'SKIPPED','schema_version':'2'},",
                        "    'human_summary':{'report_kind':'human_summary','presence':'present','status':'PASS','schema_version':'2','path':'human_summary.md','hash':sha256(human)},",
                        "    'typed_issue_targets':{'report_kind':'typed_issue_targets','presence':'not_applicable','status':'SKIPPED','schema_version':'2'}",
                        "  }",
                        "}",
                        "w(work/'run_manifest.json', manifest)",
                        "print('{\"ok\": true}')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            validator_script = root / "validator.py"
            validator_script.write_text(
                "#!/usr/bin/env python3\nimport sys\nprint('ok')\nsys.exit(0)\n",
                encoding="utf-8",
            )
            report_dir = root / "reports"
            fixture = {
                "fixture_id": "fixture_mode",
                "scenario_id": "ACC-MODE",
                "category": "stripped",
                "path": fixture_path.name,
                "requested_mode": "auto",
                "expected_eligibility_class": "simple_eligible",
                "expected_final_backend": "simple",
                "expected_routing_class": "simple_direct",
                "expected_layout_final_mode": "simple_postprocess_refine",
            }
            args = type(
                "Args",
                (),
                {
                    "pipeline_script": str(pipeline_script),
                    "manifest_validator": str(validator_script),
                    "timeout_seconds": 5,
                    "helper_command": None,
                    "repeatability_runs": 2,
                    "build_version": "test",
                    "skill_version": "test",
                    "runtime_target": "test",
                },
            )()
            result = MATRIX._run_pipeline_fixture(args, fixture, fixture_path, report_dir)

        self.assertFalse(result["ok"])
        self.assertTrue(
            any("layout_final_mode mismatch" in error for error in result["errors"])
        )

    def test_inventory_can_assert_warning_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fixture_path = root / "fixture_warn_budget.bpmn"
            fixture_path.write_text("<definitions id='f1' />\n", encoding="utf-8")

            pipeline_script = root / "pipeline.py"
            pipeline_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import argparse, hashlib, json",
                        "from pathlib import Path",
                        "def sha256(path):",
                        "  h=hashlib.sha256(); h.update(Path(path).read_bytes()); return h.hexdigest()",
                        "def w(path,payload):",
                        "  Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True)+'\\n', encoding='utf-8')",
                        "parser=argparse.ArgumentParser()",
                        "parser.add_argument('input')",
                        "parser.add_argument('--work-dir', required=True)",
                        "parser.add_argument('--requested-mode', default='auto')",
                        "parser.add_argument('--preserve-existing-di', action='store_true')",
                        "parser.add_argument('--facts-json')",
                        "parser.add_argument('--timeout-seconds', type=int, default=30)",
                        "args=parser.parse_args()",
                        "work=Path(args.work_dir); work.mkdir(parents=True, exist_ok=True)",
                        "backend=work/'backend_selection.json'",
                        "semantic=work/'semantic_report.json'",
                        "layout=work/'layout_report.md'",
                        "human=work/'human_summary.md'",
                        "w(backend, {'initial_backend':'simple','final_backend':'simple','fallback_happened':False,'semantic_status':'PASS','layout_status':'PASS','preview_status':'SKIPPED'})",
                        "w(semantic, {'backend':'simple','status':'PASS','errors':[],'warnings':[]})",
                        "layout.write_text('# Layout Report\\n\\nFinal status: PASS\\n', encoding='utf-8')",
                        "human.write_text('# Summary\\n', encoding='utf-8')",
                        "manifest={",
                        "  'manifest_schema_version':'2','linked_report_schema_version':'2','build_version':'t','skill_version':'s','runtime_target':'r',",
                        "  'requested_mode':args.requested_mode,'logic_only':False,'preserve_existing_di':bool(args.preserve_existing_di),'full_relayout':False,",
                        "  'layout_bypass':False,'eligibility_class':'simple_eligible','eligibility_reasons':['test'],",
                        "  'scenario_id':'ACC-WARN','fixture_id':'fixture_warn_budget','traceability_count':0,'assumptions_count':0,",
                        "  'initial_backend':'simple','final_backend':'simple','fallback_happened':False,'semantic_status':'PASS','layout_status':'PASS','preview_status':'SKIPPED',",
                        "  'layout_summary':{'final_status':'PASS','final_mode':'simple_postprocess_refine','layout_profile_family':'simple_postprocess','layout_policy_status':'PASS','typed_issue_count':5,'warning_issue_count':5,'error_issue_count':0,'shape_budget_violations':2,'label_budget_violations':0,'participant_lane_budget_violations':0,'advisory_only':True},",
                        "  'artifacts':{",
                        "    'backend_selection':{'report_kind':'backend_selection','presence':'present','status':'PASS','schema_version':'2','path':'backend_selection.json','hash':sha256(backend)},",
                        "    'semantic_report':{'report_kind':'semantic_report','presence':'present','status':'PASS','schema_version':'2','path':'semantic_report.json','hash':sha256(semantic)},",
                        "    'layout_report':{'report_kind':'layout_report','presence':'present','status':'PASS','schema_version':'2','path':'layout_report.md','hash':sha256(layout)},",
                        "    'preview_report':{'report_kind':'preview_report','presence':'skipped','status':'SKIPPED','schema_version':'2'},",
                        "    'human_summary':{'report_kind':'human_summary','presence':'present','status':'PASS','schema_version':'2','path':'human_summary.md','hash':sha256(human)},",
                        "    'typed_issue_targets':{'report_kind':'typed_issue_targets','presence':'not_applicable','status':'SKIPPED','schema_version':'2'}",
                        "  }",
                        "}",
                        "w(work/'run_manifest.json', manifest)",
                        "print('{\"ok\": true}')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            validator_script = root / "validator.py"
            validator_script.write_text(
                "#!/usr/bin/env python3\nimport sys\nprint('ok')\nsys.exit(0)\n",
                encoding="utf-8",
            )
            report_dir = root / "reports"
            fixture = {
                "fixture_id": "fixture_warn_budget",
                "scenario_id": "ACC-WARN",
                "category": "stripped",
                "path": fixture_path.name,
                "requested_mode": "auto",
                "expected_eligibility_class": "simple_eligible",
                "expected_final_backend": "simple",
                "expected_routing_class": "simple_direct",
                "expected_layout_profile_family": "simple_postprocess",
                "max_warning_issue_count": 1,
                "max_error_issue_count": 0,
                "advisory_only_allowed": True,
            }
            args = type(
                "Args",
                (),
                {
                    "pipeline_script": str(pipeline_script),
                    "manifest_validator": str(validator_script),
                    "timeout_seconds": 5,
                    "helper_command": None,
                    "repeatability_runs": 2,
                    "build_version": "test",
                    "skill_version": "test",
                    "runtime_target": "test",
                },
            )()
            result = MATRIX._run_pipeline_fixture(args, fixture, fixture_path, report_dir)

        self.assertFalse(result["ok"])
        self.assertTrue(
            any("warning_issue_count exceeds fixture budget" in error for error in result["errors"])
        )


if __name__ == "__main__":
    unittest.main()
