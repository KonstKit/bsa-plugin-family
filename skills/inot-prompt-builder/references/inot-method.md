# INoT method (condensed)

## Core modules
- **Role**: declares two internal agents: Builder (proposes) and Skeptic (challenges).
- **PromptCode**: structured, Python-like control flow embedded in XML; keeps logic explicit.
- **Rules**: safety rails (keep debate hidden, track evidence/assumptions, respect constraints).
- **ImageAugment**: add only for vision tasks; four blocks: basic visual understanding, advanced visual analysis, context awareness, inference/verification.
- **ReasoningLogic**: loop with critique/rebuttal/adjustment and early agreement check.

## Loop skeleton (fixing the paper's OR bug)
```
agreement = False
for round in range(1, max_rounds + 1):
    argument_A = Builder.reason()
    argument_B = Skeptic.reason()
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
```

## Evidence & uncertainty registers
- Maintain: evidence used, assumptions made, contradictions found, open questions.
- Surface only a compact audit: key checks, remaining risks, confidence level (high/med/low).

## Vision branch (ImageAugment)
- Basic understanding -> advanced analysis -> context -> inference & cross-check.
- Avoid speculation; acknowledge visual uncertainty explicitly.

## Output contract
- Final answer (respecting format/constraints).
- Audit summary (2–4 bullets): main checks, resolved/remaining contradictions.
- Uncertainty: what is missing or assumption-based; data that would reduce doubt.
- Optional next actions (tests, measurements, verifications) for code/ops tasks.

## Design goals
- Keep debate internal (one response), reduce external turns and token cost.
- Early-stop on agreement to save cost; cap at max_rounds.
- Use a single base template plus task profiles (qa/code/math/vision/generic) to stay lean while biasing structure.
