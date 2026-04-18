#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent / "claim_guardrail.py"
SPEC = importlib.util.spec_from_file_location("claim_guardrail", SCRIPT_PATH)
GUARDRAIL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARDRAIL)


class ClaimGuardrailTests(unittest.TestCase):
    def test_guardrail_passes_for_current_skill_contract(self):
        root = SCRIPT_PATH.parent.parent
        errors, checked = GUARDRAIL.validate_claim_guardrails(root)
        self.assertGreaterEqual(len(checked), 4)
        self.assertEqual(errors, [])

    def test_guardrail_fails_when_required_snippet_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "agents").mkdir(parents=True, exist_ok=True)
            (root / "references").mkdir(parents=True, exist_ok=True)

            (root / "SKILL.md").write_text(
                "This file intentionally omits one required snippet.\n",
                encoding="utf-8",
            )
            (root / "agents" / "openai.yaml").write_text(
                "default_prompt: basic Camunda 7 or Camunda 8 extension support\n",
                encoding="utf-8",
            )
            (root / "references" / "support-matrix.md").write_text(
                "These statuses describe this skill's documented support only. They do not imply full BPMN spec coverage or full Camunda runtime parity.\n"
                "Treat full BPMN 2.0 parity and full Camunda runtime parity as explicit non-goals for this package.\n",
                encoding="utf-8",
            )
            (root / "references" / "deployment-readiness.md").write_text(
                "Treat semantic-validator success as evidence for the documented subset only; it is not proof of full BPMN notation coverage or full Camunda runtime parity.\n"
                "Full-runtime-parity claims are out of scope for this package and must be treated as separate engineering scope.\n",
                encoding="utf-8",
            )

            errors, _ = GUARDRAIL.validate_claim_guardrails(root)
            self.assertTrue(errors)
            self.assertTrue(any("SKILL.md: missing required snippet" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
