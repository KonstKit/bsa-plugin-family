#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent / "engine_smoke_bpmn.py"


MINIMAL_BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="Process_1">
    <bpmn:startEvent id="Start_1" />
    <bpmn:endEvent id="End_1" />
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
  </bpmn:process>
</bpmn:definitions>
"""


def python_ok_command(message):
    return f"{sys.executable} -c \"print('{message}')\""


def python_fail_command(message):
    return f"{sys.executable} -c \"import sys; print('{message}'); sys.exit(1)\""


class EngineSmokeTests(unittest.TestCase):
    def run_smoke(self, extra_args, env=None):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bpmn_path = temp_path / "input.bpmn"
            report_path = temp_path / "report.json"
            bpmn_path.write_text(MINIMAL_BPMN, encoding="utf-8")

            command = [
                sys.executable,
                str(SCRIPT_PATH),
                str(bpmn_path),
                "--report",
                str(report_path),
                *extra_args,
            ]
            completed = subprocess.run(command, capture_output=True, text=True, env=env)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            return completed, report

    def test_skips_when_no_engine_commands_are_configured(self):
        completed, report = self.run_smoke(["--camunda-version", "8"])
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["status"], "SKIPPED")
        self.assertEqual(report["proof_level"], "not verified")
        self.assertEqual(report["steps"], [])
        self.assertTrue(report["skipped_reason"])

    def test_partial_configuration_is_misconfigured(self):
        completed, report = self.run_smoke(
            [
                "--camunda-version",
                "8",
                "--import-cmd",
                python_ok_command("import-ok"),
            ]
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["status"], "MISCONFIGURED")
        self.assertIn("Missing required commands: deploy, process_test", report["errors"][0])

    def test_missing_preferred_shell_falls_back_without_crash(self):
        completed, report = self.run_smoke(
            [
                "--camunda-version",
                "8",
                "--shell",
                "/definitely/missing-shell",
                "--import-cmd",
                python_ok_command("import-ok"),
                "--deploy-cmd",
                python_ok_command("deploy-ok"),
                "--process-test-cmd",
                python_ok_command("process-ok"),
            ]
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["status"], "PASS")
        self.assertNotEqual(report["selected_shell"], "/definitely/missing-shell")

    def test_passes_when_all_engine_steps_succeed(self):
        completed, report = self.run_smoke(
            [
                "--camunda-version",
                "8",
                "--import-cmd",
                python_ok_command("import-ok"),
                "--deploy-cmd",
                python_ok_command("deploy-ok"),
                "--process-test-cmd",
                python_ok_command("process-ok"),
            ]
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["status"], "PASS")
        self.assertIn("engine-smoke verified", report["proof_level"])
        self.assertEqual(len(report["steps"]), 3)
        self.assertTrue(all(step["exit_code"] == 0 for step in report["steps"]))

    def test_explicit_shell_path_is_supported(self):
        shell_path = shutil.which("sh")
        self.assertIsNotNone(shell_path)
        completed, report = self.run_smoke(
            [
                "--camunda-version",
                "8",
                "--shell",
                shell_path,
                "--import-cmd",
                python_ok_command("import-ok"),
                "--deploy-cmd",
                python_ok_command("deploy-ok"),
                "--process-test-cmd",
                python_ok_command("process-ok"),
            ]
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["selected_shell"], shell_path)

    def test_brace_heavy_commands_do_not_trigger_template_errors(self):
        brace_command = f"{sys.executable} -c \"print({{'ok': 1}})\""
        completed, report = self.run_smoke(
            [
                "--camunda-version",
                "8",
                "--import-cmd",
                brace_command,
                "--deploy-cmd",
                python_ok_command("deploy-ok"),
                "--process-test-cmd",
                python_ok_command("process-ok"),
            ]
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["status"], "PASS")
        self.assertIn("{'ok': 1}", report["steps"][0]["stdout"])

    def test_fails_when_any_engine_step_fails(self):
        completed, report = self.run_smoke(
            [
                "--camunda-version",
                "7",
                "--import-cmd",
                python_ok_command("import-ok"),
                "--deploy-cmd",
                python_fail_command("deploy-fail"),
                "--process-test-cmd",
                python_ok_command("process-ok"),
            ]
        )
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(report["status"], "NOT_VERIFIED")
        self.assertEqual(report["steps"][1]["name"], "deploy")
        self.assertEqual(report["steps"][1]["exit_code"], 1)

    def test_env_var_commands_are_supported(self):
        env = os.environ.copy()
        env.update(
            {
                "BPMN_SMOKE_IMPORT_CMD": python_ok_command("import-env"),
                "BPMN_SMOKE_DEPLOY_CMD": python_ok_command("deploy-env"),
                "BPMN_SMOKE_PROCESS_TEST_CMD": python_ok_command("process-env"),
            }
        )
        completed, report = self.run_smoke(["--camunda-version", "8"], env=env)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["status"], "PASS")
        self.assertIn("import-env", report["steps"][0]["stdout"])


if __name__ == "__main__":
    unittest.main()
