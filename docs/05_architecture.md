# SpotterPrep — Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        LOCAL MACHINE                            │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │   generate_  │    │   Profile &  │    │  load_to_        │  │
│  │   all.py     │───▶│   Clean      │───▶│  snowflake.py    │  │
│  │              │    │   Scripts    │    │                  │  │
│  │  5 datasets  │    │  5 profiles  │    │  Schema infer    │  │
│  │  ~19 GB CSV  │    │  5 cleaned   │    │  PUT + COPY INTO │  │
│  └──────────────┘    └──────────────┘    └────────┬─────────┘  │
│                                                   │            │
└───────────────────────────────────────────────────┼────────────┘
                                                    │ HTTPS
                                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                        SNOWFLAKE                                │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  DATABASE: SPOTTERPREP_TEST                             │   │
│  │                                                         │   │
│  │  SCHEMA: RAW               SCHEMA: CLEANED              │   │
│  │  ├── CUSTOMER_ORDERS_RAW   ├── CUSTOMER_ORDERS_CLEANED  │   │
│  │  ├── IOT_TELEMETRY_RAW     ├── IOT_TELEMETRY_CLEANED    │   │
│  │  ├── HR_WORKFORCE_RAW      ├── HR_WORKFORCE_CLEANED     │   │
│  │  ├── FINANCIAL_LEDGER_RAW  ├── FINANCIAL_LEDGER_CLEANED │   │
│  │  └── PRODUCT_CATALOG_RAW   └── PRODUCT_CATALOG_CLEANED  │   │
│  │                                                         │   │
│  │  STAGE: SPOTTERPREP_LOAD_STAGE (internal, auto-GZIP)    │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow — Step by Step

### Step 1: Data Generation (`generate_all.py`)
- Generates 5 synthetic CSV datasets using `pandas` + `numpy`
- Each dataset targets a specific business domain with realistic dirty data patterns
- Intentional issues introduced: nulls, duplicates, format inconsistencies, out-of-range values, impossible sequences
- Output: 10 CSV files (~19 GB total) in `data/raw/` and `data/cleaned/`

### Step 2: Data Profiling
- Reads first 10,000 rows of each raw CSV
- Computes per-column statistics: null rate, cardinality, min/max, type distribution
- Scores each dataset across 5 quality dimensions
- Output: JSON + Markdown profiles in `data/profiles/`

### Step 3: Data Cleaning
- Applies targeted fixes per dataset:
  - Null imputation (median for numeric, mode for categorical)
  - Deduplication by primary key
  - Format standardization (status vocab, country codes, email formats)
  - Business rule enforcement (ARR = MRR × 12, non-negative amounts)
  - Impossible sequence removal (end_date < start_date)
- Output: Cleaned CSVs in `data/cleaned/`

### Step 4: Schema Inference (`load_to_snowflake.py`)
- Reads first 10,000 rows of each CSV
- Maps pandas dtypes to Snowflake types using word-boundary regex for temporal detection
- Generates `CREATE OR REPLACE TABLE` DDL
- Key type mappings:
  - `datetime64[ns]` or name matches `_TEMPORAL_COL` regex → `TIMESTAMP_NTZ`
  - `float64/32` (integer-valued) → `NUMBER(18,0)`
  - `float64/32` → `FLOAT`
  - `int64/32/16/8` → `NUMBER(18,0)`
  - `object` (short strings ≤50 chars) → `VARCHAR(256)`
  - `object` (medium strings ≤500 chars) → `VARCHAR(2048)`
  - `object` (long strings) → `TEXT`

### Step 5: Snowflake Load (`load_to_snowflake.py`)
```
For each CSV:
  1. CREATE OR REPLACE TABLE with inferred DDL
  2. PUT 'file://...' @stage AUTO_COMPRESS=TRUE PARALLEL=4
     → Snowflake client gzips and uploads in parallel chunks
  3. COPY INTO table FROM @stage/file.csv.gz
     → Server-side parallel parse and load
     → ON_ERROR=CONTINUE (skips malformed rows, logs them)
     → PURGE=TRUE (removes staged file after load)
  4. SELECT COUNT(*) to verify row count
```

---

## Key Design Decisions

### Why Snowflake Internal Stage?
- Files up to 9 GB can't be loaded via the Snowsight UI (250 MB limit)
- Internal stage auto-compresses with GZIP, reducing transfer size by ~50%
- Parallel upload (`PARALLEL=4`) saturates available bandwidth
- Server-side COPY INTO is significantly faster than row-by-row insertion

### Why Async COPY INTO?
- COPY INTO for a 9 GB file takes 15–90 minutes
- Synchronous execution would hold an open socket for the entire duration
- `execute_async()` + polling every 15s avoids connection timeouts

### Why `ON_ERROR=CONTINUE`?
- Allows partial loads to succeed even if some rows have issues
- Failed rows are logged with the exact error and column position
- Makes it possible to diagnose issues without re-running the entire load

### Why `STATEMENT_TIMEOUT_IN_SECONDS = 86400`?
- `= 0` in Snowflake means "no session override → fall through to warehouse default"
- SE_DEMO_WH warehouse default is 3,600s (1 hour)
- DS4 (3.5 GB, 1M rows) took ~58 min when rows were failing → hit the cap
- Explicit 86,400s (24 hours) overrides the warehouse-level limit at the session level

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.9 |
| Data manipulation | pandas, numpy |
| Snowflake client | snowflake-connector-python |
| Cloud storage | AWS S3 (via boto3, internal to Snowflake) |
| Credentials | python-dotenv (.env file) |
| Orchestration | Bash shell script |
| Schema inference | Custom regex-based type mapper |
