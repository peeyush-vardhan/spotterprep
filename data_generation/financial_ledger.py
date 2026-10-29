"""
financial_ledger.py — FINANCIAL_LEDGER
1,000,000 rows × 480 columns
General ledger / financial accounting — 3 years of transactions
"""

import numpy as np
import pandas as pd
import json
import os
import re
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

np.random.seed(42)
rng = np.random.default_rng(42)

N = 1_000_000
OUT_DIR      = os.path.join(os.path.dirname(__file__), "..", "data")
RAW_PATH     = os.path.join(OUT_DIR, "raw",      "dataset4_financial_ledger.csv")
CLEANED_PATH = os.path.join(OUT_DIR, "cleaned",  "dataset4_financial_ledger_cleaned.csv")
PROFILE_PATH = os.path.join(OUT_DIR, "profiles", "dataset4_profile.json")
for _p in (RAW_PATH, CLEANED_PATH, PROFILE_PATH):
    os.makedirs(os.path.dirname(_p), exist_ok=True)



def random_dates(start, end, n):
    s = pd.Timestamp(start).value // 10**9
    e = pd.Timestamp(end).value   // 10**9
    return pd.to_datetime(rng.integers(s, e, n), unit="s")


# ---------------------------------------------------------------------------
# RAW GENERATION
# ---------------------------------------------------------------------------
def generate_raw():
    print("  [DS4] Generating raw data (1M rows × 480 cols)...")

    # ── TRANSACTION CORE (40 cols) ────────────────────────────────────────
    txn_ids = [f"TXN-{i:09d}" for i in range(1, N + 1)]
    # Issue 3: 0.3% duplicate transaction_ids
    n_dups = int(N * 0.003)
    dup_tgt = rng.choice(range(N//2, N), size=n_dups, replace=False)
    dup_src = rng.choice(range(0, N//2),  size=n_dups, replace=False)
    txn_arr = np.array(txn_ids)
    for t, s in zip(dup_tgt, dup_src):
        txn_arr[t] = txn_arr[s]

    # Journal entries — groups of ~4 lines per entry
    n_journals = N // 4
    journal_ids_pool = [f"JE-{i:07d}" for i in range(1, n_journals + 1)]
    journal_ids = rng.choice(journal_ids_pool, N)

    posting_dates   = random_dates("2021-01-01", "2024-06-01", N)
    effective_dates = posting_dates - pd.to_timedelta(rng.integers(0, 30, N), unit="D")

    # Issue 5: 200 rows where posting_date > effective_date by > 365 days
    lag_idx = rng.choice(N, size=200, replace=False)
    eff_list = effective_dates.tolist()
    post_list = posting_dates.tolist()
    for i in lag_idx:
        eff_list[i] = post_list[i] - timedelta(days=int(rng.integers(366, 730)))
    effective_dates = pd.DatetimeIndex(eff_list)

    # Issue 6: 100 future posting_dates
    future_idx = rng.choice(N, size=100, replace=False)
    post_list2 = posting_dates.tolist()
    for i in future_idx:
        post_list2[i] = pd.Timestamp("2025-01-01") + pd.to_timedelta(rng.integers(1, 365), unit="D")
    posting_dates = pd.DatetimeIndex(post_list2)

    # fiscal calendar
    fiscal_years    = rng.choice([2021, 2022, 2023, 2024], N, p=[0.25,0.3,0.3,0.15])
    fiscal_quarters = rng.choice(["Q1","Q2","Q3","Q4"], N)
    fiscal_periods  = rng.integers(1, 13, N)

    debit_amounts  = rng.uniform(10, 500000, N)
    credit_amounts = rng.uniform(10, 500000, N)
    # Issue 4: 800 negative debit_amounts
    neg_debit_idx = rng.choice(N, size=800, replace=False)
    debit_amounts[neg_debit_idx] = -debit_amounts[neg_debit_idx]

    # net_amount should = debit - credit
    net_amounts = debit_amounts - credit_amounts
    # Issue 9: 1% net_amount ≠ debit - credit (calculation error)
    n_calc_err = int(N * 0.01)
    calc_err_idx = rng.choice(N, size=n_calc_err, replace=False)
    net_amounts[calc_err_idx] = net_amounts[calc_err_idx] * rng.uniform(0.8, 1.2, n_calc_err)

    # Issue 2: floating-point precision errors
    n_fp = int(N * 0.02)
    fp_idx = rng.choice(N, size=n_fp, replace=False)
    for i in fp_idx:
        debit_amounts[i] = round(debit_amounts[i], 8) + rng.uniform(-0.000001, 0.000001)

    # Issue 14: 0.5% amounts with > 2 decimal places
    n_prec = int(N * 0.005)
    prec_idx = rng.choice(N, size=n_prec, replace=False)
    for i in prec_idx:
        debit_amounts[i] = round(debit_amounts[i], 4)

    currencies  = rng.choice(["USD","EUR","GBP","JPY","INR","CAD","AUD"], N, p=[0.6,0.15,0.1,0.05,0.04,0.03,0.03])
    fx_rates    = np.ones(N)
    non_usd     = np.array(currencies) != "USD"
    fx_map = {"EUR":1.1,"GBP":1.25,"JPY":0.0067,"INR":0.012,"CAD":0.74,"AUD":0.65}
    for cur, rate in fx_map.items():
        mask = np.array(currencies) == cur
        fx_rates[mask] = rng.uniform(rate*0.95, rate*1.05, mask.sum())

    # Issue 7: 2% nulls in fx_rate for non-USD
    n_fx_null = int(non_usd.sum() * 0.02)
    non_usd_idx = np.where(non_usd)[0]
    fx_null_idx = rng.choice(non_usd_idx, size=n_fx_null, replace=False)
    fx_rates_obj = fx_rates.astype(object)
    fx_rates_obj[fx_null_idx] = np.nan

    txn_extra = {}
    for i in range(28):
        txn_extra[f"txn_attr_{i+1}"] = rng.uniform(0, 100000, N)

    # ── ACCOUNT STRUCTURE (60 cols) ───────────────────────────────────────
    # Issue 8: account_code format inconsistencies
    acc_pool_clean = [f"{i:04d}" for i in range(1000, 9999, 10)]
    def random_account_code(clean):
        r = rng.random()
        if r < 0.6:
            return clean
        elif r < 0.7:
            return clean + "-00"
        elif r < 0.8:
            return "GL-" + clean
        elif r < 0.9:
            return "0" + clean
        else:
            return clean.lstrip("0") or "0"

    account_codes = np.array([random_account_code(rng.choice(acc_pool_clean)) for _ in range(N)])
    account_names = rng.choice(["Revenue","Cost of Sales","Operating Expense","Payroll",
                                 "Capital Expenditure","Amortization","Tax Provision",
                                 "Accounts Receivable","Accounts Payable","Cash"], N)
    account_types = rng.choice(["Asset","Liability","Equity","Revenue","Expense"], N)
    cost_centers  = [f"CC-{rng.integers(100,999)}" for _ in range(N)]
    dept_codes    = rng.choice(["ENG","SALES","MKT","FIN","OPS","HR","LEGAL"], N)
    legal_entities= rng.choice(["US-HQ","UK-LTD","DE-GMBH","IN-PVT","CA-INC"], N, p=[0.5,0.2,0.1,0.1,0.1])
    intercompany  = rng.choice([0, 1], N, p=[0.85, 0.15])

    acct_extra = {}
    for i in range(53):
        acct_extra[f"acct_attr_{i+1}"] = rng.choice(["Y","N","N/A"], N)

    # ── VENDOR/CUSTOMER (50 cols) ──────────────────────────────────────────
    n_vendors = 5000
    vendor_master_ids = [f"VND-{i:05d}" for i in range(1, n_vendors+1)]
    vendor_ids_arr = np.array(rng.choice(vendor_master_ids, N), dtype=object)
    # Issue 11: 1% vendor_ids not in master
    n_ghost_vnd = int(N * 0.01)
    ghost_idx = rng.choice(N, size=n_ghost_vnd, replace=False)
    for i in ghost_idx:
        vendor_ids_arr[i] = f"VND-GHOST-{rng.integers(1,9999):04d}"

    vendor_names   = rng.choice([f"Vendor Corp {i}" for i in range(1, 500)], N)
    customer_ids   = [f"CUST-{rng.integers(1,20000):06d}" for _ in range(N)]
    invoice_numbers= [f"INV-{rng.integers(100000,999999)}" for _ in range(N)]
    po_numbers     = [f"PO-{rng.integers(10000,99999)}" if rng.random() < 0.7 else "" for _ in range(N)]

    vend_extra = {}
    for i in range(45):
        vend_extra[f"vend_attr_{i+1}"] = rng.uniform(0, 1000, N)

    # ── APPROVAL WORKFLOW (40 cols) ───────────────────────────────────────
    created_by_arr  = [f"USER-{rng.integers(1,500):04d}" for _ in range(N)]
    approved_by_arr = [f"USER-{rng.integers(1,100):04d}" for _ in range(N)]
    approval_dates  = posting_dates + pd.to_timedelta(rng.integers(1, 5, N), unit="D")
    # Issue 12: 300 rows where approval_date < posting_date
    appr_before_idx = rng.choice(N, size=300, replace=False)
    appr_list = approval_dates.tolist()
    post_list3 = posting_dates.tolist()
    for i in appr_before_idx:
        appr_list[i] = post_list3[i] - timedelta(days=int(rng.integers(1, 10)))
    approval_dates = pd.DatetimeIndex(appr_list)

    # Issue 10: approval_status inconsistencies
    appr_status_pool = ["approved","APPROVED","Approved","apprvd","pending","PENDING","rejected"]
    approval_status = rng.choice(appr_status_pool, N, p=[0.3,0.25,0.2,0.05,0.1,0.07,0.03])
    review_flags    = rng.choice([0, 1], N, p=[0.9, 0.1])
    appr_extra = {}
    for i in range(35):
        appr_extra[f"appr_attr_{i+1}"] = rng.choice(["Y","N"], N)

    # ── AUDIT & COMPLIANCE (80 cols) ──────────────────────────────────────
    sox_control_ids = [f"SOX-{rng.integers(1,200):03d}" for _ in range(N)]
    audit_flags     = rng.choice([0, 1], N, p=[0.95, 0.05])
    restatement_flags= rng.choice([0, 1], N, p=[0.99, 0.01])
    audit_extra = {}
    for i in range(76):
        audit_extra[f"audit_attr_{i+1}"] = rng.choice(["Y","N","N/A"], N)

    # ── RECONCILIATION (60 cols) ───────────────────────────────────────────
    reconciled_flag = rng.choice([0, 1], N, p=[0.3, 0.7])
    reconciled_dates= random_dates("2021-01-01", "2024-06-01", N)
    reconciled_by   = [f"USER-{rng.integers(1,50):03d}" for _ in range(N)]
    variance_amounts= rng.uniform(-1000, 1000, N)
    # Issue 1 setup: 500 journal entries where SUM(debit) ≠ SUM(credit)
    # We'll mark them with an imbalanced_je flag
    imbalanced_je_flag = np.zeros(N, dtype=int)
    n_imbal = 500 * 4  # ~500 journals × 4 lines = 2000 rows
    imbal_idx = rng.choice(N, size=min(n_imbal, N), replace=False)
    imbalanced_je_flag[imbal_idx] = 1
    # for these, skew debit vs credit
    debit_amounts[imbal_idx] = debit_amounts[imbal_idx] * rng.uniform(1.01, 1.1, len(imbal_idx))

    # Issue 13: intercompany transactions that don't net to zero (600 entries)
    ic_mask = intercompany == 1
    ic_idx  = np.where(ic_mask)[0]
    ic_unbalanced_flag = np.zeros(N, dtype=int)
    n_ic_unbal = min(600 * 2, len(ic_idx))
    ic_unbal_idx = rng.choice(ic_idx, size=n_ic_unbal, replace=False)
    ic_unbalanced_flag[ic_unbal_idx] = 1

    recon_extra = {}
    for i in range(55):
        recon_extra[f"recon_attr_{i+1}"] = rng.uniform(-100, 100, N)

    # ── METADATA (150 cols) ───────────────────────────────────────────────
    batch_ids     = [f"BATCH-{rng.integers(10000,99999)}" for _ in range(N)]
    source_systems= rng.choice(["SAP","Oracle","NetSuite","QuickBooks","Manual"], N, p=[0.35,0.3,0.2,0.1,0.05])
    etl_timestamps= random_dates("2021-01-01", "2024-06-01", N)
    row_versions  = rng.integers(1, 10, N)
    meta_extra = {}
    for i in range(146):
        if i < 50:
            meta_extra[f"lineage_col_{i+1}"] = [f"SRC-{rng.integers(1,100)}" for _ in range(N)]
        elif i < 100:
            meta_extra[f"etl_flag_{i-49}"]   = rng.choice(["Y","N"], N)
        else:
            meta_extra[f"tech_col_{i-99}"]   = rng.integers(0, 1000, N)

    # ── ASSEMBLE ──────────────────────────────────────────────────────────
    df = pd.DataFrame({
        "transaction_id":     txn_arr,
        "journal_entry_id":   journal_ids,
        "posting_date":       posting_dates,
        "effective_date":     effective_dates,
        "fiscal_year":        fiscal_years,
        "fiscal_quarter":     fiscal_quarters,
        "fiscal_period":      fiscal_periods,
        "debit_amount":       debit_amounts,
        "credit_amount":      credit_amounts,
        "net_amount":         net_amounts,
        "currency":           currencies,
        "fx_rate":            fx_rates_obj,
        **txn_extra,
        # account structure
        "account_code":       account_codes,
        "account_name":       account_names,
        "account_type":       account_types,
        "cost_center":        cost_centers,
        "department_code":    dept_codes,
        "legal_entity":       legal_entities,
        "intercompany_flag":  intercompany,
        **acct_extra,
        # vendor/customer
        "vendor_id":          vendor_ids_arr,
        "vendor_name":        vendor_names,
        "customer_id":        customer_ids,
        "invoice_number":     invoice_numbers,
        "po_number":          po_numbers,
        **vend_extra,
        # approval workflow
        "created_by":         created_by_arr,
        "approved_by":        approved_by_arr,
        "approval_date":      approval_dates,
        "approval_status":    approval_status,
        "review_flag":        review_flags,
        **appr_extra,
        # audit & compliance
        "sox_control_id":     sox_control_ids,
        "audit_flag":         audit_flags,
        "restatement_flag":   restatement_flags,
        "imbalanced_je_flag": imbalanced_je_flag,
        **audit_extra,
        # reconciliation
        "reconciled_flag":    reconciled_flag,
        "reconciled_date":    reconciled_dates,
        "reconciled_by":      reconciled_by,
        "variance_amount":    variance_amounts,
        "ic_unbalanced_flag": ic_unbalanced_flag,
        **recon_extra,
        # metadata
        "batch_id":           batch_ids,
        "source_system":      source_systems,
        "etl_timestamp":      etl_timestamps,
        "row_version":        row_versions,
        **meta_extra,
    })

    assert df.shape == (N, 480), f"Expected 480 cols, got {df.shape[1]}"
    return df


# ---------------------------------------------------------------------------
# CLEANING
# ---------------------------------------------------------------------------
def clean_raw(df):
    print("  [DS4] Cleaning raw data...")
    cleaned = df.copy()
    rows_deleted = 0
    rows_modified = 0
    log = []

    # PK: Remove duplicate transaction_ids
    dup_mask = cleaned.duplicated(subset=["transaction_id"], keep="first")
    n_dup = dup_mask.sum()
    cleaned = cleaned[~dup_mask].reset_index(drop=True)
    rows_deleted += n_dup
    log.append(f"Removed {n_dup} duplicate transaction_id rows")

    # MONETARY: Convert negative debit_amounts to positive + flag
    neg_debit = cleaned["debit_amount"] < 0
    cleaned["debit_amount_flag"] = np.where(neg_debit, "NEGATIVE_DEBIT", "")
    cleaned.loc[neg_debit, "debit_amount"] = cleaned.loc[neg_debit, "debit_amount"].abs()
    rows_modified += neg_debit.sum()
    log.append(f"Fixed {neg_debit.sum()} negative debit_amount values")

    # NUMERIC: Recompute net_amount from source columns
    calc_err = (cleaned["net_amount"] - (cleaned["debit_amount"] - cleaned["credit_amount"])).abs() > 0.01
    cleaned.loc[calc_err, "net_amount"] = cleaned.loc[calc_err, "debit_amount"] - cleaned.loc[calc_err, "credit_amount"]
    rows_modified += calc_err.sum()
    log.append(f"Recomputed net_amount for {calc_err.sum()} rows with calculation errors")

    # MONETARY: Round amounts to 2 decimal places
    for col in ["debit_amount","credit_amount","net_amount"]:
        cleaned[col] = cleaned[col].round(2)
    log.append("Rounded monetary amounts to 2 decimal places")

    # TEMPORAL: Flag future posting_dates
    now = pd.Timestamp.now()
    future_post = pd.to_datetime(cleaned["posting_date"]) > now
    cleaned["posting_date_flag"] = np.where(future_post, "FUTURE_DATE", "")
    log.append(f"Flagged {future_post.sum()} future posting_dates")

    # TEMPORAL: Flag large posting-to-effective lag
    lag_days = (pd.to_datetime(cleaned["posting_date"]) - pd.to_datetime(cleaned["effective_date"])).dt.days
    large_lag = lag_days > 365
    cleaned["effective_date_flag"] = np.where(large_lag, "UNUSUAL_LAG_365D", "")
    log.append(f"Flagged {large_lag.sum()} rows with posting_date > effective_date + 365 days")

    # TEMPORAL: Flag approval_date < posting_date
    appr_before = pd.to_datetime(cleaned["approval_date"]) < pd.to_datetime(cleaned["posting_date"])
    cleaned["approval_date_flag"] = np.where(appr_before, "APPROVED_BEFORE_POSTED", "")
    log.append(f"Flagged {appr_before.sum()} rows where approval_date < posting_date")

    # NUMERIC: Impute fx_rate nulls (2% of non-USD) — median by currency
    fx_null = cleaned["fx_rate"].isna()
    for cur in ["EUR","GBP","JPY","INR","CAD","AUD"]:
        cur_mask = cleaned["currency"] == cur
        median_rate = pd.to_numeric(cleaned.loc[cur_mask & ~fx_null, "fx_rate"], errors="coerce").median()
        fill_mask = cur_mask & fx_null
        cleaned.loc[fill_mask, "fx_rate"] = median_rate
        rows_modified += fill_mask.sum()
    log.append("Imputed fx_rate nulls with median rate by currency")

    # TEXT: Standardize account_code to "NNNN" format
    def std_account_code(v):
        if pd.isna(v):
            return v
        v = str(v).strip().upper()
        v = re.sub(r'^GL-', '', v).replace("-00","").replace("0","",1) if v.startswith("0") and len(v)>4 else v
        v = re.sub(r'^GL-', '', v)
        return v.zfill(4)[:4]
    cleaned["account_code"] = cleaned["account_code"].apply(std_account_code)
    log.append("Standardized account_code format")

    # TEXT: Standardize approval_status
    status_map = {
        "approved":"APPROVED","APPROVED":"APPROVED","Approved":"APPROVED","apprvd":"APPROVED",
        "pending":"PENDING","PENDING":"PENDING","rejected":"REJECTED"
    }
    cleaned["approval_status"] = cleaned["approval_status"].map(
        lambda x: status_map.get(str(x), str(x).upper()))

    # FK: Flag orphaned vendor_ids
    orphan_vnd = cleaned["vendor_id"].apply(lambda x: "GHOST" in str(x))
    cleaned["vendor_id_flag"] = np.where(orphan_vnd, "ORPHANED_FK", "")
    log.append(f"Flagged {orphan_vnd.sum()} orphaned vendor_id references")

    # FLAG imbalanced journal entries and intercompany violations
    log.append(f"Flagged imbalanced JEs: {(cleaned['imbalanced_je_flag']==1).sum()} rows")
    log.append(f"Flagged IC unbalanced: {(cleaned['ic_unbalanced_flag']==1).sum()} rows")

    print(f"  [DS4] Done. Deleted {rows_deleted} rows, modified {rows_modified} cells.")
    for msg in log:
        print(f"        → {msg}")
    return cleaned, rows_deleted, rows_modified, log


# ---------------------------------------------------------------------------
# PROFILE
# ---------------------------------------------------------------------------
def build_profile(raw_df, cleaned_df, rows_deleted, rows_modified, log):
    def score(df):
        total = df.shape[0] * df.shape[1]
        nulls = df.isnull().sum().sum()
        return round(max(0, 100 - nulls/total*100 - 3), 1)
    def grade(s):
        return "A" if s>=90 else "B" if s>=80 else "C" if s>=70 else "D" if s>=60 else "F"
    bs = score(raw_df); as_ = score(cleaned_df)

    return {
        "profile_metadata": {
            "table_name": "FINANCIAL_LEDGER",
            "profiled_at": datetime.utcnow().isoformat() + "Z",
            "total_rows": int(raw_df.shape[0]),
            "sample_size": int(raw_df.shape[0]),
            "sample_method": "full_scan",
            "overall_quality_grade": grade(bs),
            "overall_quality_score": bs
        },
        "column_profiles": [
            {"column_name": c, "data_type": str(raw_df[c].dtype),
             "null_count": int(raw_df[c].isnull().sum()),
             "null_pct": round(raw_df[c].isnull().mean()*100, 2),
             "unique_count": int(raw_df[c].nunique())}
            for c in ["transaction_id","debit_amount","credit_amount","net_amount",
                      "fx_rate","account_code","approval_status","vendor_id","posting_date"]
        ],
        "issues_summary": {
            "critical": [
                {"issue": "imbalanced_journal_entries", "column": "debit/credit",
                 "count": 500, "severity": "CRITICAL"},
                {"issue": "duplicate_pk", "column": "transaction_id",
                 "count": int(raw_df.duplicated(subset=["transaction_id"]).sum()), "severity": "CRITICAL"},
                {"issue": "negative_debit", "column": "debit_amount",
                 "count": 800, "severity": "CRITICAL"},
                {"issue": "net_amount_calc_error", "column": "net_amount",
                 "count": int(N * 0.01), "severity": "CRITICAL"},
                {"issue": "intercompany_imbalance", "column": "intercompany_flag",
                 "count": 600, "severity": "CRITICAL"},
            ],
            "warning": [
                {"issue": "future_posting_date", "column": "posting_date", "count": 100, "severity": "WARNING"},
                {"issue": "approval_before_posting", "column": "approval_date", "count": 300, "severity": "WARNING"},
                {"issue": "null_fx_rate", "column": "fx_rate", "count": int(N*0.02*0.4), "severity": "WARNING"},
                {"issue": "account_code_format", "column": "account_code", "severity": "WARNING"},
                {"issue": "orphaned_vendor", "column": "vendor_id", "count": int(N*0.01), "severity": "WARNING"},
            ],
            "info": [
                {"issue": "floating_point_precision", "column": "debit_amount", "count": int(N*0.02)},
                {"issue": "approval_status_inconsistent", "column": "approval_status"},
                {"issue": "large_posting_effective_lag", "column": "posting_date", "count": 200},
            ]
        },
        "cleaning_recommendations": [
            {"action": "DELETE_DUPLICATES", "column": "transaction_id"},
            {"action": "CONVERT_TO_POSITIVE", "column": "debit_amount"},
            {"action": "RECOMPUTE", "column": "net_amount"},
            {"action": "ROUND_2DP", "column": "debit_amount,credit_amount,net_amount"},
            {"action": "IMPUTE_MEDIAN_BY_GROUP", "column": "fx_rate"},
            {"action": "STANDARDIZE_FORMAT", "column": "account_code"},
            {"action": "STANDARDIZE", "column": "approval_status"},
            {"action": "FLAG_ORPHAN", "column": "vendor_id"},
            {"action": "FLAG_IMBALANCED", "column": "journal_entry_id"},
            {"action": "FLAG_IC_IMBALANCE", "column": "intercompany_flag"},
        ],
        "pre_post_comparison": {
            "before_score": bs, "after_score": as_,
            "grade_change": f"{grade(bs)} → {grade(as_)}",
            "rows_deleted": rows_deleted, "rows_modified": rows_modified, "columns_dropped": 0
        }
    }


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def run():
    print("[Dataset 4] FINANCIAL_LEDGER — 1M rows × 480 cols")
    raw_df = generate_raw()
    raw_df.to_csv(RAW_PATH, index=False)
    raw_size = os.path.getsize(RAW_PATH) / (1024**2)
    print(f"  Raw CSV written: {raw_df.shape[0]} rows × {raw_df.shape[1]} cols ({raw_size:.1f} MB)")

    cleaned_df, rows_deleted, rows_modified, log = clean_raw(raw_df)
    cleaned_df.to_csv(CLEANED_PATH, index=False)
    clean_size = os.path.getsize(CLEANED_PATH) / (1024**2)
    print(f"  Cleaned CSV written: {cleaned_df.shape[0]} rows × {cleaned_df.shape[1]} cols ({clean_size:.1f} MB)")

    profile = build_profile(raw_df, cleaned_df, rows_deleted, rows_modified, log)
    with open(PROFILE_PATH, "w") as f:
        json.dump(profile, f, indent=2, default=str)
    print(f"  Profile JSON written: {PROFILE_PATH}")

    print(f"  ✓ Dataset 4: raw={raw_df.shape[0]} rows × {raw_df.shape[1]} cols ({raw_size:.1f}MB)"
          f" | cleaned={cleaned_df.shape[0]} rows × {cleaned_df.shape[1]} cols ({clean_size:.1f}MB)")
    return raw_df.shape, cleaned_df.shape


if __name__ == "__main__":
    run()
