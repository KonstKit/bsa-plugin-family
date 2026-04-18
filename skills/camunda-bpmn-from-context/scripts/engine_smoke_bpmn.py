#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path


ENV_VARS = {
    "import_cmd": "BPMN_SMOKE_IMPORT_CMD",
    "deploy_cmd": "BPMN_SMOKE_DEPLOY_CMD",
    "process_test_cmd": "BPMN_SMOKE_PROCESS_TEST_CMD",
    "shell": "BPMN_SMOKE_SHELL",
}
STEP_ORDER = ("import", "deploy", "process_test")
STATUS_PASS = "PASS"
STATUS_SKIPPED = "SKIPPED"
STATUS_MISCONFIGURED = "MISCONFIGURED"
STATUS_NOT_VERIFIED = "NOT_VERIFIED"


def resolve_command(args, attr_name):
    explicit = getattr(args, attr_name)
    if explicit:
        return explicit
    return os.getenv(ENV_VARS[attr_name])


def resolve_executable(candidate):
    if not candidate:
        return None
    if os.path.sep in candidate:
        path = Path(candidate).expanduser()
        if path.exists() and os.access(path, os.X_OK):
            return str(path)
        return None
    return shutil.which(candidate)


def resolve_shell(args):
    preferred = resolve_command(args, "shell")
    candidates = []
    if preferred:
        candidates.append(preferred)
    env_shell = os.getenv("SHELL")
    if env_shell and env_shell not in candidates:
        candidates.append(env_shell)
    for fallback in ("sh", "bash", "zsh"):
        if fallback not in candidates:
            candidates.append(fallback)

    checked = []
    for candidate in candidates:
        resolved = resolve_executable(candidate)
        checked.append(candidate)
        if resolved:
            return resolved, checked
    return None, checked


def render_command(command, input_path, camunda_version):
    if not command:
        return None
    rendered = command
    replacements = {
        "{input}": shlex.quote(str(input_path)),
        "{input_path}": str(input_path),
        "{camunda_version}": camunda_version,
    }
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


def build_step_env(input_path, camunda_version):
    env = os.environ.copy()
    env["BPMN_SMOKE_INPUT"] = shlex.quote(str(input_path))
    env["BPMN_SMOKE_INPUT_PATH"] = str(input_path)
    env["BPMN_SMOKE_CAMUNDA_VERSION"] = camunda_version
    return env


def run_step(name, command, shell_path, env):
    started_at = time.time()
    try:
        completed = subprocess.run(
            [shell_path, "-lc", command],
            capture_output=True,
            text=True,
            env=env,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        internal_error = None
    except Exception as exc:
        exit_code = 127
        stdout = ""
        stderr = ""
        internal_error = str(exc)

    step = {
        "name": name,
        "command": command,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": int((time.time() - started_at) * 1000),
    }
    if internal_error:
        step["internal_error"] = internal_error
    return step


def build_report(
    input_path,
    camunda_version,
    deploy_profile,
    status,
    proof_level,
    commands,
    steps,
    errors=None,
    skipped_reason=None,
    selected_shell=None,
    shell_candidates=None,
):
    return {
        "input": str(input_path),
        "camunda_version": camunda_version,
        "deploy_profile": deploy_profile,
        "status": status,
        "proof_level": proof_level,
        "commands": commands,
        "selected_shell": selected_shell,
        "shell_candidates": shell_candidates or [],
        "errors": errors or [],
        "skipped_reason": skipped_reason,
        "steps": steps,
    }


def write_report(report, report_path):
    if not report_path:
        return
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return

    lines = [
        "# Engine Smoke Report",
        "",
        f"- input: `{report['input']}`",
        f"- camunda_version: `{report['camunda_version']}`",
        f"- deploy_profile: `{report['deploy_profile']}`",
        f"- status: `{report['status']}`",
        f"- proof_level: `{report['proof_level']}`",
    ]
    if report.get("skipped_reason"):
        lines.append(f"- skipped_reason: `{report['skipped_reason']}`")
    if report.get("commands"):
        lines.append("- commands:")
        for name, command in report["commands"].items():
            lines.append(f"  - {name}: `{command}`")
    if report.get("errors"):
        lines.append("- errors:")
        for error in report["errors"]:
            lines.append(f"  - {error}")
    if report.get("selected_shell"):
        lines.append(f"- selected_shell: `{report['selected_shell']}`")
    if report.get("shell_candidates"):
        lines.append(f"- shell_candidates: `{', '.join(report['shell_candidates'])}`")
    if report["steps"]:
        lines.extend(["", "## Steps", ""])
        for step in report["steps"]:
            lines.extend(
                [
                    f"### {step['name']}",
                    "",
                    f"- exit_code: `{step['exit_code']}`",
                    f"- duration_ms: `{step['duration_ms']}`",
                    f"- command: `{step['command']}`",
                ]
            )
            if step.get("internal_error"):
                lines.append(f"- internal_error: `{step['internal_error']}`")
            if step["stdout"].strip():
                lines.extend(["", "```text", step["stdout"].rstrip(), "```"])
            if step["stderr"].strip():
                lines.extend(["", "```text", step["stderr"].rstrip(), "```"])
            lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="Run optional engine-level BPMN smoke checks.")
    parser.add_argument("input", help="Path to BPMN file")
    parser.add_argument("--camunda-version", choices=["7", "8", "documentation-only"], default="documentation-only")
    parser.add_argument(
        "--deploy-profile",
        choices=["7", "8", "off"],
        help="Runtime profile used for engine-level proof checks.",
    )
    parser.add_argument("--import-cmd", help="Shell command for model import/open round-trip")
    parser.add_argument("--deploy-cmd", help="Shell command for deploy validation")
    parser.add_argument("--process-test-cmd", help="Shell command for minimal process smoke test")
    parser.add_argument("--shell", help="Optional shell executable to use for step commands")
    parser.add_argument("--report", help="Optional path for a JSON or Markdown report")
    return parser.parse_args()


def emit_and_return(report, report_path, exit_code, stream_message=None, error=False):
    write_report(report, report_path)
    if stream_message:
        target = sys.stderr if error else sys.stdout
        print(stream_message, file=target)
    return exit_code


def main():
    args = parse_args()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"Input BPMN does not exist: {input_path}", file=sys.stderr)
        return 2

    if args.deploy_profile is None:
        deploy_profile = args.camunda_version if args.camunda_version in {"7", "8"} else "off"
    else:
        deploy_profile = args.deploy_profile

    commands = {
        "import": resolve_command(args, "import_cmd"),
        "deploy": resolve_command(args, "deploy_cmd"),
        "process_test": resolve_command(args, "process_test_cmd"),
    }
    rendered_commands = {
        name: render_command(command, input_path, args.camunda_version) for name, command in commands.items()
    }
    configured = {name: bool(command) for name, command in commands.items()}

    if deploy_profile == "off":
        report = build_report(
            input_path,
            args.camunda_version,
            deploy_profile,
            STATUS_SKIPPED,
            proof_level="not verified",
            commands=rendered_commands,
            steps=[],
            skipped_reason="Deploy profile is off",
        )
        return emit_and_return(
            report,
            args.report,
            0,
            "SKIPPED: deploy profile is off; deployability proof not requested",
        )

    if not any(configured.values()):
        report = build_report(
            input_path,
            args.camunda_version,
            deploy_profile,
            status=STATUS_SKIPPED,
            proof_level="not verified",
            commands=rendered_commands,
            steps=[],
            skipped_reason="No engine smoke commands were configured.",
            errors=["No engine smoke commands were configured."],
        )
        return emit_and_return(
            report,
            args.report,
            0,
            "SKIPPED: no engine smoke commands configured; deployability remains not verified",
        )

    missing = [name for name, is_configured in configured.items() if not is_configured]
    if missing:
        report = build_report(
            input_path,
            args.camunda_version,
            deploy_profile,
            status=STATUS_MISCONFIGURED,
            proof_level="not verified",
            commands=rendered_commands,
            steps=[],
            skipped_reason="Engine smoke commands are partially configured.",
            errors=[f"Missing required commands: {', '.join(sorted(missing))}"],
        )
        return emit_and_return(
            report,
            args.report,
            2,
            f"Engine smoke is partially configured; missing steps: {', '.join(sorted(missing))}",
            error=True,
        )

    shell_path, shell_candidates = resolve_shell(args)
    if shell_path is None:
        report = build_report(
            input_path,
            args.camunda_version,
            deploy_profile,
            status=STATUS_MISCONFIGURED,
            proof_level="not verified",
            commands=rendered_commands,
            steps=[],
            skipped_reason="No executable shell was found for engine smoke commands.",
            errors=["No executable shell was found for engine smoke commands."],
            shell_candidates=shell_candidates,
        )
        return emit_and_return(
            report,
            args.report,
            2,
            "Engine smoke could not resolve an executable shell",
            error=True,
        )

    env = build_step_env(input_path, args.camunda_version)
    steps = []
    try:
        for name in STEP_ORDER:
            rendered_command = render_command(commands[name], input_path, args.camunda_version)
            step_result = run_step(name, rendered_command, shell_path, env)
            steps.append(step_result)
            if step_result.get("internal_error"):
                report = build_report(
                    input_path,
                    args.camunda_version,
                    deploy_profile,
                    status=STATUS_NOT_VERIFIED,
                    proof_level="not verified",
                    commands=rendered_commands,
                    steps=steps,
                    errors=["A smoke step failed before completion."],
                    selected_shell=shell_path,
                    shell_candidates=shell_candidates,
                )
                return emit_and_return(
                    report,
                    args.report,
                    1,
                    f"FAIL: engine smoke step `{name}` could not be executed",
                    error=True,
                )
            if step_result["exit_code"] != 0:
                report = build_report(
                    input_path,
                    args.camunda_version,
                    deploy_profile,
                    status=STATUS_NOT_VERIFIED,
                    proof_level="not verified",
                    commands=rendered_commands,
                    steps=steps,
                    errors=[f"Step `{name}` failed with exit_code={step_result['exit_code']}."],
                    selected_shell=shell_path,
                    shell_candidates=shell_candidates,
                )
                return emit_and_return(
                    report,
                    args.report,
                    1,
                    f"FAIL: engine smoke step `{name}` failed",
                    error=True,
                )
    except Exception as exc:
        report = build_report(
            input_path,
            args.camunda_version,
            deploy_profile,
            status=STATUS_NOT_VERIFIED,
            proof_level="not verified",
            commands=rendered_commands,
            steps=steps,
            errors=[f"Internal engine smoke error: {exc}"],
            selected_shell=shell_path,
            shell_candidates=shell_candidates,
        )
        return emit_and_return(
            report,
            args.report,
            1,
            "FAIL: engine smoke encountered an internal error",
            error=True,
        )

    report = build_report(
        input_path,
        args.camunda_version,
        deploy_profile,
        status=STATUS_PASS,
        proof_level=f"engine-smoke verified for Camunda {args.camunda_version}",
        commands=rendered_commands,
        steps=steps,
        errors=[],
        selected_shell=shell_path,
        shell_candidates=shell_candidates,
    )
    return emit_and_return(
        report,
        args.report,
        0,
        f"PASS: engine smoke checks passed for Camunda {args.camunda_version}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
