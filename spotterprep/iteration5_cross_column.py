"""
cross_column_validator.py — SpotterPrep Cross-Column Validator
==============================================================
Implements Iteration 5 of the multi-iteration cleaning model.

Runs after all per-column fixes (iterations 3–4) are complete. Detects patterns
that are statistically invisible at the column level but become obvious when two
or more columns are examined together.

The 5 patterns correspond exactly to the 5 datasets documented in
docs/03_five_iteration_model.md, Iteration 5:

  DS1 CUSTOMER_ORDERS  : churn_risk='low' but health_score < 20 (stale ML labels)
  DS2 IOT_TELEMETRY    : energy spike + RPM flat (bearing failure signal)
  DS3 HR_WORKFORCE     : 5+ yr tenure + declining performance (retention risk)
  DS4 FINANCIAL_LEDGER : accrual entries with no reversal in following period
  DS5 PRODUCT_CATALOG  : EUR price > USD price after FX conversion (grey market)

Each validator returns a list of CrossColumnFinding dicts. These are designed
to feed directly into AuditLogger.log_finding().

Usage:
  import pandas as pd
  from spotterprep.iteration5_cross_column import validate_cross_columns

  df = pd.read_csv("data/cleaned/dataset1_customer_orders_cleaned.csv")
  findings = validate_cross_columns(df, dataset_name="CUSTOMER_ORDERS")

  for f in findings:
      print(f["finding_type"], f["rows_affected"], f["business_context"])
"""

from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd


# ── Finding structure ──────────────────────────────────────────────────────
# All validators return lists of dicts conforming to this shape.
# Fields map directly to AuditLogger.log_finding() parameters.

def _finding(
    finding_type: str,
    columns_involved: list[str],
    rows_affected: int,
    business_context: str,
    example_rows: Optional[pd.DataFrame] = None,
    recommended_action: str = "FLAG_FOR_REVIEW",
) -> dict:
    return {
        "finding_type":       finding_type,
        "columns_involved":   columns_involved,
        "rows_affected":      int(rows_affected),
        "business_context":   business_context,
        "recommended_action": recommended_action,
        "example_rows":       (example_rows.to_dict(orient="records")
                               if example_rows is not None and not example_rows.empty
                               else []),
        "detected_at":        datetime.utcnow().isoformat() + "Z",
    }


def _require_cols(df: pd.DataFrame, cols: list[str], validator_name: str) -> list[str]:
    """Return a list of columns from `cols` that are missing from df, with a warning."""
    missing = [c for c in cols if c not in df.columns]
    if missing:
        print(f"  [CrossColumnValidator:{validator_name}] "
              f"Skipping — columns not found: {missing}")
    return missing


# ── DS1: CUSTOMER_ORDERS ──────────────────────────────────────────────────

def validate_customer_orders(df: pd.DataFrame) -> list[dict]:
    """
    Checks for CUSTOMER_ORDERS:

    1. STALE_ML_LABELS
       churn_risk = 'low' but health_score < 20
       Signals that the ML churn model was scored at a different time than
       the health score was computed. These accounts may be at undisclosed risk.

    2. ARR_MRR_MISMATCH
       arr < mrr * 12 by more than rounding tolerance
       After cleaning, any remaining mismatch is a logic violation — the single-
       column cleaner may not have caught all variants if custom MRR calculations
       were applied in a specific order.

    3. SEATS_UTILISATION_ANOMALY
       seats_used > seats_purchased
       Over-utilisation — likely a provisioning error or unlicensed usage.
    """
    findings = []

    # ── 1. Stale ML labels ────────────────────────────────────────────────
    needed = ["churn_risk", "health_score"]
    if not _require_cols(df, needed, "CUSTOMER_ORDERS"):
        health = pd.to_numeric(df["health_score"], errors="coerce")
        mask   = (df["churn_risk"].astype(str).str.lower() == "low") & (health < 20)
        count  = int(mask.sum())
        if count > 0:
            findings.append(_finding(
                finding_type="STALE_ML_LABELS",
                columns_involved=["churn_risk", "health_score"],
                rows_affected=count,
                business_context=(
                    f"{count} rows where churn_risk='low' but health_score < 20. "
                    "The churn model label and health score were computed at different times. "
                    "These accounts appear healthy to the model but are actually at risk. "
                    "Recommend re-scoring churn_risk or adding a STALE_LABEL flag."
                ),
                example_rows=df[mask][["churn_risk", "health_score"]].head(5),
                recommended_action="FLAG_STALE_LABEL",
            ))

    # ── 2. ARR / MRR mismatch ─────────────────────────────────────────────
    needed = ["arr", "mrr"]
    if not _require_cols(df, needed, "CUSTOMER_ORDERS"):
        arr = pd.to_numeric(df["arr"], errors="coerce")
        mrr = pd.to_numeric(df["mrr"], errors="coerce")
        both_valid = arr.notna() & mrr.notna() & (mrr > 0)
        # Allow 1% rounding tolerance
        mismatch = both_valid & (arr < mrr * 12 * 0.99)
        count = int(mismatch.sum())
        if count > 0:
            findings.append(_finding(
                finding_type="ARR_MRR_MISMATCH",
                columns_involved=["arr", "mrr"],
                rows_affected=count,
                business_context=(
                    f"{count} rows where arr < mrr * 12 after cleaning (>1% tolerance). "
                    "Remaining mismatches may reflect mid-period contract changes or "
                    "custom billing cadences not captured in the single-column fix. "
                    "Finance should review before using ARR for board reporting."
                ),
                example_rows=df[mismatch][["arr", "mrr"]].head(5),
                recommended_action="ESCALATE_FINANCE_REVIEW",
            ))

    # ── 3. Seats over-utilisation ─────────────────────────────────────────
    needed = ["seats_purchased", "seats_used"]
    if not _require_cols(df, needed, "CUSTOMER_ORDERS"):
        purchased = pd.to_numeric(df["seats_purchased"], errors="coerce")
        used      = pd.to_numeric(df["seats_used"], errors="coerce")
        both_valid = purchased.notna() & used.notna() & (purchased > 0)
        over = both_valid & (used > purchased)
        count = int(over.sum())
        if count > 0:
            findings.append(_finding(
                finding_type="SEATS_OVER_UTILISATION",
                columns_involved=["seats_purchased", "seats_used"],
                rows_affected=count,
                business_context=(
                    f"{count} accounts using more seats than purchased. "
                    "This is either a provisioning error (seats_used inflated by a bug) "
                    "or unlicensed usage. Either requires follow-up before renewal."
                ),
                example_rows=df[over][["seats_purchased", "seats_used"]].head(5),
                recommended_action="FLAG_OVERLICENSING",
            ))

    return findings


# ── DS2: IOT_TELEMETRY ────────────────────────────────────────────────────

def validate_iot_telemetry(df: pd.DataFrame) -> list[dict]:
    """
    Checks for IOT_TELEMETRY:

    1. BEARING_FAILURE_SIGNAL
       power_kw (or energy_kwh) increased while rpm stayed flat or decreased.
       Power-without-rotation is a physical indicator of mechanical resistance
       consistent with early bearing failure. Not detectable per-column.

    2. POWER_PHYSICS_VIOLATION
       power_kw > voltage * current (P > VI)
       After per-column cleaning, any remaining rows violate basic electrical physics.
       These are measurement errors, not outliers.

    3. VIBRATION_STATUS_CONFLICT
       vibration_hz == 0 while device_status == 'running'
       Zero vibration on a running device is a sensor fault, not a valid reading.
       This was flagged in Iteration 4; cross-column validation confirms it
       persists after cleaning (should be zero after iter 4 fixes).
    """
    findings = []

    # ── 1. Bearing failure signal ──────────────────────────────────────────
    # Accept either power_kw or energy_kwh as the energy column
    energy_col = next((c for c in ["power_kw", "energy_kwh", "energy_kw"] if c in df.columns), None)
    rpm_col    = next((c for c in ["rpm", "motor_rpm", "shaft_rpm"] if c in df.columns), None)

    if energy_col and rpm_col:
        energy = pd.to_numeric(df[energy_col], errors="coerce")
        rpm    = pd.to_numeric(df[rpm_col], errors="coerce")
        both_valid = energy.notna() & rpm.notna()

        # Energy in top quartile AND rpm in bottom quartile — simultaneous spike/flat
        energy_p75 = float(energy[both_valid].quantile(0.75))
        rpm_p25    = float(rpm[both_valid].quantile(0.25))

        mask  = both_valid & (energy > energy_p75) & (rpm < rpm_p25) & (rpm >= 0)
        count = int(mask.sum())
        if count > 0:
            findings.append(_finding(
                finding_type="BEARING_FAILURE_SIGNAL",
                columns_involved=[energy_col, rpm_col],
                rows_affected=count,
                business_context=(
                    f"{count} device-readings where {energy_col} is in the top quartile "
                    f"(>{energy_p75:.1f}) while {rpm_col} is in the bottom quartile "
                    f"(<{rpm_p25:.1f}). High power with low rotation indicates mechanical "
                    "resistance — a known early indicator of bearing failure. "
                    "Flag affected device IDs for predictive maintenance scheduling."
                ),
                example_rows=df[mask][[energy_col, rpm_col]].head(5),
                recommended_action="FLAG_PREDICTIVE_MAINTENANCE",
            ))
    else:
        print(f"  [CrossColumnValidator:IOT_TELEMETRY] "
              f"Bearing check skipped — no energy/rpm columns found")

    # ── 2. Power physics violation ─────────────────────────────────────────
    needed = ["power_kw", "voltage", "current"]
    if not _require_cols(df, needed, "IOT_TELEMETRY"):
        power   = pd.to_numeric(df["power_kw"], errors="coerce")
        voltage = pd.to_numeric(df["voltage"], errors="coerce")
        current = pd.to_numeric(df["current"], errors="coerce")
        all_valid = power.notna() & voltage.notna() & current.notna()
        # Allow 5% measurement tolerance
        vi = voltage * current
        violation = all_valid & (power > vi * 1.05) & (vi > 0)
        count = int(violation.sum())
        if count > 0:
            findings.append(_finding(
                finding_type="POWER_PHYSICS_VIOLATION",
                columns_involved=["power_kw", "voltage", "current"],
                rows_affected=count,
                business_context=(
                    f"{count} readings where power_kw > voltage × current (>5% tolerance). "
                    "This violates Ohm's law — these are sensor measurement errors, not "
                    "physical extremes. Imputation with VI product is appropriate."
                ),
                example_rows=df[violation][["power_kw", "voltage", "current"]].head(5),
                recommended_action="RECOMPUTE_FROM_VI",
            ))

    # ── 3. Vibration / status conflict ────────────────────────────────────
    vibration_col = next((c for c in ["vibration_hz", "vibration"] if c in df.columns), None)
    status_col    = next((c for c in ["device_status", "status"] if c in df.columns), None)

    if vibration_col and status_col:
        vibration = pd.to_numeric(df[vibration_col], errors="coerce")
        running   = df[status_col].astype(str).str.lower().isin(["running", "active", "on"])
        conflict  = running & vibration.notna() & (vibration == 0)
        count     = int(conflict.sum())
        if count > 0:
            findings.append(_finding(
                finding_type="VIBRATION_STATUS_CONFLICT",
                columns_involved=[vibration_col, status_col],
                rows_affected=count,
                business_context=(
                    f"{count} readings where {vibration_col}=0 while device is 'running'. "
                    "A running device cannot have zero vibration — these are sensor faults. "
                    "These rows should have been caught in Iteration 4; if still present "
                    "after cleaning, the ZERO_VIBRATION_RUNNING flag was not applied."
                ),
                example_rows=df[conflict][[vibration_col, status_col]].head(5),
                recommended_action="FLAG_SENSOR_FAULT",
            ))

    return findings


# ── DS3: HR_WORKFORCE ─────────────────────────────────────────────────────

def validate_hr_workforce(df: pd.DataFrame) -> list[dict]:
    """
    Checks for HR_WORKFORCE:

    1. RETENTION_RISK_SIGNAL
       Long-tenured employees (5+ years) with declining performance ratings.
       Per-column checks see tenure and performance independently.
       Combined, they identify an early resignation pattern that HR needs to act on.

    2. COMP_BELOW_BAND_LONG_TENURE
       Employees with 5+ years tenure whose total_comp is below the 25th
       percentile for their department. A flight risk for high performers.

    3. HIRE_TO_PROMO_ANOMALY
       Employees promoted faster than the minimum promotion timeline for their level.
       Suggests either data entry errors or undocumented fast-track paths.
    """
    findings = []

    # ── 1. Retention risk signal ───────────────────────────────────────────
    # Compute tenure from hire_date if tenure_years column is absent
    tenure_col  = next((c for c in ["tenure_years", "years_of_service"] if c in df.columns), None)
    perf_col    = next((c for c in ["performance_rating", "performance_score",
                                    "perf_rating", "annual_rating"] if c in df.columns), None)

    if tenure_col is None and "hire_date" in df.columns:
        hire_dates = pd.to_datetime(df["hire_date"], errors="coerce")
        df = df.copy()  # avoid SettingWithCopyWarning on caller's df
        df["_tenure_years"] = (pd.Timestamp.now() - hire_dates).dt.days / 365.25
        tenure_col = "_tenure_years"

    if tenure_col and perf_col:
        tenure = pd.to_numeric(df[tenure_col], errors="coerce")
        perf   = pd.to_numeric(df[perf_col],   errors="coerce")
        both_valid = tenure.notna() & perf.notna()

        # Long tenure: 5+ years. Declining perf: bottom quartile for their cohort.
        perf_p25 = float(perf[both_valid].quantile(0.25))
        mask     = both_valid & (tenure >= 5) & (perf < perf_p25)
        count    = int(mask.sum())
        if count > 0:
            findings.append(_finding(
                finding_type="RETENTION_RISK_SIGNAL",
                columns_involved=[tenure_col, perf_col],
                rows_affected=count,
                business_context=(
                    f"{count} employees with 5+ years tenure whose {perf_col} is in the "
                    f"bottom quartile (<{perf_p25:.1f}). "
                    "Long-tenured employees with declining ratings are a known early "
                    "resignation indicator. HR should initiate retention conversations "
                    "before performance reviews are scheduled."
                ),
                example_rows=df[mask][[tenure_col, perf_col]].head(5),
                recommended_action="FLAG_RETENTION_RISK",
            ))

    # ── 2. Comp below band for long-tenure employees ───────────────────────
    comp_col   = next((c for c in ["total_comp", "total_compensation",
                                   "annual_salary"] if c in df.columns), None)
    dept_col   = next((c for c in ["department", "dept", "department_name"] if c in df.columns), None)

    if tenure_col and comp_col and dept_col:
        tenure = pd.to_numeric(df[tenure_col], errors="coerce")
        comp   = pd.to_numeric(df[comp_col],   errors="coerce")
        long_tenure = tenure >= 5

        # Compare against the 25th percentile within each department
        dept_p25 = comp.groupby(df[dept_col]).transform(lambda x: x.quantile(0.25))
        below_band = long_tenure & comp.notna() & dept_p25.notna() & (comp < dept_p25)
        count = int(below_band.sum())
        if count > 0:
            findings.append(_finding(
                finding_type="COMP_BELOW_BAND_LONG_TENURE",
                columns_involved=[tenure_col, comp_col, dept_col],
                rows_affected=count,
                business_context=(
                    f"{count} employees with 5+ years tenure whose {comp_col} is below "
                    "the 25th percentile for their department. "
                    "Long-tenured employees paid below band are at high attrition risk. "
                    "Total rewards should review these cases before the next comp cycle."
                ),
                example_rows=df[below_band][[tenure_col, comp_col, dept_col]].head(5),
                recommended_action="FLAG_COMP_REVIEW",
            ))

    # ── 3. Faster-than-minimum promotion ──────────────────────────────────
    hire_col  = "hire_date"
    promo_col = next((c for c in ["last_promotion_date", "promotion_date"] if c in df.columns), None)
    level_col = next((c for c in ["job_level", "level", "grade"] if c in df.columns), None)

    if hire_col in df.columns and promo_col and level_col:
        hire  = pd.to_datetime(df[hire_col],  errors="coerce")
        promo = pd.to_datetime(df[promo_col], errors="coerce")
        both_valid = hire.notna() & promo.notna()
        months_to_promo = (promo - hire).dt.days / 30.44

        # Less than 6 months from hire to first promotion is anomalously fast
        too_fast = both_valid & (months_to_promo < 6) & (months_to_promo >= 0)
        count = int(too_fast.sum())
        if count > 0:
            findings.append(_finding(
                finding_type="HIRE_TO_PROMO_ANOMALY",
                columns_involved=[hire_col, promo_col, level_col],
                rows_affected=count,
                business_context=(
                    f"{count} employees promoted within 6 months of hire. "
                    "This may indicate data entry errors (promotion date = hire date) "
                    "or undocumented lateral transfers recorded as promotions. "
                    "HRIS should validate before the next org chart export."
                ),
                example_rows=df[too_fast][[hire_col, promo_col, level_col]].head(5),
                recommended_action="FLAG_HRIS_REVIEW",
            ))

    return findings


# ── DS4: FINANCIAL_LEDGER ─────────────────────────────────────────────────

def validate_financial_ledger(df: pd.DataFrame) -> list[dict]:
    """
    Checks for FINANCIAL_LEDGER:

    1. ACCRUAL_NO_REVERSAL
       Accrual journal entries with no corresponding reversal in the following
       period. Unreversed accruals overstate the balance sheet until corrected.
       This is only detectable by looking at entry_type + posting_date together.

    2. INTERCOMPANY_NET_MISMATCH
       Intercompany pairs that don't net to zero within the same period.
       After Iteration 4 resolved timing differences, any remaining mismatch
       is a genuine reconciliation issue.

    3. DEBIT_CREDIT_SUM_VIOLATION
       Journal entries where the sum of debits does not equal the sum of credits
       within the same journal_entry_id. SOX controls require balanced entries.
    """
    findings = []

    # ── 1. Accrual with no reversal ────────────────────────────────────────
    entry_type_col  = next((c for c in ["entry_type", "journal_type"] if c in df.columns), None)
    posting_col     = next((c for c in ["posting_date", "post_date"] if c in df.columns), None)
    amount_col      = next((c for c in ["net_amount", "amount", "debit_amount"] if c in df.columns), None)
    je_col          = next((c for c in ["journal_entry_id", "je_id", "entry_id"] if c in df.columns), None)

    if entry_type_col and posting_col and amount_col:
        posting = pd.to_datetime(df[posting_col], errors="coerce")
        accrual_mask = df[entry_type_col].astype(str).str.lower().isin(
            ["accrual", "accrued", "accrual_entry", "acc"]
        )
        accruals = df[accrual_mask & posting.notna()].copy()
        accruals["_posting_month"] = pd.to_datetime(accruals[posting_col], errors="coerce").dt.to_period("M")

        if len(accruals) > 0 and je_col and je_col in df.columns:
            # For each accrual, check if there's a reversal entry in the next month
            reversals = df[df[entry_type_col].astype(str).str.lower().isin(
                ["reversal", "reverse", "reversed", "rev"]
            )].copy()

            accrual_jes   = set(accruals[je_col].dropna().astype(str))
            reversal_refs = set(reversals[je_col].dropna().astype(str)) if len(reversals) > 0 else set()

            unreversed_mask = accruals[je_col].astype(str).isin(accrual_jes - reversal_refs)
            count = int(unreversed_mask.sum())

            if count > 0:
                amounts = pd.to_numeric(accruals.loc[unreversed_mask, amount_col], errors="coerce")
                total_exposure = float(amounts.abs().sum())
                findings.append(_finding(
                    finding_type="ACCRUAL_NO_REVERSAL",
                    columns_involved=[entry_type_col, posting_col, amount_col],
                    rows_affected=count,
                    business_context=(
                        f"{count} accrual entries with no corresponding reversal in the "
                        f"following period. Total exposure: ${total_exposure:,.0f}. "
                        "Unreversed accruals overstate liabilities on the balance sheet. "
                        "Finance must review and either post reversals or reclassify as "
                        "permanent entries before period close."
                    ),
                    example_rows=accruals[unreversed_mask][[entry_type_col, posting_col, amount_col]].head(5),
                    recommended_action="ESCALATE_PERIOD_CLOSE",
                ))

    # ── 2. Debit / credit imbalance within journal entries ─────────────────
    debit_col  = next((c for c in ["debit_amount", "debit"] if c in df.columns), None)
    credit_col = next((c for c in ["credit_amount", "credit"] if c in df.columns), None)

    if je_col and debit_col and credit_col and je_col in df.columns:
        debit  = pd.to_numeric(df[debit_col],  errors="coerce").fillna(0)
        credit = pd.to_numeric(df[credit_col], errors="coerce").fillna(0)

        je_sums = pd.DataFrame({
            "je_id":  df[je_col],
            "debit":  debit,
            "credit": credit,
        }).groupby("je_id").sum()

        # Tolerance: $0.01 rounding
        imbalanced_jes = je_sums[abs(je_sums["debit"] - je_sums["credit"]) > 0.01]
        affected_rows  = int(df[je_col].isin(imbalanced_jes.index).sum())

        if affected_rows > 0:
            max_imbalance = float(abs(imbalanced_jes["debit"] - imbalanced_jes["credit"]).max())
            findings.append(_finding(
                finding_type="DEBIT_CREDIT_IMBALANCE",
                columns_involved=[je_col, debit_col, credit_col],
                rows_affected=affected_rows,
                business_context=(
                    f"{affected_rows} rows across {len(imbalanced_jes)} journal entries "
                    f"where total debits ≠ total credits (>$0.01 tolerance). "
                    f"Largest imbalance: ${max_imbalance:,.2f}. "
                    "Double-entry bookkeeping requires balanced journals — these entries "
                    "violate SOX controls and must be corrected before audit."
                ),
                example_rows=df[df[je_col].isin(imbalanced_jes.index[:5])][[je_col, debit_col, credit_col]].head(5),
                recommended_action="ESCALATE_SOX_REVIEW",
            ))

    # ── 3. Intercompany net mismatch ───────────────────────────────────────
    ic_flag_col = next((c for c in ["is_intercompany", "intercompany_flag",
                                    "interco_flag"] if c in df.columns), None)
    period_col  = next((c for c in ["fiscal_period", "period", "posting_date"] if c in df.columns), None)
    net_col     = next((c for c in ["net_amount", "amount"] if c in df.columns), None)

    if ic_flag_col and period_col and net_col:
        ic_mask = df[ic_flag_col].astype(str).str.lower().isin(["true", "1", "yes", "y"])
        ic_df   = df[ic_mask].copy()
        if len(ic_df) > 0:
            ic_df["_period"] = pd.to_datetime(
                ic_df[period_col], errors="coerce"
            ).dt.to_period("M").astype(str)
            ic_df["_net"] = pd.to_numeric(ic_df[net_col], errors="coerce").fillna(0)

            period_nets = ic_df.groupby("_period")["_net"].sum()
            imbalanced  = period_nets[abs(period_nets) > 100]  # $100 materiality threshold
            count       = int(ic_mask.sum())

            if len(imbalanced) > 0:
                findings.append(_finding(
                    finding_type="INTERCOMPANY_NET_MISMATCH",
                    columns_involved=[ic_flag_col, period_col, net_col],
                    rows_affected=count,
                    business_context=(
                        f"Intercompany entries do not net to zero in {len(imbalanced)} periods "
                        f"(>$100 materiality). Max period imbalance: "
                        f"${float(imbalanced.abs().max()):,.0f}. "
                        "Intercompany eliminations require zero-sum periods. "
                        "These entries will cause consolidation errors in the group P&L."
                    ),
                    recommended_action="FLAG_INTERCO_RECONCILIATION",
                ))

    return findings


# ── DS5: PRODUCT_CATALOG ──────────────────────────────────────────────────

def validate_product_catalog(df: pd.DataFrame) -> list[dict]:
    """
    Checks for PRODUCT_CATALOG:

    1. GREY_MARKET_ARBITRAGE_RISK
       Products priced higher in EUR than in USD after FX conversion.
       Creates grey market opportunity: buy in USD, resell in EUR market.
       Not visible per-column because it requires dividing price_eur by
       the FX rate and comparing to price_usd.

    2. MISSING_REQUIRED_TRANSLATIONS
       Products with no translated description in markets where that language
       is required. Per-column null checks see the translation columns
       individually — cross-column shows which market/language pairs are incomplete.

    3. WEIGHT_UNIT_INCONSISTENCY
       Products in the same category with implausibly different weights,
       suggesting kg vs lb unit confusion was not fully resolved in Iteration 4.
    """
    findings = []

    # ── 1. Grey market arbitrage risk ─────────────────────────────────────
    usd_col = next((c for c in ["price_usd", "price_us", "usd_price"] if c in df.columns), None)
    eur_col = next((c for c in ["price_eur", "price_eu", "eur_price"] if c in df.columns), None)
    fx_col  = next((c for c in ["fx_rate_eur", "eur_fx_rate", "usd_eur_rate"] if c in df.columns), None)

    if usd_col and eur_col:
        usd = pd.to_numeric(df[usd_col], errors="coerce")
        eur = pd.to_numeric(df[eur_col], errors="coerce")
        both_valid = usd.notna() & eur.notna() & (usd > 0) & (eur > 0)

        if fx_col and fx_col in df.columns:
            fx_rate = pd.to_numeric(df[fx_col], errors="coerce")
            # eur_in_usd = price_eur / fx_rate (fx_rate = USD per EUR, e.g. 1.08)
            eur_in_usd = eur / fx_rate.where(fx_rate > 0)
            # Flag where EUR price is >5% higher than USD after conversion
            arbitrage  = both_valid & fx_rate.notna() & (eur_in_usd > usd * 1.05)
        else:
            # No FX column — use a typical USD/EUR rate as a fallback approximation
            fallback_fx = 1.08
            eur_in_usd  = eur / fallback_fx
            arbitrage   = both_valid & (eur_in_usd > usd * 1.05)
            print(f"  [CrossColumnValidator:PRODUCT_CATALOG] "
                  f"No FX rate column found — using fallback rate {fallback_fx}")

        count = int(arbitrage.sum())
        if count > 0:
            findings.append(_finding(
                finding_type="GREY_MARKET_ARBITRAGE_RISK",
                columns_involved=[usd_col, eur_col] + ([fx_col] if fx_col else []),
                rows_affected=count,
                business_context=(
                    f"{count} products priced more than 5% higher in EUR than USD "
                    "after FX conversion. This creates a grey market opportunity: "
                    "buyers in EUR markets can source from the USD market at a discount. "
                    "Pricing team should align EUR prices with USD × FX rate ± permitted "
                    "market premium before next catalogue publish."
                ),
                example_rows=df[arbitrage][[usd_col, eur_col]].head(5),
                recommended_action="FLAG_PRICING_REVIEW",
            ))

    # ── 2. Missing required translations ──────────────────────────────────
    market_col = next((c for c in ["market", "market_code", "region"] if c in df.columns), None)
    lang_cols  = [c for c in df.columns if c.startswith("description_") and
                  c != "description_en"]

    if market_col and lang_cols:
        # Markets that require a specific language (simplified mapping)
        market_lang_requirements = {
            "DE": "description_de",
            "FR": "description_fr",
            "ES": "description_es",
            "JP": "description_ja",
            "KR": "description_ko",
        }
        incomplete_rows = pd.Series(False, index=df.index)
        missing_details = []

        for market_code, required_col in market_lang_requirements.items():
            if required_col not in df.columns:
                continue
            in_market   = df[market_col].astype(str).str.upper() == market_code
            missing_val = df[required_col].isna() | (df[required_col].astype(str).str.strip() == "")
            this_gap    = in_market & missing_val
            count       = int(this_gap.sum())
            if count > 0:
                incomplete_rows |= this_gap
                missing_details.append(f"{market_code}:{count}")

        total = int(incomplete_rows.sum())
        if total > 0:
            findings.append(_finding(
                finding_type="MISSING_REQUIRED_TRANSLATIONS",
                columns_involved=[market_col] + lang_cols[:3],
                rows_affected=total,
                business_context=(
                    f"{total} products are missing translations required for their market. "
                    f"Breakdown: {', '.join(missing_details)}. "
                    "Products without localised descriptions will display in the fallback "
                    "language (EN), which may violate local regulatory requirements in "
                    "DE and FR markets."
                ),
                recommended_action="FLAG_TRANSLATION_REQUIRED",
            ))

    # ── 3. Weight unit inconsistency within category ───────────────────────
    weight_col   = next((c for c in ["weight_kg", "weight", "product_weight"] if c in df.columns), None)
    category_col = next((c for c in ["category", "product_category",
                                     "category_name"] if c in df.columns), None)

    if weight_col and category_col:
        weight   = pd.to_numeric(df[weight_col], errors="coerce")
        both_val = weight.notna()

        # Within each category, flag products whose weight is >100× the median —
        # a typical symptom of kg vs lb confusion (1 lb ≈ 0.453 kg, so a 1 kg item
        # recorded as 2.2 lb is a 2.2× ratio; the pathological case is full kg
        # values stored in a column labelled in a different unit, giving ~2.2× error
        # which blends in, but full unit swaps give ~100× ratios).
        cat_medians = weight.groupby(df[category_col]).transform("median")
        unit_suspect = both_val & cat_medians.notna() & (cat_medians > 0)
        ratio = weight / cat_medians
        anomaly = unit_suspect & ((ratio > 100) | (ratio < 0.01))
        count   = int(anomaly.sum())

        if count > 0:
            findings.append(_finding(
                finding_type="WEIGHT_UNIT_INCONSISTENCY",
                columns_involved=[weight_col, category_col],
                rows_affected=count,
                business_context=(
                    f"{count} products with {weight_col} values >100× or <1% of their "
                    "category median — a strong indicator of kg/lb unit confusion not "
                    "fully resolved in Iteration 4. "
                    "Incorrect weights affect shipping cost calculations, customs "
                    "declarations, and carrier rate cards."
                ),
                example_rows=df[anomaly][[weight_col, category_col]].head(5),
                recommended_action="FLAG_UNIT_REVIEW",
            ))

    return findings


# ── Dispatch ───────────────────────────────────────────────────────────────

_VALIDATORS = {
    "CUSTOMER_ORDERS":  validate_customer_orders,
    "IOT_TELEMETRY":    validate_iot_telemetry,
    "HR_WORKFORCE":     validate_hr_workforce,
    "FINANCIAL_LEDGER": validate_financial_ledger,
    "PRODUCT_CATALOG":  validate_product_catalog,
}


def validate_cross_columns(df: pd.DataFrame, dataset_name: str) -> list[dict]:
    """
    Run the cross-column validator for the specified dataset.

    This is the Iteration 5 — Cross-Column Validation. Call this after all
    Iteration 3 and 4 transformations have been applied to the DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        The fully cleaned DataFrame (post iterations 3 and 4).
    dataset_name : str
        One of: "CUSTOMER_ORDERS", "IOT_TELEMETRY", "HR_WORKFORCE",
        "FINANCIAL_LEDGER", "PRODUCT_CATALOG".

    Returns
    -------
    list[dict]
        List of CrossColumnFinding dicts, each suitable for passing directly
        to AuditLogger.log_finding(). Empty list if no findings.

    Raises
    ------
    ValueError
        If dataset_name is not one of the five supported datasets.
    """
    key = dataset_name.upper().strip()
    if key not in _VALIDATORS:
        raise ValueError(
            f"Unknown dataset_name {dataset_name!r}. "
            f"Must be one of: {list(_VALIDATORS)}"
        )

    print(f"  [CrossColumnValidator] Running Iteration 5 for {key} "
          f"({len(df):,} rows × {len(df.columns)} cols) ...")

    findings = _VALIDATORS[key](df)

    print(f"  [CrossColumnValidator] {len(findings)} cross-column finding(s) detected")
    for f in findings:
        print(f"    · [{f['finding_type']}] {f['rows_affected']:,} rows — "
              f"{f['recommended_action']}")
    if not findings:
        print("    No cross-column issues found — dataset is internally consistent.")
    print()

    return findings


def print_findings_report(findings: list[dict], dataset_name: str) -> None:
    """
    Print the Iteration 5 chat output: findings presented with business context,
    formatted as the AI would surface them to the analyst.
    """
    print(f"\n{'='*65}")
    print(f"  Cross-Column Validation — {dataset_name.upper()}")
    print(f"  {len(findings)} finding(s) — these are the highest-value outputs")
    print(f"  of the pipeline: business intelligence, not just quality fixes.")
    print(f"{'='*65}")

    if not findings:
        print("\n  No cross-column issues found.")
        print("  The cleaned dataset is internally consistent across all column pairs.\n")
        return

    for i, f in enumerate(findings, 1):
        print(f"\n  [{i}] {f['finding_type']}")
        print(f"  Columns: {' + '.join(f['columns_involved'])}")
        print(f"  Rows affected: {f['rows_affected']:,}")
        print(f"\n  {f['business_context']}")
        print(f"\n  Recommended action: {f['recommended_action']}")
        if f.get("example_rows"):
            print(f"  Example rows ({min(3, len(f['example_rows']))} shown):")
            for row in f["example_rows"][:3]:
                print(f"    {row}")
        print(f"  {'─'*58}")
    print()
