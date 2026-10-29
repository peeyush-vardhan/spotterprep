# SpotterPrep — PII Handling Policy

**Author:** Peeyush Vardhan, Product Manager
**Document type:** Product + Solution + Technical Policy
**Status:** V1 — For engineering alignment
**Last updated:** March 2026

---

## Why This Document Exists

SpotterPrep sits at an uncomfortable intersection: it needs to *understand* data well enough to ask intelligent questions about it, but it does this by passing information to an external LLM API. The moment a data preparation product touches personal data, three questions must be answered before any code is written:

1. **What data does the LLM actually need** to do its job?
2. **What is the default data handling posture** — opt-in or opt-out?
3. **What changes at each layer** of the architecture to enforce that posture?

This document answers all three, and derives the engineering requirements from the product and legal position — not the other way around.

---

## 1. The Product Position

**Default stance: the LLM never receives raw cell values from PII or monetary columns.**

This is not a legal hedge. It is the correct product design for an enterprise data tool.

SpotterPrep's primary customers are analysts at companies with 500+ seats. These companies have data governance policies, security reviews, and in many cases regulatory obligations (GDPR, CCPA, HIPAA, SOC 2, FedRAMP). A product that sends customer names and email addresses to a third-party API — even one that does not train on the data — will fail the security review before it reaches the analyst.

More importantly: SpotterPrep does not *need* raw PII values to do its job. The LLM needs to understand *what kind of problem exists on a column* — not read actual personal data to do that. Column name, issue type, null rate, and issue detail are sufficient to generate a useful, targeted question. "14.9% of rows in `customer_name` are null — is this expected for guest checkout orders?" does not require the LLM to have seen a single actual customer name.

**The metadata-only default is a product strength, not a limitation.** It is what makes SpotterPrep deployable in regulated industries without a custom security review per customer.

---

## 2. What the LLM Needs vs. What It Doesn't

Understanding this distinction is the foundation of the technical design.

### What the LLM needs (always safe to send)

| Data | Example | Why safe |
|---|---|---|
| Column name | `customer_name`, `order_amount` | Metadata — no personal data |
| Issue type | `NULL_PII`, `NEGATIVE_MONETARY` | Classification label — no values |
| Row count and percentage | `14,900 rows (14.9%)` | Aggregate statistic — no values |
| Issue detail | `"14.9% null — PII column, nulls may be opt-outs"` | AI-generated description — no values |
| Confidence level and action | `LOW / PRESERVE_NULL` | Classification — no values |
| Table name | `CUSTOMER_ORDERS` | Schema metadata — no values |

### What requires a policy decision before sending

| Data | Example | Risk |
|---|---|---|
| Non-PII example values | `["ACTIVE", "active", "Active"]` — a status column | Low risk. Safe to send for categorical/format issues. Not personal data. |
| Numeric example values | `[-120.50, -45.00, -890.25]` — negative order amounts | Low risk for the values themselves, but monetary columns require care — amounts can be identifying in small datasets. |
| PII example values | `["John Smith", "jane.doe@acme.com"]` | **High risk. Never send by default.** Personal data leaving the customer environment. |
| Monetary PII (e.g. salary) | `[42000.0, 38500.0, 95000.0]` — HR salary column | **High risk.** Compensation data is sensitive even without names. |

### The rule, stated simply

> Send column metadata and aggregate statistics to the LLM always.
> Send non-PII example values for non-monetary columns — they help the LLM ask better questions.
> Never send example values from PII columns or monetary columns in their raw form.
> If a customer wants value-level context for PII/monetary columns, that is an opt-in feature gated behind a signed DPA.

---

## 3. Legal and Compliance Context

### GDPR (EU customers)

Under GDPR Article 28, sending personal data to a third-party processor (Anthropic) requires:
- A Data Processing Agreement (DPA) between the customer and Anthropic
- Documentation of the processing purpose and legal basis
- The ability to audit or terminate the processing

Anthropic offers a DPA for enterprise API customers. But the customer must sign it — and SpotterPrep cannot assume they have. The default posture must be safe without a DPA in place.

### CCPA (US/California customers)

CCPA requires disclosure of what personal data is shared with third parties and for what purpose. An analyst using SpotterPrep at a California company would need to disclose that customer PII is passed to an AI API for data quality analysis. This is a non-trivial disclosure that requires legal review. Default: avoid it.

### HIPAA (Healthcare customers)

PHI (Protected Health Information) cannot be sent to any third-party API without a signed Business Associate Agreement (BAA). Anthropic does not currently offer a BAA for the standard API. SpotterPrep must never send values from columns that could contain PHI — patient names, dates of birth, diagnosis codes, provider IDs.

### SOC 2 / Enterprise Security Reviews

Most 500+ seat enterprise software purchases go through a security review. The question "does your product send our data to external APIs?" is always on the questionnaire. The correct answer for SpotterPrep is: "We send schema metadata and aggregate statistics. Raw cell values are never sent to external APIs unless the customer explicitly opts in and has a signed DPA with the AI provider." This answer passes security reviews. "We send example values to help the AI ask better questions" does not.

---

## 4. The Three-Layer Architecture and PII Boundaries

SpotterPrep's architecture has three layers. PII policy applies differently at each.

```
┌─────────────────────────────────────────────────────────────┐
│  CONTEXT LAYER (LLM — Claude)                               │
│  Receives: column metadata + aggregate stats ONLY           │
│  Never receives: raw cell values from PII/monetary cols     │
│  PII policy: enforced by sanitise_issue() before call      │
└──────────────────────────┬──────────────────────────────────┘
                           │ sanitised metadata only
┌──────────────────────────▼──────────────────────────────────┐
│  PROFILER LAYER (Python / SQL — deterministic)              │
│  Receives: full dataset or sample                           │
│  Holds: raw cell values in memory during scan               │
│  PII policy: values used for detection, never persisted     │
│             example_values field populated but sanitised    │
│             before LLM handoff                              │
└──────────────────────────┬──────────────────────────────────┘
                           │ approved action list (no values)
┌──────────────────────────▼──────────────────────────────────┐
│  TRANSFORMER LAYER (parameterised execution)                │
│  Receives: action type + column name + rule only            │
│  Never receives: LLM output containing raw PII values       │
│  PII policy: transformations are structural, not value-based│
└─────────────────────────────────────────────────────────────┘
```

**The PII boundary is at the Context Layer input.** The Profiler can and should see raw values — that's how it detects issues. The Transformer applies structural rules. Only the LLM handoff requires sanitisation, and that is enforced by a single function: `_sanitise_for_llm()`.

---

## 5. SQL Profiler vs. Python Profiler — PII Implications

This is an open engineering question. The PII policy has direct implications for which approach is architecturally cleaner.

### Python profiler (current approach — `confidence_scorer.py`)

The profiler runs locally, reads raw values from the CSV/DataFrame, and produces a confidence map including `example_values`. Those example values are in memory and would be passed to the LLM without sanitisation.

**PII implication:** requires explicit sanitisation before every LLM call. One `_sanitise_for_llm()` function handles this. If that function is not called, PII can leak. The correctness of PII handling depends on developer discipline.

**Advantage:** richer detection — email regex, whitespace detection, pattern matching, outlier calculation all run locally on full data.

### SQL profiler (alternative approach)

The profiler runs as SQL inside Snowflake. It never extracts raw cell values. It computes aggregate statistics (null counts, distinct counts, min/max, value distributions) and returns only numbers and category lists to the Python layer.

**PII implication:** raw values never leave Snowflake. The LLM receives only aggregates — structurally impossible for PII to leak because the values are never in the Python process at all.

**Advantage:** architecturally PII-safe by default. No sanitisation function needed. Easier security review.

**Disadvantage:** loses some detection richness — email regex, whitespace detection, and pattern-level checks require seeing individual values. These would need to run as Snowflake UDFs or be approximated from statistics.

### Recommendation

**Default to SQL profiler for production.** The structural PII safety — no values ever leave the warehouse — is worth the detection tradeoff. Build the Python profiler as a local/dev mode for analysts who are working with non-PII datasets or have completed a DPA.

This means: the question "SQL or Python profiler?" is actually the question "do we want PII safety by architecture, or by code discipline?" Architecture wins for an enterprise product.

---

## 6. The Opt-In Path

There will be customers — typically working with non-PII datasets (IoT telemetry, financial ledger aggregates, product catalog data) — who want the LLM to see real example values to generate more specific questions.

The opt-in path requires:

1. **Customer has signed a DPA with Anthropic** — or is using a private deployment (Bedrock, Vertex AI) where data stays in their cloud account
2. **Analyst explicitly enables value-level context** — not a default setting, a deliberate toggle
3. **Audit log records that value-level mode was used** — so the customer can demonstrate to their DPO what data was processed and when
4. **PII columns are still never included, even in opt-in mode** — the `NULL_PII` issue type always receives redacted examples

The opt-in toggle in the script:
```python
python spotterprep/iteration2_context.py data/raw/iot_telemetry.csv --allow-value-context
```

Without `--allow-value-context`, all example values are sanitised before LLM calls. With it, non-PII column examples are sent as-is, and the audit log records the session as `value_context_enabled: true`.

---

## 7. Column Classification and PII Detection

The current `confidence_scorer.py` uses regex patterns to classify columns. These same patterns drive the sanitisation decision:

| Pattern | Column examples | LLM treatment |
|---|---|---|
| `_MONETARY_COL` | `order_amount`, `salary`, `arr`, `balance` | Redact example values |
| `_PII_COL` | `customer_name`, `email`, `phone`, `address`, `dob` | Redact example values |
| `NULL_PII` issue type | Any column triggering PII null detection | Redact example values |
| `NULL_MONETARY` issue type | Any column triggering monetary null detection | Redact example values |
| Everything else | `status`, `region`, `product_id`, `sensor_type` | Send example values (safe) |

**Edge cases that need explicit handling:**

- `account_number`, `employee_id`, `patient_id` — these are quasi-identifiers. Not matched by current PII regex but should be treated as PII. Add to `_PII_COL` pattern.
- `ip_address`, `device_id` — can be PII under GDPR. Add to `_PII_COL` pattern for EU customers.
- `zip_code`, `age` — borderline. Safe to send as examples in most contexts, but combine with other quasi-identifiers and they become identifying. Treat as safe for now; revisit for HIPAA customers.

---

## 8. Implementation Requirements

### What must be built

| Requirement | Where | Priority |
|---|---|---|
| `_sanitise_for_llm(issue)` function | `spotterprep/iteration2_context.py` | **P0 — before any customer use** |
| Apply sanitisation before every LLM call | `_generate_question()` and `_parse_answer()` | **P0** |
| `--allow-value-context` CLI flag with audit log entry | `spotterprep/iteration2_context.py` | P1 |
| Extend `_PII_COL` regex with quasi-identifiers | `confidence_scorer.py` | P1 |
| SQL profiler as production default | New file `spotterprep/sql_profiler.py` | P2 |
| DPA check / warning at session start | `spotterprep/iteration2_context.py` | P2 |

### What the sanitisation function does

```python
# PII and monetary issue types — always redact
_REDACT_ISSUE_TYPES = {
    "NULL_PII",
    "NULL_MONETARY",
    "NEGATIVE_MONETARY",
}

# Column name patterns that trigger redaction regardless of issue type
_REDACT_COL_PATTERN = re.compile(
    r'amount|price|revenue|cost|salary|pay|fee|balance|debit|credit|arr|mrr|ltv|cac'  # monetary
    r'|name|email|phone|address|ssn|dob|birth|passport'           # PII
    r'|account.?number|employee.?id|patient.?id|ip.?address',     # quasi-identifiers
    re.I
)

def _sanitise_for_llm(issue: dict) -> dict:
    """
    Return a copy of the issue safe to send to the LLM.
    Redacts example_values for PII and monetary columns.
    All other fields (column name, issue type, counts, detail) are always safe.
    """
    if (
        issue["issue_type"] in _REDACT_ISSUE_TYPES
        or _REDACT_COL_PATTERN.search(issue["column"])
    ):
        safe = issue.copy()
        safe["example_values"] = ["[redacted — PII/monetary column]"]
        return safe
    return issue
```

The function is called once per issue before any LLM prompt is constructed. The original issue in the confidence map is never modified — only the copy passed to the LLM is sanitised.

---

## 9. What the Analyst Sees

The sanitisation is invisible to the analyst in the default case. The LLM generates a slightly more general question for PII/monetary columns — but "slightly more general" is appropriate. For a PII column:

**With raw values (unsafe):**
> "I see that row 4,823 has `customer_name = 'John Smith'` as null. Is this expected for guest checkout orders?"

**With redacted values (safe and correct):**
> "I see 14.9% of rows in `customer_name` are null. For this table, are null customer names expected — for example, for guest checkout orders — or are these data errors?"

The second question is actually *better* product behaviour. It asks about the business rule, not a specific row. The analyst's answer applies to all 14,900 null rows at once, not just one example. Sanitisation produces better questions, not worse ones.

---

## 10. Summary of Decisions

| Decision | Stance | Rationale |
|---|---|---|
| Default PII handling | Metadata only — no raw values to LLM | Enterprise deployability without DPA |
| Opt-in value context | Available with `--allow-value-context` + DPA | Useful for non-PII datasets |
| PII columns in opt-in mode | Still redacted — no exceptions | Personal data is never optional to protect |
| SQL vs Python profiler | SQL as production default | Structural PII safety beats code-discipline safety |
| Python profiler | Dev/local mode for non-PII datasets | Richer detection where PII is not a concern |
| Quasi-identifiers | Treated as PII | Conservative — correct for GDPR |
| Audit log for value-context sessions | Required | Customer DPO accountability |

---

*SpotterPrep — built by Peeyush Vardhan, Product Manager, ThoughtSpot.*


---

## Implementation note (current code)

Sanitisation lives in `sanitise_issue()` in [`spotterprep/llm.py`](../spotterprep/llm.py) and runs on every prompt. It applies two layers:

1. **By column.** Monetary and personal-data columns (by name) and monetary/PII issue types never send example values. The model sees only that values exist and were redacted.
2. **By value.** Every other example value is scanned for email addresses, SSN-shaped strings, card or account numbers, phone numbers and IPv4 addresses, and redacted individually. This catches personal data in columns whose names give no hint, such as `notes` or `contact`.

The never-impute rule for monetary and personal-data columns is also enforced in code after the model responds (`apply_guardrails()`), so it holds even if the analyst's answer or a prompt injection persuades the model otherwise. Every call is logged to `logs/llm_calls.jsonl` with the sanitised prompt, so redaction can be audited after the fact. Tests: [`tests/test_llm.py`](../tests/test_llm.py).
