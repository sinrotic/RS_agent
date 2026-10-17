"""v3硬边界测试；夹具不代表真实顾客请求或独立语义标注。"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from rs_core.offline.evaluation.skill_benchmark.request_contract import validate_request
from rs_core.offline.evaluation.skill_benchmark.request_contract_v3 import evidence_report, normalize_request
from test_request_contract import MESSAGE, request


def fixture():
    value = request()
    value["schema_version"] = "rs-shopping-request/3"
    value["answer_requirements"][0]["kind"] = "comparison"
    value["recipient"]["profile_reason"] = "通用技术比较，无需购物画像"
    return value


def test_v2_still_read_only_compatible_and_v3_input_unchanged():
    legacy, current = request(), fixture()
    before = copy.deepcopy(current)
    assert validate_request(legacy, MESSAGE) == legacy
    assert validate_request(current, MESSAGE) == current
    assert current == before


def test_registered_aliases_are_logged_not_silent_repairs():
    value = fixture()
    value["requirements"][0]["field"] = "budget"
    normalized, changes = normalize_request(value)
    assert normalized["requirements"][0]["field"] == "price"
    assert changes[0]["before"]["field"] == value["requirements"][0]["field"] == "budget"
    assert changes[0]["after"]["unit"] is None
    assert validate_request(value, MESSAGE) == normalized


@pytest.mark.parametrize("unit", ["ft", "feet", "英尺"])
def test_exact_length_conversion_keeps_approximation_and_verbatim_quote(unit):
    message = "大概50英尺，先比较安装难度。"
    value = fixture()
    value["requirements"][0].update(field="cable_length", value=50, unit=unit, quote="大概50英尺")
    checked = validate_request(value, message)
    row = checked["requirements"][0]
    assert (row["field"], row["value"], row["unit"], row["relation"], row["quote"]) == ("length", 15.24, "m", "about", "大概50英尺")
    assert value["requirements"][0]["value"] == 50


@pytest.mark.parametrize("field,unit", [("length", None), ("length", "yard"), ("price", "元"),
                                      ("product_type", "m"), ("made_up_field", None)])
def test_unknown_units_or_fields_never_inferred(field, unit):
    value = fixture()
    value["requirements"][0].update(field=field, unit=unit)
    with pytest.raises(ValueError):
        validate_request(value, MESSAGE)


def test_all_bad_quotes_reported_not_repaired_and_offsets_are_exact():
    value = fixture()
    value["answer_requirements"][0]["quote"] = "先……比较"
    value["recipient"].update(target="self", quote="我自己")
    report = evidence_report(value, MESSAGE)
    assert {row["path"] for row in report["errors"]} == {"/answer_requirements/0/quote", "/recipient/quote"}
    for row in report["records"]:
        if row["valid"]:
            assert MESSAGE[row["start"]:row["end"]] == row["quote"]
    with pytest.raises(ValueError, match="recipient/quote"):
        validate_request(value, MESSAGE)
    assert value["answer_requirements"][0]["quote"] == "先……比较"


def test_literal_ellipsis_is_allowed_and_not_automatically_deleted():
    value = fixture()
    message = MESSAGE + "我……先看看"
    value["context_facts"].append({"name": "hesitation", "value": "先看", "quote": "我……先看看"})
    assert validate_request(value, message)["context_facts"][-1]["quote"] == "我……先看看"


def test_current_specific_verdict_cannot_hide_behind_optional_question():
    value = fixture()
    value["intent"]["actions"].append("verify_compatibility")
    value["answer_requirements"].append({"kind": "compatibility_verdict", "need": "核对具体组合", "quote": "先比较安装难度"})
    with pytest.raises(ValueError, match="未暂缓"):
        validate_request(value, MESSAGE)


@pytest.mark.parametrize("level", ["needed_for_specific_item", "required_for_requested_answer"])
def test_partial_clarification_defers_only_requested_verdict_and_covers_necessary_slot(level):
    value = fixture()
    value["unknowns"][0]["blocking_level"] = level
    value["intent"]["actions"].append("verify_compatibility")
    value["answer_requirements"].append({"kind": "compatibility_verdict", "need": "核对具体组合", "quote": "先比较安装难度"})
    value["clarification"] = {"mode": "answer_partially_then_clarify", "safe_answer_before_clarification": True,
        "unresolved_actions": ["verify_compatibility"], "questions": [{"question": "设备型号是什么？", "slots": ["device_model"],
        "necessity": "required_for_action", "reason": "先比较一般难度，再核对具体型号"}]}
    assert validate_request(value, MESSAGE)["clarification"]["unresolved_actions"] == ["verify_compatibility"]
    assert value["unknowns"][0]["blocking_level"] == level


def test_local_required_information_cannot_be_lost_or_changed_to_optional_question():
    value = fixture()
    value["intent"]["actions"].append("verify_compatibility")
    value["answer_requirements"].append({"kind": "compatibility_verdict", "need": "核查具体组合", "quote": "安装难度"})
    value["unknowns"][0]["blocking_level"] = "required_for_requested_answer"
    value["clarification"] = {"mode": "answer_partially_then_clarify", "safe_answer_before_clarification": True,
        "unresolved_actions": ["verify_compatibility"], "questions": [{"question": "型号？", "slots": ["device_model"],
        "necessity": "optional", "reason": "错误地改为可选"}]}
    with pytest.raises(ValueError):
        validate_request(value, MESSAGE)


def test_future_dependency_cannot_be_turned_into_current_required_slot_in_partial_mode():
    value = fixture()
    value["intent"]["actions"].append("verify_compatibility")
    value["answer_requirements"].append({"kind": "compatibility_verdict", "need": "具体核查", "quote": "安装难度"})
    value["unknowns"].append({"slot": "future_price", "reason": "仅未来推荐用", "needed_for": ["recommend"],
                              "blocking_level": "required_for_requested_answer"})
    value["clarification"] = {"mode": "answer_partially_then_clarify", "safe_answer_before_clarification": True,
        "unresolved_actions": ["verify_compatibility"], "questions": [{"question": "型号？", "slots": ["device_model"],
        "necessity": "required_for_action", "reason": "用于具体核查"}]}
    with pytest.raises(ValueError, match="未来动作"):
        validate_request(value, MESSAGE)


def test_missing_answer_kind_and_context_only_scoring_condition_are_rejected():
    value = fixture()
    value["answer_requirements"][0]["kind"] = "explanation"
    with pytest.raises(ValueError, match="回答目标"):
        validate_request(value, MESSAGE)
    value = fixture()
    value["context_facts"].append({"name": "operating_system", "value": "Windows", "quote": "安装难度"})
    with pytest.raises(ValueError, match="仅放入背景"):
        validate_request(value, MESSAGE)


def test_self_does_not_make_shopping_history_relevant_to_methods():
    value = fixture()
    value["recipient"].update(target="self", quote="先比较安装难度", profile_policy="weak_reference_if_self")
    with pytest.raises(ValueError, match="购物画像"):
        validate_request(value, MESSAGE)


def test_gift_never_transfers_giver_preferences():
    value = fixture()
    value["recipient"].update(target="other", quote="先比较安装难度", profile_policy="not_relevant")
    with pytest.raises(ValueError, match="收礼人"):
        validate_request(value, MESSAGE)


def test_revised_seven_are_same_messages_valid_and_no_strict_gift_quantity():
    base = Path(__file__).resolve().parents[1]
    script = base / "scripts/evaluation/revise_seven_request_proposals.py"
    spec = importlib.util.spec_from_file_location("seven_revisions", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    preview = base / ".runs/request-preview-20261011-6luna-01"
    if not (preview / "request-candidates.json").exists():
        pytest.skip("本地七条预览不属于可移植测试依赖")
    source = json.loads((preview / "request-candidates.json").read_text(encoding="utf-8"))
    old = json.loads((preview / "protocol-review-01/revision-proposals.json").read_text(encoding="utf-8"))
    before = copy.deepcopy(old)
    revised = module.revise(source, old)
    assert old == before and len(revised["entries"]) == 7
    gift = next(row for row in revised["entries"] if row["candidate_id"] == "synth-001-01")
    assert not any(row["field"] == "purchase_quantity" for row in gift["revision_proposal"]["requirements"])
    choice = next(row for row in revised["entries"] if row["candidate_id"] == "synth-002-01")
    assert "decision_support" in {need["kind"] for need in choice["revision_proposal"]["answer_requirements"]}
