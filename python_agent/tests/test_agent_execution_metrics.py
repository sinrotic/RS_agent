import copy
from pathlib import Path

import pytest

from rs_core.offline.evaluation.skill_benchmark.dataset import load_benchmark, fingerprint
from rs_core.offline.evaluation.skill_benchmark.execution_metrics import (
    summarize_execution, summarize_model_usage, summarize_trace_usage,
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


def test_trace_ledger_tracks_started_only_calls_and_never_adds_stream_snapshots():
    trace = [
        {"event": "model_call_started", "data": {"model_call_id": "a"}},
        {"event": "model_usage", "data": {"total_tokens": 20}},
        {"event": "model_call_completed", "data": {"model_call_id": "a", "status": "completed",
         "usage_final": True, "usage": {"total_tokens": 20}}},
        {"event": "model_call_started", "data": {"model_call_id": "b"}},
    ]
    report = summarize_trace_usage(trace + [trace[2]])
    assert report["model_calls"] == 2
    assert report["completed_observations"] == 1
    assert report["fields"]["total_tokens"]["total"] is None
    assert report["fields"]["total_tokens"]["known_subtotal"] == 20


def test_nonfinal_usage_stays_a_known_subtotal_instead_of_a_full_total():
    report = summarize_model_usage([{"model_call_id": "early-stop", "usage_final": False,
                                     "usage": {"prompt_tokens": 20, "total_tokens": 25}}])
    assert report["fields"]["total_tokens"]["total"] is None
    assert report["fields"]["total_tokens"]["known_subtotal"] == 25
    assert report["fields"]["total_tokens"]["finalized_calls"] == 0


def test_benchmark_persists_call_ledger_even_when_model_attempt_failed():
    from rs_core.offline.evaluation.skill_benchmark.runner import run_benchmark

    catalog = [{"item_id": "a", "price": 10}]
    benchmark = {"schema_version": "rs-skill-benchmark/1", "catalog": catalog, "environment": {},
                 "manifest": {"catalog_sha256": fingerprint(catalog)},
                 "tasks": [{"task_id": "task", "family_id": "family", "kind": "base", "split": "dev",
                            "turns": [{"user_message": "预算20元以内", "limit": 1,
                                       "gold": {"k": 1, "hard": [{"field": "price", "op": "lte", "value": 20}]}}]}]}
    def adapter(request):
        return {"turns": [{"item_ids": [], "outcome": "invalid_output", "status": "failed"}],
                "trace": [{"event": "model_call_started", "data": {"model_call_id": "failed-call"}},
                          {"event": "model_call_completed", "data": {"model_call_id": "failed-call",
                           "status": "error", "usage_final": False, "usage": {}}}]}
    run = run_benchmark(benchmark, adapter, {"adapter_kind": "engineering_only"})
    assert run["trials"][0]["model_usage"]["model_calls"] == 1
    assert run["trials"][0]["model_usage"]["fields"]["total_tokens"]["total"] is None
    assert run["summary"]["execution_failures"] == 1


def test_trace_versions_keep_call_association_and_do_not_infer_missing_metadata():
    metadata = {"fingerprint_schema_version": "rs-agent-model-request-fingerprint/1",
                "fingerprint_status": "observed", "fingerprint_scope": "spring_ai_prepared_request",
                "request_sha256": "a" * 64, "tools_sha256": "b" * 64,
                "prompt": "private-body", "declared_model_sha256": "invalid"}
    completed = {"event": "model_call_completed", "data": {
        "model_call_id": "a", "status": "completed", "usage": {"total_tokens": 10}, "usage_final": True, **metadata}}
    trace = [completed, copy.deepcopy(completed), {"event": "model_call_started", "data": {"model_call_id": "b"}}]
    report = summarize_trace_usage(trace)
    coverage = report["fingerprint_coverage"]
    assert coverage["model_calls"] == 2
    assert coverage["observed_calls"] == 1
    assert coverage["statuses"] == {"observed": 1, "not_reported": 1}
    assert coverage["fields_observed_calls"]["tools_sha256"] == 1
    assert coverage["fields_observed_calls"]["declared_model_sha256"] == 0
    assert report["request_fingerprints"][0]["tools_sha256"] == "b" * 64
    assert "prompt" not in report["request_fingerprints"][0]
    assert "declared_model_sha256" not in report["request_fingerprints"][0]
    changed = copy.deepcopy(completed)
    changed["data"]["request_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="冲突"):
        summarize_trace_usage([completed, changed])


@pytest.mark.parametrize("metadata", [
    {}, {"fingerprint_status": "conflict"},
    {"fingerprint_status": "observed", "request_sha256": "fake"},
    {"fingerprint_status": "unknown-version"},
    {"fingerprint_status": []},
    {"fingerprint_status": "observed", "fingerprint_schema_version": "rs-agent-model-request-fingerprint/1",
     "fingerprint_scope": {}, "request_sha256": "a" * 64},
])
def test_unavailable_or_malformed_versions_do_not_change_usage_results(metadata):
    report = summarize_trace_usage([{"event": "model_call_completed", "data": {
        "model_call_id": "a", "status": "completed", "usage": {"total_tokens": 10}, "usage_final": True, **metadata}}])
    assert report["fields"]["total_tokens"]["total"] == 10
    assert report["fingerprint_coverage"]["observed_calls"] == 0
