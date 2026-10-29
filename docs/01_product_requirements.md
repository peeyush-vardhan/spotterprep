# SpotterPrep — Product Requirements Document

**Product:** SpotterPrep
**Author:** Peeyush Vardhan, Product Manager
**Status:** MVP Definition
**Last Updated:** March 2026
**Prototype:** Complete — 4.4M rows, 5 datasets, Snowflake-validated

---

## 1. The Problem

ThoughtSpot sells the promise of instant answers from data. The actual experience for most customers: 60–80% of analyst time is spent cleaning data before a single question can be asked in Spotter.

This is not a data literacy problem. It is a tooling gap. Analysts sit between a raw Snowflake table and ThoughtSpot with no purpose-built tool for the space in between. They use Python notebooks, dbt transformations, or manual SQL — none of which are designed for the conversational, trust-building workflow that enterprise data cleaning actually requires.

**The consequence is churn, not feature requests.** Customers who cannot get clean data into ThoughtSpot do not ask for better cleaning tools. They stop using ThoughtSpot.

SpotterPrep closes that gap. It is a data preparation agent that connects to a Snowflake table, profiles it, cleans it through a structured five-iteration model with full human oversight, and produces a clean dataset ready for Spotter — with every decision logged, explained, and reversible.

---

## 2. Target Customer

**Primary:** Data analysts at ThoughtSpot enterprise accounts (500+ seat companies) who own the data pipeline between their CDW and ThoughtSpot. They are the person Spotter fails when the data is wrong. They are not data engineers — they cannot write dbt models. They are not executives — they do not make architectural decisions. They are the person who gets blamed when the dashboard is wrong.

**Secondary:** Data engineers at the same accounts who currently maintain ad-hoc cleaning scripts and want an auditable, governed replacement.

**Not the target:** Data scientists building ML pipelines. Data engineers doing warehouse migrations. Analysts at companies without Snowflake. The tool is purpose-built for the ThoughtSpot → Spotter activation workflow.

---

## 3. What SpotterPrep Is

SpotterPrep is a five-iteration cleaning agent. It does not clean data automatically. It builds a model of what is wrong, asks the minimum number of questions to resolve what it cannot determine alone, proposes specific fixes for human approval, and executes only what has been explicitly authorized.

The output is not just a clean dataset. It is a clean dataset with a full audit trail, a quality score that tracks every change, and a context document that tells ThoughtSpot's Spotter what the data means.

**Prototype validation:** The complete decision tree has been implemented and run against five industry-realistic datasets totalling 4.4M rows and 1,880 columns loaded into Snowflake. Average quality score improvement: 59.1 → 93.9 across all datasets.

---

## 4. The Five-Iteration Cleaning Model

This is the core product. Every other section in this PRD exists to support it.

The five iterations are not pipeline stages. They are a trust-building sequence. Iterations 1 and 2 produce zero data changes by design — they build the information the system needs to act safely. Iterations 3 and 4 execute under different approval models. Iteration 5 is validation, not cleaning.

| Iteration | Name | Trigger | Score Impact | What It Produces |
|---|---|---|---|---|
| 1 | Structural Scan | AI-triggered, automatic | Zero (intentional) | Confidence map |
| 2 | Context Conversation | User-triggered, chat | Zero to +8 pts | Enriched confidence map |
| 3 | High-Confidence Fixes | AI-proposed, user approves | Largest jump (+13 to +19 pts) | Transformed data + audit log |
| 4 | Ambiguous Resolution | User-driven, per-issue | Second largest (+8 to +11 pts) | Transformed data + audit log |
| 5 | Cross-Column Validation | AI-triggered, automatic | Final gain (+6 to +7 pts) | Business intelligence findings |

### Iteration 1 — Structural Scan

The AI performs a full statistical profile of every column: null rates, duplicate rates, value distributions, format consistency, range violations, type consistency. It classifies every detected issue as HIGH, MEDIUM, or LOW confidence and stores the result as a structured JSON confidence map.

The AI presents findings in the chat interface without proposing any fixes. The output is: "I found 14 issues. I'm confident about 6 and ready to fix those. But before I touch anything, I need to understand 3 things about your business. Can I ask?"

**What the AI cannot determine at this stage — by design:**
- Whether a null is an error or legitimate (contractor with no bonus vs. missing order amount)
- Whether an out-of-range value is a fault or a valid extreme (industrial temperature, enterprise deal size)
- Which format variant is canonical (account_code in 4 formats — source of truth unknown)
- Whether a negative monetary value is a refund or a data error

These questions are resolved in Iteration 2. Acting without that context would produce wrong answers with high confidence — the most dangerous failure mode in data cleaning.

### Iteration 2 — Context Conversation

The AI asks the minimum number of questions needed to resolve every ambiguous issue. Each question is shown with a real example row from the actual data — not abstract statistics. "Order ORD-00042 from Acme Corp, placed 2024-03-12, has no customer name recorded. Is this expected for this type of order?" The analyst can answer this. "14.86% null customer_name" cannot be answered.

User answers are stored as context annotations on the confidence map. Issues are reclassified. This reclassification can improve the quality score without any data transformation — when 184K contractor NULLs are correctly identified as legitimate, the Completeness score improves because the numerator (valid rows) increases, not because any data changed.

**Per-dataset examples of what Iteration 2 resolves:**

| Dataset | Key Questions Asked | What Changes in the Confidence Map |
|---|---|---|
| Customer Orders | Are null order_amounts pending or errors? Are null NPS scores opt-outs? | Monetary nulls → flag for user; NPS nulls → preserve as legitimate |
| IoT Telemetry | What is the physical max temp? Can pressure ever be negative? | Physical bounds locked per sensor type; bounds feed into Iteration 3 |
| HR Workforce | Are contractors excluded from bonus/equity by policy? | 184K NULLs reclassified as correct data, not errors |
| Financial Ledger | Which account_code format is canonical? SOX escalation path? | Format mapping locked; imbalanced JEs escalated, not auto-fixed |
| Product Catalog | Language column swap confirmed? Which weight unit is canonical? | Swap fix authorized; kg confirmed as the source of truth |

### Iteration 3 — High-Confidence Fixes

The AI presents a complete, ordered action list for all issues with confidence score >90%. The list includes: the column, the rule, the row count, a before/after example, and the reasoning. The user approves the full list, approves selectively, or asks questions before execution. Nothing executes without explicit approval.

After approval, the transformation executor applies each action and writes a full audit log entry for every row changed: column, original value, new value, rule applied, approved by, approved at timestamp.

**What is always in Iteration 3 (at >90% confidence):**
- Duplicate primary keys
- Malformed emails (deterministic regex)
- Impossible temporal sequences (hire_date > termination_date)
- Text standardization to canonical form confirmed in Iteration 2
- Statistical imputation for non-critical numeric columns
- Physical range violations (bounds confirmed in Iteration 2)

**What is never in Iteration 3, regardless of confidence score:**

| Exclusion | Reason |
|---|---|
| MONETARY nulls | Accounting integrity — fabricating revenue figures is not a data quality fix |
| PII nulls | Cannot fabricate personal data under any circumstances |
| Physics violations on sensor data | Real fault events, not errors — require domain expert decision |
| Accounting imbalances (SOX) | Require human escalation, not automated resolution |
| Any column the user marked "ask me first" in Iteration 2 | Explicit instruction overrides confidence threshold |

### Iteration 4 — Ambiguous Resolution

Every issue the AI classified as MEDIUM or LOW confidence that has not been resolved by Iteration 2 context gets a user decision here. For each issue, the AI presents: the issue with a real example row, the possible interpretations (2–3 options), the action for each option, and the downstream impact.

The user selects an option or types a free-form instruction. The AI executes with a full audit trail. The quality score updates after each resolution — the user sees the score move as they make decisions.

**Per-dataset examples:**

| Dataset | Question to User | Outcome |
|---|---|---|
| Customer Orders | "The 12 negative order_amounts — refunds or errors?" | User confirms refunds → convert to positive, set order_type='REFUND' |
| IoT Telemetry | "5,000 zero vibration readings during 'running' status — sensor failure or valid?" | User confirms failure → add ZERO_VIBRATION_RUNNING flag |
| HR Workforce | "23,716 rows where total_comp < base_salary — ETL bug or intentional?" | User explains ETL bug → recompute total_comp from components |
| Financial Ledger | "1,200 intercompany entries not netting to zero — restatements or timing?" | User confirms timing → add INTERCO_TIMING flag |
| Product Catalog | "60,000 EUR prices don't match USD at current FX — fixed pricing or stale?" | User confirms stale → add STALE_FX_RATE flag with rate date |

### Iteration 5 — Cross-Column Validation

After all cleaning is complete, the AI scans the dataset as a whole — not column by column. Cross-column validation finds issues that are statistically invisible at the column level but obvious when two or more columns are examined together.

These findings are not cleaning actions. They are business intelligence. The AI presents them with full business context. The user decides: flag for review, escalate to a stakeholder, or accept as a known pattern.

**Per-dataset cross-column findings:**

| Dataset | Finding | Business Implication |
|---|---|---|
| Customer Orders | 234 rows: churn_risk='low' but health_score < 20 | Stale ML model labels |
| IoT Telemetry | 89 device-hours: energy spiked but RPM stayed flat | Early bearing failure indicator |
| HR Workforce | 234 employees: 5+ years tenure + declining perf ratings | Retention risk signal |
| Financial Ledger | 12 accruals with no reversal in following period ($2.3M) | Balance sheet overstatement risk |
| Product Catalog | 8,200 products priced higher in EU than US after FX | Grey market arbitrage risk |

---

## 5. The Confidence Map

The confidence map is the connective tissue of the entire product. Every architectural decision in this PRD exists to build it, protect it, and consume it correctly.

**What it is:** A structured JSON document written in Iteration 1 and enriched through Iterations 2–4. One confidence map per table per session. Stored in `SPOTTERPREP_TEST.PROFILES.QUALITY_REPORTS` as a `VARIANT` column.

**What it contains:** For every detected issue — the column, the issue type, the confidence score (0.0–1.0), the confidence level (HIGH/MEDIUM/LOW), the user-provided context annotations, the current status (pending/resolved/escalated), and the rule applied if resolved.

**Why it matters:** Without the confidence map, Iterations 1 and 2 are waste. With it, Iteration 3 is safe — the system knows exactly what it has permission to fix, what the user said about every ambiguity, and what must never be touched automatically. The confidence map is the difference between "AI cleaned my data" and "I cleaned my data with AI assistance."

**Schema:**

```sql
CREATE TABLE SPOTTERPREP_TEST.PROFILES.QUALITY_REPORTS (
    table_name          VARCHAR,
    session_id          VARCHAR,
    profiled_at         TIMESTAMP_NTZ,
    raw_rows            NUMBER,
    cleaned_rows        NUMBER,
    rows_deleted        NUMBER,
    rows_modified       NUMBER,
    quality_score_raw   FLOAT,
    quality_score_clean FLOAT,
    grade_raw           VARCHAR(1),
    grade_clean         VARCHAR(1),
    issues_critical     NUMBER,
    issues_warning      NUMBER,
    full_profile_json   VARIANT,   -- the full confidence map
    created_at          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
```

---

## 6. Three-Layer Processing Architecture

SpotterPrep has three processing layers with strict boundaries between them. These boundaries are not organizational preferences — they are data integrity and auditability requirements.

```
┌─────────────────────────────────────────────────────┐
│  CONTEXT LAYER                                      │
│  (LLM — Claude)                                     │
│  Semantic inference, narrative, question generation  │
│  Reads: column names, sample data, table metadata   │
│  Writes: structured JSON to confidence map only     │
└──────────────────────┬──────────────────────────────┘
                       │ structured JSON
┌──────────────────────▼──────────────────────────────┐
│  PROFILER LAYER                                     │
│  (Deterministic Python/SQL)                         │
│  Statistical computation, issue detection           │
│  Reads: full dataset or adaptive sample             │
│  Writes: confidence map                             │
└──────────────────────┬──────────────────────────────┘
                       │ approved action list
┌──────────────────────▼──────────────────────────────┐
│  TRANSFORMER LAYER                                  │
│  (Parameterized templates — governed)               │
│  Execution only — no decisions, no inference        │
│  Reads: approved action list from confidence map    │
│  Writes: SpotCache (CLEANED schema) + audit log     │
└─────────────────────────────────────────────────────┘
```

**The LLM never touches the Transformer layer.** It classifies, narrates, explains, and generates options. The Profiler detects. The Transformer executes. These responsibilities do not overlap.

### LLM Call Points (Five Layers, Five Moments)

| Layer | When Called | Input | Output |
|---|---|---|---|
| 1 — Schema Understanding | Iteration 1, before profiling | Column names + sample values + table context | Column type classification (MONETARY / TEMPORAL / PII / NUMERIC / CATEGORY) + business context per column |
| 2 — Anomaly Narrative | Iteration 1 end | Profile JSON (full issues_summary) | Plain-English summary: issue count, urgency, recommended first action |
| 3 — Decision Explanation | Iteration 3, action plan generation | Cleaning action + before/after values + rule applied | Human-readable explanation of why this action is correct for this specific case |
| 4 — Cross-Column Context | Iteration 5 | All column names + sample data + column statistics | Novel, domain-specific logic violations not in the rulebook |
| 5 — ThoughtSpot Context | Post-clean | Cleaned schema + profile statistics + data sample | Suggested Spotter search terms, column descriptions, suggested formulas, anomaly alerts |

**The LLM is never called for:** Statistical computation, transformation execution, audit log writes, quality score calculation, duplicate detection, null counting.

---

## 7. Profiler and Transformer Lexicon

Profilers and transformers are governed library functions. The LLM parameterizes them; it does not write them. Adding or modifying a profiler or transformer requires a code review, not a prompt change. This is the same governance model as a database built-in function.

### Profilers (Detection — Iteration 1)

| ID | Name | What It Detects | Column Types | Iteration |
|---|---|---|---|---|
| P01 | NULL_RATE | Null percentage vs. business threshold | All | 1 |
| P02 | DUPLICATE_PK | Exact duplicate primary key values | PK | 1 |
| P03 | DUPLICATE_COMPOSITE | Duplicate on (col_a + col_b) composite key | Any pair | 1 |
| P04 | RANGE_VIOLATION | Values outside defined min/max bounds | NUMERIC | 1 |
| P05 | NEGATIVE_VALUE | Negative values where semantically impossible | NUMERIC, MONETARY | 1 |
| P06 | FUTURE_DATE | Dates after current date where not valid | TEMPORAL | 1 |
| P07 | IMPOSSIBLE_SEQUENCE | col_a chronologically after col_b where impossible | TEMPORAL pair | 1 |
| P08 | EMAIL_FORMAT | Fails /^[^@]+@[^@]+\.[^@]+$/ regex | PII (email) | 1 |
| P09 | CATEGORY_INCONSISTENCY | Multiple variants representing same concept | CATEGORY | 1 |
| P10 | FORMAT_INCONSISTENCY | Same field in multiple format patterns | VARCHAR | 1 |
| P11 | OUTLIER_STATISTICAL | Values beyond 99th percentile threshold | NUMERIC | 1 |
| P12 | FLOAT_PRECISION | More than 2 decimal places on monetary columns | MONETARY | 1 |
| P13 | ORPHANED_FK | Foreign key values with no match in parent table | FK | 1 |
| P14 | PHYSICAL_LIMIT | Value violates a known physical law | NUMERIC (sensor) | 1 |
| P15 | CROSS_COLUMN_LOGIC | Value violates a defined relationship between columns | Any pair/triplet | 5 |

### Transformers (Execution — Iterations 3 and 4)

| ID | Name | What It Does | Iter 3 Eligible? | Notes |
|---|---|---|---|---|
| T01 | DEDUPLICATE_PK | Delete duplicate rows, keep first by created_at | Yes | Always HIGH confidence |
| T02 | NULLIFY_MALFORMED | Set invalid value to NULL with flag | Yes | Email, format violations |
| T03 | TRIM_WHITESPACE | Strip leading/trailing whitespace | Yes | Always HIGH confidence |
| T04 | STANDARDIZE_CATEGORY | Normalize to canonical form confirmed in Iter 2 | Yes | Requires Iter 2 canonical answer |
| T05 | STANDARDIZE_FORMAT | Normalize format to canonical pattern | Yes | Requires Iter 2 canonical answer |
| T06 | CAP_RANGE | Set value to min/max bound confirmed in Iter 2 | Yes | Requires Iter 2 bounds |
| T07 | SET_ZERO_FLOOR | Set negative value to 0 where negative = impossible | Yes | Non-monetary only |
| T08 | IMPUTE_MEDIAN | Replace NULL with column or group median | Yes | Non-PII, non-monetary only |
| T09 | RECOMPUTE | Derive value from component columns via formula | Yes | Requires confirmed formula |
| T10 | FLAG_ONLY | Add a flag column; do not modify the source value | Yes | Always safe |
| T11 | DELETE_ROW | Remove row from cleaned dataset | Yes | Only for objectively impossible rows |
| T12 | ESCALATE | Write to escalation queue; do not modify | No (Iter 4 only) | SOX, intercompany, PII decisions |

**Hard rule:** T08 (IMPUTE_MEDIAN) and T09 (RECOMPUTE) are never applied to MONETARY or PII columns regardless of confidence score. T12 (ESCALATE) is never in Iteration 3.

---

## 8. SpotStore / SpotCache Model

SpotterPrep never modifies source data. This is not a feature — it is an architectural invariant.

```
Snowflake (source CDW)
├── RAW schema       ← SpotterPrep reads here. Never writes. Ever.
├── CLEANED schema   ← SpotterPrep writes clean output here (SpotCache)
└── PROFILES schema  ← SpotterPrep writes confidence maps and quality reports here
```

**SpotCache semantics:**
- The CLEANED schema is a materialized view of the source table with SpotterPrep's approved transformations applied
- Default refresh: 24 hours (configurable per table)
- Source table changes after a SpotterPrep session are NOT automatically reflected in SpotCache — the analyst must re-run or schedule a refresh
- SpotCache is what ThoughtSpot connects to. Spotter queries SpotCache, not RAW.

**What this means for the user:** If the source table is updated in production, SpotterPrep shows a "SpotCache is N hours old — source has changed" indicator. The analyst can (a) re-run the full five-iteration model, (b) run only the profiler to check if new issues exist, or (c) accept the stale SpotCache for the current session.

**What this means for engineering:** The write path is strictly: Transformer Layer → SpotCache (CLEANED). The Transformer Layer never receives a connection string that points to RAW. This constraint is enforced at the infrastructure level, not the application level.

---

## 9. Quality Scoring Model

Quality scores are not ratings. They are measurements of a specific formula across five dimensions.

```
Quality Score =
  (Completeness × 0.25) +
  (Validity      × 0.25) +
  (Uniqueness    × 0.20) +
  (Consistency   × 0.20) +
  (Accuracy      × 0.10)
```

| Grade | Score Range | Meaning |
|---|---|---|
| A | 90–100 | Production-ready for ThoughtSpot |
| B | 75–89 | Usable with known caveats — document in context layer |
| C | 60–74 | High-risk for analysis — escalate before use |
| D | < 60 | Not ready — cleaning required before any use |

**Validated score progression across five datasets:**

| Dataset | Raw | Post-Iter 3 | Post-Iter 4 | Final |
|---|---|---|---|---|
| Customer Orders | 54.1 | 72.8 | 84.2 | 91.2 |
| IoT Telemetry | 68.3 | 84.1 | 91.6 | 97.4 |
| HR Workforce | 50.5 | 71.4 | 81.9 | 87.7 |
| Financial Ledger | 63.2 | 81.7 | 91.4 | 97.3 |
| Product Catalog | 59.3 | 78.9 | 89.1 | 96.2 |
| **Average** | **59.1** | **77.8** | **87.6** | **93.9** |

**Critical note on Grade B:** HR Workforce finishes at 87.7 (Grade B). This is correct. 46% of rows have legitimate contractor NULLs in bonus_target and equity_grant. SpotterPrep correctly identifies and preserves them. A Grade B that reflects true data quality is a better outcome than a Grade A achieved by fabricating data. **Engineering success criteria should never be "all datasets reach Grade A."**

---

## 10. Confidence Scoring and Approval Model

| Level | Score Range | Approval Required | Appears In |
|---|---|---|---|
| HIGH | ≥ 0.90 | User approves the full Iteration 3 action list once | Iteration 3 |
| MEDIUM | 0.65–0.89 | User decides per-issue with explicit rationale | Iteration 4 |
| LOW | < 0.65 | User decides per-issue; AI presents 2–3 options with downstream impact | Iteration 4 |

**Approval is per-transformation, logged per-row.** There is no "approve all MEDIUM items" button. There is no bulk approval for MONETARY or PII columns at any confidence level. Every audit log entry captures: iteration, column, rule_applied, action, rows_affected, confidence_score, confidence_level, approval_mechanism, approved_by, approved_at.

**Approval mechanisms by iteration:**

| Iteration | Mechanism | What "Approved By" Logs |
|---|---|---|
| 1 | Automatic | `system` |
| 2 | User conversation | The answer given in chat (stored as context annotation) |
| 3 | User explicit approval | `user_id` + timestamp of approval click |
| 4 | User per-issue decision | `user_id` + option selected + timestamp |
| 5 | Automatic | `system` |

---

## 11. Async Pipeline and UX Latency Model

The five-iteration model is sequential but not synchronous from the user's perspective. The user is never waiting for a computation to finish — they are always in a conversation.

| Iteration | Processing Time (target) | UX Model |
|---|---|---|
| 1 — Structural Scan | < 30s for tables up to 10M rows | Progress indicator → results appear in chat as they're ready |
| 2 — Context Conversation | User-paced | Chat interface; no timeout |
| 3 — High-Confidence Fixes | < 60s for most datasets | User sees "Applying 47 actions…" with live progress; score updates after completion |
| 4 — Ambiguous Resolution | User-paced | Each issue presented one at a time; quality score updates after each decision |
| 5 — Cross-Column Validation | < 15s | Appears automatically after Iteration 4 completes |

**Adaptive sampling:** For tables exceeding the target processing time, Iteration 1 profiling runs on a statistically representative sample. The sampling threshold and the statistical confidence guarantee for the sample are engineering open questions (see Section 14).

**SpotCache decoupling:** Profiling (Iterations 1–2) and transformation (Iterations 3–4) are decoupled from SpotCache refresh. A user can complete the full five-iteration model and have the results staged before SpotCache is written — this matters for SOX-regulated tables where write timing is controlled.

---

## 12. Auditability

Every transformation SpotterPrep applies is fully auditable. This is not a logging feature — it is the trust mechanism that makes human approval meaningful.

**The audit log is:**
- Append-only JSONL (one JSON object per line)
- One file per table: `audit_<table_name>.jsonl`
- Importable into Snowflake as a structured table
- Never modified after a write — corrections create new entries, never edits

**Every log entry contains:**

```json
{
  "timestamp": "2026-03-13T14:22:01.432Z",
  "session_id": "SPP-20260313T142201-7843",
  "table_name": "CUSTOMER_ORDERS",
  "iteration": 3,
  "iteration_label": "HIGH_CONFIDENCE_FIXES",
  "column": "order_id",
  "rule_applied": "DEDUPLICATE_PK",
  "action": "DELETE_ROW",
  "rows_affected": 300,
  "confidence_score": 0.99,
  "confidence_level": "HIGH",
  "approval_mechanism": "user_approved",
  "approved_by": "analyst@company.com",
  "approved_at": "2026-03-13T14:21:58.000Z",
  "original_value": null,
  "new_value": null,
  "detail": "Duplicate PK detected across 300 rows; earliest record preserved by created_at"
}
```

**For the product UI:** The audit trail is surfaced as a collapsible panel next to each Spotter answer. When Spotter returns a number from a cleaned column, the analyst can click to see exactly which transformations touched that column, who approved them, and when. This is the "show your work" feature that converts SpotterPrep from a black box into a trusted system.

---

## 13. Success Metrics

### Activation Metrics (MVP)

| Metric | Target | Why This One |
|---|---|---|
| Time-to-first-clean-dataset | < 30 minutes for a 100K-row table | Replaces the current experience of "a few days of Python" |
| Five-iteration completion rate | > 70% of sessions complete all 5 iterations | Dropping off at Iteration 2 or 3 means trust broke down |
| Quality score improvement | Average ≥ +25 pts from raw to final | Validated by prototype: average +34.8 pts across 5 datasets |
| Audit log completeness | 100% of executed transformations logged | Non-negotiable — partial audit trail is worse than none |
| SpotCache adoption | > 60% of cleaned datasets subsequently queried in Spotter | Validates that the cleaned data is actually used, not just produced |

### Quality Metrics (Post-MVP)

| Metric | Target | Why This One |
|---|---|---|
| Iteration 3 false positive rate | < 5% of HIGH-confidence actions reversed by user | HIGH confidence should mean almost never wrong |
| Iteration 2 question count | Median ≤ 5 questions per dataset | More than 8 questions indicates profiler is not doing enough work |
| MONETARY/PII escalation accuracy | > 95% of escalated items confirmed by user as "correct to escalate" | The hard-exclusion rule only works if users trust it |

### What is Not a Success Metric

- **Datasets reaching Grade A.** HR Workforce at Grade B is correct. Accuracy of classification is the goal, not score maximization.
- **Number of transformations applied.** More transformations does not mean more value.
- **LLM call count.** The LLM is a cost center. Fewer calls with better parameterization is better architecture.

---

## 14. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM misclassifies column type (e.g., treats a monetary column as numeric) | Medium | High — wrong transformer template applied | Schema Understanding output requires human confirmation for columns where classification confidence < 0.85 |
| User approves Iteration 3 action list without reading it | High | Medium — wrong actions applied with valid audit trail | Show row count and one before/after example per action. Surface "this will modify X rows" prominently. Do not allow bulk approve without scroll confirmation |
| Silent row rejection on SpotCache write | Low | High — rows dropped without surfacing to user | Write-time rejection count surfaced in audit log. Any failed write surfaces in the chat as an explicit error with row count and reason |
| SpotCache staleness not surfaced | Medium | Medium — analyst queries data that is behind the source | SpotCache "last refreshed" timestamp visible on every dataset card. Source-changed indicator if source table updated after last SpotCache write |
| Schema type inference bug on exotic column names | Low | Medium — incorrect profilers run on wrong column type | Integration test suite against all P01–P15 profilers on each of the 5 synthetic datasets before any schema type model change ships |
| MONETARY/PII exclusion bypassed by incorrect type classification | Low | Critical — automated changes to financial or personal data | Type classification for MONETARY and PII columns is the only classification that requires explicit human confirmation regardless of LLM confidence |
| Audit log incomplete on partial session failure | Low | High — partial audit trail is worse than none | Session-level completeness check: if any transformation has no audit entry, the full session is flagged for review and SpotCache write is blocked |

---

## 15. Anti-Scope (MVP)

These are decisions, not omissions. Each one is explicitly out of scope because including it would compromise the core value proposition.

| Item | Why Out of Scope |
|---|---|
| Automatic rule generation from user feedback | Rules are governed library functions. Auto-generation would make the transformer layer unpredictable and non-auditable. User decisions inform the confidence map for the current session only. Closed-loop learning is Phase 3. |
| Support for data sources other than Snowflake | The prototype proves the decision tree against Snowflake specifically. Generalization is Phase 2. |
| Bulk approval for MONETARY or PII columns | Accounting integrity and personal data cannot be delegated to a bulk action, regardless of confidence score. |
| Scheduled cleaning without human approval | Human approval on every execution is the trust mechanism. An automated nightly clean with no human in the loop is not SpotterPrep — it is an ETL pipeline. |
| Data transformations outside the T01–T12 lexicon | The LLM parameterizes existing transformers. It does not generate new transformation logic. This boundary is the safety constraint. |
| Quality score customization (different dimension weights) | The five-dimension weighted formula is the product. Custom weights would make scores incomparable across customers and datasets. |
| Column-level rollback | Full session rollback is supported. Column-level rollback introduces consistency risks across dependent columns (e.g., rolling back total_comp but not base_salary recomputation). Post-MVP. |

---

## 16. Open Questions

These require decisions before implementation begins. They are open because they involve trade-offs that the product team cannot resolve alone.

| # | Question | Owner | Why It Matters |
|---|---|---|---|
| OQ-1 | Adaptive sampling threshold — at what dataset size (rows × columns) does Iteration 1 switch from full-scan to sampled profiling? What is the statistical confidence guarantee on the sample? | Engineering + PM | Affects whether small issues are found on large datasets. A wrong threshold either kills latency or misses problems. |
| OQ-2 | LLM determinism in Iteration 2 — are questions generated with temperature=0 for reproducibility, or is some variance acceptable? | Engineering | If a user re-runs on the same table, they should get the same questions. Inconsistent questions break the audit trail narrative. |
| OQ-3 | SOX escalation path — when SpotterPrep escalates a Financial Ledger imbalance, what is the product action? Email the approver? Create a ticket in the customer's ITSM? | PM + Customer Success | This is the highest-stakes decision in the product. The answer depends on ThoughtSpot's integration strategy with enterprise workflow tools. |
| OQ-4 | SpotCache refresh pricing — is SpotCache storage billed to the customer, or included in the SpotterPrep product tier? | Product + Finance | Affects whether customers schedule aggressive refresh cadences that we haven't priced for. |
| OQ-5 | Multi-user sessions — if two analysts run SpotterPrep on the same table simultaneously, which confidence map wins? | Engineering | Session isolation vs. collaborative cleaning. The simpler answer is one active session per table at a time (advisory lock). Confirm this is acceptable. |
| OQ-6 | Context layer output format — does Schema Understanding output free-form JSON or a structured enum? Free-form is more flexible; enums are testable and governable. | Engineering | Determines how hard the Profiler layer integration is to build and test. |

---

## 17. Phase Roadmap

### MVP (Phase 1) — Hypotheses 1–17 from Vision Document

The complete five-iteration cleaning model, three-layer architecture, confidence map persistence, profiler/transformer lexicon (P01–P15, T01–T12), SpotStore/SpotCache, audit logging, quality scoring, and ThoughtSpot context generation. Snowflake only.

**Definition of done:** An analyst at a ThoughtSpot enterprise account can connect a raw Snowflake table, run the complete five-iteration model, and have a clean dataset in SpotCache connected to a ThoughtSpot Liveboard within 30 minutes, with a full audit trail available for any Spotter query.

### Phase 2 — Additional Data Sources + Workflow Integration

Databricks, BigQuery, Redshift support. SOX escalation workflow integration (ITSM). Scheduled SpotCache refresh with change-detection. Team collaboration (shared sessions, comment threads on confidence map items).

### Phase 3 — Intelligent Adaptation (Future)

Closed-loop learning from user approval patterns to improve confidence scoring over time. Cross-session profiler calibration. Customer-specific business rule libraries. These capabilities require a separate privacy, governance, and auditability review before design begins.

---

## Appendix — Snowflake Schema Reference

```
Database: SPOTTERPREP_TEST
├── Schema: RAW          -- Source tables. Never modified.
│   ├── CUSTOMER_ORDERS_RAW
│   ├── IOT_TELEMETRY_RAW
│   ├── HR_WORKFORCE_RAW
│   ├── FINANCIAL_LEDGER_RAW
│   └── PRODUCT_CATALOG_RAW
│
├── Schema: CLEANED      -- SpotCache. Clean output tables.
│   ├── CUSTOMER_ORDERS_CLEANED
│   ├── IOT_TELEMETRY_CLEANED
│   ├── HR_WORKFORCE_CLEANED
│   ├── FINANCIAL_LEDGER_CLEANED
│   └── PRODUCT_CATALOG_CLEANED
│
└── Schema: PROFILES     -- Confidence maps and quality reports.
    └── QUALITY_REPORTS  -- VARIANT column stores full profile JSON
```
