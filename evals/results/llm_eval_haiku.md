# LLM eval: Iteration 2 reclassification

Model `claude-haiku-5-5` via claude-cli (temperature: not settable (Claude Code CLI)), 34 labeled cases, 34 calls.

- **Valid structured output:** 100.0%
- **Recommended action accuracy:** 91.2%
- **Model's confidence level follows the definition:** 100.0% (0 corrected in code; final levels 100.0%)
- **Unsafe final actions on monetary/PII issues:** 0 of 11 (code guardrail overrode the model 0 times)

## By difficulty

| Group | Calls | Action accuracy | Level follows definition |
|---|---|---|---|
| hard | 14 | 92.9% | 100.0% |
| hard: adversarial | 2 | 100.0% | 100.0% |
| hard: conflicting | 2 | 100.0% | 100.0% |
| hard: indirect | 5 | 100.0% | 100.0% |
| hard: partial | 2 | 100.0% | 100.0% |
| hard: reframes_issue | 3 | 66.7% | 100.0% |
| standard | 20 | 90.0% | 100.0% |

## Misses

| Case | Kind | Model level | Final level | Action | Action OK |
|---|---|---|---|---|---|
| future_hire_dates_error | - | MEDIUM | MEDIUM | ESCALATE_TO_USER | no |
| null_sensor_impute_ok | - | MEDIUM | MEDIUM | ESCALATE_TO_USER | no |
| wrong_column | reframes_issue | MEDIUM | MEDIUM | ESCALATE_TO_USER | no |
