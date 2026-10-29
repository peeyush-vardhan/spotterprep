import numpy as np
import pandas as pd

from spotterprep.quality_scorer import compute_quality_score


def _base(n=1_000):
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "order_id": [f"O{i}" for i in range(n)],
        "status": pd.array(rng.choice(["Open", "Closed"], n), dtype="str"),
        "email": pd.array([f"u{i}@x.com" for i in range(n)], dtype="str"),
        "nps_delta": rng.normal(0, 3, n),
    })


def test_annotation_columns_do_not_lower_completeness():
    clean = _base()
    flagged = clean.assign(total_amount_flag=pd.array([None] * len(clean), dtype="str"))
    a = compute_quality_score(clean, "CUSTOMER_ORDERS")
    b = compute_quality_score(flagged, "CUSTOMER_ORDERS")
    assert a["dimensions"]["completeness"]["score"] == b["dimensions"]["completeness"]["score"]


def test_malformed_email_lowers_validity_on_string_dtype_with_nulls():
    df = _base()
    df.loc[:49, "email"] = "broken"
    df.loc[50:59, "email"] = None
    assert compute_quality_score(df, "CUSTOMER_ORDERS")["dimensions"]["validity"]["score"] < 100


def test_case_variants_lower_consistency_on_string_dtype():
    df = _base()
    df.loc[:49, "status"] = "OPEN"
    assert compute_quality_score(df, "CUSTOMER_ORDERS")["dimensions"]["consistency"]["score"] < 100


def test_signed_column_does_not_fail_validity():
    assert compute_quality_score(_base(), "CUSTOMER_ORDERS")["dimensions"]["validity"]["score"] == 100


def test_composite_primary_key_for_iot():
    df = pd.DataFrame({"device_id": ["D1", "D1", "D2", "D2"],
                       "reading_timestamp": ["t1", "t2", "t1", "t1"]})
    u = compute_quality_score(df, "IOT_TELEMETRY")["dimensions"]["uniqueness"]["score"]
    assert u == 50.0  # rows 3 and 4 share a key; rows 1 and 2 do not


def test_cleaning_never_scores_below_raw():
    raw = _base()
    raw.loc[:49, "status"] = "OPEN"
    raw.loc[50:79, "email"] = "broken"
    raw = pd.concat([raw, raw.head(20)], ignore_index=True)
    clean = raw.drop_duplicates("order_id").copy()
    clean["status"] = clean["status"].str.title()
    clean["email_flag"] = np.where(clean["email"].str.contains("@"), "", "MALFORMED")
    clean.loc[clean["email_flag"] != "", "email"] = None
    before, after = (compute_quality_score(d, "CUSTOMER_ORDERS")["overall_score"] for d in (raw, clean))
    assert after > before
