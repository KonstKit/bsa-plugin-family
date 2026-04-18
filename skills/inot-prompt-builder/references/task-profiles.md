# Task profiles

Select `task_type` and adjust knobs before rendering the prompt.

## generic (default)
- Use for mixed or unclear cases.
- max_rounds: 4–6; output_mode: answer_plus_audit.

## qa
- Emphasize evidence, contradiction checks, and uncertainty block.
- Encourage citing sources or requesting missing data.
- max_rounds: 4–7.

## code
- Prefer design/algorithm reasoning; avoid full code unless asked.
- Suggest post-answer verification: tests, lint, types.
- max_rounds: 4–6.

## math
- Keep chain-of-thought terse; highlight known theorems/lemmas.
- Double-check units and boundary cases.
- max_rounds: 4–8.

## vision
- Always include ImageAugment (has_image=true is enforced).
- Require explicit statements of what is visible vs inferred.
- max_rounds: 5–8.

## knobs
- `max_rounds`: clamp 3–10; early stop on agreement.
- `output_mode`: `answer_only` for terse replies; `answer_plus_audit` (default) adds audit+uncertainty.
- `style`: optional tone (formal/concise/teaching) — keep short.
- `constraints`: must/avoid formats, safety, or tool allowances.
