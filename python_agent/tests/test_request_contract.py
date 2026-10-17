"""协议防护测试，不调用真实模型，不证明候选语义或评分校准。"""

import copy

import pytest

from rs_core.offline.evaluation.skill_benchmark.request_contract import (
    AUDIT_VERSION, DIMENSIONS, REQUEST_VERSION, strict_fact_inputs, validate_request,
)
from rs_core.offline.evaluation.skill_benchmark.request_synthesis import constraint_fact_report, validate_audit

MESSAGE = "预算三十左右，先比较安装难度。"


def request():
    return {"schema_version": REQUEST_VERSION,
            "intent": {"primary": "comparison", "actions": ["compare"], "evidence": ["先比较安装难度"]},
            "context_facts": [{"name": "comparison_axes", "value": ["安装难度"], "quote": "比较安装难度"}],
            "answer_requirements": [{"need": "比较安装难度", "quote": "先比较安装难度"}],
            "requirements": [{"id": "budget", "kind": "approximate", "field": "price", "relation": "about",
                              "value": 30, "unit": None, "quote": "预算三十左右"}],
            "unknowns": [{"slot": "device_model", "reason": "用于后续确定具体型号兼容性",
                          "needed_for": ["verify_compatibility"], "blocking_level": "needed_for_specific_item"}],
            "clarification": {"mode": "not_needed", "safe_answer_before_clarification": True, "unresolved_actions": [], "questions": []},
            "recipient": {"target": "unknown", "quote": None, "profile_policy": "not_relevant"}}


def audit():
    return {"schema_version": AUDIT_VERSION, "checks": {key: "pass" for key in DIMENSIONS},
            "reasons": {key: "测试夹具，待人工审核" for key in DIMENSIONS},
            "evidence": [{"source": "customer", "quote": MESSAGE}], "issues": []}


def test_approximate_is_not_a_hard_filter_and_input_unchanged():
    value = request()
    before = copy.deepcopy(value)
    assert validate_request(value, MESSAGE) == value
    assert strict_fact_inputs(value) == {"hard_constraints": []}
    report = constraint_fact_report([{"price": 31}], value)
    assert report["known_feasible_count"] is None
    assert report["not_evaluated_by_formula"] == value["requirements"]
    assert before == value


@pytest.mark.parametrize("relation", ["lte", "gte", "eq"])
def test_approximate_cannot_use_strict_relations(relation):
    value = request()
    value["requirements"][0]["relation"] = relation
    with pytest.raises(ValueError):
        validate_request(value, MESSAGE)


def test_tolerance_and_unknown_fields_rejected():
    value = request()
    value["requirements"][0]["tolerance"] = .1
    with pytest.raises(ValueError):
        validate_request(value, MESSAGE)


@pytest.mark.parametrize("location", ["primary", "actions", "kind", "relation", "level", "slots"])
def test_bad_container_types_fail_closed(location):
    value = request()
    if location == "primary":
        value["intent"]["primary"] = []
    elif location == "actions":
        value["intent"]["actions"] = [{}]
    elif location in {"kind", "relation"}:
        value["requirements"][0][location] = []
    elif location == "level":
        value["unknowns"][0]["blocking_level"] = []
    else:
        value["clarification"] = {"mode": "answer_then_optional_question", "safe_answer_before_clarification": True,
                                  "unresolved_actions": [],
                                  "questions": [{"question": "什么型号？", "slots": [{}],
                                                 "necessity": "optional", "reason": "后续具体核对"}]}
    with pytest.raises(ValueError):
        validate_request(value, MESSAGE)


def test_specific_item_unknown_does_not_require_question_for_general_comparison():
    assert validate_request(request(), MESSAGE)["clarification"]["mode"] == "not_needed"
    value = request()
    value["unknowns"][0]["blocking_level"] = "required_for_requested_answer"
    with pytest.raises(ValueError, match="未请求动作"):
        validate_request(value, MESSAGE)


def test_required_mode_covers_requested_action_and_all_blocking_slots():
    value = request()
    value["intent"]["actions"] = ["verify_compatibility"]
    value["unknowns"][0]["blocking_level"] = "required_for_requested_answer"
    value["clarification"] = {"mode": "required_before_answer", "safe_answer_before_clarification": False,
                              "unresolved_actions": ["verify_compatibility"],
                              "questions": [{"question": "你的设备是什么型号？", "slots": ["device_model"],
                                             "necessity": "blocking", "reason": "不能在型号未知时保证兼容"}]}
    validate_request(value, MESSAGE)
    value["clarification"]["questions"] = []
    with pytest.raises(ValueError):
        validate_request(value, MESSAGE)


def test_partial_response_does_not_turn_needed_compatibility_information_optional():
    value = request()
    value["intent"]["actions"].append("verify_compatibility")
    value["clarification"] = {"mode": "answer_partially_then_clarify", "safe_answer_before_clarification": True,
                              "unresolved_actions": ["verify_compatibility"], "questions": [
                                  {"question": "什么设备型号？", "slots": ["device_model"],
                                   "necessity": "required_for_action", "reason": "先比较，具体兼容结论需要型号"}]}
    validate_request(value, MESSAGE)
    value["clarification"]["questions"][0]["necessity"] = "optional"
    with pytest.raises(ValueError):
        validate_request(value, MESSAGE)


def test_gift_does_not_transfer_buyer_profile():
    value = request()
    value["recipient"] = {"target": "other", "quote": "先比较", "profile_policy": "weak_reference_if_self"}
    with pytest.raises(ValueError, match="收礼人"):
        validate_request(value, MESSAGE)


def test_ambiguous_quantity_field_rejected():
    value = request()
    value["requirements"][0].update(field="quantity", kind="strict", relation="eq", value=1)
    with pytest.raises(ValueError, match="数量须区分"):
        validate_request(value, MESSAGE)
    value["requirements"][0]["field"] = "purchase_quantity"
    validate_request(value, MESSAGE)  # 结构通过仍不代表语义正确。


def test_unknown_or_mixed_currency_not_evaluated_as_satisfied_price():
    value = request()
    value["requirements"][0].update(kind="strict", relation="lte")
    catalog = [{"price": 29, "currency": "CNY"}]
    assert constraint_fact_report(catalog, value)["known_feasible_count"] is None
    value["requirements"][0]["unit"] = "CNY"
    assert constraint_fact_report(catalog, value)["known_feasible_count"] == 1
    catalog.append({"price": 29, "currency": "USD"})
    assert constraint_fact_report(catalog, value)["known_feasible_count"] is None


def test_v2_and_bounded_legacy_audit_compatibility_preserve_input():
    value = audit()
    assert validate_audit(value, MESSAGE, {"catalog": [], "profile": {}}) == value
    legacy = {key: copy.deepcopy(value[key]) for key in ("checks", "evidence", "issues")}
    legacy["reason"] = copy.deepcopy(value["reasons"])
    before = copy.deepcopy(legacy)
    assert validate_audit(legacy, MESSAGE, {"catalog": [], "profile": {}}) == before
    legacy["reason"] = "原始字符串理由"
    validate_audit(legacy, MESSAGE, {"catalog": [], "profile": {}})


@pytest.mark.parametrize("bad", [{"naturalness": "漏维度"}, {key: [] for key in DIMENSIONS}, []])
def test_legacy_reason_is_not_blindly_coerced(bad):
    value = audit()
    legacy = {key: value[key] for key in ("checks", "evidence", "issues")}
    legacy["reason"] = bad
    with pytest.raises(ValueError):
        validate_audit(legacy, MESSAGE, {"catalog": [], "profile": {}})


def test_legacy_reason_compatibility_does_not_repair_bad_evidence():
    value = audit()
    value["evidence"] = [{"source": "profile", "quote": "history_meaning: past_positive_reviews_not_purchases"}]
    with pytest.raises(ValueError, match="引用"):
        validate_audit(value, MESSAGE, {"catalog": [], "profile": {"history_meaning": "past_positive_reviews_not_purchases"}})


def test_legacy_pipeline_response_is_not_promoted_by_compatibility():
    from test_request_synthesis import AUDIT, EXTRACT, Verifier, extraction, run

    class LegacyVerifier(Verifier):
        def __call__(self, prompt, payload):
            if prompt == EXTRACT:
                return extraction()
            result = super().__call__(prompt, payload)
            if prompt == AUDIT:
                result["reason"] = result.pop("reasons")
                result.pop("schema_version")
            return result

    row = run(verifier=LegacyVerifier())["entries"][0]
    assert row["status"] == "quarantined"
    assert row["quarantine_reason"] == "legacy_protocol_requires_review"
