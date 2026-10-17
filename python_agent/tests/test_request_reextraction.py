"""受控模型测试重跑隔离和真实输出留痕，不调用服务端模型。"""

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint
from test_request_synthesis import MESSAGE, Verifier, extraction, protocol_fixture, run

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/evaluation/reextract_request_candidates.py"
spec = importlib.util.spec_from_file_location("request_reextraction", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture_model(outputs=None):
    calls = []
    values = outputs if outputs is not None else [protocol_fixture(extraction()),
        Verifier()(module.AUDIT, {"customer_message": MESSAGE})]

    def call(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        value = values[len(calls) - 1]
        return {"model": "gpt-6-luna", "id": "fixture-only", "usage": {"total_tokens": 1},
                "choices": [{"message": {"content": json.dumps(value, ensure_ascii=False)}, "finish_reason": "stop"}]}

    return SimpleNamespace(model="gpt-6-luna", identity="fixture", max_tokens=6000,
                           client=SimpleNamespace(chat_completion=call)), calls


def test_original_message_only_then_current_extraction_and_original_context(tmp_path):
    original = run()["entries"][0]
    before = copy.deepcopy(original)
    model, calls = fixture_model()
    row = module.rerun_candidate(original, model, tmp_path)
    assert len(calls) == row["model_calls"] == 2
    extraction_input = json.loads(calls[0]["messages"][1]["content"])
    assert extraction_input == {"customer_message": MESSAGE}
    audit_input = json.loads(calls[1]["messages"][1]["content"])
    assert set(audit_input) == {"customer_message", "extraction", "catalog", "profile", "price_unit"}
    assert audit_input["extraction"] == row["extraction"]
    assert audit_input["catalog"] == original["context"]["catalog"]
    assert original == before
    assert row["status"] == "pending_independent_human_review" and row["is_gold"] is False
    assert row["human_reviews"] == []
    assert (tmp_path / original["candidate_id"] / "extraction-call.json").exists()
    assert row["extraction_call"]["raw_content"] == json.dumps(protocol_fixture(extraction()), ensure_ascii=False)


def test_bad_schema_kept_raw_and_can_be_audited_without_automatic_fix(tmp_path):
    raw = protocol_fixture(extraction())
    raw["requirements"][0]["quote"] = "这句不存在"
    model, calls = fixture_model([raw, Verifier()(module.AUDIT, {"customer_message": MESSAGE})])
    row = module.rerun_candidate(run()["entries"][0], model, tmp_path)
    assert row["extraction_protocol_valid"] is False and len(calls) == 2
    assert row["extraction_call"]["parsed_json"] == raw
    assert json.loads(calls[1]["messages"][1]["content"])["extraction"] == raw
    assert row["status"] == "quarantined"


def test_call_failure_sanitized_and_no_retry(tmp_path):
    model, calls = fixture_model()
    def broken(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("SECRET_TOKEN_DO_NOT_SAVE")
    model.client.chat_completion = broken
    row = module.rerun_candidate(run()["entries"][0], model, tmp_path)
    assert row["model_calls"] == len(calls) == 1
    assert "SECRET_TOKEN_DO_NOT_SAVE" not in json.dumps(row)
    assert row["audit_protocol_valid"] is None
    assert row["status"] == "quarantined"


def test_invalid_json_raw_content_retained_without_retry(tmp_path):
    model, calls = fixture_model()
    def malformed(**kwargs):
        calls.append(kwargs)
        return {"model": "gpt-6-luna", "choices": [{"message": {"content": "{unfinished"}, "finish_reason": "length"}]}
    model.client.chat_completion = malformed
    row = module.rerun_candidate(run()["entries"][0], model, tmp_path)
    assert row["extraction_call"]["raw_content"] == "{unfinished"
    assert row["extraction_call"]["error_type"] == "JSONDecodeError"
    assert len(calls) == 1


def test_new_run_cannot_accept_legacy_audit_as_new_protocol(tmp_path):
    raw = Verifier()(module.AUDIT, {"customer_message": MESSAGE})
    raw["reason"] = raw.pop("reasons")
    raw.pop("schema_version")
    model, _ = fixture_model([protocol_fixture(extraction()), raw])
    row = module.rerun_candidate(run()["entries"][0], model, tmp_path)
    assert row["audit_protocol_valid"] is False
    assert row["status"] == "quarantined"


@pytest.mark.parametrize("bad", ["model", "finish_reason"])
def test_unexpected_model_or_truncated_completion_never_promoted(tmp_path, bad):
    model, _ = fixture_model()
    original_call = model.client.chat_completion
    def changed(**kwargs):
        response = original_call(**kwargs)
        if bad == "model":
            response["model"] = "other-model"
        else:
            response["choices"][0]["finish_reason"] = "length"
        return response
    model.client.chat_completion = changed
    row = module.rerun_candidate(run()["entries"][0], model, tmp_path)
    assert row["status"] == "quarantined"


def test_preflight_exactly_seven_verbatim_requests():
    source = run()
    base = source["entries"][0]
    source["entries"] = [dict(copy.deepcopy(base), candidate_id=f"synth-{i:03d}-00") for i in range(7)]
    review = {"source_pack_sha256": fingerprint(source), "is_gold": False,
              "entries": [{"candidate_id": row["candidate_id"], "customer_message": MESSAGE,
                           "original_validated_extraction": copy.deepcopy(row["extraction"]),
                           "original_status": row["status"]} for row in source["entries"]]}
    assert len(module.select_existing(source, review)) == 7
    source["entries"].append(dict(copy.deepcopy(base), candidate_id="extra"))
    review["source_pack_sha256"] = fingerprint(source)
    with pytest.raises(ValueError):
        module.select_existing(source, review)


def test_three_way_comparison_does_not_claim_semantic_agreement():
    new = protocol_fixture(extraction())
    row = {"extraction_protocol_valid": True, "extraction": new, "extraction_call": {"parsed_json": new}}
    draft = copy.deepcopy(new)
    draft["requirements"][0]["field"] = "budget"
    result = module.compare_with_review(row, {"revision_proposal": draft})
    assert result["strict_approximate_signatures_equal"] is False
    assert "not_semantic" in result["comparison_scope"]
