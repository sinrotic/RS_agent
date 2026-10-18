"""漂移评测分母、拒绝效果与检查成本的独立回归。"""

import pytest

from rs_core.offline.evaluation.drift_evaluation import summarize_drift_reviews
from rs_core.offline.evaluation.skill_benchmark.execution_metrics import summarize_trace_usage

pytestmark = pytest.mark.unit


def test_unknown_and_missing_reviews_cannot_improve_the_reported_detection_rate():
    scenarios = [{"scenario_id": str(i), "expected": label} for i, label in enumerate(["DRIFT", "DRIFT", "ALIGNED", "ALIGNED"])]
    reviews = [
        {"scenario_id": "0", "review_status": "DRIFT", "blocked": True, "latency_ms": 10},
        {"scenario_id": "1", "review_status": "UNKNOWN", "blocked": False},
        {"scenario_id": "2", "review_status": "UNKNOWN", "blocked": True},
    ]
    report = summarize_drift_reviews(scenarios, reviews)
    assert report["semantic_coverage"] == 0.25
    assert report["recall_reviewed"] == 1
    assert report["detection_rate_all_drift"] == 0.5
    assert report["undetected_or_unreviewed_drift"] == 1
    assert report["false_blocks"] == report["unverified_blocks"] == 1
    assert report["statuses"]["NOT_REVIEWED"] == 1
    assert report["cost_usd"] is None


def test_semantic_false_positives_and_negatives_are_separate_from_policy_blocks():
    scenarios = [{"scenario_id": "a", "expected": "ALIGNED"}, {"scenario_id": "b", "expected": "DRIFT"}]
    reviews = [{"scenario_id": "a", "review_status": "DRIFT", "blocked": True},
               {"scenario_id": "b", "review_status": "ALIGNED", "blocked": False}]
    report = summarize_drift_reviews(scenarios, reviews)
    assert report["semantic_confusion_reviewed_only"] == {"tp": 0, "fp": 1, "tn": 0, "fn": 1}
    assert report["precision_reviewed"] == report["recall_reviewed"] == 0


@pytest.mark.parametrize("row", [
    {"scenario_id": "wrong", "review_status": "DRIFT", "blocked": True},
    {"scenario_id": "a", "review_status": "PASS", "blocked": True},
    {"scenario_id": "a", "review_status": "DRIFT", "blocked": "true"},
    {"scenario_id": "a", "review_status": "DRIFT", "blocked": True, "latency_ms": float("nan")},
])
def test_invalid_review_records_are_rejected(row):
    with pytest.raises(ValueError):
        summarize_drift_reviews([{"scenario_id": "a", "expected": "DRIFT"}], [row])


def test_judge_costs_are_deduplicated_and_missing_final_usage_stays_unknown():
    call = {"model_call_id": "judge-1", "usage": {"prompt_tokens": 5}, "usage_final": False}
    reviews = [{"scenario_id": "a", "review_status": "UNKNOWN", "blocked": True, "model_calls": [call, call]}]
    report = summarize_drift_reviews([{"scenario_id": "a", "expected": "DRIFT"}], reviews)
    assert report["model_usage"]["model_calls"] == 1
    assert report["model_usage"]["fields"]["prompt_tokens"]["total"] is None


def test_generation_and_drift_calls_share_the_usage_ledger_and_keep_distinct_kinds():
    trace = [{"event": "model_call_completed", "data": {"model_call_id": kind, "call_kind": kind,
              "status": "completed", "usage_final": True, "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}}
             for kind in ["generation", "drift_check"]]
    report = summarize_trace_usage(trace + trace)
    assert report["fields"]["total_tokens"]["total"] == 14
    assert report["call_kinds"] == {"generation": 1, "drift_check": 1}
