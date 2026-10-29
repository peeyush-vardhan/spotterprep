"""
audit_logger.py — SpotterPrep Audit Logger
==========================================
Records every transformation applied during the 5-iteration cleaning model.

Each log entry captures:
  - Which iteration produced the action (1–5)
  - The rule applied and column(s) affected
  - Original and new values (for single-row changes)
  - Confidence score and level from the confidence map
  - Approval metadata: who approved, when, via which mechanism

Log format: JSONL (one JSON object per line) — append-friendly, grep-able,
importable into Snowflake or any analytics tool.

Default log path: data/audit_<table_name>.jsonl

Usage:
  from spotterprep.audit_logger import AuditLogger

  logger = AuditLogger(table_name="CUSTOMER_ORDERS")

  # Iteration 3 — high-confidence fix, approved by user
  logger.log_transformation(
      iteration=3,
      column="order_id",
      rule_applied="DEDUPLICATE_PK",
      action="DELETE_ROW",
      rows_affected=300,
      confidence_score=0.99,
      confidence_level="HIGH",
      approved_by="analyst@company.com",
  )

  # Iteration 5 — cross-column finding, AI-triggered
  logger.log_finding(
      iteration=5,
      finding_type="STALE_ML_LABELS",
      columns_involved=["churn_risk", "health_score"],
      rows_affected=234,
      business_context="churn_risk='low' but health_score < 20 — ML model labels may be stale",
  )

  logger.summary()
"""

import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Iteration metadata ─────────────────────────────────────────────────────

ITERATION_LABELS: dict[int, str] = {
    1: "STRUCTURAL_SCAN",
    2: "CONTEXT_CONVERSATION",
    3: "HIGH_CONFIDENCE_FIXES",
    4: "AMBIGUOUS_RESOLUTION",
    5: "CROSS_COLUMN_VALIDATION",
}

# How approval is granted in each iteration — baked into every log entry
# so the audit trail is self-documenting without requiring external context.
APPROVAL_MECHANISMS: dict[int, str] = {
    1: "automatic",           # AI-triggered diagnostic — no user action, nothing changes
    2: "user_conversation",   # User answered AI's question in chat interface
    3: "user_approved",       # User explicitly approved the full action list
    4: "user_decision",       # User selected one option from AI's ambiguity menu
    5: "automatic",           # AI-triggered post-cleaning validation
}

DEFAULT_LOG_DIR = Path(__file__).parent.parent / "data"


# ── AuditLogger ───────────────────────────────────────────────────────────

class AuditLogger:
    """
    Append-only audit log for all SpotterPrep transformations.

    One instance per table being cleaned. Thread-safe for single-process use
    (each write opens, appends, and closes the file atomically).

    Every entry written includes session_id so a single JSONL file can
    accumulate records from multiple cleaning sessions and still be filtered
    to one session for review.
    """

    def __init__(
        self,
        table_name: str,
        session_id: Optional[str] = None,
        log_dir: Optional[Path] = None,
    ):
        self.table_name = table_name.upper()
        self.session_id = session_id or _generate_session_id()
        log_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = log_dir / f"audit_{self.table_name.lower()}.jsonl"
        self._entry_count = 0
        print(f"  [AuditLogger] {self.table_name}  session={self.session_id}  "
              f"log={self.log_path}")

    # ── Core write ────────────────────────────────────────────────────────

    def log_transformation(
        self,
        iteration: int,
        column: str,
        rule_applied: str,
        action: str,
        rows_affected: int,
        confidence_score: float,
        confidence_level: str,
        approved_by: Optional[str] = None,
        approved_at: Optional[str] = None,
        original_value: Optional[str] = None,
        new_value: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> dict:
        """
        Write one transformation entry to the audit log.

        Parameters
        ----------
        iteration : int
            Which iteration produced this action (1–5).
        column : str
            Column(s) affected. Use "col_a + col_b" for multi-column rules
            and "col_a > col_b" for temporal sequence rules.
        rule_applied : str
            Rule identifier, matching IssueType constants in confidence_scorer.py
            (e.g. "DEDUPLICATE_PK", "NULLIFY_MALFORMED_EMAIL", "TRIM_WHITESPACE").
        action : str
            What was done: "DELETE_ROW", "SET_VALUE", "FLAG", "IMPUTE",
            "STANDARDIZE", "RECOMPUTE", "NULLIFY", "PRESERVE".
        rows_affected : int
            Number of rows changed or flagged.
        confidence_score : float
            Score from the confidence map (0.0–1.0).
        confidence_level : str
            "HIGH", "MEDIUM", or "LOW".
        approved_by : str, optional
            User ID / email, or "system" for automatic iterations (1, 5).
            Required for iterations 3 and 4; defaults to "system" for 1 and 5.
        approved_at : str, optional
            ISO 8601 UTC timestamp of approval. Defaults to now.
        original_value : str, optional
            Representative original value (useful for single-value fixes).
        new_value : str, optional
            Replacement value after transformation.
        detail : str, optional
            Free-text rationale for this specific action.

        Returns
        -------
        dict
            The log entry exactly as written to disk.
        """
        if iteration not in ITERATION_LABELS:
            raise ValueError(f"iteration must be 1–5, got {iteration!r}")
        if confidence_level not in ("HIGH", "MEDIUM", "LOW"):
            raise ValueError(f"confidence_level must be HIGH/MEDIUM/LOW, got {confidence_level!r}")

        now = datetime.now(timezone.utc).isoformat()

        # Iterations 1 and 5 are automatic; iterations 3/4 require a human approver.
        if approved_by is None:
            approved_by = "system" if iteration in (1, 5) else None

        entry = {
            "timestamp":          now,
            "session_id":         self.session_id,
            "table_name":         self.table_name,
            "iteration":          iteration,
            "iteration_label":    ITERATION_LABELS[iteration],
            "column":             column,
            "rule_applied":       rule_applied,
            "action":             action,
            "rows_affected":      int(rows_affected),
            "confidence_score":   round(float(confidence_score), 4),
            "confidence_level":   confidence_level,
            "approval_mechanism": APPROVAL_MECHANISMS[iteration],
            "approved_by":        approved_by,
            "approved_at":        approved_at or now,
            "original_value":     str(original_value) if original_value is not None else None,
            "new_value":          str(new_value) if new_value is not None else None,
            "detail":             detail,
        }

        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

        self._entry_count += 1
        return entry

    # ── Batch write ───────────────────────────────────────────────────────

    def log_batch(self, entries: list[dict]) -> list[dict]:
        """
        Write multiple transformation entries in one call.

        Each dict in `entries` must contain the keyword arguments accepted
        by log_transformation(). Useful for writing all Iteration 3 actions
        at once after the user approves the full action list.
        """
        written = []
        for kwargs in entries:
            written.append(self.log_transformation(**kwargs))
        return written

    # ── Cross-column finding convenience ──────────────────────────────────

    def log_finding(
        self,
        iteration: int,
        finding_type: str,
        columns_involved: list[str],
        rows_affected: int,
        business_context: str,
        action: str = "FLAGGED",
        approved_by: Optional[str] = None,
    ) -> dict:
        """
        Convenience method for Iteration 5 cross-column findings.

        Cross-column findings span multiple columns and represent business
        intelligence, not just data quality fixes. They are always AI-triggered
        (confidence_level="HIGH") because they emerge from correlation, not
        from a pre-specified rule.

        Parameters
        ----------
        finding_type : str
            Short identifier for the finding, e.g. "STALE_ML_LABELS",
            "BEARING_FAILURE_SIGNAL", "RETENTION_RISK", "ACCRUAL_NO_REVERSAL",
            "GREY_MARKET_ARBITRAGE".
        columns_involved : list[str]
            All columns that participate in the finding.
        rows_affected : int
            Number of rows exhibiting this cross-column pattern.
        business_context : str
            Human-readable explanation of the finding and its business implication.
        action : str
            What was done with the finding: "FLAGGED", "ESCALATED", "ACCEPTED".
        approved_by : str, optional
            Defaults to "system" (Iteration 5 is AI-triggered).
        """
        return self.log_transformation(
            iteration=iteration,
            column=" + ".join(columns_involved),
            rule_applied=f"CROSS_COLUMN_{finding_type.upper()}",
            action=action,
            rows_affected=rows_affected,
            confidence_score=0.85,   # cross-column findings use correlation, not thresholds
            confidence_level="HIGH",
            approved_by=approved_by or "system",
            detail=business_context,
        )

    # ── Read / query ──────────────────────────────────────────────────────

    def read_log(
        self,
        iteration: Optional[int] = None,
        confidence_level: Optional[str] = None,
        session_only: bool = True,
    ) -> list[dict]:
        """
        Read entries from the log file with optional filters.

        Parameters
        ----------
        iteration : int, optional
            Return only entries from this iteration.
        confidence_level : str, optional
            Return only "HIGH", "MEDIUM", or "LOW" entries.
        session_only : bool
            If True (default), return only entries from the current session.
            Set False to see all sessions in the log file.

        Returns
        -------
        list[dict]
            Matching log entries in chronological order.
        """
        if not self.log_path.exists():
            return []

        entries = []
        with open(self.log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if session_only and entry.get("session_id") != self.session_id:
                    continue
                if iteration is not None and entry.get("iteration") != iteration:
                    continue
                if confidence_level is not None and entry.get("confidence_level") != confidence_level:
                    continue
                entries.append(entry)
        return entries

    # ── Summary ───────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """
        Print and return a summary of all transformations in this session,
        broken down by iteration and confidence level.

        Returns
        -------
        dict
            {session_id, table_name, total_entries, total_rows_affected,
             by_iteration, by_confidence}
        """
        entries = self.read_log(session_only=True)

        by_iteration: dict[str, dict] = {}
        by_confidence: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        total_rows = 0

        for e in entries:
            label = f"Iter {e['iteration']} — {e['iteration_label']}"
            by_iteration.setdefault(label, {"count": 0, "rows_affected": 0})
            by_iteration[label]["count"] += 1
            by_iteration[label]["rows_affected"] += e.get("rows_affected", 0)
            by_confidence[e.get("confidence_level", "MEDIUM")] += 1
            total_rows += e.get("rows_affected", 0)

        print(f"\n{'='*65}")
        print(f"  Audit Summary — {self.table_name}")
        print(f"  Session: {self.session_id}")
        print(f"{'='*65}")
        print(f"  Total transformations : {len(entries)}")
        print(f"  Total rows affected   : {total_rows:,}")
        print()
        for label, stats in sorted(by_iteration.items()):
            print(f"  {label}")
            print(f"    {stats['count']} rules  ·  {stats['rows_affected']:,} rows affected")
        print()
        print(f"  By confidence: "
              f"HIGH={by_confidence['HIGH']}  "
              f"MEDIUM={by_confidence['MEDIUM']}  "
              f"LOW={by_confidence['LOW']}")
        print()

        return {
            "session_id":          self.session_id,
            "table_name":          self.table_name,
            "total_entries":       len(entries),
            "total_rows_affected": total_rows,
            "by_iteration":        by_iteration,
            "by_confidence":       by_confidence,
        }

    def __repr__(self) -> str:
        return (f"AuditLogger(table={self.table_name}, "
                f"session={self.session_id}, "
                f"entries_this_run={self._entry_count})")


# ── Helpers ────────────────────────────────────────────────────────────────

def _generate_session_id() -> str:
    ts     = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = f"{random.randint(0, 9999):04d}"
    return f"SPP-{ts}-{suffix}"


def load_audit_log(log_path: str) -> list[dict]:
    """
    Load a full audit JSONL file into a list of dicts without instantiating
    an AuditLogger — useful for ad-hoc analysis or Snowflake ingestion.
    """
    entries = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries
