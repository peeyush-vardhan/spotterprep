"""
confidence_scorer.py — SpotterPrep Confidence Scorer
=====================================================
Implements Iteration 1 of the multi-iteration cleaning model.

Scans a DataFrame and classifies every detected issue as:
  HIGH   — AI can act autonomously (>90% confidence)
  MEDIUM — AI needs business context before acting
  LOW    — Human decision required (monetary, PII, business rules)

Returns a structured confidence map (dict) that drives iterations 2–5.

Usage:
  from spotterprep.iteration1_confidence import score_issues, print_confidence_report

  import pandas as pd
  df = pd.read_csv("data/raw/dataset1_customer_orders.csv", nrows=10_000)
  confidence_map = score_issues(df, table_name="CUSTOMER_ORDERS", pk_column="order_id")
  print_confidence_report(confidence_map)
"""

import re
import json
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd


# ── Issue type constants ───────────────────────────────────────────────────

class IssueType:
    DUPLICATE_PK             = "DUPLICATE_PK"
    NULL_MONETARY            = "NULL_MONETARY"
    NULL_PII                 = "NULL_PII"
    NULL_CRITICAL            = "NULL_CRITICAL"
    NULL_NON_CRITICAL        = "NULL_NON_CRITICAL"
    NEGATIVE_MONETARY        = "NEGATIVE_MONETARY"
    NEGATIVE_NUMERIC         = "NEGATIVE_NUMERIC"
    MALFORMED_EMAIL          = "MALFORMED_EMAIL"
    FUTURE_DATE              = "FUTURE_DATE"
    IMPOSSIBLE_TEMPORAL      = "IMPOSSIBLE_TEMPORAL"
    CATEGORICAL_INCONSISTENCY = "CATEGORICAL_INCONSISTENCY"
    STATISTICAL_OUTLIER      = "STATISTICAL_OUTLIER"
    PHYSICAL_RANGE_VIOLATION = "PHYSICAL_RANGE_VIOLATION"
    LOGIC_VIOLATION          = "LOGIC_VIOLATION"
    TYPE_INCONSISTENCY       = "TYPE_INCONSISTENCY"
    WHITESPACE               = "WHITESPACE"


# ── Confidence rules ───────────────────────────────────────────────────────
# Maps issue type → (confidence_level, confidence_score 0.0–1.0)
# Score reflects how certain the AI is that this is an error (not a legitimate value).

_CONFIDENCE_RULES = {
    IssueType.DUPLICATE_PK:              ("HIGH",   0.99),  # duplicate PK is always wrong
    IssueType.IMPOSSIBLE_TEMPORAL:       ("HIGH",   0.97),  # start > end is objectively impossible
    IssueType.MALFORMED_EMAIL:           ("HIGH",   0.95),  # regex is deterministic
    IssueType.WHITESPACE:                ("HIGH",   0.98),  # trim is always safe
    IssueType.TYPE_INCONSISTENCY:        ("HIGH",   0.91),  # coercion to dominant type is safe
    IssueType.NEGATIVE_NUMERIC:          ("HIGH",   0.92),  # negative non-monetary = data error
    IssueType.CATEGORICAL_INCONSISTENCY: ("HIGH",   0.90),  # canonical form confirmed in iter 2
    IssueType.NULL_NON_CRITICAL:         ("HIGH",   0.90),  # low null rate, imputable
    IssueType.FUTURE_DATE:               ("MEDIUM", 0.72),  # could be a scheduled event
    IssueType.STATISTICAL_OUTLIER:       ("MEDIUM", 0.68),  # needs domain bounds confirmation
    IssueType.PHYSICAL_RANGE_VIOLATION:  ("MEDIUM", 0.74),  # needs physical limits confirmed
    IssueType.LOGIC_VIOLATION:           ("MEDIUM", 0.70),  # could be ETL bug or valid exception
    IssueType.NULL_CRITICAL:             ("MEDIUM", 0.65),  # high null rate — intent unclear
    IssueType.NEGATIVE_MONETARY:         ("LOW",    0.45),  # could be refund or credit memo
    IssueType.NULL_MONETARY:             ("LOW",    0.30),  # cannot impute — accounting integrity
    IssueType.NULL_PII:                  ("LOW",    0.25),  # cannot fabricate personal data
}

# ── Column name pattern matchers ───────────────────────────────────────────

_MONETARY_COL   = re.compile(r'amount|price|revenue|cost|salary|pay|fee|charge|balance|debit|credit|arr|mrr|ltv|cac', re.I)
_PII_COL        = re.compile(r'(?:^|_)(?:name|email|phone|address|ssn|dob|birth|passport)(?:_|$)', re.I)
_PK_COL         = re.compile(r'(?:^|_)id$|_key$|_pk$', re.I)
_TEMPORAL_COL   = re.compile(r'(?:^|_)(?:date|timestamp|time)(?:_|$)|_at$', re.I)
_EMAIL_FORMAT   = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _is_monetary(col_name: str) -> bool:
    return bool(_MONETARY_COL.search(col_name))


def _is_pii(col_name: str) -> bool:
    return bool(_PII_COL.search(col_name))


def _is_likely_pk(col_name: str) -> bool:
    return bool(_PK_COL.search(col_name))


def _is_temporal(col_name: str) -> bool:
    return bool(_TEMPORAL_COL.search(col_name))


# ── Issue factory ──────────────────────────────────────────────────────────

def _make_issue(
    column: str,
    issue_type: str,
    count: int,
    pct: float,
    detail: str,
    example_values: list = None,
) -> dict:
    level, score = _CONFIDENCE_RULES.get(issue_type, ("MEDIUM", 0.60))
    return {
        "column":             column,
        "issue_type":         issue_type,
        "count":              int(count),
        "pct":                round(float(pct), 4),
        "confidence_level":   level,
        "confidence_score":   score,
        "detail":             detail,
        "example_values":     (example_values or [])[:5],
        "recommended_action": _recommended_action(issue_type),
    }


def _recommended_action(issue_type: str) -> str:
    return {
        IssueType.DUPLICATE_PK:              "DEDUPLICATE_KEEP_FIRST",
        IssueType.NULL_MONETARY:             "FLAG_NULL_MONETARY",
        IssueType.NULL_PII:                  "PRESERVE_NULL",
        IssueType.NULL_CRITICAL:             "ESCALATE_TO_USER",
        IssueType.NULL_NON_CRITICAL:         "IMPUTE_MEDIAN",
        IssueType.NEGATIVE_MONETARY:         "ESCALATE_TO_USER",
        IssueType.NEGATIVE_NUMERIC:          "SET_ZERO_OR_ABS",
        IssueType.MALFORMED_EMAIL:           "NULLIFY_MALFORMED",
        IssueType.FUTURE_DATE:               "FLAG_SCHEDULED",
        IssueType.IMPOSSIBLE_TEMPORAL:       "DELETE_ROW",
        IssueType.CATEGORICAL_INCONSISTENCY: "STANDARDIZE_AFTER_CANONICAL_CONFIRMED",
        IssueType.STATISTICAL_OUTLIER:       "FLAG_OUTLIER_REVIEW",
        IssueType.PHYSICAL_RANGE_VIOLATION:  "ESCALATE_TO_USER",
        IssueType.LOGIC_VIOLATION:           "ESCALATE_TO_USER",
        IssueType.TYPE_INCONSISTENCY:        "COERCE_TO_DOMINANT_TYPE",
        IssueType.WHITESPACE:                "TRIM_WHITESPACE",
    }.get(issue_type, "ESCALATE_TO_USER")


# ── Per-column scanners ────────────────────────────────────────────────────

def _check_nulls(col_name: str, series: pd.Series) -> Optional[dict]:
    null_count = int(series.isna().sum())
    if null_count == 0:
        return None
    null_pct = null_count / len(series)

    if _is_monetary(col_name):
        return _make_issue(col_name, IssueType.NULL_MONETARY, null_count, null_pct,
                           f"{null_pct:.1%} null — monetary column, imputation would fabricate financial data")
    if _is_pii(col_name):
        return _make_issue(col_name, IssueType.NULL_PII, null_count, null_pct,
                           f"{null_pct:.1%} null — PII column, nulls may be legitimate opt-outs or contractors")
    if null_pct > 0.10:
        return _make_issue(col_name, IssueType.NULL_CRITICAL, null_count, null_pct,
                           f"{null_pct:.1%} null — high null rate, business context needed to determine intent")
    # Low null rate, non-PII, non-monetary — safe to impute
    return _make_issue(col_name, IssueType.NULL_NON_CRITICAL, null_count, null_pct,
                       f"{null_pct:.1%} null — low rate, statistical imputation appropriate")


def _check_duplicates(col_name: str, series: pd.Series) -> Optional[dict]:
    dup_count = int(series.duplicated(keep=False).sum())
    if dup_count == 0:
        return None
    dup_pct = dup_count / len(series)
    examples = list(series[series.duplicated(keep=False)].dropna().head(3).astype(str))
    return _make_issue(col_name, IssueType.DUPLICATE_PK, dup_count, dup_pct,
                       f"{dup_count} duplicate values in apparent PK column — deduplication is safe",
                       example_values=examples)


def _check_negatives(col_name: str, series: pd.Series) -> Optional[dict]:
    numeric = pd.to_numeric(series, errors="coerce")
    neg_mask = numeric < 0
    neg_count = int(neg_mask.sum())
    if neg_count == 0:
        return None
    neg_pct = neg_count / len(series)
    examples = [f"{v:.4g}" for v in numeric[neg_mask].head(3)]

    if _is_monetary(col_name):
        return _make_issue(col_name, IssueType.NEGATIVE_MONETARY, neg_count, neg_pct,
                           f"{neg_count} negative values — could be refunds/credit memos or entry errors",
                           example_values=examples)
    return _make_issue(col_name, IssueType.NEGATIVE_NUMERIC, neg_count, neg_pct,
                       f"{neg_count} negative values in non-monetary numeric column",
                       example_values=examples)


def _check_email(col_name: str, series: pd.Series) -> Optional[dict]:
    non_null = series.dropna().astype(str)
    if len(non_null) == 0:
        return None
    malformed = non_null[~non_null.apply(lambda x: bool(_EMAIL_FORMAT.match(x)))]
    count = len(malformed)
    if count == 0:
        return None
    return _make_issue(col_name, IssueType.MALFORMED_EMAIL, count, count / len(series),
                       f"{count} values fail RFC-5322 email format — regex check is deterministic",
                       example_values=list(malformed.head(3)))


def _check_future_dates(col_name: str, series: pd.Series) -> Optional[dict]:
    dates = pd.to_datetime(series, errors="coerce")
    now = pd.Timestamp.now()
    future_mask = dates > now
    count = int(future_mask.sum())
    if count == 0:
        return None
    examples = [str(d.date()) for d in dates[future_mask].dropna().head(3)]
    return _make_issue(col_name, IssueType.FUTURE_DATE, count, count / len(series),
                       f"{count} dates after {now.date()} — could be scheduled events or data errors",
                       example_values=examples)


def _check_whitespace(col_name: str, series: pd.Series) -> Optional[dict]:
    non_null = series.dropna().astype(str)
    if len(non_null) == 0:
        return None
    ws_mask = non_null != non_null.str.strip()
    count = int(ws_mask.sum())
    if count == 0:
        return None
    return _make_issue(col_name, IssueType.WHITESPACE, count, count / len(series),
                       f"{count} string values have leading/trailing whitespace — safe to trim",
                       example_values=[repr(v) for v in non_null[ws_mask].head(3)])


def _check_categorical_inconsistency(col_name: str, series: pd.Series) -> Optional[dict]:
    non_null = series.dropna().astype(str)
    if len(non_null) == 0 or non_null.nunique() > 50:
        return None  # Too many uniques — not a controlled vocabulary column

    # Find values that are case variants of each other
    lower_to_variants: dict = {}
    for val in non_null.unique():
        key = val.strip().lower()
        lower_to_variants.setdefault(key, set()).add(val)

    inconsistent_variants = []
    for variants in lower_to_variants.values():
        if len(variants) > 1:
            inconsistent_variants.extend(variants)

    if not inconsistent_variants:
        return None

    affected = int(non_null.isin(set(inconsistent_variants)).sum())
    return _make_issue(col_name, IssueType.CATEGORICAL_INCONSISTENCY, affected, affected / len(series),
                       f"Case variants detected — canonical form must be confirmed before standardising",
                       example_values=sorted(inconsistent_variants)[:6])


def _check_outliers(col_name: str, series: pd.Series) -> Optional[dict]:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if len(numeric) < 100:
        return None
    mean, std = float(numeric.mean()), float(numeric.std())
    if std == 0:
        return None
    z_scores = (numeric - mean) / std
    outlier_mask = z_scores.abs() > 3
    count = int(outlier_mask.sum())
    if count == 0:
        return None
    extremes = numeric[outlier_mask].sort_values()
    examples = [f"{v:.4g}" for v in list(extremes.head(2)) + list(extremes.tail(2))]
    return _make_issue(col_name, IssueType.STATISTICAL_OUTLIER, count, count / len(series),
                       f"{count} values >3σ from mean (μ={mean:.2f}, σ={std:.2f}) — "
                       f"physical/business bounds needed to classify",
                       example_values=examples)


# ── Cross-column temporal sequence scanner ────────────────────────────────

def _check_temporal_sequence(col_a: str, col_b: str, df: pd.DataFrame) -> Optional[dict]:
    """Detect impossible sequences where a start column is later than its end column."""
    if col_a not in df.columns or col_b not in df.columns:
        return None
    dates_a = pd.to_datetime(df[col_a], errors="coerce")
    dates_b = pd.to_datetime(df[col_b], errors="coerce")
    both_valid = dates_a.notna() & dates_b.notna()
    impossible = both_valid & (dates_a > dates_b)
    count = int(impossible.sum())
    if count == 0:
        return None
    return _make_issue(
        f"{col_a}>{col_b}", IssueType.IMPOSSIBLE_TEMPORAL, count, count / len(df),
        f"{count} rows where {col_a} is later than {col_b} — logically impossible, safe to remove"
    )


# ── Known temporal pairs per dataset ──────────────────────────────────────
# These are the start→end column pairs where start > end is always an error.

_KNOWN_TEMPORAL_PAIRS: dict[str, list[tuple[str, str]]] = {
    "CUSTOMER_ORDERS":  [("onboarding_date", "go_live_date")],
    "HR_WORKFORCE":     [("hire_date", "termination_date")],
    "FINANCIAL_LEDGER": [("effective_date", "posting_date")],
    "IOT_TELEMETRY":    [],
    "PRODUCT_CATALOG":  [],
}


# ── Main entry point ───────────────────────────────────────────────────────

def score_issues(
    df: pd.DataFrame,
    table_name: str,
    pk_column: Optional[str] = None,
    sample_rows: int = 10_000,
) -> dict:
    """
    Scan a DataFrame and return a confidence map for all detected issues.

    This is the Iteration 1 — Structural Scan. Score impact is zero; the output
    is a confidence map that drives all subsequent iterations.

    Parameters
    ----------
    df : pd.DataFrame
        The table to scan. For large datasets, pass a pre-sampled slice or
        set sample_rows to limit the scan.
    table_name : str
        Dataset name (e.g. "CUSTOMER_ORDERS") — used to look up known
        temporal pairs and provides context for the output.
    pk_column : str, optional
        Name of the primary key column. If None, auto-detected by column name pattern.
    sample_rows : int
        If df has more rows than this, only the first N rows are used for
        expensive per-value checks.

    Returns
    -------
    dict
        Confidence map with structure:
        {
          "table_name": str,
          "scanned_at": ISO8601,
          "total_rows": int,
          "sample_rows": int,
          "pk_column": str | None,
          "total_issues": int,
          "summary": {"HIGH": int, "MEDIUM": int, "LOW": int},
          "issues": [
            {
              "column": str,
              "issue_type": str,
              "count": int,
              "pct": float,
              "confidence_level": "HIGH"|"MEDIUM"|"LOW",
              "confidence_score": float,
              "detail": str,
              "example_values": list[str],
              "recommended_action": str,
            },
            ...
          ]
        }
    """
    scanned_df = df.head(sample_rows) if len(df) > sample_rows else df
    issues: list[dict] = []
    scanned_at = datetime.utcnow().isoformat() + "Z"

    print(f"  [ConfidenceScorer] Scanning {table_name}: "
          f"{len(scanned_df):,} rows × {len(scanned_df.columns)} cols")

    # ── Auto-detect PK column ─────────────────────────────────────────────
    detected_pk = pk_column
    if detected_pk is None:
        for col in scanned_df.columns:
            if _is_likely_pk(col):
                detected_pk = col
                break

    # ── Per-column scans ──────────────────────────────────────────────────
    for col in scanned_df.columns:
        series = scanned_df[col]
        dtype  = str(series.dtype)

        # Nulls — every column
        issue = _check_nulls(col, series)
        if issue:
            issues.append(issue)

        # Duplicate PK
        if col == detected_pk:
            issue = _check_duplicates(col, series)
            if issue:
                issues.append(issue)

        # Negatives — numeric columns and numeric-looking object columns
        if dtype in ("float64", "float32", "int64", "int32", "int16", "int8"):
            issue = _check_negatives(col, series)
            if issue:
                issues.append(issue)

        # Email format — object columns with "email" in the name
        if dtype == "object" and "email" in col.lower():
            issue = _check_email(col, series)
            if issue:
                issues.append(issue)

        # Future dates — temporal columns and datetime dtype
        if _is_temporal(col) or dtype == "datetime64[ns]":
            issue = _check_future_dates(col, series)
            if issue:
                issues.append(issue)

        # Whitespace — string columns that are not temporal identifiers
        if dtype == "object" and not _is_temporal(col):
            issue = _check_whitespace(col, series)
            if issue:
                issues.append(issue)

        # Categorical inconsistency — low-cardinality string columns
        if dtype == "object":
            issue = _check_categorical_inconsistency(col, series)
            if issue:
                issues.append(issue)

        # Statistical outliers — non-monetary numeric columns (monetary needs context)
        if dtype in ("float64", "float32") and not _is_monetary(col):
            issue = _check_outliers(col, series)
            if issue:
                issues.append(issue)

    # ── Temporal sequence checks ───────────────────────────────────────────
    for col_a, col_b in _KNOWN_TEMPORAL_PAIRS.get(table_name.upper(), []):
        issue = _check_temporal_sequence(col_a, col_b, scanned_df)
        if issue:
            issues.append(issue)

    # ── Build summary ─────────────────────────────────────────────────────
    summary: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for issue in issues:
        summary[issue["confidence_level"]] += 1

    confidence_map = {
        "table_name":   table_name.upper(),
        "scanned_at":   scanned_at,
        "total_rows":   len(df),
        "sample_rows":  len(scanned_df),
        "pk_column":    detected_pk,
        "total_issues": len(issues),
        "summary":      summary,
        "issues":       issues,
    }

    print(f"  [ConfidenceScorer] Done — {len(issues)} issues: "
          f"{summary['HIGH']} HIGH · {summary['MEDIUM']} MEDIUM · {summary['LOW']} LOW")
    return confidence_map


def print_confidence_report(confidence_map: dict) -> None:
    """
    Print the Iteration 1 chat output: a human-readable summary categorised
    by confidence level, formatted as the AI would present it to the analyst.
    """
    m = confidence_map
    print(f"\n{'='*65}")
    print(f"  Structural Scan — {m['table_name']}")
    print(f"  Scanned {m['sample_rows']:,} of {m['total_rows']:,} rows  ·  "
          f"{m['total_issues']} issues found")
    print(f"{'='*65}")

    labels = {
        "HIGH":   "Ready to fix autonomously",
        "MEDIUM": "Need your context before acting",
        "LOW":    "Require your decision",
    }

    for level in ("HIGH", "MEDIUM", "LOW"):
        level_issues = [i for i in m["issues"] if i["confidence_level"] == level]
        if not level_issues:
            continue
        print(f"\n  {level} CONFIDENCE — {labels[level]}  ({len(level_issues)})")
        print(f"  {'─'*58}")
        for issue in level_issues:
            print(f"  · [{issue['issue_type']}] {issue['column']}: "
                  f"{issue['count']:,} rows ({issue['pct']:.1%})")
            print(f"    {issue['detail']}")
            if issue["example_values"]:
                print(f"    Examples: {issue['example_values'][:3]}")

    high = m["summary"]["HIGH"]
    med  = m["summary"]["MEDIUM"]
    low  = m["summary"]["LOW"]
    print(f"\n  I'm confident about {high} issue(s) and ready to fix those.")
    if med + low > 0:
        print(f"  But before I touch anything, I need to understand "
              f"{med + low} thing(s) about your data. Can I ask?")
    print()


def save_confidence_map(confidence_map: dict, output_path: str) -> None:
    """Persist the confidence map to a JSON file for use in later iterations."""
    with open(output_path, "w") as f:
        json.dump(confidence_map, f, indent=2, default=str)
    print(f"  [ConfidenceScorer] Confidence map saved → {output_path}")
