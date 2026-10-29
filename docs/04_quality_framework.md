# SpotterPrep — Data Quality Scoring Framework

## Overview

Every dataset is scored across **5 dimensions** before and after cleaning.
The score shows what percentage of rows are "clean" in each dimension,
weighted to produce a single overall quality score (0–100).

---

## Formula

```
Score_dimension = (rows with zero issues in this dimension / total_rows) × 100

Overall_score = Σ (Score_dimension × weight)
```

---

## Dimensions & Weights

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| Completeness | 25% | % of rows where all important fields are non-null |
| Validity | 25% | % of rows within expected type, range, and format |
| Uniqueness | 20% | % of rows not duplicating another row (by primary key) |
| Consistency | 20% | % of rows conforming to domain vocabulary and business rules |
| Accuracy | 10% | % of rows where logical and temporal relationships hold |

---

## Grade Thresholds

| Grade | Score Range | Meaning |
|-------|------------|---------|
| A | 95 – 100 | Production-ready |
| B | 85 – 94 | Minor issues, usable with caveats |
| C | 70 – 84 | Moderate issues, needs cleaning |
| D | 55 – 69 | Significant issues |
| F | < 55 | Not fit for use |

---

## Dimension Definitions

### Completeness (25%)
A row passes if all **business-critical fields** are populated.
Intentionally nullable fields (e.g. PII fields, optional monetary amounts)
do not count as missing — they are flagged as "intentionally null" in cleaning.

Examples of issues that reduce completeness:
- `customer_name IS NULL` in an orders dataset
- `employee_id IS NULL` in an HR dataset
- `transaction_amount IS NULL` in a financial ledger (unintentional)

### Validity (25%)
A row passes if all values are within expected type, range, and format.

Examples of issues that reduce validity:
- Email addresses that don't match `*@*.*` pattern
- Negative values in `order_amount` (should be ≥ 0)
- `discount_pct` > 100 or < 0
- Dates in the future for historical fields

### Uniqueness (20%)
A row passes if its primary key does not appear more than once in the dataset.

Examples of issues that reduce uniqueness:
- Duplicate `order_id` values
- Duplicate `employee_id` values
- Duplicate `transaction_id` values

### Consistency (20%)
A row passes if it conforms to domain vocabulary and internal business rules.

Examples of issues that reduce consistency:
- `status` field has mixed casing: "active", "Active", "ACTIVE"
- `arr < mrr × 12` (ARR should equal MRR × 12)
- `country_code` not in the ISO 3166 standard list
- `department` name not in the approved list

### Accuracy (10%)
A row passes if logical and temporal relationships between fields hold.

Examples of issues that reduce accuracy:
- `go_live_date < onboarding_date` (impossible sequence)
- `end_date < start_date`
- `seats_used > seats_purchased`

---

## Results — All 5 Datasets

| Dataset | Completeness | Validity | Uniqueness | Consistency | Accuracy | **Overall** | Grade |
|---------|-------------|---------|-----------|------------|---------|------------|-------|
| CUSTOMER_ORDERS RAW | 72.0 | 90.5 | 99.7 | 90.0 | 99.9 | **88.5** | B |
| CUSTOMER_ORDERS CLEAN | 84.0 | 99.7 | 100.0 | 99.0 | 99.9 | **95.7** | A |
| IOT_TELEMETRY RAW | 90.0 | 96.0 | 99.9 | 93.0 | 97.0 | **94.0** | B |
| IOT_TELEMETRY CLEAN | 98.0 | 99.8 | 100.0 | 99.3 | 99.0 | **99.1** | A |
| HR_WORKFORCE RAW | 77.5 | 91.3 | 98.0 | 91.3 | 96.9 | **89.7** | B |
| HR_WORKFORCE CLEAN | 82.5 | 99.0 | 99.8 | 99.0 | 99.2 | **95.1** | A |
| FINANCIAL_LEDGER RAW | 98.2 | 97.6 | 99.4 | 72.0 | 98.7 | **93.1** | B |
| FINANCIAL_LEDGER CLEAN | 99.5 | 99.8 | 99.9 | 99.5 | 99.2 | **99.6** | A |
| PRODUCT_CATALOG RAW | 85.3 | 98.7 | 96.0 | 87.0 | 89.5 | **91.6** | B |
| PRODUCT_CATALOG CLEAN | 97.0 | 99.8 | 100.0 | 97.5 | 97.0 | **98.4** | A |

**Average lift: +6.2 percentage points. All 5 datasets: Grade B → Grade A.**

---

## Why These Weights?

- **Completeness and Validity (25% each):** Missing and invalid data are the most
  common causes of broken analytics queries. They get equal top weight.
- **Uniqueness and Consistency (20% each):** Duplicates inflate metrics; inconsistent
  vocabularies break GROUP BY aggregations. Critical for BI tools like ThoughtSpot.
- **Accuracy (10%):** Logical errors are less frequent but high impact when they occur.
  Lower weight because they are harder to detect systematically at scale.
