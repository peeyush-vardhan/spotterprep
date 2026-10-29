import numpy as np
import pandas as pd

from spotterprep.iteration1_confidence import score_issues


def _types(result, column=None):
    return {i["issue_type"] for i in result["issues"] if column is None or column in i["column"]}


def _orders(n=2_000, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "order_id": [f"ORD-{i:05d}" for i in range(n)],
        "status": pd.array(rng.choice(["Shipped", "Pending"], n), dtype="str"),
        "email": pd.array([f"user{i}@example.com" for i in range(n)], dtype="str"),
        "total_amount": rng.uniform(10, 1_000, n),
        "onboarding_date": pd.Timestamp("2024-01-01") + pd.to_timedelta(rng.integers(0, 100, n), unit="D"),
        "go_live_date": pd.Timestamp("2024-06-01") + pd.to_timedelta(rng.integers(0, 100, n), unit="D"),
    })


def test_text_checks_run_on_pandas3_string_dtype():
    df = _orders()
    df.loc[5, "status"] = "SHIPPED"
    df.loc[6, "email"] = "not-an-email"
    r = score_issues(df, "CUSTOMER_ORDERS")
    assert "CATEGORICAL_INCONSISTENCY" in _types(r, "status")
    assert "MALFORMED_EMAIL" in _types(r, "email")


def test_duplicates_appended_at_the_end_are_found_beyond_the_sample():
    df = _orders(30_000)
    df = pd.concat([df, df.tail(50)], ignore_index=True)
    r = score_issues(df, "CUSTOMER_ORDERS", sample_rows=1_000)
    dup = [i for i in r["issues"] if i["issue_type"] == "DUPLICATE_PK"]
    assert dup and dup[0]["count"] == 100


def test_composite_key_used_for_iot():
    df = pd.DataFrame({"device_id": ["D1", "D1", "D2"],
                       "reading_timestamp": ["2025-01-01 00:00", "2025-01-01 00:05", "2025-01-01 00:00"],
                       "ingestion_timestamp": ["2025-01-01 00:01", "2025-01-01 00:06", "2025-01-01 00:01"]})
    r = score_issues(df, "IOT_TELEMETRY")
    assert r["pk_column"] == "device_id+reading_timestamp"
    assert "DUPLICATE_PK" not in _types(r)


def test_impossible_temporal_pair_detected():
    df = _orders()
    df.loc[:9, "onboarding_date"] = pd.Timestamp("2030-01-01")
    r = score_issues(df, "CUSTOMER_ORDERS")
    assert any(i["issue_type"] == "IMPOSSIBLE_TEMPORAL" and i["count"] >= 10 for i in r["issues"])


def test_signed_column_negatives_are_not_flagged():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"order_id": range(1_000), "temp_delta": rng.normal(0, 5, 1_000)})
    assert "NEGATIVE_NUMERIC" not in _types(score_issues(df, "X"), "temp_delta")


def test_rare_negatives_in_non_negative_column_are_flagged():
    df = pd.DataFrame({"order_id": range(1_000), "quantity": np.arange(1_000, dtype=float)})
    df.loc[:4, "quantity"] = -1
    assert "NEGATIVE_NUMERIC" in _types(score_issues(df, "X"), "quantity")


def test_monetary_issues_are_low_confidence():
    df = _orders()
    df.loc[:4, "total_amount"] = -50.0
    df.loc[10:14, "total_amount"] = np.nan
    levels = {i["issue_type"]: i["confidence_level"] for i in score_issues(df, "CUSTOMER_ORDERS")["issues"]
              if i["column"] == "total_amount"}
    assert levels == {"NEGATIVE_MONETARY": "LOW", "NULL_MONETARY": "LOW"}


def test_percentage_out_of_bounds_detected():
    df = pd.DataFrame({"order_id": range(500), "efficiency_pct": np.linspace(60, 95, 500)})
    df.loc[:2, "efficiency_pct"] = 130.0
    assert "PHYSICAL_RANGE_VIOLATION" in _types(score_issues(df, "X"), "efficiency_pct")


def test_future_dates_relative_to_today():
    df = _orders()
    df["order_date"] = pd.Timestamp.now().normalize() - pd.Timedelta(days=30)
    df.loc[:2, "order_date"] = pd.Timestamp.now().normalize() + pd.Timedelta(days=30)
    assert "FUTURE_DATE" in _types(score_issues(df, "CUSTOMER_ORDERS"), "order_date")
