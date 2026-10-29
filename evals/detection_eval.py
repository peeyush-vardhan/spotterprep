"""
detection_eval.py — How well does Iteration 1 find the issues we know are there?

The generators inject issues at known columns and rates and log them. This eval runs
the Iteration 1 detector on each raw table and scores it against that log:

  Recall      share of injected single-column issues the detector found, with the
              right issue family on the right column.
  Precision   share of detections that correspond to a logged injected issue.
              Read this as a lower bound: the filler columns carry incidental
              noise (e.g. random nulls) that is real but was never logged.
  Safety      share of detected issues on monetary or personal-data columns that the
              detector classifies LOW confidence, i.e. never auto-fixed. Target: 100%.
  Precision by confidence level, to check that HIGH-confidence detections are
              more often real than MEDIUM or LOW ones.

Usage:
  python evals/detection_eval.py                 # uses existing data/ (run the generators first)
  python evals/detection_eval.py --out evals/results
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals.ground_truth import DATASETS, FAMILY_TO_DETECTOR_TYPES, load_ground_truth, read_raw  # noqa: E402
from spotterprep.iteration1_confidence import score_issues  # noqa: E402

_TYPE_TO_FAMILIES: dict[str, set[str]] = defaultdict(set)
for _fam, _types in FAMILY_TO_DETECTOR_TYPES.items():
    for _t in _types:
        _TYPE_TO_FAMILIES[_t].add(_fam)

_SENSITIVE_DETECTOR_TYPES = {"NULL_MONETARY", "NULL_PII", "NEGATIVE_MONETARY"}

# The generators pad every table with numbered filler columns (acct_attr_1 ... content_attr_130)
# to reach enterprise width. Their randomness, such as blank cells, is real but never logged.
_FILLER_COL = re.compile(r"_attr_\d+$")


def _detection_columns(detection: dict) -> set[str]:
    return set(re.findall(r"[A-Za-z][A-Za-z0-9_]*", detection["column"]))


def run(data_dir: Path, sample_rows: int = 10_000) -> dict:
    detections: dict[str, list[dict]] = {}
    table_columns: dict[str, list[str]] = {}
    for idx, stem, table in DATASETS:
        df = read_raw(data_dir, idx, stem)
        table_columns[table] = list(df.columns)
        with contextlib.redirect_stdout(io.StringIO()):
            detections[table] = score_issues(df, table_name=table, sample_rows=sample_rows)["issues"]

    truth = load_ground_truth(data_dir, table_columns)
    scored = [t for t in truth if t.scope == "detector"]

    # Recall: for each injected issue, is there a detection of a matching family on one of its columns?
    per_issue = []
    matched_detection_ids: set[int] = set()
    for t in scored:
        hit = False
        for d in detections[t.table]:
            if t.family in _TYPE_TO_FAMILIES.get(d["issue_type"], set()) and _detection_columns(d) & set(t.columns):
                hit = True
                matched_detection_ids.add(id(d))
        per_issue.append({"table": t.table, "issue": t.issue, "family": t.family,
                          "columns": t.columns, "detected": hit})

    recall_by_family: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in per_issue:
        recall_by_family[r["family"]][1] += 1
        recall_by_family[r["family"]][0] += int(r["detected"])

    # Precision: does each detection correspond to a logged injected issue? A detection counts when it
    # matched a scored issue above, or when it is a logic/range detection on a cross-column issue's columns.
    cross_cols = defaultdict(set)
    for t in truth:
        if t.scope == "cross_column":
            cross_cols[t.table].update(t.columns)
    by_level: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    total_det = matched = 0
    named_det = named_matched = 0
    for table, dets in detections.items():
        for d in dets:
            total_det += 1
            real = id(d) in matched_detection_ids or (
                d["issue_type"] in {"LOGIC_VIOLATION", "PHYSICAL_RANGE_VIOLATION"}
                and bool(_detection_columns(d) & cross_cols[table])
            )
            matched += int(real)
            if not any(_FILLER_COL.search(c) for c in _detection_columns(d)):
                named_det += 1
                named_matched += int(real)
            by_level[d["confidence_level"]][1] += 1
            by_level[d["confidence_level"]][0] += int(real)

    # Safety: detections on monetary / personal-data columns must be LOW (never auto-fixed).
    sensitive = [d for dets in detections.values() for d in dets if d["issue_type"] in _SENSITIVE_DETECTOR_TYPES]
    sensitive_low = sum(1 for d in sensitive if d["confidence_level"] == "LOW")

    detected = sum(int(r["detected"]) for r in per_issue)
    return {
        "injected_total": len(truth),
        "scope_counts": {s: sum(1 for t in truth if t.scope == s) for s in ("detector", "cross_column", "out_of_scope")},
        "recall": round(detected / len(per_issue), 3) if per_issue else None,
        "detected": detected,
        "in_scope": len(per_issue),
        "recall_by_family": {f: {"detected": h, "total": n, "recall": round(h / n, 3)}
                             for f, (h, n) in sorted(recall_by_family.items())},
        "precision_vs_logged": round(matched / total_det, 3) if total_det else None,
        "detections_total": total_det,
        "precision_named_columns": round(named_matched / named_det, 3) if named_det else None,
        "detections_named_columns": named_det,
        "precision_by_confidence": {lvl: {"matched": h, "total": n, "precision": round(h / n, 3)}
                                    for lvl, (h, n) in sorted(by_level.items())},
        "safety_low_on_sensitive": {"low": sensitive_low, "total": len(sensitive),
                                    "rate": round(sensitive_low / len(sensitive), 3) if sensitive else None},
        "missed": [r for r in per_issue if not r["detected"]],
        "excluded": [{"table": t.table, "issue": t.issue, "scope": t.scope, "column": t.column_ref}
                     for t in truth if t.scope != "detector"],
    }


def to_markdown(r: dict) -> str:
    pct = lambda x: "n/a" if x is None else f"{x * 100:.1f}%"  # noqa: E731
    lines = [
        "# Detection eval: Iteration 1 vs injected ground truth", "",
        f"- **Recall:** {pct(r['recall'])} ({r['detected']} of {r['in_scope']} single-column issues found)",
        f"- **Precision vs logged issues:** {pct(r['precision_vs_logged'])} of {r['detections_total']} detections"
        " (lower bound; filler columns carry unlogged noise)",
        f"- **Precision excluding filler columns:** {pct(r['precision_named_columns'])}"
        f" of {r['detections_named_columns']} detections on the tables' named business columns",
        f"- **Safety:** {pct(r['safety_low_on_sensitive']['rate'])} of {r['safety_low_on_sensitive']['total']}"
        " monetary/PII detections classified LOW (never auto-fixed)",
        f"- **Ground truth:** {r['injected_total']} injected issues; scored {r['scope_counts']['detector']},"
        f" cross-column {r['scope_counts']['cross_column']} (Iteration 5 and cleaning rules),"
        f" out of scope {r['scope_counts']['out_of_scope']}", "",
        "## Recall by issue family", "", "| Family | Found | Recall |", "|---|---|---|",
    ]
    lines += [f"| {f} | {v['detected']} / {v['total']} | {pct(v['recall'])} |" for f, v in r["recall_by_family"].items()]
    lines += ["", "## Precision by confidence level", "", "| Level | Matched | Precision |", "|---|---|---|"]
    lines += [f"| {lvl} | {v['matched']} / {v['total']} | {pct(v['precision'])} |"
              for lvl, v in r["precision_by_confidence"].items()]
    lines += ["", "## Missed issues", "", "| Table | Issue | Family | Columns |", "|---|---|---|---|"]
    lines += [f"| {m['table']} | {m['issue']} | {m['family']} | {', '.join(m['columns'])} |" for m in r["missed"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "evals" / "results"))
    args = ap.parse_args()
    result = run(Path(args.data))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "detection_eval.json").write_text(json.dumps(result, indent=2))
    md = to_markdown(result)
    (out / "detection_eval.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
