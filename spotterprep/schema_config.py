"""
schema_config.py — Per-dataset schema facts shared by the detector and the scorer.

These are the facts an analyst would confirm once per table in Iteration 2: which
columns form the primary key, and which (start, end) column pairs must be ordered.
Keeping them here, instead of guessing from column names, is what lets the IoT table
use its real composite key (one row per device per reading).
"""
from __future__ import annotations

import pandas as pd

PRIMARY_KEYS: dict[str, list[str]] = {
    "CUSTOMER_ORDERS":  ["order_id"],
    "IOT_TELEMETRY":    ["device_id", "reading_timestamp"],
    "HR_WORKFORCE":     ["employee_id"],
    "FINANCIAL_LEDGER": ["transaction_id"],
    "PRODUCT_CATALOG":  ["product_id"],
}

# (start, end): start later than end is always an error.
TEMPORAL_PAIRS: dict[str, list[tuple[str, str]]] = {
    "CUSTOMER_ORDERS":  [("onboarding_date", "go_live_date")],
    "HR_WORKFORCE":     [("hire_date", "termination_date")],
    "FINANCIAL_LEDGER": [("effective_date", "posting_date"), ("posting_date", "approval_date")],
    "IOT_TELEMETRY":    [("reading_timestamp", "ingestion_timestamp")],
    "PRODUCT_CATALOG":  [("created_at", "published_at")],
}


def is_text(series: pd.Series) -> bool:
    """True for text columns under both pandas 2 (object) and pandas 3 (str) dtypes."""
    return series.dtype == object or pd.api.types.is_string_dtype(series.dtype)


def is_number(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(series.dtype)


def is_float(series: pd.Series) -> bool:
    return pd.api.types.is_float_dtype(series.dtype)
