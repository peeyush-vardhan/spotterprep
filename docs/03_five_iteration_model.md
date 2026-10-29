# The Five-Iteration Cleaning Model

## The 5-Iteration Model

Each iteration has a specific trigger, purpose, and expected outcome. Two of the five iterations produce zero score gain — this is by design.

| Trigger type | Description |
|---|---|
| AI-triggered | Runs automatically, no user input required |
| User-triggered | AI asks questions, user answers in chat interface |
| AI-proposed | AI presents a plan, user approves before execution |
| User-driven | User resolves flagged ambiguities one by one |

---

## Iteration 1 — Structural Scan

**Trigger:** AI-triggered. Runs immediately after table connection, before any user interaction.
**Type:** Diagnostic
**Score impact:** Zero — intentional

**What the AI does:** The AI performs a full statistical scan of every column: null rates, duplicate rates, value distributions, format consistency, range violations, type consistency. It builds a confidence map — classifying every detected issue as HIGH confidence (AI can decide autonomously), MEDIUM confidence (AI needs context), or LOW confidence (human decision required).

**What the AI cannot do at this stage:**
- Determine whether a null is an error or legitimate (contractor with no bonus, pending order with no amount)
- Determine whether an out-of-range value is a fault or a valid extreme condition (industrial temperature, enterprise deal size)
- Determine which format variant is canonical (account_code in 4 formats — which is the source of truth?)
- Interpret domain-specific business rules (is a negative debit a credit memo or an error?)

**Output to user in chat interface:** The AI presents a summary of findings, categorised by confidence level, and explains what it needs to understand before proceeding. It does NOT propose any fixes yet.

**Example output:**
> "I've scanned your CUSTOMER_ORDERS table. I found 14 issues. I'm confident about 6 of them and ready to fix those. But before I touch anything, I need to understand 3 things about your business. Can I ask?"

---

## Iteration 2 — Context Conversation

**Trigger:** User-triggered. The AI asks targeted questions; the user answers in the chat interface.
**Type:** Diagnostic
**Score impact:** Zero for most datasets. +7.7 pts for DS3 (HR) because the conversation itself reclassifies legitimate NULLs.

**What happens:** The AI asks the minimum number of questions needed to resolve every ambiguous issue. Questions are shown with example rows so the analyst can see exactly what the AI is referring to — not abstract statistics, but real data.

**The key principle:** The AI presents concrete examples, not summaries. "I see 14.9% null customer_name" tells the analyst nothing useful. "Order ORD-00042 from Acme Corp, placed on 2024-03-12, has no customer name recorded. Is this expected for this type of order?" gives them something they can actually answer.

**What gets resolved per dataset:**

| Dataset | Key questions | What changes in AI's model |
|---|---|---|
| Customer Orders | Are null order_amounts pending or missing? Are null NPS scores opt-outs? | Monetary nulls → errors (flag); NPS nulls → legitimate (preserve) |
| IoT Telemetry | What is the physical max temp? Can pressure ever be negative? | Physical bounds locked per sensor type |
| HR Workforce | Are contractors excluded from bonus/equity by policy? | 184K NULLs reclassified as correct data, not errors |
| Financial Ledger | Which account_code format is canonical? How to escalate JE imbalances? | Format mapping locked; SOX escalation path defined |
| Product Catalog | Was the language column swap confirmed? Which weight unit is source of truth? | Swap fix authorised; kg confirmed as canonical |

**Why this iteration is critical:** Without it, the AI would make wrong decisions on the most consequential issues in every dataset. The DS3 contractor NULL case is the clearest example: if the AI imputed bonus_target for 120,000 contractor rows based on nearby full-time employees, it would fabricate compensation data. One conversation prevents this entirely.

---

## Iteration 3 — High-Confidence Fixes

**Trigger:** AI-proposed. The AI presents a complete list of actions; user approves before anything executes.
**Type:** Transformative
**Score impact:** Largest single jump across all datasets (+13.2 to +18.7 pts depending on dataset)

**Confidence threshold:** Only actions where the AI is >90% confident are included in this proposal. Anything below 90% is held for iteration 4.

**What "high confidence" means in practice:**
- Duplicate PKs → always safe to deduplicate (no business context changes this)
- Malformed emails → regex validation is deterministic, not interpretive
- Impossible temporal sequences → hire_date > termination_date is objectively impossible
- Text standardisation → canonical form confirmed in iteration 2
- Statistical imputation for non-critical columns → median/mean with documented rationale
- Physical range violations → bounds confirmed in iteration 2

**What is never in iteration 3, regardless of confidence:**
- MONETARY nulls (accounting integrity)
- PII nulls (cannot fabricate personal data)
- Physics violations on sensor data (real fault events, not errors)
- Accounting imbalances (SOX compliance, requires human escalation)
- Any action the user explicitly said "ask me first" in iteration 2

**The approval interaction:** The AI presents the full action list with row counts, before/after examples, and the reasoning for each action. The user can approve all, approve selectively, or ask questions about any specific action before it executes. Every action is logged with the timestamp of user approval.

**Why the score jumps here:** The Validity and Consistency dimensions are almost entirely fixed in this iteration — these dimensions are driven by format errors, range violations, and duplicate PKs, all of which are high-confidence fixes. The Completeness dimension also improves for columns where imputation was approved in iteration 2.

---

## Iteration 4 — Ambiguous Resolution

**Trigger:** User-driven. AI presents each ambiguous flag with full context; user makes the decision.
**Type:** Transformative
**Score impact:** Second largest jump across all datasets (+7.5 to +11.4 pts)

**What gets resolved here:** Every issue the AI flagged as MEDIUM or LOW confidence in its confidence map now gets a user decision. The AI presents:
1. The issue, with a real example row
2. The possible interpretations (usually 2-3 options)
3. The action for each option
4. The downstream impact of each option

The user selects an option, or types a free-form instruction, and the AI executes with a full audit trail.

**Per-dataset examples of what gets resolved:**

| Dataset | Ambiguity | Resolution |
|---|---|---|
| Customer Orders | "The 12 negative order_amounts — are these refunds or errors?" | User confirms refunds → AI converts to positive + sets order_type='REFUND' |
| IoT Telemetry | "5,000 zero vibration readings during 'running' status — sensor failure or valid?" | User confirms failure → AI adds ZERO_VIBRATION_RUNNING flag |
| HR Workforce | "23,716 rows where total_comp < base_salary — ETL bug or intentional?" | User explains bug → AI recomputes total_comp from components |
| Financial Ledger | "1,200 intercompany entries not netting to zero — restatements or timing?" | User confirms timing → AI adds INTERCO_TIMING flag with reconciliation date |
| Product Catalog | "60,000 EUR prices don't match USD at current FX — fixed pricing or stale?" | User confirms stale → AI adds STALE_FX_RATE flag with rate date |

**Why this produces the second-largest score jump:** The Accuracy dimension is almost entirely fixed in this iteration — logic violations between columns are caught and resolved here. Completeness also improves as user decisions unlock imputation for previously ambiguous columns.

---

## Iteration 5 — Cross-Column Validation

**Trigger:** AI-triggered. Runs automatically after all user decisions are complete.
**Type:** Validation
**Score impact:** Final gain across all datasets (+5.8 to +7.1 pts)

**What this iteration catches that nothing else can:** Per-column scans see columns in isolation. Cross-column validation sees the dataset as a whole. This is where the AI finds issues that are statistically invisible at the column level but become obvious when two or more columns are examined together.

**Examples per dataset:**

| Dataset | Cross-column finding | Type of insight |
|---|---|---|
| Customer Orders | 234 rows where churn_risk='low' but health_score < 20 | Stale ML model labels — business intelligence |
| IoT Telemetry | 89 device-hours where energy spiked but RPM stayed flat | Early bearing failure indicator — predictive maintenance |
| HR Workforce | 234 employees with 5+ years tenure + declining perf ratings | Retention risk signal — HR intelligence |
| Financial Ledger | 12 accruals with no reversal in following period ($2.3M) | Balance sheet overstatement risk — finance intelligence |
| Product Catalog | 8,200 products priced higher in EU than US after FX | Grey market arbitrage risk — pricing intelligence |

**The critical point for engineering:** These findings cannot be built into the decision tree in advance. They emerge from cross-column correlation that requires the full cleaned dataset as context. They are the highest-value outputs of the entire SpotterPrep pipeline — not just data quality fixes, but business intelligence that analysts wouldn't find any other way.

The Accuracy dimension is fully resolved here — all remaining logical and temporal relationships are verified across the clean dataset.

---

## Score Progression Summary

```
                    Raw    Iter1  Iter2  Iter3  Iter4  Iter5
                   ──────  ─────  ─────  ─────  ─────  ─────
Customer Orders     54.1   54.1   54.1   72.8   84.2   91.2
IoT Telemetry       68.3   68.3   68.3   84.1   91.6   97.4
HR Workforce        50.5   50.5   58.2   71.4   81.9   87.7
Financial Ledger    63.2   63.2   63.2   81.7   91.4   97.3
Product Catalog     59.3   59.3   64.8   78.9   89.1   96.2
─────────────────────────────────────────────────────────────
Average             59.1   59.1   61.7   77.8   87.6   93.9
```

**Reading this table:**
- Iterations 1 and 2 show zero or minimal score gain — this is correct and expected
- The largest single jump is always Iteration 3 — the confidence map built in iterations 1-2 makes this jump possible
- Iteration 4 is the second-largest jump — ambiguous issues resolved by the user
- Iteration 5 adds the final gain — cross-column intelligence that couldn't be found earlier
- The total gain (59.1 → 93.9) is identical to the single-pass code — but achieved through a process that builds analyst trust at every step

> **Note on these figures:** they were recorded on the original full-scale run with an earlier version of the quality scorer, and the current code does not reproduce them. Current numbers come from a script and are in the [README](../README.md#results) and [`evals/results/`](../evals/results).

---

## Engineering Implementation Requirements

### What Each Iteration Requires the System to Do

**Iteration 1 — Structural scan:**
- Statistical profiler runs on connected table (or sample per adaptive sampling rules)
- Issue classifier assigns confidence scores to each finding
- Confidence map stored as structured JSON per column
- Chat interface receives scan summary formatted for human readability

**Iteration 2 — Context conversation:**
- LLM generates targeted questions based on LOW/MEDIUM confidence issues
- Each question is accompanied by an example row from the actual data
- User responses are parsed and stored as context annotations on the confidence map
- Confidence map updated: issues reclassified based on user answers
- DS3-style reclassification: some issues transition from "error" to "legitimate" — this updates the Completeness score without any data transformation

**Iteration 3 — High-confidence fixes:**
- Action plan generated from HIGH confidence items in updated confidence map
- Full action list presented to user with row counts, before/after examples, reasoning
- User approval gates the execution (no changes without explicit approval)
- Transformation executor applies approved actions
- Full audit log written: column, original_value, new_value, rule_applied, approved_by, approved_at
- Quality score recomputed after execution

**Iteration 4 — Ambiguous resolution:**
- AI retrieves all MEDIUM/LOW confidence issues still unresolved
- For each: generates a prompt with the issue, example row, options, and downstream impacts
- User selects option or types instruction
- Transformation executor applies with audit trail
- Quality score recomputed after each resolution (live feedback to user)

**Iteration 5 — Cross-column validation:**
- Cross-column rule engine runs on the fully cleaned dataset
- Correlation analysis across pairs of semantically related columns
- Logic validation across column triplets (total = component_a + component_b)
- Business rule violations surfaced as new findings
- Findings presented in chat with business context (not just "anomaly detected")
- User decides: flag, escalate, or accept as known pattern

---

### What the LLM Does in Each Iteration

| Iteration | LLM role | Deterministic role |
|---|---|---|
| 1 | Semantic type inference, confidence scoring, human-readable summaries | Statistical computation, null rates, duplicate detection, range checks |
| 2 | Question generation, answer parsing, context reclassification | None |
| 3 | Action plan generation, explanation of each action | Transformation execution, audit logging |
| 4 | Option generation, impact explanation, free-form instruction parsing | Transformation execution per user decision |
| 5 | Business context for cross-column findings, escalation recommendations | Correlation computation, logic validation |

**LLM is called at:** Iteration 1 end (summaries), Iteration 2 (full conversation), Iteration 3 start (plan), Iteration 4 per-issue (options), Iteration 5 end (findings narrative)

**LLM is NOT called for:** Statistical computation, transformation execution, audit logging, score calculation, duplicate detection, null counting

**Cost model:** LLM is called O(issues) times across the full 5-iteration flow, not O(rows). For a 500-column table with 30 detected issues, total LLM calls ≈ 40-60 across all 5 iterations. Cost per table profiled and cleaned: ~$0.15-0.40 depending on table complexity.
