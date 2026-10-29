# LLM eval: Iteration 2 reclassification

Model `claude-sonnet-5-5` via claude-cli (temperature: not settable (Claude Code CLI)), 34 labeled cases, 102 calls.

- **Valid structured output:** 100.0%
- **Recommended action accuracy:** 100.0%
- **Model's confidence level follows the definition:** 100.0% (0 corrected in code; final levels 100.0%)
- **Unsafe final actions on monetary/PII issues:** 0 of 33 (code guardrail overrode the model 0 times)
- **Same answer on every repeat:** 97.1% of cases

## By difficulty

| Group | Calls | Action accuracy | Level follows definition |
|---|---|---|---|
| hard | 42 | 100.0% | 100.0% |
| hard: adversarial | 6 | 100.0% | 100.0% |
| hard: conflicting | 6 | 100.0% | 100.0% |
| hard: indirect | 15 | 100.0% | 100.0% |
| hard: partial | 6 | 100.0% | 100.0% |
| hard: reframes_issue | 9 | 100.0% | 100.0% |
| standard | 60 | 100.0% | 100.0% |
