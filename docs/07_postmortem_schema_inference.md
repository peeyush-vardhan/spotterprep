# Bug Postmortem — Schema Inference False-Positive (`_at` Substring Match)

**Severity:** Critical — 8 of 10 tables loaded with 0 rows
**Time to detect:** ~4 hours (multiple failed load attempts)
**Time to fix:** 15 minutes once root cause identified
**Lines of code changed:** 2

---

## Summary

A substring check `"_at" in column_name` in the schema inference logic incorrectly typed
400+ numeric/string columns as `TIMESTAMP_NTZ` in Snowflake. Because every row in every
affected dataset had at least one of these mislabeled columns, Snowflake's COPY INTO
rejected 100% of rows with:

```
Timestamp '40.8090759437365' is not recognized — column CUSTOMER_ATTR_1
```

Result: 8 tables loaded with 0 rows despite successful file uploads to the Snowflake stage.

---

## Timeline

| Time | Event |
|------|-------|
| Session start | Launched loads for DS1, DS3, DS4, DS5 |
| ~30 min in | DS1 completes: 0 rows. Error: `CUSTOMER_ATTR_1` typed as TIMESTAMP_NTZ |
| ~2 hrs in | DS3 completes: 0 rows. Same error on `EMP_ATTR_1` |
| ~3 hrs in | DS4 RAW hits 3,600s warehouse timeout (separate issue) |
| ~3.5 hrs in | Root cause identified: `_at` substring in `pandas_dtype_to_sf()` |
| ~3.6 hrs in | Fix applied to `pandas_dtype_to_sf()` — BUT second bug location missed |
| ~4 hrs in | Dry-run DDL generation reveals `CUSTOMER_ATTR_1` still typed as TIMESTAMP_NTZ |
| ~4.1 hrs in | Second bug location found in `infer_schema()` — same substring check |
| ~4.2 hrs in | Both locations fixed. All 4 datasets re-run and load successfully |

---

## Root Cause

Two functions in `load_to_snowflake.py` both used `"_at" in column_name.lower()`:

### Bug Location 1 — `infer_schema()` (line ~182)

```python
# BEFORE (buggy)
for col in df.columns:
    if any(kw in col.lower() for kw in ["_date", "_at", "timestamp", "_time"]):
        df[col] = pd.to_datetime(df[col], errors="coerce", format="mixed")
```

This converted columns like `customer_attr_1` to `datetime64[ns]` dtype in pandas
(all values become `NaT` since floats can't be parsed as dates). The dtype change
happened **before** type-mapping, so the next function saw `datetime64[ns]` and
returned `TIMESTAMP_NTZ`.

### Bug Location 2 — `pandas_dtype_to_sf()` (line ~118)

```python
# BEFORE (buggy)
if dtype == "datetime64[ns]" or "_at" in col_lower:
    return "TIMESTAMP_NTZ"
```

The `"_at" in col_lower` check matched `customer_attr_1` (contains `_att` → `_at`
is a substring), `emp_attr_1`, `txn_attr_*`, `price_attr_*`, `inv_attr_*`, etc.

### Affected Columns per Dataset

| Dataset | Column Pattern | Count Affected |
|---------|---------------|---------------|
| DS1 CUSTOMER_ORDERS | `customer_attr_1..10` | 10 |
| DS3 HR_WORKFORCE | `emp_attr_1..N` | ~50 |
| DS4 FINANCIAL_LEDGER | `txn_attr_*`, `recon_attr_*` | ~80 |
| DS5 PRODUCT_CATALOG | `id_attr_*`, `price_attr_*`, `phys_attr_*`, `class_attr_*`, `inv_attr_*`, `content_attr_*`, `compliance_attr_*` | 300+ |

---

## Fix

Replaced the substring check with a **word-boundary regex** applied at module level,
used consistently in both functions:

```python
# Module-level (applied in both infer_schema and pandas_dtype_to_sf)
import re as _re
_TEMPORAL_COL = _re.compile(
    r'(?:^|_)(?:date|timestamp|time)(?:_|$)|_at$'
)
```

**What this matches (true temporal columns):**
- `created_at` — ends with `_at` ✅
- `updated_at` — ends with `_at` ✅
- `order_date` — contains `date` as a word segment ✅
- `timestamp_utc` — starts with `timestamp` ✅
- `hire_date`, `go_live_date` — `date` at end ✅

**What this no longer matches (false positives):**
- `customer_attr_1` — `_at` not at end ❌
- `emp_attr_5` — `_at` not at end ❌
- `price_attr_10` — `_at` not at end ❌
- `compliance_attr_33` — `_at` not at end ❌

---

## Secondary Issue — Warehouse Timeout

The SE_DEMO_WH warehouse has a 3,600-second (1-hour) statement timeout.
Setting `ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 0` does NOT mean
"unlimited" in Snowflake — it means "no session-level override, fall through
to warehouse default."

With `ON_ERROR = CONTINUE` and every row failing the type check, Snowflake
logged individual failures for 1M rows at ~285 rows/second = ~58 minutes,
hitting the 3,600s warehouse cap before finishing.

**Fix:** `ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 86400` (24 hours)
sets an explicit session-level timeout that overrides the warehouse default.

---

## Impact After Fix

| Metric | Before | After |
|--------|--------|-------|
| Tables with 0 rows | 8/10 | 0/10 |
| Total rows loaded | ~499,244 (DS2 only) | 8,645,719 |
| Warehouse timeouts | 4 | 0 |
| Wasted compute time | ~10 hours | 0 |

---

## Lessons Learned

1. **Substring checks on column names are fragile.** Always use word-boundary regex when pattern-matching identifiers.
2. **Test schema inference with a dry-run before loading.** The `--dry-run` flag would have caught this in seconds.
3. **`ALTER SESSION SET ... = 0` ≠ unlimited in Snowflake.** Always set an explicit large value when overriding warehouse timeouts.
4. **Two bug locations, one logical bug.** When fixing a pattern, grep the entire codebase for the same pattern before declaring it fixed.
