"""逐字引用诊断与对照输出的离线夹具测试。"""

import copy
import importlib.util
from pathlib import Path

from test_request_synthesis import extraction, protocol_fixture

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/evaluation/compare_request_reextraction.py"
spec = importlib.util.spec_from_file_location("request_reextraction_comparison", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_nonliteral_quotes_all_reported_without_rewriting():
    value = protocol_fixture(extraction())
    value["intent"]["evidence"] = ["给朋友挑"]
    value["answer_requirements"] = [{"need": "解释续航", "quote": "续航……我不太会看"}]
    value["recipient"] = {"target": "other", "quote": "给朋友挑……当礼物", "profile_policy": "do_not_transfer_to_recipient"}
    value["requirements"] = []
    before = copy.deepcopy(value)
    result = module.quote_errors(value, "给朋友挑耳机当礼物，续航和降噪效果我不太会看")
    assert result == [{"json_pointer": "/answer_requirements/0/quote", "quote": "续航……我不太会看"},
                      {"json_pointer": "/recipient/quote", "quote": "给朋友挑……当礼物"}]
    assert value == before


def test_literal_ellipsis_in_customer_text_is_not_banned():
    assert module.quote_errors({"quote": "想想……"}, "我想想……再说") == []


def test_intent_evidence_is_also_checked_and_null_unknown_quote_accepted():
    assert module.quote_errors({"intent": {"evidence": ["这是不存在的"]},
                                "recipient": {"quote": None}}, "顾客原话") == [
        {"json_pointer": "/intent/evidence/0", "quote": "这是不存在的"}]


def test_unavailable_original_is_not_rendered_as_empty_conditions():
    assert module.short_requirements(None, legacy=True) == "提取失败，原响应未保存"


def test_field_and_unit_differences_stay_visible_without_semantic_coercion():
    value = {"requirements": [{"kind": "approximate", "field": "cable_length", "relation": "about", "value": 50, "unit": "英尺"}]}
    before = copy.deepcopy(value)
    assert module.short_requirements(value) == "cable_length about 50 英尺"
    assert value == before
