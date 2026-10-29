"""
customer_orders.py — CUSTOMER_ORDERS
100,000 rows × 200 columns
Generates raw (dirty), cleaned, and profile JSON
"""

import numpy as np
import pandas as pd
from faker import Faker
import json
import os
import re
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

fake = Faker()
Faker.seed(42)
np.random.seed(42)
rng = np.random.default_rng(42)

N = 100_000
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RAW_PATH    = os.path.join(OUT_DIR, "raw",      "dataset1_customer_orders.csv")
CLEANED_PATH= os.path.join(OUT_DIR, "cleaned",  "dataset1_customer_orders_cleaned.csv")
PROFILE_PATH= os.path.join(OUT_DIR, "profiles", "dataset1_profile.json")
for _p in (RAW_PATH, CLEANED_PATH, PROFILE_PATH):
    os.makedirs(os.path.dirname(_p), exist_ok=True)



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def random_dates(start, end, n):
    start_ts = pd.Timestamp(start).value // 10**9
    end_ts   = pd.Timestamp(end).value   // 10**9
    return pd.to_datetime(rng.integers(start_ts, end_ts, n), unit="s")

def inject_nulls(series, pct):
    mask = rng.random(len(series)) < pct
    series = series.copy().astype(object)
    series[mask] = np.nan
    return series

def inject_negatives(series, n):
    idx = rng.choice(series.dropna().index, size=n, replace=False)
    series = series.copy()
    series[idx] = -series[idx].abs()
    return series


# ---------------------------------------------------------------------------
# RAW GENERATION
# ---------------------------------------------------------------------------
def generate_raw():
    print("  [DS1] Generating raw data...")

    # ── ORDER CORE (20 cols) ──────────────────────────────────────────────
    order_ids = [f"ORD-{i:07d}" for i in range(1, N + 1)]
    # Issue 7: 0.3% duplicate order_ids (~300 rows)
    n_dups = int(N * 0.003)
    dup_positions = rng.choice(range(N // 2, N), size=n_dups, replace=False)
    dup_sources   = rng.choice(range(0, N // 2), size=n_dups, replace=False)
    for pos, src in zip(dup_positions, dup_sources):
        order_ids[pos] = order_ids[src]

    customer_ids = [f"CUST-{rng.integers(1, 9500):06d}" for _ in range(N)]
    # Issue 13: 0.5% orphaned customer_ids (IDs > 9500 don't exist)
    n_orphans = int(N * 0.005)
    orphan_idx = rng.choice(N, size=n_orphans, replace=False)
    for i in orphan_idx:
        customer_ids[i] = f"CUST-{rng.integers(9501, 10000):06d}"

    order_dates = random_dates("2021-01-01", "2024-06-01", N)
    order_dates = order_dates.tolist()
    # Issue 5: 23 future order_dates
    future_dates = pd.date_range("2024-12-01", periods=23, freq="7D")
    future_idx = rng.choice(N, size=23, replace=False)
    for i, fd in zip(future_idx, future_dates):
        order_dates[i] = fd
    # Issue 6: 5 very old dates (pre-2020)
    old_dates = ["2018-03-15","2017-11-02","2019-01-08","2018-07-20","2016-05-30"]
    old_idx = rng.choice(N, size=5, replace=False)
    for i, od in zip(old_idx, old_dates):
        order_dates[i] = pd.Timestamp(od)

    order_amounts = rng.uniform(500, 15000, N)
    # Issue 1: 1.5% nulls in order_amount
    amount_null_mask = rng.random(N) < 0.015
    order_amounts = order_amounts.astype(object)
    order_amounts[amount_null_mask] = np.nan
    # Issue 2 (negative values): 12 negative
    neg_idx = rng.choice(np.where(~amount_null_mask)[0], size=12, replace=False)
    for i in neg_idx:
        order_amounts[i] = -abs(float(order_amounts[i]))

    statuses_pool = ["active","ACTIVE","Active","actv"]  # Issue 9
    statuses = rng.choice(statuses_pool, N, p=[0.4, 0.3, 0.2, 0.1])

    currencies = rng.choice(["USD","EUR","GBP","JPY","INR"], N, p=[0.7,0.12,0.08,0.05,0.05])
    payment_methods = rng.choice(["credit_card","wire","ach","check","paypal"], N, p=[0.4,0.25,0.2,0.1,0.05])
    channels = rng.choice(["web","mobile","partner","direct","marketplace"], N)
    regions = rng.choice(["AMER","EMEA","APAC","LATAM"], N, p=[0.5,0.25,0.15,0.1])
    sales_rep_ids = [f"REP-{rng.integers(1,200):04d}" for _ in range(N)]
    discount_pcts = rng.uniform(0, 0.35, N)
    tax_amounts = rng.uniform(0, 500, N)
    shipping_costs = rng.uniform(0, 200, N)

    clean_amounts = np.where(amount_null_mask, np.nan,
                             np.array([float(x) if x is not np.nan else np.nan for x in order_amounts], dtype=float))
    total_amounts = np.where(
        amount_null_mask, np.nan,
        np.abs(clean_amounts) * (1 - discount_pcts) + tax_amounts + shipping_costs
    )
    # Issue 2: 4.57% outliers in total_amount (enterprise deals > $50K)
    n_outliers = int(N * 0.0457)
    outlier_idx = rng.choice(N, size=n_outliers, replace=False)
    for i in outlier_idx:
        total_amounts[i] = rng.uniform(50001, 500000)

    order_sources = rng.choice(["crm","website","api","csv_import","manual"], N)
    promo_codes = [f"PROMO{rng.integers(100,999)}" if rng.random() < 0.3 else "" for _ in range(N)]
    contract_ids = [f"CTR-{rng.integers(1,5000):05d}" for _ in range(N)]
    renewal_flags = rng.choice([0, 1], N, p=[0.4, 0.6])
    arr_contributions = rng.uniform(1000, 100000, N)

    # ── CUSTOMER INFO (30 cols) ────────────────────────────────────────────
    customer_names = [fake.name() for _ in range(N)]
    # Issue 3: 14.8% nulls in customer_name
    name_null_mask = rng.random(N) < 0.148
    customer_names = np.array(customer_names, dtype=object)
    customer_names[name_null_mask] = np.nan
    # 124 whitespace issues
    ws_idx = rng.choice(np.where(~name_null_mask)[0], size=124, replace=False)
    for i in ws_idx:
        customer_names[i] = "  " + str(customer_names[i]) + "  "

    emails = [fake.email() for _ in range(N)]
    # Issue 4: 8% malformed emails
    n_malformed = int(N * 0.08)
    mal_idx = rng.choice(N, size=n_malformed, replace=False)
    bad_patterns = ["userATdomain.com", "user@domaincom", "user@.com", "user@domain.", "@domain.com", "nodomain"]
    for i in mal_idx:
        emails[i] = rng.choice(bad_patterns) + str(rng.integers(100, 999))

    phones = [fake.phone_number() for _ in range(N)]
    companies = [fake.company() for _ in range(N)]

    industries_pool = ["SaaS","SAAS","Software as a Service","FinTech","Healthcare","Manufacturing","Retail","Education"]
    industry_weights = [0.3, 0.15, 0.15, 0.1, 0.1, 0.08, 0.07, 0.05]  # Issue 10
    industries = rng.choice(industries_pool, N, p=industry_weights)

    employee_counts = rng.integers(50, 10000, N)
    arr_vals = rng.uniform(10000, 2000000, N)
    mrr_vals = arr_vals / 12.0
    # Issue 14: 200 rows where arr < mrr * 12 (logic violation)
    logic_idx = rng.choice(N, size=200, replace=False)
    for i in logic_idx:
        mrr_vals[i] = arr_vals[i] / 8.0  # makes arr < mrr*12

    csm_owners = [f"CSM-{rng.integers(1,50):03d}" for _ in range(N)]
    account_tiers = rng.choice(["Enterprise","Mid-Market","SMB","Startup"], N, p=[0.2,0.35,0.3,0.15])

    nps_scores = rng.integers(-100, 100, N).astype(float)
    # Issue 11: 15% nulls in nps_score
    nps_null_mask = rng.random(N) < 0.15
    nps_scores[nps_null_mask] = np.nan

    health_scores = rng.uniform(0, 100, N)
    # Issue 12: 8% nulls in health_score
    hs_null_mask = rng.random(N) < 0.08
    health_scores[hs_null_mask] = np.nan

    churn_risks = rng.choice(["low","medium","high"], N, p=[0.5, 0.35, 0.15])
    last_logins = random_dates("2023-01-01", "2024-06-01", N)
    product_tiers = rng.choice(["Free","Starter","Pro","Enterprise"], N, p=[0.1,0.25,0.4,0.25])
    seats_purchased = rng.integers(5, 500, N)
    seats_used = rng.integers(0, 500, N)
    # Issue 8: 2% negative values in seats_used
    neg_seats_mask = rng.random(N) < 0.02
    seats_used = seats_used.astype(float)
    seats_used[neg_seats_mask] = -rng.integers(1, 50, neg_seats_mask.sum())

    onboarding_dates = random_dates("2021-01-01", "2024-01-01", N)
    go_live_dates    = onboarding_dates + pd.to_timedelta(rng.integers(14, 180, N), unit="D")
    # Issue 15: 45 rows where onboarding_date > go_live_date
    impossible_idx = rng.choice(N, size=45, replace=False)
    go_live_dates = go_live_dates.tolist()
    onboarding_dates_list = onboarding_dates.tolist()
    for i in impossible_idx:
        go_live_dates[i] = onboarding_dates_list[i] - timedelta(days=int(rng.integers(1, 30)))
    go_live_dates    = pd.DatetimeIndex(go_live_dates)
    onboarding_dates = pd.DatetimeIndex(onboarding_dates_list)

    support_tiers = rng.choice(["Standard","Premier","Elite"], N, p=[0.5, 0.35, 0.15])

    # 10 extra customer info cols
    extra_customer_cols = {}
    for c in range(10):
        extra_customer_cols[f"customer_attr_{c+1}"] = rng.uniform(0, 100, N)

    # ── PRODUCT USAGE (50 cols) ────────────────────────────────────────────
    feature_cols = {}
    for i in range(1, 31):
        feature_cols[f"feature_{i}"] = rng.integers(0, 1000, N)
    feature_cols["api_calls_monthly"]        = rng.integers(0, 100000, N)
    feature_cols["dashboards_created"]       = rng.integers(0, 200, N)
    feature_cols["searches_per_day"]         = rng.uniform(0, 500, N)
    feature_cols["data_sources_connected"]   = rng.integers(1, 50, N)
    feature_cols["worksheets_count"]         = rng.integers(0, 100, N)
    feature_cols["pinboards_count"]          = rng.integers(0, 50, N)
    feature_cols["liveboards_count"]         = rng.integers(0, 30, N)
    feature_cols["spotter_queries"]          = rng.integers(0, 10000, N)
    for i in range(12):
        feature_cols[f"usage_metric_{i+1}"] = rng.uniform(0, 1000, N)

    # ── FINANCIAL METRICS (40 cols) ───────────────────────────────────────
    fin_cols = {}
    fin_cols["ltv"]              = rng.uniform(10000, 5000000, N)
    fin_cols["cac"]              = rng.uniform(500, 50000, N)
    fin_cols["payback_months"]   = rng.uniform(3, 36, N)
    fin_cols["gross_margin"]     = rng.uniform(0.4, 0.9, N)
    fin_cols["expansion_arr"]    = rng.uniform(0, 200000, N)
    fin_cols["contraction_arr"]  = rng.uniform(0, 50000, N)
    fin_cols["churned_arr"]      = rng.uniform(0, 100000, N)
    fin_cols["net_arr"]          = fin_cols["expansion_arr"] - fin_cols["contraction_arr"] - fin_cols["churned_arr"]
    for i in range(32):
        fin_cols[f"fin_metric_{i+1}"] = rng.uniform(-10000, 100000, N)

    # ── METADATA (60 cols) ────────────────────────────────────────────────
    meta_cols = {}
    meta_cols["created_at"]   = random_dates("2021-01-01", "2024-06-01", N)
    meta_cols["updated_at"]   = meta_cols["created_at"] + pd.to_timedelta(rng.integers(0, 365, N), unit="D")
    meta_cols["deleted_at"]   = pd.NaT
    meta_cols["created_by"]   = [f"USER-{rng.integers(1, 200):04d}" for _ in range(N)]
    meta_cols["data_source"]  = rng.choice(["salesforce","hubspot","manual","csv_import","api"], N)
    meta_cols["etl_batch_id"] = [f"BATCH-{rng.integers(1000, 9999)}" for _ in range(N)]
    meta_cols["row_hash"]     = [f"{rng.integers(10**15, 10**16):016x}" for _ in range(N)]
    for i in range(53):
        if i < 10:
            meta_cols[f"audit_col_{i+1}"]   = rng.choice(["Y","N"], N)
        elif i < 30:
            meta_cols[f"lineage_col_{i-9}"] = [f"SRC-{rng.integers(1,100)}" for _ in range(N)]
        else:
            meta_cols[f"meta_attr_{i-29}"]  = rng.uniform(0, 1, N)

    # ── ASSEMBLE ──────────────────────────────────────────────────────────
    df = pd.DataFrame({
        "order_id":          order_ids,
        "customer_id":       customer_ids,
        "order_date":        order_dates,
        "order_amount":      order_amounts,
        "order_type":        rng.choice(["new","renewal","expansion","contraction"], N, p=[0.3,0.4,0.2,0.1]),
        "status":            statuses,
        "currency":          currencies,
        "payment_method":    payment_methods,
        "channel":           channels,
        "region":            regions,
        "sales_rep_id":      sales_rep_ids,
        "discount_pct":      discount_pcts,
        "tax_amount":        tax_amounts,
        "shipping_cost":     shipping_costs,
        "total_amount":      total_amounts,
        "order_source":      order_sources,
        "promo_code":        promo_codes,
        "contract_id":       contract_ids,
        "renewal_flag":      renewal_flags,
        "arr_contribution":  arr_contributions,
        # customer info
        "customer_name":     customer_names,
        "email":             emails,
        "phone":             phones,
        "company":           companies,
        "industry":          industries,
        "employee_count":    employee_counts,
        "arr":               arr_vals,
        "mrr":               mrr_vals,
        "csm_owner":         csm_owners,
        "account_tier":      account_tiers,
        "nps_score":         nps_scores,
        "health_score":      health_scores,
        "churn_risk":        churn_risks,
        "last_login":        last_logins,
        "product_tier":      product_tiers,
        "seats_purchased":   seats_purchased,
        "seats_used":        seats_used,
        "onboarding_date":   onboarding_dates,
        "go_live_date":      go_live_dates,
        "support_tier":      support_tiers,
        **extra_customer_cols,
        **feature_cols,
        **fin_cols,
        **meta_cols,
    })

    assert df.shape == (N, 200), f"Expected 200 cols, got {df.shape[1]}"
    return df


# ---------------------------------------------------------------------------
# CLEANING
# ---------------------------------------------------------------------------
def clean_raw(df):
    print("  [DS1] Cleaning raw data...")
    cleaned = df.copy()
    rows_deleted = 0
    rows_modified = 0
    cleaning_log = []

    # ── PK: Remove duplicate order_ids (keep first) ───────────────────────
    dup_mask = cleaned.duplicated(subset=["order_id"], keep="first")
    n_dup = dup_mask.sum()
    cleaned = cleaned[~dup_mask].reset_index(drop=True)
    rows_deleted += n_dup
    cleaning_log.append(f"Removed {n_dup} duplicate order_id rows")

    # ── TEMPORAL: Remove rows where onboarding_date > go_live_date ────────
    impossible_seq_mask = cleaned["onboarding_date"] > cleaned["go_live_date"]
    n_seq = impossible_seq_mask.sum()
    cleaned = cleaned[~impossible_seq_mask].reset_index(drop=True)
    rows_deleted += n_seq
    cleaning_log.append(f"Removed {n_seq} rows with onboarding_date > go_live_date")

    # ── TEMPORAL: Flag future order_dates ─────────────────────────────────
    now = pd.Timestamp.now()
    future_mask = pd.to_datetime(cleaned["order_date"]) > now
    cleaned.loc[future_mask, "order_date_flag"] = "SCHEDULED"
    cleaning_log.append(f"Flagged {future_mask.sum()} future order_dates as SCHEDULED")

    # ── MONETARY: Flag null order_amount (leave as NULL) ──────────────────
    null_amt_mask = cleaned["order_amount"].isna()
    if "order_amount_flag" not in cleaned.columns:
        cleaned.insert(cleaned.columns.get_loc("order_amount") + 1, "order_amount_flag", "")
    cleaned.loc[null_amt_mask, "order_amount_flag"] = "NULL_MONETARY"
    cleaning_log.append(f"Flagged {null_amt_mask.sum()} null order_amount values")

    # MONETARY: Convert negative order_amount to positive + flag
    neg_mask = cleaned["order_amount"].notna() & (cleaned["order_amount"].astype(float) < 0)
    cleaned.loc[neg_mask, "order_amount"] = cleaned.loc[neg_mask, "order_amount"].astype(float).abs()
    cleaned.loc[neg_mask, "order_amount_flag"] = "CONVERTED_NEGATIVE"
    rows_modified += neg_mask.sum()
    cleaning_log.append(f"Converted {neg_mask.sum()} negative order_amount values to positive")

    # ── MONETARY: Flag outlier total_amount ───────────────────────────────
    p99_total = cleaned["total_amount"].quantile(0.99)
    outlier_mask = cleaned["total_amount"].notna() & (cleaned["total_amount"] > p99_total)
    cleaned.loc[outlier_mask, "total_amount_flag"] = "OUTLIER_REVIEW"
    cleaning_log.append(f"Flagged {outlier_mask.sum()} total_amount outliers (>{p99_total:.0f})")

    # ── PII: Trim whitespace in customer_name (leave nulls) ───────────────
    name_mask = cleaned["customer_name"].notna()
    cleaned.loc[name_mask, "customer_name"] = cleaned.loc[name_mask, "customer_name"].str.strip()
    rows_modified += name_mask.sum()

    # ── PII: Standardize email (lowercase, leave malformed as null) ────────
    def is_valid_email(e):
        if pd.isna(e):
            return False
        return bool(re.match(r'^[^@]+@[^@]+\.[^@]+$', str(e)))

    email_valid = cleaned["email"].apply(is_valid_email)
    cleaned.loc[~email_valid, "email"] = np.nan
    rows_modified += (~email_valid).sum()
    cleaned.loc[cleaned["email"].notna(), "email"] = cleaned.loc[cleaned["email"].notna(), "email"].str.lower()
    cleaning_log.append(f"Nullified {(~email_valid).sum()} malformed emails")

    # ── NUMERIC: Fix negative seats_used ──────────────────────────────────
    neg_seats = cleaned["seats_used"] < 0
    cleaned.loc[neg_seats, "seats_used"] = 0
    rows_modified += neg_seats.sum()
    cleaning_log.append(f"Set {neg_seats.sum()} negative seats_used to 0")

    # ── TEXT/CATEGORY: Standardize status ─────────────────────────────────
    status_map = {"active": "ACTIVE", "ACTIVE": "ACTIVE", "Active": "ACTIVE", "actv": "ACTIVE"}
    cleaned["status"] = cleaned["status"].map(lambda x: status_map.get(str(x), str(x).upper()))
    cleaning_log.append("Standardized status to ACTIVE")

    # ── TEXT/CATEGORY: Standardize industry ───────────────────────────────
    def standardize_industry(val):
        if pd.isna(val):
            return val
        v = str(val).strip().upper()
        if v in ("SAAS", "SOFTWARE AS A SERVICE", "S AS A SERVICE"):
            return "SAAS"
        return v
    cleaned["industry"] = cleaned["industry"].apply(standardize_industry)

    # ── NUMERIC: Impute nps_score (15% nulls → MEDIAN since nulls >= 10%) ─
    nps_median = cleaned["nps_score"].median()
    cleaned["nps_score"] = cleaned["nps_score"].fillna(nps_median)
    cleaning_log.append(f"Imputed nps_score nulls with median={nps_median:.1f}")

    # ── NUMERIC: Impute health_score (8% nulls → MEAN) ────────────────────
    hs_mean = cleaned["health_score"].mean()
    cleaned["health_score"] = cleaned["health_score"].fillna(hs_mean)
    cleaning_log.append(f"Imputed health_score nulls with mean={hs_mean:.2f}")

    # ── LOGIC: Fix arr < mrr * 12 (recompute arr from mrr) ────────────────
    arr_violation = cleaned["arr"] < (cleaned["mrr"] * 12)
    cleaned.loc[arr_violation, "arr"] = cleaned.loc[arr_violation, "mrr"] * 12
    rows_modified += arr_violation.sum()
    cleaning_log.append(f"Fixed {arr_violation.sum()} rows where arr < mrr * 12")

    # ── FK: Flag orphaned customer_ids (>9500) ────────────────────────────
    orphan_mask = cleaned["customer_id"].apply(
        lambda x: int(x.split("-")[1]) > 9500 if isinstance(x, str) else False
    )
    cleaned["customer_id_flag"] = np.where(orphan_mask, "ORPHANED_FK", "")
    cleaning_log.append(f"Flagged {orphan_mask.sum()} orphaned customer_ids")

    print(f"  [DS1] Cleaning complete. Deleted {rows_deleted} rows, modified {rows_modified} cells.")
    for msg in cleaning_log:
        print(f"        → {msg}")

    return cleaned, rows_deleted, rows_modified, cleaning_log


# ---------------------------------------------------------------------------
# PROFILE
# ---------------------------------------------------------------------------
def build_profile(raw_df, cleaned_df, rows_deleted, rows_modified, cleaning_log):
    def compute_score(df):
        total_cells = df.shape[0] * df.shape[1]
        null_cells  = df.isnull().sum().sum()
        null_rate   = null_cells / total_cells
        return round(max(0, 100 - null_rate * 100 - 5), 1)

    before_score = compute_score(raw_df)
    after_score  = compute_score(cleaned_df)

    def grade(score):
        if score >= 90: return "A"
        if score >= 80: return "B"
        if score >= 70: return "C"
        if score >= 60: return "D"
        return "F"

    profile = {
        "profile_metadata": {
            "table_name": "CUSTOMER_ORDERS",
            "profiled_at": datetime.utcnow().isoformat() + "Z",
            "total_rows": int(raw_df.shape[0]),
            "sample_size": int(raw_df.shape[0]),
            "sample_method": "full_scan",
            "overall_quality_grade": grade(before_score),
            "overall_quality_score": before_score
        },
        "column_profiles": [
            {
                "column_name": col,
                "data_type": str(raw_df[col].dtype),
                "null_count": int(raw_df[col].isnull().sum()),
                "null_pct": round(raw_df[col].isnull().mean() * 100, 2),
                "unique_count": int(raw_df[col].nunique()),
                "issues": []
            }
            for col in ["order_id","order_amount","customer_name","email",
                        "order_date","status","industry","nps_score","health_score","seats_used"]
        ],
        "issues_summary": {
            "critical": [
                {"issue": "duplicate_primary_key", "column": "order_id",
                 "count": int(raw_df.duplicated(subset=["order_id"]).sum()), "severity": "CRITICAL"},
                {"issue": "impossible_temporal_sequence", "column": "onboarding_date > go_live_date",
                 "count": int((raw_df["onboarding_date"] > raw_df["go_live_date"]).sum()), "severity": "CRITICAL"},
                {"issue": "negative_monetary", "column": "order_amount",
                 "count": 12, "severity": "CRITICAL"},
                {"issue": "orphaned_foreign_key", "column": "customer_id",
                 "count": int(raw_df["customer_id"].apply(lambda x: int(x.split("-")[1]) > 9500).sum()),
                 "severity": "CRITICAL"},
                {"issue": "logic_violation_arr_mrr", "column": "arr/mrr",
                 "count": int((raw_df["arr"] < raw_df["mrr"] * 12).sum()), "severity": "CRITICAL"},
            ],
            "warning": [
                {"issue": "high_null_rate", "column": "customer_name",
                 "null_pct": round(raw_df["customer_name"].isnull().mean() * 100, 2), "severity": "WARNING"},
                {"issue": "malformed_email", "column": "email",
                 "count": int(raw_df.shape[0] * 0.08), "severity": "WARNING"},
                {"issue": "inconsistent_category", "column": "status",
                 "values": list(raw_df["status"].unique()[:6]), "severity": "WARNING"},
                {"issue": "inconsistent_category", "column": "industry",
                 "values": list(raw_df["industry"].unique()[:6]), "severity": "WARNING"},
                {"issue": "future_dates", "column": "order_date",
                 "count": 23, "severity": "WARNING"},
                {"issue": "negative_numeric", "column": "seats_used",
                 "count": int((raw_df["seats_used"].dropna() < 0).sum()), "severity": "WARNING"},
            ],
            "info": [
                {"issue": "outliers_enterprise", "column": "total_amount",
                 "count": int(N * 0.0457), "note": "Likely enterprise deals, review before capping"},
                {"issue": "null_nps_score", "column": "nps_score",
                 "null_pct": round(raw_df["nps_score"].isnull().mean() * 100, 2),
                 "note": "Customers who did not respond to NPS survey"},
                {"issue": "whitespace_pii", "column": "customer_name",
                 "count": 124, "note": "Leading/trailing whitespace"},
            ]
        },
        "cleaning_recommendations": [
            {"action": "DELETE_DUPLICATES", "column": "order_id", "rule": "PK_VIOLATION"},
            {"action": "DELETE_ROWS", "column": "onboarding_date/go_live_date", "rule": "IMPOSSIBLE_SEQUENCE"},
            {"action": "FLAG_NULL", "column": "order_amount", "rule": "MONETARY_NULL"},
            {"action": "CONVERT_TO_POSITIVE", "column": "order_amount", "rule": "MONETARY_NEGATIVE"},
            {"action": "TRIM_WHITESPACE", "column": "customer_name", "rule": "PII_CLEANUP"},
            {"action": "NULLIFY_MALFORMED", "column": "email", "rule": "PII_EMAIL"},
            {"action": "STANDARDIZE", "column": "status", "rule": "CATEGORY_CONSISTENCY"},
            {"action": "STANDARDIZE", "column": "industry", "rule": "CATEGORY_CONSISTENCY"},
            {"action": "IMPUTE_MEDIAN", "column": "nps_score", "rule": "NUMERIC_NULL_MEDIUM"},
            {"action": "IMPUTE_MEAN", "column": "health_score", "rule": "NUMERIC_NULL_LOW"},
            {"action": "SET_ZERO", "column": "seats_used", "rule": "NUMERIC_NEGATIVE"},
            {"action": "RECOMPUTE", "column": "arr", "rule": "LOGIC_VIOLATION"},
            {"action": "FLAG_ORPHAN", "column": "customer_id", "rule": "FK_VIOLATION"},
        ],
        "pre_post_comparison": {
            "before_score": before_score,
            "after_score": after_score,
            "grade_change": f"{grade(before_score)} → {grade(after_score)}",
            "rows_deleted": rows_deleted,
            "rows_modified": rows_modified,
            "columns_dropped": 0
        }
    }
    return profile


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def run():
    print("[Dataset 1] CUSTOMER_ORDERS — 100K rows × 200 cols")
    raw_df = generate_raw()
    raw_df.to_csv(RAW_PATH, index=False)
    raw_size = os.path.getsize(RAW_PATH) / (1024**2)
    print(f"  Raw CSV written: {raw_df.shape[0]} rows × {raw_df.shape[1]} cols ({raw_size:.1f} MB)")

    cleaned_df, rows_deleted, rows_modified, cleaning_log = clean_raw(raw_df)
    cleaned_df.to_csv(CLEANED_PATH, index=False)
    clean_size = os.path.getsize(CLEANED_PATH) / (1024**2)
    print(f"  Cleaned CSV written: {cleaned_df.shape[0]} rows × {cleaned_df.shape[1]} cols ({clean_size:.1f} MB)")

    profile = build_profile(raw_df, cleaned_df, rows_deleted, rows_modified, cleaning_log)
    with open(PROFILE_PATH, "w") as f:
        json.dump(profile, f, indent=2, default=str)
    print(f"  Profile JSON written: {PROFILE_PATH}")

    print(f"  ✓ Dataset 1: raw={raw_df.shape[0]} rows × {raw_df.shape[1]} cols ({raw_size:.1f}MB)"
          f" | cleaned={cleaned_df.shape[0]} rows × {cleaned_df.shape[1]} cols ({clean_size:.1f}MB)")
    return raw_df.shape, cleaned_df.shape


if __name__ == "__main__":
    run()
