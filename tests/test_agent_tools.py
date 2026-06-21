from __future__ import annotations

import json

import pytest

from rs_core.rsagent.dialogue import plan_dialogue_turn
from rs_core.rsagent.schema import AgentSession
from rs_core.rsagent.tools import (
    AGENT_CAPABILITY_MANIFEST,
    AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT,
    AGENT_TOOL_MANIFEST,
    AgentToolCall,
    AgenticRecallRequest,
    BrandConstraint,
    BuildRecommendationSlateInput,
    BuildRecommendationSlateOutput,
    CategoryConstraint,
    DeepFMRankRequest,
    DisplayResponseDraft,
    GetItemEvidenceInput,
    GetItemEvidenceOutput,
    GetUserContextInput,
    GetUserContextOutput,
    KeywordConstraint,
    ProductSearchRequest,
    QueryRagInput,
    QueryRagOutput,
    RankCandidatesInput,
    RankCandidatesOutput,
    RecallConstraints,
    RecallDiversityPolicy,
    RecallIntent,
    RecallPathPlan,
    RecallProfilePolicy,
    RecallRetrievalSummary,
    RecallRouteDecision,
    RecallRoutePolicy,
    RecordUserFeedbackInput,
    RecordUserFeedbackOutput,
    RetrieveCandidatesInput,
    RetrieveCandidatesOutput,
    UnderstandUserNeedInput,
    UnderstandUserNeedOutput,
    agentic_recall_candidates,
    build_agent_tool_planner_system_prompt,
    build_target_conditioned_catalog_text,
    catalog_constraint_search,
    collect_diagnostic_tool_events,
    deepfm_rank_candidates,
    normalize_agent_tool_calls,
    validate_agent_tool_call,
    validate_rank_candidates_arguments,
)

pytestmark = pytest.mark.unit

EXPECTED_CORE_TOOLS = {
    "get_user_context",
    "query_rag",
    "retrieve_candidates",
    "rank_candidates",
    "get_item_evidence",
    "record_user_feedback",
    "build_recommendation_slate",
}
PUBLIC_PAYLOAD_TOOLS = {"build_recommendation_slate"}
BLOCKED_PUBLIC_TERMS = {
    "agent_runtime_trace",
    "runtime_trace",
    "diagnostic",
    "reward",
    "training",
    "source",
}


def test_agent_tool_manifest_contains_core_business_tools():
    assert {tool.name for tool in AGENT_TOOL_MANIFEST} == EXPECTED_CORE_TOOLS


def test_agent_tool_schema_names_have_local_contracts_for_new_tools():
    assert GetUserContextInput(session_id="s1").to_dict()["include_recent_turns"] == 3
    assert GetUserContextOutput(session_id="s1", user_id="u1").to_dict()["turn_count"] == 0
    query_rag_payload = QueryRagInput(query="通勤耳机", fields=["title"]).to_dict()
    assert query_rag_payload["purpose"] == "query_planning"
    assert query_rag_payload["scope"] == "catalog_knowledge"
    assert query_rag_payload["fields"] == ["title"]
    assert QueryRagOutput(semantic_query_hint="通勤 蓝牙").to_dict()["semantic_query_hint"] == "通勤 蓝牙"
    retrieve_payload = RetrieveCandidatesInput(
        query="通勤耳机",
        target_pool_size=500,
        intent=RecallIntent(scenario="commute", need_specificity="specific"),
        profile_policy=RecallProfilePolicy(use_current_query=True, use_recent_history=True),
        route_policy=RecallRoutePolicy(semantic="hybrid_query_history", similar_item="auto", user_neighbor="auto"),
        constraints=RecallConstraints(preferred_keywords=["bluetooth"]),
        diversity=RecallDiversityPolicy(source_balance="balanced"),
        limit=50,
        semantic_mode="hybrid_query_history",
    ).to_dict()
    assert retrieve_payload["target_pool_size"] == 500
    assert retrieve_payload["retrieval_mode"] == "auto"
    assert retrieve_payload["profile_usage"] == "balanced"
    assert retrieve_payload["expansion_policy"] == "balanced"
    assert retrieve_payload["reference_item_id"] is None
    assert retrieve_payload["route_policy"]["semantic"] == "hybrid_query_history"
    assert retrieve_payload["constraints"]["preferred_keywords"] == ["bluetooth"]
    assert retrieve_payload["limit"] == 50
    assert retrieve_payload["semantic_mode"] == "hybrid_query_history"
    assert retrieve_payload["use_history_profile"] is True
    retrieve_output = RetrieveCandidatesOutput(
        candidate_item_ids=["i1"],
        retrieval_summary=RecallRetrievalSummary(target_pool_size=500, returned_count=1),
        route_decisions=[RecallRouteDecision(route="semantic", status="used", eligible=True, returned_count=1)],
    ).to_dict()
    assert retrieve_output["candidate_count"] == 0
    assert retrieve_output["retrieval_summary"]["schema_version"] == "retrieve_candidates_output_v3"
    assert retrieve_output["retrieval_summary"]["retrieval_mode"] == "auto"
    assert retrieve_output["retrieval_summary"]["profile_usage"] == "balanced"
    assert retrieve_output["retrieval_summary"]["expansion_policy"] == "balanced"
    assert retrieve_output["route_decisions"][0]["route"] == "semantic"
    assert RankCandidatesInput(candidate_item_ids=["i1"], return_top_k=1).to_dict()["return_top_k"] == 1
    assert RankCandidatesOutput(ranked_item_ids=["i1"]).to_dict()["ranked_item_count"] == 0
    assert GetItemEvidenceInput(item_ids=["i1"]).to_dict()["max_evidence_per_item"] == 3
    assert GetItemEvidenceOutput(evidence={"i1": [{"field": "title", "text": "耳机"}]}).to_dict()["item_count"] == 0
    assert RecordUserFeedbackInput(action_type="like", item_id="i1").to_dict()["item_id"] == "i1"
    assert RecordUserFeedbackOutput(applied=True).to_dict()["applied"] is True
    assert BuildRecommendationSlateInput(max_items=2).to_dict()["max_items"] == 2
    assert BuildRecommendationSlateOutput(display={"items": []}).to_dict()["item_count"] == 0
    assert UnderstandUserNeedInput(user_input="推荐点耳机").to_dict()["user_input"] == "推荐点耳机"
    assert UnderstandUserNeedOutput(intent="recommend_request", action="recommend_items").to_dict()["confidence"] == 0.0
    assert DisplayResponseDraft(user_need_summary="通勤耳机").to_dict()["user_need_summary"] == "通勤耳机"
    assert AgenticRecallRequest(user_id="u1", paths=[RecallPathPlan(name="constraint_catalog_search")]).to_dict()["paths"][0]["name"] == "constraint_catalog_search"
    assert DeepFMRankRequest(user_id="u1", return_top_k=2).to_dict()["return_top_k"] == 2


def test_agent_tool_specs_are_hidden_with_only_slate_public_payload_allowed():
    for tool in AGENT_TOOL_MANIFEST:
        assert tool.hidden is True
        assert tool.description
        assert tool.input_schema_name
        assert tool.output_schema_name
        assert tool.public_payload_allowed is (tool.name in PUBLIC_PAYLOAD_TOOLS)


def test_query_rag_declares_optional_planning_boundaries():
    tool = next(tool for tool in AGENT_TOOL_MANIFEST if tool.name == "query_rag")

    assert tool.stage == "query_planning"
    assert tool.read_only is True
    assert tool.hidden is True
    assert tool.public_payload_allowed is False
    assert tool.requires_candidate_pool is False
    assert tool.can_search_catalog is True
    assert tool.uses_rag_evidence is True
    assert tool.routing_attributes["available_phase"] == "pre_recommendation"
    assert tool.routing_attributes["candidate_pool_required"] is False
    assert "concept_completion" in tool.routing_attributes["uses"]
    assert "synonym_expansion" in tool.routing_attributes["uses"]
    assert "query_rewrite_support" in tool.routing_attributes["uses"]
    assert "concept completion" in tool.boundary_prompt
    assert "attribute expansion" in tool.boundary_prompt
    assert "scenario" in tool.boundary_prompt
    assert "synonym" in tool.boundary_prompt
    assert "category knowledge" in tool.boundary_prompt
    assert "query rewrite" in tool.boundary_prompt
    assert "never use query_rag as a replacement" in tool.boundary_prompt
    assert "optionally call query_rag before retrieve_candidates" in AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT


def test_agent_tool_planner_system_prompt_payload_contains_hidden_tool_boundaries():
    prompt = build_agent_tool_planner_system_prompt()

    assert prompt.startswith(AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT)
    assert "retrieve_candidates" in prompt
    assert "query_rag" in prompt
    assert "retrieval_mode" in prompt
    assert "reference_item_id" in prompt
    assert "never use query_rag as a replacement" in prompt
    assert "concept completion" in prompt
    assert "attribute expansion" in prompt
    assert "query rewrite" in prompt
    assert "Ask a clarifying question before retrieval only when" in prompt
    assert "After candidates are ranked" in prompt
    assert "must not add new candidates" in prompt
    assert "must not change ranking" in prompt
    assert "tool traces" in prompt
    assert "public_payload_allowed" in prompt
    assert "public_output" in prompt


def test_get_item_evidence_declares_post_ranking_grounding_boundary():
    tool = next(tool for tool in AGENT_TOOL_MANIFEST if tool.name == "get_item_evidence")

    assert tool.stage == "evidence"
    assert tool.requires_candidate_pool is True
    assert "after retrieval and ranking" in tool.boundary_prompt
    assert "ground explanations" in tool.boundary_prompt
    assert "must not add new candidates" in tool.boundary_prompt
    assert "change ranking" in tool.boundary_prompt
    assert "raw RAG/source diagnostics" in tool.boundary_prompt


def test_retrieve_candidates_declares_business_mode_boundaries():
    tool = next(tool for tool in AGENT_TOOL_MANIFEST if tool.name == "retrieve_candidates")

    assert tool.routing_attributes["llm_visible_policy"]["retrieval_mode"] == [
        "auto",
        "specific_need",
        "personalized_feed",
        "broad_browse",
        "similar_to_item",
        "reference_with_constraints",
    ]
    assert tool.routing_attributes["llm_visible_policy"]["profile_usage"] == ["none", "light", "balanced", "strong"]
    assert tool.routing_attributes["llm_visible_policy"]["expansion_policy"] == ["none", "narrow", "balanced", "broad"]
    assert "reference_item_id" in tool.routing_attributes["llm_visible_policy"]
    assert "semantic_participation" in tool.routing_attributes
    assert tool.routing_attributes["internal_output"] == "business_route_decisions_allowed_without_scores_or_lineage"
    assert "retrieval_mode" in tool.boundary_prompt
    assert "reference_item_id" in tool.boundary_prompt
    assert "semantic acquisition" in tool.boundary_prompt
    assert "do not choose provider names" in tool.boundary_prompt
    assert "never public scores" in tool.boundary_prompt
    assert "retrieval_mode/profile_usage/expansion_policy" in AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT
    assert "tool traces" in AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT


def test_dialogue_plan_passes_business_mode_boundary_to_retrieve_candidates():
    plan = plan_dialogue_turn("For commute, prefer bluetooth speaker", AgentSession(session_id="s1", user_id="u1"))

    tool_names = [call["name"] for call in plan.tool_calls]
    assert tool_names == [
        "get_user_context",
        "query_rag",
        "retrieve_candidates",
        "rank_candidates",
        "get_item_evidence",
        "build_recommendation_slate",
    ]
    query_rag_call = next(call for call in plan.tool_calls if call["name"] == "query_rag")
    assert query_rag_call["arguments"] == {"query": "For commute, prefer bluetooth speaker", "purpose": "query_planning"}

    retrieve_call = next(call for call in plan.tool_calls if call["name"] == "retrieve_candidates")
    arguments = retrieve_call["arguments"]

    assert arguments["retrieval_mode"] == "specific_need"
    assert arguments["profile_usage"] == "balanced"
    assert arguments["expansion_policy"] == "balanced"
    assert arguments["target_pool_size"] == 500
    assert arguments["reference_item_id"] is None
    assert arguments["semantic_mode"] == "hybrid_query_history"
    assert arguments["use_history_profile"] is True
    assert arguments["use_behavioral_recall"] is True
    assert arguments["profile_policy"] == {"use_current_query": True, "use_recent_history": True, "history_weight": "balanced"}
    assert arguments["route_policy"] == {
        "semantic": "hybrid_query_history",
        "similar_item": "auto",
        "user_neighbor": "auto",
        "behavioral": "auto",
        "fallback": "auto",
    }
    assert arguments["query"] == "For commute, prefer bluetooth speaker"


def test_agent_capability_manifest_matches_tool_public_payload_policy():
    serialized = json.dumps([capability.__dict__ for capability in AGENT_CAPABILITY_MANIFEST], ensure_ascii=False).lower()

    assert {capability.name for capability in AGENT_CAPABILITY_MANIFEST} == EXPECTED_CORE_TOOLS
    for capability in AGENT_CAPABILITY_MANIFEST:
        assert capability.hidden is True
        assert capability.public_payload_allowed is (capability.name in PUBLIC_PAYLOAD_TOOLS)
        assert capability.name.lower() in serialized
    for term in BLOCKED_PUBLIC_TERMS:
        assert term not in serialized


def test_normalize_agent_tool_calls_accepts_strings_dicts_and_lists():
    calls = normalize_agent_tool_calls([
        "get_user_context",
        {"tool_name": "retrieve_candidates", "arguments": {"limit": 3}, "phase": "pre_recommendation"},
        {"requested_tools": [{"name": "build_recommendation_slate"}]},
    ])

    assert [call.name for call in calls] == [
        "get_user_context",
        "retrieve_candidates",
        "build_recommendation_slate",
    ]
    assert calls[1].arguments == {"limit": 3}
    assert calls[1].phase == "pre_recommendation"


def test_validate_agent_tool_call_reports_unknown_intent_and_phase_reasons():
    assert validate_agent_tool_call(AgentToolCall("missing_tool"), "recommend_request", "post_recommendation") == "unknown_tool"
    assert validate_agent_tool_call(AgentToolCall("retrieve_candidates"), "unsupported", "pre_recommendation") == "intent_not_allowed"
    assert validate_agent_tool_call(AgentToolCall("query_rag"), "recommend_request", "pre_recommendation") is None
    assert validate_agent_tool_call(AgentToolCall("rank_candidates"), "recommend_request", "pre_recommendation") == "candidate_pool_not_available"


def test_agent_tool_events_are_collected_from_diagnostics():
    events = collect_diagnostic_tool_events({"agent_tool_events": [{"tool_name": "understand_user_need", "status": "ok"}]})

    assert events == [{"tool_name": "understand_user_need", "status": "ok"}]


def test_validate_rank_candidates_arguments_normalizes_allowlisted_fields():
    validation = validate_rank_candidates_arguments({
        "candidate_item_ids": [" a ", "", None, "a", 7],
        "candidates": [{"item_features": {"parent_asin": "b"}}],
        "return_top_k": "3",
        "ranking_context": {"query": "bluetooth"},
    })

    assert validation.valid is True
    assert validation.normalized_arguments["candidate_item_ids"] == ["a", "7"]
    assert validation.normalized_arguments["return_top_k"] == 3
    assert validation.normalized_arguments["candidates"] == [{"item_features": {"parent_asin": "b"}}]
    assert validation.diagnostics == {"compact": True, "internal_only": True, "public_payload_allowed": False}


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ([], "invalid_rank_candidates_arguments_type"),
        ({"unexpected": 1}, "invalid_rank_candidates_arguments_unknown_fields"),
        ({"return_top_k": True}, "invalid_rank_candidates_return_top_k_type"),
        ({"return_top_k": 1.5}, "invalid_rank_candidates_return_top_k_type"),
        ({"return_top_k": "1.5"}, "invalid_rank_candidates_return_top_k_type"),
        ({"return_top_k": 0}, "invalid_rank_candidates_return_top_k_range"),
        ({"return_top_k": 501}, "invalid_rank_candidates_return_top_k_range"),
        ({"candidate_item_ids": "a"}, "invalid_rank_candidates_candidate_item_ids_type"),
        ({"candidates": {}}, "invalid_rank_candidates_candidates_type"),
        ({"candidates": ["a"]}, "invalid_rank_candidates_candidate_entry_type"),
        ({"candidates": [{"title": "missing id"}]}, "invalid_rank_candidates_candidate_entry_type"),
        ({"ranking_context": []}, "invalid_rank_candidates_ranking_context_type"),
    ],
)
def test_validate_rank_candidates_arguments_rejects_invalid_inputs(arguments, reason):
    validation = validate_rank_candidates_arguments(arguments)

    assert validation.valid is False
    assert validation.reason == reason
    assert validation.diagnostics["compact"] is True
    assert validation.diagnostics["internal_only"] is True
    assert validation.diagnostics["public_payload_allowed"] is False


def test_agentic_recall_candidates_respects_path_top_k_and_global_rules():
    output = agentic_recall_candidates(
        AgenticRecallRequest(
            user_id="u1",
            target_pool_size=3,
            global_rules={
                "dedupe_by_parent_asin": True,
                "must_satisfy": [{"field": "category", "op": "in", "values": ["Audio"]}],
                "must_not_satisfy": [{"field": "brand", "op": "in", "values": ["CableCo"]}],
            },
            paths=[
                RecallPathPlan(
                    name="constraint_catalog_search",
                    limit=4,
                    top_k=2,
                    rules=[{"field": "keyword", "op": "preferred", "values": ["bluetooth"]}],
                    reason="audio bluetooth path",
                ),
                RecallPathPlan(name="semantic_intent_search", limit=4, top_k=2, query="portable bluetooth"),
            ],
            ranking_context={"intent_type": "portable bluetooth audio"},
        ),
        _catalog_items(),
    )

    item_ids = [candidate.item_id for candidate in output.candidates]
    assert 1 <= len(item_ids) <= 3
    assert len(item_ids) == len(set(item_ids))
    assert "keyboard" not in item_ids
    assert "wired_bluetooth_adapter" not in item_ids
    assert all(candidate.acquisition_path in {"constraint_catalog_search", "semantic_intent_search"} for candidate in output.candidates)
    assert all(candidate.source_rank <= 2 for candidate in output.candidates)
    assert all(candidate.item_features["target_conditioned_catalog_text"] for candidate in output.candidates)



def test_agentic_recall_candidates_dedupes_parent_asin_and_enforces_source_budget():
    catalog = _catalog_items()
    catalog["speaker_budget_variant"] = {
        **catalog["speaker_budget"],
        "item_id": "speaker_budget_variant",
        "parent_asin": "parent_speaker_budget",
        "price": 45.0,
        "sources": ["semantic"],
    }
    catalog["speaker_budget"]["parent_asin"] = "parent_speaker_budget"
    catalog["speaker_budget"]["sources"] = ["semantic"]
    catalog["speaker_other_store"]["sources"] = ["semantic"]

    output = agentic_recall_candidates(
        AgenticRecallRequest(
            user_id="u1",
            target_pool_size=5,
            global_rules={"dedupe_by_parent_asin": True},
            paths=[RecallPathPlan(
                name="semantic_intent_search",
                limit=5,
                top_k=5,
                query="bluetooth",
                sources=["semantic"],
                source_budgets={"semantic": 1},
            )],
        ),
        catalog,
    )

    parent_ids = [candidate.item_features.get("parent_asin") for candidate in output.candidates]
    assert parent_ids.count("parent_speaker_budget") <= 1
    assert len(output.candidates) == 1
    assert output.diagnostics["paths"][0]["source_counts"] == {"semantic": 1}



def test_agentic_recall_candidates_supports_cheaper_alternative_path():
    output = agentic_recall_candidates(
        AgenticRecallRequest(
            user_id="u1",
            target_pool_size=5,
            paths=[RecallPathPlan(
                name="cheaper_alternative_search",
                limit=5,
                top_k=5,
                reference_item_id="speaker_ref",
                target_item_id="speaker_ref",
            )],
        ),
        _catalog_items(),
    )

    item_ids = {candidate.item_id for candidate in output.candidates}
    assert "speaker_ref" not in item_ids
    assert item_ids
    assert all(_catalog_items()[item_id]["price"] < _catalog_items()["speaker_ref"]["price"] for item_id in item_ids)



def test_rank_candidates_compact_output_does_not_leak_deepfm_internals():
    output = RankCandidatesOutput(ranked_item_ids=["i1"], ranking_summary={"ranker": "facade"}).to_dict()
    payload = json.dumps(output, ensure_ascii=False)

    assert "feature_rows" not in payload
    assert "deepfm_score" not in payload


def test_deepfm_rank_candidates_returns_top_k_with_feature_rows():
    recall_output = agentic_recall_candidates(
        AgenticRecallRequest(
            user_id="u1",
            session_id="s1",
            target_pool_size=4,
            paths=[RecallPathPlan(name="constraint_catalog_search", limit=4, top_k=4, query="bluetooth portable")],
            ranking_context={"intent_type": "bluetooth portable"},
        ),
        _catalog_items(),
    )

    output = deepfm_rank_candidates(DeepFMRankRequest(
        user_id="u1",
        session_id="s1",
        return_top_k=2,
        ranking_context={"intent_type": "bluetooth portable"},
        candidates=[candidate.to_dict() for candidate in recall_output.candidates],
    ))

    assert len(output.ranked_items) == 2
    assert len(output.feature_rows) == len(recall_output.candidates)
    assert output.ranked_items[0]["deepfm_score"] >= output.ranked_items[1]["deepfm_score"]
    assert all(row.target_conditioned_catalog_text for row in output.feature_rows)



def test_target_conditioned_catalog_text_keeps_listing_style_and_target():
    text = build_target_conditioned_catalog_text(_catalog_items()["speaker_budget"], {"intent_type": "commute bluetooth"})

    assert "Product: Budget Bluetooth Speaker" in text
    assert "Category: Audio" in text
    assert "Target fit: commute bluetooth" in text



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
