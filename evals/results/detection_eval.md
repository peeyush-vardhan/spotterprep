# Detection eval: Iteration 1 vs injected ground truth

- **Recall:** 82.0% (41 of 50 single-column issues found)
- **Precision vs logged issues:** 26.4% of 159 detections (lower bound; filler columns carry unlogged noise)
- **Precision excluding filler columns:** 48.8% of 86 detections on the tables' named business columns
- **Safety:** 100.0% of 15 monetary/PII detections classified LOW (never auto-fixed)
- **Ground truth:** 65 injected issues; scored 50, cross-column 11 (Iteration 5 and cleaning rules), out of scope 4

## Recall by issue family

| Family | Found | Recall |
|---|---|---|
| CATEGORICAL | 6 / 8 | 75.0% |
| DUPLICATE | 5 / 5 | 100.0% |
| FORMAT | 0 / 4 | 0.0% |
| FUTURE_DATE | 4 / 4 | 100.0% |
| IMPOSSIBLE_TEMPORAL | 5 / 5 | 100.0% |
| MALFORMED_EMAIL | 2 / 2 | 100.0% |
| NEGATIVE_MONETARY | 4 / 4 | 100.0% |
| NEGATIVE_NUMERIC | 3 / 3 | 100.0% |
| NULL | 9 / 9 | 100.0% |
| OUT_OF_RANGE | 2 / 5 | 40.0% |
| WHITESPACE | 1 / 1 | 100.0% |

## Precision by confidence level

| Level | Matched | Precision |
|---|---|---|
| HIGH | 25 / 51 | 49.0% |
| LOW | 8 / 15 | 53.3% |
| MEDIUM | 9 / 93 | 9.7% |

## Missed issues

| Table | Issue | Family | Columns |
|---|---|---|---|
| CUSTOMER_ORDERS | outliers_enterprise | OUT_OF_RANGE | total_amount |
| IOT_TELEMETRY | sensor_fault_temperature | OUT_OF_RANGE | temperature_c |
| IOT_TELEMETRY | inconsistent_format | CATEGORICAL | firmware_version |
| HR_WORKFORCE | perf_rating_oob | OUT_OF_RANGE | perf_rating_2019, perf_rating_2020, perf_rating_2021, perf_rating_2022, perf_rating_2023, perf_rating_2024 |
| FINANCIAL_LEDGER | account_code_format | CATEGORICAL | account_code |
| FINANCIAL_LEDGER | floating_point_precision | FORMAT | debit_amount |
| PRODUCT_CATALOG | html_in_description | FORMAT | description_en |
| PRODUCT_CATALOG | lang_swap | FORMAT | product_name_en, product_name_hi, product_name_ja, product_name_de, product_name_fr, product_name_es, product_name_pt, product_name_zh |
| PRODUCT_CATALOG | special_chars_utf8 | FORMAT | product_name |
