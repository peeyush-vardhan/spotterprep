# SpotterPrep — AI Interaction Design Brief

**Product:** SpotterPrep
**Author:** Peeyush Vardhan, Product Manager
**Document type:** AI Interaction Design Brief
**Status:** V1 — Prototype-validated
**Last updated:** March 2026

---

## What This Document Is

This is not a feature spec. It is a record of the design reasoning behind how SpotterPrep structures the relationship between a human analyst and an AI cleaning agent.

Every AI product makes implicit decisions about where the AI acts, where it asks, and where it refuses. Most of those decisions are never written down. This document makes them explicit — and explains why each one was made.

The prototype at `prototype/index.html` is the interactive expression of these decisions. This document is the reasoning behind what you see there.

---

## 1. The Problem, Stated Precisely

The surface problem is familiar: enterprise data is dirty, and analysts spend most of their time cleaning it before asking a single question.

The deeper problem is less discussed: **an AI that queries dirty data gives confident, wrong answers.** ThoughtSpot's Spotter doesn't say "this data may be unreliable." It answers. If `order_amount` has 14.9% nulls and `customer_name` has 14.9% nulls, Spotter's average revenue calculation is structurally incorrect — and the analyst has no way to know.

The consequence is not a bad query result the analyst can identify and fix. It is a trusted wrong answer that propagates into decisions.

SpotterPrep exists to close that gap. But the design problem is not "how do we clean data." It is: **how do we clean data in a way that an enterprise analyst trusts enough to stake their reputation on the output.**

That distinction is the reason for everything that follows.

---

## 2. The Product Thesis

**The wrong approach:** Build a cleaning agent that profiles a table, applies a decision tree, and returns a clean dataset. Fast, scalable, automatable.

**Why it's wrong:** An analyst who receives a cleaned dataset from an AI they don't understand will not trust it. They will manually verify it. That verification costs more time than cleaning it themselves. The AI has created work, not removed it.

**The right approach:** Build a cleaning agent that makes the analyst feel like *they* cleaned the data — with AI doing the computation. The analyst owns every non-trivial decision. The AI owns every deterministic one. The output carries the analyst's judgment, not just the AI's.

This sounds like a UX preference. It is actually a trust architecture. And it determines every interaction decision in the product.

---

## 3. The Human-AI Control Model

SpotterPrep uses a five-iteration sequence. The iterations are not pipeline stages. They are a **trust-building sequence** — each one is designed to earn the right to do the next one.

```
Iteration 1 — Structural Scan     AI acts alone. Zero changes made. Earns the right to ask.
Iteration 2 — Context Conversation    AI asks. Analyst answers. Earns the right to propose.
Iteration 3 — High-Confidence Fixes   AI proposes. Analyst approves. Earns the right to execute.
Iteration 4 — Ambiguous Resolution    Analyst decides. AI executes. Earns the right to validate.
Iteration 5 — Cross-Column Validation AI reports. Analyst judges. Session complete.
```

The two most important design decisions in this sequence:

**Decision 1: Iterations 1 and 2 produce zero data changes.**

This is counterintuitive. A product that does nothing for the first two interactions looks broken. The reason: the AI cannot make safe decisions on the most consequential issues without business context it does not have. If it acts before it has that context, it acts wrongly. Acting wrongly once destroys the trust required for the analyst to approve the larger actions in Iterations 3 and 4.

The score progression validates this. Customer Orders goes from 54.1 to 54.1 across Iterations 1 and 2 — no change. Then +18.7 points in Iteration 3. The zero-score iterations are not waste. They are what make the +18.7 possible.

**Decision 2: The approval model changes between Iterations 3 and 4.**

In Iteration 3, the AI proposes a complete action list and the analyst approves the batch. In Iteration 4, each ambiguous issue is presented individually and the analyst decides one at a time.

This is not a UX preference. It reflects a real difference in what is being resolved. Iteration 3 actions are deterministic — the analyst is verifying the AI's work. Iteration 4 actions require judgment — the analyst is making a business decision that the AI genuinely cannot make. Conflating these two types of decisions into a single interaction would obscure the difference between "reviewing AI output" and "making a call."

---

## 4. Where the AI Has Autonomy — and Where It Does Not

This is the most important section of the document. Most AI product failures happen because this was never written down.

### Full autonomy (AI acts without asking)

| Action | Reason |
|---|---|
| Statistical profiling of every column | Pure computation — no business judgment involved |
| Duplicate primary key detection | Mathematically deterministic, no interpretation required |
| Malformed email detection | Regex validation — correct answer is not ambiguous |
| Impossible temporal sequences | `hire_date > termination_date` is objectively impossible |
| Cross-column correlation computation | Mathematical, not interpretive |

### Conditional autonomy (AI acts after user approval)

| Action | Condition |
|---|---|
| Text standardisation to canonical form | Canonical form must be confirmed by user in Iteration 2 first |
| Statistical imputation (median/mean) | Column type must not be MONETARY or PII; user must not have flagged it in Iteration 2 |
| Physical range violation fixes | Physical bounds must be confirmed per sensor type in Iteration 2 |
| Deduplication | User must approve the full action list in Iteration 3 |

### Zero autonomy (AI never acts, regardless of confidence)

| Action | Reason |
|---|---|
| MONETARY null resolution | Fabricating or imputing revenue figures is an accounting integrity violation, not a data quality fix |
| PII null resolution | Personal data cannot be fabricated under any circumstances |
| Physics violations on sensor data | A temperature or pressure reading that violates physical law is a real fault event — not a data error. Correcting it would destroy evidence of equipment failure |
| Accounting imbalances (SOX-relevant) | `SUM(debit) ≠ SUM(credit)` requires finance review and audit documentation. An AI that auto-resolves this is creating compliance exposure |
| Any column the analyst marked "ask me first" in Iteration 2 | Explicit instruction overrides confidence threshold. This is not a soft preference — it is a hard veto |

**The principle behind these exclusions:**

The zero-autonomy list is not about the AI's capability. In several cases, the AI has high confidence about what the correct action is. The exclusions exist because the *consequence of being wrong* is categorically different from the consequence of being wrong on a text standardisation fix. One wrong decision on `order_amount` nulls affects every revenue figure downstream. One wrong decision on a bonus_target imputation fabricates compensation records for 120,000 employees.

The AI's confidence is not the right threshold for autonomy. **The right threshold is: what is the worst-case outcome if this action is wrong?**

---

## 5. UX Decisions and Why

### Why conversational, not form-based

The alternative to a chat interface for Iteration 2 is a structured form: "For each detected issue, select from the following options." This would be faster to build and more predictable to test.

It would also fail. The questions the AI needs to ask depend entirely on what the scan found — and the scan finds different things in every table. A fixed form cannot accommodate that. More importantly, the analyst needs to see a real example row alongside each question. "14.9% null customer_name" is a statistic. "Order ORD-00042 from Acme Corp, placed 2024-03-12, has no customer name recorded — is this expected?" is a question a human can actually answer.

The conversational format forces the AI to ask concrete questions about concrete data. That concreteness is what makes the answers usable.

### Why the score is visible throughout

The quality score is displayed in real time and updates as each transformation executes. Iteration 4 shows the score moving after each individual user decision.

This is not a motivational design choice. It is feedback that makes the analyst's decisions legible to themselves. When an analyst decides that 5,000 zero vibration readings during "running" status are sensor failures (not valid readings), they see the score move. That movement confirms their decision had the consequence they expected. If the score doesn't move, something is wrong — either with their decision or with the system's execution of it.

Real-time score feedback is the cheapest form of trust building the system can provide.

### Why Iteration 5 produces findings, not actions

Cross-column validation finds things that are statistically invisible at the column level: 234 customer rows where `churn_risk = 'low'` but `health_score < 20` (stale ML labels), 12 accruals with no reversal in the following period ($2.3M balance sheet exposure), 8,200 products priced higher in the EU than the US after FX conversion (grey market arbitrage risk).

These are not data quality issues in the cleaning sense. They are business intelligence findings that emerge from the fully cleaned dataset. They cannot be auto-resolved because the AI does not know whether they represent errors, known patterns, or intentional business decisions.

The deliberate design choice: Iteration 5 gives the analyst *information*, not *actions*. The analyst decides what to do with each finding. This is the right boundary — the AI is at its best surfacing things humans wouldn't find; the human is at their best deciding what those things mean.

### Why the before/after table view is always available

During the cleaning conversation, the analyst can toggle between the raw table and the current cleaned state at any moment. This is not a nice-to-have. It is the primary mechanism by which the analyst verifies that the AI's actions produced what they expected.

An analyst who cannot see the data changing in response to their approvals is being asked to trust a system they cannot observe. That is not a reasonable ask. The before/after toggle makes every transformation observable.

---

## 6. What Was Deliberately Not Built

These were considered and rejected. The reasoning is as important as the features themselves.

**Automatic cleaning on connection.**
The first version of this product concept cleaned the table automatically on connection and showed the result. User research equivalent in this domain: analysts asked "what did you change?" — and then spent time verifying the output rather than using it. Automatic cleaning transfers the work from cleaning to auditing. The net time saved is near zero. The trust deficit is large.

**Confidence threshold as a user setting.**
"Let the analyst set the confidence threshold — if they want the AI to act on 70% confidence instead of 90%, let them." This sounds like analyst empowerment. It is actually analyst confusion. The analyst does not know what 70% confidence means for their specific data. They will set it to 70% and then discover the AI made wrong decisions. The confidence threshold is an internal implementation detail, not a user-facing control. The five-iteration structure is the user-facing control.

**Undo as a safety net.**
"Build undo — if the AI makes a wrong decision, the analyst can reverse it." Undo is not a substitute for a correct approval model. An analyst who has to undo an AI action has already lost trust in the system. The right design is to make wrong actions impossible, not recoverable.

**Cleaning without an audit trail.**
Every transformation must be logged with: column, original value, new value, rule applied, approved by, approved at timestamp. This is not optional for enterprise use. An analyst who uses SpotterPrep to clean data that feeds a board-level dashboard will eventually be asked "why does this number say X?" The audit log is the answer. A product without one is not deployable in the accounts that matter most.

---

## 7. The Confidence Map as Core Infrastructure

Every decision in the five-iteration model flows through a single data structure: the confidence map. It is written in Iteration 1, enriched in Iterations 2 through 4, and consumed by the Transformer layer for execution.

The confidence map is what makes it possible for the Transformer to execute without making decisions. The Transformer reads an approved action list from the confidence map and applies parameterized templates. It does not infer, interpret, or decide. The LLM wrote to the confidence map; the Transformer reads from it.

This separation is not an engineering preference. It is an auditability requirement. If a transformation produces an unexpected result, the audit trail points to a specific entry in the confidence map, which points to a specific user approval at a specific timestamp. The chain of accountability is complete.

The architecture consequence: **the LLM never touches the Transformer layer.** It classifies, narrates, questions, explains, and generates options. The Transformer executes. These responsibilities do not overlap, by design.

---

## 8. Success Metrics

Not sessions cleaned. Not rows processed. These would measure usage, not whether the product is doing what it is supposed to do.

| Metric | What it measures | Why it matters |
|---|---|---|
| Analyst approval rate on Iteration 3 action list | What % of AI-proposed actions does the analyst approve without modification? | A low approval rate means the AI is proposing actions the analyst doesn't trust. The problem is in Iteration 2, not Iteration 3. |
| Iteration 2 question count per table | How many context questions does the AI need to ask before Iteration 3? | More than 5 questions per table suggests the confidence classifier is under-confident. Fewer than 2 suggests it's overconfident. |
| Iteration 4 override rate | What % of Iteration 4 decisions result in the analyst choosing a non-default option? | High override rate means the AI's default options are wrong. |
| Audit trail completeness | % of transformed rows with full provenance (rule + approval + timestamp) | Must be 100%. Non-negotiable for enterprise compliance. |
| Post-cleaning Spotter query accuracy | Do Spotter answers on cleaned datasets match verified ground truth? | The ultimate outcome metric — SpotterPrep exists to make Spotter correct. |
| Time from connection to analyst approval of Iteration 3 | How long does the trust-building sequence take? | Target: under 15 minutes for a 100-column table. If this is too long, Iteration 2 question generation needs to be more precise. |

---

## 9. The Prototype as a Design Artifact

The interactive prototype at `prototype/index.html` is a single self-contained HTML file that simulates the full five-iteration cleaning flow for a CUSTOMER_ORDERS table.

It is not a UI mockup. It is a working demonstration of the interaction model — the timing of when the AI speaks, when it waits, when it shows buttons versus a text input, when the score moves, when the table updates. Every one of those choices reflects a decision documented above.

The prototype was built to answer a specific question: **does the trust-building sequence feel right at the interaction level, or does it feel like friction?**

The finding: the two zero-score iterations do not feel like waste when the AI explains clearly what it is doing and why it is not yet ready to act. The typing indicator, the scan summary language, and the explicit "I need to understand 3 things before I touch anything" framing convert what could feel like delay into what feels like diligence.

That framing is as much a product decision as the confidence threshold.

---

## 10. What Comes After This Prototype

The prototype validates the interaction model. What it does not validate:

- **LLM question quality at scale.** The Iteration 2 questions in the prototype are hand-authored. A production system generates them from the confidence map. The quality of those generated questions determines whether analysts can answer them precisely enough to usefully update the confidence map.

- **Confidence map accuracy on novel schemas.** The five datasets in the validation set were designed to exercise the confidence classifier. Production tables will have schemas the classifier has never seen. The HIGH/MEDIUM/LOW classification accuracy on novel data is the key unknown.

- **Enterprise approval workflows.** Some organisations will require a data steward to approve Iteration 3 actions, not the analyst who initiated the session. The current model has no multi-party approval. That is a known gap for regulated industries.

- **Context document generation for Spotter.** The current product ends at "cleaned dataset saved." The full vision includes generating column descriptions, suggested search terms, and anomaly alerts that Spotter can use to give better answers. That layer is not built.

These are the next problems. This document is the foundation they build on.

---

*SpotterPrep — built by Peeyush Vardhan, Product Manager, ThoughtSpot.*
*Prototype validated against 4.4M rows across 5 enterprise datasets. Average quality lift: 59.1 → 93.9.*
