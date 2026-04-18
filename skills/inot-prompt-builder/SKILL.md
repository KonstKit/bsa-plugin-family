---
name: inot-prompt-builder
description: "Generate one-shot Introspection-of-Thought (INoT) prompts with hidden dual-agent critique/rebuttal/adjustment and early-stop agreement (max 10 rounds) for complex QA/code/math/vision tasks. Use when internal self-review must stay inside a single response; avoid for trivial facts or user-visible coaching loops."
---

# INoT Prompt Builder

Produce faithful INoT prompts that keep the debate hidden and finish in one model response. This skill **builds prompts**; it does not run the debate itself. Two internal agents argue, critique, rebut, adjust, and stop early on agreement or after the configured round budget.

## When to use (short)
- Complex reasoning (qa, code design/debug, math, vision) needing self-check inside one answer.
- Requests for "introspection", "hidden debate", "internal self-review", or "one-shot multi-agent" prompts.
- Need to cap cost/turns while improving answer quality via internal critique.

## When NOT to use
- Simple factual lookups, open brainstorming, or user-visible coaching loops (use reflection-session-facilitator instead).
- Tasks that require long back-and-forth with the user.

## Inputs you must capture
- `task`: problem statement (include any provided data/links/images description).
- `task_type`: qa | code | math | vision | generic (default generic).
- `max_rounds`: 3–10 (default 6) with early stop on agreement.
- `output_mode`: answer_only | answer_plus_audit (default answer_plus_audit).
- `constraints`: must/avoid/style/time/format; mention tools allowed.
- `has_image`: boolean; set true if image provided. For `task_type=vision` this is always treated as true.

## Workflow
1) Collect inputs above; clamp `max_rounds` to [3,10] (minimum 3, no lower).
2) Select a task profile (qa/code/math/vision/generic) using `references/task-profiles.md`.
3) Render prompt via `scripts/render_inot_prompt.py` or assemble manually using references/output-contracts.md and references/inot-method.md.
4) The rendered prompt keeps inner debate hidden; only the final answer (and optional audit) are exposed when the prompt is executed.
5) Return the rendered prompt to the caller (this skill does **not** execute the reasoning itself).

## Output contract options
- `answer_plus_audit` (default): answer + audit summary + uncertainty + optional next actions.
- `answer_only`: answer only; uncertainty only if material, inline and terse; no audit.

## Files in this skill
- `scripts/render_inot_prompt.py` — prompt compiler; validates config and emits ready-to-use INoT prompt.
- `references/inot-method.md` — condensed architecture: modules, reasoning loop, convergence rule.
- `references/task-profiles.md` — task profiles and per-domain tweaks.
- `references/output-contracts.md` — required output structure and examples.
- `assets/examples/` — small sample configs and rendered prompts.
- `evals/run_smoke.sh` — quick regression guard (vision always ImageAugment, generic+image, CLI overrides, answer_only, XML escaping, code no-ImageAugment, invalid has_image/task_type/output_mode/style).

## Quick start (one-liner)
```
python scripts/render_inot_prompt.py --task "Design a concurrency-safe cache" --task-type code --max-rounds 6 --output-mode answer_plus_audit
```

## Manual assembly cheat-sheet
- Use two roles: Builder and Skeptic.
- Modules (as XML blocks): <Role>, <PromptCode>, <Rules>, <ImageAugment> (only if has_image), <ReasoningLogic>.
- ReasoningLogic loop: argument -> critique -> rebuttal -> adjustment; check semantic agreement; early break on agreement or after max_rounds.
- Agreement condition must use AND, not OR (fixes paper bug).
- Keep evidence, assumptions, contradictions, and uncertainty registers; surface only a concise audit.

## Guardrails
- Do not run visible iterative chat loops; debate must stay hidden in the prompt.
- Clamp `max_rounds` to [3,10]; do not go below 3.
- Always state assumptions or missing data inside the generated prompt's audit/uncertainty sections.
- For code tasks, suggest post-answer verification (tests/lint) in next-actions, but keep it outside the hidden debate.
- Vision tasks always inject ImageAugment; `--no-has-image` is ignored for `task_type=vision`.

## If user requests raw debate
- Do not expose raw transcripts. At most, include a concise audit summary by setting `output_mode=answer_plus_audit`.

## Note on related flows
- For visible, user-guided reflection loops, use a separate facilitation skill (not included in this bundle).

## Evals (smoke)
- Run `evals/run_smoke.sh` to check: vision always renders `<ImageAugment>` (even with `--no-has-image`), generic+`has_image=true` renders `<ImageAugment>`, non-vision `--no-has-image` removes it, `answer_only` omits audits, XML payload is escaped, code profile omits ImageAugment, and invalid `has_image`/`task_type`/`output_mode`/`style` fail fast with clear errors.
