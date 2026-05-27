from __future__ import annotations

import json

import pytest

from rs_core.rsagent.tools import (
    AGENT_CAPABILITY_MANIFEST,
    AGENT_TOOL_MANIFEST,
    BrandConstraint,
    CategoryConstraint,
    DisplayResponseDraft,
    KeywordConstraint,
    ProductSearchRequest,
    UnderstandUserNeedInput,
    UnderstandUserNeedOutput,
    catalog_constraint_search,
)

pytestmark = pytest.mark.unit

EXPECTED_INTERNAL_TOOLS = {
    "understand_user_need",
    "rerank_for_browsing",
    "match_specific_need_in_pool",
    "catalog_constraint_search",
    "build_product_reasoning",
    "compose_shopping_response",
}
BLOCKED_PUBLIC_TERMS = {
    "agent_runtime_trace",
    "runtime_trace",
    "diagnostic",
    "reward",
    "training",
    "source",
}


def test_agent_tool_manifest_contains_core_internal_tools():
    assert {tool.name for tool in AGENT_TOOL_MANIFEST} == EXPECTED_INTERNAL_TOOLS


def test_agent_tool_schema_names_have_local_contracts_for_new_tools():
    assert UnderstandUserNeedInput(user_input="推荐点耳机").to_dict()["user_input"] == "推荐点耳机"
    assert UnderstandUserNeedOutput(intent="recommend_request", action="recommend_items").to_dict()["confidence"] == 0.0
    assert DisplayResponseDraft(user_need_summary="通勤耳机").to_dict()["user_need_summary"] == "通勤耳机"


def test_agent_tool_specs_are_hidden_and_internal_except_optional_composer_payload():
    for tool in AGENT_TOOL_MANIFEST:
        assert tool.hidden is True
        assert tool.description
        assert tool.input_schema_name
        assert tool.output_schema_name
        if tool.name == "compose_shopping_response":
            assert tool.public_payload_allowed is True
        else:
            assert tool.public_payload_allowed is False


def test_agent_capability_manifest_remains_hidden_from_public_payloads():
    serialized = json.dumps([capability.__dict__ for capability in AGENT_CAPABILITY_MANIFEST], ensure_ascii=False).lower()

    for capability in AGENT_CAPABILITY_MANIFEST:
        assert capability.hidden is True
        assert capability.public_payload_allowed is False
        assert capability.name.lower() in serialized
    for term in BLOCKED_PUBLIC_TERMS:
        assert term not in serialized


def test_catalog_constraint_search_rejects_missing_price_for_relative_price_request():
    catalog = _catalog_items()
    catalog["speaker_no_price"] = {
        "item_id": "speaker_no_price",
        "title": "Bluetooth Mystery Speaker",
        "main_category": "Audio",
        "brand": "Mystery",
        "store": "Mystery Store",
        "features": ["bluetooth", "portable"],
        "rating": 4.9,
    }
    output = catalog_constraint_search(
        ProductSearchRequest(
            category=CategoryConstraint(same_as_reference=True),
            reference_item_id="speaker_ref",
            target_item_id="speaker_ref",
            constraints=[{"field": "price", "op": "lt", "reference_field": "price"}],
            limit=10,
        ),
        catalog,
    )

    assert "speaker_no_price" not in {item["item_id"] for item in output.matched_items}


def test_catalog_constraint_search_returns_cheaper_similar_item_with_grounded_reasons():
    output = catalog_constraint_search(
        ProductSearchRequest(
            query="this item is too expensive, find cheaper similar",
            category=CategoryConstraint(same_as_reference=True),
            reference_item_id="speaker_ref",
            target_item_id="speaker_ref",
            constraints=[{"field": "price", "op": "lt", "reference_field": "price"}],
            limit=3,
        ),
        _catalog_items(),
    )

    assert output.matched_items
    assert "speaker_ref" not in {item["item_id"] for item in output.matched_items}
    match = output.matched_items[0]
    assert match["price"] < _catalog_items()["speaker_ref"]["price"]
    assert match["main_category"] == _catalog_items()["speaker_ref"]["main_category"]
    reason_fields = {reason.field for reason in output.match_reasons[match["item_id"]]}
    assert "price" in reason_fields
    assert reason_fields & {"main_category", "category", "text", "title"}


def test_catalog_constraint_search_requires_bluetooth_and_penalizes_wired_items():
    output = catalog_constraint_search(
        ProductSearchRequest(
            keywords=KeywordConstraint(required=["bluetooth"], disliked=["wired"]),
            limit=3,
        ),
        _catalog_items(),
    )

    item_ids = [item["item_id"] for item in output.matched_items]
    assert item_ids
    assert all("bluetooth" in _item_text(item) for item in output.matched_items)
    if "wired_bluetooth_adapter" in item_ids:
        assert item_ids.index("speaker_budget") < item_ids.index("wired_bluetooth_adapter")
        wired_reasons = output.match_reasons["wired_bluetooth_adapter"]
        assert any(reason.reason == "disliked keyword matched" for reason in wired_reasons)


def test_catalog_constraint_search_applies_default_category_and_brand_constraints():
    category_output = catalog_constraint_search(
        ProductSearchRequest(category=CategoryConstraint(categories=["Audio"]), limit=10),
        _catalog_items(),
    )
    assert category_output.matched_items
    assert all(item["main_category"] == "Audio" for item in category_output.matched_items)

    brand_output = catalog_constraint_search(
        ProductSearchRequest(brand=BrandConstraint(brands=["RoadSound"]), limit=10),
        _catalog_items(),
    )
    assert [item["item_id"] for item in brand_output.matched_items] == ["speaker_other_store"]


def test_catalog_constraint_search_excludes_same_brand_or_store_when_requested():
    output = catalog_constraint_search(
        ProductSearchRequest(
            reference_item_id="speaker_ref",
            category=CategoryConstraint(same_as_reference=True),
            brand=BrandConstraint(not_eq_reference=True),
            constraints=[{"field": "store", "op": "not_eq_reference"}],
            limit=5,
        ),
        _catalog_items(),
    )

    assert output.matched_items
    assert all(item["brand"] != _catalog_items()["speaker_ref"]["brand"] for item in output.matched_items)
    assert all(item["store"] != _catalog_items()["speaker_ref"]["store"] for item in output.matched_items)


def test_catalog_constraint_search_keeps_required_keywords_hard():
    output = catalog_constraint_search(
        ProductSearchRequest(
            keywords=KeywordConstraint(required=["nonexistent-token"]),
            category=CategoryConstraint(categories=["Audio"]),
            limit=2,
        ),
        _catalog_items(),
        min_results=2,
    )

    assert output.matched_items == []
    assert output.diagnostics["matched_item_count"] == 0


def test_catalog_constraint_search_relaxes_narrow_soft_keywords_without_empty_result():
    output = catalog_constraint_search(
        ProductSearchRequest(
            query="rare nonexistent audiophile token",
            keywords=KeywordConstraint(preferred=["nonexistent-token"]),
            category=CategoryConstraint(categories=["Audio"]),
            limit=2,
        ),
        _catalog_items(),
        min_results=2,
    )

    assert len(output.matched_items) == 2
    assert all(item["main_category"] == "Audio" for item in output.matched_items)
    assert output.diagnostics["relaxation_level"] == 1
    assert output.diagnostics["matched_item_count"] == 2


def _catalog_items() -> dict[str, dict[str, object]]:
    return {
        "speaker_ref": {
            "item_id": "speaker_ref",
            "title": "Premium Bluetooth Speaker",
            "main_category": "Audio",
            "price": 120.0,
            "brand": "Acme",
            "store": "Acme Store",
            "features": ["bluetooth", "portable"],
            "rating": 4.7,
        },
        "speaker_budget": {
            "item_id": "speaker_budget",
            "title": "Budget Bluetooth Speaker",
            "main_category": "Audio",
            "price": 49.0,
            "brand": "Acme",
            "store": "Acme Store",
            "features": ["bluetooth", "portable"],
            "rating": 4.4,
        },
        "speaker_other_store": {
            "item_id": "speaker_other_store",
            "title": "Bluetooth Travel Speaker",
            "main_category": "Audio",
            "price": 79.0,
            "brand": "RoadSound",
            "store": "Travel Audio",
            "features": ["bluetooth", "compact"],
            "rating": 4.6,
        },
        "wired_bluetooth_adapter": {
            "item_id": "wired_bluetooth_adapter",
            "title": "Wired Bluetooth Audio Adapter",
            "main_category": "Audio",
            "price": 19.0,
            "brand": "CableCo",
            "store": "Cable Shop",
            "features": ["bluetooth", "wired"],
            "rating": 4.2,
        },
        "keyboard": {
            "item_id": "keyboard",
            "title": "Bluetooth Keyboard",
            "main_category": "Computer Accessories",
            "price": 35.0,
            "brand": "Keys",
            "store": "Office Store",
            "features": ["bluetooth"],
            "rating": 4.3,
        },
    }


def _item_text(item: dict[str, object]) -> str:
    return " ".join(str(value) for value in item.values()).lower()
