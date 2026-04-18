#!/usr/bin/env python3
"""
Render a ready-to-use Introspection-of-Thought (INoT) prompt with hidden dual-agent debate.

Usage:
  python render_inot_prompt.py --task "Design a concurrency-safe cache" --task-type code --max-rounds 6 \
    --output-mode answer_plus_audit --constraints "must stay under 200 words" "prefer Go" --style concise

Or via JSON config (CLI flags override config fields):
  python render_inot_prompt.py --config config.json

Config schema:
{
  "task": "text of the problem (include data/links/vision description)",
  "task_type": "qa|code|math|vision|generic",
  "max_rounds": 6,
  "output_mode": "answer_plus_audit|answer_only",
  "constraints": ["must...", "avoid..."],
  "style": "concise / formal / teaching / etc.",
  "has_image": false
}
"""
import argparse
import json
import sys
from html import escape
from pathlib import Path
from textwrap import dedent
from typing import Optional

VALID_TASK_TYPES = {"qa", "code", "math", "vision", "generic"}
VALID_OUTPUT_MODES = {"answer_plus_audit", "answer_only"}

DOMAIN_RULES = {
    "generic": "- Focus on correctness and clarity.\n- Keep chain-of-thought compact.\n- Call out assumptions explicitly.",
    "qa": "- Check claims against evidence or note missing data.\n- Surface contradictions and avoid speculation.\n- Ask for clarifications only if blocking.",
    "code": "- Reason about design/algorithms before code.\n- Keep code minimal unless explicitly requested.\n- Suggest tests/lint/type checks after synthesis.",
    "math": "- Track assumptions, units, and boundary cases.\n- Keep derivations tight.\n- Re-check final result and sanity bounds.",
    "vision": "- Separate observed facts from inferences.\n- Avoid guessing; state visual uncertainty.\n- Cross-check objects/relations relevant to the task.",
}

IMAGE_BLOCK = dedent(
    """
    <ImageAugment>
      - Basic visual understanding: identify key objects, text, and layout.
      - Advanced visual analysis: relationships, counts, spatial reasoning.
      - Context awareness: link visual cues to task goals; avoid unsupported leaps.
      - Inference and verification: cross-check claims; flag uncertain or ambiguous regions.
    </ImageAugment>
    """
)

OUTPUT_CONTRACT_AUDIT = """
<OutputContract>
mode = answer_plus_audit
- answer: final response that follows user format/constraints.
- audit_summary: key checks, contradictions resolved/remaining.
- uncertainty: what is assumption-based or missing; evidence or data that would reduce doubt.
- next_actions: optional for code/ops (tests to run, data to gather).
Do not include the internal debate transcript.
</OutputContract>
"""

OUTPUT_CONTRACT_ANSWER_ONLY = """
<OutputContract>
mode = answer_only
- answer: final response that follows user format/constraints.
- uncertainty: mention briefly inline only if material; otherwise keep terse.
Do not include audit or internal debate transcript.
</OutputContract>
"""

BASE_TEMPLATE = """
<Role>
  PromptCode Executor: runs the reasoning logic exactly as written.
  Builder: proposes structured solutions.
  Skeptic: challenges, probes for flaws, edge cases, missing evidence.
</Role>

<PromptCode>
  PromptCode combines Python-like control flow with natural-language steps.
  Learn and execute the reasoning logic line by line; do not skip or reorder steps.
  Keep all debate internal; never reveal raw transcripts.
</PromptCode>

<Rules>
  - Respect constraints: {constraints}
  - Style: {style}
  - Maintain registers: evidence, assumptions, contradictions, uncertainty.
  - Early stop when semantic agreement is reached.
  - Cap rounds at max_rounds.
  - For code: prefer reasoning; suggest tests/verification after synthesis.
  - For vision: separate observed facts from inferred claims; avoid speculation.
</Rules>

{image_block}

<ReasoningLogic>
max_rounds = {max_rounds}
agreement = False
for round in range(1, max_rounds + 1):
    argument_A = Builder.reason(task)
    argument_B = Skeptic.reason(task)
    critique_A = Builder.critique(argument_B)
    critique_B = Skeptic.critique(argument_A)
    rebuttal_A = Builder.rebut(critique_B)
    rebuttal_B = Skeptic.rebut(critique_A)
    result_A = Builder.adjust(rebuttal_B)
    result_B = Skeptic.adjust(rebuttal_A)
    agreement = semantically_equivalent(result_A, result_B)
    if agreement:
        break
final = synthesize(result_A, result_B)
</ReasoningLogic>

<Task>
{task}
</Task>

<DomainHints>
{domain_rules}
</DomainHints>

{output_contract}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render an INoT prompt")
    parser.add_argument("--task", help="Problem statement")
    parser.add_argument("--task-type", choices=sorted(VALID_TASK_TYPES), dest="task_type")
    parser.add_argument("--max-rounds", type=int, dest="max_rounds", default=None)
    parser.add_argument("--output-mode", choices=sorted(VALID_OUTPUT_MODES), dest="output_mode")
    parser.add_argument("--constraints", nargs="*", default=None, help="List of must/avoid/style constraints")
    parser.add_argument("--style", default=None, help="Optional tone e.g., concise, formal, teaching")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--has-image", dest="has_image", action="store_true", help="Force include ImageAugment")
    group.add_argument("--no-has-image", dest="has_image", action="store_false", help="Force skip ImageAugment")
    parser.set_defaults(has_image=None)
    parser.add_argument("--config", type=Path, help="Path to JSON config; CLI flags override")
    parser.add_argument("--out", type=Path, help="Write prompt to file instead of stdout")
    parser.add_argument("--dump-schema", action="store_true", help="Print JSON schema and exit")
    return parser.parse_args()


def load_config(path: Path) -> dict:
    try:
        with path.open() as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit(f"Config file not found: {path}")
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in config file: {e}")


def clamp_rounds(value: Optional[int]) -> int:
    default = 6
    if value is None:
        return default
    return max(3, min(10, value))


def ensure_str_list(name: str, value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, (list, tuple)):
        sys.exit(f"{name} must be a string or a list of strings")
    out: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            sys.exit(f"{name}[{idx}] must be a string")
        out.append(item)
    return out


def ensure_int(name: str, value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):  # avoid bool being int
        sys.exit(f"{name} must be an integer, not boolean")
    if isinstance(value, int):
        return value
    sys.exit(f"{name} must be an integer; got {type(value).__name__}")


def xml_escape(text: str) -> str:
    return escape(text, quote=True)


def assert_required_blocks(prompt: str) -> None:
    required = [
        "<Role>", "<PromptCode>", "<Rules>", "<ReasoningLogic>",
        "<Task>", "<DomainHints>", "<OutputContract>",
    ]
    for block in required:
        if prompt.count(block) != 1:
            sys.exit(f"Rendered prompt is missing or has duplicate block: {block}")
    if prompt.find("</Task>") < prompt.find("<Task>"):
        sys.exit("Task block is malformed (closing tag before opening)")
    closing_pairs = {
        "<Role>": "</Role>",
        "<PromptCode>": "</PromptCode>",
        "<Rules>": "</Rules>",
        "<ReasoningLogic>": "</ReasoningLogic>",
        "<Task>": "</Task>",
        "<DomainHints>": "</DomainHints>",
        "<OutputContract>": "</OutputContract>",
    }
    for open_tag, close_tag in closing_pairs.items():
        if prompt.count(open_tag) != prompt.count(close_tag):
            sys.exit(f"Mismatched tags: {open_tag} / {close_tag}")
    # Ensure required blocks appear in canonical order (ImageAugment is optional).
    order = [
        "<Role>", "<PromptCode>", "<Rules>", "<ReasoningLogic>",
        "<Task>", "<DomainHints>", "<OutputContract>",
    ]
    positions = [prompt.find(tag) for tag in order]
    if any(pos == -1 for pos in positions):
        sys.exit("Rendered prompt missing required block positions")
    for earlier, later in zip(positions, positions[1:]):
        if earlier > later:
            sys.exit("Rendered prompt blocks are out of expected order")


def coalesce_config(args: argparse.Namespace) -> dict:
    cfg = {}
    if args.config:
        cfg = load_config(args.config)
        if not isinstance(cfg, dict):
            sys.exit("Config root must be an object")
    def pick(key, default=None):
        return getattr(args, key) if getattr(args, key) is not None else cfg.get(key, default)

    task = pick("task")
    if not isinstance(task, str) or not task.strip():
        sys.exit("task is required (non-empty string via --task or config)")

    task_type = pick("task_type", "generic")
    if task_type not in VALID_TASK_TYPES:
        sys.exit(f"task_type must be one of {sorted(VALID_TASK_TYPES)}")

    max_rounds = clamp_rounds(ensure_int("max_rounds", pick("max_rounds")))
    output_mode = pick("output_mode", "answer_plus_audit")
    if output_mode not in VALID_OUTPUT_MODES:
        sys.exit(f"output_mode must be one of {sorted(VALID_OUTPUT_MODES)}")

    constraints = ensure_str_list("constraints", pick("constraints", []))
    style = pick("style", None)
    if style is not None and not isinstance(style, str):
        sys.exit("style must be a string if provided")

    has_image_cfg = pick("has_image", None)
    if has_image_cfg is not None and not isinstance(has_image_cfg, bool):
        sys.exit("has_image must be boolean (true/false)")

    has_image = task_type == "vision"
    if has_image_cfg is not None:
        has_image = has_image_cfg
    if args.has_image is not None:
        has_image = bool(args.has_image)
    if task_type == "vision":
        has_image = True

    return {
        "task": task.strip(),
        "task_type": task_type,
        "max_rounds": max_rounds,
        "output_mode": output_mode,
        "constraints": constraints,
        "style": style,
        "has_image": has_image,
    }


def render_prompt(cfg: dict) -> str:
    constraints_str = "; ".join(cfg["constraints"]) if cfg["constraints"] else "none"
    style = cfg["style"] or "concise, neutral"
    image_block = IMAGE_BLOCK if cfg["has_image"] else ""
    domain_rules = DOMAIN_RULES.get(cfg["task_type"], DOMAIN_RULES["generic"])

    output_contract = OUTPUT_CONTRACT_AUDIT if cfg["output_mode"] == "answer_plus_audit" else OUTPUT_CONTRACT_ANSWER_ONLY

    prompt = BASE_TEMPLATE.format(
        constraints=xml_escape(constraints_str),
        style=xml_escape(style),
        image_block=image_block,
        max_rounds=cfg["max_rounds"],
        task=xml_escape(cfg["task"]),
        domain_rules=xml_escape(domain_rules),
        output_contract=output_contract,
    )
    prompt = dedent(prompt).strip() + "\n"
    assert_required_blocks(prompt)
    return prompt


def dump_schema():
    schema = {
        "task": "string (required)",
        "task_type": "qa|code|math|vision|generic (optional, default generic)",
        "max_rounds": "int 3-10 (optional, default 6)",
        "output_mode": "answer_plus_audit|answer_only (optional, default answer_plus_audit)",
        "constraints": ["string", "string"],
        "style": "string (optional)",
        "has_image": "bool (optional)"
    }
    print(json.dumps(schema, indent=2))


def main():
    args = parse_args()
    if args.dump_schema:
        dump_schema()
        return
    cfg = coalesce_config(args)
    prompt = render_prompt(cfg)
    if args.out:
        args.out.write_text(prompt)
        print(f"Wrote prompt to {args.out}")
    else:
        sys.stdout.write(prompt)


if __name__ == "__main__":
    main()
