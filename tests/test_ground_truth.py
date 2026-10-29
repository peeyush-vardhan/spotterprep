import pytest

from evals.ground_truth import classify, resolve_columns


@pytest.mark.parametrize("name, family, scope", [
    ("duplicate_pk", "DUPLICATE", "detector"),
    ("orphaned_foreign_key", "ORPHAN_FK", "out_of_scope"),
    ("approval_before_posting", "IMPOSSIBLE_TEMPORAL", "detector"),
    ("negative_price", "NEGATIVE_MONETARY", "detector"),
    ("negative_stock", "NEGATIVE_NUMERIC", "detector"),
    ("physics_violation", "CROSS_COLUMN", "cross_column"),
    ("margin_oob", "OUT_OF_RANGE", "detector"),
])
def test_classify(name, family, scope):
    assert classify(name) == (family, scope)


def test_resolve_columns_handles_expressions_wildcards_and_suffixes():
    cols = ["onboarding_date", "go_live_date", "perf_rating_2023", "perf_rating_2024", "weight_kg", "weight_lbs"]
    assert resolve_columns("onboarding_date > go_live_date", cols) == ["onboarding_date", "go_live_date"]
    assert resolve_columns("perf_rating_*", cols) == ["perf_rating_2023", "perf_rating_2024"]
    assert set(resolve_columns("weight_kg/lbs", cols)) == {"weight_kg", "weight_lbs"}
    assert resolve_columns("15 sensor columns", cols) == []
