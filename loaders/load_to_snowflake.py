"""
load_to_snowflake.py — SpotterPrep Snowflake Loader
=====================================================
Loads all 5 raw and cleaned CSVs into a Snowflake instance.

Creates:
  Database : SPOTTERPREP_TEST
  Schemas  : RAW, CLEANED
  Tables   : one per dataset per schema (10 total)

Strategy for large files (up to 9 GB):
  1. Read first 10K rows to infer column types
  2. CREATE TABLE with inferred DDL (TEXT fallback for ambiguous cols)
  3. PUT file to a named internal stage (Snowflake auto-compresses)
  4. COPY INTO table from stage (parallel, server-side parse)

Credentials: set these environment variables before running —
  SNOWFLAKE_ACCOUNT     e.g. xy12345.us-east-1
  SNOWFLAKE_USER        your login username
  SNOWFLAKE_PASSWORD    your password  (or use key-pair — see KEY_PAIR mode below)
  SNOWFLAKE_ROLE        e.g. SYSADMIN  (optional, defaults to your default role)
  SNOWFLAKE_WAREHOUSE   e.g. COMPUTE_WH

  Alternatively, copy .env.example → .env and fill it in; the script will
  load it automatically if python-dotenv is installed.

Usage:
  python3 loaders/load_to_snowflake.py               # load all 10 tables
  python3 loaders/load_to_snowflake.py --dry-run      # print DDL only, no Snowflake calls
  python3 loaders/load_to_snowflake.py --dataset 1    # load only dataset 1 (both schemas)
  python3 loaders/load_to_snowflake.py --schema raw   # load only RAW schema tables
"""

import os
import sys
import argparse
import time
import textwrap
from pathlib import Path
from datetime import datetime

import re as _re
import pandas as pd
import numpy as np

# Regex for column names that are genuinely temporal.
# Matches: ends with _at (created_at, updated_at), OR contains "date"/"timestamp"/"time"
# as a standalone word segment (order_date, timestamp_utc, hire_date).
# Does NOT match: customer_attr_1, price_attr_2, emp_attr_3 (no word-boundary _at at end).
_TEMPORAL_COL = _re.compile(
    r'(?:^|_)(?:date|timestamp|time)(?:_|$)|_at$'
)

# ── Optional: load .env file if present ───────────────────────────────────
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded credentials from {env_path}")
except ImportError:
    pass  # python-dotenv not installed — rely on env vars directly

import snowflake.connector
from snowflake.connector import DictCursor

# ── Paths ─────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR     = PROJECT_ROOT / "data"
RAW_DIR      = DATA_DIR / "raw"
CLEANED_DIR  = DATA_DIR / "cleaned"

# ── Dataset registry ──────────────────────────────────────────────────────
DATASETS = [
    {
        "id":          1,
        "name":        "CUSTOMER_ORDERS",
        "raw_file":    RAW_DIR     / "dataset1_customer_orders.csv",
        "clean_file":  CLEANED_DIR / "dataset1_customer_orders_cleaned.csv",
        "expected_raw_rows":     100_000,
        "expected_clean_rows":    99_655,
    },
    {
        "id":          2,
        "name":        "IOT_TELEMETRY",
        "raw_file":    RAW_DIR     / "dataset2_iot_telemetry.csv",
        "clean_file":  CLEANED_DIR / "dataset2_iot_telemetry_cleaned.csv",
        "expected_raw_rows":    500_000,
        "expected_clean_rows":  499_244,
    },
    {
        "id":          3,
        "name":        "HR_WORKFORCE",
        "raw_file":    RAW_DIR     / "dataset3_hr_workforce.csv",
        "clean_file":  CLEANED_DIR / "dataset3_hr_workforce_cleaned.csv",
        "expected_raw_rows":    800_000,
        "expected_clean_rows":  790_809,
    },
    {
        "id":          4,
        "name":        "FINANCIAL_LEDGER",
        "raw_file":    RAW_DIR     / "dataset4_financial_ledger.csv",
        "clean_file":  CLEANED_DIR / "dataset4_financial_ledger_cleaned.csv",
        "expected_raw_rows":  1_000_000,
        "expected_clean_rows":  997_000,
    },
    {
        "id":          5,
        "name":        "PRODUCT_CATALOG",
        "raw_file":    RAW_DIR     / "dataset5_product_catalog.csv",
        "clean_file":  CLEANED_DIR / "dataset5_product_catalog_cleaned.csv",
        "expected_raw_rows":  2_000_000,
        "expected_clean_rows": 1_959_606,
    },
]

# ── Snowflake type mapping ─────────────────────────────────────────────────
def pandas_dtype_to_sf(col_name: str, dtype, sample_series: pd.Series) -> str:
    """
    Map a pandas dtype + sample values to a Snowflake column type.
    Conservative: TEXT for anything ambiguous (Snowflake stores efficiently).
    """
    col_lower = col_name.lower()

    # Datetime columns — use _TEMPORAL_COL (module-level regex) to avoid false
    # matches like "customer_attr_1" (contains "_at" as substring).
    # Valid temporal patterns: ends with _at, or "date"/"timestamp"/"time" as
    # a standalone word segment (order_date, timestamp_utc, hire_date).
    if dtype == "datetime64[ns]" or _TEMPORAL_COL.search(col_lower):
        return "TIMESTAMP_NTZ"

    # Float columns
    if dtype in ("float64", "float32"):
        # Check if actually integer-valued (e.g. flag columns stored as float due to NaN)
        non_null = sample_series.dropna()
        if len(non_null) > 0 and non_null.apply(float.is_integer).all():
            return "NUMBER(18,0)"
        return "FLOAT"

    # Integer columns
    if dtype in ("int64", "int32", "int16", "int8"):
        return "NUMBER(18,0)"

    # Boolean
    if dtype == "bool":
        return "BOOLEAN"

    # Object / string — inspect contents
    if dtype == "object":
        non_null = sample_series.dropna().astype(str)
        if len(non_null) == 0:
            return "TEXT"
        max_len = non_null.str.len().max()

        # Detect numeric-looking object columns (e.g. fx_rate stored as object due to NaN)
        try:
            pd.to_numeric(non_null)
            if non_null.str.contains(r'\.').any():
                return "FLOAT"
            return "NUMBER(18,0)"
        except (ValueError, TypeError):
            pass

        # Size-appropriate VARCHAR
        if max_len <= 50:
            return f"VARCHAR(256)"
        elif max_len <= 500:
            return f"VARCHAR(2048)"
        else:
            return "TEXT"

    return "TEXT"


def infer_schema(csv_path: Path, sample_rows: int = 10_000) -> list[tuple[str, str]]:
    """
    Read the first sample_rows of a CSV and return a list of
    (column_name, snowflake_type) tuples.
    """
    print(f"    Inferring schema from first {sample_rows:,} rows of {csv_path.name} ...")
    df = pd.read_csv(csv_path, nrows=sample_rows, low_memory=False)

    # Try parsing likely datetime columns.
    # Use the same word-boundary regex as pandas_dtype_to_sf to avoid false-matching
    # _attr_ columns (customer_attr_1, emp_attr_1, price_attr_2, etc.)
    for col in df.columns:
        if _TEMPORAL_COL.search(col.lower()):
            try:
                df[col] = pd.to_datetime(df[col], errors="coerce", format="mixed")
            except Exception:
                pass

    schema = []
    for col in df.columns:
        sf_type = pandas_dtype_to_sf(col, str(df[col].dtype), df[col])
        # Sanitize column name for Snowflake (already safe, but guard against spaces)
        safe_col = col.strip().replace(" ", "_").replace("-", "_").upper()
        schema.append((safe_col, sf_type))

    return schema


def build_create_table_ddl(table_fqn: str, schema: list[tuple[str, str]]) -> str:
    """Generate a CREATE OR REPLACE TABLE statement."""
    col_defs = ",\n    ".join(f'"{col}" {sf_type}' for col, sf_type in schema)
    return f"CREATE OR REPLACE TABLE {table_fqn} (\n    {col_defs}\n);"


def build_copy_into_sql(table_fqn: str, stage_name: str, file_name: str) -> str:
    """Generate a COPY INTO statement from an internal stage."""
    return textwrap.dedent(f"""
        COPY INTO {table_fqn}
        FROM @{stage_name}/{file_name}
        FILE_FORMAT = (
            TYPE = 'CSV'
            FIELD_OPTIONALLY_ENCLOSED_BY = '"'
            SKIP_HEADER = 1
            NULL_IF = ('', 'NULL', 'None', 'nan', 'NaN', 'NaT')
            EMPTY_FIELD_AS_NULL = TRUE
            DATE_FORMAT = 'AUTO'
            TIMESTAMP_FORMAT = 'AUTO'
            ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE
        )
        ON_ERROR = 'CONTINUE'
        PURGE = TRUE;
    """).strip()


# ── Connection ────────────────────────────────────────────────────────────
def get_connection_params() -> dict:
    required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD", "SNOWFLAKE_WAREHOUSE"]
    missing  = [v for v in required if not os.getenv(v)]
    if missing:
        print("\nERROR: Missing required environment variables:")
        for v in missing:
            print(f"  {v}")
        print("\nSet them in your shell:")
        print('  export SNOWFLAKE_ACCOUNT="xy12345.us-east-1"')
        print('  export SNOWFLAKE_USER="myuser"')
        print('  export SNOWFLAKE_PASSWORD="mypassword"')
        print('  export SNOWFLAKE_WAREHOUSE="COMPUTE_WH"')
        print('  export SNOWFLAKE_ROLE="SYSADMIN"  # optional')
        print("\nOr copy .env.example → .env and fill it in.")
        sys.exit(1)

    params = {
        "account":   os.environ["SNOWFLAKE_ACCOUNT"],
        "user":      os.environ["SNOWFLAKE_USER"],
        "password":  os.environ["SNOWFLAKE_PASSWORD"],
        "warehouse": os.environ["SNOWFLAKE_WAREHOUSE"],
        "database":  "SPOTTERPREP_TEST",
        "login_timeout": 60,
        "network_timeout": None,   # None = no timeout; 0 means non-blocking (wrong)
    }
    if os.getenv("SNOWFLAKE_ROLE"):
        params["role"] = os.environ["SNOWFLAKE_ROLE"]

    return params


def connect_snowflake(params: dict):
    print(f"  Connecting to Snowflake account: {params['account']} as {params['user']} ...")
    # Connect without specifying database first (it may not exist yet)
    init_params = {k: v for k, v in params.items() if k != "database"}
    conn = snowflake.connector.connect(**init_params)
    print("  Connected ✓")
    return conn


# ── Setup: database, schemas, stage ───────────────────────────────────────
STAGE_NAME = "SPOTTERPREP_LOAD_STAGE"

def setup_environment(conn, warehouse: str, dry_run: bool = False):
    """Create database, schemas, and named internal stage."""
    # Warehouse is already set in connection params; USE WAREHOUSE can fail if
    # the role lacks OPERATE privilege, so we skip it and rely on the connection setting.
    # ALTER SESSION has no warehouse dependency so it runs first.
    priority = [
        # 0 means "no session timeout → fall through to warehouse timeout" in Snowflake.
        # The SE_DEMO_WH has a warehouse-level limit of 3,600 s (1 hour).
        # Setting an explicit large value here overrides the warehouse limit.
        # 86400 = 24 hours, sufficient for the 9 GB DS5 load.
        "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 86400;",
    ]
    idempotent = [
        "CREATE DATABASE IF NOT EXISTS SPOTTERPREP_TEST;",
        "USE DATABASE SPOTTERPREP_TEST;",
        "CREATE SCHEMA IF NOT EXISTS SPOTTERPREP_TEST.RAW;",
        "CREATE SCHEMA IF NOT EXISTS SPOTTERPREP_TEST.CLEANED;",
        f"CREATE STAGE IF NOT EXISTS SPOTTERPREP_TEST.PUBLIC.{STAGE_NAME} "
        f"  COMMENT = 'Internal stage for SpotterPrep CSV uploads';",
    ]

    for sql in priority:
        print(f"  SQL: {sql.strip()}")
        if not dry_run:
            conn.cursor().execute(sql)

    for sql in idempotent:
        print(f"  SQL: {sql.strip()}")
        if not dry_run:
            try:
                conn.cursor().execute(sql)
            except Exception as e:
                # IF NOT EXISTS statements — safe to continue if object already exists
                print(f"  (skipped — {e})")

    print("  Database SPOTTERPREP_TEST, schemas RAW + CLEANED, stage ready ✓")


# ── Per-table load ────────────────────────────────────────────────────────
def load_table(
    conn,
    csv_path: Path,
    table_fqn: str,
    dry_run: bool = False,
    verbose: bool = True,
) -> dict:
    """
    Full load pipeline for one CSV → one Snowflake table.
    Returns a result dict with timing and row counts.
    """
    result = {
        "table":       table_fqn,
        "file":        csv_path.name,
        "file_mb":     csv_path.stat().st_size / (1024**2),
        "status":      "pending",
        "rows_loaded": 0,
        "elapsed_s":   0,
        "error":       None,
    }

    t0 = time.time()

    try:
        # 1. Infer schema
        schema = infer_schema(csv_path)
        if verbose:
            print(f"    Schema: {len(schema)} columns inferred")

        # 2. Build DDL
        ddl = build_create_table_ddl(table_fqn, schema)
        if verbose:
            print(f"    DDL preview (first 3 cols): " +
                  ", ".join(f'{c} {t}' for c,t in schema[:3]) + " ...")

        # 3. Create table
        print(f"    Creating table {table_fqn} ...")
        if not dry_run:
            conn.cursor().execute(f"USE DATABASE SPOTTERPREP_TEST;")
            conn.cursor().execute(ddl)

        # 4. PUT file to internal stage
        # Snowflake auto-gzips during PUT. Large files are chunked automatically.
        stage_fqn  = f"SPOTTERPREP_TEST.PUBLIC.{STAGE_NAME}"
        file_str   = str(csv_path.resolve())
        put_sql    = f"PUT 'file://{file_str}' @{stage_fqn} AUTO_COMPRESS=TRUE OVERWRITE=TRUE PARALLEL=4;"

        print(f"    PUT {csv_path.name} → @{stage_fqn} (this may take a few minutes for large files) ...")
        if not dry_run:
            cur = conn.cursor()
            cur.execute(put_sql)
            put_rows = cur.fetchall()
            if verbose:
                for row in put_rows[:3]:
                    print(f"      {row}")

        # 5. COPY INTO table
        # Snowflake compresses and parallelises the ingest server-side.
        staged_file = csv_path.name + ".gz"
        copy_sql    = build_copy_into_sql(table_fqn, stage_fqn, staged_file)
        print(f"    COPY INTO {table_fqn} ...")
        if verbose:
            print(f"    {copy_sql.splitlines()[0]}")

        if not dry_run:
            # Use async execution so the client never holds a blocking socket
            # waiting for a potentially 20+ minute server-side COPY INTO.
            cur = conn.cursor()
            cur.execute_async(copy_sql)
            qid = cur.sfqid
            print(f"    Query ID: {qid}  (polling for completion ...)")

            try:
                from snowflake.connector.constants import QueryStatus
            except ImportError:
                from snowflake.connector import QueryStatus
            poll_interval = 15   # seconds between status checks
            waited = 0
            while True:
                status = conn.get_query_status_throw_if_error(qid)
                if status == QueryStatus.SUCCESS:
                    break
                time.sleep(poll_interval)
                waited += poll_interval
                print(f"    ... still running ({waited}s elapsed, status={status.name})")

            # Fetch results now that the query has completed
            cur.get_results_from_sfqid(qid)
            copy_result = cur.fetchall()
            if verbose:
                for row in copy_result[:5]:
                    print(f"      {row}")

        # 6. Verify row count
        if not dry_run:
            cur = conn.cursor(DictCursor)
            cur.execute(f"SELECT COUNT(*) AS cnt FROM {table_fqn};")
            result["rows_loaded"] = cur.fetchone()["CNT"]
        else:
            result["rows_loaded"] = -1  # dry-run placeholder

        result["status"]    = "ok"
        result["elapsed_s"] = round(time.time() - t0, 1)
        print(f"    ✓ {table_fqn}: {result['rows_loaded']:,} rows loaded in {result['elapsed_s']}s")

    except Exception as e:
        result["status"]    = "error"
        result["error"]     = str(e)
        result["elapsed_s"] = round(time.time() - t0, 1)
        print(f"    ✗ {table_fqn}: ERROR — {e}")

    return result


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Load SpotterPrep synthetic datasets into Snowflake"
    )
    parser.add_argument("--dry-run",  action="store_true",
                        help="Print DDL and SQL without executing any Snowflake calls")
    parser.add_argument("--dataset",  type=int, choices=[1,2,3,4,5],
                        help="Load only this dataset number (both raw and cleaned)")
    parser.add_argument("--schema",   choices=["raw","cleaned"],
                        help="Load only this schema (raw or cleaned)")
    parser.add_argument("--verbose",  action="store_true", default=True,
                        help="Show detailed output per column")
    args = parser.parse_args()

    # ── Filter dataset list ───────────────────────────────────────────────
    datasets_to_load = DATASETS
    if args.dataset:
        datasets_to_load = [d for d in DATASETS if d["id"] == args.dataset]

    # ── Header ────────────────────────────────────────────────────────────
    width = 70
    print("\n" + "=" * width)
    print("  SpotterPrep — Snowflake Loader")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.dry_run:
        print("  MODE: DRY RUN (no Snowflake calls)")
    print("=" * width + "\n")

    # ── Validate files exist ───────────────────────────────────────────────
    print("Validating data files ...")
    missing = []
    for ds in datasets_to_load:
        for key in ("raw_file", "clean_file"):
            if not ds[key].exists():
                missing.append(str(ds[key]))
    if missing:
        print("ERROR: Missing data files (run generate_all.py first):")
        for f in missing:
            print(f"  {f}")
        sys.exit(1)
    print(f"  All {len(datasets_to_load) * 2} CSV files found ✓\n")

    # ── Connect ───────────────────────────────────────────────────────────
    if not args.dry_run:
        params = get_connection_params()
        conn   = connect_snowflake(params)
        setup_environment(conn, params["warehouse"])
    else:
        conn = None
        print("DRY RUN: Skipping Snowflake connection\n")

    # ── Load tables ───────────────────────────────────────────────────────
    results = []

    for ds in datasets_to_load:
        print(f"\n{'─'*60}")
        print(f"Dataset {ds['id']}: {ds['name']}")
        print(f"{'─'*60}")

        load_pairs = []
        if not args.schema or args.schema == "raw":
            load_pairs.append((
                ds["raw_file"],
                f"SPOTTERPREP_TEST.RAW.{ds['name']}_RAW",
                ds["expected_raw_rows"],
            ))
        if not args.schema or args.schema == "cleaned":
            load_pairs.append((
                ds["clean_file"],
                f"SPOTTERPREP_TEST.CLEANED.{ds['name']}_CLEANED",
                ds["expected_clean_rows"],
            ))

        for csv_path, table_fqn, expected_rows in load_pairs:
            mb = csv_path.stat().st_size / (1024**2)
            print(f"\n  Loading: {csv_path.name} ({mb:.0f} MB)")
            print(f"  Target:  {table_fqn}")
            res = load_table(conn, csv_path, table_fqn, dry_run=args.dry_run, verbose=args.verbose)
            res["expected_rows"] = expected_rows
            results.append(res)

    # ── Final summary ─────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  LOAD SUMMARY")
    print("=" * 70)
    print(f"{'Table':<55} {'Rows':>10} {'MB':>8} {'Time':>8} {'Status'}")
    print("─" * 90)

    total_rows = 0
    total_mb   = 0
    errors     = []

    for r in results:
        status_icon = "✓" if r["status"] == "ok" else "✗"
        row_str = f"{r['rows_loaded']:,}" if r["rows_loaded"] >= 0 else "dry-run"
        print(f"{r['table']:<55} {row_str:>10} {r['file_mb']:>7.0f}MB {r['elapsed_s']:>6.1f}s  {status_icon}")
        if r["status"] == "ok":
            total_rows += r["rows_loaded"]
            total_mb   += r["file_mb"]
        if r["status"] == "error":
            errors.append(r)

    print("─" * 90)
    print(f"  Total rows loaded:  {total_rows:,}")
    print(f"  Total data size:    {total_mb/1024:.1f} GB")
    print(f"  Tables loaded:      {sum(1 for r in results if r['status']=='ok')}/{len(results)}")

    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for r in errors:
            print(f"    {r['table']}: {r['error']}")
    else:
        print("\n  All tables loaded successfully ✓")

    print(f"\n  Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ── Print useful Snowflake queries ─────────────────────────────────────
    print("\n" + "=" * 70)
    print("  QUICK-START QUERIES (run in Snowflake worksheet)")
    print("=" * 70)
    print("""
USE DATABASE SPOTTERPREP_TEST;

-- Row counts for all tables
SELECT table_schema, table_name, row_count
FROM information_schema.tables
WHERE table_schema IN ('RAW','CLEANED')
ORDER BY table_schema, table_name;

-- Sample raw vs cleaned comparison (Dataset 1)
SELECT * FROM RAW.CUSTOMER_ORDERS_RAW     LIMIT 5;
SELECT * FROM CLEANED.CUSTOMER_ORDERS_CLEANED LIMIT 5;

-- Check order_amount nulls in raw vs cleaned
SELECT
    'RAW'     AS source,
    COUNT(*)  AS total_rows,
    SUM(CASE WHEN order_amount IS NULL THEN 1 ELSE 0 END) AS null_order_amount
FROM RAW.CUSTOMER_ORDERS_RAW
UNION ALL
SELECT
    'CLEANED' AS source,
    COUNT(*)  AS total_rows,
    SUM(CASE WHEN order_amount IS NULL THEN 1 ELSE 0 END) AS null_order_amount
FROM CLEANED.CUSTOMER_ORDERS_CLEANED;

-- Status standardization check (raw should show mixed case, cleaned ACTIVE only)
SELECT status, COUNT(*) AS cnt
FROM RAW.CUSTOMER_ORDERS_RAW
GROUP BY 1 ORDER BY 2 DESC;

SELECT status, COUNT(*) AS cnt
FROM CLEANED.CUSTOMER_ORDERS_CLEANED
GROUP BY 1 ORDER BY 2 DESC;
""")

    if conn:
        conn.close()


if __name__ == "__main__":
    main()
