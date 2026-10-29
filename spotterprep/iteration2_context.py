#!/usr/bin/env python3
"""
spotterprep/iteration2_context.py — SpotterPrep Live Iteration 2
====================================================
Runs the real AI-powered context conversation for any CSV table.

Flow:
  1. Loads the CSV and runs Iteration 1 (structural scan via confidence_scorer.py)
  2. Uses Claude to generate one targeted question per MEDIUM/LOW confidence issue
  3. You answer in the terminal — concrete examples from your actual data, not statistics
  4. Claude updates the confidence map based on your answers
  5. Saves the enriched confidence map ready for Iterations 3–5

Usage:
  python spotterprep/iteration2_context.py data/raw/dataset1_customer_orders.csv
  python spotterprep/iteration2_context.py data/raw/dataset1_customer_orders.csv --table CUSTOMER_ORDERS
  python spotterprep/iteration2_context.py data/raw/dataset1_customer_orders.csv --nrows 20000 --pk order_id

Requirements:
  pip install anthropic pandas numpy
  export ANTHROPIC_API_KEY=your_key
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

# Add project root to path so `spotterprep` imports resolve when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from spotterprep.iteration1_confidence import score_issues, print_confidence_report  # noqa: E402
from spotterprep.llm import DEFAULT_MODEL, LLMClient, make_client, sanitise_issue  # noqa: E402

# Prompts, structured output, validation, retries, guardrails and the call log all live in
# spotterprep/llm.py. Kept as an alias for docs/06_pii_policy.md.
_sanitise_for_llm = sanitise_issue


# ── Terminal formatting ───────────────────────────────────────────────────────

_BLUE   = "\033[94m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_GRAY   = "\033[90m"
_RED    = "\033[91m"
_RESET  = "\033[0m"


def _print_sp(text: str) -> None:
    """Print a SpotterPrep message with a character-by-character typing effect."""
    print(f"\n  {_BLUE}SpotterPrep:{_RESET} ", end="", flush=True)
    for ch in text:
        print(ch, end="", flush=True)
        time.sleep(0.010)
    print()


def _print_divider(label: str = "") -> None:
    line = "─" * 58
    if label:
        print(f"\n  {_GRAY}{line}")
        print(f"  {label}")
        print(f"  {line}{_RESET}")
    else:
        print(f"  {_GRAY}{line}{_RESET}")


def _print_score_bar(label: str, score: float, grade: str) -> None:
    grade_color = _GREEN if grade == "A" else _YELLOW if grade in ("B", "C") else _RED
    filled = int(score / 2)
    bar = f"{_GREEN}{'█' * filled}{_GRAY}{'░' * (50 - filled)}{_RESET}"
    print(f"\n  {label}: {grade_color}{score:.1f} / 100  Grade {grade}{_RESET}")
    print(f"  [{bar}]")


def _estimate_score(confidence_map: dict) -> tuple[float, str]:
    """Rough quality estimate from confidence map for display — not a real score."""
    total = confidence_map.get("total_rows", 1) or 1
    issues = confidence_map.get("issues", [])
    if not issues:
        return 100.0, "A"
    # Pessimistic: assume worst issue affects a unique set of rows
    max_affected = max((i["count"] for i in issues), default=0)
    pct_clean = max(0.0, 1.0 - max_affected / total)
    score = round(pct_clean * 100, 1)
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 45 else "F"
    return score, grade


# ── Main ─────────────────────────────────────────────────────────────────────

def run_iter2(
    csv_path: str,
    table_name: str = None,
    pk_column: str = None,
    nrows: int = 50_000,
    model: str = DEFAULT_MODEL,
    llm: LLMClient | None = None,
) -> dict:

    # ── API key check ─────────────────────────────────────────────────────
    if llm is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(f"\n  {_RED}Error:{_RESET} ANTHROPIC_API_KEY not set.")
            print("  Run: export ANTHROPIC_API_KEY=your_key\n")
            sys.exit(1)
        llm = make_client(model=model)

    # ── Load CSV ──────────────────────────────────────────────────────────
    print(f"\n  Loading {csv_path} ...")
    try:
        df = pd.read_csv(csv_path, nrows=nrows, keep_default_na=False, na_values=[""], low_memory=False)
    except FileNotFoundError:
        print(f"\n  {_RED}Error:{_RESET} File not found — {csv_path}\n")
        sys.exit(1)

    # Infer table name from filename if not provided
    if not table_name:
        stem = Path(csv_path).stem.upper()
        for suffix in ("_RAW", "_CLEAN", "_CLEANED"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        table_name = stem

    print(f"  {_GRAY}Table: {table_name}  ·  {len(df):,} rows × {len(df.columns)} columns{_RESET}")

    # ── ITERATION 1: Structural Scan ──────────────────────────────────────
    _print_divider("ITERATION 1 — Structural Scan")
    confidence_map = score_issues(df, table_name=table_name, pk_column=pk_column)
    print_confidence_report(confidence_map)

    raw_score, raw_grade = _estimate_score(confidence_map)
    _print_score_bar("Quality score (raw)", raw_score, raw_grade)

    needs_context = [
        i for i in confidence_map["issues"]
        if i["confidence_level"] in ("MEDIUM", "LOW")
    ]

    if not needs_context:
        _print_sp(
            f"All {confidence_map['summary']['HIGH']} issues are high confidence. "
            "No context questions needed — ready for Iteration 3."
        )
        return confidence_map

    # ── ITERATION 2: Context Conversation ─────────────────────────────────
    _print_divider("ITERATION 2 — Context Conversation")

    high_count = confidence_map["summary"]["HIGH"]
    n = len(needs_context)
    _print_sp(
        f"I've scanned {table_name}. "
        f"I found {confidence_map['total_issues']} issues. "
        f"I'm confident about {high_count} of them and ready to fix those. "
        f"But before I touch anything, I need to understand "
        f"{n} thing{'s' if n > 1 else ''} about your data. Can I ask?"
    )

    try:
        input(f"\n  {_GRAY}Press Enter to begin...{_RESET}")
    except KeyboardInterrupt:
        print("\n\n  Session ended.\n")
        return confidence_map

    context_log = []

    for idx, issue in enumerate(needs_context, 1):
        _print_divider(
            f"Question {idx} of {n}  ·  {issue['column']}  ·  {issue['issue_type']}"
        )

        # Generate question via Claude
        print(f"  {_GRAY}(thinking...){_RESET}", end="\r", flush=True)
        question = llm.generate_question(issue, table_name)
        _print_sp(question)

        # Get analyst answer
        print(f"\n  {_YELLOW}You:{_RESET} ", end="", flush=True)
        try:
            answer = input().strip() or "(no response)"
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Session ended.\n")
            break

        # Parse answer and update confidence map
        print(f"  {_GRAY}(updating confidence map...){_RESET}", end="\r", flush=True)
        update = llm.reclassify(issue, question, answer, table_name)

        old_level = issue["confidence_level"]
        issue["confidence_level"]   = update["confidence_level"]
        issue["recommended_action"] = update["recommended_action"]
        issue["context_note"]       = update.get("context_note", "")
        issue["analyst_answer"]     = answer
        issue["iter2_question"]     = question

        changed = old_level != update["confidence_level"]
        if update.get("guardrail"):
            print(f"  {_YELLOW}! Guardrail:{_RESET} {update['guardrail']}" + " " * 20)
        if not update.get("valid", True):
            print(f"  {_RED}! Model output failed validation; issue left unchanged{_RESET}" + " " * 20)
        elif changed:
            print(
                f"  {_GREEN}✓ Reclassified:{_RESET} {old_level} → {update['confidence_level']}  "
                f"·  action: {update['recommended_action']}" + " " * 20
            )
        else:
            print(
                f"  {_GRAY}✓ Noted — action: {update['recommended_action']}{_RESET}" + " " * 20
            )

        context_log.append({
            "column":           issue["column"],
            "issue_type":       issue["issue_type"],
            "question":         question,
            "answer":           answer,
            "old_confidence":   old_level,
            "new_confidence":   update["confidence_level"],
            "recommended_action": update["recommended_action"],
            "context_note":     update.get("context_note", ""),
            "valid":            update.get("valid", True),
            "guardrail":        update.get("guardrail"),
        })

    # ── Rebuild summary ───────────────────────────────────────────────────
    new_summary: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for i in confidence_map["issues"]:
        new_summary[i["confidence_level"]] += 1
    confidence_map["summary"]        = new_summary
    confidence_map["iter2_complete"] = True
    confidence_map["iter2_context"]  = context_log

    # ── Completion message ────────────────────────────────────────────────
    _print_divider("ITERATION 2 — Complete")

    upgraded = sum(
        1 for e in context_log
        if e["old_confidence"] in ("MEDIUM", "LOW") and e["new_confidence"] == "HIGH"
    )

    msg = "Context conversation complete. "
    if upgraded:
        msg += (
            f"{upgraded} issue{'s' if upgraded > 1 else ''} reclassified to HIGH confidence "
            "based on your answers. "
        )
    msg += f"Ready for Iteration 3: {new_summary['HIGH']} high-confidence fix{'es' if new_summary['HIGH'] != 1 else ''} to propose."
    _print_sp(msg)

    # ── Save updated confidence map ───────────────────────────────────────
    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"confidence_map_{table_name.lower()}.json"

    with open(out_path, "w") as f:
        json.dump(confidence_map, f, indent=2, default=str)

    print(f"\n  {_GREEN}✓ Confidence map saved →{_RESET} {out_path}")
    print(
        f"  {_GRAY}HIGH: {new_summary['HIGH']}  ·  "
        f"MEDIUM: {new_summary['MEDIUM']}  ·  "
        f"LOW: {new_summary['LOW']}{_RESET}\n"
    )

    return confidence_map


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SpotterPrep — Iteration 2: AI-powered context conversation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python spotterprep/iteration2_context.py data/raw/dataset1_customer_orders.csv
  python spotterprep/iteration2_context.py data/raw/dataset1_customer_orders.csv --table CUSTOMER_ORDERS
  python spotterprep/iteration2_context.py data/raw/dataset1_customer_orders.csv --nrows 20000 --pk order_id
        """,
    )
    parser.add_argument("csv_path", help="Path to the raw CSV file")
    parser.add_argument("--table",  help="Table name (defaults to filename stem)")
    parser.add_argument("--pk",     help="Primary key column name (auto-detected if omitted)")
    parser.add_argument("--nrows",  type=int, default=50_000,
                        help="Rows to scan (default: 50,000)")
    parser.add_argument("--model",  default=DEFAULT_MODEL,
                        help=f"Claude model to use (default: {DEFAULT_MODEL}; or set SPOTTERPREP_MODEL)")

    args = parser.parse_args()

    run_iter2(
        csv_path=args.csv_path,
        table_name=args.table,
        pk_column=args.pk,
        nrows=args.nrows,
        model=args.model,
    )
