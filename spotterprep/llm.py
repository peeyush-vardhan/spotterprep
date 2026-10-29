"""
spotterprep/llm.py — The only place SpotterPrep talks to an LLM.

Iteration 2 makes two kinds of call: generate one question about an issue, and turn the
analyst's answer into a reclassification. The second one changes what the pipeline does
next, so it is treated as an untrusted output and checked in code:

  1. Structured output.  The model must call a tool whose input schema fixes the fields
     and enumerates the allowed confidence levels and actions. No free-text JSON parsing.
  2. Validation.         The tool input is validated again in Python. A response that
     fails is retried; if it still fails, the issue stays as it was and the failure is
     recorded, never silently swallowed.
  3. Guardrails.         Rules that must never depend on the model are enforced after the
     call: monetary and personal-data columns are never imputed, whatever the model says.
  4. Determinism.        temperature=0 and a pinned, configurable model.
  5. Resilience.         Transient API errors are retried with exponential backoff.
  6. Audit.              Every call is appended to a JSONL log (sanitised prompt, raw
                         response, model, latency, attempts, validation outcome).

The model never sees raw PII or monetary values: prompts are built from sanitise_issue(),
which redacts by column name and by scanning the values themselves.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

DEFAULT_MODEL = os.environ.get("SPOTTERPREP_MODEL", "claude-sonnet-4-6")
DEFAULT_LOG = Path(os.environ.get("SPOTTERPREP_LLM_LOG", "logs/llm_calls.jsonl"))

CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW")
ACTIONS = (
    "DEDUPLICATE_KEEP_FIRST", "FLAG_NULL_MONETARY", "PRESERVE_NULL", "ESCALATE_TO_USER",
    "IMPUTE_MEDIAN", "IMPUTE_MODE", "SET_ZERO_OR_ABS", "NULLIFY_MALFORMED", "FLAG_SCHEDULED",
    "DELETE_ROW", "STANDARDIZE_AFTER_CANONICAL_CONFIRMED", "FLAG_OUTLIER_REVIEW",
    "COERCE_TO_DOMINANT_TYPE", "TRIM_WHITESPACE", "FLAG_AND_PRESERVE", "CONVERT_TO_REFUND",
)
_IMPUTE_ACTIONS = {"IMPUTE_MEDIAN", "IMPUTE_MODE"}

RECLASSIFY_TOOL = {
    "name": "record_reclassification",
    "description": "Record the updated confidence classification for one data quality issue, "
                   "based on the analyst's answer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "confidence_level": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
            "recommended_action": {"type": "string", "enum": list(ACTIONS)},
            "context_note": {"type": "string", "description": "One sentence: what changed and why."},
        },
        "required": ["confidence_level", "recommended_action", "context_note"],
        "additionalProperties": False,
    },
}

# ── PII and monetary sanitisation ──────────────────────────────────────────
# See docs/06_pii_policy.md. Column-name rules catch the obvious columns; value rules catch
# personal data sitting in a column whose name gives no hint (e.g. `notes`, `contact`).

_REDACT_ISSUE_TYPES = {"NULL_PII", "NULL_MONETARY", "NEGATIVE_MONETARY"}
_MONETARY_COL = re.compile(r"amount|price|revenue|cost|salary|pay|fee|charge|balance|debit|credit"
                           r"|(?:^|_)(?:arr|mrr|ltv|cac)(?:_|$)", re.I)
_PII_COL = re.compile(r"(?:^|_)(?:name|email|phone|address|ssn|dob|birth|passport)(?:_|$)"
                      r"|account.?number|employee.?id|patient.?id|ip.?address", re.I)
_PII_VALUE = [
    re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}"),                       # email address
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                                 # US SSN
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),                                # card or account number
    re.compile(r"(?:\+\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}"),  # phone number
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),                           # IPv4 address
]
REDACTED = "[redacted]"


def is_protected_column(column: str) -> bool:
    """Monetary or personal-data column: never imputed, values never sent to the LLM."""
    return bool(_MONETARY_COL.search(column) or _PII_COL.search(column))


def _value_has_pii(value: Any) -> bool:
    text = str(value)
    return any(p.search(text) for p in _PII_VALUE)


def sanitise_issue(issue: dict) -> dict:
    """Copy of the issue that is safe to put in a prompt. The original is never modified."""
    safe = dict(issue)
    examples = list(issue.get("example_values") or [])
    if issue.get("issue_type") in _REDACT_ISSUE_TYPES or is_protected_column(str(issue.get("column", ""))):
        safe["example_values"] = [f"{REDACTED}: PII or monetary column"] if examples else []
    else:
        safe["example_values"] = [REDACTED if _value_has_pii(v) else v for v in examples]
    return safe


# ── Validation and guardrails ──────────────────────────────────────────────

class ValidationError(ValueError):
    pass


def validate_reclassification(data: Any) -> dict:
    """Return a clean reclassification dict or raise ValidationError."""
    if not isinstance(data, dict):
        raise ValidationError(f"expected an object, got {type(data).__name__}")
    extra = set(data) - {"confidence_level", "recommended_action", "context_note"}
    if extra:
        raise ValidationError(f"unexpected fields: {sorted(extra)}")
    level, action, note = data.get("confidence_level"), data.get("recommended_action"), data.get("context_note")
    if level not in CONFIDENCE_LEVELS:
        raise ValidationError(f"confidence_level {level!r} not in {CONFIDENCE_LEVELS}")
    if action not in ACTIONS:
        raise ValidationError(f"recommended_action {action!r} is not an allowed action")
    if not isinstance(note, str) or not note.strip():
        raise ValidationError("context_note must be a non-empty string")
    return {"confidence_level": level, "recommended_action": action, "context_note": note.strip()[:500]}


def apply_guardrails(issue: dict, update: dict) -> dict:
    """Enforce the never-do rules in code. Returns a new dict; notes any override."""
    out = dict(update)
    protected = issue.get("issue_type") in _REDACT_ISSUE_TYPES or is_protected_column(str(issue.get("column", "")))
    if protected and out["recommended_action"] in _IMPUTE_ACTIONS:
        out["recommended_action"] = "FLAG_AND_PRESERVE"
        out["confidence_level"] = "LOW"
        out["guardrail"] = "imputation blocked on a monetary or personal-data column"
    return out


# ── Client ─────────────────────────────────────────────────────────────────

_SYSTEM_QUESTION = """\
You are SpotterPrep, an AI data preparation assistant embedded in a data workspace.
Your job: ask ONE targeted question about a data quality issue so the analyst can give
you the business context you need to decide what to do.

Rules:
- Ask exactly one question. No follow-ups in the same message.
- Reference a real value from the example values provided; never ask about abstract
  statistics like "14.9% null". Ask about a specific case. If the values are redacted,
  ask about the pattern without quoting values.
- Be concise: 2-3 sentences maximum.
- Do not propose any fix yet. Only ask.
- Start the question directly, with no preamble."""

_SYSTEM_RECLASSIFY = """\
You are SpotterPrep, an AI data preparation assistant.
An analyst has answered a question about a data quality issue. Record the updated
classification by calling the record_reclassification tool.

Guidance:
- Nulls the analyst says are legitimate (contractors, opt-outs, pending orders):
  confidence_level LOW, recommended_action PRESERVE_NULL.
- The analyst confirms the values are errors: raise confidence_level to HIGH and choose
  the action that fixes this issue type.
- Negative monetary values the analyst confirms are refunds: CONVERT_TO_REFUND.
- Monetary or personal-data columns are never imputed.
- Still ambiguous after the answer, or the answer is off-topic: keep MEDIUM,
  recommended_action ESCALATE_TO_USER."""


def _issue_block(table: str, safe: dict) -> str:
    return (f"Table: {table}\nColumn: {safe['column']}\nIssue type: {safe['issue_type']}\n"
            f"Rows affected: {safe['count']:,} ({safe['pct']:.1%} of table)\n"
            f"Issue detail: {safe['detail']}\nExample values: {safe.get('example_values', [])}\n"
            f"Current confidence level: {safe['confidence_level']}\n"
            f"Current recommended action: {safe['recommended_action']}")


@dataclass
class LLMClient:
    """Thin wrapper over the Anthropic Messages API with retries, validation and logging.

    `client` is anything with a `.messages.create(**kwargs)` method, so tests and evals can
    pass a fake without network access.
    """
    client: Any
    model: str = DEFAULT_MODEL
    temperature: float = 0.0
    max_retries: int = 3
    backoff_seconds: float = 1.0
    log_path: Optional[Path] = DEFAULT_LOG
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)

    # -- transport ---------------------------------------------------------
    def _create(self, purpose: str, **kwargs) -> Any:
        kwargs = {"model": self.model, "temperature": self.temperature, **kwargs}
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            started = time.monotonic()
            try:
                resp = self.client.messages.create(**kwargs)
                self._log(purpose, kwargs, resp, attempt, time.monotonic() - started, None)
                return resp
            except Exception as err:  # noqa: BLE001  (SDK error classes vary by version)
                last_err = err
                self._log(purpose, kwargs, None, attempt, time.monotonic() - started, repr(err))
                if not _is_retryable(err) or attempt == self.max_retries:
                    raise
                self.sleep(self.backoff_seconds * 2 ** (attempt - 1))
        raise RuntimeError("unreachable") from last_err

    def _log(self, purpose, request, resp, attempt, latency, error, **extra) -> None:
        if not self.log_path:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(), "purpose": purpose, "model": request.get("model"),
            "temperature": request.get("temperature"), "attempt": attempt, "latency_s": round(latency, 3),
            "system": request.get("system"), "messages": request.get("messages"),
            "response": _response_payload(resp), "error": error, **extra,
        }
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except OSError:
            pass  # logging must never break the conversation

    # -- calls ---------------------------------------------------------------
    def generate_question(self, issue: dict, table: str) -> str:
        safe = sanitise_issue(issue)
        resp = self._create(
            "generate_question", max_tokens=200, system=_SYSTEM_QUESTION,
            messages=[{"role": "user", "content": _issue_block(table, safe)
                       + "\n\nAsk one targeted question to understand the business context for this issue."}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text").strip()
        return text or f"Can you tell me more about the {issue['issue_type'].lower()} values in {issue['column']}?"

    def reclassify(self, issue: dict, question: str, answer: str, table: str) -> dict:
        """Return a validated, guard-railed update. Never raises on bad model output."""
        safe = sanitise_issue(issue)
        messages = [{"role": "user", "content": _issue_block(table, safe)
                     + f"\n\nQuestion that was asked: {question}\nAnalyst's answer: {answer}"}]
        errors: list[str] = []
        for _ in range(2):  # one retry on invalid output, with the error fed back
            resp = self._create(
                "reclassify", max_tokens=300, system=_SYSTEM_RECLASSIFY, messages=messages,
                tools=[RECLASSIFY_TOOL], tool_choice={"type": "tool", "name": RECLASSIFY_TOOL["name"]},
            )
            tool_input = _tool_input(resp, RECLASSIFY_TOOL["name"])
            try:
                update = validate_reclassification(tool_input)
                return {**apply_guardrails(issue, update), "valid": True,
                        "reclassified": update["confidence_level"] != issue["confidence_level"]}
            except ValidationError as err:
                errors.append(str(err))
                messages = messages + [
                    {"role": "assistant", "content": resp.content},
                    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": _tool_use_id(resp),
                                                  "is_error": True, "content": f"Invalid: {err}. Call the tool again."}]},
                ] if _tool_use_id(resp) else messages
        return {
            "confidence_level": issue["confidence_level"], "recommended_action": issue["recommended_action"],
            "context_note": f"Model output failed validation; issue left unchanged. Analyst said: {answer}",
            "valid": False, "validation_errors": errors, "reclassified": False,
        }


def _is_retryable(err: Exception) -> bool:
    status = getattr(err, "status_code", None)
    if status is not None:
        return status == 429 or status >= 500
    return type(err).__name__ in {"APIConnectionError", "APITimeoutError", "RateLimitError",
                                  "InternalServerError", "OverloadedError", "TimeoutError", "ConnectionError"}


def _tool_input(resp: Any, name: str) -> Any:
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == name:
            return getattr(block, "input", None)
    return None


def _tool_use_id(resp: Any) -> Optional[str]:
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "tool_use":
            return getattr(block, "id", None)
    return None


def _response_payload(resp: Any) -> Any:
    if resp is None:
        return None
    if hasattr(resp, "model_dump"):
        try:
            return resp.model_dump()
        except Exception:  # noqa: BLE001
            pass
    return [{"type": getattr(b, "type", None), "text": getattr(b, "text", None), "input": getattr(b, "input", None)}
            for b in getattr(resp, "content", []) or []]


def make_client(model: str = DEFAULT_MODEL, **kwargs) -> LLMClient:
    import anthropic  # imported here so the rest of the package works without the SDK installed
    return LLMClient(client=anthropic.Anthropic(), model=model, **kwargs)
