from conftest import FakeAnthropic, tool_response
from evals.llm_eval import load_cases, run
from spotterprep.llm import LLMClient, required_level


def test_labeled_cases_are_well_formed():
    cases = load_cases()
    assert len(cases) >= 20 and len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert c["expected"]["recommended_actions"] and "confidence_levels" not in c["expected"]


def test_oracle_model_scores_perfectly_and_unsafe_model_is_contained():
    cases = load_cases()
    oracle = [tool_response({"confidence_level": required_level(c["issue"], c["expected"]["recommended_actions"][0]),
                             "recommended_action": c["expected"]["recommended_actions"][0],
                             "context_note": "label"}) for c in cases]
    r = run(LLMClient(client=FakeAnthropic(oracle), log_path=None), cases)
    assert r["model_level_follows_definition"] == r["action_accuracy"] == r["valid_output_rate"] == 1.0

    reckless = [tool_response({"confidence_level": "HIGH", "recommended_action": "IMPUTE_MEDIAN",
                               "context_note": "impute everything"}) for _ in cases]
    r = run(LLMClient(client=FakeAnthropic(reckless), log_path=None), cases)
    assert r["unsafe_final_actions"] == 0 and r["guardrail_overrides"] == r["protected_calls"] > 0


def test_level_mismatch_is_corrected_and_counted():
    cases = [c for c in load_cases() if c["id"] == "neg_amount_refunds"]
    wrong = [tool_response({"confidence_level": "HIGH", "recommended_action": "CONVERT_TO_REFUND", "context_note": "x"})]
    r = run(LLMClient(client=FakeAnthropic(wrong), log_path=None), cases)
    assert r["action_accuracy"] == 1.0 and r["model_level_follows_definition"] == 0.0
    assert r["final_level_follows_definition"] == 1.0 and r["level_corrections"] == 1
