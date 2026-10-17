import copy
from pathlib import Path

import pytest

from rs_core.offline.evaluation.skill_benchmark.dataset import load_benchmark
from rs_core.offline.evaluation.skill_benchmark.execution_metrics import (
    summarize_execution, summarize_model_usage,
)

pytestmark = pytest.mark.unit


def test_frozen_baseline_has_complete_families_and_is_not_quality_evidence():
    path = Path(__file__).resolve().parents[1] / "benchmarks/skill_benchmark/agent-baseline-v1.json"
    baseline = load_benchmark(path)
    assert baseline["manifest"]["human_reviewed"] is False
    assert {task["split"] for task in baseline["tasks"]} == {"train", "dev", "test"}
    assert len({task["trusted_identity"]["profile_user_id"] for task in baseline["tasks"]}) == 3
    assert all(len(task["turns"]) == 3 for task in baseline["tasks"])


def test_missing_cancelled_unknown_and_internal_transitions_stay_in_denominator():
    rows = [
        {"session_id": "s", "turn_id": str(index), "finish_reason": reason,
         "business_complete": True, "hard_gate": gate, "elapsed_ms": 10}
        for index, (reason, gate) in enumerate([
            ("FINAL_ANSWER", "passed"), ("INTERRUPTED", "passed"),
            ("FINAL_ANSWER", "unknown"), ("NEXT_TURN", "passed"),
        ])
    ]
    report = summarize_execution(rows, planned_turns=5)
    assert report["completion_rate"] == 0.2
    assert report["missing_turns"] == 1
    assert report["terminal_turns"] == 3
    assert report["first_token_ms"]["mean"] is None
    assert report["satisfaction"] is None
    with pytest.raises(ValueError, match="重复"):
        summarize_execution([rows[0], rows[0]], planned_turns=5)


def test_usage_deduplicates_export_and_counts_failed_attempts_without_zero_filling():
    success = {"model_call_id": "call-1", "status": "success",
               "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110,
                         "cache_read_input_tokens": 0}}
    failed = {"model_call_id": "call-2", "status": "error", "usage": {"prompt_tokens": 20}}
    report = summarize_model_usage([success, copy.deepcopy(success), failed])
    assert report["model_calls"] == 2
    assert report["fields"]["prompt_tokens"]["total"] == 120
    assert report["fields"]["total_tokens"]["total"] is None
    assert report["fields"]["total_tokens"]["known_subtotal"] == 110
    assert report["fields"]["cache_read_input_tokens"]["coverage"] == 0.5
    assert report["fields"]["cache_write_input_tokens"]["known_subtotal"] is None
    with pytest.raises(ValueError, match="冲突"):
        summarize_model_usage([success, {**success, "usage": {"total_tokens": 111}}])


@pytest.mark.parametrize("value", [-1, True, 2.5])
def test_usage_rejects_invalid_counters(value):
    with pytest.raises(ValueError):
        summarize_model_usage([{"model_call_id": "call", "usage": {"prompt_tokens": value}}])


def test_no_model_calls_does_not_claim_zero_cost_or_measured_tokens():
    report = summarize_model_usage([])
    assert report["fields"]["total_tokens"]["total"] is None
    assert report["cost"] is None
