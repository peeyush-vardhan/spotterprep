"""
ground_truth.py — Turn the generators' injected-issue logs into an evaluation set.

Each generator writes data/profiles/datasetN_profile.json with an `issues_summary`
listing every data quality issue it deliberately injected, the column(s) it touched
and, usually, how many rows. That log is the ground truth for evaluating the
Iteration 1 detector (spotterprep/iteration1_confidence.py).

Every injected issue is mapped to an evaluation *family* and one of three scopes:

  detector      A single-column issue Iteration 1 is designed to find.
  cross_column  Needs two or more columns (e.g. ARR < MRR x 12). Handled by the
                deterministic cleaning rules and Iteration 5, not Iteration 1.
  out_of_scope  Cannot be detected from one table alone (e.g. orphaned foreign
                keys need the parent table), so it is reported but not scored.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

DATASETS = [
    # (index, file stem, table name)
    (1, "customer_orders", "CUSTOMER_ORDERS"),
    (2, "iot_telemetry", "IOT_TELEMETRY"),
    (3, "hr_workforce", "HR_WORKFORCE"),
    (4, "financial_ledger", "FINANCIAL_LEDGER"),
    (5, "product_catalog", "PRODUCT_CATALOG"),
]

# Detector issue types that count as a hit for each family.
FAMILY_TO_DETECTOR_TYPES: dict[str, set[str]] = {
    "DUPLICATE":          {"DUPLICATE_PK"},
    "NULL":               {"NULL_CRITICAL", "NULL_NON_CRITICAL", "NULL_MONETARY", "NULL_PII"},
    "NEGATIVE_MONETARY":  {"NEGATIVE_MONETARY"},
    "NEGATIVE_NUMERIC":   {"NEGATIVE_NUMERIC"},
    "IMPOSSIBLE_TEMPORAL": {"IMPOSSIBLE_TEMPORAL"},
    "FUTURE_DATE":        {"FUTURE_DATE"},
    "MALFORMED_EMAIL":    {"MALFORMED_EMAIL"},
    "CATEGORICAL":        {"CATEGORICAL_INCONSISTENCY", "TYPE_INCONSISTENCY"},
    "WHITESPACE":         {"WHITESPACE"},
    "OUT_OF_RANGE":       {"STATISTICAL_OUTLIER", "PHYSICAL_RANGE_VIOLATION"},
    "FORMAT":             {"TYPE_INCONSISTENCY", "CATEGORICAL_INCONSISTENCY"},
}

# Ordered (pattern, family, scope). First match wins.
_RULES: list[tuple[str, str, str]] = [
    (r"orphan",                                        "ORPHAN_FK",          "out_of_scope"),
    (r"duplicate",                                     "DUPLICATE",          "detector"),
    (r"impossible_temporal|approval_before_posting",   "IMPOSSIBLE_TEMPORAL", "detector"),
    (r"future",                                        "FUTURE_DATE",        "detector"),
    (r"negative_(monetary|debit|price)",               "NEGATIVE_MONETARY",  "detector"),
    (r"negative",                                      "NEGATIVE_NUMERIC",   "detector"),
    (r"null|missing_.*translation|sensor_dropout",     "NULL",               "detector"),
    (r"malformed_email",                               "MALFORMED_EMAIL",    "detector"),
    (r"whitespace",                                    "WHITESPACE",         "detector"),
    (r"inconsistent|account_code_format",              "CATEGORICAL",        "detector"),
    (r"outlier|sensor_fault|over_100|oob",             "OUT_OF_RANGE",       "detector"),
    (r"html|lang_swap|special_chars|floating_point",   "FORMAT",             "detector"),
    (r"logic|physics|imbalance|calc_error|band_violation|weight_inconsistency"
     r"|stale_fx|zero_vibration|lag",                  "CROSS_COLUMN",       "cross_column"),
]

# Columns the detector treats as monetary or personal data. Issues in these columns must
# never be auto-fixed, so the safety check expects them to be classified LOW confidence.
_SENSITIVE_COL = re.compile(
    r"amount|price|revenue|cost|salary|pay|fee|charge|balance|debit|credit|(?:^|_)(?:arr|mrr)(?:_|$)"
    r"|(?:^|_)(?:name|email|phone|address|ssn|dob|birth|passport)(?:_|$)",
    re.I,
)


@dataclass
class InjectedIssue:
    table: str
    issue: str
    column_ref: str
    family: str
    scope: str
    columns: list[str] = field(default_factory=list)
    count: int | None = None

    @property
    def sensitive(self) -> bool:
        return any(_SENSITIVE_COL.search(c) for c in self.columns)


def classify(issue_name: str) -> tuple[str, str]:
    for pattern, family, scope in _RULES:
        if re.search(pattern, issue_name, re.I):
            return family, scope
    return "UNMAPPED", "out_of_scope"


def resolve_columns(column_ref: str, table_columns: list[str]) -> list[str]:
    """Resolve references like 'a > b', 'arr/mrr', 'perf_rating_*', 'weight_kg/lbs' to real columns."""
    cols: list[str] = []
    lower = {c.lower(): c for c in table_columns}
    for token in re.findall(r"[a-z][a-z0-9_]*\*?", column_ref.lower()):
        if token.endswith("*"):
            prefix = token[:-1]
            cols += [c for c in table_columns if c.lower().startswith(prefix)]
        elif token in lower:
            cols.append(lower[token])
    # 'weight_kg/lbs' style: a bare suffix after a slash inherits the previous token's stem
    for stem, suffix in re.findall(r"([a-z0-9_]+?_)[a-z0-9]+/([a-z0-9]+)", column_ref.lower()):
        cand = stem + suffix
        if cand in lower:
            cols.append(lower[cand])
    return list(dict.fromkeys(cols))


def load_ground_truth(data_dir: Path, table_columns: dict[str, list[str]]) -> list[InjectedIssue]:
    issues: list[InjectedIssue] = []
    for idx, _stem, table in DATASETS:
        profile = json.loads((data_dir / "profiles" / f"dataset{idx}_profile.json").read_text())
        for _severity, items in profile["issues_summary"].items():
            for item in items:
                family, scope = classify(item["issue"])
                cols = resolve_columns(str(item.get("column", "")), table_columns.get(table, []))
                if scope == "detector" and not cols:
                    scope = "out_of_scope"  # column reference can't be resolved (e.g. '15 sensor columns')
                issues.append(InjectedIssue(
                    table=table, issue=item["issue"], column_ref=str(item.get("column", "")),
                    family=family, scope=scope, columns=cols, count=item.get("count"),
                ))
    return issues


def read_raw(data_dir: Path, idx: int, stem: str, which: str = "raw") -> pd.DataFrame:
    """Read a generated table with only empty cells treated as missing.

    pandas' default also turns the literal strings "N/A", "NA" and "null" into NaN. Several
    columns use "N/A" as a real category ("not applicable"), so the default read invents
    hundreds of null columns that are not in the data.
    """
    suffix = "" if which == "raw" else "_cleaned"
    return pd.read_csv(data_dir / which / f"dataset{idx}_{stem}{suffix}.csv",
                       keep_default_na=False, na_values=[""], low_memory=False)
