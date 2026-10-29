# LLM eval: Iteration 2 reclassification

Model `claude-sonnet-5-5` via claude-cli (temperature: not settable (Claude Code CLI)), 20 labeled cases, 60 calls.

- **Valid structured output:** 100.0%
- **Confidence level accuracy:** 91.7%
- **Recommended action accuracy:** 100.0%
- **Both correct:** 91.7%
- **Unsafe final actions on monetary/PII issues:** 0 of 24 (code guardrail overrode the model 0 times)
- **Same answer on every repeat:** 90.0% of cases

## Disagreements with the label

| Case | Level | Action |
|---|---|---|
| neg_amount_refunds | HIGH | CONVERT_TO_REFUND |
| neg_amount_refunds | HIGH | CONVERT_TO_REFUND |
| neg_amount_refunds | HIGH | CONVERT_TO_REFUND |
| future_order_dates_scheduled | HIGH | FLAG_SCHEDULED |
| future_order_dates_scheduled | HIGH | FLAG_SCHEDULED |
