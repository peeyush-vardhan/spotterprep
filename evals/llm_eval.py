"""
llm_eval.py — Does the Iteration 2 reclassification step do what the analyst meant?

Runs every labeled case in evals/data/llm_reclassification_cases.json through
LLMClient.reclassify() and reports:

  Valid output     share of calls whose tool output passed schema validation
  Action accuracy  final recommended action is one the label accepts
  Level follows    the model's own confidence level matches the level its action implies
  definition       under the definition in spotterprep/llm.py. Code corrects any mismatch,
                   so this measures whether the model understood the definition.
  Guardrail        no monetary or personal-data issue ends with an imputation action,
                   plus how often the code guardrail had to override the model

Labels list acceptable actions only. The expected confidence level follows from the action
(spotterprep.llm.required_level), so it is never labeled separately.

Two ways to reach the model:
  --backend api         Anthropic API; needs ANTHROPIC_API_KEY. Temperature 0.
  --backend claude-cli  The Claude Code CLI on a Claude subscription login, no API key.
                        Temperature can't be set, so use --repeats to measure stability.

Results go to evals/results/llm_eval.{json,md}.

Usage:
  python evals/llm_eval.py --repeats 3
  python evals/llm_eval.py --backend claude-cli --model sonnet --repeats 3
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

from spotterprep.llm import DEFAULT_MODEL, LLMClient, is_protected_column, required_level  # noqa: E402

CASES_PATH = ROOT / "evals" / "data" / "llm_reclassification_cases.json"
_IMPUTE = {"IMPUTE_MEDIAN", "IMPUTE_MODE"}
_PROTECTED_TYPES = {"NULL_MONETARY", "NULL_PII", "NEGATIVE_MONETARY"}


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return json.loads(path.read_text())


def run(llm: LLMClient, cases: list[dict], repeats: int = 1, backend: str = "api") -> dict:
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
                "id": case["id"], "difficulty": case.get("difficulty", "standard"), "kind": case.get("kind", "-"),
                "valid": out.get("valid", True),
                "level": out["confidence_level"], "action": out["recommended_action"],
                "model_level": out.get("model_confidence_level", out["confidence_level"]),
                "level_ok": out["confidence_level"] == required_level(issue, out["recommended_action"]),
                "model_level_ok": out.get("model_confidence_level", out["confidence_level"])
                == required_level(issue, out["recommended_action"]),
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
        "model": llm.model, "backend": backend,
        "temperature": "0" if backend == "api" else "not settable (Claude Code CLI)", "cases": len(cases), "calls": n, "repeats": repeats,
        "valid_output_rate": rate("valid"),
        "action_accuracy": rate("action_ok"),
        "model_level_follows_definition": rate("model_level_ok"),
        "final_level_follows_definition": rate("level_ok"),
        "level_corrections": sum(not r["model_level_ok"] for r in rows),
        "protected_calls": len(protected_rows),
        "unsafe_final_actions": sum(r["unsafe"] for r in rows),
        "guardrail_overrides": sum(r["guardrail_fired"] for r in rows),
        "failures": [r for r in rows if not (r["action_ok"] and r["model_level_ok"])],
        "actions_seen": dict(Counter(r["action"] for r in rows)),
    }
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["difficulty"], []).append(r)
        if r["difficulty"] == "hard":
            groups.setdefault(f"hard: {r['kind']}", []).append(r)
    result["by_group"] = {
        g: {"calls": len(rs), "action_accuracy": round(sum(x["action_ok"] for x in rs) / len(rs), 3),
            "model_level_follows_definition": round(sum(x["model_level_ok"] for x in rs) / len(rs), 3)}
        for g, rs in sorted(groups.items())
    }
    if repeats > 1:
        stable = [r["stable"] for r in rows if "stable" in r]
        result["stable_case_rate"] = round(sum(stable) / len(stable), 3)
    return result


def to_markdown(r: dict) -> str:
    pct = lambda x: "n/a" if x is None else f"{x * 100:.1f}%"  # noqa: E731
    lines = [
        "# LLM eval: Iteration 2 reclassification", "",
        f"Model `{r['model']}` via {r.get('backend', 'api')} (temperature: {r.get('temperature', '0')}), "
        f"{r['cases']} labeled cases, {r['calls']} calls.", "",
        f"- **Valid structured output:** {pct(r['valid_output_rate'])}",
        f"- **Recommended action accuracy:** {pct(r['action_accuracy'])}",
        f"- **Model's confidence level follows the definition:** {pct(r['model_level_follows_definition'])}"
        f" ({r['level_corrections']} corrected in code; final levels {pct(r['final_level_follows_definition'])})",
        f"- **Unsafe final actions on monetary/PII issues:** {r['unsafe_final_actions']} of {r['protected_calls']}"
        f" (code guardrail overrode the model {r['guardrail_overrides']} times)",
    ]
    if "stable_case_rate" in r:
        lines.append(f"- **Same answer on every repeat:** {pct(r['stable_case_rate'])} of cases")
    if r.get("by_group"):
        lines += ["", "## By difficulty", "", "| Group | Calls | Action accuracy | Level follows definition |",
                  "|---|---|---|---|"]
        lines += [f"| {g} | {v['calls']} | {pct(v['action_accuracy'])} | {pct(v['model_level_follows_definition'])} |"
                  for g, v in r["by_group"].items()]
    if r["failures"]:
        lines += ["", "## Misses", "", "| Case | Kind | Model level | Final level | Action | Action OK |", "|---|---|---|---|---|---|"]
        lines += [f"| {f['id']} | {f['kind']} | {f['model_level']} | {f['level']} | {f['action']} | {'yes' if f['action_ok'] else 'no'} |"
                  for f in r["failures"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--backend", choices=["api", "claude-cli"], default="api")
    ap.add_argument("--model", default=None, help=f"API default: {DEFAULT_MODEL}; CLI default: your Claude Code default")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--out", default=str(ROOT / "evals" / "results"))
    args = ap.parse_args()
    log = Path(args.out) / "llm_eval_calls.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("")  # one log per run, so the committed log matches the committed results
    if args.backend == "api":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("ANTHROPIC_API_KEY is not set. Use --backend claude-cli to run on a Claude subscription instead.")
        from spotterprep.llm import make_client
        llm = make_client(model=args.model or DEFAULT_MODEL, log_path=log)
    else:
        from spotterprep.claude_cli import ClaudeCLIClient
        llm = LLMClient(client=ClaudeCLIClient(), model=args.model or "", log_path=log)
    result = run(llm, load_cases(), repeats=args.repeats, backend=args.backend)
    if args.backend == "claude-cli":
        # The CLI also uses a small model for housekeeping, so name the requested model when there is one.
        result["models_seen"] = sorted(llm.client.messages.models_seen)
        result["model"] = args.model or ", ".join(result["models_seen"]) or "Claude Code default"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "llm_eval.json").write_text(json.dumps(result, indent=2))
    md = to_markdown(result)
    (out / "llm_eval.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
