-- ============================================================
-- SpotterPrep — Data Quality Validation Queries
-- Run these to validate quality scores per dimension.
-- ============================================================

USE DATABASE SPOTTERPREP_TEST;

-- ============================================================
-- DATASET 1 — CUSTOMER_ORDERS
-- ============================================================

-- Completeness: rows with no nulls in critical fields
SELECT
    'Completeness' AS dimension,
    COUNT(*) AS total_rows,
    SUM(CASE WHEN customer_name IS NOT NULL
              AND email         IS NOT NULL
              AND order_amount  IS NOT NULL
              AND nps_score     IS NOT NULL
        THEN 1 ELSE 0 END) AS passing_rows,
    ROUND(passing_rows / total_rows * 100, 1) AS score
FROM RAW.CUSTOMER_ORDERS_RAW
UNION ALL
SELECT 'Completeness', COUNT(*),
    SUM(CASE WHEN customer_name IS NOT NULL AND email IS NOT NULL AND order_amount IS NOT NULL THEN 1 ELSE 0 END),
    ROUND(SUM(CASE WHEN customer_name IS NOT NULL AND email IS NOT NULL AND order_amount IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 1)
FROM CLEANED.CUSTOMER_ORDERS_CLEANED;

-- Validity: emails in valid format and amounts non-negative
SELECT
    'Validity' AS dimension,
    COUNT(*) AS total_rows,
    SUM(CASE WHEN (email IS NULL OR email LIKE '%@%.%')
              AND (order_amount IS NULL OR order_amount >= 0)
              AND (discount_pct IS NULL OR (discount_pct >= 0 AND discount_pct <= 100))
        THEN 1 ELSE 0 END) AS passing_rows
FROM RAW.CUSTOMER_ORDERS_RAW;

-- Uniqueness: duplicate order_id check
SELECT order_id, COUNT(*) AS cnt
FROM RAW.CUSTOMER_ORDERS_RAW
GROUP BY 1 HAVING cnt > 1
ORDER BY 2 DESC
LIMIT 10;

SELECT order_id, COUNT(*) AS cnt
FROM CLEANED.CUSTOMER_ORDERS_CLEANED
GROUP BY 1 HAVING cnt > 1
ORDER BY 2 DESC
LIMIT 10;


-- ============================================================
-- DATASET 2 — IOT_TELEMETRY
-- ============================================================

-- Validity: sensor readings within physical limits
SELECT
    'Validity' AS dimension,
    COUNT(*) AS total,
    SUM(CASE WHEN temperature_c BETWEEN -50 AND 150
              AND humidity_pct  BETWEEN 0   AND 100
        THEN 1 ELSE 0 END) AS valid_rows,
    ROUND(valid_rows / total * 100, 1) AS score
FROM RAW.IOT_TELEMETRY_RAW
UNION ALL
SELECT 'Validity', COUNT(*),
    SUM(CASE WHEN temperature_c BETWEEN -50 AND 150 AND humidity_pct BETWEEN 0 AND 100 THEN 1 ELSE 0 END),
    ROUND(SUM(CASE WHEN temperature_c BETWEEN -50 AND 150 AND humidity_pct BETWEEN 0 AND 100 THEN 1 ELSE 0 END) / COUNT(*) * 100, 1)
FROM CLEANED.IOT_TELEMETRY_CLEANED;


-- ============================================================
-- DATASET 3 — HR_WORKFORCE
-- ============================================================

-- Completeness: key HR fields populated
SELECT
    'Completeness' AS dimension,
    COUNT(*) AS total,
    SUM(CASE WHEN employee_id  IS NOT NULL
              AND full_name    IS NOT NULL
              AND department   IS NOT NULL
              AND hire_date    IS NOT NULL
              AND salary       IS NOT NULL
        THEN 1 ELSE 0 END) AS passing,
    ROUND(passing / total * 100, 1) AS score
FROM RAW.HR_WORKFORCE_RAW
UNION ALL
SELECT 'Completeness', COUNT(*),
    SUM(CASE WHEN employee_id IS NOT NULL AND full_name IS NOT NULL AND department IS NOT NULL AND hire_date IS NOT NULL THEN 1 ELSE 0 END),
    ROUND(SUM(CASE WHEN employee_id IS NOT NULL AND full_name IS NOT NULL AND department IS NOT NULL AND hire_date IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 1)
FROM CLEANED.HR_WORKFORCE_CLEANED;

-- Accuracy: hire_date should be before termination_date
SELECT COUNT(*) AS impossible_sequences
FROM RAW.HR_WORKFORCE_RAW
WHERE termination_date IS NOT NULL
  AND termination_date < hire_date;

SELECT COUNT(*) AS impossible_sequences
FROM CLEANED.HR_WORKFORCE_CLEANED
WHERE termination_date IS NOT NULL
  AND termination_date < hire_date;


-- ============================================================
-- DATASET 4 — FINANCIAL_LEDGER
-- ============================================================

-- Consistency: account_code format check
SELECT
    'Consistency' AS dimension,
    COUNT(*) AS total,
    SUM(CASE WHEN account_code REGEXP '^[A-Z]{2}-[0-9]{4}$' THEN 1 ELSE 0 END) AS passing,
    ROUND(passing / total * 100, 1) AS score
FROM RAW.FINANCIAL_LEDGER_RAW
UNION ALL
SELECT 'Consistency', COUNT(*),
    SUM(CASE WHEN account_code REGEXP '^[A-Z]{2}-[0-9]{4}$' THEN 1 ELSE 0 END),
    ROUND(SUM(CASE WHEN account_code REGEXP '^[A-Z]{2}-[0-9]{4}$' THEN 1 ELSE 0 END) / COUNT(*) * 100, 1)
FROM CLEANED.FINANCIAL_LEDGER_CLEANED;

-- Validity: no negative transaction amounts for debit entries
SELECT COUNT(*) AS invalid_debits
FROM RAW.FINANCIAL_LEDGER_RAW
WHERE entry_type = 'DEBIT' AND transaction_amount < 0;

SELECT COUNT(*) AS invalid_debits
FROM CLEANED.FINANCIAL_LEDGER_CLEANED
WHERE entry_type = 'DEBIT' AND transaction_amount < 0;


-- ============================================================
-- DATASET 5 — PRODUCT_CATALOG
-- ============================================================

-- Validity: price must be positive
SELECT
    'Validity — price > 0' AS check_name,
    COUNT(*) AS total,
    SUM(CASE WHEN price > 0 THEN 1 ELSE 0 END) AS passing,
    ROUND(passing / total * 100, 2) AS score
FROM RAW.PRODUCT_CATALOG_RAW
UNION ALL
SELECT 'Validity — price > 0', COUNT(*),
    SUM(CASE WHEN price > 0 THEN 1 ELSE 0 END),
    ROUND(SUM(CASE WHEN price > 0 THEN 1 ELSE 0 END) / COUNT(*) * 100, 2)
FROM CLEANED.PRODUCT_CATALOG_CLEANED;

-- Uniqueness: duplicate product_id
SELECT product_id, COUNT(*) AS cnt
FROM RAW.PRODUCT_CATALOG_RAW
GROUP BY 1 HAVING cnt > 1
ORDER BY 2 DESC LIMIT 10;

SELECT product_id, COUNT(*) AS cnt
FROM CLEANED.PRODUCT_CATALOG_CLEANED
GROUP BY 1 HAVING cnt > 1
ORDER BY 2 DESC LIMIT 10;
