"""原包和修订草案对应、只读留痕与禁止加样本的离线测试。"""

import copy
import importlib.util
from pathlib import Path

import pytest

from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint
from test_request_contract import request
from test_request_synthesis import run

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/evaluation/review_request_candidates.py"
spec = importlib.util.spec_from_file_location("request_candidate_review", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def inputs():
    source = run()
    message = "预算三十左右，先比较安装难度。"
    source["entries"][0]["customer_message"] = message
    proposals = {"source_pack_sha256": fingerprint(source), "entries": [{
        "candidate_id": source["entries"][0]["candidate_id"], "title": "测试对照",
        "disputes": [{"issue": "近似不能变上限", "certainty": "clear_protocol_or_semantic_issue",
                      "quote": "预算三十左右", "suggestion": "保留about"}],
        "revision_proposal": request(), "response_guidance": ["只是待人审草案"]}]}
    return source, proposals


def test_review_preserves_original_extraction_states_and_no_new_calls():
    source, proposals = inputs()
    before = copy.deepcopy((source, proposals))
    result = module.build_review(source, proposals)
    assert (source, proposals) == before
    row = result["entries"][0]
    assert row["customer_message"] == source["entries"][0]["customer_message"]
    assert row["original_validated_extraction"] == source["entries"][0]["extraction"]
    assert row["revision_status"] == "pending_human_review" and row["is_gold"] is False
    assert row["lineage"]["environment_sha256"] == source["entries"][0]["environment_sha256"]
    assert result["new_model_calls"] == 0 and result["original_statuses_modified"] is False


@pytest.mark.parametrize("mutation", ["extra", "duplicate", "missing", "wrong_source", "bad_quote"])
def test_added_missing_or_mismatched_drafts_rejected(mutation):
    source, proposals = inputs()
    if mutation == "extra":
        row = copy.deepcopy(proposals["entries"][0])
        row["candidate_id"] = "NEW"
        proposals["entries"].append(row)
    elif mutation == "duplicate":
        proposals["entries"].append(copy.deepcopy(proposals["entries"][0]))
    elif mutation == "missing":
        proposals["entries"] = []
    elif mutation == "wrong_source":
        proposals["source_pack_sha256"] = "incorrect"
    else:
        proposals["entries"][0]["disputes"][0]["quote"] = "原话中没有此句"
    with pytest.raises(ValueError):
        module.build_review(source, proposals)


def test_missing_extraction_is_not_reconstructed_as_model_output():
    source, proposals = inputs()
    row = source["entries"][0]
    row.pop("extraction")
    row.pop("raw_extraction")
    row.update(status="quarantined", failed_stage="extraction", error_type="ValueError")
    proposals["source_pack_sha256"] = fingerprint(source)
    result = module.build_review(source, proposals)["entries"][0]
    assert result["original_validated_extraction"] is None
    assert result["raw_extraction_available"] is False
    assert "不是恢复结果" in result["original_extraction_note"]


def test_generation_failure_slot_not_replaced_with_request():
    source, proposals = inputs()
    source["entries"].append({"candidate_id": "failed-slot", "status": "quarantined", "failed_stage": "generation"})
    proposals["source_pack_sha256"] = fingerprint(source)
    result = module.build_review(source, proposals)
    assert result["summary"]["original_slots"] == 2
    assert result["summary"]["existing_customer_messages"] == 1
    assert result["summary"]["added_customer_messages"] == 0
    assert result["summary"]["failed_generation_slots_not_reconstructed"] == 1


def test_diagnostic_evidence_is_not_auto_repaired_or_promoted():
    source, proposals = inputs()
    raw = source["entries"][0]["raw_model_audit"]
    raw["evidence"] = [{"source": "profile", "quote": "history_meaning: past_positive_reviews_not_purchases"}]
    proposals["source_pack_sha256"] = fingerprint(source)
    result = module.build_review(source, proposals)
    view = result["entries"][0]["original_audit_views"][0]
    assert view["current_compatibility_check"]["protocol_valid"] is False
    assert view["raw_model_audit"] == raw
    assert view["original_status_unchanged"] is True
