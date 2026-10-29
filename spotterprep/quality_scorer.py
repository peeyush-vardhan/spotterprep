"""
quality_scorer.py — SpotterPrep 5-Dimension Quality Scorer
===========================================================
Standalone quality score computation, callable after each iteration
to give the analyst live score feedback as transformations are applied.

Implements the methodology in docs/04_quality_framework.md:

  Dimension      Weight  What it measures
  ──────────────────────────────────────────────────────────────
  Completeness    25%    % rows with no nulls in critical columns
  Validity        25%    % rows with no format/range/type violations
  Uniqueness      20%    % rows with a unique PK value
  Consistency     20%    % rows using canonical categorical values
  Accuracy        10%    % rows where logical/temporal relationships hold

  Weighted overall = sum(dimension_score × weight)

  Grade thresholds: A = 95–100 · B = 85–94 · C = 70–84 · D = 55–69 · F < 55

Designed for live feedback — runs on a DataFrame sample (default 10K rows)
so it completes in <2 seconds even on wide tables.

Usage:
  from spotterprep.quality_scorer import compute_quality_score, format_score_delta

  # After Iteration 3 transformations are applied:
  before = compute_quality_score(df_before, table_name="CUSTOMER_ORDERS")
  after  = compute_quality_score(df_after,  table_name="CUSTOMER_ORDERS")
  print(format_score_delta(before, after, iteration=3))
"""

import re
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from spotterprep.schema_config import PRIMARY_KEYS, is_float, is_number, is_text


# ── Dimension weights ──────────────────────────────────────────────────────

WEIGHTS = {
    "completeness": 0.25,
    "validity":     0.25,
    "uniqueness":   0.20,
    "consistency":  0.20,
    "accuracy":     0.10,
}

GRADE_THRESHOLDS = [
    (95, "A"),
    (85, "B"),
    (70, "C"),
    (55, "D"),
]


# ── Column pattern classifiers (shared with confidence_scorer) ─────────────

_MONETARY_COL  = re.compile(r'amount|price|revenue|cost|salary|pay|fee|charge|balance|debit|credit|arr|mrr|ltv|cac', re.I)
_PII_COL       = re.compile(r'(?:^|_)(?:name|email|phone|address|ssn|dob|birth|passport)(?:_|$)', re.I)
_PK_COL        = re.compile(r'(?:^|_)id$|_key$|_pk$', re.I)
_TEMPORAL_COL  = re.compile(r'(?:^|_)(?:date|timestamp|time)(?:_|$)|_at$', re.I)
_EMAIL_FORMAT  = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# Columns SpotterPrep itself adds during cleaning (e.g. `order_amount_flag`, `vendor_id_orphan`).
# They are sparse by design: empty means "nothing to flag". They describe the data rather than
# being data, so every dimension ignores them. Without this, their nulls were counted as missing
# critical values and cleaned tables scored lower than raw ones.
_ANNOTATION_COL = re.compile(r'_(?:flag|orphan)$', re.I)

# Primary keys per dataset. A list means a composite key. Name-pattern detection is only a
# fallback: in IOT_TELEMETRY the first `_id` column is `device_id`, which repeats by design.
# PRIMARY_KEYS lives in spotterprep/schema_config.py, shared with the detector.

# A negative value is only treated as invalid when the column is otherwise non-negative.
# Columns that are signed by nature (NPS, deltas, normally distributed metrics) routinely hold
# negatives; flagging them made Validity near zero on every table, raw or cleaned.
_MAX_ANOMALOUS_NEGATIVE_SHARE = 0.05


def _data_columns(df: pd.DataFrame) -> list[str]:
    """All columns except SpotterPrep's own annotation columns."""
    return [c for c in df.columns if not _ANNOTATION_COL.search(c)]

# Known temporal start→end pairs per dataset.
# A row fails Accuracy if start > end for any known pair.
_TEMPORAL_PAIRS: dict[str, list[tuple[str, str]]] = {
    "CUSTOMER_ORDERS":  [("onboarding_date", "go_live_date")],
    "HR_WORKFORCE":     [("hire_date", "termination_date")],
    "FINANCIAL_LEDGER": [("effective_date", "posting_date")],
    "IOT_TELEMETRY":    [],
    "PRODUCT_CATALOG":  [],
}

# Known logical relationships per dataset: (col_a, operator, col_b_expression)
# A row fails Accuracy if the relationship is violated.
_LOGIC_CHECKS: dict[str, list[tuple[str, str, str]]] = {
    "CUSTOMER_ORDERS":  [("arr", ">=", "mrr * 12 * 0.99")],
    "FINANCIAL_LEDGER": [("net_amount", "~=", "debit_amount - credit_amount")],
    "HR_WORKFORCE":     [],
    "IOT_TELEMETRY":    [("power_kw", "<=", "voltage * current * 1.05")],
    "PRODUCT_CATALOG":  [],
}


# ── Dimension scorers ──────────────────────────────────────────────────────

def _score_completeness(df: pd.DataFrame) -> tuple[float, dict]:
    """
    % of rows where all critical columns are non-null.
    Critical columns: PK, monetary, and PII columns detected by name pattern.
    """
    critical_cols = [
        c for c in _data_columns(df)
        if bool(_PK_COL.search(c)) or bool(_MONETARY_COL.search(c)) or bool(_PII_COL.search(c))
    ]
    if not critical_cols:
        return 100.0, {"critical_columns": [], "note": "No critical columns detected"}

    null_in_any_critical = df[critical_cols].isnull().any(axis=1)
    passing = int((~null_in_any_critical).sum())
    score   = round(passing / len(df) * 100, 2)

    # Per-column null rates for the detail dict
    null_rates = {
        c: round(df[c].isnull().mean() * 100, 2) for c in critical_cols
    }
    return score, {"critical_columns": critical_cols, "null_rates": null_rates}


def _score_validity(df: pd.DataFrame) -> tuple[float, dict]:
    """
    % of rows with no detected format, range, or type violations.
    Checks: malformed emails, negative values in non-monetary numeric columns,
    extreme outliers (>5σ) in numeric columns.
    """
    failing = pd.Series(False, index=df.index)
    detail: dict = {"checks_run": []}

    for col in _data_columns(df):
        s = df[col]

        # Malformed email
        if "email" in col.lower() and is_text(s):
            non_null = df[col].notna()
            # In pandas 3, astype(str) on a string column keeps missing values as NaN, so match
            # only the non-null cells.
            valid = df.loc[non_null, col].astype(str).str.match(_EMAIL_FORMAT)
            malformed = non_null & ~valid.reindex(df.index, fill_value=True)
            failing |= malformed
            detail["checks_run"].append(f"{col}:email_format")

        # Negative values in non-monetary columns that are otherwise non-negative
        if is_number(s) and not _MONETARY_COL.search(col):
            numeric = pd.to_numeric(df[col], errors="coerce")
            negative = (numeric < 0).fillna(False)
            share = float(negative.mean()) if len(negative) else 0.0
            if 0 < share <= _MAX_ANOMALOUS_NEGATIVE_SHARE:
                failing |= negative
                detail["checks_run"].append(f"{col}:no_negatives")

        # Extreme outliers (>5σ) in float columns — anything beyond 5σ is a data error
        if is_float(s) and not _MONETARY_COL.search(col):
            numeric = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(numeric) > 50:
                mean, std = float(numeric.mean()), float(numeric.std())
                if std > 0:
                    z = (pd.to_numeric(df[col], errors="coerce") - mean) / std
                    failing |= (z.abs() > 5).fillna(False)
                    detail["checks_run"].append(f"{col}:no_5sigma_outliers")

    passing = int((~failing).sum())
    score   = round(passing / len(df) * 100, 2)
    detail["failing_rows"] = int(failing.sum())
    return score, detail


def _score_uniqueness(df: pd.DataFrame, pk_column, table_name: str = "") -> tuple[float, dict]:
    """
    % of rows whose primary key (single or composite) is unique.
    Key resolution order: explicit pk_column, the dataset's known key, then name-pattern detection.
    Returns 100.0 if no key can be resolved.
    """
    if pk_column is not None:
        cols = [pk_column] if isinstance(pk_column, str) else list(pk_column)
    elif table_name.upper() in PRIMARY_KEYS:
        cols = PRIMARY_KEYS[table_name.upper()]
    else:
        found = next((c for c in _data_columns(df) if _PK_COL.search(c)), None)
        cols = [found] if found else []
    if not cols or any(c not in df.columns for c in cols):
        return 100.0, {"note": "No primary key resolved — uniqueness not measured"}

    dup_count = int(df.duplicated(subset=cols, keep=False).sum())
    passing   = len(df) - dup_count
    score     = round(passing / len(df) * 100, 2)
    return score, {"pk_columns": cols, "duplicate_rows": dup_count}


def _score_consistency(df: pd.DataFrame) -> tuple[float, dict]:
    """
    % of rows using the canonical (modal) form of each controlled vocabulary column.
    A column is treated as a controlled vocabulary if it is a text column and
    fewer than 50 unique non-null values.
    Any row with a non-modal case variant in any such column fails this dimension.
    """
    failing = pd.Series(False, index=df.index)
    inconsistent_cols = []

    for col in _data_columns(df):
        if not is_text(df[col]):
            continue
        non_null = df[col].dropna()
        if non_null.nunique() > 50 or len(non_null) == 0:
            continue

        # Find case-variant groups
        lower_to_variants: dict = {}
        for val in non_null.unique():
            lower_to_variants.setdefault(str(val).strip().lower(), set()).add(val)

        multi_variant_groups = {k: v for k, v in lower_to_variants.items() if len(v) > 1}
        if not multi_variant_groups:
            continue

        # Canonical form = the most frequent variant for each group
        value_counts = non_null.value_counts()
        non_canonical: set = set()
        for group_variants in multi_variant_groups.values():
            canonical = max(group_variants, key=lambda v: value_counts.get(v, 0))
            non_canonical.update(group_variants - {canonical})

        if non_canonical:
            failing |= df[col].isin(non_canonical)
            inconsistent_cols.append(col)

    passing = int((~failing).sum())
    score   = round(passing / len(df) * 100, 2)
    return score, {
        "inconsistent_columns": inconsistent_cols,
        "failing_rows": int(failing.sum()),
    }


def _score_accuracy(df: pd.DataFrame, table_name: str) -> tuple[float, dict]:
    """
    % of rows where all known logical and temporal relationships hold.
    Checks temporal sequences (start <= end) and column-level logic relationships.
    """
    failing = pd.Series(False, index=df.index)
    checks_applied = []

    # Temporal sequence checks
    for col_a, col_b in _TEMPORAL_PAIRS.get(table_name.upper(), []):
        if col_a not in df.columns or col_b not in df.columns:
            continue
        dates_a = pd.to_datetime(df[col_a], errors="coerce")
        dates_b = pd.to_datetime(df[col_b], errors="coerce")
        both_valid = dates_a.notna() & dates_b.notna()
        impossible = both_valid & (dates_a > dates_b)
        failing |= impossible
        checks_applied.append(f"{col_a}<={col_b}: {int(impossible.sum())} violations")

    # Column logic checks
    for col_a, op, expr in _LOGIC_CHECKS.get(table_name.upper(), []):
        if col_a not in df.columns:
            continue
        try:
            a = pd.to_numeric(df[col_a], errors="coerce")

            if op == ">=" and "*" in expr:
                # e.g. "mrr * 12 * 0.99"
                parts = expr.split("*")
                col_b = parts[0].strip()
                if col_b not in df.columns:
                    continue
                multiplier = 1.0
                for p in parts[1:]:
                    multiplier *= float(p.strip())
                b = pd.to_numeric(df[col_b], errors="coerce") * multiplier
                both_valid = a.notna() & b.notna()
                violation = both_valid & (a < b)
                failing |= violation
                checks_applied.append(f"{col_a}>={expr}: {int(violation.sum())} violations")

            elif op == "<=" and "*" in expr:
                # e.g. "voltage * current * 1.05"
                parts = expr.split("*")
                col_b1 = parts[0].strip()
                col_b2 = parts[1].strip() if len(parts) > 1 else None
                factor = float(parts[2].strip()) if len(parts) > 2 else 1.0
                if col_b1 not in df.columns or (col_b2 and col_b2 not in df.columns):
                    continue
                b = pd.to_numeric(df[col_b1], errors="coerce")
                if col_b2:
                    b = b * pd.to_numeric(df[col_b2], errors="coerce")
                b = b * factor
                both_valid = a.notna() & b.notna() & (b > 0)
                violation = both_valid & (a > b)
                failing |= violation
                checks_applied.append(f"{col_a}<={expr}: {int(violation.sum())} violations")

            elif op == "~=" and "-" in expr:
                # e.g. "debit_amount - credit_amount" — net_amount should equal debit - credit
                parts = [p.strip() for p in expr.split("-")]
                if parts[0] not in df.columns or parts[1] not in df.columns:
                    continue
                expected = (pd.to_numeric(df[parts[0]], errors="coerce") -
                            pd.to_numeric(df[parts[1]], errors="coerce"))
                both_valid = a.notna() & expected.notna()
                violation = both_valid & (abs(a - expected) > 0.01)
                failing |= violation
                checks_applied.append(f"{col_a}~={expr}: {int(violation.sum())} violations")

        except Exception:
            continue  # skip malformed check silently

    passing = int((~failing).sum())
    score   = round(passing / len(df) * 100, 2)
    return score, {
        "checks_applied": checks_applied,
        "failing_rows": int(failing.sum()),
    }


# ── Grade helper ───────────────────────────────────────────────────────────

def _grade(score: float) -> str:
    for threshold, letter in GRADE_THRESHOLDS:
        if score >= threshold:
            return letter
    return "F"


# ── Main entry point ───────────────────────────────────────────────────────

def compute_quality_score(
    df: pd.DataFrame,
    table_name: str,
    pk_column=None,
    sample_rows: int = 10_000,
) -> dict:
    """
    Compute the 5-dimension quality score for a DataFrame.

    Designed for live feedback — call this after each iteration to show
    the analyst how the score has changed. Runs on a sample for speed.

    Parameters
    ----------
    df : pd.DataFrame
        The DataFrame to score (pre- or post-transformation).
    table_name : str
        Dataset name — used to look up known temporal pairs and logic checks.
    pk_column : str or list[str], optional
        Primary key column(s). Defaults to the dataset's known key, then name-pattern detection.
    sample_rows : int
        Max rows to use. Default 10K gives <2s on a 500-column table.

    Returns
    -------
    dict
        {
          "table_name": str,
          "scored_at": ISO8601,
          "row_count": int,
          "sample_rows": int,
          "dimensions": {
            "completeness": {"score": float, "weight": 0.25, "detail": dict},
            "validity":     {"score": float, "weight": 0.25, "detail": dict},
            "uniqueness":   {"score": float, "weight": 0.20, "detail": dict},
            "consistency":  {"score": float, "weight": 0.20, "detail": dict},
            "accuracy":     {"score": float, "weight": 0.10, "detail": dict},
          },
          "overall_score": float,
          "grade": str,
        }
    """
    # Fixed-seed random sample: representative of the whole table and reproducible run to run.
    sample = df.sample(n=sample_rows, random_state=0) if len(df) > sample_rows else df

    c_score, c_detail = _score_completeness(sample)
    v_score, v_detail = _score_validity(sample)
    u_score, u_detail = _score_uniqueness(sample, pk_column, table_name)
    co_score, co_detail = _score_consistency(sample)
    a_score, a_detail = _score_accuracy(sample, table_name)

    overall = round(
        c_score  * WEIGHTS["completeness"] +
        v_score  * WEIGHTS["validity"]     +
        u_score  * WEIGHTS["uniqueness"]   +
        co_score * WEIGHTS["consistency"]  +
        a_score  * WEIGHTS["accuracy"],
        2
    )

    return {
        "table_name":  table_name.upper(),
        "scored_at":   datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "row_count":   len(df),
        "sample_rows": len(sample),
        "dimensions": {
            "completeness": {"score": c_score,  "weight": WEIGHTS["completeness"], "detail": c_detail},
            "validity":     {"score": v_score,  "weight": WEIGHTS["validity"],     "detail": v_detail},
            "uniqueness":   {"score": u_score,  "weight": WEIGHTS["uniqueness"],   "detail": u_detail},
            "consistency":  {"score": co_score, "weight": WEIGHTS["consistency"],  "detail": co_detail},
            "accuracy":     {"score": a_score,  "weight": WEIGHTS["accuracy"],     "detail": a_detail},
        },
        "overall_score": overall,
        "grade":         _grade(overall),
    }


# ── Live feedback formatter ────────────────────────────────────────────────

def format_score_delta(before: dict, after: dict, iteration: int) -> str:
    """
    Format a before/after score comparison as a single chat message line.
    Intended for live feedback to the analyst at the end of each iteration.

    Example output:
      "After Iteration 3: 72.8 → 84.1  (+11.3 pts)  Grade: C → B"
    """
    delta = round(after["overall_score"] - before["overall_score"], 1)
    sign  = "+" if delta >= 0 else ""
    return (
        f"After Iteration {iteration}: "
        f"{before['overall_score']} → {after['overall_score']}  "
        f"({sign}{delta} pts)  "
        f"Grade: {before['grade']} → {after['grade']}"
    )


def print_score_report(score: dict) -> None:
    """Print a dimension-level breakdown of a quality score result."""
    print(f"\n{'='*55}")
    print(f"  Quality Score — {score['table_name']}")
    print(f"  {score['row_count']:,} rows  ·  scored at {score['scored_at'][:19]}")
    print(f"{'='*55}")
    print(f"  Overall: {score['overall_score']:.1f}  (Grade {score['grade']})")
    print(f"  {'─'*50}")
    for dim, data in score["dimensions"].items():
        bar_len = int(data["score"] / 100 * 30)
        bar     = "█" * bar_len + "░" * (30 - bar_len)
        print(f"  {dim.capitalize():<14} {data['score']:>6.1f}  {bar}  (weight {int(data['weight']*100)}%)")
    print()
