#!/usr/bin/env python3
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


REQUIRED_SNIPPETS = {
    "SKILL.md": [
        "does not claim full BPMN 2.0 notation coverage",
        "Camunda-aware, not a substitute for full Camunda Modeler/runtime parity",
    ],
    "agents/openai.yaml": [
        "basic Camunda 7 or Camunda 8 extension support",
    ],
    "references/support-matrix.md": [
        "These statuses describe this skill's documented support only. They do not imply full BPMN spec coverage or full Camunda runtime parity.",
        "Treat full BPMN 2.0 parity and full Camunda runtime parity as explicit non-goals for this package.",
    ],
    "references/deployment-readiness.md": [
        "Treat semantic-validator success as evidence for the documented subset only; it is not proof of full BPMN notation coverage or full Camunda runtime parity.",
        "Full-runtime-parity claims are out of scope for this package and must be treated as separate engineering scope.",
    ],
}


def validate_claim_guardrails(root=None):
    root_dir = Path(root) if root else ROOT
    errors = []
    checked_files = []
    for rel_path, snippets in REQUIRED_SNIPPETS.items():
        path = root_dir / rel_path
        checked_files.append(str(path))
        if not path.exists():
            errors.append(f"Missing contract file: {rel_path}")
            continue
        content = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in content:
                errors.append(f"{rel_path}: missing required snippet: {snippet}")
    return errors, checked_files


def main():
    parser = argparse.ArgumentParser(description="Verify claim-boundary guardrails in skill contract files.")
    parser.add_argument("--root", default=str(ROOT), help="Skill root directory")
    args = parser.parse_args()

    errors, checked_files = validate_claim_guardrails(args.root)
    for path in checked_files:
        print(f"CHECKED: {path}")
    if errors:
        for item in errors:
            print(f"ERROR: {item}")
        raise SystemExit(1)
    print("Claim guardrails validation passed")


if __name__ == "__main__":
    main()
