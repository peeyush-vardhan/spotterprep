# Evals

Three questions, three scripts. Each one writes its results to `evals/results/` as JSON and Markdown.

| Question | Script | Needs |
|---|---|---|
| Does cleaning raise the quality score, and by how much? | [`reproduce_results.py`](reproduce_results.py) | Nothing (generates its own data) |
| Does Iteration 1 find the issues we know are there? | [`detection_eval.py`](detection_eval.py) | Generated data in `data/` |
| Does Iteration 2 turn the analyst's answer into the right decision? | [`llm_eval.py`](llm_eval.py) | `ANTHROPIC_API_KEY`, or a Claude subscription with `--backend claude-cli` |

```bash
python evals/reproduce_results.py --scale 0.02   # generate at 2% size and score raw vs cleaned
python evals/detection_eval.py                   # detector vs injected ground truth
python evals/llm_eval.py --repeats 3             # LLM reclassification on 34 labeled cases (API key)
python evals/llm_eval.py --backend claude-cli --model claude-sonnet-5-5 --repeats 3   # same, on a Claude subscription
```

## Ground truth

The generators inject every issue at a known column and rate and log it in `data/profiles/datasetN_profile.json`. [`ground_truth.py`](ground_truth.py) turns that log into an evaluation set and sorts each issue into one of three scopes:

- **detector**: single-column issues Iteration 1 is built to find. These are scored.
- **cross_column**: issues that need two or more columns, such as ARR below MRR × 12. Iteration 5 and the cleaning rules handle these, so they are excluded from detector recall.
- **out_of_scope**: issues no single table can reveal, such as orphaned foreign keys.

## How to read the detection numbers

- **Recall** is the share of scored issues where the detector raised the right issue family on the right column.
- **Precision** has two versions. The strict one counts every detection that does not match a logged issue as a false positive. That understates real precision, because the generators pad each table with numbered filler columns (`acct_attr_1` and so on) whose random blanks are real but never logged. The second figure leaves the filler columns out.
- **Safety** is the share of monetary and personal-data detections classified LOW confidence, which means the pipeline never fixes them on its own. The target is 100%, and CI fails below it.

## LLM eval cases

[`data/llm_reclassification_cases.json`](data/llm_reclassification_cases.json) holds 34 hand-labeled cases. Each case is an issue, the question asked and the analyst's answer, plus the actions that would count as correct. The expected confidence level follows from the action (`required_level()` in `spotterprep/llm.py`), so it is not labeled separately. The 20 standard cases cover legitimate nulls, refunds versus sign errors, scheduled versus mistyped dates, sensor fault codes, distinct values that only look like case variants, off-topic and unsure answers, and a prompt-injection attempt asking the model to impute salaries. The 14 hard cases, tagged `"difficulty": "hard"` with a `kind`, cover contradictory answers, answers that split the rows, answers that reframe the issue, sarcasm, reversals, claimed authority, an instruction planted in a data value, and informal mixed-language replies. Results are reported by group.

The unit tests run this eval against two fake models. One always gives the labeled answer and must score 100%. The other always tries to impute, and the code guardrail must block it on every protected column. Real-model scores are in [`results/llm_eval.md`](results/llm_eval.md), and every call behind them, with its sanitised prompt and response, is in `results/llm_eval_calls.jsonl`.

**Without an API key:** `--backend claude-cli` sends the same prompts through `claude -p`, which runs on a Claude subscription login. The reclassification schema is passed as `--json-schema`, built-in tools are switched off, and the system prompt is replaced. Temperature can't be set on this path, which is why `--repeats` reports how often the model gives the same answer.
