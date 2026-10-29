"""
reproduce_results.py — Regenerate the README results table from code.

Generates the five datasets at a stated scale, scores every raw table and its
cleaned counterpart with spotterprep/quality_scorer.py, and writes the table to
evals/results/quality_scores.{md,json}. Every number in the README's results
section comes from this script, so anyone can rerun it and check.

Usage:
  python evals/reproduce_results.py --scale 0.02          # ~2 minutes, ~750 MB on disk
  python evals/reproduce_results.py --skip-generate       # score data/ as it already is
  python evals/reproduce_results.py --scale 1.0           # full size: ~19 GB, 45-90 minutes
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals.ground_truth import DATASETS, read_raw  # noqa: E402
from spotterprep.quality_scorer import compute_quality_score  # noqa: E402


def generate(scale: float) -> None:
    env = {**os.environ, "SPOTTERPREP_SCALE": str(scale)}
    subprocess.run([sys.executable, str(ROOT / "data_generation" / "generate_all.py")],
                   env=env, check=True, stdout=subprocess.DEVNULL)


def score_all(data_dir: Path, sample_rows: int) -> list[dict]:
    rows = []
    for idx, stem, table in DATASETS:
        raw = read_raw(data_dir, idx, stem, "raw")
        clean = read_raw(data_dir, idx, stem, "cleaned")
        with contextlib.redirect_stdout(io.StringIO()):
            before = compute_quality_score(raw, table_name=table, sample_rows=sample_rows)
            after = compute_quality_score(clean, table_name=table, sample_rows=sample_rows)
        rows.append({
            "table": table, "rows_raw": len(raw), "rows_clean": len(clean), "columns": raw.shape[1],
            "raw_score": before["overall_score"], "raw_grade": before["grade"],
            "clean_score": after["overall_score"], "clean_grade": after["grade"],
            "raw_dimensions": before["dimensions"], "clean_dimensions": after["dimensions"],
        })
    return rows


def to_markdown(rows: list[dict], meta: dict) -> str:
    source = "from existing data" if meta["scale"] is None else f"at scale {meta['scale']}"
    lines = [
        "# Quality scores: raw vs cleaned", "",
        f"Generated {meta['generated_at']} {source} "
        f"(scored on a seeded sample of up to {meta['sample_rows']:,} rows per table).", "",
        "| Dataset | Rows (raw) | Columns | Raw score | Clean score | Change |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['table']} | {r['rows_raw']:,} | {r['columns']} | {r['raw_score']:.1f} ({r['raw_grade']}) "
                     f"| {r['clean_score']:.1f} ({r['clean_grade']}) | {r['clean_score'] - r['raw_score']:+.1f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--scale", type=float, default=0.02, help="Dataset size relative to full scale")
    ap.add_argument("--skip-generate", action="store_true", help="Score the existing data/ folder")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--sample-rows", type=int, default=10_000)
    ap.add_argument("--out", default=str(ROOT / "evals" / "results"))
    args = ap.parse_args()

    if not args.skip_generate:
        generate(args.scale)
    rows = score_all(Path(args.data), args.sample_rows)
    meta = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "scale": None if args.skip_generate else args.scale, "sample_rows": args.sample_rows}

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "quality_scores.json").write_text(json.dumps({"meta": meta, "results": rows}, indent=2))
    md = to_markdown(rows, meta)
    (out / "quality_scores.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
