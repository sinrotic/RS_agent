"""本地七条回归报告的独立留痕校验；无模型调用或状态写回。"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/evaluation/report_request_protocol_regression.py"
spec = importlib.util.spec_from_file_location("protocol_regression", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def inputs():
    base = ROOT / ".runs/request-preview-20261011-6luna-01"
    paths = [base / "protocol-reextraction-01/reextraction-results.json",
             base / "protocol-reextraction-02/reextraction-results.json",
             base / "protocol-reextraction-02/assistant-analysis.json"]
    if not all(path.exists() for path in paths):
        pytest.skip("七条本地回归留痕未提供；不调用模型补造")
    return tuple(json.loads(path.read_text(encoding="utf-8")) for path in paths)


def test_replay_does_not_rewrite_first_run_or_model_response(inputs):
    before = copy.deepcopy(inputs)
    report = module.compare(*inputs)
    assert inputs == before
    assert report["summary"]["actual_model_calls"] == 14
    assert report["summary"]["frozen_v3_extraction_valid"] == 6
    assert report["summary"]["offline_replay_extraction_valid"] == 7
    row = next(row for row in report["entries"] if row["candidate_id"] == "synth-003-00")
    assert row["current_frozen_run"]["status"] == "quarantined"
    assert row["offline_validation_replay"]["automatic_promotion"] is False
    raw = row["current_frozen_run"]["extraction_call"]["parsed_json"]
    assert raw["unknowns"][0]["blocking_level"] == "required_for_requested_answer"
    assert row["offline_validation_replay"]["normalized_extraction"]["unknowns"] == raw["unknowns"]


def test_model_quote_false_alarm_is_distinct_from_program_evidence(inputs):
    report = module.compare(*inputs)
    row = next(row for row in report["entries"] if row["candidate_id"] == "synth-000-01")
    assert row["evidence_validation"]["all_quotes_valid"] is True
    assert row["current_frozen_run"]["model_audit"]["checks"]["extraction_fidelity"] == "fail"
    quote = row["current_frozen_run"]["extraction_call"]["parsed_json"]["answer_requirements"][1]["quote"]
    assert quote.endswith("；") and quote in row["customer_message"]


@pytest.mark.parametrize("mutation", ["message", "raw_audit", "context", "model", "count"])
def test_report_refuses_changed_inputs_or_fake_lineage(inputs, mutation):
    old, current, notes = copy.deepcopy(inputs)
    row = current["entries"][0]
    if mutation == "message":
        row["customer_message"] += "追加需求"
    elif mutation == "raw_audit":
        row["model_audit"]["checks"]["extraction_fidelity"] = "pass"
    elif mutation == "context":
        row["audit_call"]["request_payload"]["catalog"] = []
    elif mutation == "model":
        row["audit_call"]["response_metadata"]["model"] = "different-model"
    else:
        current["summary"]["model_calls"] = 16
    with pytest.raises(ValueError):
        module.compare(old, current, notes)
