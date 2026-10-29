"""
hr_workforce.py — HR_WORKFORCE
800,000 rows × 400 columns
Enterprise HR / workforce management — 6 years of historical data
Uses pooled PII generation for performance.
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

N = 800_000
POOL = 20_000   # PII pool size

OUT_DIR      = os.path.join(os.path.dirname(__file__), "..", "data")
RAW_PATH     = os.path.join(OUT_DIR, "raw",      "dataset3_hr_workforce.csv")
CLEANED_PATH = os.path.join(OUT_DIR, "cleaned",  "dataset3_hr_workforce_cleaned.csv")
PROFILE_PATH = os.path.join(OUT_DIR, "profiles", "dataset3_profile.json")
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
    print("  [DS3] Generating PII pools...")
    name_pool  = [fake.name()            for _ in range(POOL)]
    email_pool = [fake.email()           for _ in range(POOL)]
    phone_pool = [fake.phone_number()    for _ in range(POOL)]
    company_pool=[fake.company()         for _ in range(POOL)]

    print("  [DS3] Generating raw data (800K rows × 400 cols)...")

    # ── EMPLOYEE CORE (40 cols) ───────────────────────────────────────────
    employee_ids = [f"EMP-{i:07d}" for i in range(1, N + 1)]
    # Issue 15: 1% duplicate employee_ids
    n_dups = int(N * 0.01)
    dup_tgt = rng.choice(range(N//2, N), size=n_dups, replace=False)
    dup_src = rng.choice(range(0, N//2),  size=n_dups, replace=False)
    emp_ids_arr = np.array(employee_ids)
    for t, s in zip(dup_tgt, dup_src):
        emp_ids_arr[t] = emp_ids_arr[s]

    full_names = np.array(rng.choice(name_pool, N), dtype=object)
    # Issue 7: 5% nulls in full_name
    fn_null_mask = rng.random(N) < 0.05
    full_names[fn_null_mask] = np.nan
    # 300 whitespace issues
    ws_idx = rng.choice(np.where(~fn_null_mask)[0], size=300, replace=False)
    for i in ws_idx:
        full_names[i] = "  " + str(full_names[i]) + "  "

    first_names = np.array([str(n).split()[0] if not pd.isnull(n) else np.nan for n in full_names], dtype=object)
    last_names  = np.array([str(n).split()[-1] if not pd.isnull(n) else np.nan for n in full_names], dtype=object)

    emails_raw = np.array(rng.choice(email_pool, N))
    # Issue 8: 6% malformed emails
    n_mal = int(N * 0.06)
    mal_idx = rng.choice(N, size=n_mal, replace=False)
    bad_emails = ["userATdomain.com","user@domaincom","user@.com","@domain.com"]
    for i in mal_idx:
        emails_raw[i] = rng.choice(bad_emails) + str(rng.integers(100,999))

    phones_arr = np.array(rng.choice(phone_pool, N))
    hire_dates = random_dates("2018-01-01", "2024-06-01", N)

    # Issue 2: 800 future hire_dates
    future_hire_idx = rng.choice(N, size=800, replace=False)
    hire_dates_list = hire_dates.tolist()
    for i in future_hire_idx:
        hire_dates_list[i] = pd.Timestamp("2025-01-01") + pd.to_timedelta(rng.integers(1,365), unit="D")
    hire_dates = pd.DatetimeIndex(hire_dates_list)

    termination_dates = pd.Series([pd.NaT] * N, dtype="datetime64[ns]")
    term_mask = rng.random(N) < 0.25  # 25% terminated
    term_dates = hire_dates[term_mask] + pd.to_timedelta(rng.integers(180, 2000, term_mask.sum()), unit="D")
    termination_dates[np.where(term_mask)[0]] = term_dates

    # Issue 1: 1200 rows where hire_date > termination_date
    # only set on rows that have a termination date
    term_idx = np.where(term_mask)[0]
    impossible_idx = rng.choice(term_idx, size=min(1200, len(term_idx)), replace=False)
    term_dates_list = termination_dates.tolist()
    hire_dates_list2 = hire_dates.tolist()
    for i in impossible_idx:
        term_dates_list[i] = hire_dates_list2[i] - timedelta(days=int(rng.integers(1, 90)))
    termination_dates = pd.Series(term_dates_list, dtype="datetime64[ns]")

    emp_status_pool = ["active","ACTIVE","Active","terminated","Terminated"]  # Issue 10
    employment_status = rng.choice(emp_status_pool, N, p=[0.35,0.25,0.2,0.1,0.1])

    dept_pool = ["Eng","Engineering","ENGINEERING","R&D","Product","Sales","Marketing",
                 "HR","Finance","Legal","Operations","Customer Success"]  # Issue 9
    departments = rng.choice(dept_pool, N, p=[0.1,0.15,0.1,0.05,0.1,0.12,0.08,0.05,0.07,0.04,0.08,0.06])
    teams = [f"Team-{rng.integers(1,20):02d}" for _ in range(N)]

    # manager_ids: mostly valid employee IDs
    valid_emp_ids = list(emp_ids_arr[:N//2])
    manager_ids = np.array(rng.choice(valid_emp_ids, N), dtype=object)
    # Issue 14: 2% orphaned manager_ids
    n_orphan_mgr = int(N * 0.02)
    orphan_idx = rng.choice(N, size=n_orphan_mgr, replace=False)
    for i in orphan_idx:
        manager_ids[i] = f"EMP-GHOST-{rng.integers(1,9999):04d}"

    locations = rng.choice(["New York","San Francisco","London","Bangalore","Toronto","Austin","Seattle","Boston"], N)
    countries  = rng.choice(["US","US","US","US","UK","IN","CA","AU"], N)

    # extra employee core cols to reach 40
    emp_extra = {}
    for i in range(26):
        emp_extra[f"emp_attr_{i+1}"] = rng.choice(["A","B","C"], N)

    # ── COMPENSATION (60 cols) ────────────────────────────────────────────
    salary_band_min = rng.uniform(50000, 120000, N)
    salary_band_max = salary_band_min + rng.uniform(20000, 80000, N)
    base_salary     = rng.uniform(salary_band_min * 0.9, salary_band_max * 1.05, N)

    # Issue 3: 2% negative base_salary
    neg_sal_mask = rng.random(N) < 0.02
    base_salary[neg_sal_mask] = -base_salary[neg_sal_mask]

    # Issue 11: base_salary > salary_band_max in 400 rows
    band_viol_idx = rng.choice(N, size=400, replace=False)
    base_salary[band_viol_idx] = salary_band_max[band_viol_idx] * rng.uniform(1.05, 1.3, 400)

    bonus_target = rng.uniform(5000, 50000, N).astype(float)
    # Issue 5: 15% nulls in bonus_target (contractors)
    bonus_null_mask = rng.random(N) < 0.15
    bonus_target[bonus_null_mask] = np.nan

    equity_grant = rng.uniform(0, 200000, N).astype(float)
    # Issue 6: 8% nulls in equity_grant
    equity_null_mask = rng.random(N) < 0.08
    equity_grant[equity_null_mask] = np.nan

    total_comp = base_salary + np.where(pd.isnull(bonus_target), 0, bonus_target) + \
                 np.where(pd.isnull(equity_grant), 0, equity_grant) / 4.0
    # Issue 4: 3% total_comp < base_salary (bonus not added)
    tc_viol_mask = rng.random(N) < 0.03
    total_comp[tc_viol_mask] = base_salary[tc_viol_mask] * rng.uniform(0.7, 0.99, tc_viol_mask.sum())

    pay_grades = rng.choice(["L1","L2","L3","L4","L5","L6","L7","L8"], N)
    comp_extra = {}
    for i in range(53):
        comp_extra[f"comp_metric_{i+1}"] = rng.uniform(0, 100000, N)

    # ── PERFORMANCE (80 cols) ─────────────────────────────────────────────
    perf_cols = {}
    for yr in range(2019, 2025):
        ratings = rng.uniform(1, 5, N)
        # Issue 12: 0.3% outside 1-5 range
        n_oob = int(N * 0.003)
        oob_idx = rng.choice(N, size=n_oob, replace=False)
        ratings[oob_idx] = rng.choice([-1, 0, 6, 7, 8], n_oob)
        perf_cols[f"perf_rating_{yr}"] = ratings

    promotion_count     = rng.integers(0, 8, N)
    last_promotion_date = random_dates("2018-01-01", "2024-01-01", N)
    pip_flag            = rng.choice([0, 1], N, p=[0.95, 0.05])
    perf_extra = {}
    for i in range(71):
        perf_extra[f"perf_metric_{i+1}"] = rng.uniform(0, 100, N)

    # ── BENEFITS & TIME (80 cols) ──────────────────────────────────────────
    pto_days_used      = rng.integers(0, 25, N).astype(float)
    pto_days_remaining = rng.integers(0, 30, N).astype(float)
    # Issue 13: 200 rows where pto_used > pto_remaining + pto_used (logic error: used > total)
    pto_viol_idx = rng.choice(N, size=200, replace=False)
    for i in pto_viol_idx:
        pto_days_used[i] = pto_days_remaining[i] + pto_days_used[i] + rng.integers(5, 20)

    sick_days             = rng.integers(0, 15, N)
    k401_contribution_pct = rng.uniform(0, 0.15, N)
    health_plan           = rng.choice(["PPO","HMO","HSA","None"], N, p=[0.4,0.3,0.2,0.1])
    dental_plan           = rng.choice(["Basic","Premium","None"], N, p=[0.5,0.35,0.15])
    benefits_extra = {}
    for i in range(74):
        benefits_extra[f"benefits_attr_{i+1}"] = rng.uniform(0, 100, N)

    # ── LEARNING & DEVELOPMENT (60 cols) ──────────────────────────────────
    training_hours_ytd = rng.uniform(0, 200, N)
    certifications     = rng.integers(0, 10, N)
    courses_completed  = rng.integers(0, 50, N)
    ld_extra = {}
    for i in range(57):
        ld_extra[f"ld_metric_{i+1}"] = rng.uniform(0, 100, N)

    # ── RECRUITING SOURCE (30 cols) ────────────────────────────────────────
    source_channels = rng.choice(["linkedin","referral","job_board","agency","direct","university"], N)
    recruiter_ids   = [f"REC-{rng.integers(1,100):03d}" for _ in range(N)]
    offer_dates     = hire_dates - pd.to_timedelta(rng.integers(14, 60, N), unit="D")
    offer_amounts   = base_salary * rng.uniform(0.9, 1.1, N)
    accepted_amounts= offer_amounts * rng.uniform(0.95, 1.0, N)
    rec_extra = {}
    for i in range(25):
        rec_extra[f"rec_attr_{i+1}"] = rng.uniform(0, 100, N)

    # ── METADATA (50 cols) ────────────────────────────────────────────────
    created_at  = random_dates("2018-01-01", "2024-06-01", N)
    updated_at  = created_at + pd.to_timedelta(rng.integers(0, 365, N), unit="D")
    hris_source = rng.choice(["workday","bamboohr","adp","sap","manual"], N)
    meta_extra  = {}
    for i in range(47):
        meta_extra[f"meta_hr_{i+1}"] = rng.choice(["Y","N"], N)

    # ── ASSEMBLE ──────────────────────────────────────────────────────────
    df = pd.DataFrame({
        "employee_id":        emp_ids_arr,
        "full_name":          full_names,
        "first_name":         first_names,
        "last_name":          last_names,
        "email":              emails_raw,
        "phone":              phones_arr,
        "hire_date":          hire_dates,
        "termination_date":   termination_dates,
        "employment_status":  employment_status,
        "department":         departments,
        "team":               teams,
        "manager_id":         manager_ids,
        "location":           locations,
        "country":            countries,
        **emp_extra,
        # compensation
        "base_salary":        base_salary,
        "bonus_target":       bonus_target,
        "equity_grant":       equity_grant,
        "total_comp":         total_comp,
        "salary_band_min":    salary_band_min,
        "salary_band_max":    salary_band_max,
        "pay_grade":          pay_grades,
        **comp_extra,
        # performance
        **perf_cols,
        "promotion_count":       promotion_count,
        "last_promotion_date":   last_promotion_date,
        "pip_flag":              pip_flag,
        **perf_extra,
        # benefits & time
        "pto_days_used":          pto_days_used,
        "pto_days_remaining":     pto_days_remaining,
        "sick_days":              sick_days,
        "k401_contribution_pct":  k401_contribution_pct,
        "health_plan":            health_plan,
        "dental_plan":            dental_plan,
        **benefits_extra,
        # learning & dev
        "training_hours_ytd":  training_hours_ytd,
        "certifications":      certifications,
        "courses_completed":   courses_completed,
        **ld_extra,
        # recruiting
        "source_channel":      source_channels,
        "recruiter_id":        recruiter_ids,
        "offer_date":          offer_dates,
        "offer_amount":        offer_amounts,
        "accepted_amount":     accepted_amounts,
        **rec_extra,
        # metadata
        "created_at":          created_at,
        "updated_at":          updated_at,
        "hris_source":         hris_source,
        **meta_extra,
    })

    assert df.shape == (N, 400), f"Expected 400 cols, got {df.shape[1]}"
    return df


# ---------------------------------------------------------------------------
# CLEANING
# ---------------------------------------------------------------------------
def clean_raw(df):
    print("  [DS3] Cleaning raw data...")
    cleaned = df.copy()
    rows_deleted = 0
    rows_modified = 0
    log = []

    # PK: Remove duplicate employee_ids (keep first)
    dup_mask = cleaned.duplicated(subset=["employee_id"], keep="first")
    n_dup = dup_mask.sum()
    cleaned = cleaned[~dup_mask].reset_index(drop=True)
    rows_deleted += n_dup
    log.append(f"Removed {n_dup} duplicate employee_id rows")

    # TEMPORAL: Delete rows where hire_date > termination_date
    has_term = cleaned["termination_date"].notna()
    impossible_seq = has_term & (cleaned["hire_date"] > cleaned["termination_date"])
    n_imp = impossible_seq.sum()
    cleaned = cleaned[~impossible_seq].reset_index(drop=True)
    rows_deleted += n_imp
    log.append(f"Removed {n_imp} rows where hire_date > termination_date")

    # TEMPORAL: Flag future hire_dates
    now = pd.Timestamp.now()
    future_hire = pd.to_datetime(cleaned["hire_date"]) > now
    cleaned["hire_date_flag"] = np.where(future_hire, "FUTURE_DATE_ERROR", "")
    log.append(f"Flagged {future_hire.sum()} future hire_dates")

    # MONETARY: Convert negative base_salary to positive, flag
    neg_sal = cleaned["base_salary"] < 0
    cleaned["base_salary_flag"] = np.where(neg_sal, "NEGATIVE_SALARY", "")
    cleaned.loc[neg_sal, "base_salary"] = cleaned.loc[neg_sal, "base_salary"].abs()
    rows_modified += neg_sal.sum()
    log.append(f"Fixed {neg_sal.sum()} negative base_salary values")

    # MONETARY: Flag total_comp < base_salary (recompute where clean bonus available)
    tc_violation = cleaned["total_comp"] < cleaned["base_salary"]
    cleaned.loc[tc_violation, "total_comp"] = (
        cleaned.loc[tc_violation, "base_salary"] +
        cleaned.loc[tc_violation, "bonus_target"].fillna(0) +
        cleaned.loc[tc_violation, "equity_grant"].fillna(0) / 4.0
    )
    rows_modified += tc_violation.sum()
    log.append(f"Recomputed total_comp for {tc_violation.sum()} rows where total_comp < base_salary")

    # NUMERIC: Nulls in bonus_target (15% — leave as NULL, MONETARY rule)
    log.append(f"Left {cleaned['bonus_target'].isnull().sum()} null bonus_target as NULL (contractors)")

    # NUMERIC: Nulls in equity_grant (8% → MEDIAN)
    eq_median = cleaned["equity_grant"].median()
    cleaned["equity_grant"] = cleaned["equity_grant"].fillna(eq_median)
    log.append(f"Imputed equity_grant nulls with median={eq_median:.0f}")

    # PII: Trim whitespace full_name
    name_valid = cleaned["full_name"].notna()
    cleaned.loc[name_valid, "full_name"] = cleaned.loc[name_valid, "full_name"].str.strip()
    rows_modified += name_valid.sum()

    # PII: Fix malformed emails
    def is_valid_email(e):
        return bool(re.match(r'^[^@]+@[^@]+\.[^@]+$', str(e))) if pd.notna(e) else False
    email_valid = cleaned["email"].apply(is_valid_email)
    cleaned.loc[~email_valid, "email"] = np.nan
    cleaned.loc[cleaned["email"].notna(), "email"] = cleaned.loc[cleaned["email"].notna(), "email"].str.lower()
    rows_modified += (~email_valid).sum()
    log.append(f"Nullified {(~email_valid).sum()} malformed emails")

    # TEXT: Standardize department
    dept_map = {
        "Eng": "ENGINEERING", "Engineering": "ENGINEERING", "ENGINEERING": "ENGINEERING",
        "R&D": "ENGINEERING", "Product": "PRODUCT", "Sales": "SALES",
        "Marketing": "MARKETING", "HR": "HR", "Finance": "FINANCE",
        "Legal": "LEGAL", "Operations": "OPERATIONS", "Customer Success": "CUSTOMER_SUCCESS"
    }
    cleaned["department"] = cleaned["department"].map(lambda x: dept_map.get(str(x), str(x).upper()))

    # TEXT: Standardize employment_status
    status_map = {
        "active":"ACTIVE","ACTIVE":"ACTIVE","Active":"ACTIVE",
        "terminated":"TERMINATED","Terminated":"TERMINATED"
    }
    cleaned["employment_status"] = cleaned["employment_status"].map(
        lambda x: status_map.get(str(x), str(x).upper()))

    # NUMERIC: Fix perf_rating outliers (cap to [1, 5])
    for yr in range(2019, 2025):
        col = f"perf_rating_{yr}"
        if col in cleaned.columns:
            oob = (cleaned[col] < 1) | (cleaned[col] > 5)
            cleaned.loc[oob, col] = cleaned.loc[~oob, col].median()
            rows_modified += oob.sum()
    log.append("Capped out-of-range perf_rating values to valid median")

    # NUMERIC: Fix pto_days_used logic (cap at total)
    pto_total = cleaned["pto_days_used"] + cleaned["pto_days_remaining"]
    pto_viol  = cleaned["pto_days_used"] > pto_total
    cleaned.loc[pto_viol, "pto_days_used"] = pto_total[pto_viol] * 0.9
    rows_modified += pto_viol.sum()
    log.append(f"Fixed {pto_viol.sum()} pto_days_used logic violations")

    # FK: Flag orphaned manager_ids
    valid_ids = set(cleaned["employee_id"].values)
    orphan_mgr = cleaned["manager_id"].apply(lambda x: x not in valid_ids if pd.notna(x) else False)
    cleaned["manager_id_flag"] = np.where(orphan_mgr, "ORPHANED_FK", "")
    log.append(f"Flagged {orphan_mgr.sum()} orphaned manager_id references")

    # NUMERIC: Fix base_salary > salary_band_max (flag, leave value)
    band_viol = cleaned["base_salary"] > cleaned["salary_band_max"]
    cleaned["salary_band_flag"] = np.where(band_viol, "ABOVE_BAND_MAX", "")
    log.append(f"Flagged {band_viol.sum()} base_salary > salary_band_max")

    print(f"  [DS3] Done. Deleted {rows_deleted} rows, modified {rows_modified} cells.")
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
        return round(max(0, 100 - nulls/total*100 - 4), 1)
    def grade(s):
        return "A" if s>=90 else "B" if s>=80 else "C" if s>=70 else "D" if s>=60 else "F"
    bs = score(raw_df); as_ = score(cleaned_df)

    return {
        "profile_metadata": {
            "table_name": "HR_WORKFORCE",
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
            for c in ["employee_id","full_name","email","hire_date","termination_date",
                      "base_salary","bonus_target","department","employment_status","manager_id"]
        ],
        "issues_summary": {
            "critical": [
                {"issue": "impossible_temporal", "column": "hire_date > termination_date",
                 "count": int((raw_df["termination_date"].notna() & (raw_df["hire_date"] > raw_df["termination_date"])).sum()), "severity": "CRITICAL"},
                {"issue": "duplicate_pk", "column": "employee_id",
                 "count": int(raw_df.duplicated(subset=["employee_id"]).sum()), "severity": "CRITICAL"},
                {"issue": "negative_monetary", "column": "base_salary",
                 "count": int((raw_df["base_salary"] < 0).sum()), "severity": "CRITICAL"},
                {"issue": "comp_logic_violation", "column": "total_comp < base_salary",
                 "count": int((raw_df["total_comp"] < raw_df["base_salary"]).sum()), "severity": "CRITICAL"},
                {"issue": "orphaned_fk", "column": "manager_id",
                 "count": int(N * 0.02), "severity": "CRITICAL"},
            ],
            "warning": [
                {"issue": "future_hire_date", "column": "hire_date", "count": 800, "severity": "WARNING"},
                {"issue": "perf_rating_oob", "column": "perf_rating_*", "severity": "WARNING"},
                {"issue": "band_violation", "column": "base_salary > salary_band_max", "count": 400, "severity": "WARNING"},
                {"issue": "inconsistent_dept", "column": "department", "severity": "WARNING"},
                {"issue": "malformed_email", "column": "email", "count": int(N*0.06), "severity": "WARNING"},
            ],
            "info": [
                {"issue": "null_bonus_target", "column": "bonus_target", "null_pct": 15.0, "note": "Contractors not eligible"},
                {"issue": "null_equity_grant", "column": "equity_grant", "null_pct": 8.0},
            ]
        },
        "cleaning_recommendations": [
            {"action": "DELETE_DUPLICATES", "column": "employee_id"},
            {"action": "DELETE_ROWS", "column": "hire_date > termination_date"},
            {"action": "CONVERT_TO_POSITIVE", "column": "base_salary"},
            {"action": "RECOMPUTE", "column": "total_comp"},
            {"action": "IMPUTE_MEDIAN", "column": "equity_grant"},
            {"action": "TRIM_WHITESPACE", "column": "full_name"},
            {"action": "NULLIFY_MALFORMED", "column": "email"},
            {"action": "STANDARDIZE", "column": "department"},
            {"action": "STANDARDIZE", "column": "employment_status"},
            {"action": "CAP_RANGE", "column": "perf_rating_*"},
            {"action": "FLAG_ORPHAN", "column": "manager_id"},
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
    print("[Dataset 3] HR_WORKFORCE — 800K rows × 400 cols")
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

    print(f"  ✓ Dataset 3: raw={raw_df.shape[0]} rows × {raw_df.shape[1]} cols ({raw_size:.1f}MB)"
          f" | cleaned={cleaned_df.shape[0]} rows × {cleaned_df.shape[1]} cols ({clean_size:.1f}MB)")
    return raw_df.shape, cleaned_df.shape


if __name__ == "__main__":
    run()
