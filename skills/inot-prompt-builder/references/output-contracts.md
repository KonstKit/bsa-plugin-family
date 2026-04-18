# Output contracts

## answer_plus_audit (default)
- **Answer**: final solution in requested format.
- **Audit summary**: 2–4 bullets, covering main checks and resolved/remaining contradictions.
- **Uncertainty**: what is assumption-based or missing; data/tests that would increase confidence.
- **Next actions** (optional): small list for code/ops tasks (e.g., run tests, gather metric X).
- **Hidden debate**: do not include internal debate transcripts in the output.

### Example (QA)
```
Answer: The painting is likely by Alice Doe (1912), based on signature pattern and palette.
Audit: Checked signature vs catalog; palette matches 1910–1914 works; no record of 1915 exhibit here.
Uncertainty: No high-res view of lower-left stamp; provenance docs absent.
Next actions: Acquire stamp macro photo; check gallery ledger for 1913 loans.
```

## answer_only
- **Answer** only (no audit block), but still run the hidden debate and agreement check internally.
- Mention uncertainty inline only if it is material; otherwise keep terse.
- No audit summary or next actions.
- **Hidden debate**: never expose internal debate transcripts.

## Vision-specific addendum
- In answers, separate visible facts from inferred conclusions.
- If visibility is insufficient, state that clearly and avoid speculation.
