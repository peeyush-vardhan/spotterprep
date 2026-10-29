-- ============================================================
-- SpotterPrep — Snowflake Quickstart Queries
-- Run these in a Snowflake worksheet after loading all tables.
-- ============================================================

USE DATABASE SPOTTERPREP_TEST;

-- ============================================================
-- 1. Verify all 10 tables loaded with correct row counts
-- ============================================================
SELECT
    table_schema,
    table_name,
    row_count,
    CASE
        WHEN table_name = 'CUSTOMER_ORDERS_RAW'      AND row_count = 100000  THEN 'PASS'
        WHEN table_name = 'CUSTOMER_ORDERS_CLEANED'  AND row_count = 99655   THEN 'PASS'
        WHEN table_name = 'IOT_TELEMETRY_RAW'        AND row_count = 500000  THEN 'PASS'
        WHEN table_name = 'IOT_TELEMETRY_CLEANED'    AND row_count = 499244  THEN 'PASS'
        WHEN table_name = 'HR_WORKFORCE_RAW'         AND row_count = 800000  THEN 'PASS'
        WHEN table_name = 'HR_WORKFORCE_CLEANED'     AND row_count = 790809  THEN 'PASS'
        WHEN table_name = 'FINANCIAL_LEDGER_RAW'     AND row_count = 1000000 THEN 'PASS'
        WHEN table_name = 'FINANCIAL_LEDGER_CLEANED' AND row_count = 996405  THEN 'PASS'
        WHEN table_name = 'PRODUCT_CATALOG_RAW'      AND row_count = 2000000 THEN 'PASS'
        WHEN table_name = 'PRODUCT_CATALOG_CLEANED'  AND row_count = 1959606 THEN 'PASS'
        ELSE 'FAIL — unexpected count'
    END AS load_status
FROM information_schema.tables
WHERE table_schema IN ('RAW', 'CLEANED')
ORDER BY table_schema, table_name;


-- ============================================================
-- 2. Dataset 1 — CUSTOMER_ORDERS: Raw vs Cleaned comparison
-- ============================================================

-- Sample rows
SELECT * FROM RAW.CUSTOMER_ORDERS_RAW     LIMIT 5;
SELECT * FROM CLEANED.CUSTOMER_ORDERS_CLEANED LIMIT 5;

-- Null rate on key fields
SELECT
    'RAW'  AS source, COUNT(*) AS total,
    SUM(CASE WHEN order_amount   IS NULL THEN 1 ELSE 0 END) AS null_order_amount,
    SUM(CASE WHEN customer_name  IS NULL THEN 1 ELSE 0 END) AS null_customer_name,
    SUM(CASE WHEN email          IS NULL THEN 1 ELSE 0 END) AS null_email
FROM RAW.CUSTOMER_ORDERS_RAW
UNION ALL
SELECT
    'CLEANED', COUNT(*),
    SUM(CASE WHEN order_amount   IS NULL THEN 1 ELSE 0 END),
    SUM(CASE WHEN customer_name  IS NULL THEN 1 ELSE 0 END),
    SUM(CASE WHEN email          IS NULL THEN 1 ELSE 0 END)
FROM CLEANED.CUSTOMER_ORDERS_CLEANED;

-- Status standardisation (raw: mixed case; cleaned: standardised)
SELECT 'RAW' AS source, status, COUNT(*) AS cnt FROM RAW.CUSTOMER_ORDERS_RAW    GROUP BY 2 ORDER BY 1,3 DESC;
SELECT 'CLN' AS source, status, COUNT(*) AS cnt FROM CLEANED.CUSTOMER_ORDERS_CLEANED GROUP BY 2 ORDER BY 1,3 DESC;


-- ============================================================
-- 3. Dataset 2 — IOT_TELEMETRY: Sensor reading ranges
-- ============================================================
SELECT
    'RAW'  AS source,
    MIN(temperature_c) AS min_temp, MAX(temperature_c) AS max_temp,
    MIN(humidity_pct)  AS min_hum,  MAX(humidity_pct)  AS max_hum
FROM RAW.IOT_TELEMETRY_RAW
UNION ALL
SELECT
    'CLEANED',
    MIN(temperature_c), MAX(temperature_c),
    MIN(humidity_pct),  MAX(humidity_pct)
FROM CLEANED.IOT_TELEMETRY_CLEANED;


-- ============================================================
-- 4. Dataset 3 — HR_WORKFORCE: Department distribution
-- ============================================================
SELECT department, COUNT(*) AS headcount
FROM RAW.HR_WORKFORCE_RAW
GROUP BY 1 ORDER BY 2 DESC
LIMIT 10;

SELECT department, COUNT(*) AS headcount
FROM CLEANED.HR_WORKFORCE_CLEANED
GROUP BY 1 ORDER BY 2 DESC
LIMIT 10;


-- ============================================================
-- 5. Dataset 4 — FINANCIAL_LEDGER: Amount distribution
-- ============================================================
SELECT
    'RAW'  AS source,
    COUNT(*) AS total_txns,
    SUM(transaction_amount) AS total_amount,
    AVG(transaction_amount) AS avg_amount,
    MIN(transaction_amount) AS min_amount,
    MAX(transaction_amount) AS max_amount
FROM RAW.FINANCIAL_LEDGER_RAW
UNION ALL
SELECT
    'CLEANED',
    COUNT(*), SUM(transaction_amount), AVG(transaction_amount),
    MIN(transaction_amount), MAX(transaction_amount)
FROM CLEANED.FINANCIAL_LEDGER_CLEANED;


-- ============================================================
-- 6. Dataset 5 — PRODUCT_CATALOG: Category breakdown
-- ============================================================
SELECT category, COUNT(*) AS product_count, AVG(price) AS avg_price
FROM RAW.PRODUCT_CATALOG_RAW
GROUP BY 1 ORDER BY 2 DESC
LIMIT 10;

SELECT category, COUNT(*) AS product_count, AVG(price) AS avg_price
FROM CLEANED.PRODUCT_CATALOG_CLEANED
GROUP BY 1 ORDER BY 2 DESC
LIMIT 10;


-- ============================================================
-- 7. Full pipeline summary — all tables at a glance
-- ============================================================
SELECT
    r.table_name                                          AS raw_table,
    r.row_count                                           AS raw_rows,
    c.table_name                                          AS cleaned_table,
    c.row_count                                           AS cleaned_rows,
    r.row_count - c.row_count                             AS rows_removed,
    ROUND((r.row_count - c.row_count) / r.row_count * 100, 2) AS pct_removed
FROM information_schema.tables r
JOIN information_schema.tables c
    ON REPLACE(r.table_name, '_RAW', '') = REPLACE(c.table_name, '_CLEANED', '')
WHERE r.table_schema = 'RAW'
  AND c.table_schema = 'CLEANED'
ORDER BY r.row_count DESC;
