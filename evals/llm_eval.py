"""
llm_eval.py — Does the Iteration 2 reclassification step do what the analyst meant?

Runs every labeled case in evals/data/llm_reclassification_cases.json through
LLMClient.reclassify() and reports:

  Valid output     share of calls whose tool output passed schema validation
  Level accuracy   final confidence level is one the label accepts
  Action accuracy  final recommended action is one the label accepts
  Guardrail        no monetary or personal-data issue ends with an imputation action,
                   plus how often the code guardrail had to override the model

Needs ANTHROPIC_API_KEY. Results go to evals/results/llm_eval.{json,md}.

Usage:
  python evals/llm_eval.py
  python evals/llm_eval.py --model claude-sonnet-4-6 --repeats 3   # check run-to-run stability
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from spotterprep.llm import DEFAULT_MODEL, LLMClient, is_protected_column  # noqa: E402

CASES_PATH = ROOT / "evals" / "data" / "llm_reclassification_cases.json"
_IMPUTE = {"IMPUTE_MEDIAN", "IMPUTE_MODE"}
_PROTECTED_TYPES = {"NULL_MONETARY", "NULL_PII", "NEGATIVE_MONETARY"}


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return json.loads(path.read_text())


def run(llm: LLMClient, cases: list[dict], repeats: int = 1) -> dict:
    rows = []
    for case in cases:
        outcomes = []
        for _ in range(repeats):
            issue = dict(case["issue"])
            out = llm.reclassify(issue, case["question"], case["answer"], case["table"])
            outcomes.append(out)
        exp = case["expected"]
        protected = issue["issue_type"] in _PROTECTED_TYPES or is_protected_column(issue["column"])
        for out in outcomes:
            rows.append({
                "id": case["id"], "valid": out.get("valid", True),
                "level": out["confidence_level"], "action": out["recommended_action"],
                "level_ok": out["confidence_level"] in exp["confidence_levels"],
                "action_ok": out["recommended_action"] in exp["recommended_actions"],
                "protected": protected,
                "unsafe": protected and out["recommended_action"] in _IMPUTE,
                "guardrail_fired": bool(out.get("guardrail")),
            })
        if repeats > 1:
            rows[-1]["stable"] = len({(o["confidence_level"], o["recommended_action"]) for o in outcomes}) == 1

    n = len(rows)
    rate = lambda k: round(sum(r[k] for r in rows) / n, 3) if n else None  # noqa: E731
    protected_rows = [r for r in rows if r["protected"]]
    result = {
        "model": llm.model, "cases": len(cases), "calls": n, "repeats": repeats,
        "valid_output_rate": rate("valid"),
        "level_accuracy": rate("level_ok"),
        "action_accuracy": rate("action_ok"),
        "both_correct": round(sum(r["level_ok"] and r["action_ok"] for r in rows) / n, 3) if n else None,
        "protected_calls": len(protected_rows),
        "unsafe_final_actions": sum(r["unsafe"] for r in rows),
        "guardrail_overrides": sum(r["guardrail_fired"] for r in rows),
        "failures": [r for r in rows if not (r["level_ok"] and r["action_ok"])],
        "actions_seen": dict(Counter(r["action"] for r in rows)),
    }
    if repeats > 1:
        stable = [r["stable"] for r in rows if "stable" in r]
        result["stable_case_rate"] = round(sum(stable) / len(stable), 3)
    return result


def to_markdown(r: dict) -> str:
    pct = lambda x: "n/a" if x is None else f"{x * 100:.1f}%"  # noqa: E731
    lines = [
        "# LLM eval: Iteration 2 reclassification", "",
        f"Model `{r['model']}`, {r['cases']} labeled cases, {r['calls']} calls.", "",
        f"- **Valid structured output:** {pct(r['valid_output_rate'])}",
        f"- **Confidence level accuracy:** {pct(r['level_accuracy'])}",
        f"- **Recommended action accuracy:** {pct(r['action_accuracy'])}",
        f"- **Both correct:** {pct(r['both_correct'])}",
        f"- **Unsafe final actions on monetary/PII issues:** {r['unsafe_final_actions']} of {r['protected_calls']}"
        f" (code guardrail overrode the model {r['guardrail_overrides']} times)",
    ]
    if "stable_case_rate" in r:
        lines.append(f"- **Same answer on every repeat:** {pct(r['stable_case_rate'])} of cases")
    if r["failures"]:
        lines += ["", "## Disagreements with the label", "", "| Case | Level | Action |", "|---|---|---|"]
        lines += [f"| {f['id']} | {f['level']} | {f['action']} |" for f in r["failures"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--out", default=str(ROOT / "evals" / "results"))
    args = ap.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. This eval calls the model; see evals/README.md.")
    from spotterprep.llm import make_client
    llm = make_client(model=args.model, log_path=Path(args.out) / "llm_eval_calls.jsonl")
    result = run(llm, load_cases(), repeats=args.repeats)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "llm_eval.json").write_text(json.dumps(result, indent=2))
    md = to_markdown(result)
    (out / "llm_eval.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
